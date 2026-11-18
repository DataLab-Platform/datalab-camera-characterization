"""Analytical camera campaign: 100 photo + 10 dark LSB/s, gain 2 e-/LSB."""

from __future__ import annotations

import numpy as np
import pytest
from datalab.plugins.recipes import RecipeExecutionContext, RecipeValidationError
from sigima.objects import create_image

from datalab_camera_characterization.core import (
    CameraCharacterizationError,
    CameraExposureSeries,
    characterize_photon_transfer,
    characterize_relative_dn,
    metadata_key,
)
from datalab_camera_characterization.workflow import (
    PHOTON_TRANSFER_RECIPE,
    RELATIVE_DN_RECIPE,
)

TIMES = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
T = np.array(TIMES)
CHECKER = 2 * (np.indices((6, 8)).sum(axis=0) % 2) - 1


def _series(mean: np.ndarray | float, variance: float, count: int) -> np.ndarray:
    """Make exact per-pixel sample moments without changing frame means."""
    delta = CHECKER * np.sqrt(variance * (count - 1) / 2)
    return np.stack((mean - delta, mean + delta, *([mean + 0 * delta] * (count - 2))))


def _dark(t: float) -> np.ndarray:
    # A spatially structured dark rate must cancel in the flat-field maps.
    return _series(100 + (10 + CHECKER) * t, 2 + 5 * t, 3 if t >= 1 else 2)


def _campaign():
    flats = tuple(
        CameraExposureSeries(_series(100 + (110 + CHECKER) * t, 2 + 55 * t, 2), t)
        for t in TIMES
    )
    return {t: _dark(t) for t in reversed((0.0, *TIMES))}, flats


def test_complete_ladder_corrects_both_moments_without_replacing_raw_noise() -> None:
    darks, flats = _campaign()
    relative = characterize_relative_dn(darks, flats)
    ptc = characterize_photon_transfer(darks, flats)
    assert relative.linear_fit_slope_dn_per_s == pytest.approx(100)
    assert ptc.conversion_gain_e_per_dn == pytest.approx(2)
    for r in (relative, ptc):
        np.testing.assert_allclose(r.mean_signal_dn, 100 * T)
        ref = r.dark_reference
        assert ref.plan.mode == "matched"
        assert ref.plan.correction_exposures_s == TIMES
        assert ref.plan.correction_frame_counts == (2, 2, 3, 3, 3, 3)
        np.testing.assert_allclose(ref.mean_dn_by_level, 100 + 10 * T)
        np.testing.assert_allclose(ref.variance_dn2_by_level, 2 + 5 * T)
        assert ref.plan.noise_exposure_s == 0
        assert r.dark_temporal_noise_dn == pytest.approx(np.sqrt(2))
    np.testing.assert_allclose(relative.signal_variance_dn2, 50 * T)
    np.testing.assert_allclose(ptc.temporal_variance_dn2, 50 * T)
    np.testing.assert_allclose(relative.temporal_variance_dn2, 2 + 55 * T)
    np.testing.assert_allclose(ptc.flat_temporal_variance_dn2, 2 + 55 * T)
    np.testing.assert_allclose(ptc.measured_snr, 100 * T / np.sqrt(2 + 55 * T))
    np.testing.assert_allclose(ptc.model_snr, ptc.measured_snr)
    assert ptc.read_noise_e == pytest.approx(2 * np.sqrt(2))


@pytest.mark.parametrize("exposure", [0.0, 8.0, None])
def test_single_reference_keeps_observable_signal_not_necessarily_read_noise(exposure):
    _, flats = _campaign()
    t = 8.0 if exposure is None else exposure
    dark = _dark(t) if exposure is None else {t: _dark(t)}
    ptc = characterize_photon_transfer(dark, flats)
    relative = characterize_relative_dn(dark, flats)
    assert relative.linear_fit_slope_dn_per_s == pytest.approx(110)
    assert relative.mean_signal_dn[0] == pytest.approx(27.5 - 10 * t)
    assert ptc.conversion_gain_e_per_dn == pytest.approx(2)
    assert ptc.dark_temporal_noise_e == pytest.approx(2 * np.sqrt(2 + 5 * t))
    assert (ptc.read_noise_e is not None) == (exposure == 0.0)
    assert ptc.dark_reference.plan.noise_exposure_s == exposure


