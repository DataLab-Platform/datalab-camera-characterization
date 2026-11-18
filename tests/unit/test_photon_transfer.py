"""Photon transfer core method and recipe."""

from __future__ import annotations

import json

import numpy as np
import pytest
from datalab.plugins.recipes import RecipeExecutionContext, RecipeValidationError
from sigima.objects import create_image

from datalab_camera_characterization.core import (
    CameraCharacterizationError,
    CameraExposureSeries,
    CameraSimulationParameters,
    PhotonTransferParameters,
    characterize_photon_transfer,
    metadata_key,
    simulate_camera_frames,
)
from datalab_camera_characterization.workflow import (
    EXPOSURE_TIME_METADATA_KEY,
    FRAME_ROLE_METADATA_KEY,
    PHOTON_TRANSFER_RECIPE,
    PhotonTransferRecipeParameters,
)

GAIN_E_PER_DN = 2.5
READ_NOISE_E = 4.0


def _frames(exposure_time_s: float, rate: float, stream: int, count: int = 6):
    """Simulate one series of a shared uniform-illumination sensor."""
    return simulate_camera_frames(
        CameraSimulationParameters(
            shape=(48, 48),
            frame_count=count,
            exposure_time_s=exposure_time_s,
            signal_electrons=rate * exposure_time_s,
            conversion_gain_e_per_dn=GAIN_E_PER_DN,
            read_noise_e=READ_NOISE_E,
            dark_current_e_per_s=0.0,
            prnu_fraction=0.01,
            defective_pixel_fraction=0.002,
            seed=5,
            noise_stream=stream,
        )
    ).frames_dn


def _campaign(levels: tuple[float, ...] = (1, 2, 3, 4, 5, 6, 7, 8)):
    """Return dark frames and increasing flat series."""
    dark = _frames(0.0, 0.0, 1, count=4)
    flats = tuple(
        CameraExposureSeries(_frames(t, 1_000.0, stream), t)
        for stream, t in enumerate(levels, start=2)
    )
    return dark, flats


def test_photon_transfer_recovers_gain_and_read_noise() -> None:
    """The variance-versus-mean slope gives the conversion gain."""
    dark, flats = _campaign()

    result = characterize_photon_transfer({0.0: dark}, flats)

    assert result.conversion_gain_e_per_dn == pytest.approx(GAIN_E_PER_DN, rel=0.05)
    # Quantization adds 1/12 LSB^2 to the electronic read noise.
    expected_read_noise = GAIN_E_PER_DN * np.sqrt(
        (READ_NOISE_E / GAIN_E_PER_DN) ** 2 + 1.0 / 12.0
    )
    assert result.read_noise_e == pytest.approx(expected_read_noise, rel=0.1)
    assert result.excluded_pixel_count == 5
    assert not result.saturation_reached
    assert result.fit_r_squared > 0.99
    assert np.all(result.model_snr[1:] > result.model_snr[:-1])


def test_photon_transfer_rejects_too_few_linear_levels() -> None:
    """A fit needs the configured number of levels in the linear range."""
    dark, flats = _campaign((1.0, 2.0))

    with pytest.raises(CameraCharacterizationError, match="insufficient_ptc_levels"):
        characterize_photon_transfer(
            dark,
            flats,
            PhotonTransferParameters(minimum_fit_levels=3),
        )


@pytest.mark.parametrize(
    "kwargs",
    [{"fit_upper_fraction": 0.0}, {"minimum_fit_levels": 1}],
)
def test_photon_transfer_parameters_are_validated(kwargs: dict) -> None:
    """Fit settings are rejected before any calculation."""
    with pytest.raises(ValueError):
        PhotonTransferParameters(**kwargs)


def _image(frame: np.ndarray, role: str, exposure_time_s: float):
    """Wrap one frame with the plugin acquisition metadata."""
    image = create_image(f"{role} {exposure_time_s:g}", frame.copy())
    image.zunit = "LSB"
    image.metadata[metadata_key("bit_depth")] = 12
    image.metadata[metadata_key("bit_shift")] = 0
    image.metadata[FRAME_ROLE_METADATA_KEY] = role
    image.metadata[EXPOSURE_TIME_METADATA_KEY] = exposure_time_s
    return image


