"""Split-ramp covariance and its uncertainty for a fixed sensor population."""

from __future__ import annotations

import dataclasses
import enum
import math

import numpy as np
from scipy.special import stdtrit


class DispersionStatus(enum.Enum):
    """Resolution of the intrinsic SD, independently of the observed SD."""

    RESOLVED = "Resolved on the reserved-frame population"
    UNRESOLVED = "Not resolved: the covariance interval includes zero"
    NEGATIVE_INTERVAL = "Not resolved: the covariance interval is entirely negative"
    TOO_FEW_REPEATS = "Not measurable: need at least four repeats at every exposure"
    TOO_FEW_PIXELS = "Not measurable: fewer than two selected pixels"
    MEASUREMENT_RAIL = "Not measurable: a selected pixel reached a rail in a fit frame"
    TOO_FEW_BLOCKS = "Not measurable: fewer than 16 populated spatial blocks"
    NO_CONTRAST = "Not measurable: no between-map contrast for uncertainty"
    CONCENTRATED = "Not measurable: too few blocks carry the uncertainty"


@dataclasses.dataclass(frozen=True)
class IntrinsicDarkDispersion:
    """Signed variance evidence in (LSB/s)²; SD only when resolved."""

    status: DispersionStatus
    frames_per_level: tuple[int, ...]
    block_side: int
    pixel_mask: np.ndarray | None = None
    pilot_rail_pixels: int | None = None
    pilot_hot_pixels: int | None = None
    fit_rail_pixels: int | None = None
    block_count: int | None = None
    effective_blocks: float | None = None
    covariance: float = math.nan
    covariance_ci95: tuple[float, float] = (math.nan, math.nan)

    @property
    def split_counts(self) -> tuple[tuple[int, int, int], ...]:
        """Return (reserved, A, B) frame counts at each exposure in order."""
        if min(self.frames_per_level) < 4:
            return ()
        halves = [(n - 2) // 2 for n in self.frames_per_level]
        return tuple((n - 2 * h, h, h) for n, h in zip(self.frames_per_level, halves))

    @property
    def pixel_count(self) -> int | None:
        """Return None if selection could not be made, not an empty population."""
        if self.pixel_mask is None:
            return None
        return int(np.count_nonzero(self.pixel_mask))

    @property
    def sd_dn_per_s(self) -> float:
        """Do not turn signed or unresolved covariance into a measured SD."""
        if self.status is DispersionStatus.RESOLVED:
            return math.sqrt(self.covariance)
        return math.nan

    @property
    def sd_ci95(self) -> tuple[float, float]:
        """Transform the physical part of the interval, never claim [0, 0]."""
        low, high = self.covariance_ci95
        if high > 0.0:
            return math.sqrt(max(0.0, low)), math.sqrt(high)
        return math.nan, math.nan


def _tile_sums(values: np.ndarray, side: int) -> np.ndarray:
    """Sum rectangular tiles, retaining partial edge tiles and mask holes."""
    rows = np.add.reduceat(values, np.arange(0, values.shape[0], side), axis=0)
    return np.add.reduceat(rows, np.arange(0, values.shape[1], side), axis=1)


def _split_covariance(
    result: IntrinsicDarkDispersion, a: np.ndarray, b: np.ndarray
) -> IntrinsicDarkDispersion:
    """Evaluate two balanced, independent slope maps on the frozen pilot mask."""
    mask = result.pixel_mask
    assert mask is not None
    n = np.count_nonzero(mask)
    if n < 2:
        return dataclasses.replace(result, status=DispersionStatus.TOO_FEW_PIXELS)
    for slopes in (a, b):
        selected = slopes[mask]
        selected -= selected[0]  # exactly zero for a constant map
        slopes.fill(0.0)
        slopes[mask] = selected - selected.mean()
    covariance = float(np.sum(a * b) / (n - 1))
    blocks = int(np.count_nonzero(_tile_sums(mask, result.block_side)))
    result = dataclasses.replace(result, covariance=covariance, block_count=blocks)
    if blocks < 16:
        return dataclasses.replace(result, status=DispersionStatus.TOO_FEW_BLOCKS)

    # For Gaussian maps with equal noise covariance V, both the cross product
    # and half the difference of squared norms have variance
    # 2 theta' V theta + tr(V²) (theta and V spatially centered). Only the
    # latter has zero mean for *every* fixed signal, including a smooth glow.
    # Sum this contrast within spatial clusters before estimating its variance.
    scores = _tile_sums((a - b) * (a + b) * 0.5, result.block_side)
    energy = scores**2
    total = float(energy.sum())
    if total == 0.0:
        return dataclasses.replace(result, status=DispersionStatus.NO_CONTRAST)
    # Moment-matched number of contributing clusters: E[score^4] ≈ 3 var²
    # for nearly normal cluster sums. Avoid precise-looking intervals when
    # nearly all the uncertainty is supported by just one or two tiles.
    effective = min(blocks, 3.0 / float(np.sum((energy / total) ** 2)))
    result = dataclasses.replace(result, effective_blocks=float(effective))
    if effective < 8:
        return dataclasses.replace(result, status=DispersionStatus.CONCENTRATED)
    width = float(stdtrit(effective - 1, 0.975)) * math.sqrt(total) / (n - 1)
    low, high = covariance - width, covariance + width
    if low > 0.0:
        status = DispersionStatus.RESOLVED
    elif high < 0.0:
        status = DispersionStatus.NEGATIVE_INTERVAL
    else:
        status = DispersionStatus.UNRESOLVED
    return dataclasses.replace(result, status=status, covariance_ci95=(low, high))
