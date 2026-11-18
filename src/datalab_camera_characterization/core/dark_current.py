"""Dark-current characterization from a dark-frame exposure ramp."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from numbers import Real

import numpy as np
from scipy import ndimage

from .aggregation import (
    ImageStackSource,
    _iter_image_stack_blocks,
    compute_image_stack_statistics,
)
from .characterization import CameraCharacterizationError
from .dark_dispersion import (
    DispersionStatus,
    IntrinsicDarkDispersion,
    _split_covariance,
)
from .validation import (
    CameraDiagnosticLevel,
    CameraExposureSeries,
    CameraInputDiagnostic,
    CameraInputValidation,
    CameraValidationParameters,
    _diagnostic,
    _StackInfo,
    _validate_aggregation_block_size,
    _validate_stack,
)

#: Scale factor turning a median absolute deviation into a Gaussian sigma.
MAD_TO_SIGMA = 1.4826


@dataclasses.dataclass(frozen=True)
class DarkCurrentParameters:
    """Explicit, non-normative settings for the dark-ramp method.

    ``conversion_gain_e_per_dn`` converts LSB/s into e-/s when known, for
    instance from a photon transfer measurement; ``None`` keeps LSB units.
    Hot pixels are isolated pixels whose dark current exceeds the local
    background (median filter of ``background_window`` pixels) by more than
    ``hot_pixel_threshold_sigma`` robust standard deviations, so that smooth
    structures such as amplifier glow are not reported as hot pixels.
    """

    validation: CameraValidationParameters = dataclasses.field(
        default_factory=CameraValidationParameters
    )
    minimum_exposure_levels: int = 3
    conversion_gain_e_per_dn: float | None = None
    hot_pixel_threshold_sigma: float = 5.0
    background_window: int = 5
    dispersion_block_side: int = 8

    def __post_init__(self) -> None:
        """Validate settings independently from a dataset."""
        if not isinstance(self.validation, CameraValidationParameters):
            raise TypeError("Validation parameters must be CameraValidationParameters")
        if (
            isinstance(self.minimum_exposure_levels, bool)
            or not isinstance(self.minimum_exposure_levels, int)
            or self.minimum_exposure_levels < 2
        ):
            raise ValueError("Minimum exposure levels must be an integer of at least 2")
        if self.conversion_gain_e_per_dn is not None:
            gain = float(self.conversion_gain_e_per_dn)
            if not math.isfinite(gain) or gain <= 0.0:
                raise ValueError("Conversion gain must be finite and positive")
        threshold = float(self.hot_pixel_threshold_sigma)
        if not math.isfinite(threshold) or threshold <= 0.0:
            raise ValueError("Hot-pixel threshold must be finite and positive")
        if (
            isinstance(self.background_window, bool)
            or not isinstance(self.background_window, int)
            or self.background_window < 3
            or self.background_window % 2 == 0
        ):
            raise ValueError("Background window must be an odd integer of at least 3")
        if (
            isinstance(self.dispersion_block_side, bool)
            or not isinstance(self.dispersion_block_side, int)
            or self.dispersion_block_side < 1
        ):
            raise ValueError("Dispersion block side must be a positive integer")


@dataclasses.dataclass(frozen=True)
class DarkCurrentCharacterization:
    """Dark-ramp results in LSB; electron values require a conversion gain.

    The maps retain every measurable fit. Observed spatial summaries and both
    ramps use the same non-hot pixels with usable data at every exposure. The
    split-ramp covariance uses a separate, reserved-frame mask. The indicative
    ``conversion_gain_from_dark_e_per_dn`` follows from dark shot noise:
    variance grows as ``mean / K`` like in a photon transfer curve.
    """

    validation: CameraInputValidation
    exposure_times_s: np.ndarray
    mean_dark_dn: np.ndarray
    temporal_variance_dn2: np.ndarray
    dark_current_dn_per_s: float
    offset_dn: float
    fit_r_squared: float
    variance_slope_dn2_per_s: float
    conversion_gain_from_dark_e_per_dn: float
    dark_current_map_dn_per_s: np.ndarray
    offset_map_dn: np.ndarray
    hot_pixel_mask: np.ndarray
    stuck_pixel_mask: np.ndarray
    indeterminate_pixel_mask: np.ndarray
    summary_pixel_mask: np.ndarray
    usable_level_count: np.ndarray
    hot_pixel_threshold_sigma: float
    dark_current_nonuniformity_dn_per_s: float
    intrinsic_dispersion: IntrinsicDarkDispersion
    median_dark_current_dn_per_s: float
    conversion_gain_e_per_dn: float | None

    @property
    def hot_pixel_count(self) -> int:
        """Return the number of hot pixels."""
        return int(np.count_nonzero(self.hot_pixel_mask))

    @property
    def stuck_pixel_count(self) -> int:
        """Return the number of pixels fixed to the same rail in every frame."""
        return int(np.count_nonzero(self.stuck_pixel_mask))

    @property
    def indeterminate_pixel_count(self) -> int:
        """Return the number of non-stuck pixels without a measurable slope."""
        return int(np.count_nonzero(self.indeterminate_pixel_mask))

    @property
    def measured_pixel_count(self) -> int:
        """Return the number of slopes on the map and in the histogram."""
        return (
            self.hot_pixel_mask.size
            - self.stuck_pixel_count
            - (self.indeterminate_pixel_count)
        )

    @property
    def summary_pixel_count(self) -> int:
        """Return the fixed population used at all exposures in the summary."""
        return int(np.count_nonzero(self.summary_pixel_mask))

    @property
    def regular_pixel_mask(self) -> np.ndarray:
        """Historical alias for the summary population, not defect-map class 0."""
        return self.summary_pixel_mask

    def to_electrons(self, value_dn: float) -> float | None:
        """Convert one LSB-based value with the configured gain, if any."""
        if self.conversion_gain_e_per_dn is None:
            return None
        return value_dn * self.conversion_gain_e_per_dn


def _readonly(array: np.ndarray) -> np.ndarray:
    """Mark an owned result array as read-only and return it."""
    array.setflags(write=False)
    return array


def validate_dark_ramp_inputs(
    dark_series: Sequence[CameraExposureSeries] | None,
    parameters: DarkCurrentParameters | None = None,
    *,
    aggregation_block_size: int = 1,
) -> CameraInputValidation:
    """Validate a dark ramp without mutating data or raising dataset errors.

    Args:
        dark_series: Dark stacks in strictly increasing exposure order
        parameters: Minimum level count and stack validation thresholds
        aggregation_block_size: Maximum frames converted to float together

    Returns:
        Structured diagnostics; errors block characterization
    """
    parameters = parameters or DarkCurrentParameters()
    _validate_aggregation_block_size(aggregation_block_size)
    diagnostics: list[CameraInputDiagnostic] = []
    series_values = tuple(dark_series or ())
    if len(series_values) < parameters.minimum_exposure_levels:
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.ERROR,
                "insufficient_dark_levels",
                "Not enough dark exposure levels",
                actual=len(series_values),
                required=parameters.minimum_exposure_levels,
            )
        )
    stack_infos: list[_StackInfo] = []
    previous_exposure: float | None = None
    for index, series in enumerate(series_values):
        if not isinstance(series, CameraExposureSeries):
            diagnostics.append(
                _diagnostic(
                    CameraDiagnosticLevel.ERROR,
                    "invalid_dark_series",
                    "Dark inputs must be CameraExposureSeries values",
                    index=index,
                )
            )
            continue
        name = series.label or f"dark[{index}]"
        exposure = series.exposure_time_s
        if (
            isinstance(exposure, bool)
            or not isinstance(exposure, Real)
            or not math.isfinite(float(exposure))
            or float(exposure) < 0.0
        ):
            diagnostics.append(
                _diagnostic(
                    CameraDiagnosticLevel.ERROR,
                    "invalid_exposure",
                    f"{name} exposure time must be finite and non-negative",
                    series=name,
                )
            )
        else:
            if previous_exposure is not None and float(exposure) <= previous_exposure:
                diagnostics.append(
                    _diagnostic(
                        CameraDiagnosticLevel.ERROR,
                        "exposure_order",
                        "Dark exposure times must be strictly increasing",
                        series=name,
                        previous_s=previous_exposure,
                        actual_s=float(exposure),
                    )
                )
            previous_exposure = float(exposure)
        stack_info = _validate_stack(
            series.frames_dn,
            name,
            parameters.validation,
            aggregation_block_size,
            diagnostics,
        )
        if stack_info is not None:
            stack_infos.append(stack_info)

    if stack_infos:
        reference = stack_infos[0]
        for stack_info in stack_infos[1:]:
            if stack_info.spatial_shape != reference.spatial_shape:
                diagnostics.append(
                    _diagnostic(
                        CameraDiagnosticLevel.ERROR,
                        "shape_mismatch",
                        f"{stack_info.name} image size differs from {reference.name}",
                        series=stack_info.name,
                        expected=list(reference.spatial_shape),
                        actual=list(stack_info.spatial_shape),
                    )
                )
            if stack_info.dtype != reference.dtype:
                diagnostics.append(
                    _diagnostic(
                        CameraDiagnosticLevel.ERROR,
                        "dtype_mismatch",
                        f"{stack_info.name} dtype differs from {reference.name}",
                        series=stack_info.name,
                        expected=str(reference.dtype),
                        actual=str(stack_info.dtype),
                    )
                )
    return CameraInputValidation(diagnostics)


def _level_rail_masks(
    frames: ImageStackSource, saturation_dn: float, block_size: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return usable, low-censored, all-low and all-high masks for one level."""
    shape = frames[0].shape
    low_count = np.zeros(shape, dtype=np.intp)
    any_high = np.zeros(shape, dtype=bool)
    all_high = np.ones(shape, dtype=bool)
    for block in _iter_image_stack_blocks(frames, block_size):
        low_count += np.count_nonzero(block <= 0, axis=0)
        high = block >= saturation_dn
        any_high |= np.any(high, axis=0)
        all_high &= np.all(high, axis=0)
    # A single zero can be read noise. Require repeated pile-up in at least
    # half the frames; one high clip still invalidates the historical mean.
    low_censored = (low_count >= 2) & (2 * low_count >= len(frames))
    return ~(low_censored | any_high), low_censored, low_count == len(frames), all_high


