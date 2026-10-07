"""DataLab Desktop plugin adapter.

DataLab runs the recipes through its generic interaction: it assigns the
selected frames to the recipe inputs from their metadata, checks them, edits
the parameters, then runs the recipe.
"""

from __future__ import annotations

from datalab.config import _
from datalab.plugin_examples import PluginExample, PluginExampleData
from datalab.plugin_tiles import WelcomeTile
from datalab.plugins import PluginBase, PluginCapability, PluginInfo
from datalab.recipes import RecipeOutcome

from .. import (
    PLUGIN_DESCRIPTION,
    PLUGIN_ID,
    PLUGIN_NAME,
    __version__,
)
from ..demo import DARK_RAMP_DEMO, PHOTON_TRANSFER_DEMO, materialize_generated_example
from ..workflow import (
    CAMERA_RECIPES,
    DARK_CURRENT_RECIPE,
    PHOTON_TRANSFER_RECIPE,
    RELATIVE_DN_RECIPE,
)

PLUGIN_ICON = "datalab_camera_characterization:icons/camera_characterization.svg"
DEMO_ICON = "datalab_camera_characterization:icons/camera_demo.svg"

CAMERA_QUICKSTART = PluginExample(
    id="quickstart",
    title=_("Relative-DN Camera quickstart"),
    description=_("Synthetic dark and flat frames for a first Camera characterization"),
    resource=("datalab_camera_characterization:examples/camera_quickstart.h5"),
    recipe_ids=(RELATIVE_DN_RECIPE.recipe_id,),
    expected_checks=(
        "response-curve",
        "mean-dark-image",
        "mean-flat-image",
        "anchored-metrics-table",
    ),
)


class CameraDetectorCharacterizationPlugin(PluginBase):
    """Expose Camera characterization to DataLab Desktop."""

    PLUGIN_INFO = PluginInfo(
        id=PLUGIN_ID,
        name=PLUGIN_NAME,
        version=__version__,
        description=PLUGIN_DESCRIPTION,
        icon=PLUGIN_ICON,
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
    WELCOME_TILES = (
        WelcomeTile(
            id="application",
            title=PLUGIN_NAME,
            description=PLUGIN_DESCRIPTION,
            icon=PLUGIN_ICON,
        ),
        WelcomeTile(
            id="quickstart",
            title=_("Open quickstart example"),
            description=_("Open and select the packaged synthetic Camera campaign"),
            icon=DEMO_ICON,
            launcher="open_quickstart",
        ),
    )

    @classmethod
    def materialize_example(cls, example_id: str) -> PluginExampleData | None:
        """Generate in-memory examples; the quickstart stays a packaged file."""
        cls.get_example(example_id)
        return materialize_generated_example(example_id)

    def run_relative_dn(self) -> RecipeOutcome | None:
        """Run the relative-DN characterization on the selected frames."""
        return self.start_recipe(RELATIVE_DN_RECIPE.recipe_id)

    def run_photon_transfer(self) -> RecipeOutcome | None:
        """Run the photon transfer analysis on the selected frames."""
        return self.start_recipe(PHOTON_TRANSFER_RECIPE.recipe_id)

    def run_dark_current(self) -> RecipeOutcome | None:
        """Run the dark-current analysis on the selected dark ramp."""
        return self.start_recipe(DARK_CURRENT_RECIPE.recipe_id)

    def open_quickstart(self) -> PluginExample | None:
        """Open the packaged quickstart and select all Camera input images."""
        if self.main is None:
            raise RuntimeError("Plugin must be registered before opening quickstart")
        if not self.main.confirm_memory_state():
            return None
        if any(len(panel) for panel in (self.signalpanel, self.imagepanel)) and not (
            self.ask_yesno(
                _("Opening the quickstart replaces the current workspace. Continue?"),
                title=_("Open quickstart example"),
            )
        ):
            return None
        example = self.open_example(CAMERA_QUICKSTART.id, reset_all=True)
        images = self.imagepanel.objmodel.get_all_objects()
        self.imagepanel.objview.select_objects(images)
        return example

    def launch_example(self, example_id: str) -> PluginExample | None:
        """Open one catalog example and select its images."""
        self.get_example(example_id)
        if example_id == CAMERA_QUICKSTART.id:
            return self.open_quickstart()
        return super().launch_example(example_id)

    def open_photon_transfer_example(self) -> PluginExample | None:
        """Open the generated photon transfer campaign from the plugin menu."""
        return self.launch_example(PHOTON_TRANSFER_DEMO.id)

    def open_dark_ramp_example(self) -> PluginExample | None:
        """Open the generated dark-ramp campaign from the plugin menu."""
        return self.launch_example(DARK_RAMP_DEMO.id)

    def create_actions(self) -> None:
        """Create the Camera example and recipe actions."""
        handler = self.imagepanel.acthandler
        with handler.new_menu(PLUGIN_NAME.replace("&", "&&")):
            self.open_quickstart_action = handler.new_action(
                _("Open quickstart example"),
                triggered=self.open_quickstart,
                tip=_("Open and select the packaged synthetic Camera campaign"),
                select_condition="always",
            )
            self.open_photon_transfer_action = handler.new_action(
                _("Open photon transfer example"),
                triggered=self.open_photon_transfer_example,
                tip=_("Generate and select a synthetic photon transfer campaign"),
                select_condition="always",
            )
            self.open_dark_ramp_action = handler.new_action(
                _("Open dark-ramp example"),
                triggered=self.open_dark_ramp_example,
                tip=_("Generate and select a synthetic dark-frame exposure ramp"),
                select_condition="always",
            )
            self.run_relative_dn_action = handler.new_action(
                _("Run camera characterization..."),
                triggered=self.run_relative_dn,
                tip=_("Characterize the selected dark and flat frames"),
                select_condition="at_least_one",
                separator=True,
            )
            self.run_photon_transfer_action = handler.new_action(
                _("Run photon transfer analysis..."),
                triggered=self.run_photon_transfer,
                tip=_("Estimate conversion gain, read noise and saturation capacity"),
                select_condition="at_least_one",
            )
            self.run_dark_current_action = handler.new_action(
                _("Run dark-current analysis..."),
                triggered=self.run_dark_current,
                tip=_("Map dark current and hot pixels from a dark exposure ramp"),
                select_condition="at_least_one",
            )
