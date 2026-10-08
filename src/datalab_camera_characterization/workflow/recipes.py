"""Camera recipe registry."""

from __future__ import annotations

from datalab.plugins.recipes import (
    RecipeCardinality,
    RecipeDescriptor,
    RecipeInputSlot,
    RecipeMetadataRequirement,
    RecipeObjectType,
)

from .. import PLUGIN_ID, __version__
from .dark_current import DarkCurrentRecipeParameters, run_dark_current_characterization
from .input_checks import (
    check_dark_current_inputs,
    check_photon_transfer_inputs,
    check_relative_dn_inputs,
    suggest_dark_flat_bindings,
    suggest_dark_ramp_bindings,
)
from .photon_transfer import (
    PhotonTransferRecipeParameters,
    run_photon_transfer_characterization,
)
from .relative_dn import (
    EXPOSURE_TIME_METADATA_KEY,
    FRAME_ROLE_METADATA_KEY,
    CameraRecipeParameters,
    run_relative_dn_characterization,
)

EXPOSURE_TIME = RecipeMetadataRequirement(
    EXPOSURE_TIME_METADATA_KEY, "Exposure time in seconds"
)
FRAME_ROLE_HINT = RecipeMetadataRequirement(
    FRAME_ROLE_METADATA_KEY,
    "'dark' or 'flat'; without it, frames carrying an exposure time are flat",
    required=False,
)


def _dark_frames_slot() -> RecipeInputSlot:
    """Return the dark-frame slot shared by relative DN and photon transfer."""
    return RecipeInputSlot(
        "dark_frames",
        RecipeObjectType.IMAGE,
        RecipeCardinality.MANY,
        title="Dark frames",
        description=(
            "Frames acquired without light (shutter closed or sensor covered), "
            "with the same settings as the flat frames."
        ),
        min_count=2,
        metadata=(FRAME_ROLE_HINT,),
    )


def _flat_frames_slot(description: str) -> RecipeInputSlot:
    """Return a flat-frame slot: an exposure ladder of uniform illumination."""
    return RecipeInputSlot(
        "flat_frames",
        RecipeObjectType.IMAGE,
        RecipeCardinality.MANY,
        title="Flat frames",
        description=description,
        min_count=4,
        metadata=(EXPOSURE_TIME, FRAME_ROLE_HINT),
    )


RELATIVE_DN_RECIPE = RecipeDescriptor(
    recipe_id=f"{PLUGIN_ID}:relative-dn-characterization",
    plugin_version=__version__,
    title="Relative Camera characterization",
    version="1.1.0",
    description=(
        "Characterize dark and uniform-illumination image series with relative "
        "temporal and spatial metrics in digital numbers."
    ),
    inputs=(
        _dark_frames_slot(),
        _flat_frames_slot(
            "Uniformly illuminated frames at two or more exposure times, with "
            "two or more frames per exposure time."
        ),
    ),
    parameter_class=CameraRecipeParameters,
    run=run_relative_dn_characterization,
    suggest_bindings=suggest_dark_flat_bindings,
    check_inputs=check_relative_dn_inputs,
)

PHOTON_TRANSFER_RECIPE = RecipeDescriptor(
    recipe_id=f"{PLUGIN_ID}:photon-transfer",
    plugin_version=__version__,
    title="Photon transfer curve",
    version="1.0.0",
    description=(
        "Estimate conversion gain, read noise, saturation capacity and dynamic "
        "range from the temporal variance versus mean signal of dark and "
        "uniform-illumination series."
    ),
    inputs=(
        _dark_frames_slot(),
        _flat_frames_slot(
            "Uniformly illuminated frames on an exposure ladder from low signal "
            "up to saturation (five exposure times or more by default), with "
            "two or more frames per exposure time."
        ),
    ),
    parameter_class=PhotonTransferRecipeParameters,
    run=run_photon_transfer_characterization,
    suggest_bindings=suggest_dark_flat_bindings,
    check_inputs=check_photon_transfer_inputs,
)

DARK_CURRENT_RECIPE = RecipeDescriptor(
    recipe_id=f"{PLUGIN_ID}:dark-current",
    plugin_version=__version__,
    title="Dark current and hot pixels",
    version="1.0.0",
    description=(
        "Fit the dark signal of every pixel against exposure time to map dark "
        "current, its non-uniformity and isolated hot pixels."
    ),
    inputs=(
        RecipeInputSlot(
            "dark_frames",
            RecipeObjectType.IMAGE,
            RecipeCardinality.MANY,
            title="Dark ramp",
            description=(
                "Frames acquired without light at three or more exposure times "
                "(by default), with two or more frames per exposure time."
            ),
            min_count=4,
            metadata=(
                EXPOSURE_TIME,
                RecipeMetadataRequirement(
                    FRAME_ROLE_METADATA_KEY,
                    "Frames tagged 'flat' are left out",
                    required=False,
                ),
            ),
        ),
    ),
    parameter_class=DarkCurrentRecipeParameters,
    run=run_dark_current_characterization,
    suggest_bindings=suggest_dark_ramp_bindings,
    check_inputs=check_dark_current_inputs,
)

CAMERA_RECIPES: tuple[RecipeDescriptor, ...] = (
    RELATIVE_DN_RECIPE,
    PHOTON_TRANSFER_RECIPE,
    DARK_CURRENT_RECIPE,
)

__all__ = [
    "CAMERA_RECIPES",
    "DARK_CURRENT_RECIPE",
    "PHOTON_TRANSFER_RECIPE",
    "RELATIVE_DN_RECIPE",
]