def _fit_pixel_ramps(
    times: np.ndarray,
    means: list[np.ndarray],
    variances: list[np.ndarray],
    usable: list[np.ndarray],
    frame_counts: list[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Fit usable level means and propagate temporal noise and ADC resolution."""
    count = np.sum(usable, axis=0)
    divisor = np.maximum(count, 1)
    # Work in relative time to preserve nearby exposures with a large origin.
    relative_t = times - times[0]
    mean_t = sum(t * mask for t, mask in zip(relative_t, usable)) / divisor
    mean_y = sum(y * mask for y, mask in zip(means, usable)) / divisor
    sxx = np.zeros_like(mean_t)
    sxy = np.zeros_like(mean_t)
    slope_variance = np.zeros_like(mean_t)
    rounding_bound = np.zeros_like(mean_t)
    for t, y, variance, mask, n in zip(
        relative_t, means, variances, usable, frame_counts
    ):
        dt = (t - mean_t) * mask
        sxx += dt**2
        sxy += dt * (y - mean_y)
        slope_variance += dt**2 * variance / n
        # A deterministic native-code mean can be rounded by up to half a LSB.
        rounding_bound += 0.5 * np.abs(dt)
    fitted = (count >= 2) & (sxx > 0.0)
    slope = np.divide(sxy, sxx, out=np.full_like(sxy, np.nan), where=fitted)
    offset = mean_y - slope * (times[0] + mean_t)
    np.divide(slope_variance, sxx**2, out=slope_variance, where=fitted)
    np.divide(rounding_bound, sxx, out=rounding_bound, where=fitted)
    return slope, offset, count, slope_variance, rounding_bound


def _hot_candidates(
    slope: np.ndarray,
    slope_variance: np.ndarray,
    rounding_bound: np.ndarray,
    parameters: DarkCurrentParameters,
) -> np.ndarray:
    """Compare measurable slopes to their local background, including at zero noise."""
    fitted = np.isfinite(slope)
    if not np.any(fitted):
        return np.zeros_like(fitted)

    def local_median(values: np.ndarray) -> np.ndarray:
        filled = np.where(fitted, values, np.median(values[fitted]))
        return ndimage.median_filter(
            filled, size=parameters.background_window, mode="nearest"
        )

    excess = slope - local_median(slope)
    # Few frames give noisy per-pixel variances; the noise level is smooth.
    slope_variance = local_median(slope_variance)
    excess_values = excess[fitted]
    robust_variance = (
        MAD_TO_SIGMA * np.median(np.abs(excess_values - np.median(excess_values)))
    ) ** 2
    intrinsic_variance = max(robust_variance - np.median(slope_variance[fitted]), 0.0)
    sigma = np.sqrt(slope_variance + intrinsic_variance)
    hot = excess > parameters.hot_pixel_threshold_sigma * sigma
    if np.any(fitted & (sigma == 0.0)):
        # No estimated noise: the lower bound of this slope must exceed even
        # the upper bound of the local median (same window, same fit units).
        resolved = slope - rounding_bound > local_median(slope + rounding_bound)
        hot &= (sigma > 0.0) | resolved
    return fitted & hot


def _fit_summary_ramp(
    times: np.ndarray, values: np.ndarray
) -> tuple[float, float, float]:
    """Return slope, offset and R² (undefined for constant or two-point data)."""
    t = times - times[0]
    dt = t - np.mean(t)
    y = values - values[0]
    dy = y - np.mean(y)
    slope = float(dt @ dy / (dt @ dt))
    offset = float(values[0] + np.mean(y) - slope * (times[0] + np.mean(t)))
    total = float(dy @ dy)
    residuals = dy - slope * dt
    r_squared = (
        1.0 - float(residuals @ residuals) / total
        if total > 0.0 and times.size > 2
        else math.nan
    )
    return slope, offset, r_squared


def _intrinsic_dispersion(
    series: Sequence[CameraExposureSeries],
    times: np.ndarray,
    parameters: DarkCurrentParameters,
    block_size: int,
) -> IntrinsicDarkDispersion:
    """Select on reserved frames, then fit two disjoint sets at every exposure."""
    result = IntrinsicDarkDispersion(
        DispersionStatus.TOO_FEW_REPEATS,
        tuple(len(item.frames_dn) for item in series),
        parameters.dispersion_block_side,
    )
    split = result.split_counts
    if not split:
        return result
    dt = times - times[0]
    dt -= dt.mean()
    weights = dt / (dt @ dt)
    shape = series[0].frames_dn[0].shape
    pilot_slope = np.zeros(shape)
    pilot_variance = np.zeros(shape)
    pilot_ok = np.ones(shape, bool)
    fit_rail = np.zeros(shape, bool)
    a, b = np.zeros(shape), np.zeros(shape)
    rail = parameters.validation.saturation_dn
    for level, w, (reserved, half, _) in zip(series, weights, split):
        frames = level.frames_dn
        pilot = frames[:reserved]
        stats = compute_image_stack_statistics(pilot, block_size=block_size)
        pilot_slope += w * stats.mean
        pilot_variance += (w**2 / reserved) * stats.variance
        for frame in pilot:
            pilot_ok &= (frame > 0) & (frame < rail)
        for index in range(reserved, len(frames)):
            frame = frames[index]
            target = a if (index - reserved) % 2 == 0 else b
            target += (w / half) * frame.astype(np.float64, copy=False)
            fit_rail |= (frame <= 0) | (frame >= rail)

    pilot_slope[~pilot_ok] = np.nan
    hot = _hot_candidates(
        pilot_slope,
        pilot_variance,
        np.broadcast_to(0.5 * np.sum(np.abs(weights)), shape),
        parameters,
    )
    mask = _readonly(pilot_ok & ~hot)
    fit_rail_count = int(np.count_nonzero(fit_rail & mask))
    result = dataclasses.replace(
        result,
        pixel_mask=mask,
        pilot_rail_pixels=int(mask.size - np.count_nonzero(pilot_ok)),
        pilot_hot_pixels=int(np.count_nonzero(hot)),
        fit_rail_pixels=fit_rail_count,
    )
    if fit_rail_count:
        # Dropping these pixels would select on the measurement errors.
        return dataclasses.replace(result, status=DispersionStatus.MEASUREMENT_RAIL)
    return _split_covariance(result, a, b)


def characterize_dark_current(
    dark_series: Sequence[CameraExposureSeries] | None,
    parameters: DarkCurrentParameters | None = None,
    *,
    aggregation_block_size: int = 1,
) -> DarkCurrentCharacterization:
    """Estimate dark current, its non-uniformity and hot pixels.

    Each pixel's dark signal is fitted against exposure time with least squares
    over levels not censored at either rail. The slope map is
    the per-pixel dark current and the intercept map the exposure-independent
    offset (bias and offset fixed pattern).

    Args:
        dark_series: Dark stacks in strictly increasing exposure order
        parameters: Gain, hot-pixel and validation settings
        aggregation_block_size: Maximum frames converted to float together

    Returns:
        Dark ramp, dark-current and offset maps, hot pixels and summary values

    Raises:
        CameraCharacterizationError: If inputs are invalid
    """
    parameters = parameters or DarkCurrentParameters()
    validation = validate_dark_ramp_inputs(
        dark_series,
        parameters,
        aggregation_block_size=aggregation_block_size,
    )
    if validation.has_errors:
        raise CameraCharacterizationError(validation)
    assert dark_series is not None
    series_values = tuple(dark_series)
    saturation_dn = parameters.validation.saturation_dn
    exposure_times_s = np.array([float(s.exposure_time_s) for s in series_values])

    mean_maps: list[np.ndarray] = []
    variance_maps: list[np.ndarray] = []
    usable_maps: list[np.ndarray] = []
    frame_counts: list[int] = []
    low_counts: list[int] = []
    shape = series_values[0].frames_dn[0].shape
    always_low = np.ones(shape, dtype=bool)
    always_high = np.ones(shape, dtype=bool)
    for series in series_values:
        statistics = compute_image_stack_statistics(
            series.frames_dn,
            block_size=aggregation_block_size,
            ddof=1,
        )
        mean_maps.append(statistics.mean)
        variance_maps.append(statistics.variance)
        usable, low_censored, all_low, all_high = _level_rail_masks(
            series.frames_dn, saturation_dn, aggregation_block_size
        )
        frame_counts.append(statistics.count)
        usable_maps.append(usable)
        low_counts.append(int(np.count_nonzero(low_censored)))
        always_low &= all_low
        always_high &= all_high

    stuck_pixel_mask = always_low | always_high
    slope_map, offset_map, count, slope_variance, rounding_bound = _fit_pixel_ramps(
        exposure_times_s, mean_maps, variance_maps, usable_maps, frame_counts
    )
    fitted = np.isfinite(slope_map)
    indeterminate = ~stuck_pixel_mask & ~fitted
    hot_pixel_mask = _hot_candidates(
        slope_map, slope_variance, rounding_bound, parameters
    )
    summary = fitted & ~hot_pixel_mask & (count == exposure_times_s.size)
    warnings = []
    stuck_low_count = int(np.count_nonzero(always_low))
    censored_counts = [n - stuck_low_count for n in low_counts]
    if any(censored_counts):
        warnings.append(
            _diagnostic(
                CameraDiagnosticLevel.WARNING,
                "low_rail_censoring",
                "Low-rail pile-up: affected levels excluded from pixel fits",
                exposure_times_s=exposure_times_s.tolist(),
                non_stuck_pixel_counts=censored_counts,
            )
        )
    two_point_count = int(np.count_nonzero(fitted & (count == 2)))
    if two_point_count:
        warnings.append(
            _diagnostic(
                CameraDiagnosticLevel.WARNING,
                "two_point_dark_fit",
                "Only two usable exposure levels: linearity cannot be tested "
                f"for {two_point_count} pixel fit(s)",
                pixel_count=two_point_count,
            )
        )
    regular_slopes = slope_map[summary]
    if regular_slopes.size:
        mean_dark_dn = np.array([np.mean(m[summary]) for m in mean_maps])
        temporal_variance_dn2 = np.array([np.mean(v[summary]) for v in variance_maps])
        dark_current, offset, fit_r_squared = _fit_summary_ramp(
            exposure_times_s, mean_dark_dn
        )
        variance_slope, _, _ = _fit_summary_ramp(
            exposure_times_s, temporal_variance_dn2
        )
    else:
        # The defect map and any partially measurable slopes still carry information.
        mean_dark_dn = np.full_like(exposure_times_s, np.nan)
        temporal_variance_dn2 = mean_dark_dn.copy()
        dark_current = offset = fit_r_squared = variance_slope = math.nan
        warnings.append(
            _diagnostic(
                CameraDiagnosticLevel.WARNING,
                "no_summary_pixels",
                "No non-hot pixel is measurable at every exposure; summary unavailable",
            )
        )
    conversion_gain_from_dark = (
        float(dark_current) / float(variance_slope)
        if variance_slope > 0.0 and dark_current > 0.0
        else math.nan
    )
    del mean_maps, variance_maps, usable_maps, slope_variance, rounding_bound
    intrinsic = _intrinsic_dispersion(
        series_values, exposure_times_s, parameters, aggregation_block_size
    )
    if intrinsic.status is not DispersionStatus.RESOLVED:
        warnings.append(
            _diagnostic(
                CameraDiagnosticLevel.WARNING,
                "intrinsic_dark_dispersion_" + intrinsic.status.name.lower(),
                "Intrinsic dark-current dispersion: " + intrinsic.status.value,
                selected_pixels=intrinsic.pixel_count,
                total_pixels=summary.size,
                fit_rail_pixels=intrinsic.fit_rail_pixels,
                frames_per_level=list(frame_counts),
                block_side=intrinsic.block_side,
                populated_blocks=intrinsic.block_count,
                effective_blocks=intrinsic.effective_blocks,
            )
        )
    return DarkCurrentCharacterization(
        validation=CameraInputValidation((*validation.diagnostics, *warnings)),
        exposure_times_s=_readonly(exposure_times_s),
        mean_dark_dn=_readonly(mean_dark_dn),
        temporal_variance_dn2=_readonly(temporal_variance_dn2),
        dark_current_dn_per_s=float(dark_current),
        offset_dn=float(offset),
        fit_r_squared=fit_r_squared,
        variance_slope_dn2_per_s=float(variance_slope),
        conversion_gain_from_dark_e_per_dn=conversion_gain_from_dark,
        dark_current_map_dn_per_s=_readonly(slope_map),
        offset_map_dn=_readonly(offset_map),
        hot_pixel_mask=_readonly(hot_pixel_mask),
        stuck_pixel_mask=_readonly(stuck_pixel_mask),
        indeterminate_pixel_mask=_readonly(indeterminate),
        summary_pixel_mask=_readonly(summary),
        usable_level_count=_readonly(count),
        hot_pixel_threshold_sigma=float(parameters.hot_pixel_threshold_sigma),
        dark_current_nonuniformity_dn_per_s=(
            float(np.std(regular_slopes, ddof=1))
            if regular_slopes.size > 1
            else math.nan
        ),
        intrinsic_dispersion=intrinsic,
        median_dark_current_dn_per_s=(
            float(np.median(regular_slopes)) if regular_slopes.size else math.nan
        ),
        conversion_gain_e_per_dn=(
            None
            if parameters.conversion_gain_e_per_dn is None
            else float(parameters.conversion_gain_e_per_dn)
        ),
    )


__all__ = [
    "DarkCurrentCharacterization",
    "DarkCurrentParameters",
    "characterize_dark_current",
    "validate_dark_ramp_inputs",
]
