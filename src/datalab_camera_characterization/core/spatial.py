"""Non-normative relative spatial Camera characterization in DN."""

from __future__ import annotations

import dataclasses
import math

import numpy as np


@dataclasses.dataclass(frozen=True)
class RelativeSpatialCharacterization:
    """Read-only relative maps, profiles, distributions, and candidates."""

    dsnu_like_map_dn: np.ndarray
    prnu_like_map_fraction: np.ndarray
    dark_nonuniformity_dn: float
    flat_field_nonuniformity_fraction: float
    candidate_pixel_mask: np.ndarray
    candidate_pixel_count: int
    candidate_pixel_fraction: float
    row_profile_fraction: np.ndarray
    column_profile_fraction: np.ndarray
    dsnu_histogram_counts: np.ndarray
    dsnu_histogram_bin_edges_dn: np.ndarray
    prnu_histogram_counts: np.ndarray
    prnu_histogram_bin_edges_fraction: np.ndarray


def _readonly(array: np.ndarray) -> np.ndarray:
    """Mark an owned result array as read-only and return it."""
    array.setflags(write=False)
    return array


def _validate_mean_image(image: np.ndarray, name: str) -> np.ndarray:
    """Return one finite two-dimensional mean image as float64."""
    if not isinstance(image, np.ndarray) or image.ndim != 2 or 0 in image.shape:
        raise ValueError(f"{name} must be a non-empty two-dimensional array")
    if not np.issubdtype(image.dtype, np.number) or np.issubdtype(
        image.dtype, np.complexfloating
    ):
        raise TypeError(f"{name} must use a real numeric dtype")
    if not np.all(np.isfinite(image)):
        raise ValueError(f"{name} must contain only finite values")
    return image.astype(np.float64, copy=False)


def _validate_positive_real(value: float, name: str) -> float:
    """Return one finite positive real value."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{name} must be positive and finite")
    return normalized


def _validate_histogram_bin_count(value: int) -> int:
    """Return one positive built-in histogram bin count."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Histogram bin count must be an integer")
    if value <= 0:
        raise ValueError("Histogram bin count must be positive")
    return value


def _sample_standard_deviation(array: np.ndarray) -> float:
    """Return the spatial sample deviation, or zero for one pixel."""
    if array.size == 1:
        return 0.0
    return float(np.std(array, ddof=1))


def characterize_spatial_dn(
    mean_dark_dn: np.ndarray,
    mean_flat_dn: np.ndarray,
    *,
    candidate_threshold_sigma: float = 5.0,
    histogram_bin_count: int = 64,
) -> RelativeSpatialCharacterization:
    """Compute relative spatial maps from dark and illuminated mean images.

    The DSNU-like map is the centered mean dark image in DN. The PRNU-like
    map is the dark-corrected mean flat image divided by its spatial mean,
    minus one. These relative definitions are non-normative and make no EMVA
    compliance claim.

    Args:
        mean_dark_dn: Per-pixel temporal mean of the dark series
        mean_flat_dn: Per-pixel temporal mean of one unsaturated flat series
        candidate_threshold_sigma: Absolute spatial-deviation threshold
        histogram_bin_count: Number of bins in each map distribution

    Returns:
        Read-only relative spatial characterization arrays and metrics

    Raises:
        ValueError: If images are incompatible or flat signal is not positive
    """
    dark = _validate_mean_image(mean_dark_dn, "Mean dark image")
    flat = _validate_mean_image(mean_flat_dn, "Mean flat image")
    if flat.shape != dark.shape:
        raise ValueError("Mean dark and flat images must share a shape")
    threshold_sigma = _validate_positive_real(
        candidate_threshold_sigma, "Candidate threshold sigma"
    )
    bin_count = _validate_histogram_bin_count(histogram_bin_count)

    dsnu_like_map_dn = dark - np.mean(dark, dtype=np.float64)
    flat_signal_dn = flat - dark
    mean_flat_signal_dn = float(np.mean(flat_signal_dn, dtype=np.float64))
    if mean_flat_signal_dn <= 0.0:
        raise ValueError("Mean dark-corrected flat signal must be positive")
    prnu_like_map_fraction = flat_signal_dn / mean_flat_signal_dn
    prnu_like_map_fraction -= 1.0

    dark_nonuniformity_dn = _sample_standard_deviation(dsnu_like_map_dn)
    flat_field_nonuniformity_fraction = _sample_standard_deviation(
        prnu_like_map_fraction
    )
    candidate_pixel_mask = np.zeros(dark.shape, dtype=bool)
    if dark_nonuniformity_dn > 0.0:
        candidate_pixel_mask |= np.abs(dsnu_like_map_dn) > (
            threshold_sigma * dark_nonuniformity_dn
        )
    if flat_field_nonuniformity_fraction > 0.0:
        candidate_pixel_mask |= np.abs(prnu_like_map_fraction) > (
            threshold_sigma * flat_field_nonuniformity_fraction
        )

    row_profile_fraction = np.mean(prnu_like_map_fraction, axis=1)
    column_profile_fraction = np.mean(prnu_like_map_fraction, axis=0)
    dsnu_histogram_counts, dsnu_histogram_bin_edges_dn = np.histogram(
        dsnu_like_map_dn, bins=bin_count
    )
    prnu_histogram_counts, prnu_histogram_bin_edges_fraction = np.histogram(
        prnu_like_map_fraction, bins=bin_count
    )
    candidate_pixel_count = int(np.count_nonzero(candidate_pixel_mask))

    return RelativeSpatialCharacterization(
        dsnu_like_map_dn=_readonly(dsnu_like_map_dn),
        prnu_like_map_fraction=_readonly(prnu_like_map_fraction),
        dark_nonuniformity_dn=dark_nonuniformity_dn,
        flat_field_nonuniformity_fraction=flat_field_nonuniformity_fraction,
        candidate_pixel_mask=_readonly(candidate_pixel_mask),
        candidate_pixel_count=candidate_pixel_count,
        candidate_pixel_fraction=candidate_pixel_count / candidate_pixel_mask.size,
        row_profile_fraction=_readonly(row_profile_fraction),
        column_profile_fraction=_readonly(column_profile_fraction),
        dsnu_histogram_counts=_readonly(dsnu_histogram_counts),
        dsnu_histogram_bin_edges_dn=_readonly(dsnu_histogram_bin_edges_dn),
        prnu_histogram_counts=_readonly(prnu_histogram_counts),
        prnu_histogram_bin_edges_fraction=_readonly(prnu_histogram_bin_edges_fraction),
    )


__all__ = [
    "RelativeSpatialCharacterization",
    "characterize_spatial_dn",
]
