"""Tests for the headless relative-DN Camera recipe."""

from __future__ import annotations

import numpy as np
import pytest
from datalab.recipes import RecipeExecutionContext, RecipeValidationError
from sigima.objects import ImageObj, SignalObj, TableResult, create_image

import datalab_camera_characterization.core.aggregation as aggregation
from datalab_camera_characterization.core import CameraCharacterizationError
from datalab_camera_characterization.workflow import (
    EXPOSURE_TIME_METADATA_KEY,
    OUTPUT_ROLE_METADATA_KEY,
    RELATIVE_DN_RECIPE,
    CameraRecipeParameters,
)


def _frame(title: str, value: int, exposure_time_s: float | None = None) -> ImageObj:
    """Create one 2D Camera frame with optional exposure metadata."""
    image = create_image(title, np.full((2, 3), value, dtype=np.uint16))
    if exposure_time_s is not None:
        image.metadata[EXPOSURE_TIME_METADATA_KEY] = exposure_time_s
    return image


@pytest.mark.parametrize("block_size", [1, 3])
def test_relative_dn_recipe_builds_anchored_cross_panel_outcome(
    block_size: int,
) -> None:
    """The recipe returns a response anchor, useful images, and one table."""
    dark = (_frame("dark low", 9), _frame("dark high", 11))
    flats = tuple(
        frame
        for mean_dn, exposure_time_s in ((30, 1.0), (50, 2.0), (70, 3.0))
        for frame in (
            _frame("flat low", mean_dn - 1, exposure_time_s),
            _frame("flat high", mean_dn + 1, exposure_time_s),
        )
    )
    for image in (*dark, *flats):
        image.set_uniform_coords(0.5, 0.75, 2.0, 3.0)
        image.xlabel, image.ylabel, image.zlabel = "X", "Y", "Signal"
        image.xunit, image.yunit, image.zunit = "mm", "mm", "DN"
        image.metadata["frame_id"] = image.title
    parameters = CameraRecipeParameters()
    parameters.saturation_dn = 100.0
    parameters.aggregation_block_size = block_size
    progress: list[tuple[float, str | None]] = []
    context = RecipeExecutionContext(
        progress_callback=lambda value, message: progress.append((value, message))
    )

    outcome = RELATIVE_DN_RECIPE.run(
        {"dark_frames": dark, "flat_frames": flats},
        parameters,
        context,
    )

    assert [output.id for output in outcome.objects] == [
        "response",
        "mean_dark",
        "mean_flat",
    ]
    response = outcome.objects[0].value
    assert isinstance(response, SignalObj)
    np.testing.assert_array_equal(response.x, (1.0, 2.0, 3.0))
    np.testing.assert_array_equal(response.y, (20.0, 40.0, 60.0))
    assert response.metadata[OUTPUT_ROLE_METADATA_KEY] == "response"

    mean_dark = outcome.objects[1].value
    mean_flat = outcome.objects[2].value
    assert isinstance(mean_dark, ImageObj)
    assert isinstance(mean_flat, ImageObj)
    np.testing.assert_array_equal(mean_dark.data, 10.0)
    np.testing.assert_array_equal(mean_flat.data, 70.0)
    assert mean_dark.metadata[OUTPUT_ROLE_METADATA_KEY] == "mean_dark"
    assert mean_flat.metadata[OUTPUT_ROLE_METADATA_KEY] == "mean_flat"
    assert mean_flat.metadata[EXPOSURE_TIME_METADATA_KEY] == 3.0
    assert "frame_id" not in mean_dark.metadata
    assert "frame_id" not in mean_flat.metadata
    assert (mean_dark.dx, mean_dark.dy, mean_dark.x0, mean_dark.y0) == (
        0.5,
        0.75,
        2.0,
        3.0,
    )
    assert (mean_flat.xlabel, mean_flat.ylabel, mean_flat.zlabel) == (
        "X",
        "Y",
        "Signal",
    )
    assert (mean_flat.xunit, mean_flat.yunit, mean_flat.zunit) == (
        "mm",
        "mm",
        "DN",
    )

    assert len(outcome.results) == 1
    table_output = outcome.results[0]
    assert table_output.id == "metrics"
    assert table_output.anchor_id == "response"
    assert isinstance(table_output.value, TableResult)
    assert table_output.value.headers == ["Metric", "Value", "Unit", "Status"]
    metrics = {row[0]: row[1] for row in table_output.value.data}
    assert metrics["Response slope"] == pytest.approx(20.0)
    assert metrics["Dark temporal noise"] == pytest.approx(np.sqrt(2.0))
    assert table_output.value.attrs["normative"] is False
    assert outcome.diagnostics == ()
    assert progress[-1] == (1.0, "Camera characterization complete")


