"""DataLab Desktop adapter contract tests."""

from __future__ import annotations

from importlib import resources

import numpy as np
import pytest
from datalab.adapters_metadata import TableAdapter
from datalab.env import execenv
from datalab.gui.actionhandler import ActionCategory
from datalab.gui.recipe_inputs import RecipeInputDialog
from datalab.gui.recipe_runner import RecipeRunner
from datalab.plugins import PluginCapability
from datalab.recipe_binding import RecipeInputIssueCode, RecipeReadinessStatus
from datalab.recipes import (
    RECIPE_RUN_RECORD_OPTION,
    RecipeRunRecord,
)
from datalab.tests import datalab_test_app_context
from sigima.objects import ImageObj, create_image

from datalab_camera_characterization import PLUGIN_DESCRIPTION, PLUGIN_ID, PLUGIN_NAME
from datalab_camera_characterization.adapters import desktop as desktop_adapter
from datalab_camera_characterization.adapters.desktop import (
    CAMERA_QUICKSTART,
    CameraDetectorCharacterizationPlugin,
)
from datalab_camera_characterization.core import metadata_key
from datalab_camera_characterization.demo import DARK_RAMP_DEMO, PHOTON_TRANSFER_DEMO
from datalab_camera_characterization.workflow import (
    DARK_CURRENT_RECIPE,
    EXPOSURE_TIME_METADATA_KEY,
    FRAME_ROLE_METADATA_KEY,
    PHOTON_TRANSFER_RECIPE,
    RELATIVE_DN_RECIPE,
    CameraRecipeParameters,
    DarkCurrentRecipeParameters,
    PhotonTransferRecipeParameters,
)


def _no_assignment_dialog(_dialog: RecipeInputDialog) -> bool:
    """Fail when DataLab asks the user to assign inputs that metadata define."""
    pytest.fail("The selected frames should be assigned from their metadata")


def test_plugin_descriptor() -> None:
    """The entry point exposes stable SDK metadata and its headless recipes."""
    assert CameraDetectorCharacterizationPlugin.get_plugin_id() == PLUGIN_ID
    assert CameraDetectorCharacterizationPlugin.PLUGIN_INFO.version == "0.2.0"
    assert CameraDetectorCharacterizationPlugin.PLUGIN_INFO.capabilities == frozenset(
        {
            PluginCapability.APPLICATION,
            PluginCapability.PROCESSING,
        }
    )
    assert CameraDetectorCharacterizationPlugin.get_recipes() == (
        RELATIVE_DN_RECIPE,
        PHOTON_TRANSFER_RECIPE,
        DARK_CURRENT_RECIPE,
    )
    # DataLab's generic interaction runs every recipe
    assert CameraDetectorCharacterizationPlugin.get_recipe_launchers() == {}
    assert CameraDetectorCharacterizationPlugin.get_examples() == (
        CAMERA_QUICKSTART,
        PHOTON_TRANSFER_DEMO,
        DARK_RAMP_DEMO,
    )
    assert CameraDetectorCharacterizationPlugin.PLUGIN_INFO.documentation_url == (
        "https://github.com/DataLab-Platform/datalab-camera-characterization"
    )
    assert CAMERA_QUICKSTART.resolve().is_file()
    assert CAMERA_QUICKSTART.recipe_ids == (RELATIVE_DN_RECIPE.recipe_id,)
    assert PHOTON_TRANSFER_DEMO.recipe_ids == (
        PHOTON_TRANSFER_RECIPE.recipe_id,
        RELATIVE_DN_RECIPE.recipe_id,
    )
    assert DARK_RAMP_DEMO.recipe_ids == (DARK_CURRENT_RECIPE.recipe_id,)
    for recipe in CameraDetectorCharacterizationPlugin.get_recipes():
        assert recipe.suggest_bindings is not None
        assert recipe.check_inputs is not None
        assert all(slot.title and slot.description for slot in recipe.inputs)
    flat_slot = RELATIVE_DN_RECIPE.get_input("flat_frames")
    assert [(item.key, item.required) for item in flat_slot.metadata] == [
        (EXPOSURE_TIME_METADATA_KEY, True),
        (FRAME_ROLE_METADATA_KEY, False),
    ]
    assert RELATIVE_DN_RECIPE.plugin_id == PLUGIN_ID
    assert RELATIVE_DN_RECIPE.plugin_version == "0.2.0"
    assert RELATIVE_DN_RECIPE.version == "1.1.0"
    assert RELATIVE_DN_RECIPE.parameter_class is CameraRecipeParameters
    assert PHOTON_TRANSFER_RECIPE.version == "1.0.0"
    assert PHOTON_TRANSFER_RECIPE.parameter_class is PhotonTransferRecipeParameters
    assert DARK_CURRENT_RECIPE.version == "1.0.0"
    assert DARK_CURRENT_RECIPE.parameter_class is DarkCurrentRecipeParameters


