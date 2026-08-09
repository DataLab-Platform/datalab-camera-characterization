"""Batch reference implementation of relative Camera metrics in DN."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence

import numpy as np

from .aggregation import _fraction_at_or_above, compute_image_stack_statistics
from .validation import (
    CameraExposureSeries,
    CameraInputValidation,
    CameraValidationParameters,
    validate_camera_inputs,
)


class CameraCharacterizationError(ValueError):
    """Raised when structured input errors block characterization."""

    def __init__(self, validation: CameraInputValidation) -> None:
        self.validation = validation
        codes = ", ".join(diagnostic.code for diagnostic in validation.errors)
        super().__init__(f"Camera input validation failed: {codes}")


@dataclasses.dataclass(frozen=True)
class RelativeCameraCharacterization:
    """Relative temporal Camera metrics expressed only in DN and seconds."""

    validation: CameraInputValidation
    exposure_times_s: np.ndarray
    mean_signal_dn: np.ndarray
    temporal_variance_dn2: np.ndarray
    temporal_noise_dn: np.ndarray
    relative_snr: np.ndarray
    saturation_fractions: np.ndarray
    linear_fit_mask: np.ndarray
    linearity_residuals_dn: np.ndarray
    linear_fit_slope_dn_per_s: float
    linear_fit_intercept_dn: float
    dark_mean_dn: float
    dark_temporal_noise_dn: float
    maximum_unsaturated_signal_dn: float
    relative_dynamic_range: float
    saturation_onset_exposure_s: float | None
    saturation_onset_signal_dn: float | None


def _readonly(array: np.ndarray) -> np.ndarray:
    """Mark an owned result array as read-only and return it."""
    array.setflags(write=False)
    return array


def characterize_relative_dn(
    dark_frames_dn: np.ndarray | None,
    flat_series: Sequence[CameraExposureSeries] | None,
    validation_parameters: CameraValidationParameters | None = None,
    *,
    aggregation_block_size: int = 1,
) -> RelativeCameraCharacterization:
    """Compute relative metrics with bounded mean and variance aggregation.

    Args:
        dark_frames_dn: Dark frame stack shaped ``(frames, height, width)``
        flat_series: Uniform-illumination stacks in increasing exposure order
        validation_parameters: Explicit validation and saturation thresholds
        aggregation_block_size: Maximum frames converted to float together

    Returns:
        Relative response, temporal noise, SNR, saturation, and linearity data

    Raises:
        CameraCharacterizationError: If structured input validation reports an
         error
    """
    parameters = validation_parameters or CameraValidationParameters()
    validation = validate_camera_inputs(
        dark_frames_dn,
        flat_series,
        parameters,
        aggregation_block_size=aggregation_block_size,
    )
    if validation.has_errors:
        raise CameraCharacterizationError(validation)
    assert dark_frames_dn is not None
    assert flat_series is not None

    series_values = tuple(flat_series)
    dark_statistics = compute_image_stack_statistics(
        dark_frames_dn,
        block_size=aggregation_block_size,
        ddof=1,
    )
    dark_mean_dn = dark_statistics.mean_value
    dark_temporal_variance_dn2 = dark_statistics.mean_variance
    dark_temporal_noise_dn = math.sqrt(max(dark_temporal_variance_dn2, 0.0))

    flat_statistics = tuple(
        compute_image_stack_statistics(
            series.frames_dn,
            block_size=aggregation_block_size,
            ddof=1,
        )
        for series in series_values
    )

    exposure_times_s = np.array(
        [series.exposure_time_s for series in series_values],
        dtype=float,
    )
    mean_signal_dn = np.array(
        [statistics.mean_value - dark_mean_dn for statistics in flat_statistics],
        dtype=float,
    )
    temporal_variance_dn2 = np.array(
        [statistics.mean_variance for statistics in flat_statistics],
        dtype=float,
    )
    temporal_noise_dn = np.sqrt(np.maximum(temporal_variance_dn2, 0.0))
    relative_snr = np.divide(
        mean_signal_dn,
        temporal_noise_dn,
        out=np.full_like(mean_signal_dn, np.inf),
        where=temporal_noise_dn > 0.0,
    )
    saturation_fractions = np.array(
        [
            _fraction_at_or_above(
                series.frames_dn,
                parameters.saturation_dn,
                aggregation_block_size,
            )
            for series in series_values
        ],
        dtype=float,
    )
    linear_fit_mask = saturation_fractions < parameters.saturation_fraction_warning
    linear_fit_slope, linear_fit_intercept = np.polyfit(
        exposure_times_s[linear_fit_mask],
        mean_signal_dn[linear_fit_mask],
        deg=1,
    )
    fitted_signal_dn = linear_fit_slope * exposure_times_s + linear_fit_intercept
    linearity_residuals_dn = mean_signal_dn - fitted_signal_dn

    maximum_unsaturated_signal_dn = float(np.max(mean_signal_dn[linear_fit_mask]))
    relative_dynamic_range = (
        maximum_unsaturated_signal_dn / dark_temporal_noise_dn
        if dark_temporal_noise_dn > 0.0
        else math.inf
    )
    saturated_indices = np.flatnonzero(~linear_fit_mask)
    if saturated_indices.size:
        saturation_index = int(saturated_indices[0])
        saturation_onset_exposure_s = float(exposure_times_s[saturation_index])
        saturation_onset_signal_dn = float(mean_signal_dn[saturation_index])
    else:
        saturation_onset_exposure_s = None
        saturation_onset_signal_dn = None

    return RelativeCameraCharacterization(
        validation=validation,
        exposure_times_s=_readonly(exposure_times_s),
        mean_signal_dn=_readonly(mean_signal_dn),
        temporal_variance_dn2=_readonly(temporal_variance_dn2),
        temporal_noise_dn=_readonly(temporal_noise_dn),
        relative_snr=_readonly(relative_snr),
        saturation_fractions=_readonly(saturation_fractions),
        linear_fit_mask=_readonly(linear_fit_mask),
        linearity_residuals_dn=_readonly(linearity_residuals_dn),
        linear_fit_slope_dn_per_s=float(linear_fit_slope),
        linear_fit_intercept_dn=float(linear_fit_intercept),
        dark_mean_dn=dark_mean_dn,
        dark_temporal_noise_dn=dark_temporal_noise_dn,
        maximum_unsaturated_signal_dn=maximum_unsaturated_signal_dn,
        relative_dynamic_range=relative_dynamic_range,
        saturation_onset_exposure_s=saturation_onset_exposure_s,
        saturation_onset_signal_dn=saturation_onset_signal_dn,
    )


__all__ = [
    "CameraCharacterizationError",
    "RelativeCameraCharacterization",
    "characterize_relative_dn",
]
