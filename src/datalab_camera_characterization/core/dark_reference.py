"""Exact-exposure dark references for illuminated camera measurements."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from numbers import Real

import numpy as np

from .aggregation import (
    ImageStackSource,
    _describe_image_stack,
    _iter_image_stack_blocks,
    compute_image_stack_mean,
    compute_image_stack_statistics,
)
from .errors import CameraCharacterizationError
from .validation import (
    CameraDiagnosticLevel,
    CameraExposureSeries,
    CameraInputDiagnostic,
    CameraInputValidation,
    CameraValidationParameters,
    _validate_stack,
    validate_camera_inputs,
)

# A bare stack designates one series, without claiming to know its exposure.
DarkInput = ImageStackSource | Mapping[float, ImageStackSource]
Exposure = float | None


def _error(code: str, message: str) -> CameraCharacterizationError:
    return CameraCharacterizationError(
        CameraInputValidation(
            (CameraInputDiagnostic(CameraDiagnosticLevel.ERROR, code, message),)
        )
    )


def _check_exposure(exposure: float) -> None:
    if (
        isinstance(exposure, bool)
        or not isinstance(exposure, Real)
        or not math.isfinite(exposure)
        or exposure < 0
    ):
        raise _error("invalid_exposure", f"Invalid exposure in seconds: {exposure!r}")


@dataclasses.dataclass(frozen=True)
class DarkReferencePlan:
    """Correction for each illuminated level and separate noise reference."""

    mode: str
    flat_exposures_s: tuple[float, ...]
    correction_exposures_s: tuple[Exposure, ...]
    correction_frame_counts: tuple[int, ...]
    noise_exposure_s: Exposure
    noise_frame_count: int
    noise_source: str

    @property
    def used_exposures(self) -> tuple[Exposure, ...]:
        """Return distinct exposures actually used, starting with the noise stack."""
        return tuple(
            dict.fromkeys((self.noise_exposure_s, *self.correction_exposures_s))
        )


def select_dark_references(
    counts: Mapping[Exposure, int],
    flat_exposures: Sequence[float],
    *,
    dark_reference_exposure_s: float | None = None,
    short_dark_exposure_s: float | None = None,
    minimum_frame_count: int = 2,
) -> DarkReferencePlan:
    """Resolve references from counts alone, without inspecting pixel data.

    Positive exposure is never evidence by itself of a negligible dark current:
    a non-zero short bias must be explicitly identified as the camera minimum.
    """
    times = tuple(flat_exposures)
    if not counts:
        raise _error("missing_dark_series", "Select repeated dark frames")
    if not times:
        raise _error("missing_flat_series", "Select an illuminated exposure ladder")
    for exposure in (*times, *(t for t in counts if t is not None)):
        _check_exposure(exposure)
    if None in counts and len(counts) != 1:
        raise _error(
            "unknown_dark_exposure",
            "Assign exposures to unlabelled dark frames, or remove them",
        )
    if dark_reference_exposure_s is not None:
        _check_exposure(dark_reference_exposure_s)
        if dark_reference_exposure_s not in counts:
            raise _error(
                "missing_selected_dark",
                f"No dark series at selected exposure {dark_reference_exposure_s} s",
            )
        correction = (dark_reference_exposure_s,) * len(times)
        mode = "explicit_single"
    elif all(t in counts for t in times):
        correction = times
        mode = "matched"
    elif len(counts) == 1:
        correction = (next(iter(counts)),) * len(times)
        mode = "single"
    else:
        missing = ", ".join(str(t) for t in times if t not in counts)
        raise _error(
            "incomplete_dark_coverage",
            f"No matching dark for {missing} s: complete the dark ladder or "
            "select one dark reference exposure explicitly",
        )

    if short_dark_exposure_s is not None:
        _check_exposure(short_dark_exposure_s)
        if (
            short_dark_exposure_s not in counts
            or any(t < short_dark_exposure_s for t in times)
            or any(t is not None and t < short_dark_exposure_s for t in counts)
        ):
            raise _error(
                "invalid_short_dark",
                "The short bias must be present at the minimum acquisition exposure",
            )
        noise, source = short_dark_exposure_s, "declared_short_bias"
    elif counts.get(0.0, 0) >= max(2, minimum_frame_count):
        noise, source = 0.0, "zero_exposure_bias"
    elif mode == "matched":
        noise = min(
            (
                t
                for t, n in counts.items()
                if t is not None and n >= max(2, minimum_frame_count)
            ),
            default=min(times),
        )
        source = "shortest_available_dark"
    else:
        noise, source = correction[0], "single_dark"

    plan = DarkReferencePlan(
        mode,
        times,
        correction,
        tuple(counts[t] for t in correction),
        noise,
        counts[noise],
        source,
    )
    for t in plan.used_exposures:
        if counts[t] < max(2, minimum_frame_count):
            raise _error(
                "insufficient_frames",
                f"Dark exposure {t} s has {counts[t]} frame(s); acquire at least "
                f"{max(2, minimum_frame_count)} repeats or explicitly select another "
                "reference",
            )
    return plan


@dataclasses.dataclass(frozen=True)
class DarkReferenceStatistics:
    """All scalar dark corrections, measured on the same population as the flats."""

    plan: DarkReferencePlan
    mean_dn_by_level: np.ndarray
    variance_dn2_by_level: np.ndarray
    noise_mean_dn: float
    noise_variance_dn2: float
    noise_status: str

    @property
    def read_noise_estimable(self) -> bool:
        """Only a measured, uncensored short bias qualifies."""
        return self.noise_status == "estimated_read_noise"


def prepare_dark_references(
    dark: DarkInput | None,
    flats: Sequence[CameraExposureSeries] | None,
    parameters: CameraValidationParameters,
    block_size: int,
    dark_reference_exposure_s: Exposure,
    short_dark_exposure_s: Exposure,
    *,
    exclude_stuck_pixels: bool = False,
    check_flat_saturation: bool = True,
) -> tuple[CameraInputValidation, DarkReferenceStatistics, np.ndarray | None]:
    """Validate stacks and aggregate unique dark exposures in bounded memory."""
    groups = dark if isinstance(dark, Mapping) else {dark_reference_exposure_s: dark}
    if dark is None:
        raise _error("missing_dark_series", "Select repeated dark frames")
    if flats is not None and any(
        not isinstance(f, CameraExposureSeries) for f in flats
    ):
        raise _error("invalid_flat_series", "Expected CameraExposureSeries values")
    # Counts allow the exact same reference decision in the lightweight host check.
    try:
        counts = {t: len(stack) for t, stack in groups.items()}
    except TypeError as error:
        raise _error("invalid_stack_type", "Expected dark frame stacks") from error
    plan = select_dark_references(
        counts,
        [f.exposure_time_s for f in flats] if flats is not None else (),
        dark_reference_exposure_s=dark_reference_exposure_s,
        short_dark_exposure_s=short_dark_exposure_s,
        minimum_frame_count=parameters.minimum_frame_count,
    )
    noise_stack = groups[plan.noise_exposure_s]
    validation = validate_camera_inputs(
        noise_stack,
        flats,
        parameters,
        aggregation_block_size=block_size,
        check_flat_saturation=check_flat_saturation,
    )
    if validation.has_errors:
        raise CameraCharacterizationError(validation)
    diagnostics = list(validation.diagnostics)
    ref = _describe_image_stack(noise_stack)
    for t in plan.used_exposures[1:]:
        name = f"dark[{t} s]"
        info = _validate_stack(groups[t], name, parameters, block_size, diagnostics)
        if info and info.spatial_shape != ref.spatial_shape:
            raise _error("shape_mismatch", f"{name} has a different image size")
        if info and info.dtype != ref.dtype:
            raise _error("dtype_mismatch", f"{name} has a different dtype")
    validation = CameraInputValidation(diagnostics)
    if validation.has_errors:
        raise CameraCharacterizationError(validation)

    # Fixed PTC population across all corrections and the noise reference.
    mask = None
    if exclude_stuck_pixels:
        mask = np.ones(ref.spatial_shape, dtype=bool)
        for t in plan.used_exposures:
            mean = compute_image_stack_mean(groups[t], block_size=block_size)
            mask &= (mean > 0) & (mean < parameters.saturation_dn)
            del mean
        if not np.any(mask):
            raise _error("no_valid_pixels", "No off-rail pixels common to the darks")

    means, variances = {}, {}
    for t in plan.used_exposures:
        stats = compute_image_stack_statistics(groups[t], block_size=block_size)
        means[t] = (
            stats.mean_value if mask is None else float(np.mean(stats.mean[mask]))
        )
        variances[t] = (
            stats.mean_variance
            if mask is None
            else float(np.mean(stats.variance[mask]))
        )
        del stats
    status = "dark_temporal_noise"
    if plan.noise_source in ("declared_short_bias", "zero_exposure_bias"):
        rail_count = 0
        for block in _iter_image_stack_blocks(noise_stack, block_size):
            values = block if mask is None else block[:, mask]
            rail_count += np.count_nonzero(
                (values <= 0) | (values >= parameters.saturation_dn)
            )
        pixels = (
            math.prod(ref.spatial_shape) if mask is None else np.count_nonzero(mask)
        )
        if (
            rail_count / (pixels * plan.noise_frame_count)
            >= parameters.saturation_fraction_warning
        ):
            status = "clipped_short_bias"
        elif variances[plan.noise_exposure_s] <= 0:
            status = "unresolved_short_bias"
        else:
            status = "estimated_read_noise"
    mean_dn = np.array([means[t] for t in plan.correction_exposures_s])
    variance_dn2 = np.array([variances[t] for t in plan.correction_exposures_s])
    mean_dn.setflags(write=False)
    variance_dn2.setflags(write=False)
    return (
        validation,
        DarkReferenceStatistics(
            plan,
            mean_dn,
            variance_dn2,
            means[plan.noise_exposure_s],
            variances[plan.noise_exposure_s],
            status,
        ),
        mask,
    )
