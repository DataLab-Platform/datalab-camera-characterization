"""DataLab Desktop adapter contract tests."""

from __future__ import annotations

import numpy as np
import pytest
from datalab.adapters_metadata import TableAdapter
from datalab.env import execenv
from datalab.gui.actionhandler import ActionCategory
from datalab.gui.recipe_runner import RecipeRunner
from datalab.plugins import PluginCapability
from datalab.recipes import (
    RECIPE_RUN_RECORD_OPTION,
    RecipeRunRecord,
    RecipeValidationError,
)
from datalab.tests import datalab_test_app_context
from sigima.objects import ImageObj, create_image

from datalab_camera_characterization import PLUGIN_ID
from datalab_camera_characterization.adapters import desktop as desktop_adapter
from datalab_camera_characterization.adapters.desktop import (
    CameraDetectorCharacterizationPlugin,
    CameraInputRoleParameters,
)
from datalab_camera_characterization.workflow import (
    EXPOSURE_TIME_METADATA_KEY,
    RELATIVE_DN_RECIPE,
    CameraRecipeParameters,
)


def test_plugin_descriptor() -> None:
    """The entry point exposes stable SDK metadata and its headless recipe."""
    assert CameraDetectorCharacterizationPlugin.get_plugin_id() == PLUGIN_ID
    assert CameraDetectorCharacterizationPlugin.PLUGIN_INFO.version == "0.1.0"
    assert CameraDetectorCharacterizationPlugin.PLUGIN_INFO.capabilities == frozenset(
        {
            PluginCapability.APPLICATION,
            PluginCapability.PROCESSING,
        }
    )
    assert CameraDetectorCharacterizationPlugin.get_recipes() == (RELATIVE_DN_RECIPE,)
    assert RELATIVE_DN_RECIPE.plugin_id == PLUGIN_ID
    assert RELATIVE_DN_RECIPE.plugin_version == "0.1.0"
    assert RELATIVE_DN_RECIPE.parameter_class is CameraRecipeParameters


