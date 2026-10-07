"""Dark-ramp core method and recipe."""

from __future__ import annotations

import numpy as np
import pytest
from datalab.recipes import RecipeExecutionContext, RecipeValidationError
from sigima.objects import create_image

from datalab_camera_characterization.core import (
    CameraCharacterizationError,
    CameraExposureSeries,
    CameraSimulationParameters,
    DarkCurrentParameters,
    characterize_dark_current,
    simulate_camera_frames,
    validate_dark_ramp_inputs,
)
from datalab_camera_characterization.workflow import (
    DARK_CURRENT_RECIPE,
    EXPOSURE_TIME_METADATA_KEY,
    DarkCurrentRecipeParameters,
)

EXPOSURES_S = (1.0, 2.0, 4.0, 8.0)


def _series(glow: float = 0.0) -> tuple[CameraExposureSeries, ...]:
    """Simulate one dark ramp of a sensor with hot pixels."""
    series = []
    for stream, exposure_time_s in enumerate(EXPOSURES_S, start=1):
        result = simulate_camera_frames(
            CameraSimulationParameters(
                shape=(64, 64),
                frame_count=4,
                exposure_time_s=exposure_time_s,
                signal_electrons=0.0,
                dark_current_e_per_s=20.0,
                dark_current_nonuniformity_fraction=0.05,
                dark_hot_pixel_fraction=0.003,
                dark_hot_pixel_factor=25.0,
                amplifier_glow_e_per_s=glow,
                defective_pixel_fraction=0.001,
                seed=11,
                noise_stream=stream,
            )
        )
        series.append(CameraExposureSeries(result.frames_dn, exposure_time_s))
    return tuple(series), result.truth


@pytest.mark.parametrize("glow", [0.0, 200.0])
def test_dark_ramp_recovers_dark_current_and_hot_pixels(glow: float) -> None:
    """Hot pixels are isolated outliers; smooth glow is not reported as hot."""
    series, truth = _series(glow)

    result = characterize_dark_current(
        series,
        DarkCurrentParameters(conversion_gain_e_per_dn=2.0),
    )
    regular = result.regular_pixel_mask
    true_rate = truth.dark_current_map_e_per_s[regular].mean()

    assert result.to_electrons(result.dark_current_dn_per_s) == pytest.approx(
        true_rate, rel=0.02
    )
    hot = truth.dark_hot_pixel_mask
    assert np.all(result.hot_pixel_mask[hot])
    # A steep glow gradient may cause at most one statistical false alarm.
    assert np.count_nonzero(result.hot_pixel_mask & ~hot) <= 1
    assert result.stuck_pixel_count == 4
    assert result.conversion_gain_from_dark_e_per_dn == pytest.approx(2.0, rel=0.1)
    assert result.fit_r_squared > 0.999


def test_dark_ramp_reports_insufficient_levels_and_exposure_order() -> None:
    """Too few or unordered dark levels produce structured errors."""
    series, _truth = _series()

    short = validate_dark_ramp_inputs(series[:2])
    unordered = validate_dark_ramp_inputs((series[1], series[0], series[2]))

    assert "insufficient_dark_levels" in {item.code for item in short.errors}
    assert "exposure_order" in {item.code for item in unordered.errors}
    with pytest.raises(CameraCharacterizationError, match="insufficient_dark_levels"):
        characterize_dark_current(series[:2])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"background_window": 4},
        {"conversion_gain_e_per_dn": 0.0},
        {"hot_pixel_threshold_sigma": 0.0},
    ],
)
def test_dark_current_parameters_are_validated(kwargs: dict) -> None:
    """Invalid settings are rejected before any calculation."""
    with pytest.raises(ValueError):
        DarkCurrentParameters(**kwargs)


def test_dark_current_recipe_builds_maps_and_anchored_table() -> None:
    """The recipe returns ramps, maps, histogram and an anchored table."""
    series, truth = _series()
    images = []
    for item in series:
        for frame in item.frames_dn:
            image = create_image(f"dark {item.exposure_time_s:g}", frame.copy())
            image.metadata[EXPOSURE_TIME_METADATA_KEY] = item.exposure_time_s
            images.append(image)
    parameters = DarkCurrentRecipeParameters()
    parameters.conversion_gain_e_per_dn = 2.0

    outcome = DARK_CURRENT_RECIPE.run(
        {"dark_frames": tuple(images)},
        parameters,
        RecipeExecutionContext(),
    )

    outputs = {output.id: output.value for output in outcome.objects}
    assert list(outputs) == [
        "dark_ramp",
        "dark_variance_ramp",
        "dark_current_map",
        "offset_map",
        "hot_pixel_map",
        "dark_current_distribution",
    ]
    assert outputs["dark_current_map"].zunit == "e-/s"
    assert np.count_nonzero(outputs["hot_pixel_map"].data == 1) == np.count_nonzero(
        truth.dark_hot_pixel_mask
    )
    (metrics,) = outcome.results
    assert metrics.anchor_id == "dark_ramp"
    rows = {row[0]: row for row in metrics.value.data}
    assert rows["Mean dark current"][2] == "e-/s"


def test_dark_current_recipe_requires_exposure_metadata() -> None:
    """Dark frames without exposure time cannot be placed on the ramp."""
    image = create_image("dark", np.zeros((4, 4), dtype=np.uint16))

    with pytest.raises(RecipeValidationError, match="Dark image"):
        DARK_CURRENT_RECIPE.run(
            {"dark_frames": (image,)},
            DarkCurrentRecipeParameters(),
            RecipeExecutionContext(),
        )