def test_plugin_welcome_tiles_open_catalog_and_quickstart() -> None:
    """The main tile opens the catalog; the second opens the quickstart."""
    package = resources.files("datalab_camera_characterization") / "icons"

    application, quickstart = CameraDetectorCharacterizationPlugin.get_welcome_tiles()

    assert CameraDetectorCharacterizationPlugin.PLUGIN_INFO.icon == (
        desktop_adapter.PLUGIN_ICON
    )
    assert (
        application.id,
        application.title,
        application.description,
        application.icon,
        application.launcher,
    ) == (
        "application",
        PLUGIN_NAME,
        PLUGIN_DESCRIPTION,
        desktop_adapter.PLUGIN_ICON,
        None,
    )
    assert (quickstart.id, quickstart.icon, quickstart.launcher) == (
        "quickstart",
        desktop_adapter.DEMO_ICON,
        "open_quickstart",
    )
    assert (package / "camera_characterization.svg").is_file()
    assert (package / "camera_demo.svg").is_file()


def test_desktop_entry_points_require_registered_plugin() -> None:
    """Methods and examples need the Desktop window they act on."""
    plugin = CameraDetectorCharacterizationPlugin()

    for entry_point in (
        plugin.run_relative_dn,
        plugin.open_quickstart,
        lambda: plugin.launch_example(CAMERA_QUICKSTART.id),
    ):
        with pytest.raises(RuntimeError, match="registered"):
            entry_point()


def _frame(title: str, value: int, exposure_time_s: float | None = None) -> ImageObj:
    """Create one recipe input image."""
    image = create_image(title, np.full((2, 3), value, dtype=np.uint16))
    if exposure_time_s is not None:
        image.metadata[EXPOSURE_TIME_METADATA_KEY] = exposure_time_s
    return image


def _small_campaign() -> tuple[tuple[ImageObj, ...], tuple[ImageObj, ...]]:
    """Return two dark frames and two frames at each of two flat exposures."""
    dark = (_frame("dark 1", 9), _frame("dark 2", 11))
    flats = tuple(
        frame
        for mean_dn, exposure_time_s in ((30, 1.0), (50, 2.0))
        for frame in (
            _frame("flat low", mean_dn - 1, exposure_time_s),
            _frame("flat high", mean_dn + 1, exposure_time_s),
        )
    )
    return dark, flats


def _select(window, images) -> None:
    """Add images to the image panel and select them."""
    for image in images:
        window.imagepanel.add_object(image, set_current=False)
    window.set_current_panel("image")
    window.imagepanel.objview.select_objects(images)


