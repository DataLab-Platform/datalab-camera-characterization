"""Installed distribution, reload, and persistence qualification."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from datalab.adapters_metadata import TableAdapter
from datalab.config import Conf
from datalab.env import execenv
from datalab.gui.actionhandler import ActionCategory
from datalab.gui.recipe_runner import RecipeRunner
from datalab.objectmodel import get_uuid
from datalab.plugins import PluginRegistry
from datalab.recipes import RECIPE_RUN_RECORD_OPTION, RecipeRunRecord
from datalab.tests import datalab_test_app_context

from datalab_camera_characterization import PLUGIN_ID, PLUGIN_NAME
from datalab_camera_characterization.adapters.desktop import (
    CameraDetectorCharacterizationPlugin,
    CameraInputRoleParameters,
)
from datalab_camera_characterization.workflow import (
    RELATIVE_DN_RECIPE,
    CameraRecipeParameters,
)

PROJECT_ROOT = Path(__file__).parents[2]
QUICKSTART_SHA256 = "5875333EE7561A6C73AD9C690E5790D9A0BC081586122F33E0BEB001FE690FBF"


def _camera_plugins() -> list[CameraDetectorCharacterizationPlugin]:
    """Return active Camera plugin instances."""
    return [
        plugin
        for plugin in PluginRegistry.get_plugins()
        if plugin.plugin_id == PLUGIN_ID
    ]


def test_wheel_installs_and_resolves_entry_point_outside_checkout(tmp_path) -> None:
    """A built wheel imports its plugin and example from an isolated target."""
    wheel_dir = tmp_path / "wheel"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            os.fspath(wheel_dir),
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = tuple(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1

    install_dir = tmp_path / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            "--target",
            os.fspath(install_dir),
            os.fspath(wheels[0]),
        ],
        check=True,
    )
    probe = """
import hashlib
import importlib
import importlib.metadata as metadata
import json

distribution = next(metadata.distributions(path=[INSTALL_DIR]))
entry_point = next(
    value
    for value in distribution.entry_points
    if value.group == "datalab.plugins"
)
plugin_class = entry_point.load()
example = plugin_class.get_example("quickstart")
payload = example.resolve().read_bytes()
module = importlib.import_module(plugin_class.__module__)
print(json.dumps({
    "entry_point": entry_point.name,
    "module_file": module.__file__,
    "plugin_id": plugin_class.get_plugin_id(),
    "recipe_id": example.recipe_id,
    "resource_size": len(payload),
    "resource_sha256": hashlib.sha256(payload).hexdigest().upper(),
}))
""".replace("INSTALL_DIR", repr(os.fspath(install_dir)))
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (os.fspath(install_dir), environment.get("PYTHONPATH", ""))
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result == {
        "entry_point": "datalab_camera_characterization",
        "module_file": os.fspath(
            install_dir / "datalab_camera_characterization" / "adapters" / "desktop.py"
        ),
        "plugin_id": PLUGIN_ID,
        "recipe_id": RELATIVE_DN_RECIPE.recipe_id,
        "resource_size": 285_344,
        "resource_sha256": QUICKSTART_SHA256,
    }


def test_entry_point_plugin_reload_keeps_one_instance_and_menu() -> None:
    """Desktop hot reload replaces the Camera plugin without action leaks."""
    original_plugins_enabled = Conf.main.plugins_enabled.get(True)
    original_enabled_list = Conf.main.plugins_enabled_list.get(None)
    Conf.main.plugins_enabled.set(True)
    Conf.main.plugins_enabled_list.set(None)
    try:
        with (
            execenv.context(unattended=True),
            datalab_test_app_context(console=False, exec_loop=False) as window,
        ):
            window.reload_plugins()
            plugins_before = _camera_plugins()
            assert len(plugins_before) == 1
            plugin_before = plugins_before[0]
            sources = plugin_before.__class__.__plugin_discovery_sources__
            assert any(
                "entry point 'datalab_camera_characterization'" in source
                for source in sources
            )

            window.reload_plugins()

            plugins_after = _camera_plugins()
            assert len(plugins_after) == 1
            plugin_after = plugins_after[0]
            assert plugin_after is not plugin_before
            menus = [
                action
                for action in window.imagepanel.get_category_actions(
                    ActionCategory.PLUGINS
                )
                if hasattr(action, "title") and action.title() == PLUGIN_NAME
            ]
            assert len(menus) == 1
            window.imagepanel.acthandler.selected_objects_changed([], [])
            assert plugin_after.open_quickstart_action.isEnabled()
    finally:
        Conf.main.plugins_enabled.set(original_plugins_enabled)
        if original_enabled_list is None:
            Conf.main.plugins_enabled_list.remove()
        else:
            Conf.main.plugins_enabled_list.set(original_enabled_list)


def test_camera_outputs_survive_native_h5_round_trip(tmp_path) -> None:
    """Output UUIDs, recipe provenance, and anchored metrics survive HDF5."""
    with (
        execenv.context(unattended=True),
        datalab_test_app_context(console=False, exec_loop=False) as window,
    ):
        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window
        plugin.open_quickstart()
        images = window.imagepanel.objmodel.get_all_objects()
        inputs = CameraInputRoleParameters.create(images).to_recipe_inputs()
        outcome = RecipeRunner(window).run(
            RELATIVE_DN_RECIPE,
            inputs,
            CameraRecipeParameters(),
        )
        output_uuids = {output.id: get_uuid(output.value) for output in outcome.objects}
        records = {
            output.id: RecipeRunRecord.from_dict(
                output.value.get_metadata_option(RECIPE_RUN_RECORD_OPTION)
            )
            for output in outcome.objects
        }
        input_uuids = {
            get_uuid(image) for images in inputs.values() for image in images
        }
        response = outcome.objects[0].value
        table = next(TableAdapter.iterate_from_obj(response))
        table_payload = table.result.to_dict()

        filename = tmp_path / "camera-round-trip.h5"
        window.save_h5_workspace(os.fspath(filename))
        window.load_h5_workspace([os.fspath(filename)], reset_all=True)

        assert all(
            window.find_object_by_uuid(value) is not None for value in input_uuids
        )
        for output_id, output_uuid in output_uuids.items():
            loaded = window.find_object_by_uuid(output_uuid)
            assert loaded is not None
            loaded_record = RecipeRunRecord.from_dict(
                loaded.get_metadata_option(RECIPE_RUN_RECORD_OPTION)
            )
            assert loaded_record == records[output_id]
        loaded_response = window.find_object_by_uuid(output_uuids["response"])
        loaded_tables = list(TableAdapter.iterate_from_obj(loaded_response))
        assert len(loaded_tables) == 1
        assert loaded_tables[0].result.to_dict() == table_payload
