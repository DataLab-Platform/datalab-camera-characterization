"""Dark-current characterization from a dark-frame exposure ramp."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from numbers import Real

import numpy as np
from scipy import ndimage

from .aggregation import compute_image_stack_statistics
from .characterization import CameraCharacterizationError
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

    ``conversion_gain_e_per_dn`` converts DN/s into e-/s when known, for
    instance from a photon transfer measurement; ``None`` keeps DN units.
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


@dataclasses.dataclass(frozen=True)
class DarkCurrentCharacterization:
    """Dark-ramp results in DN; electron values require a conversion gain.

    Spatial means and the variance ramp use regular pixels only: pixels that
    are not stuck, not hot and unsaturated at every exposure. The indicative
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
    regular_pixel_mask: np.ndarray
    hot_pixel_threshold_sigma: float
    dark_current_nonuniformity_dn_per_s: float
    median_dark_current_dn_per_s: float
    conversion_gain_e_per_dn: float | None

    @property
    def hot_pixel_count(self) -> int:
        """Return the number of hot pixels."""
        return int(np.count_nonzero(self.hot_pixel_mask))

    @property
    def stuck_pixel_count(self) -> int:
        """Return the number of pixels stuck at an ADC limit."""
        return int(np.count_nonzero(self.stuck_pixel_mask))

    def to_electrons(self, value_dn: float) -> float | None:
        """Convert one DN-based value with the configured gain, if any."""
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


def _per_pixel_maximum(frames, block_size: int) -> np.ndarray:
    """Return the per-pixel maximum of one stack without a full copy."""
    maximum: np.ndarray | None = None
    count = frames.shape[0] if isinstance(frames, np.ndarray) else len(frames)
    for start in range(0, count, block_size):
        block = np.asarray(frames[start : start + block_size])
        block_maximum = np.max(block, axis=0)
        maximum = (
            block_maximum.astype(np.float64)
            if maximum is None
            else np.maximum(maximum, block_maximum)
        )
    assert maximum is not None
    return maximum