def test_selection_readiness_explains_what_each_method_needs() -> None:
    """Every method assesses the selected frames and names what is missing."""
    dark, flats = _small_campaign()
    with (
        execenv.context(unattended=True),
        datalab_test_app_context(console=False, exec_loop=False) as window,
    ):
        _select(window, (*dark, *flats))
        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window

        relative = plugin.assess_recipe(RELATIVE_DN_RECIPE.recipe_id)
        assert relative.status is RecipeReadinessStatus.READY
        assert relative.bindings == {"dark_frames": dark, "flat_frames": flats}

        # Two exposure levels are enough for relative DN, not for a PTC
        photon_transfer = plugin.assess_recipe(PHOTON_TRANSFER_RECIPE.recipe_id)
        assert photon_transfer.status is RecipeReadinessStatus.NOT_READY
        assert [item.code for item in photon_transfer.diagnostics] == [
            "insufficient-flat-levels"
        ]

        # A dark ramp needs an exposure time on every dark frame
        dark_current = plugin.assess_recipe(DARK_CURRENT_RECIPE.recipe_id)
        assert dark_current.status is RecipeReadinessStatus.NOT_READY
        (issue,) = dark_current.issues
        assert issue.code is RecipeInputIssueCode.MISSING_METADATA
        assert issue.details["key"] == EXPOSURE_TIME_METADATA_KEY
        assert issue.details["count"] == 2

        # An explicit role wins over the exposure-time convention
        tagged_flat = _frame("dark-looking flat", 30)
        tagged_flat.metadata[FRAME_ROLE_METADATA_KEY] = "flat"
        readiness = plugin.assess_recipe(
            RELATIVE_DN_RECIPE.recipe_id, (*dark, *flats, tagged_flat)
        )
        assert tagged_flat in readiness.bindings["flat_frames"]
        assert [issue.code for issue in readiness.issues] == [
            RecipeInputIssueCode.MISSING_METADATA
        ]


def test_desktop_action_runs_selection_through_generic_interaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plugin action runs the selected campaign without a role dialog."""
    dark, flats = _small_campaign()
    selected_images = (*dark, *flats)

    def edit(parameters: CameraRecipeParameters, parent) -> bool:
        parameters.saturation_dn = 100.0
        return True

    monkeypatch.setattr(CameraRecipeParameters, "edit", edit)
    monkeypatch.setattr(RecipeInputDialog, "exec", _no_assignment_dialog)

    with (
        execenv.context(unattended=True),
        datalab_test_app_context(
            console=False,
            exec_loop=False,
        ) as window,
    ):
        _select(window, selected_images)
        plugin = desktop_adapter.CameraDetectorCharacterizationPlugin()
        plugin.main = window
        handler = window.imagepanel.acthandler
        with handler.new_category(ActionCategory.PLUGINS):
            plugin.create_actions()

        handler.selected_objects_changed([], [])
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
        assert plugin.assess_recipe(RELATIVE_DN_RECIPE.recipe_id).status is (
            RecipeReadinessStatus.READY
        )

        monkeypatch.setattr(RecipeInputDialog, "exec", _no_assignment_dialog)
        monkeypatch.setattr(CameraRecipeParameters, "edit", lambda *_a, **_k: True)
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


def test_desktop_action_explains_invalid_campaign_without_partial_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A frame lacking its exposure time is named before any computation."""
    dark, flats = _small_campaign()
    untimed_flat = _frame("flat missing exposure", 29)
    untimed_flat.metadata[FRAME_ROLE_METADATA_KEY] = "flat"
    selected_images = (*dark, untimed_flat, *flats)
    dialogs: list[RecipeInputDialog] = []

    def cancel(dialog: RecipeInputDialog) -> bool:
        dialogs.append(dialog)
        return False

    monkeypatch.setattr(RecipeInputDialog, "exec", cancel)
    monkeypatch.setattr(
        CameraRecipeParameters,
        "edit",
        lambda *_args, **_kwargs: pytest.fail("Parameters must not be edited"),
    )

    with (
        execenv.context(unattended=True),
        datalab_test_app_context(
            console=False,
            exec_loop=False,
        ) as window,
    ):
        _select(window, selected_images)
        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window

        outcome = plugin.run_relative_dn()

        assert outcome is None
        assert len(window.signalpanel) == 0
        assert len(window.imagepanel) == len(selected_images)
        (dialog,) = dialogs
        assert not dialog.ok_button.isEnabled()
        issues = dialog.issues_label.text()
        assert EXPOSURE_TIME_METADATA_KEY in issues
        assert "flat missing exposure" in issues


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


