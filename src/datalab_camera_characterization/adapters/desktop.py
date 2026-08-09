"""DataLab Desktop plugin adapter."""

from __future__ import annotations

from collections.abc import Sequence

import guidata.dataset as gds
from datalab.config import _
from datalab.gui.recipe_runner import RecipeCommitError, RecipeRunner
from datalab.objectmodel import get_uuid
from datalab.plugin_examples import PluginExample
from datalab.plugins import PluginBase, PluginCapability, PluginInfo
from datalab.recipes import RecipeInputs, RecipeOutcome, RecipeValidationError
from sigima.objects import ImageObj

from .. import (
    PLUGIN_DESCRIPTION,
    PLUGIN_ID,
    PLUGIN_NAME,
    __version__,
)
from ..core import CameraCharacterizationError
from ..workflow import CAMERA_RECIPES, CameraRecipeParameters
from ..workflow.recipes import RELATIVE_DN_RECIPE

MINIMUM_SELECTED_FRAME_COUNT = 6

CAMERA_QUICKSTART = PluginExample(
    id="quickstart",
    title=_("Relative-DN Camera quickstart"),
    description=_("Synthetic dark and flat frames for a first Camera characterization"),
    resource=("datalab_camera_characterization:examples/camera_quickstart.h5"),
    recipe_id=RELATIVE_DN_RECIPE.recipe_id,
    expected_checks=(
        "response-curve",
        "mean-dark-image",
        "mean-flat-image",
        "anchored-metrics-table",
    ),
)


class CameraInputRoleParameters(
    gds.DataSet,
    title=_("Camera input roles"),
):
    """Assign selected images to the dark and flat recipe input slots."""

    @classmethod
    def create(cls, images: Sequence[ImageObj]) -> CameraInputRoleParameters:
        """Create a form containing one required role choice per image."""
        image_values = tuple(images)
        if len({get_uuid(image) for image in image_values}) != len(image_values):
            raise RecipeValidationError(_("Selected Camera images must be unique"))
        role_fields: dict[str, gds.ChoiceItem] = {}
        for index, image in enumerate(image_values):
            field_name = f"role_{index:04d}"
            image_title = image.title if isinstance(image.title, str) else ""
            display_title = image_title or _("Untitled image")
            default_role = "dark" if "dark" in image_title.casefold() else "flat"
            role_fields[field_name] = gds.ChoiceItem(
                f"{index + 1}. {display_title}",
                (("dark", _("Dark")), ("flat", _("Flat"))),
                default=default_role,
                radio=True,
            )
        form_class = type(
            cls.__name__,
            (cls,),
            {"__module__": cls.__module__, **role_fields},
        )
        return form_class(image_values, tuple(role_fields))

    def __init__(
        self,
        images: Sequence[ImageObj] = (),
        role_fields: Sequence[str] = (),
    ) -> None:
        self._images_by_field = dict(zip(role_fields, images))
        super().__init__()

    def to_recipe_inputs(self) -> RecipeInputs:
        """Validate role assignments and return inputs in selection order."""
        dark_frames = tuple(
            image
            for field_name, image in self._images_by_field.items()
            if getattr(self, field_name) == "dark"
        )
        flat_frames = tuple(
            image
            for field_name, image in self._images_by_field.items()
            if getattr(self, field_name) == "flat"
        )
        if not dark_frames:
            raise RecipeValidationError(_("Assign at least one dark frame"))
        if not flat_frames:
            raise RecipeValidationError(_("Assign at least one flat frame"))
        return {
            "dark_frames": dark_frames,
            "flat_frames": flat_frames,
        }


