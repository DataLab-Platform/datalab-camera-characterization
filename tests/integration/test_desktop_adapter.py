"""DataLab Desktop adapter contract tests."""

from __future__ import annotations

import numpy as np
from datalab.adapters_metadata import TableAdapter
from datalab.env import execenv
from datalab.gui.recipe_runner import RecipeRunner
from datalab.plugins import PluginCapability
from datalab.recipes import RECIPE_RUN_RECORD_OPTION, RecipeRunRecord
from datalab.tests import datalab_test_app_context
from sigima.objects import ImageObj, create_image

from datalab_camera_characterization import PLUGIN_ID
from datalab_camera_characterization.adapters.desktop import (
    CameraDetectorCharacterizationPlugin,
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


def _frame(title: str, value: int, exposure_time_s: float | None = None) -> ImageObj:
    """Create one recipe input image."""
    image = create_image(title, np.full((2, 3), value, dtype=np.uint16))
    if exposure_time_s is not None:
        image.metadata[EXPOSURE_TIME_METADATA_KEY] = exposure_time_s
    return image


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
