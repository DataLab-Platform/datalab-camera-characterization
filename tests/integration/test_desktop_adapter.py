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
from guidata.dataset.qtitemwidgets import MultipleChoiceWidget
from guidata.dataset.qtwidgets import DataSetEditDialog
from qtpy.QtWidgets import QCheckBox, QRadioButton
from sigima.objects import ImageObj, create_image

from datalab_camera_characterization import PLUGIN_ID
from datalab_camera_characterization.adapters import desktop as desktop_adapter
from datalab_camera_characterization.adapters.desktop import (
    CAMERA_QUICKSTART,
    CameraDetectorCharacterizationPlugin,
    CameraInputRoleParameters,
)
from datalab_camera_characterization.core import metadata_key
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
    assert CameraDetectorCharacterizationPlugin.get_recipe_launchers() == {
        RELATIVE_DN_RECIPE.recipe_id: "run_relative_dn_from_selection"
    }
    assert CameraDetectorCharacterizationPlugin.get_examples() == (CAMERA_QUICKSTART,)
    assert CameraDetectorCharacterizationPlugin.PLUGIN_INFO.documentation_url == (
        "https://github.com/DataLab-Platform/datalab-camera-characterization"
    )
    assert CAMERA_QUICKSTART.resolve().is_file()
    assert CAMERA_QUICKSTART.recipe_id == RELATIVE_DN_RECIPE.recipe_id
    assert RELATIVE_DN_RECIPE.plugin_id == PLUGIN_ID
    assert RELATIVE_DN_RECIPE.plugin_version == "0.1.0"
    assert RELATIVE_DN_RECIPE.version == "1.1.0"
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

    with pytest.raises(RuntimeError, match="registered"):
        plugin.open_quickstart()

    with pytest.raises(RuntimeError, match="registered"):
        plugin.launch_example(CAMERA_QUICKSTART.id)


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


def test_input_role_parameters_use_one_compact_three_column_grid() -> None:
    """A large campaign renders one checklist instead of one block per image."""
    images = tuple(
        _frame(f"{'dark' if index < 4 else 'flat'} {index + 1}", index)
        for index in range(13)
    )

    roles = CameraInputRoleParameters.create(images)
    items = roles.get_items()

    assert len(items) == 1
    assert isinstance(items[0], desktop_adapter.gds.MultipleChoiceItem)
    assert items[0].get_prop("display", "shape") == (-1, 3)
    assert len(items[0].get_prop("data", "choices")) == len(images)
    assert roles.dark_frame_indices == (0, 1, 2, 3)
    inputs = roles.to_recipe_inputs()
    assert inputs["dark_frames"] + inputs["flat_frames"] == images


def test_input_role_dialog_renders_thirteen_images_in_five_rows() -> None:
    """The Qt editor remains compact for a representative Camera campaign."""
    images = tuple(
        _frame(f"{'dark' if index < 4 else 'flat'} {index + 1}", index)
        for index in range(13)
    )
    roles = CameraInputRoleParameters.create(images)

    with (
        execenv.context(unattended=True),
        datalab_test_app_context(console=False, exec_loop=False) as window,
    ):
        dialog = DataSetEditDialog(roles, parent=window)
        widget = dialog.edit_layout[0].widgets[0]

        assert isinstance(widget, MultipleChoiceWidget)
        assert len(dialog.findChildren(QCheckBox)) == len(images)
        assert dialog.findChildren(QRadioButton) == []
        assert widget.groupbox.layout().rowCount() == 5
        assert widget.groupbox.layout().columnCount() == 3


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
    roles.dark_frame_indices = () if role == "flat" else tuple(range(len(images)))

    with pytest.raises(RecipeValidationError, match=message):
        roles.to_recipe_inputs()