class CameraDetectorCharacterizationPlugin(PluginBase):
    """Expose Camera characterization to DataLab Desktop."""

    PLUGIN_INFO = PluginInfo(
        id=PLUGIN_ID,
        name=PLUGIN_NAME,
        version=__version__,
        description=PLUGIN_DESCRIPTION,
        capabilities=(
            PluginCapability.APPLICATION,
            PluginCapability.PROCESSING,
        ),
    )
    RECIPES = CAMERA_RECIPES
    EXAMPLES = (CAMERA_QUICKSTART,)

    @staticmethod
    def can_run_relative_dn(_selected_groups, selected_objects) -> bool:
        """Return whether the current selection can satisfy default minima."""
        return len(selected_objects) >= MINIMUM_SELECTED_FRAME_COUNT

    def edit_input_roles(
        self,
        images: Sequence[ImageObj],
        roles: CameraInputRoleParameters | None = None,
    ) -> RecipeInputs | None:
        """Edit and validate dark/flat roles for selected Desktop images."""
        if self.main is None:
            raise RuntimeError("Plugin must be registered before editing input roles")
        if roles is None:
            roles = CameraInputRoleParameters.create(images)
        elif not isinstance(roles, CameraInputRoleParameters):
            raise TypeError("Roles must be CameraInputRoleParameters")
        while roles.edit(parent=self.main):
            try:
                return roles.to_recipe_inputs()
            except RecipeValidationError as error:
                self.show_warning(str(error))
        return None

    def edit_relative_dn_parameters(
        self,
        parameters: CameraRecipeParameters | None = None,
    ) -> CameraRecipeParameters | None:
        """Edit relative-DN parameters with the Desktop as dialog parent."""
        if self.main is None:
            raise RuntimeError("Plugin must be registered before editing parameters")
        if parameters is None:
            parameters = CameraRecipeParameters()
        elif not isinstance(parameters, CameraRecipeParameters):
            raise TypeError("Parameters must be CameraRecipeParameters")
        if parameters.edit(parent=self.main):
            return parameters
        return None

    def run_relative_dn_from_selection(self) -> RecipeOutcome | None:
        """Assign selected images, edit parameters, and run the Desktop recipe."""
        if self.main is None:
            raise RuntimeError("Plugin must be registered before running a recipe")
        selected_images = tuple(
            self.imagepanel.objview.get_sel_objects(include_groups=True)
        )
        if not self.can_run_relative_dn((), selected_images):
            self.show_warning(
                _("Select at least six images for Camera characterization")
            )
            return None
        inputs = self.edit_input_roles(selected_images)
        if inputs is None:
            return None
        parameters = self.edit_relative_dn_parameters()
        if parameters is None:
            return None
        try:
            return RecipeRunner(self.main).run(
                RELATIVE_DN_RECIPE,
                inputs,
                parameters,
            )
        except (
            CameraCharacterizationError,
            RecipeCommitError,
            RecipeValidationError,
        ) as error:
            self.show_error(str(error))
            return None

    def open_quickstart(self) -> PluginExample | None:
        """Open the packaged quickstart and select all Camera input images."""
        if self.main is None:
            raise RuntimeError("Plugin must be registered before opening quickstart")
        if not self.main.confirm_memory_state():
            return None
        if any(len(panel) for panel in self.main.panels) and not self.ask_yesno(
            _("Opening the quickstart replaces the current workspace. Continue?"),
            title=_("Open quickstart example"),
        ):
            return None
        example = self.open_example(CAMERA_QUICKSTART.id, reset_all=True)
        images = self.imagepanel.objmodel.get_all_objects()
        self.imagepanel.objview.select_objects(images)
        return example

    def create_actions(self) -> None:
        """Create the complete relative-DN Camera workflow action."""
        handler = self.imagepanel.acthandler
        with handler.new_menu(PLUGIN_NAME):
            self.open_quickstart_action = handler.new_action(
                _("Open quickstart example"),
                triggered=self.open_quickstart,
                tip=_("Open and select the packaged synthetic Camera campaign"),
                select_condition="always",
            )
            self.run_relative_dn_action = handler.new_action(
                _("Run camera characterization..."),
                triggered=self.run_relative_dn_from_selection,
                tip=_("Assign dark and flat roles, then run characterization"),
                select_condition=self.can_run_relative_dn,
            )
