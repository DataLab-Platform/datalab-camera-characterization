"""DataLab-Web adapter contract tests."""

from __future__ import annotations

import numpy as np
import pytest
from datalab.plugins import PluginCapability
from datalab.recipes import RecipeValidationError
from sigima.objects import create_image

from datalab_camera_characterization import PLUGIN_ID, __version__
from datalab_camera_characterization.adapters.web import (
    CAMERA_QUICKSTART,
    WEB_STATUS,
    CameraDetectorCharacterizationWebPlugin,
    build_recipe_inputs,
    get_web_manifest,
    read_quickstart_bytes,
    run_relative_dn_recipe,
)
from datalab_camera_characterization.demo import DARK_RAMP_DEMO, PHOTON_TRANSFER_DEMO
from datalab_camera_characterization.workflow import (
    DARK_CURRENT_RECIPE,
    EXPOSURE_TIME_METADATA_KEY,
    FRAME_ROLE_METADATA_KEY,
    PHOTON_TRANSFER_RECIPE,
    RELATIVE_DN_RECIPE,
)


def _frame(title: str, value: int, exposure_time_s: float | None = None):
    """Create one browser-imported Camera frame."""
    image = create_image(title, np.full((2, 3), value, dtype=np.uint16))
    if exposure_time_s is not None:
        image.metadata[EXPOSURE_TIME_METADATA_KEY] = exposure_time_s
    return image


def test_web_adapter_declares_verified_version_matrix_and_quickstart() -> None:
    """The qualified bundle declares its exact verified browser target."""
    manifest = get_web_manifest()

    assert WEB_STATUS == "verified"
    assert manifest == {
        "plugin_id": PLUGIN_ID,
        "plugin_version": __version__,
        "web_status": "verified",
        "datalab_web_version": "0.9.0",
        "pyodide_version": "0.26.4",
        "recipes": [
            {"recipe_id": recipe.recipe_id, "recipe_version": recipe.version}
            for recipe in (
                RELATIVE_DN_RECIPE,
                PHOTON_TRANSFER_RECIPE,
                DARK_CURRENT_RECIPE,
            )
        ],
        "examples": ["quickstart", "photon-transfer", "dark-ramp"],
        "quickstart_filename": "camera_quickstart.h5",
    }
    assert read_quickstart_bytes().startswith(b"\x89HDF\r\n\x1a\n")
    assert CameraDetectorCharacterizationWebPlugin.get_plugin_id() == PLUGIN_ID
    assert CameraDetectorCharacterizationWebPlugin.get_recipes() == (
        RELATIVE_DN_RECIPE,
        PHOTON_TRANSFER_RECIPE,
        DARK_CURRENT_RECIPE,
    )
    assert CameraDetectorCharacterizationWebPlugin.get_examples() == (
        CAMERA_QUICKSTART,
        PHOTON_TRANSFER_DEMO,
        DARK_RAMP_DEMO,
    )
    assert PluginCapability.APPLICATION in (
        CameraDetectorCharacterizationWebPlugin.PLUGIN_INFO.capabilities
    )
    assert (
        CameraDetectorCharacterizationWebPlugin.materialize_example(
            CAMERA_QUICKSTART.id
        )
        is None
    )


def test_web_adapter_maps_imported_images_and_runs_headless_recipe() -> None:
    """Browser-imported images use exposure metadata for deterministic roles."""
    dark = (_frame("dark 1", 9), _frame("dark 2", 11))
    flats = tuple(
        _frame(f"flat {exposure} {index}", value, exposure)
        for exposure, value in ((1.0, 30), (2.0, 50))
        for index in range(2)
    )

    inputs = build_recipe_inputs((*dark, *flats))
    suggested = RELATIVE_DN_RECIPE.suggest_bindings((*dark, *flats))
    outcome = run_relative_dn_recipe(
        (*dark, *flats),
        {"saturation_dn": 100.0},
    )

    assert inputs == {"dark_frames": dark, "flat_frames": flats}
    assert suggested == inputs
    assert outcome.objects[0].id == "response"
    assert {output.id for output in outcome.objects} >= {
        "dsnu_like_map",
        "prnu_like_map",
    }
    assert outcome.results[0].anchor_id == "response"


def test_web_adapter_rejects_campaign_without_both_roles() -> None:
    """Browser role inference fails before executing an incomplete campaign."""
    with pytest.raises(RecipeValidationError, match="flat"):
        build_recipe_inputs((_frame("dark 1", 10), _frame("dark 2", 10)))


def test_web_adapter_generates_examples_with_explicit_frame_roles() -> None:
    """Generated demos tag frame roles so every recipe binds them correctly."""
    ptc = CameraDetectorCharacterizationWebPlugin.materialize_example(
        PHOTON_TRANSFER_DEMO.id
    )
    ramp = CameraDetectorCharacterizationWebPlugin.materialize_example(
        DARK_RAMP_DEMO.id
    )

    ptc_bindings = PHOTON_TRANSFER_RECIPE.suggest_bindings(ptc.objects)
    ramp_bindings = DARK_CURRENT_RECIPE.suggest_bindings(ramp.objects)

    assert len(ptc_bindings["dark_frames"]) == 4
    assert len(ptc_bindings["flat_frames"]) == 32
    # Dark-ramp frames carry exposure times but stay dark frames.
    assert all(EXPOSURE_TIME_METADATA_KEY in image.metadata for image in ramp.objects)
    assert ramp_bindings == {"dark_frames": ramp.objects}
    assert {image.metadata[FRAME_ROLE_METADATA_KEY] for image in ramp.objects} == {
        "dark"
    }
    assert dict(ptc.parameter_values) == {}
    assert dict(ramp.parameter_values) == {
        DARK_CURRENT_RECIPE.recipe_id: {"conversion_gain_e_per_dn": 2.0}
    }
    with pytest.raises(RecipeValidationError, match="flat"):
        build_recipe_inputs(ramp.objects)
