"""The host preflight and all three runners must use the same physical inputs."""

from __future__ import annotations

import numpy as np
import pytest
from datalab.plugins.recipe_binding import RecipeReadinessStatus, assess_recipe_inputs
from datalab.plugins.recipes import RecipeExecutionContext, RecipeValidationError
from sigima.objects import ImageObj, create_image, create_image_roi

from datalab_camera_characterization.core import metadata_key
from datalab_camera_characterization.simulator import CameraSimulator
from datalab_camera_characterization.workflow import (
    CAMERA_RECIPES,
    DARK_CURRENT_RECIPE,
    EXPOSURE_TIME_METADATA_KEY,
    FRAME_ROLE_METADATA_KEY,
    RELATIVE_DN_RECIPE,
)
from datalab_camera_characterization.workflow.adc import ADC_RESOLUTION_KEY


def _inputs(recipe, shift: int = 0):
    checker = 2 * (np.indices((8, 8)).sum(axis=0) % 2) - 1

    def series(role, levels):
        return tuple(
            create_image(
                f"{role} {t}s #{rep}",
                ((mean + rep * checker * amplitude).astype(np.uint16) << shift),
                units=("mm", "mm", "DN"),
                metadata={
                    FRAME_ROLE_METADATA_KEY: role,
                    EXPOSURE_TIME_METADATA_KEY: t,
                    metadata_key("bit_depth"): 12,
                    metadata_key("saturation_dn"): 4095,
                    metadata_key("bit_shift"): shift,
                },
            )
            for t, mean, amplitude in levels
            for rep in (-1, 1)
        )

    if recipe is DARK_CURRENT_RECIPE:
        return {"dark_frames": series("dark", [(t, 100 + 2 * t, 1) for t in (1, 2, 4)])}
    # Dark variance = 2 LSB². Each flat pair has variance 2*a²; gain = 2 e-/LSB.
    return {
        "dark_frames": series("dark", [(0, 100, 1)]),
        "flat_frames": series(
            "flat", [(4 * (a * a - 1), 100 + 4 * (a * a - 1), a) for a in range(2, 8)]
        ),
    }


def _reject(recipe, inputs, parameters, text):
    messages = [d.message for d in recipe.check_inputs(inputs, parameters)]
    assert any(text in message for message in messages), messages
    with pytest.raises(RecipeValidationError) as error:
        recipe.run(inputs, parameters, RecipeExecutionContext())
    assert str(error.value) == "; ".join(messages)


@pytest.mark.parametrize(
    "recipe", CAMERA_RECIPES, ids=lambda r: r.recipe_id.split(":")[-1]
)
def test_native_and_left_aligned_data_give_identical_results(recipe):
    outputs = []
    for shift in (0, 4):
        inputs = _inputs(recipe, shift)
        parameters = recipe.parameter_class()
        if recipe is DARK_CURRENT_RECIPE:
            parameters.conversion_gain_e_per_dn = 2.0
        original = inputs["dark_frames"][0]
        stored = original.data.copy()
        assert not recipe.check_inputs(inputs, parameters)
        outcome = recipe.run(inputs, parameters, RecipeExecutionContext())
        provenance = outcome.objects[0].value.metadata[ADC_RESOLUTION_KEY]
        assert provenance["saturation_dn"] == 4095
        assert provenance["encodings"][0]["stored_counts_per_lsb"] == 2**shift
        assert parameters.saturation_dn == 0 and parameters.bit_shift == -1
        np.testing.assert_array_equal(original.data, stored)
        assert original.zunit == "DN"
        assert original.data.flags.writeable
        assert original.metadata[metadata_key("bit_shift")] == shift
        outputs.append({o.id: o.value for o in outcome.objects})
    for key, native in outputs[0].items():
        converted = outputs[1][key]
        if isinstance(native, ImageObj):
            np.testing.assert_array_equal(converted.data, native.data)
            assert converted.zunit == native.zunit
        else:
            np.testing.assert_array_equal(converted.x, native.x)
            np.testing.assert_array_equal(converted.y, native.y)
    if recipe is DARK_CURRENT_RECIPE:
        np.testing.assert_allclose(outputs[1]["dark_current_map"].data, 4.0)
        assert outputs[1]["dark_current_map"].zunit == "e-/s"
    elif recipe is RELATIVE_DN_RECIPE:
        assert outputs[1]["mean_dark"].zunit == "LSB"


