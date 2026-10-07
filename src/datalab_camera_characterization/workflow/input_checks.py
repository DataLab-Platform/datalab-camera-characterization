"""Fast checks of Camera recipe inputs, run by hosts before any computation.

They only read metadata, shapes and counts, so that DataLab can tell whether
the current selection suits a method while the user selects frames.
"""

from __future__ import annotations

from collections.abc import Sequence

import guidata.dataset as gds
import numpy as np
from datalab.recipes import RecipeDiagnostic, RecipeInputs
from sigima.objects import ImageObj

from .dark_current import DarkCurrentRecipeParameters
from .photon_transfer import PhotonTransferRecipeParameters
from .relative_dn import (
    FRAME_ROLE_METADATA_KEY,
    CameraRecipeParameters,
    _image_exposure,
    infer_frame_role,
)


def suggest_dark_flat_bindings(
    candidates: Sequence[ImageObj],
) -> dict[str, tuple[ImageObj, ...]]:
    """Assign frames to the dark and flat slots from their metadata."""
    return {
        role: tuple(image for image in candidates if infer_frame_role(image) == name)
        for role, name in (("dark_frames", "dark"), ("flat_frames", "flat"))
    }


def suggest_dark_ramp_bindings(
    candidates: Sequence[ImageObj],
) -> dict[str, tuple[ImageObj, ...]]:
    """Assign every frame not explicitly tagged as flat to the dark ramp.

    Dark-ramp frames carry an exposure time, so the relative-DN convention
    (frames with an exposure time are flat) does not apply here.
    """
    return {
        "dark_frames": tuple(
            image
            for image in candidates
            if image.metadata.get(FRAME_ROLE_METADATA_KEY) != "flat"
        )
    }


def _error(code: str, message: str) -> RecipeDiagnostic:
    """Return one blocking diagnostic."""
    return RecipeDiagnostic("error", code, message)


def _shape_diagnostics(inputs: RecipeInputs) -> list[RecipeDiagnostic]:
    """Require one frame size across all slots."""
    shapes = {np.shape(image.data) for images in inputs.values() for image in images}
    if len(shapes) > 1:
        sizes = ", ".join("x".join(str(size) for size in shape) for shape in shapes)
        return [_error("inconsistent-frame-size", f"Frames differ in size: {sizes}")]
    return []


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


def _check_dark_flat(
    inputs: RecipeInputs, minimum_frames: int, minimum_levels: int
) -> list[RecipeDiagnostic]:
    """Check dark frames and the flat exposure ladder."""
    return [
        *_shape_diagnostics(inputs),
        *_dark_count_diagnostics(inputs["dark_frames"], minimum_frames),
        *_ladder_diagnostics(
            _exposure_counts(inputs["flat_frames"], "Flat"),
            "Flat",
            minimum_levels,
            minimum_frames,
        ),
    ]


def check_relative_dn_inputs(
    inputs: RecipeInputs, parameters: gds.DataSet | None
) -> list[RecipeDiagnostic]:
    """Check dark frames and the flat exposure ladder of relative DN."""
    if not isinstance(parameters, CameraRecipeParameters):
        parameters = CameraRecipeParameters()
    return _check_dark_flat(
        inputs,
        int(parameters.minimum_frame_count),
        int(parameters.minimum_flat_levels),
    )


def check_photon_transfer_inputs(
    inputs: RecipeInputs, parameters: gds.DataSet | None
) -> list[RecipeDiagnostic]:
    """Check dark frames and the flat exposure ladder of the photon transfer."""
    if not isinstance(parameters, PhotonTransferRecipeParameters):
        parameters = PhotonTransferRecipeParameters()
    return _check_dark_flat(
        inputs,
        int(parameters.minimum_frame_count),
        int(parameters.minimum_flat_levels),
    )


def check_dark_current_inputs(
    inputs: RecipeInputs, parameters: gds.DataSet | None
) -> list[RecipeDiagnostic]:
    """Check the dark exposure ladder of the dark-current method."""
    if not isinstance(parameters, DarkCurrentRecipeParameters):
        parameters = DarkCurrentRecipeParameters()
    return [
        *_shape_diagnostics(inputs),
        *_ladder_diagnostics(
            _exposure_counts(inputs["dark_frames"], "Dark"),
            "Dark",
            int(parameters.minimum_exposure_levels),
            int(parameters.minimum_frame_count),
        ),
    ]


__all__ = [
    "check_dark_current_inputs",
    "check_photon_transfer_inputs",
    "check_relative_dn_inputs",
    "suggest_dark_flat_bindings",
    "suggest_dark_ramp_bindings",
]
