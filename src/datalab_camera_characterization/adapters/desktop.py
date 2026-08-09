"""DataLab Desktop plugin adapter."""

from __future__ import annotations

from datalab.plugins import PluginBase, PluginCapability, PluginInfo

from .. import (
    PLUGIN_DESCRIPTION,
    PLUGIN_ID,
    PLUGIN_NAME,
    __version__,
)
from ..workflow import CAMERA_RECIPES


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

    def create_actions(self) -> None:
        """Create actions once Camera workflows are available."""