def test_ptc_uses_one_pixel_population_for_all_dark_and_light_moments():
    darks, flats = _campaign()
    darks[2.0][:, 0, 0] = 0.0
    for level in flats:
        level.frames_dn[:, 0, 0] = (0, 1000)
    ptc = characterize_photon_transfer(darks, flats)
    assert ptc.excluded_pixel_count == 1
    np.testing.assert_allclose(ptc.mean_signal_dn, 100 * T)
    np.testing.assert_allclose(ptc.temporal_variance_dn2, 50 * T)
    assert ptc.read_noise_e == pytest.approx(2 * np.sqrt(2))


@pytest.mark.parametrize(
    "method", [characterize_relative_dn, characterize_photon_transfer]
)
def test_close_exposures_are_not_merged_and_no_partial_matching(method):
    darks, flats = _campaign()
    darks[np.nextafter(1.0, 2.0)] = darks.pop(1)
    with pytest.raises(CameraCharacterizationError, match="incomplete_dark_coverage"):
        method(darks, flats)
    explicit = method(darks, flats, dark_reference_exposure_s=8)
    np.testing.assert_allclose(explicit.mean_signal_dn, 110 * T - 80)
    assert explicit.dark_reference.plan.mode == "explicit_single"
    assert explicit.dark_reference.plan.noise_exposure_s == 0
    with pytest.raises(CameraCharacterizationError, match="missing_selected_dark"):
        method(darks, flats, dark_reference_exposure_s=1)
    darks[1] = _dark(1)[:1]
    with pytest.raises(CameraCharacterizationError, match="insufficient_frames"):
        method(darks, flats)


def test_short_positive_bias_requires_identification_and_usable_noise():
    darks, flats = _campaign()
    bias = darks.pop(0)
    darks[0.001] = bias
    assert characterize_photon_transfer(darks, flats).read_noise_e is None
    kwargs = {"short_dark_exposure_s": 0.001}
    r = characterize_photon_transfer(darks, flats, **kwargs)
    assert r.read_noise_e == pytest.approx(2 * np.sqrt(2))
    assert r.dark_reference.plan.noise_source == "declared_short_bias"
    with pytest.raises(CameraCharacterizationError, match="invalid_short_dark"):
        characterize_photon_transfer(darks, flats, short_dark_exposure_s=8)
    bias[0] = 0.0
    r = characterize_photon_transfer(darks, flats, **kwargs)
    assert r.dark_reference.noise_status == "clipped_short_bias"
    assert r.read_noise_e is None
    bias[:] = 100
    r = characterize_photon_transfer(darks, flats, **kwargs)
    assert r.dark_reference.noise_status == "unresolved_short_bias"
    assert r.read_noise_e is None


def _recipe_images(darks, flats):
    def images(role, t, stack):
        for frame in stack:
            image = create_image(f"{role} {t}", frame.copy(), units=("", "", "LSB"))
            image.metadata[metadata_key("bit_depth")] = 12
            image.metadata[metadata_key("bit_shift")] = 0
            image.metadata[metadata_key("frame_role")] = role
            if t is not None:
                image.metadata[metadata_key("exposure_time_s")] = t
            yield image

    return {
        "dark_frames": tuple(
            i for t, stack in darks.items() for i in images("dark", t, stack)
        ),
        "flat_frames": tuple(
            i for s in flats for i in images("flat", s.exposure_time_s, s.frames_dn)
        ),
    }


