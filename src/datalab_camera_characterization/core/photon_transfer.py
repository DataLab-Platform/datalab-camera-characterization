"""Photon transfer (mean-variance) characterization of a linear camera."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence

import numpy as np

from .aggregation import (
    ImageStackSource,
    compute_image_stack_mean,
    compute_image_stack_statistics,
)
from .dark_reference import DarkInput, DarkReferenceStatistics, prepare_dark_references
from .errors import CameraCharacterizationError
from .validation import (
    CameraDiagnosticLevel,
    CameraExposureSeries,
    CameraInputDiagnostic,
    CameraInputValidation,
    CameraValidationParameters,
)


@dataclasses.dataclass(frozen=True)
class PhotonTransferParameters:
    """Explicit, non-normative settings for the photon transfer method.

    The fit uses a fraction of the available response range, not a fraction
    of the signal at the variance peak. A sub-rail response plateau requires
    independent evidence of stable illumination supplied by the operator.
    """

    validation: CameraValidationParameters = dataclasses.field(
        default_factory=CameraValidationParameters
    )
    fit_upper_fraction: float = 0.7
    minimum_fit_levels: int = 3
    exclude_stuck_pixels: bool = True
    variance_mode: str = "raw"
    stable_illumination: bool = False

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
        if self.variance_mode not in ("raw", "centered_pairs"):
            raise ValueError("Variance mode must be 'raw' or 'centered_pairs'")
        if not isinstance(self.stable_illumination, bool):
            raise TypeError("Stable illumination confirmation must be a bool")


@dataclasses.dataclass(frozen=True)
class PairStatistics:
    """Scalar observations on one stack, in input acquisition order."""

    frame_means_dn: tuple[float, ...]
    pair_count: int
    pair_variance_dn2: float
    removed_variance_dn2: float
    centered_variance_dn2: float | None
    frame_mean_variance_dn2: float
    common_mode_warning: bool
    high_rail_counts: tuple[int, ...]
    low_rail_counts: tuple[int, ...]
    censored_fraction: float


@dataclasses.dataclass(frozen=True)
class PhotonTransferCharacterization:
    """Photon transfer results; electron values follow from the fitted gain.

    ``conversion_gain_e_per_dn`` is the inverse slope of the dark-corrected
    temporal variance versus the dark-corrected mean signal. The noise of the
    designated dark stack is always reported; only an exploitable short bias
    provides an estimated read noise, which still includes ADC quantization.
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
    raw_gain_e_per_dn: float | None
    centered_gain_e_per_dn: float | None
    dark_mean_dn: float
    dark_temporal_noise_dn: float
    read_noise_e: float | None
    dark_temporal_noise_e: float
    dark_reference: DarkReferenceStatistics
    flat_temporal_variance_dn2: np.ndarray
    raw_temporal_variance_dn2: np.ndarray
    centered_temporal_variance_dn2: np.ndarray
    variance_mode: str
    flat_pairs: tuple[PairStatistics, ...]
    dark_pairs: tuple[
        PairStatistics, ...
    ]  # in dark_reference.plan.used_exposures order
    variance_peak_index: int
    clipped_mask: np.ndarray
    rail_population: int
    rail_min_pixels: int
    saturation_index: int | None
    usable_signal_index: int | None
    saturation_evidence: str
    saturation_signal_dn: float | None
    saturation_capacity_e: float | None
    dynamic_range_db: float | None
    signal_electrons: np.ndarray
    measured_snr: np.ndarray
    model_snr: np.ndarray
    valid_pixel_count: int
    excluded_pixel_count: int

    @property
    def saturation_reached(self) -> bool:
        return self.saturation_index is not None

    @property
    def saturation_status(self) -> str:
        if self.saturation_reached and self.saturation_signal_dn is not None:
            return "Observed"
        return (
            "Lower bound" if self.saturation_signal_dn is not None else "Indeterminate"
        )

    @property
    def dynamic_range_status(self) -> str:
        return (
            self.saturation_status
            if self.dynamic_range_db is not None
            else "Indeterminate"
        )


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