@pytest.mark.parametrize("accepted", [True, False])
def test_desktop_adapter_edits_recipe_parameters(
    accepted: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The thin adapter returns accepted parameters and preserves cancellation."""
    plugin = CameraDetectorCharacterizationPlugin()
    parent = object()
    plugin.main = parent
    parameters = CameraRecipeParameters()
    edit_calls: list[object] = []

    def edit(_self, *, parent):
        edit_calls.append(parent)
        return accepted

    monkeypatch.setattr(CameraRecipeParameters, "edit", edit)

    result = plugin.edit_relative_dn_parameters(parameters)

    assert edit_calls == [parent]
    assert result is parameters if accepted else result is None


def test_desktop_parameter_editor_requires_registered_plugin() -> None:
    """The adapter cannot parent a modal form before Desktop registration."""
    plugin = CameraDetectorCharacterizationPlugin()

    with pytest.raises(RuntimeError, match="registered"):
        plugin.edit_relative_dn_parameters()


def test_desktop_forms_open_in_unattended_application() -> None:
    """Parameter and role DataSets open successfully in a DataLab window."""
    with (
        execenv.context(unattended=True),
        datalab_test_app_context(
            console=False,
            exec_loop=False,
        ) as window,
    ):
        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window

        parameters = plugin.edit_relative_dn_parameters()
        inputs = plugin.edit_input_roles(
            (
                _frame("dark 1", 9),
                _frame("flat 1", 30, 1.0),
            )
        )

        assert isinstance(parameters, CameraRecipeParameters)
        assert parameters.get_title() == (
            "Parameters for relative Camera characterization in DN."
        )
        assert inputs is not None
        assert [image.title for image in inputs["dark_frames"]] == ["dark 1"]
        assert [image.title for image in inputs["flat_frames"]] == ["flat 1"]


def _frame(title: str, value: int, exposure_time_s: float | None = None) -> ImageObj:
    """Create one recipe input image."""
    image = create_image(title, np.full((2, 3), value, dtype=np.uint16))
    if exposure_time_s is not None:
        image.metadata[EXPOSURE_TIME_METADATA_KEY] = exposure_time_s
    return image


def test_input_role_parameters_assign_every_selected_image_once() -> None:
    """Role defaults are explicit and resolve in original selection order."""
    images = (
        _frame("dark 1", 9),
        _frame("flat low", 30, 1.0),
        _frame("dark 2", 11),
        _frame("flat high", 50, 2.0),
    )

    roles = CameraInputRoleParameters.create(images)
    inputs = roles.to_recipe_inputs()

    assert inputs == {
        "dark_frames": (images[0], images[2]),
        "flat_frames": (images[1], images[3]),
    }


@pytest.mark.parametrize(
    ("role", "message"),
    [
        ("flat", "dark"),
        ("dark", "flat"),
    ],
)
def test_input_role_parameters_reject_invalid_assignments(
    role: str,
    message: str,
) -> None:
    """Campaigns containing only one role stop before recipe execution."""
    images = tuple(_frame(f"frame {index}", index) for index in range(3))
    roles = CameraInputRoleParameters.create(images)
    for field_name in roles._images_by_field:
        setattr(roles, field_name, role)

    with pytest.raises(RecipeValidationError, match=message):
        roles.to_recipe_inputs()


def test_desktop_role_editor_reopens_after_invalid_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid role split warns and preserves the form for correction."""
    images = (_frame("frame 1", 10), _frame("frame 2", 20))
    roles = desktop_adapter.CameraInputRoleParameters.create(images)
    for field_name in roles._images_by_field:
        setattr(roles, field_name, "flat")
    edit_count = 0
    warnings: list[str] = []

    def edit(_self, *, parent):
        nonlocal edit_count
        edit_count += 1
        if edit_count == 2:
            setattr(roles, next(iter(roles._images_by_field)), "dark")
        return True

    plugin = desktop_adapter.CameraDetectorCharacterizationPlugin()
    plugin.main = object()
    monkeypatch.setattr(type(roles), "edit", edit)
    monkeypatch.setattr(plugin, "show_warning", warnings.append)

    inputs = plugin.edit_input_roles(images, roles)

    assert edit_count == 2
    assert len(warnings) == 1
    assert "dark" in warnings[0]
    assert inputs == {
        "dark_frames": (images[0],),
        "flat_frames": (images[1],),
    }


@pytest.mark.parametrize("cancel_at", ["roles", "parameters"])
def test_desktop_run_cancellation_does_not_execute_recipe(
    cancel_at: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling either modal form leaves the selected campaign unchanged."""
    images = tuple(_frame(f"frame {index}", index) for index in range(6))

    with (
        execenv.context(unattended=True),
        datalab_test_app_context(
            console=False,
            exec_loop=False,
        ) as window,
    ):
        for image in images:
            window.imagepanel.add_object(image, set_current=False)
        window.imagepanel.objview.select_objects(images)

        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window
        inputs = {"dark_frames": images[:2], "flat_frames": images[2:]}
        monkeypatch.setattr(
            plugin,
            "edit_input_roles",
            lambda selected: None if cancel_at == "roles" else inputs,
        )
        monkeypatch.setattr(
            plugin,
            "edit_relative_dn_parameters",
            lambda: None,
        )

        outcome = plugin.run_relative_dn_from_selection()

        assert outcome is None
        assert len(window.signalpanel) == 0
        assert len(window.imagepanel) == len(images)


def test_desktop_action_assigns_selection_and_commits_cross_panel_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plugin action delegates a selected campaign to the Desktop runner."""
    dark = (_frame("dark 1", 9), _frame("dark 2", 11))
    flats = tuple(
        frame
        for mean_dn, exposure_time_s in ((30, 1.0), (50, 2.0))
        for frame in (
            _frame("flat low", mean_dn - 1, exposure_time_s),
            _frame("flat high", mean_dn + 1, exposure_time_s),
        )
    )
    selected_images = (*dark, *flats)
    parameters = CameraRecipeParameters()
    parameters.saturation_dn = 100.0

    with (
        execenv.context(unattended=True),
        datalab_test_app_context(
            console=False,
            exec_loop=False,
        ) as window,
    ):
        for image in selected_images:
            window.imagepanel.add_object(image, set_current=False)
        window.imagepanel.objview.select_objects(selected_images)

        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window
        handler = window.imagepanel.acthandler
        with handler.new_category(ActionCategory.PLUGINS):
            plugin.create_actions()
        monkeypatch.setattr(
            plugin,
            "edit_input_roles",
            lambda images: {"dark_frames": dark, "flat_frames": flats},
        )
        monkeypatch.setattr(
            plugin,
            "edit_relative_dn_parameters",
            lambda: parameters,
        )

        handler.selected_objects_changed([], list(selected_images[:-1]))
        assert not plugin.run_relative_dn_action.isEnabled()
        handler.selected_objects_changed([], list(selected_images))
        assert plugin.run_relative_dn_action.isEnabled()
        plugin.run_relative_dn_action.trigger()

        assert len(window.signalpanel) == 1
        assert len(window.imagepanel) == len(selected_images) + 2
        response = window.signalpanel[1]
        tables = list(TableAdapter.iterate_from_obj(response))
        assert len(tables) == 1
        assert tables[0].func_name == (f"{RELATIVE_DN_RECIPE.recipe_id}:metrics")


def test_desktop_action_reports_invalid_campaign_without_partial_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recipe validation errors return to Desktop without committing outputs."""
    dark = (_frame("dark 1", 9), _frame("dark 2", 11))
    flats = (
        _frame("flat missing exposure", 29),
        _frame("flat low", 31, 1.0),
        _frame("flat high 1", 49, 2.0),
        _frame("flat high 2", 51, 2.0),
    )
    selected_images = (*dark, *flats)
    parameters = CameraRecipeParameters()
    parameters.saturation_dn = 100.0
    errors: list[str] = []

    with (
        execenv.context(unattended=True),
        datalab_test_app_context(
            console=False,
            exec_loop=False,
        ) as window,
    ):
        for image in selected_images:
            window.imagepanel.add_object(image, set_current=False)
        window.imagepanel.objview.select_objects(selected_images)

        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window
        monkeypatch.setattr(
            plugin,
            "edit_input_roles",
            lambda images: {"dark_frames": dark, "flat_frames": flats},
        )
        monkeypatch.setattr(
            plugin,
            "edit_relative_dn_parameters",
            lambda: parameters,
        )
        monkeypatch.setattr(plugin, "show_error", errors.append)

        outcome = plugin.run_relative_dn_from_selection()

        assert outcome is None
        assert len(window.signalpanel) == 0
        assert len(window.imagepanel) == len(selected_images)
        assert len(errors) == 1
        assert EXPOSURE_TIME_METADATA_KEY in errors[0]


def test_recipe_runner_commits_camera_outputs_and_anchored_table() -> None:
    """The Desktop runner attaches metrics and provenance to committed outputs."""
    dark = (_frame("dark 1", 9), _frame("dark 2", 11))
    flats = tuple(
        frame
        for mean_dn, exposure_time_s in ((30, 1.0), (50, 2.0), (70, 3.0))
        for frame in (
            _frame("flat low", mean_dn - 1, exposure_time_s),
            _frame("flat high", mean_dn + 1, exposure_time_s),
        )
    )
    parameters = CameraRecipeParameters()
    parameters.saturation_dn = 100.0

    with (
        execenv.context(unattended=True),
        datalab_test_app_context(
            console=False,
            exec_loop=False,
        ) as window,
    ):
        outcome = RecipeRunner(window).run(
            RELATIVE_DN_RECIPE,
            {"dark_frames": dark, "flat_frames": flats},
            parameters,
        )

        assert len(window.signalpanel) == 1
        assert len(window.imagepanel) == 2
        response = outcome.objects[0].value
        tables = list(TableAdapter.iterate_from_obj(response))
        assert len(tables) == 1
        assert tables[0].func_name == (f"{RELATIVE_DN_RECIPE.recipe_id}:metrics")
        records = [
            RecipeRunRecord.from_dict(
                output.value.get_metadata_option(RECIPE_RUN_RECORD_OPTION)
            )
            for output in outcome.objects
        ]
        assert records[0] == records[1] == records[2]
        assert records[0].recipe_id == RELATIVE_DN_RECIPE.recipe_id
        assert set(records[0].output_uuids) == {
            "response",
            "mean_dark",
            "mean_flat",
        }