def characterize_dark_current(
    dark_series: Sequence[CameraExposureSeries] | None,
    parameters: DarkCurrentParameters | None = None,
    *,
    aggregation_block_size: int = 1,
) -> DarkCurrentCharacterization:
    """Estimate dark current, its non-uniformity and hot pixels.

    Each pixel's dark signal is fitted against exposure time with least squares
    over the levels where the pixel never reaches saturation. The slope map is
    the per-pixel dark current and the intercept map the exposure-independent
    offset (bias and offset fixed pattern).

    Args:
        dark_series: Dark stacks in strictly increasing exposure order
        parameters: Gain, hot-pixel and validation settings
        aggregation_block_size: Maximum frames converted to float together

    Returns:
        Dark ramp, dark-current and offset maps, hot pixels and summary values

    Raises:
        CameraCharacterizationError: If inputs are invalid or no regular pixel
         remains
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
    unsaturated_maps: list[np.ndarray] = []
    for series in series_values:
        statistics = compute_image_stack_statistics(
            series.frames_dn,
            block_size=aggregation_block_size,
            ddof=1,
        )
        mean_maps.append(statistics.mean)
        variance_maps.append(statistics.variance)
        unsaturated_maps.append(
            _per_pixel_maximum(series.frames_dn, aggregation_block_size) < saturation_dn
        )

    # Streaming per-pixel least squares over unsaturated levels only.
    count = np.zeros(mean_maps[0].shape)
    sum_t = np.zeros_like(count)
    sum_tt = np.zeros_like(count)
    sum_y = np.zeros_like(count)
    sum_ty = np.zeros_like(count)
    for exposure, mean_map, unsaturated in zip(
        exposure_times_s, mean_maps, unsaturated_maps
    ):
        weight = unsaturated.astype(float)
        count += weight
        sum_t += weight * exposure
        sum_tt += weight * exposure**2
        sum_y += weight * mean_map
        sum_ty += weight * exposure * mean_map
    denominator = count * sum_tt - sum_t**2
    fitted = (count >= 2) & (denominator > 0.0)
    slope_map = np.full(count.shape, np.nan)
    offset_map = np.full(count.shape, np.nan)
    slope_map[fitted] = (
        count[fitted] * sum_ty[fitted] - sum_t[fitted] * sum_y[fitted]
    ) / denominator[fitted]
    offset_map[fitted] = (sum_y[fitted] - slope_map[fitted] * sum_t[fitted]) / count[
        fitted
    ]

    stuck_pixel_mask = np.all(
        [(mean_map <= 0.0) | (mean_map >= saturation_dn) for mean_map in mean_maps],
        axis=0,
    )
    candidates = fitted & ~stuck_pixel_mask
    if not np.any(candidates):
        raise CameraCharacterizationError(
            CameraInputValidation(
                (
                    _diagnostic(
                        CameraDiagnosticLevel.ERROR,
                        "no_valid_pixels",
                        "No pixel has enough unsaturated dark exposure levels",
                    ),
                )
            )
        )
    filled = np.where(candidates, slope_map, np.nanmedian(slope_map[candidates]))
    background = ndimage.median_filter(
        filled,
        size=parameters.background_window,
        mode="nearest",
    )
    excess = filled - background

    # Slope uncertainty from each pixel's own temporal noise: shot noise makes
    # it grow with the local rate (amplifier glow), unlike the intrinsic spread.
    mean_t = np.divide(sum_t, count, out=np.zeros_like(count), where=count > 0)
    sxx = np.divide(denominator, count, out=np.ones_like(count), where=count > 0)
    slope_variance = np.zeros_like(count)
    for exposure, variance_map, unsaturated, series in zip(
        exposure_times_s, variance_maps, unsaturated_maps, series_values
    ):
        frame_count = (
            series.frames_dn.shape[0]
            if isinstance(series.frames_dn, np.ndarray)
            else len(series.frames_dn)
        )
        slope_variance += (
            unsaturated * (exposure - mean_t) ** 2 * variance_map / frame_count
        )
    slope_variance = np.divide(
        slope_variance,
        sxx**2,
        out=np.zeros_like(slope_variance),
        where=sxx > 0.0,
    )
    # Few frames give noisy per-pixel variances; the noise level is smooth.
    slope_variance = ndimage.median_filter(
        np.where(candidates, slope_variance, np.median(slope_variance[candidates])),
        size=parameters.background_window,
        mode="nearest",
    )
    excess_values = excess[candidates]
    robust_variance = (
        MAD_TO_SIGMA
        * float(np.median(np.abs(excess_values - np.median(excess_values))))
    ) ** 2
    intrinsic_variance = max(
        robust_variance - float(np.median(slope_variance[candidates])), 0.0
    )
    significance = np.divide(
        excess,
        np.sqrt(slope_variance + intrinsic_variance),
        out=np.zeros_like(excess),
        where=(slope_variance + intrinsic_variance) > 0.0,
    )
    # Pixels saturating too early to be fitted are the hottest of all.
    hot_pixel_mask = ~stuck_pixel_mask & (
        ~fitted | (candidates & (significance > parameters.hot_pixel_threshold_sigma))
    )
    all_unsaturated = np.all(unsaturated_maps, axis=0)
    regular_pixel_mask = candidates & ~hot_pixel_mask & all_unsaturated
    if not np.any(regular_pixel_mask):
        raise CameraCharacterizationError(
            CameraInputValidation(
                (
                    _diagnostic(
                        CameraDiagnosticLevel.ERROR,
                        "no_regular_pixels",
                        "No regular pixel remains after hot-pixel classification",
                    ),
                )
            )
        )

    mean_dark_dn = np.array(
        [float(np.mean(mean_map[regular_pixel_mask])) for mean_map in mean_maps]
    )
    temporal_variance_dn2 = np.array(
        [
            float(np.mean(variance_map[regular_pixel_mask]))
            for variance_map in variance_maps
        ]
    )
    dark_current, offset = np.polyfit(exposure_times_s, mean_dark_dn, deg=1)
    residuals = mean_dark_dn - (dark_current * exposure_times_s + offset)
    total = float(np.sum((mean_dark_dn - np.mean(mean_dark_dn)) ** 2))
    fit_r_squared = 1.0 - float(np.sum(residuals**2)) / total if total > 0.0 else 1.0
    variance_slope, _variance_intercept = np.polyfit(
        exposure_times_s,
        temporal_variance_dn2,
        deg=1,
    )
    conversion_gain_from_dark = (
        float(dark_current) / float(variance_slope)
        if variance_slope > 0.0 and dark_current > 0.0
        else math.nan
    )
    regular_slopes = slope_map[regular_pixel_mask]

    return DarkCurrentCharacterization(
        validation=validation,
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
        regular_pixel_mask=_readonly(regular_pixel_mask),
        hot_pixel_threshold_sigma=float(parameters.hot_pixel_threshold_sigma),
        dark_current_nonuniformity_dn_per_s=float(np.std(regular_slopes, ddof=1)),
        median_dark_current_dn_per_s=float(np.median(regular_slopes)),
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