def test_photon_transfer_recipe_builds_anchored_outputs() -> None:
    """The recipe returns the curve, its fit, noise and SNR signals and a table."""
    dark, flats = _campaign()
    inputs = {
        "dark_frames": tuple(_image(frame, "dark", 0.0) for frame in dark),
        "flat_frames": tuple(
            _image(frame, "flat", series.exposure_time_s)
            for series in flats
            for frame in series.frames_dn
        ),
    }

    outcome = PHOTON_TRANSFER_RECIPE.run(
        inputs,
        PhotonTransferRecipeParameters(),
        RecipeExecutionContext(),
    )

    assert [output.id for output in outcome.objects] == [
        "ptc",
        "ptc_fit",
        "noise_vs_signal",
        "snr_vs_signal",
        "snr_model",
    ]
    (metrics,) = outcome.results
    assert metrics.anchor_id == "ptc"
    rows = {row[0]: row for row in metrics.value.data}
    assert rows["Conversion gain"][1] == pytest.approx(GAIN_E_PER_DN, rel=0.05)
    assert rows["Saturation capacity"][3] == "Lower bound"
    assert "saturation_not_reached" in {item.code for item in outcome.diagnostics}


def test_photon_transfer_recipe_requires_its_parameters() -> None:
    """A foreign parameter DataSet is rejected before reading inputs."""
    with pytest.raises(RecipeValidationError, match="PhotonTransferRecipeParameters"):
        PHOTON_TRANSFER_RECIPE.run({}, None, RecipeExecutionContext())


def test_centered_recipe_preserves_raw_noise_and_replayable_provenance():
    signs = 2 * (np.indices((16, 16)).sum(axis=0) % 2) - 1
    signals = np.array([16, 32, 64, 128, 256, 512, 1024])
    inputs = {
        "dark_frames": tuple(_image(100.0 + k * signs, "dark", 8.0) for k in (-1, 1)),
        "flat_frames": tuple(
            _image(
                100 + s + k * (np.sqrt((2 + s / 2) / 2) * signs + 0.02 * s),
                "flat",
                s / 1000,
            )
            for s in signals
            for k in (-1, 1)
        ),
    }
    p = PhotonTransferRecipeParameters.create(variance_mode="centered_pairs")
    outcome = PHOTON_TRANSFER_RECIPE.run(inputs, p, RecipeExecutionContext())
    objects = {o.id: o.value for o in outcome.objects}
    table = outcome.results[0].value
    replay = table.attrs["ptc_analysis"]
    assert replay == objects["ptc"].metadata[metadata_key("ptc_analysis")]
    json.dumps(replay, allow_nan=False)
    assert replay["variance_mode"] == "centered_pairs"
    assert replay["dark_pairs"][0]["exposure_s"] == 8.0
    np.testing.assert_allclose(objects["ptc"].y, signals / 2)
    np.testing.assert_allclose(
        replay["raw_temporal_variance_dn2"], signals / 2 + 2 * (0.02 * signals) ** 2
    )
    np.testing.assert_allclose(
        objects["noise_vs_signal"].y,
        2 * np.sqrt(2 + signals / 2 + 2 * (0.02 * signals) ** 2),
    )
    rows = {r[0]: r for r in table.data}
    assert rows["Conversion gain"][1] == pytest.approx(2)
    assert rows["Raw gain"][1] == pytest.approx(1.086, abs=0.001)
    assert rows["Saturation capacity"][1:] == [None, "e-", "Indeterminate"]
    assert rows["Dynamic range"][1:] == [None, "dB", "Indeterminate"]
    assert "Estimated read noise" not in rows
    assert "frame_mean_fluctuation" in {d.code for d in outcome.diagnostics}
