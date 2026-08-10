"""Scientific validation of characterization against synthetic ground truth."""

from __future__ import annotations

import math

import numpy as np
import pytest

from datalab_camera_characterization.core import (
    CameraExposureSeries,
    CameraSimulationParameters,
    CameraValidationParameters,
    characterize_relative_dn,
    characterize_spatial_dn,
    simulate_camera_frames,
    validate_camera_inputs,
)

SHAPE = (64, 64)
FRAME_COUNT = 24
CONVERSION_GAIN_E_PER_DN = 2.5
READ_NOISE_E = 5.0
PHOTOELECTRON_FLUX_PER_S = 600.0
EXPOSURE_TIMES_S = (0.25, 0.5, 1.0, 2.0, 4.0, 20.0)


def _simulation_parameters(
    exposure_time_s: float,
    signal_electrons: float,
) -> CameraSimulationParameters:
    """Return one acquisition from a shared deterministic synthetic sensor."""
    return CameraSimulationParameters(
        shape=SHAPE,
        frame_count=FRAME_COUNT,
        exposure_time_s=exposure_time_s,
        signal_electrons=signal_electrons,
        offset_dn=200.0,
        conversion_gain_e_per_dn=CONVERSION_GAIN_E_PER_DN,
        read_noise_e=READ_NOISE_E,
        dark_current_e_per_s=0.0,
        prnu_fraction=0.02,
        dsnu_dn=1.5,
        saturation_dn=4_095.0,
        bit_depth=12,
        defective_pixel_fraction=0.0,
        shot_noise=True,
        seed=101,
    )


def test_relative_characterization_recovers_synthetic_camera_truth() -> None:
    """Response, read noise, linearity, and saturation match known truth."""
    dark = simulate_camera_frames(_simulation_parameters(0.0, 0.0))
    flats = tuple(
        simulate_camera_frames(
            _simulation_parameters(
                exposure_time_s,
                PHOTOELECTRON_FLUX_PER_S * exposure_time_s,
            )
        )
        for exposure_time_s in EXPOSURE_TIMES_S
    )
    result = characterize_relative_dn(
        dark.frames_dn,
        tuple(
            CameraExposureSeries(simulation.frames_dn, exposure_time_s)
            for exposure_time_s, simulation in zip(EXPOSURE_TIMES_S, flats)
        ),
        CameraValidationParameters(
            saturation_dn=4_095.0,
            saturation_fraction_warning=0.01,
        ),
        aggregation_block_size=3,
    )

    mean_prnu_gain = float(np.mean(flats[0].truth.prnu_gain_map))
    expected_slope_dn_per_s = (
        PHOTOELECTRON_FLUX_PER_S * mean_prnu_gain / CONVERSION_GAIN_E_PER_DN
    )
    expected_dark_noise_dn = math.sqrt(
        (READ_NOISE_E / CONVERSION_GAIN_E_PER_DN) ** 2 + 1.0 / 12.0
    )
    expected_saturation_signal_dn = (
        flats[-1].parameters.saturation_dn - dark.parameters.offset_dn
    )
    fitted_exposures = np.asarray(EXPOSURE_TIMES_S)[result.linear_fit_mask]
    expected_fitted_signal_dn = expected_slope_dn_per_s * fitted_exposures

    assert result.linear_fit_slope_dn_per_s == pytest.approx(
        expected_slope_dn_per_s,
        rel=0.005,
    )
    assert result.dark_temporal_noise_dn == pytest.approx(
        expected_dark_noise_dn,
        rel=0.02,
    )
    np.testing.assert_allclose(
        result.mean_signal_dn[result.linear_fit_mask],
        expected_fitted_signal_dn,
        rtol=0.005,
        atol=0.2,
    )
    assert np.max(np.abs(result.linearity_residuals_dn[result.linear_fit_mask])) < 0.2
    np.testing.assert_array_equal(
        result.linear_fit_mask,
        (True, True, True, True, True, False),
    )
    assert result.saturation_onset_exposure_s == 20.0
    assert result.saturation_onset_signal_dn == pytest.approx(
        expected_saturation_signal_dn,
        abs=0.2,
    )


def test_spatial_characterization_recovers_static_synthetic_maps() -> None:
    """Relative DSNU/PRNU maps recover deterministic simulator ground truth."""
    dark_parameters = CameraSimulationParameters(
        shape=SHAPE,
        frame_count=4,
        exposure_time_s=0.0,
        signal_electrons=0.0,
        offset_dn=200.0,
        conversion_gain_e_per_dn=2.0,
        read_noise_e=0.0,
        dark_current_e_per_s=0.0,
        prnu_fraction=0.02,
        dsnu_dn=1.5,
        row_pattern_dn=3.0,
        column_pattern_dn=2.0,
        amplifier_glow_dn=20.0,
        vignetting_fraction=0.20,
        dust_shadow_count=2,
        dust_shadow_depth_fraction=0.15,
        saturation_dn=4_095.0,
        bit_depth=12,
        shot_noise=False,
        seed=202,
    )
    flat_parameters = CameraSimulationParameters(
        **{
            **dark_parameters.__dict__,
            "exposure_time_s": 1.0,
            "signal_electrons": 2_000.0,
        }
    )
    dark = simulate_camera_frames(dark_parameters)
    flat = simulate_camera_frames(flat_parameters)

    result = characterize_spatial_dn(
        np.mean(dark.frames_dn, axis=0),
        np.mean(flat.frames_dn, axis=0),
    )

    expected_dsnu_map = dark.truth.dsnu_map_dn - np.mean(dark.truth.dsnu_map_dn)
    expected_flat_gain = flat.truth.prnu_gain_map * flat.truth.illumination_gain_map
    expected_prnu_map = expected_flat_gain / np.mean(expected_flat_gain) - 1.0
    np.testing.assert_allclose(result.dsnu_like_map_dn, expected_dsnu_map, atol=1.0)
    np.testing.assert_allclose(
        result.prnu_like_map_fraction,
        expected_prnu_map,
        atol=0.002,
    )


@pytest.mark.parametrize(
    ("invalid_dark", "expected_code"),
    [
        (
            (
                np.zeros((2, 2), dtype=np.uint16),
                np.zeros((2, 2), dtype=np.uint8),
            ),
            "inconsistent_frame_dtype",
        ),
        ((np.zeros((2, 2), dtype=np.uint16), object()), "invalid_stack_dimensions"),
    ],
)
def test_invalid_sequence_campaigns_return_stable_diagnostics(
    invalid_dark: tuple[object, ...],
    expected_code: str,
) -> None:
    """Malformed bounded sources fail as diagnostics before calculation."""
    frames = tuple(np.zeros((2, 2), dtype=np.uint16) for _ in range(2))
    report = validate_camera_inputs(
        invalid_dark,
        (
            CameraExposureSeries(frames, 1.0),
            CameraExposureSeries(frames, 2.0),
        ),
    )

    assert report.has_errors
    assert expected_code in {item.code for item in report.errors}