@pytest.mark.parametrize(
    "recipe", CAMERA_RECIPES, ids=lambda r: r.recipe_id.split(":")[-1]
)
def test_voltage_cannot_be_overridden_as_lsb(recipe):
    inputs = _inputs(recipe)
    inputs["dark_frames"][-1].zunit = "V"
    parameters = recipe.parameter_class()
    parameters.assume_lsb = True
    _reject(recipe, inputs, parameters, "convert to linear ADC codes")


def test_legacy_requires_binding_unit_rail_and_alignment_without_editing_images():
    recipe = DARK_CURRENT_RECIPE
    inputs = _inputs(recipe)
    for image in inputs["dark_frames"]:
        image.data = image.data.astype(np.uint16)
        image.metadata = {
            EXPOSURE_TIME_METADATA_KEY: image.metadata[EXPOSURE_TIME_METADATA_KEY]
        }
        image.zunit = ""
    p = recipe.parameter_class()
    assert not assess_recipe_inputs(recipe, inputs["dark_frames"], p).can_run
    _reject(recipe, inputs, p, "missing Z unit")
    p.assume_lsb = True
    _reject(recipe, inputs, p, "unknown ADC rail")
    p.saturation_dn = 4095
    _reject(recipe, inputs, p, "unknown ADC alignment")
    p.bit_shift = 0
    assert assess_recipe_inputs(recipe, parameters=p, bindings=inputs).can_run
    result = recipe.run(inputs, p, RecipeExecutionContext())
    encoding = result.objects[0].value.metadata[ADC_RESOLUTION_KEY]["encodings"][0]
    assert encoding["unit_source"] == "parameter:assume_lsb"
    assert encoding["rail_source"] == "parameter:saturation_dn"
    assert encoding["shift_source"] == "parameter:bit_shift"
    assert encoding["role_source"] == "binding"
    assert all(not image.zunit for image in inputs["dark_frames"])
    assert all(FRAME_ROLE_METADATA_KEY not in i.metadata for i in inputs["dark_frames"])


@pytest.mark.parametrize(
    ("change", "text"),
    [
        ("role", "frame_role"),
        ("unknown-role", "frame_role"),
        ("origin", "origins"),
        ("spacing", "spacings"),
        ("coordinates", "vectors differ"),
        ("axis-unit", "axis units"),
        ("processing-roi", "extract the same ROI"),
        ("roi", "incompatible roi"),
        ("binning", "incompatible binning"),
        ("sensor_id", "incompatible sensor_id"),
        ("readout_mode", "incompatible readout_mode"),
        ("conversion_gain_e_per_dn", "incompatible conversion_gain"),
        ("padding", "padding bits"),
        ("above-rail", "outside declared ADC range"),
        ("rail", "incompatible saturation_dn"),
        ("depth", "does not fit dtype"),
    ],
)
def test_incompatible_acquisition_is_blocked_in_preflight_and_execution(change, text):
    inputs = _inputs(DARK_CURRENT_RECIPE, shift=4)
    images = inputs["dark_frames"]
    last = images[-1]
    if change in ("role", "unknown-role"):
        last.metadata[FRAME_ROLE_METADATA_KEY] = "flat" if change == "role" else "other"
    elif change == "origin":
        last.x0 = 11
    elif change == "spacing":
        last.dy = 0.5
    elif change == "coordinates":
        last.set_coords(0.5 + np.arange(8), np.arange(8))
    elif change == "axis-unit":
        last.yunit = "cm"
    elif change == "processing-roi":
        last.roi = create_image_roi("rectangle", [1, 2, 3, 4], indices=True)
    elif change in (
        "roi",
        "binning",
        "sensor_id",
        "readout_mode",
        "conversion_gain_e_per_dn",
    ):
        images[0].metadata[metadata_key(change)] = {
            "roi": [0, 1, 8, 8],
            "binning": [1, 1],
            "sensor_id": "A",
            "readout_mode": "slow",
            "conversion_gain_e_per_dn": 1.0,
        }[change]
        last.metadata[metadata_key(change)] = {
            "roi": [1, 0, 8, 8],
            "binning": [1, 2],
            "sensor_id": "B",
            "readout_mode": "fast",
            "conversion_gain_e_per_dn": 2.0,
        }[change]
    elif change == "padding":
        last.data[0, 0] += 1
    elif change == "above-rail":
        last.data[0, 0] = 65535
    elif change == "rail":
        last.metadata[metadata_key("saturation_dn")] = 4000
    elif change == "depth":
        last.metadata[metadata_key("bit_depth")] = 14
    _reject(DARK_CURRENT_RECIPE, inputs, DARK_CURRENT_RECIPE.parameter_class(), text)


