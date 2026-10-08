"""Regenerate the documentation screenshots in DataLab Desktop."""

from __future__ import annotations

from pathlib import Path

from datalab.config import Conf, ensure_initialized
from datalab.env import execenv
from datalab.plugins import PluginRegistry
from datalab.tests import datalab_test_app_context
from qtpy import QtWidgets as QW
from qtpy.QtTest import QTest

from datalab_camera_characterization import PLUGIN_ID
from datalab_camera_characterization.simulator import CAMERA_SIMULATOR_TOOL

OUTPUT_DIR = Path(__file__).parents[1] / "doc" / "images"
WINDOW_SIZE = (1280, 800)
SHOWN_OUTPUT = "Relative PRNU-like map"
#: Mid-range exposure with optical defects, more telling than the defaults
SIMULATOR_SETTINGS = {
    "exposure_ms": 80.0,
    "vignetting_percent": 25.0,
    "dust_shadow_count": 3,
}
#: Leaves time for plots and the simulator's first live frame to be drawn (ms)
RENDER_DELAY = 1_000


def _registered_plugin():
    """Return the plugin instance registered by DataLab at startup."""
    # Importing the adapter class here would hide it from DataLab's discovery
    for plugin in PluginRegistry.get_plugins():
        if plugin.plugin_id == PLUGIN_ID:
            return plugin
    raise RuntimeError("Install the plugin in DataLab's Python environment first")


def _save(widget: QW.QWidget, name: str) -> None:
    """Save a screenshot of a widget once it is rendered."""
    QTest.qWait(RENDER_DELAY)
    path = OUTPUT_DIR / name
    if not widget.grab().save(str(path)):
        raise OSError(f"Cannot write {path}")
    print(f"Saved {path}")


def main() -> None:
    """Run the quickstart, then open the simulator, and save both views."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    execenv.unattended = True
    ensure_initialized(load_user_config=False)
    with (
        Conf.color_mode.context("light"),
        datalab_test_app_context(
            size=WINDOW_SIZE, console=False, exec_loop=False
        ) as window,
    ):
        plugin = _registered_plugin()
        plugin.open_quickstart()
        plugin.run_relative_dn()
        panel = window.imagepanel
        (output,) = [
            obj for obj in panel.objmodel.get_all_objects() if obj.title == SHOWN_OUTPUT
        ]
        window.set_current_panel("image")
        panel.objview.select_objects([output])
        _save(window, "overview.png")

        settings = plugin.get_instrument(CAMERA_SIMULATOR_TOOL.id).settings
        for name, value in SIMULATOR_SETTINGS.items():
            setattr(settings, name, value)
        simulator = plugin.launch_tool(CAMERA_SIMULATOR_TOOL.id)
        _save(simulator, "simulator.png")
        simulator.close()


if __name__ == "__main__":
    main()
