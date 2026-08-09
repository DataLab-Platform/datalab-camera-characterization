"""Thin DataLab-Web adapter for the bundled Camera workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import resources

from datalab.recipes import (
    RecipeExecutionContext,
    RecipeInputs,
    RecipeOutcome,
    RecipeValidationError,
)
from sigima.objects import ImageObj

from .. import PLUGIN_ID, __version__
from ..workflow import (
    EXPOSURE_TIME_METADATA_KEY,
    RELATIVE_DN_RECIPE,
    CameraRecipeParameters,
)

WEB_STATUS = "untested"
DATALAB_WEB_VERSION = "0.8.0"
PYODIDE_VERSION = "0.26.4"
QUICKSTART_FILENAME = "camera_quickstart.h5"


def get_web_manifest() -> dict[str, str]:
    """Return the explicit browser bundle and compatibility contract."""
    return {
        "plugin_id": PLUGIN_ID,
        "plugin_version": __version__,
        "web_status": WEB_STATUS,
        "datalab_web_version": DATALAB_WEB_VERSION,
        "pyodide_version": PYODIDE_VERSION,
        "recipe_id": RELATIVE_DN_RECIPE.recipe_id,
        "recipe_version": RELATIVE_DN_RECIPE.version,
        "quickstart_filename": QUICKSTART_FILENAME,
    }


def read_quickstart_bytes() -> bytes:
    """Read the packaged HDF5 quickstart without arbitrary filesystem access."""
    return (
        resources.files("datalab_camera_characterization")
        .joinpath("examples")
        .joinpath(QUICKSTART_FILENAME)
        .read_bytes()
    )


def build_recipe_inputs(images: Sequence[ImageObj]) -> RecipeInputs:
    """Map browser-imported images to Camera roles using stable metadata.

    Flat frames carry :data:`EXPOSURE_TIME_METADATA_KEY`; images without that
    key are dark frames. The browser UI remains responsible for passing only
    the images selected for one campaign.
    """
    image_values = tuple(images)
    if any(not isinstance(image, ImageObj) for image in image_values):
        raise RecipeValidationError("Camera Web inputs must be image objects")
    dark_frames = tuple(
        image
        for image in image_values
        if EXPOSURE_TIME_METADATA_KEY not in image.metadata
    )
    flat_frames = tuple(
        image for image in image_values if EXPOSURE_TIME_METADATA_KEY in image.metadata
    )
    if not dark_frames:
        raise RecipeValidationError("Camera Web inputs require dark frames")
    if not flat_frames:
        raise RecipeValidationError("Camera Web inputs require flat frames")
    return {
        "dark_frames": dark_frames,
        "flat_frames": flat_frames,
    }


def run_relative_dn_recipe(
    images: Sequence[ImageObj],
    parameter_values: Mapping[str, object] | None = None,
    context: RecipeExecutionContext | None = None,
) -> RecipeOutcome:
    """Run the shared recipe for browser-imported images without GUI calls."""
    parameters = CameraRecipeParameters()
    for name, value in dict(parameter_values or {}).items():
        if not isinstance(name, str) or not hasattr(parameters, name):
            raise RecipeValidationError(f"Unknown Camera recipe parameter: {name!r}")
        setattr(parameters, name, value)
    return RELATIVE_DN_RECIPE.run(
        build_recipe_inputs(images),
        parameters,
        context or RecipeExecutionContext(),
    )


__all__ = [
    "DATALAB_WEB_VERSION",
    "PYODIDE_VERSION",
    "QUICKSTART_FILENAME",
    "WEB_STATUS",
    "build_recipe_inputs",
    "get_web_manifest",
    "read_quickstart_bytes",
    "run_relative_dn_recipe",
]
