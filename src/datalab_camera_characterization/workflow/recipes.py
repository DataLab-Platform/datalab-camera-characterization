"""Camera recipe registry."""

from __future__ import annotations

from datalab.recipes import (
    RecipeCardinality,
    RecipeDescriptor,
    RecipeInputSlot,
    RecipeObjectType,
)

from .. import PLUGIN_ID, __version__
from .relative_dn import CameraRecipeParameters, run_relative_dn_characterization

RELATIVE_DN_RECIPE = RecipeDescriptor(
    recipe_id=f"{PLUGIN_ID}:relative-dn-characterization",
    plugin_version=__version__,
    title="Relative Camera characterization",
    version="1.0.0",
    description=(
        "Characterize dark and uniform-illumination image series with relative "
        "metrics in digital numbers."
    ),
    inputs=(
        RecipeInputSlot(
            "dark_frames",
            RecipeObjectType.IMAGE,
            RecipeCardinality.MANY,
        ),
        RecipeInputSlot(
            "flat_frames",
            RecipeObjectType.IMAGE,
            RecipeCardinality.MANY,
        ),
    ),
    parameter_class=CameraRecipeParameters,
    run=run_relative_dn_characterization,
)

CAMERA_RECIPES: tuple[RecipeDescriptor, ...] = (RELATIVE_DN_RECIPE,)

__all__ = ["CAMERA_RECIPES", "RELATIVE_DN_RECIPE"]
