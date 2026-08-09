"""Tests for relative Camera characterization in DN."""

import math

import numpy as np
import pytest

from datalab_camera_characterization.core import (
    CameraCharacterizationError,
    CameraExposureSeries,
    CameraValidationParameters,
    characterize_relative_dn,
)


def _two_frame_stack(mean_dn: int, shape: tuple[int, int] = (2, 3)) -> np.ndarray:
    """Return integer frames with exact mean and sample variance of two DN2."""
    return np.stack(
        (
            np.full(shape, mean_dn - 1, dtype=np.uint16),
            np.full(shape, mean_dn + 1, dtype=np.uint16),
        )
    )


def test_linear_relative_characterization_has_exact_dn_metrics() -> None:
    """A linear dataset yields exact response, noise, SNR, and residuals."""
    dark = _two_frame_stack(10)
    flats = tuple(
        CameraExposureSeries(_two_frame_stack(mean_dn), exposure_time_s)
        for mean_dn, exposure_time_s in ((30, 1.0), (50, 2.0), (70, 3.0))
    )
    parameters = CameraValidationParameters(saturation_dn=100.0)

    result = characterize_relative_dn(dark, flats, parameters)

    np.testing.assert_array_equal(result.exposure_times_s, (1.0, 2.0, 3.0))
    np.testing.assert_array_equal(result.mean_signal_dn, (20.0, 40.0, 60.0))
    np.testing.assert_allclose(result.temporal_variance_dn2, 2.0)
    np.testing.assert_allclose(result.temporal_noise_dn, math.sqrt(2.0))
    np.testing.assert_allclose(
        result.relative_snr,
        np.array((20.0, 40.0, 60.0)) / math.sqrt(2.0),
    )
    np.testing.assert_allclose(result.linearity_residuals_dn, 0.0, atol=1e-12)
    assert result.linear_fit_slope_dn_per_s == pytest.approx(20.0)
    assert result.linear_fit_intercept_dn == pytest.approx(0.0, abs=1e-12)
    assert result.dark_mean_dn == 10.0
    assert result.dark_temporal_noise_dn == pytest.approx(math.sqrt(2.0))
    assert result.maximum_unsaturated_signal_dn == 60.0
    assert result.relative_dynamic_range == pytest.approx(60.0 / math.sqrt(2.0))
    assert result.saturation_onset_exposure_s is None
    assert result.saturation_onset_signal_dn is None
    assert not result.validation.has_errors
    for value in (
        result.exposure_times_s,
        result.mean_signal_dn,
        result.temporal_variance_dn2,
        result.temporal_noise_dn,
        result.relative_snr,
        result.saturation_fractions,
        result.linear_fit_mask,
        result.linearity_residuals_dn,
    ):
        assert not value.flags.writeable


def test_saturated_level_is_excluded_from_fit_and_marks_onset() -> None:
    """Linearity uses only levels below the explicit saturation threshold."""
    dark = _two_frame_stack(10)
    flats = (
        CameraExposureSeries(_two_frame_stack(30), 1.0),
        CameraExposureSeries(_two_frame_stack(50), 2.0),
        CameraExposureSeries(np.full((2, 2, 3), 100, dtype=np.uint16), 3.0),
    )
    parameters = CameraValidationParameters(
        saturation_dn=100.0,
        saturation_fraction_warning=0.5,
    )

    result = characterize_relative_dn(dark, flats, parameters)

    np.testing.assert_array_equal(result.linear_fit_mask, (True, True, False))
    assert result.linear_fit_slope_dn_per_s == pytest.approx(20.0)
    assert result.linear_fit_intercept_dn == pytest.approx(0.0, abs=1e-12)
    assert result.linearity_residuals_dn[2] == pytest.approx(30.0)
    assert result.maximum_unsaturated_signal_dn == 40.0
    assert result.saturation_onset_exposure_s == 3.0
    assert result.saturation_onset_signal_dn == 90.0
    assert {diagnostic.code for diagnostic in result.validation.warnings} >= {
        "excessive_saturation",
        "zero_temporal_variance",
    }


def test_characterization_stops_with_structured_validation_errors() -> None:
    """No linear fit runs when fewer than two unsaturated levels remain."""
    frames = np.full((2, 2, 3), 100, dtype=np.uint16)
    flats = (
        CameraExposureSeries(frames, 1.0),
        CameraExposureSeries(frames, 2.0),
    )
    parameters = CameraValidationParameters(
        saturation_dn=100.0,
        saturation_fraction_warning=0.5,
    )

    with pytest.raises(CameraCharacterizationError) as error:
        characterize_relative_dn(_two_frame_stack(10), flats, parameters)

    assert error.value.validation.has_errors
    assert {diagnostic.code for diagnostic in error.value.validation.errors} == {
        "insufficient_unsaturated_levels"
    }


def test_zero_noise_produces_explicit_infinite_relative_ratios() -> None:
    """Zero measured noise is represented honestly instead of being hidden."""
    dark = np.full((2, 2, 3), 10, dtype=np.uint16)
    flats = (
        CameraExposureSeries(np.full((2, 2, 3), 30, dtype=np.uint16), 1.0),
        CameraExposureSeries(np.full((2, 2, 3), 50, dtype=np.uint16), 2.0),
    )

    result = characterize_relative_dn(
        dark,
        flats,
        CameraValidationParameters(saturation_dn=100.0),
    )

    assert np.all(np.isinf(result.relative_snr))
    assert math.isinf(result.relative_dynamic_range)
