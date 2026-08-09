"""Bounded-memory mean and variance aggregation for image stacks."""

from __future__ import annotations

import dataclasses

import numpy as np


def _validate_positive_integer(value: int, name: str) -> None:
    """Validate a positive built-in integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _validate_ddof(value: int) -> None:
    """Validate a non-negative built-in delta degrees of freedom."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Delta degrees of freedom must be an integer")
    if value < 0:
        raise ValueError("Delta degrees of freedom must be non-negative")


def _validate_spatial_shape(shape: tuple[int, int]) -> None:
    """Validate a two-dimensional positive image shape."""
    if (
        not isinstance(shape, tuple)
        or len(shape) != 2
        or any(
            isinstance(size, bool) or not isinstance(size, int) or size <= 0
            for size in shape
        )
    ):
        raise ValueError("Spatial shape must contain two positive integers")


def _validate_block_structure(block: np.ndarray) -> None:
    """Validate one non-empty stack without scanning its values."""
    if not isinstance(block, np.ndarray):
        raise TypeError("Image stack block must be a NumPy array")
    if block.ndim != 3:
        raise ValueError("Image stack block must have shape (frames, height, width)")
    if 0 in block.shape:
        raise ValueError("Image stack block must not be empty")
    if not np.issubdtype(block.dtype, np.number) or np.issubdtype(
        block.dtype, np.complexfloating
    ):
        raise TypeError("Image stack block must use a real numeric dtype")


def _validate_block_values(block: np.ndarray) -> None:
    """Validate finite values in one already bounded block."""
    if not np.all(np.isfinite(block)):
        raise ValueError("Image stack block contains non-finite values")


def _readonly(array: np.ndarray) -> np.ndarray:
    """Mark an owned result array as read-only and return it."""
    array.setflags(write=False)
    return array


def _fraction_at_or_above(
    frames: np.ndarray,
    threshold: float,
    block_size: int,
) -> float:
    """Return a threshold fraction without allocating a full-stack mask."""
    _validate_positive_integer(block_size, "Block size")
    _validate_block_structure(frames)
    matching_count = sum(
        int(np.count_nonzero(frames[start : start + block_size] >= threshold))
        for start in range(0, frames.shape[0], block_size)
    )
    return matching_count / frames.size


@dataclasses.dataclass(frozen=True)
class ImageStackStatistics:
    """Read-only per-pixel statistics for an image stack."""

    count: int
    ddof: int
    mean: np.ndarray
    variance: np.ndarray

    @property
    def mean_value(self) -> float:
        """Return the spatial mean of the per-pixel means."""
        return float(np.mean(self.mean))

    @property
    def mean_variance(self) -> float:
        """Return the spatial mean of the per-pixel temporal variances."""
        return float(np.mean(self.variance))


class ImageStackAccumulator:
    """Merge image frames or blocks with the parallel variance algorithm."""

    def __init__(self, spatial_shape: tuple[int, int] | None = None) -> None:
        if spatial_shape is not None:
            _validate_spatial_shape(spatial_shape)
        self._spatial_shape = spatial_shape
        self._count = 0
        self._mean: np.ndarray | None = None
        self._m2: np.ndarray | None = None

    @property
    def count(self) -> int:
        """Return the number of accumulated frames."""
        return self._count

    @property
    def spatial_shape(self) -> tuple[int, int] | None:
        """Return the expected image shape, if known."""
        return self._spatial_shape

    def update_frame(self, frame: np.ndarray) -> None:
        """Accumulate one two-dimensional image frame."""
        if not isinstance(frame, np.ndarray):
            raise TypeError("Image frame must be a NumPy array")
        if frame.ndim != 2:
            raise ValueError("Image frame must be two-dimensional")
        self.update_block(frame[np.newaxis, :, :])

    def update_block(self, block: np.ndarray) -> None:
        """Accumulate one non-empty frame block with bounded temporary memory."""
        _validate_block_structure(block)
        _validate_block_values(block)
        spatial_shape = block.shape[1:]
        if self._spatial_shape is None:
            self._spatial_shape = spatial_shape
        elif spatial_shape != self._spatial_shape:
            raise ValueError(
                f"Image block shape {spatial_shape!r} does not match "
                f"{self._spatial_shape!r}"
            )

        block_float = block.astype(np.float64, copy=False)
        block_count = block.shape[0]
        block_mean = np.mean(block_float, axis=0, dtype=np.float64)
        centered = block_float - block_mean
        np.square(centered, out=centered)
        block_m2 = np.sum(centered, axis=0, dtype=np.float64)

        if self._count == 0:
            self._mean = block_mean
            self._m2 = block_m2
            self._count = block_count
            return

        assert self._mean is not None
        assert self._m2 is not None
        total_count = self._count + block_count
        delta = block_mean - self._mean
        self._mean += delta * (block_count / total_count)
        np.square(delta, out=delta)
        delta *= self._count * block_count / total_count
        self._m2 += block_m2
        self._m2 += delta
        self._count = total_count

    def finalize(self, ddof: int = 1) -> ImageStackStatistics:
        """Return immutable statistics for the accumulated frames."""
        _validate_ddof(ddof)
        if self._count == 0 or self._mean is None or self._m2 is None:
            raise ValueError("Cannot finalize an empty image stack")
        if self._count <= ddof:
            raise ValueError("Frame count must exceed delta degrees of freedom")
        mean = self._mean.copy()
        variance = self._m2 / (self._count - ddof)
        np.maximum(variance, 0.0, out=variance)
        return ImageStackStatistics(
            count=self._count,
            ddof=ddof,
            mean=_readonly(mean),
            variance=_readonly(variance),
        )


def compute_image_stack_statistics(
    frames: np.ndarray,
    *,
    block_size: int = 1,
    ddof: int = 1,
) -> ImageStackStatistics:
    """Compute per-pixel stack statistics using bounded frame blocks.

    Args:
        frames: Image stack shaped ``(frames, height, width)``
        block_size: Maximum number of frames converted to float at once
        ddof: Delta degrees of freedom used for variance

    Returns:
        Read-only per-pixel mean and variance arrays
    """
    _validate_positive_integer(block_size, "Block size")
    _validate_ddof(ddof)
    _validate_block_structure(frames)
    accumulator = ImageStackAccumulator(frames.shape[1:])
    for start in range(0, frames.shape[0], block_size):
        accumulator.update_block(frames[start : start + block_size])
    return accumulator.finalize(ddof)


__all__ = [
    "ImageStackAccumulator",
    "ImageStackStatistics",
    "compute_image_stack_statistics",
]
