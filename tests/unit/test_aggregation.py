"""Tests for bounded-memory image-stack statistics."""

import numpy as np
import pytest

import datalab_camera_characterization.core.aggregation as aggregation
from datalab_camera_characterization.core import (
    ImageStackAccumulator,
    compute_image_stack_mean,
    compute_image_stack_statistics,
)


@pytest.mark.parametrize("block_size", [1, 2, 4, 20])
def test_block_statistics_match_numpy_for_incomplete_final_block(
    block_size: int,
) -> None:
    """Every block size reproduces NumPy mean and sample variance."""
    frames = np.random.default_rng(7).integers(
        0,
        4_096,
        size=(11, 8, 7),
        dtype=np.uint16,
    )

    result = compute_image_stack_statistics(frames, block_size=block_size)

    np.testing.assert_allclose(result.mean, np.mean(frames, axis=0), atol=1e-12)
    np.testing.assert_allclose(
        result.variance,
        np.var(frames, axis=0, ddof=1),
        rtol=1e-13,
        atol=1e-9,
    )
    assert result.count == frames.shape[0]
    assert result.ddof == 1
    assert not result.mean.flags.writeable
    assert not result.variance.flags.writeable


def test_accumulator_merges_irregular_blocks_and_frames() -> None:
    """Manual block and frame updates share one numerically stable state."""
    frames = np.random.default_rng(11).normal(1e6, 3.0, size=(9, 3, 4))
    accumulator = ImageStackAccumulator((3, 4))

    accumulator.update_block(frames[:3])
    accumulator.update_frame(frames[3])
    accumulator.update_block(frames[4:])
    result = accumulator.finalize(ddof=0)

    np.testing.assert_allclose(result.mean, np.mean(frames, axis=0), atol=1e-9)
    np.testing.assert_allclose(
        result.variance,
        np.var(frames, axis=0, ddof=0),
        rtol=1e-10,
        atol=1e-10,
    )


def test_frame_sequence_matches_equivalent_ndarray_stack() -> None:
    """A sequence of existing 2D arrays preserves batch statistics."""
    frames = np.random.default_rng(13).integers(
        0,
        1_024,
        size=(7, 4, 5),
        dtype=np.uint16,
    )

    stack_result = compute_image_stack_statistics(frames, block_size=3)
    sequence_result = compute_image_stack_statistics(tuple(frames), block_size=3)

    np.testing.assert_allclose(sequence_result.mean, stack_result.mean)
    np.testing.assert_allclose(sequence_result.variance, stack_result.variance)
    assert sequence_result.count == stack_result.count


@pytest.mark.parametrize("block_size", [1, 3, 8, 32])
def test_mean_only_aggregation_matches_numpy(block_size: int) -> None:
    """Retained mean images do not require a per-pixel variance map."""
    frames = np.random.default_rng(17).integers(
        0,
        4_096,
        size=(11, 8, 7),
        dtype=np.uint16,
    )

    result = compute_image_stack_mean(tuple(frames), block_size=block_size)

    np.testing.assert_allclose(result, np.mean(frames, axis=0), atol=1e-12)
    assert result.dtype == np.float64
    assert not result.flags.writeable


@pytest.mark.parametrize("block_size", [1, 3, 8, 32])
def test_float_statistics_remain_stable_at_high_offset(block_size: int) -> None:
    """Chan merges stay close to NumPy for small variance on a large offset."""
    frames = np.random.default_rng(19).normal(1e9, 0.25, size=(17, 5, 4))

    result = compute_image_stack_statistics(frames, block_size=block_size)

    np.testing.assert_allclose(
        result.mean,
        np.mean(frames, axis=0),
        rtol=0.0,
        atol=3e-7,
    )
    np.testing.assert_allclose(
        result.variance,
        np.var(frames, axis=0, ddof=1),
        rtol=1e-6,
        atol=1e-10,
    )


@pytest.mark.parametrize("block_size", [0, -1])
def test_block_size_must_be_positive(block_size: int) -> None:
    """An invalid memory-bound parameter fails before aggregation."""
    with pytest.raises(ValueError, match="Block size must be positive"):
        compute_image_stack_statistics(np.zeros((2, 1, 1)), block_size=block_size)


def test_frame_count_must_exceed_delta_degrees_of_freedom() -> None:
    """Undefined sample variance is rejected explicitly."""
    with pytest.raises(ValueError, match="Frame count must exceed"):
        compute_image_stack_statistics(np.zeros((1, 1, 1)), ddof=1)


def test_stack_scans_and_float_conversion_are_block_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No value-dependent operation receives more than one configured block."""

    class ConversionRecordingArray(np.ndarray):
        conversion_frame_counts: list[int] = []

        def astype(self, *args: object, **kwargs: object) -> np.ndarray:
            self.conversion_frame_counts.append(self.shape[0])
            return super().astype(*args, **kwargs)

    frames = np.arange(11 * 3 * 4, dtype=np.uint16).reshape(11, 3, 4)
    recorded_frames = frames.view(ConversionRecordingArray)
    finite_frame_counts: list[int] = []
    original_isfinite = np.isfinite

    def recording_isfinite(values: np.ndarray) -> np.ndarray:
        finite_frame_counts.append(values.shape[0])
        return original_isfinite(values)

    monkeypatch.setattr(aggregation.np, "isfinite", recording_isfinite)
    compute_image_stack_statistics(recorded_frames, block_size=3)

    assert finite_frame_counts == [3, 3, 3, 2]
    assert ConversionRecordingArray.conversion_frame_counts == [3, 3, 3, 2]