def test_desktop_photon_transfer_example_opens_and_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generated photon transfer example runs from its menu actions."""
    errors: list[str] = []
    with (
        execenv.context(unattended=True),
        datalab_test_app_context(console=False, exec_loop=False) as window,
    ):
        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window
        monkeypatch.setattr(plugin, "show_error", errors.append)
        handler = window.imagepanel.acthandler
        with handler.new_category(ActionCategory.PLUGINS):
            plugin.create_actions()

        plugin.open_photon_transfer_action.trigger()

        images = window.imagepanel.objmodel.get_all_objects()
        assert len(images) == 36
        assert window.imagepanel.objview.get_sel_objects() == images

        monkeypatch.setattr(RecipeInputDialog, "exec", _no_assignment_dialog)
        monkeypatch.setattr(
            PhotonTransferRecipeParameters,
            "edit",
            lambda self, parent: True,
        )
        plugin.run_photon_transfer_action.trigger()

        assert not errors
        titles = [obj.title for obj in window.signalpanel.objmodel.get_all_objects()]
        assert titles == [
            "Photon transfer curve",
            "Photon transfer linear fit",
            "Temporal noise vs signal",
            "Measured SNR vs signal",
            "Model SNR vs signal",
        ]
        tables = list(TableAdapter.iterate_from_obj(window.signalpanel[1]))
        assert tables[0].func_name == f"{PHOTON_TRANSFER_RECIPE.recipe_id}:metrics"


def test_desktop_dark_ramp_example_seeds_only_its_recipe_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Example values reach the dark-current dialog, never another recipe's."""
    edited: list[object] = []

    def edit(self, parent):
        edited.append(self)
        return True

    with (
        execenv.context(unattended=True),
        datalab_test_app_context(console=False, exec_loop=False) as window,
    ):
        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window
        handler = window.imagepanel.acthandler
        with handler.new_category(ActionCategory.PLUGINS):
            plugin.create_actions()
        monkeypatch.setattr(DarkCurrentRecipeParameters, "edit", edit)
        monkeypatch.setattr(PhotonTransferRecipeParameters, "edit", edit)

        plugin.launch_example(DARK_RAMP_DEMO.id)
        images = window.imagepanel.objmodel.get_all_objects()
        assert len(images) == 20
        assert plugin.example_parameter_values(
            DARK_CURRENT_RECIPE.recipe_id, images
        ) == {"conversion_gain_e_per_dn": 2.0}
        assert (
            plugin.example_parameter_values(PHOTON_TRANSFER_RECIPE.recipe_id, images)
            == {}
        )
        outcome = plugin.run_dark_current()

        (dark_current,) = edited
        assert dark_current.conversion_gain_e_per_dn == 2.0
        assert outcome is not None
        assert len(window.imagepanel) == 20 + 3
        assert len(window.signalpanel) == 3
        hot_map = next(
            image
            for image in window.imagepanel.objmodel.get_all_objects()
            if image.title.startswith("Hot-pixel map")
        )
        assert 0 < np.count_nonzero(hot_map.data == 1) < 100


def test_trying_the_photon_transfer_ladder_with_relative_dn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One exposure ladder also feeds the relative-DN linearity analysis."""
    monkeypatch.setattr(RecipeInputDialog, "exec", _no_assignment_dialog)
    monkeypatch.setattr(CameraRecipeParameters, "edit", lambda *_a, **_k: True)
    with (
        execenv.context(unattended=True),
        datalab_test_app_context(console=False, exec_loop=False) as window,
    ):
        plugin = CameraDetectorCharacterizationPlugin()
        plugin.main = window

        outcome = plugin.try_example(
            PHOTON_TRANSFER_DEMO.id, RELATIVE_DN_RECIPE.recipe_id
        )

        assert outcome is not None
        assert len(window.imagepanel) == 36 + 5
        assert window.signalpanel[1].title == "Camera response"
