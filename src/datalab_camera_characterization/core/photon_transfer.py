"""Photon transfer (mean-variance) characterization of a linear camera."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence

import numpy as np

from .aggregation import ImageStackSource, compute_image_stack_statistics
from .characterization import CameraCharacterizationError
from .validation import (
    CameraDiagnosticLevel,
    CameraExposureSeries,
    CameraInputDiagnostic,
    CameraInputValidation,
    CameraValidationParameters,
    validate_camera_inputs,
)


@dataclasses.dataclass(frozen=True)
class PhotonTransferParameters:
    """Explicit, non-normative settings for the photon transfer method.

    ``fit_upper_fraction`` bounds the linear fit to levels whose mean signal
    does not exceed that fraction of the saturation signal (the mean at the
    variance maximum), following the usual photon transfer practice.
    """

    validation: CameraValidationParameters = dataclasses.field(
        default_factory=CameraValidationParameters
    )
    fit_upper_fraction: float = 0.7
    minimum_fit_levels: int = 3
    exclude_stuck_pixels: bool = True

    def __post_init__(self) -> None:
        """Validate settings independently from a dataset."""
        if not isinstance(self.validation, CameraValidationParameters):
            raise TypeError("Validation parameters must be CameraValidationParameters")
        fraction = float(self.fit_upper_fraction)
        if not math.isfinite(fraction) or not 0.0 < fraction <= 1.0:
            raise ValueError("Fit upper fraction must be in (0.0, 1.0]")
        if (
            isinstance(self.minimum_fit_levels, bool)
            or not isinstance(self.minimum_fit_levels, int)
            or self.minimum_fit_levels < 2
        ):
            raise ValueError("Minimum fit levels must be an integer of at least 2")
        if not isinstance(self.exclude_stuck_pixels, bool):
            raise TypeError("Stuck-pixel exclusion flag must be a bool")


@dataclasses.dataclass(frozen=True)
class PhotonTransferCharacterization:
    """Photon transfer results; electron values follow from the fitted gain.

    ``conversion_gain_e_per_dn`` is the inverse slope of the dark-corrected
    temporal variance versus the dark-corrected mean signal. The read noise is
    the dark temporal noise converted to electrons and therefore includes ADC
    quantization noise.
    """

    validation: CameraInputValidation
    exposure_times_s: np.ndarray
    mean_signal_dn: np.ndarray
    temporal_variance_dn2: np.ndarray
    fit_mask: np.ndarray
    fit_slope_dn: float
    fit_intercept_dn2: float
    fit_r_squared: float
    fit_residuals_dn2: np.ndarray
    conversion_gain_e_per_dn: float
    dark_mean_dn: float
    dark_temporal_noise_dn: float
    read_noise_e: float
    saturation_index: int
    saturation_reached: bool
    saturation_signal_dn: float
    saturation_capacity_e: float
    dynamic_range_db: float
    signal_electrons: np.ndarray
    measured_snr: np.ndarray
    model_snr: np.ndarray
    valid_pixel_count: int
    excluded_pixel_count: int


def _readonly(array: np.ndarray) -> np.ndarray:
    """Mark an owned result array as read-only and return it."""
    array.setflags(write=False)
    return array


def _error(code: str, message: str, **details: object) -> CameraCharacterizationError:
    """Return a characterization error carrying one structured diagnostic."""
    return CameraCharacterizationError(
        CameraInputValidation(
            (
                CameraInputDiagnostic(
                    CameraDiagnosticLevel.ERROR,
                    code,
                    message,
                    details,
                ),
            )
        )
    )


def characterize_photon_transfer(
    dark_frames_dn: ImageStackSource | None,
    flat_series: Sequence[CameraExposureSeries] | None,
    parameters: PhotonTransferParameters | None = None,
    *,
    aggregation_block_size: int = 1,
) -> PhotonTransferCharacterization:
    """Estimate conversion gain, read noise and saturation capacity.

    For a shot-noise-limited linear sensor, the dark-corrected temporal
    variance grows linearly with the dark-corrected mean signal:
    ``variance_dn2 = mean_signal_dn / K`` where ``K`` is the conversion gain in
    electrons per DN. Per-pixel temporal variances exclude fixed-pattern noise,
    so two frames per level are enough (equivalent to the pair-difference
    method).

    Args:
        dark_frames_dn: Dark 3D stack or sequence of 2D frame arrays
        flat_series: Uniform-illumination stacks in increasing exposure order
        parameters: Fit range, stuck-pixel and validation settings
        aggregation_block_size: Maximum frames converted to float together

    Returns:
        Photon transfer curve, fitted gain and derived electron quantities

    Raises:
        CameraCharacterizationError: If inputs are invalid or the linear range
         cannot be fitted
    """
    parameters = parameters or PhotonTransferParameters()
    validation = validate_camera_inputs(
        dark_frames_dn,
        flat_series,
        parameters.validation,
        aggregation_block_size=aggregation_block_size,
    )
    if validation.has_errors:
        raise CameraCharacterizationError(validation)
    assert dark_frames_dn is not None
    assert flat_series is not None
    series_values = tuple(flat_series)
    saturation_dn = parameters.validation.saturation_dn

    dark_statistics = compute_image_stack_statistics(
        dark_frames_dn,
        block_size=aggregation_block_size,
        ddof=1,
    )
    if parameters.exclude_stuck_pixels:
        # Dead and hot defects sit at the ADC limits even without light.
        valid_mask = (dark_statistics.mean > 0.0) & (
            dark_statistics.mean < saturation_dn
        )
    else:
        valid_mask = np.ones(dark_statistics.mean.shape, dtype=bool)
    valid_pixel_count = int(np.count_nonzero(valid_mask))
    if valid_pixel_count == 0:
        raise _error(
            "no_valid_pixels",
            "Every pixel is stuck at an ADC limit in the dark frames",
        )
    dark_mean_dn = float(np.mean(dark_statistics.mean[valid_mask]))
    dark_variance_dn2 = float(np.mean(dark_statistics.variance[valid_mask]))
    del dark_statistics

    mean_signal: list[float] = []
    temporal_variance: list[float] = []
    for series in series_values:
        statistics = compute_image_stack_statistics(
            series.frames_dn,
            block_size=aggregation_block_size,
            ddof=1,
        )
        mean_signal.append(float(np.mean(statistics.mean[valid_mask])) - dark_mean_dn)
        temporal_variance.append(
            float(np.mean(statistics.variance[valid_mask])) - dark_variance_dn2
        )
        del statistics

    exposure_times_s = np.array(
        [float(series.exposure_time_s) for series in series_values]
    )
    mean_signal_dn = np.array(mean_signal)
    temporal_variance_dn2 = np.array(temporal_variance)

    saturation_index = int(np.argmax(temporal_variance_dn2))
    saturation_signal_dn = float(mean_signal_dn[saturation_index])
    fit_mask = (mean_signal_dn > 0.0) & (
        mean_signal_dn <= parameters.fit_upper_fraction * saturation_signal_dn
    )
    fit_mask &= np.arange(len(series_values)) <= saturation_index
    fit_level_count = int(np.count_nonzero(fit_mask))
    if fit_level_count < parameters.minimum_fit_levels:
        raise _error(
            "insufficient_ptc_levels",
            "Not enough exposure levels in the linear photon transfer range",
            actual=fit_level_count,
            required=parameters.minimum_fit_levels,
            fit_upper_fraction=parameters.fit_upper_fraction,
        )
    slope, intercept = np.polyfit(
        mean_signal_dn[fit_mask],
        temporal_variance_dn2[fit_mask],
        deg=1,
    )
    if not slope > 0.0:
        raise _error(
            "non_positive_ptc_slope",
            "Temporal variance does not increase with the mean signal",
            slope_dn=float(slope),
        )
    fitted_variance = slope * mean_signal_dn + intercept
    fit_residuals_dn2 = temporal_variance_dn2 - fitted_variance
    fitted_values = temporal_variance_dn2[fit_mask]
    total_sum_squares = float(np.sum((fitted_values - np.mean(fitted_values)) ** 2))
    residual_sum_squares = float(np.sum(fit_residuals_dn2[fit_mask] ** 2))
    fit_r_squared = (
        1.0 - residual_sum_squares / total_sum_squares
        if total_sum_squares > 0.0
        else 1.0
    )

    conversion_gain_e_per_dn = 1.0 / float(slope)
    dark_temporal_noise_dn = math.sqrt(max(dark_variance_dn2, 0.0))
    read_noise_e = conversion_gain_e_per_dn * dark_temporal_noise_dn
    saturation_capacity_e = conversion_gain_e_per_dn * saturation_signal_dn
    dynamic_range_db = (
        20.0 * math.log10(saturation_capacity_e / read_noise_e)
        if read_noise_e > 0.0 and saturation_capacity_e > 0.0
        else math.inf
    )
    signal_electrons = conversion_gain_e_per_dn * mean_signal_dn
    flat_noise_dn = np.sqrt(np.maximum(temporal_variance_dn2 + dark_variance_dn2, 0.0))
    measured_snr = np.divide(
        mean_signal_dn,
        flat_noise_dn,
        out=np.full_like(mean_signal_dn, np.inf),
        where=flat_noise_dn > 0.0,
    )
    model_noise_e = np.sqrt(np.maximum(signal_electrons, 0.0) + read_noise_e**2)
    model_snr = np.divide(
        signal_electrons,
        model_noise_e,
        out=np.full_like(signal_electrons, np.inf),
        where=model_noise_e > 0.0,
    )

    return PhotonTransferCharacterization(
        validation=validation,
        exposure_times_s=_readonly(exposure_times_s),
        mean_signal_dn=_readonly(mean_signal_dn),
        temporal_variance_dn2=_readonly(temporal_variance_dn2),
        fit_mask=_readonly(fit_mask),
        fit_slope_dn=float(slope),
        fit_intercept_dn2=float(intercept),
        fit_r_squared=fit_r_squared,
        fit_residuals_dn2=_readonly(fit_residuals_dn2),
        conversion_gain_e_per_dn=conversion_gain_e_per_dn,
        dark_mean_dn=dark_mean_dn,
        dark_temporal_noise_dn=dark_temporal_noise_dn,
        read_noise_e=read_noise_e,
        saturation_index=saturation_index,
        saturation_reached=saturation_index < len(series_values) - 1,
        saturation_signal_dn=saturation_signal_dn,
        saturation_capacity_e=saturation_capacity_e,
        dynamic_range_db=dynamic_range_db,
        signal_electrons=_readonly(signal_electrons),
        measured_snr=_readonly(measured_snr),
        model_snr=_readonly(model_snr),
        valid_pixel_count=valid_pixel_count,
        excluded_pixel_count=int(valid_mask.size - valid_pixel_count),
    )


__all__ = [
    "PhotonTransferCharacterization",
    "PhotonTransferParameters",
    "characterize_photon_transfer",
]
