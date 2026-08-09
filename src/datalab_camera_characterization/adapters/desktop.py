"""DataLab Desktop plugin adapter."""

from __future__ import annotations

from datalab.plugins import PluginBase, PluginCapability, PluginInfo

from .. import (
    PLUGIN_DESCRIPTION,
    PLUGIN_ID,
    PLUGIN_NAME,
    __version__,
)
from ..workflow import CAMERA_RECIPES, CameraRecipeParameters


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

    def create_actions(self) -> None:
        """Create actions once Camera workflows are available."""
