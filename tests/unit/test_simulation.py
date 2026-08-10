"""Tests for deterministic synthetic Camera frames."""

from dataclasses import replace

import numpy as np
import pytest

from datalab_camera_characterization.core import (
    CameraSimulationParameters,
    simulate_camera_frames,
)


def test_simulation_is_reproducible_and_read_only() -> None:
    """One seed produces identical frames, maps, and defect masks."""
    parameters = CameraSimulationParameters(
        shape=(8, 10),
        frame_count=3,
        defective_pixel_fraction=0.1,
        seed=42,
    )

    first = simulate_camera_frames(parameters)
    second = simulate_camera_frames(parameters)

    assert first.frames_dn.shape == (3, 8, 10)
    assert first.frames_dn.dtype == np.uint16
    assert not first.frames_dn.flags.writeable
    np.testing.assert_array_equal(first.frames_dn, second.frames_dn)
    for field_name in (
        "prnu_gain_map",
        "illumination_gain_map",
        "dsnu_map_dn",
        "expected_electrons_map",
        "expected_dn_map",
        "dead_pixel_mask",
        "hot_pixel_mask",
    ):
        first_value = getattr(first.truth, field_name)
        second_value = getattr(second.truth, field_name)
        assert not first_value.flags.writeable
        np.testing.assert_array_equal(first_value, second_value)
    assert first.truth.seed == parameters.seed


def test_noiseless_model_converts_electrons_to_dn() -> None:
    """Photocharge and dark current use the documented electrons-per-DN gain."""
    parameters = CameraSimulationParameters(
        shape=(2, 3),
        frame_count=2,
        exposure_time_s=2.0,
        signal_electrons=20.0,
        offset_dn=10.0,
        conversion_gain_e_per_dn=2.0,
        read_noise_e=0.0,
        dark_current_e_per_s=4.0,
        prnu_fraction=0.0,
        dsnu_dn=0.0,
        saturation_dn=255.0,
        bit_depth=8,
        shot_noise=False,
    )

    result = simulate_camera_frames(parameters)

    np.testing.assert_array_equal(result.frames_dn, np.full((2, 2, 3), 24))
    np.testing.assert_array_equal(
        result.truth.expected_electrons_map,
        np.full((2, 3), 28.0),
    )
    np.testing.assert_array_equal(
        result.truth.expected_dn_map,
        np.full((2, 3), 24.0),
    )
    assert result.frames_dn.dtype == np.uint8


def test_structured_dark_and_flat_maps_have_exact_physical_roles() -> None:
    """Readout structure is additive while flat illumination is multiplicative."""
    parameters = CameraSimulationParameters(
        shape=(48, 64),
        frame_count=1,
        exposure_time_s=0.1,
        signal_electrons=1_000.0,
        offset_dn=100.0,
        conversion_gain_e_per_dn=2.0,
        read_noise_e=0.0,
        dark_current_e_per_s=0.0,
        prnu_fraction=0.0,
        dsnu_dn=0.0,
        row_pattern_dn=3.0,
        column_pattern_dn=2.0,
        amplifier_glow_dn=25.0,
        vignetting_fraction=0.25,
        dust_shadow_count=3,
        dust_shadow_depth_fraction=0.20,
        saturation_dn=4_095.0,
        bit_depth=12,
        shot_noise=False,
        seed=53,
    )

    flat = simulate_camera_frames(parameters)
    dark = simulate_camera_frames(replace(parameters, signal_electrons=0.0))
    illumination = flat.truth.illumination_gain_map
    expected_electrons = parameters.signal_electrons * illumination

    assert np.mean(illumination) == pytest.approx(1.0)
    assert np.mean(illumination[:4, :]) < np.mean(illumination[20:28, 24:40])
    assert np.std(np.mean(flat.truth.dsnu_map_dn, axis=1)) > 2.5
    assert np.std(np.mean(flat.truth.dsnu_map_dn, axis=0)) > 1.5
    assert flat.truth.dsnu_map_dn[-1, -1] > flat.truth.dsnu_map_dn[0, 0]
    np.testing.assert_allclose(
        flat.truth.expected_electrons_map,
        expected_electrons,
    )
    np.testing.assert_allclose(
        flat.truth.expected_dn_map,
        parameters.offset_dn
        + flat.truth.dsnu_map_dn
        + expected_electrons / parameters.conversion_gain_e_per_dn,
    )
    np.testing.assert_array_equal(
        dark.truth.illumination_gain_map,
        illumination,
    )
    np.testing.assert_array_equal(
        dark.truth.expected_electrons_map,
        np.zeros(parameters.shape),
    )
    np.testing.assert_allclose(
        dark.truth.expected_dn_map,
        parameters.offset_dn + dark.truth.dsnu_map_dn,
    )