def test_desktop_role_editor_reopens_after_invalid_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid role split warns and preserves the form for correction."""
    images = (_frame("frame 1", 10), _frame("frame 2", 20))
    roles = desktop_adapter.CameraInputRoleParameters.create(images)
    roles.dark_frame_indices = ()
    edit_count = 0
    warnings: list[str] = []

    def edit(_self, *, parent):
        nonlocal edit_count
        edit_count += 1
        if edit_count == 2:
            roles.dark_frame_indices = (0,)
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

        plugin = desktop_adapter.CameraDetectorCharacterizationPlugin()
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

        assert len(window.signalpanel) == 5
        assert len(window.imagepanel) == len(selected_images) + 5
        last_output = window.signalpanel.objmodel.get_all_objects()[-1]
        assert last_output.title == "PRNU-like distribution"
        assert window.get_current_panel() == "signal"
        assert window.signalpanel.objview.get_sel_objects() == [last_output]
        assert window.signalpanel.objview.get_current_object() is last_output
        response = window.signalpanel[1]
        tables = list(TableAdapter.iterate_from_obj(response))
        assert len(tables) == 1
        assert tables[0].func_name == (f"{RELATIVE_DN_RECIPE.recipe_id}:metrics")


def test_desktop_quickstart_action_opens_and_runs_packaged_example(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The visible quickstart path produces a useful result without Python."""
    warnings: list[str] = []
    errors: list[str] = []
    with (
        execenv.context(unattended=True),
        datalab_test_app_context(
            console=False,
            exec_loop=False,
        ) as window,
    ):
        plugin = desktop_adapter.CameraDetectorCharacterizationPlugin()
        plugin.main = window
        monkeypatch.setattr(plugin, "show_warning", warnings.append)
        monkeypatch.setattr(plugin, "show_error", errors.append)
        handler = window.imagepanel.acthandler
        with handler.new_category(ActionCategory.PLUGINS):
            plugin.create_actions()

        handler.selected_objects_changed([], [])
        assert plugin.open_quickstart_action.isEnabled()
        plugin.open_quickstart_action.trigger()

        input_images = window.imagepanel.objmodel.get_all_objects()
        selected_images = window.imagepanel.objview.get_sel_objects()
        flat_exposures = {
            image.metadata[EXPOSURE_TIME_METADATA_KEY]
            for image in input_images
            if EXPOSURE_TIME_METADATA_KEY in image.metadata
        }
        assert len(input_images) == 20
        assert selected_images == input_images
        assert sum(image.title.startswith("Dark") for image in input_images) == 4
        assert flat_exposures == {0.005, 0.01, 0.02, 0.04}
        dark_frame = input_images[0].data.astype(float)
        flat_frame = input_images[-1].data.astype(float)
        flat_edges = np.concatenate(
            (
                flat_frame[:12, :].ravel(),
                flat_frame[-12:, :].ravel(),
                flat_frame[:, :12].ravel(),
                flat_frame[:, -12:].ravel(),
            )
        )
        assert dark_frame.shape == (96, 128)
        assert dark_frame[-16:, -16:].mean() > dark_frame[:16, :16].mean() + 20.0
        assert np.count_nonzero(dark_frame == 4_095) == 6
        assert np.count_nonzero(dark_frame == 0) == 6
        assert flat_frame[32:64, 48:80].mean() > flat_edges.mean() + 100.0
        assert np.count_nonzero(flat_frame == 4_095) == 6
        assert np.count_nonzero(flat_frame == 0) == 6
        assert input_images[0].metadata[metadata_key("frame_role")] == "dark"
        assert input_images[-1].metadata[metadata_key("frame_role")] == "flat"
        assert (
            "vignetting"
            in input_images[-1].metadata[metadata_key("illumination_structure")]
        )
        assert plugin.run_relative_dn_action.isEnabled()

        # Real modal widgets are smoke-tested separately from this action flow.
        monkeypatch.setattr(
            plugin,
            "edit_input_roles",
            lambda images: desktop_adapter.CameraInputRoleParameters.create(
                images
            ).to_recipe_inputs(),
        )
        monkeypatch.setattr(
            plugin,
            "edit_relative_dn_parameters",
            desktop_adapter.CameraRecipeParameters,
        )
        plugin.run_relative_dn_action.trigger()

        assert not warnings
        assert not errors
        assert len(window.signalpanel) == 5
        assert len(window.imagepanel) == 25
        output_image_titles = {
            image.title for image in window.imagepanel.objmodel.get_all_objects()[20:]
        }
        assert output_image_titles == {
            "Mean dark image",
            "Mean flat image (0.04 s)",
            "Relative DSNU-like map",
            "Relative PRNU-like map",
            "Candidate pixel map",
        }
        response = window.signalpanel[1]
        tables = list(TableAdapter.iterate_from_obj(response))
        assert len(tables) == 1
        assert tables[0].func_name == (f"{RELATIVE_DN_RECIPE.recipe_id}:metrics")


def test_desktop_quickstart_cancel_preserves_current_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declining replacement leaves existing objects untouched."""
    existing = _frame("Existing image", 42)
    with (
        execenv.context(unattended=True),
        datalab_test_app_context(
            console=False,
            exec_loop=False,
        ) as window,
    ):
        window.imagepanel.add_object(existing)
        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window
        monkeypatch.setattr(plugin, "ask_yesno", lambda *args, **kwargs: False)

        opened = plugin.open_quickstart()

        assert opened is None
        assert window.imagepanel.objmodel.get_all_objects() == [existing]


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

        assert len(window.signalpanel) == 5
        assert len(window.imagepanel) == 5
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
        assert all(record == records[0] for record in records[1:])
        assert records[0].recipe_id == RELATIVE_DN_RECIPE.recipe_id
        assert set(records[0].output_uuids) == {
            "response",
            "mean_dark",
            "mean_flat",
            "dsnu_like_map",
            "prnu_like_map",
            "candidate_pixel_map",
            "prnu_row_profile",
            "prnu_column_profile",
            "dsnu_distribution",
            "prnu_distribution",
        }
