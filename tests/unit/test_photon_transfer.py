"""Photon transfer core method and recipe."""

from __future__ import annotations

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
    dark = _frames(1.0, 0.0, 1, count=4)
    flats = tuple(
        CameraExposureSeries(_frames(t, 1_000.0, stream), t)
        for stream, t in enumerate(levels, start=2)
    )
    return dark, flats


def test_photon_transfer_recovers_gain_and_read_noise() -> None:
    """The variance-versus-mean slope gives the conversion gain."""
    dark, flats = _campaign()

    result = characterize_photon_transfer(dark, flats)

    assert result.conversion_gain_e_per_dn == pytest.approx(GAIN_E_PER_DN, rel=0.05)
    # Quantization adds 1/12 DN^2 to the electronic read noise.
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
    image.metadata[FRAME_ROLE_METADATA_KEY] = role
    image.metadata[EXPOSURE_TIME_METADATA_KEY] = exposure_time_s
    return image


def test_photon_transfer_recipe_builds_anchored_outputs() -> None:
    """The recipe returns the curve, its fit, noise and SNR signals and a table."""
    dark, flats = _campaign()
    inputs = {
        "dark_frames": tuple(_image(frame, "dark", 1.0) for frame in dark),
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