def test_mixed_unknown_role_requires_assignment_even_with_enough_tagged_frames():
    recipe = RELATIVE_DN_RECIPE
    inputs = _inputs(recipe)
    del inputs["flat_frames"][-1].metadata[FRAME_ROLE_METADATA_KEY]
    candidates = inputs["flat_frames"] + inputs["dark_frames"]
    assert not assess_recipe_inputs(recipe, candidates).can_run
    assert assess_recipe_inputs(recipe, bindings=inputs).can_run


@pytest.mark.parametrize("recipe", CAMERA_RECIPES, ids=lambda r: r.title)
def test_missing_declarations_open_parameters_but_never_authorize_execution(recipe):
    inputs = _inputs(recipe)
    frames = sum(inputs.values(), ())
    for image in frames:
        image.zunit = ""
        for key in ("bit_depth", "saturation_dn", "bit_shift"):
            del image.metadata[metadata_key(key)]
    expected = {"missing-unit", "missing-rail", "missing-shift"}
    p = recipe.parameter_class()
    if recipe is not DARK_CURRENT_RECIPE:
        for image in inputs["dark_frames"]:
            del image.metadata[EXPOSURE_TIME_METADATA_KEY]
        expected.add("unknown-dark-exposure")
    assessment = assess_recipe_inputs(recipe, frames, p)
    assert assessment.status is RecipeReadinessStatus.WARNINGS
    assert {d.code for d in assessment.diagnostics} == expected
    with pytest.raises(RecipeValidationError, match="missing Z unit"):
        recipe.run(inputs, p, RecipeExecutionContext())
    p.assume_lsb, p.saturation_dn, p.bit_shift = True, 4095, 0
    if recipe is not DARK_CURRENT_RECIPE:
        with pytest.raises(RecipeValidationError, match="Unknown dark exposure"):
            recipe.run(inputs, p, RecipeExecutionContext())
        p.dark_reference_exposure_s = 0.0
    assert assess_recipe_inputs(recipe, frames, p).status is RecipeReadinessStatus.READY
    assert recipe.run(inputs, p, RecipeExecutionContext()).results