def test_defective_pixels_are_disjoint_and_applied_to_every_frame() -> None:
    """Ground-truth dead and hot masks match the quantized output stack."""
    parameters = CameraSimulationParameters(
        shape=(4, 5),
        frame_count=3,
        signal_electrons=20.0,
        offset_dn=10.0,
        conversion_gain_e_per_dn=1.0,
        read_noise_e=0.0,
        dark_current_e_per_s=0.0,
        prnu_fraction=0.0,
        dsnu_dn=0.0,
        saturation_dn=255.0,
        bit_depth=8,
        defective_pixel_fraction=0.2,
        shot_noise=False,
        seed=7,
    )

    result = simulate_camera_frames(parameters)
    dead_mask = result.truth.dead_pixel_mask
    hot_mask = result.truth.hot_pixel_mask
    healthy_mask = ~(dead_mask | hot_mask)

    assert np.count_nonzero(dead_mask) == 2
    assert np.count_nonzero(hot_mask) == 2
    assert not np.any(dead_mask & hot_mask)
    assert np.all(result.frames_dn[:, dead_mask] == 0)
    assert np.all(result.frames_dn[:, hot_mask] == 255)
    assert np.all(result.frames_dn[:, healthy_mask] == 30)


def test_regular_pixels_are_clipped_to_adc_saturation() -> None:
    """Saturation is applied before conversion to the unsigned output dtype."""
    parameters = CameraSimulationParameters(
        shape=(2, 2),
        frame_count=1,
        signal_electrons=1_000.0,
        offset_dn=10.0,
        conversion_gain_e_per_dn=1.0,
        read_noise_e=0.0,
        dark_current_e_per_s=0.0,
        prnu_fraction=0.0,
        dsnu_dn=0.0,
        saturation_dn=200.0,
        bit_depth=8,
        shot_noise=False,
    )

    result = simulate_camera_frames(parameters)

    np.testing.assert_array_equal(result.frames_dn, np.full((1, 2, 2), 200))
    assert result.frames_dn.dtype == np.uint8


def test_static_truth_maps_do_not_depend_on_acquisition_length_or_signal() -> None:
    """A sensor seed identifies the same fixed-pattern maps across acquisitions."""
    common = {
        "shape": (6, 7),
        "prnu_fraction": 0.05,
        "dsnu_dn": 2.0,
        "defective_pixel_fraction": 0.1,
        "seed": 23,
    }
    short = simulate_camera_frames(
        CameraSimulationParameters(frame_count=1, signal_electrons=100.0, **common)
    )
    long = simulate_camera_frames(
        CameraSimulationParameters(frame_count=5, signal_electrons=500.0, **common)
    )

    for field_name in (
        "prnu_gain_map",
        "illumination_gain_map",
        "dsnu_map_dn",
        "dead_pixel_mask",
        "hot_pixel_mask",
    ):
        np.testing.assert_array_equal(
            getattr(short.truth, field_name),
            getattr(long.truth, field_name),
        )
    assert not np.array_equal(
        short.truth.expected_electrons_map,
        long.truth.expected_electrons_map,
    )