@pytest.mark.parametrize("recipe", [RELATIVE_DN_RECIPE, PHOTON_TRANSFER_RECIPE])
def test_workflow_refuses_partial_mixture_before_outputs_and_reports_explicit_choice(
    recipe,
):
    darks, flats = _campaign()
    inputs = _recipe_images({1.0: darks[1], 8.0: darks[8]}, flats)
    params = recipe.parameter_class()
    diagnostics = recipe.check_inputs(inputs, params)
    assert [(d.code, d.level) for d in diagnostics] == [
        ("incomplete_dark_coverage", "warning")
    ]
    with pytest.raises(RecipeValidationError, match="complete the dark ladder"):
        recipe.run(inputs, params, RecipeExecutionContext())
    params.dark_reference_exposure_s = 8.0
    assert not recipe.check_inputs(inputs, params)
    outcome = recipe.run(inputs, params, RecipeExecutionContext())
    table = outcome.results[0].value
    provenance = table.attrs["dark_reference"]
    assert (
        outcome.objects[0].value.metadata[metadata_key("dark_reference")] == provenance
    )
    assert provenance["mode"] == "explicit_single"
    assert provenance["correction_exposures_s"] == (8.0,) * len(T)
    assert provenance["noise_exposure_s"] == 8
    assert ["Correction dark frames", 3, "frames", "8.0 s"] in table.data
    assert not any("read noise" in row[0].lower() for row in table.data)


def test_unknown_exposure_requires_a_declaration_without_retagging_sources():
    _, flats = _campaign()
    inputs = _recipe_images({None: _dark(8)}, flats)
    recipe = RELATIVE_DN_RECIPE
    p = recipe.parameter_class()
    with pytest.raises(RecipeValidationError, match="Unknown dark exposure"):
        recipe.run(inputs, p, RecipeExecutionContext())
    p.dark_reference_exposure_s = 8.0
    outcome = recipe.run(inputs, p, RecipeExecutionContext())
    ref = outcome.results[0].value.attrs["dark_reference"]
    assert ref["dark_exposure_source"] == "operator"
    assert ref["noise_exposure_s"] == 8
    assert all(
        metadata_key("exposure_time_s") not in i.metadata for i in inputs["dark_frames"]
    )


def test_recipe_spatial_dark_matches_last_unsaturated_flat_not_bias_or_last_dark():
    darks, flats = _campaign()
    flats[-1].frames_dn[:] = 4095
    inputs = _recipe_images(darks, flats)
    recipe = RELATIVE_DN_RECIPE
    outcome = recipe.run(inputs, recipe.parameter_class(), RecipeExecutionContext())
    objects = {o.id: o.value for o in outcome.objects}
    assert objects["mean_flat"].metadata[metadata_key("exposure_time_s")] == 4.0
    assert objects["mean_dark"].metadata[metadata_key("exposure_time_s")] == 4.0
    np.testing.assert_allclose(objects["mean_dark"].data, 140 + CHECKER * 4)
    np.testing.assert_allclose(objects["dsnu_like_map"].data, CHECKER * 4)
    np.testing.assert_allclose(objects["prnu_like_map"].data, 0, atol=1e-14)
    response = objects["response"]
    assert response.metadata[metadata_key("dark_reference")]["noise_exposure_s"] == 0
    np.testing.assert_allclose(
        response.metadata[metadata_key("signal_variance_dn2")][:-1], 50 * T[:-1]
    )


def test_recipe_ptc_noise_curve_uses_raw_flat_not_added_back_bias_variance():
    inputs = _recipe_images(*_campaign())
    recipe = PHOTON_TRANSFER_RECIPE
    outcome = recipe.run(inputs, recipe.parameter_class(), RecipeExecutionContext())
    objects = {o.id: o.value for o in outcome.objects}
    np.testing.assert_allclose(objects["ptc"].y, 50 * T)
    np.testing.assert_allclose(objects["noise_vs_signal"].y, 2 * np.sqrt(2 + 55 * T))
    rows = {r[0]: r[1] for r in outcome.results[0].value.data}
    assert rows["Estimated read noise"] == pytest.approx(2 * np.sqrt(2))
