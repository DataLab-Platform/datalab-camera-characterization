"""Thin DataLab-Web adapter for the bundled Camera workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import resources

from datalab.plugin_examples import PluginExample, PluginExampleData
from datalab.plugins import PluginBase, PluginCapability, PluginInfo
from datalab.recipes import (
    RecipeExecutionContext,
    RecipeInputs,
    RecipeOutcome,
    RecipeValidationError,
)
from sigima.objects import ImageObj

from .. import PLUGIN_DESCRIPTION, PLUGIN_ID, PLUGIN_NAME, __version__
from ..demo import DARK_RAMP_DEMO, PHOTON_TRANSFER_DEMO, materialize_generated_example
from ..simulator import CAMERA_SIMULATOR_TOOL, CameraSimulator
from ..workflow import (
    CAMERA_RECIPES,
    RELATIVE_DN_RECIPE,
    CameraRecipeParameters,
    infer_frame_role,
)

WEB_STATUS = "verified"
DATALAB_WEB_VERSION = "0.9.0"
PYODIDE_VERSION = "0.26.4"
QUICKSTART_FILENAME = "camera_quickstart.h5"

CAMERA_QUICKSTART = PluginExample(
    id="quickstart",
    title="Synthetic camera characterization",
    resource=("datalab_camera_characterization:examples/camera_quickstart.h5"),
    description="Physically structured dark and flat frames for relative-DN analysis.",
    recipe_ids=(RELATIVE_DN_RECIPE.recipe_id,),
)


class CameraDetectorCharacterizationWebPlugin(PluginBase):
    """Declare the Camera application contract supported by DataLab-Web."""

    PLUGIN_INFO = PluginInfo(
        id=PLUGIN_ID,
        name=PLUGIN_NAME,
        version=__version__,
        description=PLUGIN_DESCRIPTION,
        capabilities=(
            PluginCapability.APPLICATION,
            PluginCapability.PROCESSING,
        ),
        documentation_url=(
            "https://github.com/DataLab-Platform/datalab-camera-characterization"
        ),
    )
    RECIPES = CAMERA_RECIPES
    EXAMPLES = (CAMERA_QUICKSTART, PHOTON_TRANSFER_DEMO, DARK_RAMP_DEMO)
    TOOLS = (CAMERA_SIMULATOR_TOOL,)

    def create_actions(self) -> None:
        """Application actions are provided by DataLab-Web's generic host."""

    def camera_simulator(self) -> CameraSimulator:
        """Return a new scientific camera simulator."""
        return CameraSimulator()

    @classmethod
    def materialize_example(cls, example_id: str) -> PluginExampleData | None:
        """Generate in-memory examples; the quickstart stays a packaged file."""
        cls.get_example(example_id)
        return materialize_generated_example(example_id)


def get_web_manifest() -> dict[str, object]:
    """Return the explicit browser bundle and compatibility contract."""
    return {
        "plugin_id": PLUGIN_ID,
        "plugin_version": __version__,
        "web_status": WEB_STATUS,
        "datalab_web_version": DATALAB_WEB_VERSION,
        "pyodide_version": PYODIDE_VERSION,
        "recipes": [
            {"recipe_id": recipe.recipe_id, "recipe_version": recipe.version}
            for recipe in CAMERA_RECIPES
        ],
        "examples": [
            example.id
            for example in CameraDetectorCharacterizationWebPlugin.get_examples()
        ],
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

    An explicit frame-role metadata value wins; otherwise flat frames carry an
    exposure time and images without one are dark frames. The browser UI
    remains responsible for passing only the images selected for one campaign.
    """
    image_values = tuple(images)
    if any(not isinstance(image, ImageObj) for image in image_values):
        raise RecipeValidationError("Camera Web inputs must be image objects")
    dark_frames = tuple(
        image for image in image_values if infer_frame_role(image) == "dark"
    )
    flat_frames = tuple(
        image for image in image_values if infer_frame_role(image) == "flat"
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
    "CAMERA_QUICKSTART",
    "CameraDetectorCharacterizationWebPlugin",
    "DATALAB_WEB_VERSION",
    "PYODIDE_VERSION",
    "QUICKSTART_FILENAME",
    "WEB_STATUS",
    "build_recipe_inputs",
    "get_web_manifest",
    "read_quickstart_bytes",
    "run_relative_dn_recipe",
]
