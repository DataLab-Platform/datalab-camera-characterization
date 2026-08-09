"""Tests for structured Camera input validation."""

import numpy as np
import pytest

from datalab_camera_characterization.core import (
    CameraExposureSeries,
    CameraInputValidation,
    CameraValidationParameters,
    validate_camera_inputs,
)


def _diagnostic_codes(report: CameraInputValidation) -> set[str]:
    """Return diagnostic codes from a validation report."""
    return {diagnostic.code for diagnostic in report.diagnostics}


def test_missing_dataset_parts_return_errors_without_raising() -> None:
    """Absent dark and flat data are reported together before calculation."""
    report = validate_camera_inputs(None, ())

    assert report.has_errors
    assert _diagnostic_codes(report) == {
        "missing_dark_series",
        "missing_flat_series",
    }


def test_valid_inputs_preserve_warnings_as_structured_diagnostics() -> None:
    """Warnings do not invalidate an otherwise coherent dataset."""
    dark = np.zeros((2, 3, 4), dtype=np.uint16)
    flats = (
        CameraExposureSeries(np.zeros((2, 3, 4), dtype=np.uint16), 1.0),
        CameraExposureSeries(np.full((2, 3, 4), 50, dtype=np.uint16), 2.0),
        CameraExposureSeries(np.full((2, 3, 4), 100, dtype=np.uint16), 3.0),
    )
    parameters = CameraValidationParameters(
        saturation_dn=100.0,
        saturation_fraction_warning=0.5,
    )

    report = validate_camera_inputs(dark, flats, parameters)

    assert not report.has_errors
    assert _diagnostic_codes(report) == {
        "excessive_saturation",
        "zero_temporal_variance",
    }
    assert report.warnings


def test_cross_series_inconsistencies_are_reported_together() -> None:
    """Shape, dtype, acquisition count, and exposure order all remain visible."""
    dark = np.zeros((1, 2, 2), dtype=np.uint16)
    flats = (
        CameraExposureSeries(np.zeros((2, 2, 3), dtype=np.uint8), 2.0, "high"),
        CameraExposureSeries(np.zeros((2, 2, 2), dtype=np.uint16), 1.0, "low"),
    )

    report = validate_camera_inputs(dark, flats)

    assert report.has_errors
    assert {
        "dtype_mismatch",
        "exposure_order",
        "insufficient_frames",
        "shape_mismatch",
    } <= _diagnostic_codes(report)


@pytest.mark.parametrize(
    ("frames", "expected_code"),
    [
        (np.zeros((2, 3)), "invalid_stack_dimensions"),
        (np.empty((2, 0, 3)), "empty_series"),
        (np.full((2, 2, 2), np.nan), "non_finite_values"),
        (np.full((2, 2, 2), "dn"), "non_numeric_dtype"),
    ],
)
def test_malformed_dark_stacks_return_diagnostics(
    frames: np.ndarray,
    expected_code: str,
) -> None:
    """Malformed arrays do not escape as late NumPy calculation errors."""
    flats = (
        CameraExposureSeries(np.zeros((2, 2, 2)), 1.0),
        CameraExposureSeries(np.ones((2, 2, 2)), 2.0),
    )

    report = validate_camera_inputs(frames, flats)

    assert expected_code in _diagnostic_codes(report)


def test_invalid_exposure_does_not_hide_later_order_error() -> None:
    """One invalid metadata value does not break subsequent order checking."""
    frames = np.stack((np.zeros((2, 2)), np.ones((2, 2)))).astype(np.uint16)
    flats = (
        CameraExposureSeries(frames, 1.0),
        CameraExposureSeries(frames, float("nan")),
        CameraExposureSeries(frames, 0.5),
    )

    report = validate_camera_inputs(frames, flats)

    assert {"invalid_exposure", "exposure_order"} <= _diagnostic_codes(report)


def test_configured_variance_threshold_is_non_normative_warning() -> None:
    """A caller-provided variance threshold warns without invalidating data."""
    frames = np.array((np.zeros((2, 2)), np.full((2, 2), 10)), dtype=np.uint16)
    flats = (
        CameraExposureSeries(frames, 1.0),
        CameraExposureSeries(frames, 2.0),
    )
    parameters = CameraValidationParameters(maximum_temporal_variance_dn2=10.0)

    report = validate_camera_inputs(frames, flats, parameters)

    assert not report.has_errors
    assert "excessive_temporal_variance" in _diagnostic_codes(report)
    diagnostic = next(
        item
        for item in report.diagnostics
        if item.code == "excessive_temporal_variance"
    )
    with pytest.raises(TypeError):
        diagnostic.details["actual_dn2"] = 0.0


def test_validation_requires_two_flat_levels_for_linearity() -> None:
    """Configuration cannot weaken the mathematical requirement of a line fit."""
    with pytest.raises(ValueError, match="at least 2"):
        CameraValidationParameters(minimum_flat_levels=1)


def test_invalid_flat_does_not_hide_unsaturated_level_error() -> None:
    """Independent flat-stack and linearity errors are reported together."""
    dark = np.zeros((2, 2, 2), dtype=np.uint16)
    flats = (
        CameraExposureSeries(np.full((1, 2, 2), 100, dtype=np.uint16), 1.0),
        CameraExposureSeries(np.full((2, 2, 2), 100, dtype=np.uint16), 2.0),
    )
    parameters = CameraValidationParameters(
        saturation_dn=100.0,
        saturation_fraction_warning=0.5,
    )

    report = validate_camera_inputs(dark, flats, parameters)

    assert {"insufficient_frames", "insufficient_unsaturated_levels"} <= (
        _diagnostic_codes(report)
    )