def _pair_statistics(
    frames: ImageStackSource,
    mask: np.ndarray,
    rail_mask: np.ndarray,
    ceiling: float,
    raw_variance: float,
) -> PairStatistics:
    """Accumulate adjacent, disjoint differences; never subtract unsigned codes."""
    means, high, low = [], [], []
    centered = removed = rail_samples = 0.0
    pixels = int(np.count_nonzero(mask))
    for i, frame in enumerate(frames):
        values = frame[mask]
        means.append(float(np.mean(values, dtype=np.float64)))
        rail_values = values if rail_mask is mask else frame[rail_mask]
        high.append(int(np.count_nonzero(rail_values >= ceiling)))
        low.append(int(np.count_nonzero(rail_values <= 0)))
        rail_samples += np.count_nonzero((values >= ceiling) | (values <= 0))
        if i % 2:
            delta = np.subtract(values, frames[i - 1][mask], dtype=np.float64)
            delta_mean = float(np.mean(delta))
            delta -= delta_mean
            centered += float(np.mean(np.square(delta, out=delta)))
            removed += delta_mean**2
    pair_count = len(frames) // 2
    if not pair_count:
        raise _error("insufficient_frames", "PTC needs at least two frames per stack")
    centered /= 2 * pair_count
    removed /= 2 * pair_count
    mean_variance = float(np.var(means, ddof=1))
    # Heuristic, not a significance test for spatially correlated pixels.
    drift = raw_variance > 0 and mean_variance > max(0.10, 9.0 / pixels) * raw_variance
    return PairStatistics(
        tuple(means),
        pair_count,
        centered + removed,
        removed,
        centered if pixels > 1 else None,
        mean_variance,
        drift,
        tuple(high),
        tuple(low),
        rail_samples / (len(frames) * pixels),
    )


def _response_limits(
    times: np.ndarray,
    signal: np.ndarray,
    flats: tuple[PairStatistics, ...],
    darks: tuple[PairStatistics, ...],
    flat_variance: np.ndarray,
    min_pixels: int,
    dark_censor_fraction: float,
    stable_illumination: bool,
) -> tuple[np.ndarray, int | None, str, int | None]:
    """Separate an observed limit from a reproducible usable lower bound."""
    high = np.array([max(p.high_rail_counts) >= min_pixels for p in flats])
    low = np.array([max(p.low_rail_counts) >= min_pixels for p in flats])
    clipped = high | low
    # Clipping in only one repeat censors the SNR, but does not establish a
    # repeatable ceiling of the response. Require it to persist to the end.
    repeated = np.array([min(p.high_rail_counts) >= min_pixels for p in flats])
    onset = len(flats)
    while onset > 0 and repeated[onset - 1]:
        onset -= 1
    index = onset if onset < len(flats) else None
    evidence = "adc_clipping" if index is not None else "none"

    # Full span of the flat and correction-dark frame means (not just their
    # averages). A large common-mode signal must not certify its own plateau.
    span = np.array(
        [
            np.ptp(f.frame_means_dn) + np.ptp(d.frame_means_dn)
            for f, d in zip(flats, darks)
        ]
    )
    dark_ok = np.array([d.censored_fraction < dark_censor_fraction for d in darks])
    reproducible = (signal > 0) & (span <= 0.01 * signal) & ~clipped & dark_ok
    if stable_illumination and index is None:
        # Terminal plateau only; reject a transient pause, close exposures,
        # and a flat response with no preceding rise.
        for i in range(1, len(flats) - 2):
            tail = signal[i:]
            if (
                np.all(reproducible[i:])
                and np.all(times[i + 1 :] >= 1.1 * times[i:-1])
                and np.ptp(tail) + np.max(span[i:]) <= 0.01 * np.min(tail)
                and reproducible[i - 1]
                and signal[i - 1] < 0.90 * np.min(tail)
            ):
                index, evidence = i, "response_plateau"
                break

    stop = index if index is not None else len(flats)
    usable = None
    previous = None
    for i in range(stop):
        if high[i]:
            break
        if not reproducible[i] or flat_variance[i] <= 0:
            continue
        if previous is not None:
            if signal[i] < 0.99 * signal[previous]:
                break
            if signal[i] > 1.01 * signal[previous]:
                usable = i
        previous = i
    return clipped, index, evidence, usable


