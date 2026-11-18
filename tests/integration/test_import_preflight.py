"""User path for a linear-camera import with no implicit roles or ADC scale."""

from __future__ import annotations

import numpy as np
import pytest
from sigima.objects import create_image

from datalab_camera_characterization.workflow import (
    EXPOSURE_TIME_METADATA_KEY,
    RELATIVE_DN_RECIPE,
)


def _imported_frames():
    return {
        slot: tuple(
            create_image(
                f"{slot} {level} #{repeat}",
                np.full((4, 4), mean + repeat, dtype=np.uint16),
                metadata={} if level is None else {EXPOSURE_TIME_METADATA_KEY: level},
            )
            for level, mean in levels
            for repeat in (-1, 1)
        )
        for slot, levels in (
            ("dark_frames", [(None, 10)]),
            ("flat_frames", [(1.0, 30), (2.0, 50)]),
        )
    }


def test_desktop_import_assignment_then_parameter_editor(monkeypatch):
    """Operate the actual widgets; accepting defaults must not change either panel."""
    from datalab.env import execenv
    from datalab.gui.plugins.recipe_inputs import RecipeInputDialog
    from datalab.tests import datalab_test_app_context
    from guidata.dataset.qtwidgets import DataSetEditDialog
    from qtpy.QtCore import Qt

    from datalab_camera_characterization.adapters.desktop import (
        CameraDetectorCharacterizationPlugin,
    )

    inputs = _imported_frames()
    events, errors = [], []

    def assign(dialog):
        events.append("assign")
        assert not dialog.ok_button.isEnabled()
        for slot, widget in dialog.lists.items():
            for row in range(widget.count()):
                item = widget.item(row)
                assert item.checkState() == Qt.Unchecked
                if slot in item.text():
                    item.setCheckState(Qt.Checked)
        assert dialog.get_bindings() == inputs
        assert dialog.ok_button.isEnabled()
        assert "assume_lsb" in dialog.issues_label.text()
        return True

    def edit(dialog):
        assert isinstance(dialog, DataSetEditDialog)
        events.append("edit")
        if errors:  # Second attempt: fill in the missing declarations.
            widgets = {w.item.item.get_name(): w for w in dialog.edit_layout[0].widgets}
            widgets["assume_lsb"].checkbox.setChecked(True)
            for key, value in (
                ("saturation_dn", "4095"),
                ("bit_shift", "0"),
                ("dark_reference_exposure_s", "0"),
            ):
                widgets[key].edit.setText(value)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(RecipeInputDialog, "exec", assign)
    monkeypatch.setattr("guidata.qthelpers.exec_dialog", edit)
    with (
        execenv.context(unattended=True),
        datalab_test_app_context(console=False, exec_loop=False) as window,
    ):
        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window
        monkeypatch.setattr(plugin, "show_error", errors.append)
        frames = sum(inputs.values(), ())
        for image in frames:
            window.imagepanel.add_object(image)
        window.set_current_panel("image")
        window.imagepanel.objview.select_objects(frames)
        panels = (window.imagepanel, window.signalpanel)
        before = [(len(p), p.objmodel.get_groups()) for p in panels]
        assert plugin.run_relative_dn() is None
        assert len(errors) == 1 and "Unknown dark exposure" in errors[0]
        assert [(len(p), p.objmodel.get_groups()) for p in panels] == before
        assert plugin.run_relative_dn().results
        assert len(errors) == 1
        assert events == ["assign", "edit", "assign", "edit"]


def test_web_import_assignment_then_parameter_schema(monkeypatch):
    """Run with the DataLab-Web Python test runtime on the import path."""
    apps = pytest.importorskip("dlw_applications")
    import bootstrap
    from datalab.plugins.recipes import RecipeValidationError

    from datalab_camera_characterization.adapters.web import (
        CameraDetectorCharacterizationWebPlugin,
    )

    model = bootstrap.ObjectModel()
    monkeypatch.setattr(apps, "_MODEL", model)
    monkeypatch.setattr(apps, "_OBJECT_UUID", bootstrap._object_uuid)
    monkeypatch.setattr(
        apps, "_plugin_class", lambda _: CameraDetectorCharacterizationWebPlugin
    )
    recipe = RELATIVE_DN_RECIPE
    ids = recipe.plugin_id, recipe.recipe_id
    bindings = {
        slot: [model.add_object("image", obj) for obj in objects]
        for slot, objects in _imported_frames().items()
    }
    prep = apps.prepare_plugin_recipe(*ids, sum(bindings.values(), []))
    assert prep["readiness"]["status"] == "needs_assignment"
    assert not any(prep["bindings"].values())
    defaults = prep["parameters"]["values"]
    checked = apps.check_plugin_recipe_bindings(*ids, bindings, defaults)
    assert checked["status"] == "warnings" and checked["bindings"] == bindings
    panels = ("image", "signal")
    before = [model.panel_tree(p) for p in panels]
    with pytest.raises(RecipeValidationError, match="missing Z unit"):
        apps.run_plugin_recipe(*ids, bindings, defaults)
    assert [model.panel_tree(p) for p in panels] == before
    values = dict(
        defaults,
        assume_lsb=True,
        saturation_dn=4095,
        bit_shift=0,
        dark_reference_exposure_s=0.0,
    )
    assert (
        apps.check_plugin_recipe_bindings(*ids, bindings, values)["status"] == "ready"
    )
    assert apps.run_plugin_recipe(*ids, bindings, values)["results"]
