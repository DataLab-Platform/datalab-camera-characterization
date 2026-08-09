"""DataLab Desktop adapter contract tests."""

from datalab.plugins import PluginCapability

from datalab_camera_characterization import PLUGIN_ID
from datalab_camera_characterization.adapters.desktop import (
    CameraDetectorCharacterizationPlugin,
)


def test_plugin_descriptor() -> None:
    """The entry point exposes stable SDK metadata and no premature recipes."""
    assert CameraDetectorCharacterizationPlugin.get_plugin_id() == PLUGIN_ID
    assert CameraDetectorCharacterizationPlugin.PLUGIN_INFO.version == "0.1.0"
    assert CameraDetectorCharacterizationPlugin.PLUGIN_INFO.capabilities == frozenset(
        {
            PluginCapability.APPLICATION,
            PluginCapability.PROCESSING,
        }
    )
    assert CameraDetectorCharacterizationPlugin.get_recipes() == ()
