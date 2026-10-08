"""Tests of the scientific camera simulator instrument."""

from __future__ import annotations

import numpy as np
import pytest
from datalab.plugins.instruments import InstrumentAcquisition, InstrumentFrame
from datalab.plugins.recipe_binding import (
    RecipeReadinessStatus,
    assess_recipe_inputs,
    create_recipe_parameters,
)
from datalab.plugins.recipes import RecipeExecutionContext

from datalab_camera_characterization.simulator import (
    MAX_ACQUISITION_PIXELS,
    CameraSimulator,
    parse_exposures_ms,
)
from datalab_camera_characterization.workflow import (
    DARK_CURRENT_RECIPE,
    EXPOSURE_TIME_METADATA_KEY,
    FRAME_ROLE_METADATA_KEY,
    PHOTON_TRANSFER_RECIPE,
    RELATIVE_DN_RECIPE,
    PhotonTransferRecipeParameters,
)


def _ready(recipe, objects) -> bool:
    """Return True if a recipe can run on objects with its default parameters."""
    parameters = create_recipe_parameters(recipe, {})
    readiness = assess_recipe_inputs(recipe, objects, parameters)
    return readiness.status is RecipeReadinessStatus.READY


def test_live_frame_draws_new_noise_on_the_same_sensor() -> None:
    """Live frames show one exposure with the ADC range and summary levels."""
    camera = CameraSimulator()
    first = camera.preview()
    second = camera.preview()

    assert isinstance(first, InstrumentFrame)
    (image,) = first.objects
    assert image.data.shape == (96, 128)
    assert image.title == "Flat 10 ms"
    assert first.value_range == (0.0, 4095.0)
    assert first.summary.startswith("Flat frame, 10 ms: mean ")
    assert not np.array_equal(image.data, second.objects[0].data)

    camera.settings.shutter_open = False
    camera.settings.mode = "sequence"
    camera.settings.exposures_ms = "5, 50"
    dark = camera.preview()
    assert dark.objects[0].title == "Dark 50 ms"
    assert dark.summary.startswith("Dark frame, 50 ms")


def test_single_acquisition_adds_dark_and_flat_frames() -> None:
    """One exposure gives flat frames, plus dark frames at the same exposure."""
    camera = CameraSimulator()
    acquisition = camera.acquire()

    assert isinstance(acquisition, InstrumentAcquisition)
    assert acquisition.group_title == "Camera SN 20261007 - acquisition 001"
    assert [image.title for image in acquisition.objects] == [
        "Dark 10 ms 01",
        "Dark 10 ms 02",
        "Dark 10 ms 03",
        "Dark 10 ms 04",
        "Flat 10 ms 01",
        "Flat 10 ms 02",
    ]
    assert [
        image.metadata[FRAME_ROLE_METADATA_KEY] for image in acquisition.objects
    ] == ["dark"] * 4 + ["flat"] * 2
    assert {
        image.metadata[EXPOSURE_TIME_METADATA_KEY] for image in acquisition.objects
    } == {0.01}
    assert camera.acquire().group_title.endswith("acquisition 002")


def test_photon_transfer_sequence_is_ready_for_the_camera_methods() -> None:
    """A flat exposure ladder with darks suits the PTC and relative-DN methods."""
    camera = CameraSimulator()
    camera.settings.mode = "sequence"
    images = camera.acquire().objects

    assert len(images) == 4 + 2 * 12
    for recipe in (PHOTON_TRANSFER_RECIPE, RELATIVE_DN_RECIPE):
        assert _ready(recipe, images), recipe.recipe_id

    outcome = PHOTON_TRANSFER_RECIPE.run(
        assess_recipe_inputs(
            PHOTON_TRANSFER_RECIPE, images, PhotonTransferRecipeParameters()
        ).bindings,
        PhotonTransferRecipeParameters(),
        RecipeExecutionContext(),
    )
    (metrics,) = outcome.results
    rows = {row[0]: row for row in metrics.value.data}
    assert rows["Conversion gain"][1] == pytest.approx(2.0, rel=0.1)


def test_dark_ramp_sequence_is_ready_for_the_dark_current_method() -> None:
    """With the shutter closed, an exposure sequence is a dark ramp."""
    camera = CameraSimulator()
    camera.settings.mode = "sequence"
    camera.settings.shutter_open = False
    camera.settings.exposures_ms = "500, 1000, 2000, 4000, 8000"
    camera.settings.frame_count = 4
    camera.settings.dark_current = 40.0
    images = camera.acquire().objects

    assert len(images) == 20
    assert {image.metadata[FRAME_ROLE_METADATA_KEY] for image in images} == {"dark"}
    assert _ready(DARK_CURRENT_RECIPE, images)


def test_invalid_settings_are_reported() -> None:
    """Unreadable exposure lists and oversized acquisitions are rejected."""
    assert parse_exposures_ms("1; 2 4,8") == (1.0, 2.0, 4.0, 8.0)
    for text in ("", "1, a", "1, -2", "nan"):
        with pytest.raises(ValueError, match="positive numbers"):
            parse_exposures_ms(text)

    camera = CameraSimulator()
    camera.settings.width = camera.settings.height = 2048
    camera.settings.frame_count = 100
    with pytest.raises(ValueError, match="megapixels"):
        camera.acquire()
    assert 2048 * 2048 * 104 > MAX_ACQUISITION_PIXELS
