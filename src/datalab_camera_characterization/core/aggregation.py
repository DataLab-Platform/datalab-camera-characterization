"""Bounded-memory mean and variance aggregation for image stacks."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Sequence
from typing import Union

import numpy as np

ImageStackSource = Union[np.ndarray, Sequence[np.ndarray]]


class _ImageStackStructureError(ValueError):
    """Describe one invalid stack structure for structured validation."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        self.code = code
        self.details = details
        super().__init__(message)


@dataclasses.dataclass(frozen=True)
class _ImageStackDescription:
    """Structure shared by ndarray stacks and frame sequences."""

    frame_count: int
    spatial_shape: tuple[int, int]
    dtype: np.dtype


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


def _describe_image_stack(frames: ImageStackSource) -> _ImageStackDescription:
    """Validate stack structure without scanning or copying frame values."""
    if isinstance(frames, np.ndarray):
        if frames.ndim != 3:
            raise _ImageStackStructureError(
                "invalid_stack_dimensions",
                "Frames must have shape (frames, height, width)",
                shape=list(frames.shape),
            )
        if 0 in frames.shape:
            raise _ImageStackStructureError(
                "empty_series",
                "Frames must not be empty",
                shape=list(frames.shape),
            )
        if not np.issubdtype(frames.dtype, np.number) or np.issubdtype(
            frames.dtype, np.complexfloating
        ):
            raise _ImageStackStructureError(
                "non_numeric_dtype",
                "Frames must use a real numeric dtype",
                dtype=str(frames.dtype),
            )
        return _ImageStackDescription(
            frames.shape[0],
            frames.shape[1:],
            frames.dtype,
        )

    if isinstance(frames, (str, bytes)) or not isinstance(frames, Sequence):
        raise _ImageStackStructureError(
            "invalid_stack_type",
            "Frames must be a NumPy array or a sequence of NumPy image arrays",
        )
    if len(frames) == 0:
        raise _ImageStackStructureError(
            "empty_series",
            "Frames must not be empty",
            shape=[0],
        )

    first = frames[0]
    if not isinstance(first, np.ndarray) or first.ndim != 2:
        raise _ImageStackStructureError(
            "invalid_stack_dimensions",
            "Each frame must be a two-dimensional NumPy array",
        )
    if 0 in first.shape:
        raise _ImageStackStructureError(
            "empty_series",
            "Frames must not be empty",
            shape=[len(frames), *first.shape],
        )
    if not np.issubdtype(first.dtype, np.number) or np.issubdtype(
        first.dtype, np.complexfloating
    ):
        raise _ImageStackStructureError(
            "non_numeric_dtype",
            "Frames must use a real numeric dtype",
            dtype=str(first.dtype),
        )
    for index in range(1, len(frames)):
        frame = frames[index]
        if not isinstance(frame, np.ndarray) or frame.ndim != 2:
            raise _ImageStackStructureError(
                "invalid_stack_dimensions",
                "Each frame must be a two-dimensional NumPy array",
                frame_index=index,
            )
        if frame.shape != first.shape:
            raise _ImageStackStructureError(
                "inconsistent_frame_shape",
                "Frames in one series must share an image shape",
                frame_index=index,
                expected=list(first.shape),
                actual=list(frame.shape),
            )
        if frame.dtype != first.dtype:
            raise _ImageStackStructureError(
                "inconsistent_frame_dtype",
                "Frames in one series must share a dtype",
                frame_index=index,
                expected=str(first.dtype),
                actual=str(frame.dtype),
            )
    return _ImageStackDescription(len(frames), first.shape, first.dtype)


def _validate_block_structure(block: np.ndarray) -> None:
    """Validate one non-empty ndarray block without scanning its values."""
    if not isinstance(block, np.ndarray):
        raise TypeError("Image stack block must be a NumPy array")
    try:
        _describe_image_stack(block)
    except _ImageStackStructureError as error:
        raise ValueError(str(error)) from error


def _iter_image_stack_blocks(
    frames: ImageStackSource,
    block_size: int,
) -> Iterator[np.ndarray]:
    """Yield ndarray blocks without copying more than ``block_size`` frames."""
    _validate_positive_integer(block_size, "Block size")
    description = _describe_image_stack(frames)
    for start in range(0, description.frame_count, block_size):
        stop = min(start + block_size, description.frame_count)
        if isinstance(frames, np.ndarray):
            yield frames[start:stop]
        else:
            yield np.stack([frames[index] for index in range(start, stop)], axis=0)


def _validate_block_values(block: np.ndarray) -> None:
    """Validate finite values in one already bounded block."""
    if not np.all(np.isfinite(block)):
        raise ValueError("Image stack block contains non-finite values")


def _readonly(array: np.ndarray) -> np.ndarray:
    """Mark an owned result array as read-only and return it."""
    array.setflags(write=False)
    return array


def _fraction_at_or_above(
    frames: ImageStackSource,
    threshold: float,
    block_size: int,
) -> float:
    """Return a threshold fraction without allocating a full-stack mask."""
    description = _describe_image_stack(frames)
    matching_count = sum(
        int(np.count_nonzero(block >= threshold))
        for block in _iter_image_stack_blocks(frames, block_size)
    )
    pixel_count = int(np.prod(description.spatial_shape))
    return matching_count / (description.frame_count * pixel_count)


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
    frames: ImageStackSource,
    *,
    block_size: int = 1,
    ddof: int = 1,
) -> ImageStackStatistics:
    """Compute per-pixel stack statistics using bounded frame blocks.

    Args:
        frames: 3D image stack or sequence of 2D frame arrays
        block_size: Maximum number of frames converted to float at once
        ddof: Delta degrees of freedom used for variance

    Returns:
        Read-only per-pixel mean and variance arrays
    """
    _validate_positive_integer(block_size, "Block size")
    _validate_ddof(ddof)
    description = _describe_image_stack(frames)
    accumulator = ImageStackAccumulator(description.spatial_shape)
    for block in _iter_image_stack_blocks(frames, block_size):
        accumulator.update_block(block)
    return accumulator.finalize(ddof)


def compute_image_stack_mean(
    frames: ImageStackSource,
    *,
    block_size: int = 1,
) -> np.ndarray:
    """Compute a read-only per-pixel mean without a variance accumulator.

    Args:
        frames: 3D image stack or sequence of 2D frame arrays
        block_size: Maximum number of frames scanned together

    Returns:
        Read-only float64 per-pixel mean
    """
    _validate_positive_integer(block_size, "Block size")
    description = _describe_image_stack(frames)
    mean = np.zeros(description.spatial_shape, dtype=np.float64)
    for block in _iter_image_stack_blocks(frames, block_size):
        _validate_block_values(block)
        for frame in block:
            np.add(mean, frame, out=mean)
    mean /= description.frame_count
    return _readonly(mean)


__all__ = [
    "ImageStackAccumulator",
    "ImageStackSource",
    "ImageStackStatistics",
    "compute_image_stack_mean",
    "compute_image_stack_statistics",
]
