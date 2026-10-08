"""Scientific validation of the generated Camera demonstrations against truth."""

from __future__ import annotations

import numpy as np
import pytest
from datalab.plugins.recipe_binding import (
    RecipeReadinessStatus,
    assess_recipe_inputs,
    create_recipe_parameters,
)
from datalab.plugins.recipes import RecipeExecutionContext

from datalab_camera_characterization import demo
from datalab_camera_characterization.core import simulate_camera_frames
from datalab_camera_characterization.workflow import (
    CAMERA_RECIPES,
    DARK_CURRENT_RECIPE,
    PHOTON_TRANSFER_RECIPE,
    RELATIVE_DN_RECIPE,
    CameraRecipeParameters,
    DarkCurrentRecipeParameters,
    PhotonTransferRecipeParameters,
    infer_frame_role,
)


def _rows(outcome) -> dict[str, list[object]]:
    """Return the recipe metrics table rows by metric name."""
    (metrics,) = outcome.results
    return {row[0]: row for row in metrics.value.data}


@pytest.mark.parametrize(
    "example", (demo.PHOTON_TRANSFER_DEMO, demo.DARK_RAMP_DEMO), ids=lambda e: e.id
)
def test_generated_examples_suit_every_declared_recipe(example) -> None:
    """Each generated example is ready for the recipes it is designed for."""
    data = demo.GENERATED_EXAMPLES[example.id]()
    recipes = {recipe.recipe_id: recipe for recipe in CAMERA_RECIPES}
    for recipe_id in example.recipe_ids:
        recipe = recipes[recipe_id]
        parameters = create_recipe_parameters(recipe, data.values_for(recipe_id))
        readiness = assess_recipe_inputs(recipe, data.objects, parameters)
        assert readiness.status is RecipeReadinessStatus.READY, readiness


def test_photon_transfer_ladder_measures_relative_dn_linearity() -> None:
    """The PTC ladder also gives the response slope and the saturation onset."""
    data = demo.build_photon_transfer_campaign()
    parameters = CameraRecipeParameters()
    readiness = assess_recipe_inputs(RELATIVE_DN_RECIPE, data.objects, parameters)

    outcome = RELATIVE_DN_RECIPE.run(
        readiness.bindings, parameters, RecipeExecutionContext()
    )
    rows = _rows(outcome)
    rate_dn_per_s = demo.PHOTON_TRANSFER_RATE_E_PER_S / demo.CONVERSION_GAIN_E_PER_DN
    onset_s = (4_095.0 - 100.0) / rate_dn_per_s

    assert rows["Response slope"][1] == pytest.approx(rate_dn_per_s, rel=0.03)
    assert rows["Saturation onset exposure"][1] == pytest.approx(onset_s, rel=0.06)


def test_photon_transfer_demo_recovers_sensor_truth() -> None:
    """Gain, read noise and ADC-limited saturation match the simulated sensor."""
    images = demo.build_photon_transfer_campaign().objects
    inputs = {
        role: tuple(image for image in images if infer_frame_role(image) == kind)
        for role, kind in (("dark_frames", "dark"), ("flat_frames", "flat"))
    }

    outcome = PHOTON_TRANSFER_RECIPE.run(
        inputs,
        PhotonTransferRecipeParameters(),
        RecipeExecutionContext(),
    )
    rows = _rows(outcome)
    gain = demo.CONVERSION_GAIN_E_PER_DN
    adc_limit_e = gain * (4_095.0 - 100.0)

    assert len(inputs["dark_frames"]) == demo.PHOTON_TRANSFER_DARK_FRAMES
    assert rows["Conversion gain"][1] == pytest.approx(gain, rel=0.03)
    # Electronic read noise of 3 e- plus 1/12 DN^2 of ADC quantization.
    assert rows["Read noise"][1] == pytest.approx(
        gain * np.sqrt((3.0 / gain) ** 2 + 1.0 / 12.0), rel=0.1
    )
    assert 0.9 * adc_limit_e <= rows["Saturation capacity"][1] <= adc_limit_e
    assert rows["Saturation capacity"][3] == "Reached"
    assert rows["Dynamic range"][1] == pytest.approx(
        20.0 * np.log10(adc_limit_e / 3.0), abs=1.5
    )


def test_dark_ramp_demo_recovers_dark_current_truth() -> None:
    """Mean dark current, its non-uniformity and hot pixels match the truth."""
    data = demo.build_dark_ramp_campaign()
    parameters = DarkCurrentRecipeParameters()
    for name, value in data.values_for(DARK_CURRENT_RECIPE.recipe_id).items():
        setattr(parameters, name, value)
    truth = simulate_camera_frames(
        demo._sensor_parameters(
            demo.DARK_RAMP_SEED,
            frame_count=1,
            exposure_time_s=1.0,
            signal_electrons=0.0,
            dark_current_e_per_s=demo.DARK_CURRENT_E_PER_S,
            dark_current_nonuniformity_fraction=(
                demo.DARK_CURRENT_NONUNIFORMITY_FRACTION
            ),
            dark_hot_pixel_fraction=demo.DARK_HOT_PIXEL_FRACTION,
            dark_hot_pixel_factor=demo.DARK_HOT_PIXEL_FACTOR,
            amplifier_glow_e_per_s=demo.AMPLIFIER_GLOW_E_PER_S,
        )
    ).truth

    outcome = DARK_CURRENT_RECIPE.run(
        {"dark_frames": data.objects},
        parameters,
        RecipeExecutionContext(),
    )
    rows = _rows(outcome)
    outputs = {output.id: output.value for output in outcome.objects}
    hot_found = outputs["hot_pixel_map"].data == 1
    hot_truth = truth.dark_hot_pixel_mask
    regular = outputs["hot_pixel_map"].data == 0
    true_rates = truth.dark_current_map_e_per_s[regular]

    assert rows["Mean dark current"][1] == pytest.approx(np.mean(true_rates), rel=0.03)
    assert rows["Dark-current non-uniformity"][1] == pytest.approx(
        np.std(true_rates, ddof=1), rel=0.1
    )
    true_positives = np.count_nonzero(hot_found & hot_truth)
    assert true_positives >= 0.95 * np.count_nonzero(hot_truth)
    assert true_positives >= 0.95 * np.count_nonzero(hot_found)
    assert rows["Conversion gain from dark shot noise"][1] == pytest.approx(
        demo.CONVERSION_GAIN_E_PER_DN, rel=0.05
    )
    # The glow is dark current: it shows in the rate map, not in the offset map.
    rate_map = outputs["dark_current_map"].data
    offset_map = outputs["offset_map"].data
    assert np.nanmedian(rate_map[-6:, -6:]) > 2.0 * np.nanmedian(rate_map[:32, :32])
    assert np.nanmedian(offset_map[-6:, -6:]) == pytest.approx(
        np.nanmedian(offset_map[:32, :32]), abs=5.0
    )
