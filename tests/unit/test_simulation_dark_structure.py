"""Opt-in dark-current structure and independent noise streams."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from datalab_camera_characterization.core import (
    CameraSimulationParameters,
    simulate_camera_frames,
)

# Quickstart-like settings; the digest was checked against the 0.1.0 simulator.
LEGACY_SETTINGS = {
    "shape": (96, 128),
    "frame_count": 4,
    "exposure_time_s": 0.04,
    "signal_electrons": 2_400.0,
    "dark_current_e_per_s": 0.2,
    "row_pattern_dn": 3.0,
    "column_pattern_dn": 2.0,
    "amplifier_glow_dn": 30.0,
    "vignetting_fraction": 0.25,
    "dust_shadow_count": 3,
    "dust_shadow_depth_fraction": 0.18,
    "defective_pixel_fraction": 0.001,
    "seed": 20260809,
}
LEGACY_FRAMES_SHA256 = (
    "D9856C11B807AA04365D7B3B2343E6CBB698F41A28CCCDC34412F47AC7902FD0"
)


def test_default_dark_structure_keeps_legacy_frames_bitwise() -> None:
    """New opt-in parameters at their defaults reproduce existing campaigns."""
    result = simulate_camera_frames(CameraSimulationParameters(**LEGACY_SETTINGS))

    digest = hashlib.sha256(result.frames_dn.tobytes()).hexdigest().upper()

    assert digest == LEGACY_FRAMES_SHA256
    assert np.all(result.truth.dark_current_map_e_per_s == 0.2)
    assert not np.any(result.truth.dark_hot_pixel_mask)


def test_noise_stream_changes_noise_but_not_static_sensor() -> None:
    """Series sharing a seed share their sensor maps, not their noise."""
    first = simulate_camera_frames(CameraSimulationParameters(**LEGACY_SETTINGS))
    second = simulate_camera_frames(
        CameraSimulationParameters(**LEGACY_SETTINGS, noise_stream=3)
    )
    repeated = simulate_camera_frames(
        CameraSimulationParameters(**LEGACY_SETTINGS, noise_stream=3)
    )

    assert not np.array_equal(first.frames_dn, second.frames_dn)
    assert np.array_equal(second.frames_dn, repeated.frames_dn)
    for name in ("prnu_gain_map", "dsnu_map_dn", "illumination_gain_map"):
        assert np.array_equal(getattr(first.truth, name), getattr(second.truth, name))


def test_dark_current_structure_matches_requested_statistics() -> None:
    """Rate map, hot pixels and exposure-scaled glow follow their parameters."""
    parameters = CameraSimulationParameters(
        shape=(128, 128),
        frame_count=2,
        exposure_time_s=2.0,
        signal_electrons=0.0,
        dark_current_e_per_s=40.0,
        dark_current_nonuniformity_fraction=0.1,
        dark_hot_pixel_fraction=0.01,
        dark_hot_pixel_factor=20.0,
        amplifier_glow_e_per_s=100.0,
        seed=7,
    )
    truth = simulate_camera_frames(parameters).truth
    rate = truth.dark_current_map_e_per_s
    hot = truth.dark_hot_pixel_mask
    corner = rate[-4:, -4:]
    reference = rate[:32, :32][~hot[:32, :32]]

    assert np.count_nonzero(hot) == round(0.01 * rate.size)
    assert np.mean(reference) == pytest.approx(40.0, rel=0.02)
    assert np.std(reference) / np.mean(reference) == pytest.approx(0.1, rel=0.15)
    assert np.median(corner) > 120.0
    assert np.allclose(
        truth.expected_electrons_map,
        rate * parameters.exposure_time_s,
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("dark_current_nonuniformity_fraction", 1.0),
        ("dark_hot_pixel_fraction", -0.1),
        ("dark_hot_pixel_factor", 0.0),
        ("amplifier_glow_e_per_s", -1.0),
        ("noise_stream", -1),
    ],
)
def test_dark_structure_parameters_are_validated(name: str, value: object) -> None:
    """Invalid opt-in settings are rejected before allocating frames."""
    with pytest.raises(ValueError):
        CameraSimulationParameters(**{name: value})