def characterize_photon_transfer(
    dark_frames_dn: DarkInput | None,
    flat_series: Sequence[CameraExposureSeries] | None,
    parameters: PhotonTransferParameters | None = None,
    *,
    aggregation_block_size: int = 1,
    dark_reference_exposure_s: float | None = None,
    short_dark_exposure_s: float | None = None,
) -> PhotonTransferCharacterization:
    """Estimate conversion gain, read noise and saturation capacity.

    For a shot-noise-limited linear sensor, the dark-corrected temporal
    variance grows linearly with the dark-corrected mean signal:
    ``variance_dn2 = mean_signal_dn / K`` where ``K`` is the conversion gain in
    electrons per LSB. Per-pixel temporal variances exclude fixed-pattern noise,
    so two frames per level are enough (equivalent to the pair-difference
    method).

    Args:
        dark_frames_dn: One dark stack or an exposure-in-seconds to stack mapping
        flat_series: Uniform-illumination stacks in increasing exposure order
        parameters: Fit range, stuck-pixel and validation settings
        aggregation_block_size: Maximum frames converted to float together
        dark_reference_exposure_s: Force a single correction at this exposure
        short_dark_exposure_s: Explicit camera-minimum bias for noise estimation

    Returns:
        Photon transfer curve, fitted gain and derived electron quantities

    Raises:
        CameraCharacterizationError: If inputs are invalid or the linear range
         cannot be fitted
    """
    parameters = parameters or PhotonTransferParameters()
    validation, dark_reference, valid_mask = prepare_dark_references(
        dark_frames_dn,
        flat_series,
        parameters.validation,
        aggregation_block_size,
        dark_reference_exposure_s,
        short_dark_exposure_s,
        exclude_stuck_pixels=parameters.exclude_stuck_pixels,
        check_flat_saturation=False,
    )
    assert flat_series is not None and dark_frames_dn is not None
    series_values = tuple(flat_series)
    darks = (
        dark_frames_dn
        if isinstance(dark_frames_dn, Mapping)
        else {dark_reference_exposure_s: dark_frames_dn}
    )
    plan = dark_reference.plan
    ceiling = parameters.validation.saturation_dn
    if valid_mask is None:
        valid_mask = np.ones(series_values[0].frames_dn[0].shape, dtype=bool)
        # Even when the user retains defects in the variance, they cannot
        # provide evidence of ADC clipping of the responding population.
        rail_mask = valid_mask.copy()
        for t in plan.used_exposures:
            mean = compute_image_stack_mean(darks[t], block_size=aggregation_block_size)
            rail_mask &= (mean > 0) & (mean < ceiling)
    else:
        rail_mask = valid_mask.copy()
    # A pixel stuck at one rail throughout the flat ladder cannot demonstrate
    # onset, even if it is not stuck in the dark.
    ever_below = np.zeros_like(rail_mask)
    ever_above = np.zeros_like(rail_mask)
    for level in series_values:
        for frame in level.frames_dn:
            ever_below |= frame < ceiling
            ever_above |= frame > 0
    rail_mask &= ever_below & ever_above
    del ever_below, ever_above
    valid_pixel_count = int(np.count_nonzero(valid_mask))
    if parameters.variance_mode == "centered_pairs" and valid_pixel_count < 2:
        raise _error("insufficient_pixels", "Pair centering needs at least two pixels")
    rail_population = int(np.count_nonzero(rail_mask))
    fraction = parameters.validation.saturation_fraction_warning
    rail_min_pixels = max(2, math.ceil(fraction * rail_population))

    flat_means: list[float] = []
    flat_variances: list[float] = []
    pairs = []
    for series in series_values:
        statistics = compute_image_stack_statistics(
            series.frames_dn,
            block_size=aggregation_block_size,
            ddof=1,
        )
        flat_means.append(float(np.mean(statistics.mean[valid_mask])))
        flat_variances.append(float(np.mean(statistics.variance[valid_mask])))
        del statistics
        pairs.append(
            _pair_statistics(
                series.frames_dn, valid_mask, rail_mask, ceiling, flat_variances[-1]
            )
        )

    exposure_times_s = np.array(
        [float(series.exposure_time_s) for series in series_values]
    )
    mean_signal_dn = np.array(flat_means) - dark_reference.mean_dn_by_level
    flat_temporal_variance_dn2 = np.array(flat_variances)
    raw_temporal_variance_dn2 = (
        flat_temporal_variance_dn2 - dark_reference.variance_dn2_by_level
    )
    dark_variances = dict(
        zip(plan.correction_exposures_s, dark_reference.variance_dn2_by_level)
    )
    dark_variances[plan.noise_exposure_s] = dark_reference.noise_variance_dn2
    dark_pairs = {
        t: _pair_statistics(darks[t], valid_mask, rail_mask, ceiling, dark_variances[t])
        for t in plan.used_exposures
    }
    correction_pairs = tuple(dark_pairs[t] for t in plan.correction_exposures_s)
    centered_temporal_variance_dn2 = np.array(
        [p.centered_variance_dn2 for p in pairs], dtype=float
    ) - np.array([d.centered_variance_dn2 for d in correction_pairs], dtype=float)
    temporal_variance_dn2 = (
        centered_temporal_variance_dn2
        if parameters.variance_mode == "centered_pairs"
        else raw_temporal_variance_dn2
    )
    clipped, saturation_index, evidence, usable = _response_limits(
        exposure_times_s,
        mean_signal_dn,
        tuple(pairs),
        correction_pairs,
        flat_temporal_variance_dn2,
        rail_min_pixels,
        fraction,
        parameters.stable_illumination,
    )
    diags = list(validation.diagnostics)
    if np.any(clipped):
        diags.append(
            CameraInputDiagnostic(
                CameraDiagnosticLevel.WARNING,
                "excessive_saturation",
                "Significant ADC clipping: SNR is not measurable at these levels",
                {
                    "exposures_s": exposure_times_s[clipped].tolist(),
                    "rail_population": rail_population,
                    "minimum_pixels": rail_min_pixels,
                },
            )
        )
    drifting_flats = [
        float(t) for t, p in zip(exposure_times_s, pairs) if p.common_mode_warning
    ]
    drifting_darks = [t for t, p in dark_pairs.items() if p.common_mode_warning]
    if drifting_flats or drifting_darks:
        diags.append(
            CameraInputDiagnostic(
                CameraDiagnosticLevel.WARNING,
                "frame_mean_fluctuation",
                "Frame means fluctuate: check camera and illumination stability. "
                "The raw variance includes the common mode.",
                {
                    "flat_exposures_s": drifting_flats,
                    "dark_exposures_s": drifting_darks,
                },
            )
        )
    # Never fit through clipping or into a demonstrated response plateau.
    # The variance peak is descriptive only and does not select data.
    fit_mask = (mean_signal_dn > 0) & ~clipped
    if saturation_index is not None:
        fit_mask[saturation_index:] = False
    if np.any(fit_mask):
        fit_mask &= mean_signal_dn <= (
            parameters.fit_upper_fraction * np.max(mean_signal_dn[fit_mask])
        )
    fit_level_count = int(np.count_nonzero(fit_mask))
    if (
        fit_level_count < parameters.minimum_fit_levels
        or np.unique(mean_signal_dn[fit_mask]).size < 2
    ):
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
    if not slope > 0.0 or np.ptp(temporal_variance_dn2[fit_mask]) == 0:
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
    # Compare like with like: the alternative estimate uses exactly the same
    # selected levels and is absent when its slope cannot identify a gain.
    alternate = (
        raw_temporal_variance_dn2
        if parameters.variance_mode == "centered_pairs"
        else centered_temporal_variance_dn2
    )[fit_mask]
    alternate_gain = None
    if np.isfinite(alternate).all() and np.ptp(alternate) > 0:
        alt_slope = np.polyfit(mean_signal_dn[fit_mask], alternate, deg=1)[0]
        if alt_slope > 0:
            alternate_gain = 1.0 / float(alt_slope)
    centered = parameters.variance_mode == "centered_pairs"
    dark_temporal_noise_dn = math.sqrt(dark_reference.noise_variance_dn2)
    dark_temporal_noise_e = conversion_gain_e_per_dn * dark_temporal_noise_dn
    index = saturation_index if saturation_index is not None else usable
    saturation_signal_dn = (
        float(mean_signal_dn[index])
        if index is not None
        and mean_signal_dn[index] > 0
        and correction_pairs[index].censored_fraction < fraction
        else None
    )
    saturation_capacity_e = (
        conversion_gain_e_per_dn * saturation_signal_dn
        if saturation_signal_dn is not None
        else None
    )
    dynamic_range_db = (
        20.0 * math.log10(saturation_capacity_e / dark_temporal_noise_e)
        if dark_temporal_noise_e > 0.0
        and saturation_capacity_e is not None
        and dark_pairs[plan.noise_exposure_s].censored_fraction < fraction
        else None
    )
    signal_electrons = conversion_gain_e_per_dn * mean_signal_dn
    flat_noise_dn = np.sqrt(flat_temporal_variance_dn2)
    snr_valid = ~clipped
    if evidence == "response_plateau":
        snr_valid[saturation_index:] = False
    measured_snr = np.divide(
        mean_signal_dn,
        flat_noise_dn,
        out=np.full_like(mean_signal_dn, np.nan),
        where=(flat_noise_dn > 0.0) & snr_valid,
    )
    model_noise_e = np.sqrt(
        np.maximum(signal_electrons, 0.0)
        + conversion_gain_e_per_dn**2 * dark_reference.variance_dn2_by_level
    )
    model_snr = np.divide(
        signal_electrons,
        model_noise_e,
        out=np.full_like(signal_electrons, np.nan),
        where=(model_noise_e > 0.0) & snr_valid,
    )

    return PhotonTransferCharacterization(
        validation=CameraInputValidation(diags),
        exposure_times_s=_readonly(exposure_times_s),
        mean_signal_dn=_readonly(mean_signal_dn),
        temporal_variance_dn2=_readonly(temporal_variance_dn2),
        fit_mask=_readonly(fit_mask),
        fit_slope_dn=float(slope),
        fit_intercept_dn2=float(intercept),
        fit_r_squared=fit_r_squared,
        fit_residuals_dn2=_readonly(fit_residuals_dn2),
        conversion_gain_e_per_dn=conversion_gain_e_per_dn,
        raw_gain_e_per_dn=alternate_gain if centered else conversion_gain_e_per_dn,
        centered_gain_e_per_dn=conversion_gain_e_per_dn if centered else alternate_gain,
        dark_mean_dn=dark_reference.noise_mean_dn,
        dark_temporal_noise_dn=dark_temporal_noise_dn,
        read_noise_e=dark_temporal_noise_e
        if dark_reference.read_noise_estimable
        else None,
        dark_temporal_noise_e=dark_temporal_noise_e,
        dark_reference=dark_reference,
        flat_temporal_variance_dn2=_readonly(flat_temporal_variance_dn2),
        raw_temporal_variance_dn2=_readonly(raw_temporal_variance_dn2),
        centered_temporal_variance_dn2=_readonly(centered_temporal_variance_dn2),
        variance_mode=parameters.variance_mode,
        flat_pairs=tuple(pairs),
        dark_pairs=tuple(dark_pairs.values()),
        variance_peak_index=int(np.argmax(temporal_variance_dn2)),
        clipped_mask=_readonly(clipped),
        rail_population=rail_population,
        rail_min_pixels=rail_min_pixels,
        saturation_index=saturation_index,
        usable_signal_index=usable,
        saturation_evidence=evidence,
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
