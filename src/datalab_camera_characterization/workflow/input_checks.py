"""Shared Camera acquisition preflight and execution gate."""

from __future__ import annotations

from collections.abc import Sequence

import guidata.dataset as gds
from datalab.plugins.recipes import (
    RecipeDiagnostic,
    RecipeExecutionContext,
    RecipeInputs,
    RecipeValidationError,
)
from sigima.objects import ImageObj

from .adc import (
    Acquisition,
    CameraADCParameters,
    P,
    explicit_frame_role,
    inspect_acquisition,
)
from .dark_reference import _image_exposure, check_dark_reference_inputs


def suggest_dark_flat_bindings(
    candidates: Sequence[ImageObj],
) -> dict[str, tuple[ImageObj, ...]]:
    """If even one role is ambiguous, ask for bindings; do not drop candidates."""
    if any(explicit_frame_role(image) is None for image in candidates):
        return {}
    return {
        role: tuple(image for image in candidates if explicit_frame_role(image) == name)
        for role, name in (("dark_frames", "dark"), ("flat_frames", "flat"))
    }


def suggest_dark_ramp_bindings(
    candidates: Sequence[ImageObj],
) -> dict[str, tuple[ImageObj, ...]]:
    """An empty suggestion suppresses the host's automatic single-slot fallback."""
    if any(explicit_frame_role(image) is None for image in candidates):
        return {"dark_frames": ()}
    return {
        "dark_frames": tuple(
            image for image in candidates if explicit_frame_role(image) == "dark"
        )
    }


def _error(code: str, message: str) -> RecipeDiagnostic:
    """Return one blocking diagnostic."""
    return RecipeDiagnostic("error", code, message)


def _exposure_counts(images: Sequence[ImageObj], role: str) -> dict[float, int]:
    """Return the number of frames at each exposure time."""
    counts: dict[float, int] = {}
    for image in images:
        exposure = _image_exposure(image, role)
        counts[exposure] = counts.get(exposure, 0) + 1
    return counts


def _ladder_diagnostics(
    counts: dict[float, int],
    role: str,
    minimum_levels: int,
    minimum_frames: int,
) -> list[RecipeDiagnostic]:
    """Require enough exposure levels with enough frames each."""
    diagnostics: list[RecipeDiagnostic] = []
    if len(counts) < minimum_levels:
        diagnostics.append(
            _error(
                f"insufficient-{role.casefold()}-levels",
                f"{role} frames cover {len(counts)} exposure time(s); "
                f"at least {minimum_levels} are required",
            )
        )
    short = sorted(
        exposure for exposure, count in counts.items() if count < minimum_frames
    )
    if short:
        levels = ", ".join(f"{exposure:g} s" for exposure in short)
        diagnostics.append(
            _error(
                f"insufficient-{role.casefold()}-frames",
                f"{role} exposure times with fewer than {minimum_frames} frames: "
                f"{levels}",
            )
        )
    return diagnostics


def _dark_count_diagnostics(
    images: Sequence[ImageObj], minimum_frames: int
) -> list[RecipeDiagnostic]:
    """Require enough dark frames for temporal statistics."""
    if len(images) < minimum_frames:
        return [
            _error(
                "insufficient-dark-frames",
                f"{len(images)} dark frame(s); at least {minimum_frames} are required",
            )
        ]
    return []


def _inspect_inputs(
    inputs: RecipeInputs,
    parameters: CameraADCParameters,
    ramp: bool,
    context: RecipeExecutionContext | None = None,
) -> tuple[Acquisition | None, list[RecipeDiagnostic]]:
    slots = ("dark_frames",) if ramp else ("dark_frames", "flat_frames")
    try:
        acquisition, declarations = inspect_acquisition(
            inputs, parameters, slots, context
        )
    except RecipeValidationError as error:
        return None, [_error("invalid-acquisition", str(error))]
    try:
        count = int(parameters.minimum_frame_count)
        if ramp:
            diagnostics = _ladder_diagnostics(
                _exposure_counts(inputs["dark_frames"], "Dark"),
                "Dark",
                int(parameters.minimum_exposure_levels),
                count,
            )
        else:
            diagnostics = [
                *_dark_count_diagnostics(inputs["dark_frames"], count),
                *_ladder_diagnostics(
                    _exposure_counts(inputs["flat_frames"], "Flat"),
                    "Flat",
                    int(parameters.minimum_flat_levels),
                    count,
                ),
                *check_dark_reference_inputs(inputs, parameters),
            ]
    except RecipeValidationError as error:
        return None, [_error("invalid-exposure", str(error))]
    return acquisition, declarations + diagnostics


def prepare_camera_inputs(
    inputs: RecipeInputs,
    parameters: P,
    context: RecipeExecutionContext,
    *,
    ramp: bool = False,
) -> tuple[RecipeInputs, P]:
    """Require every input declaration, including those editable after assignment."""
    context.raise_if_cancelled()
    acquisition, diagnostics = _inspect_inputs(inputs, parameters, ramp, context)
    # All diagnostics here are unmet prerequisites. Warnings only authorize
    # opening the host's parameter editor; they never authorize computation.
    if acquisition is None or diagnostics:
        raise RecipeValidationError("; ".join(item.message for item in diagnostics))
    return acquisition.normalize(parameters, context)


def check_relative_dn_inputs(
    inputs: RecipeInputs, parameters: gds.DataSet | None
) -> list[RecipeDiagnostic]:
    """Check dark frames and the flat exposure ladder of relative LSB."""
    from .relative_dn import CameraRecipeParameters

    if not isinstance(parameters, CameraRecipeParameters):
        parameters = CameraRecipeParameters()
    return _inspect_inputs(inputs, parameters, False)[1]


def check_photon_transfer_inputs(
    inputs: RecipeInputs, parameters: gds.DataSet | None
) -> list[RecipeDiagnostic]:
    """Check dark frames and the flat exposure ladder of the photon transfer."""
    from .photon_transfer import PhotonTransferRecipeParameters

    if not isinstance(parameters, PhotonTransferRecipeParameters):
        parameters = PhotonTransferRecipeParameters()
    return _inspect_inputs(inputs, parameters, False)[1]


def check_dark_current_inputs(
    inputs: RecipeInputs, parameters: gds.DataSet | None
) -> list[RecipeDiagnostic]:
    """Check the dark exposure ladder of the dark-current method."""
    from .dark_current import DarkCurrentRecipeParameters

    if not isinstance(parameters, DarkCurrentRecipeParameters):
        parameters = DarkCurrentRecipeParameters()
    return _inspect_inputs(inputs, parameters, True)[1]


__all__ = [
    "check_dark_current_inputs",
    "check_photon_transfer_inputs",
    "check_relative_dn_inputs",
    "suggest_dark_flat_bindings",
    "suggest_dark_ramp_bindings",
]
