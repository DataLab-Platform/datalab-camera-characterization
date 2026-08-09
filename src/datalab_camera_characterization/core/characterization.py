"""Batch reference implementation of relative Camera metrics in DN."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence

import numpy as np

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


def _mean_temporal_variance(frames: np.ndarray) -> float:
    """Return the spatial mean of unbiased per-pixel temporal variances."""
    temporal_variance = np.var(frames.astype(float, copy=False), axis=0, ddof=1)
    return float(np.mean(temporal_variance))


def characterize_relative_dn(
    dark_frames_dn: np.ndarray | None,
    flat_series: Sequence[CameraExposureSeries] | None,
    validation_parameters: CameraValidationParameters | None = None,
) -> RelativeCameraCharacterization:
    """Compute batch reference metrics after complete structured validation.

    The implementation deliberately holds complete frame stacks in memory.
    Phase 2.5 replaces mean and variance aggregation with a numerically
    equivalent incremental or block implementation.

    Args:
        dark_frames_dn: Dark frame stack shaped ``(frames, height, width)``
        flat_series: Uniform-illumination stacks in increasing exposure order
        validation_parameters: Explicit validation and saturation thresholds

    Returns:
        Relative response, temporal noise, SNR, saturation, and linearity data

    Raises:
        CameraCharacterizationError: If structured input validation reports an
         error
    """
    parameters = validation_parameters or CameraValidationParameters()
    validation = validate_camera_inputs(dark_frames_dn, flat_series, parameters)
    if validation.has_errors:
        raise CameraCharacterizationError(validation)
    assert dark_frames_dn is not None
    assert flat_series is not None

    series_values = tuple(flat_series)
    dark_mean_dn = float(np.mean(dark_frames_dn, dtype=float))
    dark_temporal_variance_dn2 = _mean_temporal_variance(dark_frames_dn)
    dark_temporal_noise_dn = math.sqrt(max(dark_temporal_variance_dn2, 0.0))

    exposure_times_s = np.array(
        [series.exposure_time_s for series in series_values],
        dtype=float,
    )
    mean_signal_dn = np.array(
        [
            float(np.mean(series.frames_dn, dtype=float)) - dark_mean_dn
            for series in series_values
        ],
        dtype=float,
    )
    temporal_variance_dn2 = np.array(
        [_mean_temporal_variance(series.frames_dn) for series in series_values],
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
            float(np.mean(series.frames_dn >= parameters.saturation_dn))
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