@pytest.mark.parametrize(
    ("defect", "text"),
    [
        ("voltage", "convert to linear ADC codes"),
        ("geometry", "origins"),
        ("rail", "incompatible saturation_dn"),
        ("shift", "bit_shift must"),
        ("padding", "padding bits"),
        ("impossible-alignment", "outside declared ADC range"),
        ("exposure", "invalid metadata"),
        ("role", "disagree"),
    ],
)
def test_missing_declarations_never_hide_a_known_error(defect, text):
    recipe = RELATIVE_DN_RECIPE
    inputs = _inputs(recipe)
    frames = sum(inputs.values(), ())
    for image in frames:
        image.zunit = ""
        del image.metadata[metadata_key("bit_shift")]
    last = frames[-1]
    if defect == "voltage":
        last.zunit = "mV"
    elif defect == "geometry":
        last.x0 = 11
    elif defect == "rail":
        last.metadata[metadata_key("saturation_dn")] = 2000
    elif defect in ("shift", "padding"):
        del last.metadata[metadata_key("bit_depth")]
        del last.metadata[metadata_key("saturation_dn")]
        last.metadata[metadata_key("bit_shift")] = -2 if defect == "shift" else 4
    elif defect == "impossible-alignment":
        last.data[0, 0] = (
            65535  # Above a 12-bit rail even at the largest fitting shift.
        )
    elif defect == "exposure":
        last.metadata[EXPOSURE_TIME_METADATA_KEY] = -1
    else:
        last.metadata[FRAME_ROLE_METADATA_KEY] = "dark"
    p = recipe.parameter_class()
    assessment = assess_recipe_inputs(recipe, parameters=p, bindings=inputs)
    assert assessment.status is RecipeReadinessStatus.NOT_READY
    _reject(recipe, inputs, p, text)


def test_neighbouring_exposures_are_not_pooled():
    inputs = _inputs(DARK_CURRENT_RECIPE)
    inputs["dark_frames"][0].metadata[EXPOSURE_TIME_METADATA_KEY] += 1e-12
    _reject(
        DARK_CURRENT_RECIPE,
        inputs,
        DARK_CURRENT_RECIPE.parameter_class(),
        "fewer than 2 frames",
    )


def test_sensor_roi_and_binning_must_describe_the_stored_pixel_grid():
    recipe = DARK_CURRENT_RECIPE
    inputs = _inputs(recipe)
    for image in inputs["dark_frames"]:
        image.metadata[metadata_key("roi")] = [12, 4, 16, 8]
        image.metadata[metadata_key("binning")] = [2, 1]
    p = recipe.parameter_class()
    assert not recipe.check_inputs(inputs, p)
    for image in inputs["dark_frames"]:
        image.metadata[metadata_key("binning")] = 2
    _reject(recipe, inputs, p, "ROI width/height and binning disagree")


def test_native_gain_is_explicit_and_never_rescaled_by_storage_shift():
    recipe = DARK_CURRENT_RECIPE
    inputs = _inputs(recipe, shift=4)
    for image in inputs["dark_frames"]:
        image.metadata[metadata_key("conversion_gain_e_per_dn")] = 2.0
    p = recipe.parameter_class()
    p.conversion_gain_e_per_dn = 2.0 / 16
    _reject(recipe, inputs, p, "conversion_gain_e_per_dn conflicts")
    p.conversion_gain_e_per_dn = 2.0
    assert not recipe.check_inputs(inputs, p)


def test_simulator_eight_bit_witness_needs_no_recipe_overrides():
    camera = CameraSimulator()
    camera.settings.mode = "sequence"
    camera.settings.bit_depth = 8
    camera.settings.exposures_ms = "1, 2, 4, 8, 16, 32, 64"
    frames = camera.acquire().objects
    recipe = RELATIVE_DN_RECIPE
    p = recipe.parameter_class()
    ready = assess_recipe_inputs(recipe, frames, p)
    assert ready.can_run
    outcome = recipe.run(ready.bindings, p, RecipeExecutionContext())
    rows = {r[0]: r[1] for r in outcome.results[0].value.data}
    assert rows["Response slope"] == pytest.approx(30_000, rel=0.01)
    assert rows["Saturation onset exposure"] == 0.008
    assert outcome.objects[0].value.metadata[ADC_RESOLUTION_KEY]["saturation_dn"] == 255
    p.saturation_dn = 4095
    _reject(recipe, ready.bindings, p, "saturation_dn conflicts")