def test_recipe_never_stacks_more_than_the_configured_frame_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ImageObj inputs are copied into bounded blocks, not complete 3D stacks."""
    dark = tuple(_frame(f"dark {index}", 10 + index % 2) for index in range(5))
    flats = tuple(
        _frame(f"flat {exposure} {index}", value + index % 2, exposure)
        for exposure, value in ((1.0, 30), (2.0, 50))
        for index in range(5)
    )
    parameters = CameraRecipeParameters()
    parameters.saturation_dn = 100.0
    parameters.aggregation_block_size = 3
    stack_frame_counts: list[int] = []
    original_stack = np.stack

    def recording_stack(arrays, *args, **kwargs):
        stack_frame_counts.append(len(arrays))
        return original_stack(arrays, *args, **kwargs)

    monkeypatch.setattr(aggregation.np, "stack", recording_stack)

    RELATIVE_DN_RECIPE.run(
        {"dark_frames": dark, "flat_frames": flats},
        parameters,
        RecipeExecutionContext(),
    )

    assert stack_frame_counts
    assert max(stack_frame_counts) == 3
    assert 5 not in stack_frame_counts


def test_recipe_selects_last_unsaturated_flat_and_propagates_warnings() -> None:
    """The useful flat remains unsaturated and validation warnings survive."""
    dark = (_frame("dark 1", 10), _frame("dark 2", 10))
    flats = (
        _frame("flat 1a", 30, 1.0),
        _frame("flat 1b", 30, 1.0),
        _frame("flat 2a", 50, 2.0),
        _frame("flat 2b", 50, 2.0),
        _frame("flat 3a", 100, 3.0),
        _frame("flat 3b", 100, 3.0),
    )
    parameters = CameraRecipeParameters()
    parameters.saturation_dn = 100.0
    parameters.saturation_fraction_warning = 0.5

    outcome = RELATIVE_DN_RECIPE.run(
        {"dark_frames": dark, "flat_frames": flats},
        parameters,
        RecipeExecutionContext(),
    )

    mean_flat = outcome.objects[2].value
    np.testing.assert_array_equal(mean_flat.data, 50.0)
    assert mean_flat.metadata[EXPOSURE_TIME_METADATA_KEY] == 2.0
    assert {diagnostic.code for diagnostic in outcome.diagnostics} >= {
        "excessive_saturation",
        "zero_temporal_variance",
    }
    metrics = {row[0]: row[1] for row in outcome.results[0].value.data}
    assert metrics["Saturation onset exposure"] == 3.0


def test_recipe_requires_namespaced_flat_exposure_metadata() -> None:
    """A flat frame without acquisition metadata fails before calculation."""
    dark = (_frame("dark 1", 9), _frame("dark 2", 11))
    flats = (
        _frame("flat missing", 30),
        _frame("flat 1", 31, 1.0),
        _frame("flat 2a", 49, 2.0),
        _frame("flat 2b", 51, 2.0),
    )

    with pytest.raises(RecipeValidationError, match=EXPOSURE_TIME_METADATA_KEY):
        RELATIVE_DN_RECIPE.run(
            {"dark_frames": dark, "flat_frames": flats},
            CameraRecipeParameters(),
            RecipeExecutionContext(),
        )


@pytest.mark.parametrize("exposure_time_s", [True, "1.0", float("nan"), -1.0])
def test_recipe_rejects_invalid_flat_exposure_metadata(
    exposure_time_s: object,
) -> None:
    """Invalid acquisition metadata cannot produce a partial recipe outcome."""
    dark = (_frame("dark 1", 9), _frame("dark 2", 11))
    flats = (
        _frame("flat invalid", 30),
        _frame("flat 1", 31, 1.0),
        _frame("flat 2a", 49, 2.0),
        _frame("flat 2b", 51, 2.0),
    )
    flats[0].metadata[EXPOSURE_TIME_METADATA_KEY] = exposure_time_s

    with pytest.raises(RecipeValidationError, match=EXPOSURE_TIME_METADATA_KEY):
        RELATIVE_DN_RECIPE.run(
            {"dark_frames": dark, "flat_frames": flats},
            CameraRecipeParameters(),
            RecipeExecutionContext(),
        )


def test_recipe_stops_before_outputs_when_all_flats_are_saturated() -> None:
    """Core diagnostics block output construction before the anchor selection."""
    dark = (_frame("dark 1", 9), _frame("dark 2", 11))
    flats = tuple(
        _frame(f"flat {exposure} {index}", 100, exposure)
        for exposure in (1.0, 2.0)
        for index in range(2)
    )
    parameters = CameraRecipeParameters()
    parameters.saturation_dn = 100.0
    parameters.saturation_fraction_warning = 0.5

    with pytest.raises(CameraCharacterizationError) as error:
        RELATIVE_DN_RECIPE.run(
            {"dark_frames": dark, "flat_frames": flats},
            parameters,
            RecipeExecutionContext(),
        )

    assert {item.code for item in error.value.validation.errors} == {
        "insufficient_unsaturated_levels"
    }


def test_recipe_parameters_disable_zero_variance_warning_threshold() -> None:
    """The DataSet sentinel maps to the core's optional variance threshold."""
    parameters = CameraRecipeParameters()
    parameters.maximum_temporal_variance_dn2 = 0.0

    assert parameters.to_validation_parameters().maximum_temporal_variance_dn2 is None