def test_prnu_map_is_positive_with_requested_relative_deviation() -> None:
    """The lognormal PRNU population has unit mean and the requested spread."""
    parameters = CameraSimulationParameters(
        shape=(512, 512),
        frame_count=1,
        signal_electrons=0.0,
        read_noise_e=0.0,
        prnu_fraction=0.1,
        dsnu_dn=0.0,
        shot_noise=False,
        seed=31,
    )

    prnu_gain_map = simulate_camera_frames(parameters).truth.prnu_gain_map

    assert np.all(prnu_gain_map > 0.0)
    assert np.mean(prnu_gain_map) == pytest.approx(1.0, abs=0.001)
    assert np.std(prnu_gain_map) == pytest.approx(0.1, abs=0.001)


def test_shot_noise_has_poisson_mean_and_variance() -> None:
    """Quantized frames retain Poisson statistics when gain is one e-/DN."""
    parameters = CameraSimulationParameters(
        shape=(1, 1),
        frame_count=100_000,
        signal_electrons=100.0,
        offset_dn=0.0,
        conversion_gain_e_per_dn=1.0,
        read_noise_e=0.0,
        dark_current_e_per_s=0.0,
        prnu_fraction=0.0,
        dsnu_dn=0.0,
        saturation_dn=1_000.0,
        bit_depth=16,
        shot_noise=True,
        seed=37,
    )

    values = simulate_camera_frames(parameters).frames_dn[:, 0, 0].astype(float)

    assert np.mean(values) == pytest.approx(100.0, abs=0.2)
    assert np.var(values, ddof=1) == pytest.approx(100.0, abs=2.0)


def test_read_noise_has_configured_electron_deviation() -> None:
    """Read-noise spread is converted from electrons using the configured gain."""
    parameters = CameraSimulationParameters(
        shape=(1, 1),
        frame_count=100_000,
        signal_electrons=1_000.0,
        offset_dn=100.0,
        conversion_gain_e_per_dn=2.0,
        read_noise_e=10.0,
        dark_current_e_per_s=0.0,
        prnu_fraction=0.0,
        dsnu_dn=0.0,
        saturation_dn=2_000.0,
        bit_depth=16,
        shot_noise=False,
        seed=41,
    )

    values = simulate_camera_frames(parameters).frames_dn[:, 0, 0].astype(float)

    assert np.mean(values) == pytest.approx(600.0, abs=0.1)
    assert np.std(values, ddof=1) == pytest.approx(5.0, abs=0.1)


@pytest.mark.parametrize(
    ("overrides", "error_type"),
    [
        ({"shape": (4, 0)}, ValueError),
        ({"frame_count": 0}, ValueError),
        ({"frame_count": True}, TypeError),
        ({"conversion_gain_e_per_dn": 0.0}, ValueError),
        ({"read_noise_e": -1.0}, ValueError),
        ({"row_pattern_dn": -1.0}, ValueError),
        ({"vignetting_fraction": 1.0}, ValueError),
        ({"dust_shadow_count": -1}, ValueError),
        ({"dust_shadow_count": 1.5}, TypeError),
        ({"dust_shadow_depth_fraction": 1.0}, ValueError),
        ({"prnu_fraction": 1.0}, ValueError),
        ({"defective_pixel_fraction": 1.1}, ValueError),
        ({"saturation_dn": 4_096.0}, ValueError),
        ({"signal_electrons": float("nan")}, ValueError),
        ({"shot_noise": 1}, TypeError),
        ({"seed": -1}, ValueError),
    ],
)
def test_invalid_parameters_are_rejected(
    overrides: dict[str, object],
    error_type: type[Exception],
) -> None:
    """Non-physical settings fail before any simulation arrays are allocated."""
    with pytest.raises(error_type):
        CameraSimulationParameters(**overrides)
