"""Structured validation for Camera dark and flat frame series."""

from __future__ import annotations

import dataclasses
import enum
import math
from collections.abc import Mapping, Sequence
from numbers import Real
from types import MappingProxyType

import numpy as np

from .aggregation import _fraction_at_or_above, compute_image_stack_statistics


class CameraDiagnosticLevel(str, enum.Enum):
    """Severity of a Camera input diagnostic."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclasses.dataclass(frozen=True)
class CameraInputDiagnostic:
    """Machine-identifiable anomaly found before characterization."""

    level: CameraDiagnosticLevel
    code: str
    message: str
    details: Mapping[str, object] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize the level and freeze diagnostic details."""
        object.__setattr__(self, "level", CameraDiagnosticLevel(self.level))
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("Camera diagnostic code must be non-empty")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("Camera diagnostic message must be non-empty")
        if not isinstance(self.details, Mapping) or not all(
            isinstance(key, str) for key in self.details
        ):
            raise TypeError("Camera diagnostic details must map string keys to values")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclasses.dataclass(frozen=True)
class CameraInputValidation:
    """Immutable collection of diagnostics for one Camera dataset."""

    diagnostics: Sequence[CameraInputDiagnostic] = ()

    def __post_init__(self) -> None:
        """Validate and freeze diagnostics."""
        diagnostics = tuple(self.diagnostics)
        if not all(
            isinstance(diagnostic, CameraInputDiagnostic) for diagnostic in diagnostics
        ):
            raise TypeError("Camera validation requires CameraInputDiagnostic values")
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def has_errors(self) -> bool:
        """Return whether characterization must stop before calculation."""
        return any(
            diagnostic.level is CameraDiagnosticLevel.ERROR
            for diagnostic in self.diagnostics
        )

    @property
    def errors(self) -> tuple[CameraInputDiagnostic, ...]:
        """Return error diagnostics only."""
        return tuple(
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.level is CameraDiagnosticLevel.ERROR
        )

    @property
    def warnings(self) -> tuple[CameraInputDiagnostic, ...]:
        """Return warning diagnostics only."""
        return tuple(
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.level is CameraDiagnosticLevel.WARNING
        )


@dataclasses.dataclass(frozen=True)
class CameraExposureSeries:
    """Frames acquired at one uniform-illumination exposure level.

    Values are deliberately validated by :func:`validate_camera_inputs` rather
    than in ``__post_init__`` so malformed user data produces diagnostics.
    """

    frames_dn: np.ndarray
    exposure_time_s: float
    label: str = ""


@dataclasses.dataclass(frozen=True)
class CameraValidationParameters:
    """Explicit, non-normative thresholds for Camera input validation."""

    minimum_frame_count: int = 2
    minimum_flat_levels: int = 2
    saturation_dn: float = 4_095.0
    saturation_fraction_warning: float = 0.01
    maximum_temporal_variance_dn2: float | None = None

    def __post_init__(self) -> None:
        """Validate thresholds independently from a Camera dataset."""
        for name, value in (
            ("Minimum frame count", self.minimum_frame_count),
            ("Minimum flat levels", self.minimum_flat_levels),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.minimum_flat_levels < 2:
            raise ValueError("Minimum flat levels must be at least 2")
        _validate_positive_real(self.saturation_dn, "Saturation")
        _validate_fraction(
            self.saturation_fraction_warning,
            "Saturation warning fraction",
        )
        if self.maximum_temporal_variance_dn2 is not None:
            _validate_positive_real(
                self.maximum_temporal_variance_dn2,
                "Maximum temporal variance",
            )


@dataclasses.dataclass(frozen=True)
class _StackInfo:
    """Validated properties needed for cross-series checks."""

    name: str
    frames: np.ndarray
    spatial_shape: tuple[int, int]
    dtype: np.dtype
    saturation_fraction: float


def _validate_positive_real(value: float, name: str) -> float:
    """Return a finite positive real value."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return normalized


def _validate_fraction(value: float, name: str) -> float:
    """Return a finite fraction in the interval (0, 1]."""
    normalized = _validate_positive_real(value, name)
    if normalized > 1.0:
        raise ValueError(f"{name} must not exceed 1.0")
    return normalized


def _validate_aggregation_block_size(value: int) -> None:
    """Validate the maximum number of frames processed together."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Aggregation block size must be an integer")
    if value <= 0:
        raise ValueError("Aggregation block size must be positive")


def _diagnostic(
    level: CameraDiagnosticLevel,
    code: str,
    message: str,
    **details: object,
) -> CameraInputDiagnostic:
    """Build one immutable Camera input diagnostic."""
    return CameraInputDiagnostic(level, code, message, details)


def _validate_stack(
    value: object,
    name: str,
    parameters: CameraValidationParameters,
    aggregation_block_size: int,
    diagnostics: list[CameraInputDiagnostic],
) -> _StackInfo | None:
    """Validate one frame stack and return properties safe for calculations."""
    if not isinstance(value, np.ndarray):
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.ERROR,
                "invalid_stack_type",
                f"{name} frames must be a NumPy array",
                series=name,
            )
        )
        return None
    if value.ndim != 3:
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.ERROR,
                "invalid_stack_dimensions",
                f"{name} frames must have shape (frames, height, width)",
                series=name,
                shape=list(value.shape),
            )
        )
        return None
    if value.shape[0] == 0 or value.shape[1] == 0 or value.shape[2] == 0:
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.ERROR,
                "empty_series",
                f"{name} frames must not be empty",
                series=name,
                shape=list(value.shape),
            )
        )
        return None
    if not np.issubdtype(value.dtype, np.number) or np.issubdtype(
        value.dtype, np.complexfloating
    ):
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.ERROR,
                "non_numeric_dtype",
                f"{name} frames must use a real numeric dtype",
                series=name,
                dtype=str(value.dtype),
            )
        )
        return None
    if any(
        not np.all(np.isfinite(value[start : start + aggregation_block_size]))
        for start in range(0, value.shape[0], aggregation_block_size)
    ):
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.ERROR,
                "non_finite_values",
                f"{name} frames contain non-finite values",
                series=name,
            )
        )
        return None
    if value.shape[0] < parameters.minimum_frame_count:
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.ERROR,
                "insufficient_frames",
                f"{name} does not contain enough acquisitions",
                series=name,
                actual=value.shape[0],
                required=parameters.minimum_frame_count,
            )
        )
        return None

    statistics = compute_image_stack_statistics(
        value,
        block_size=aggregation_block_size,
        ddof=1,
    )
    mean_temporal_variance = statistics.mean_variance
    if mean_temporal_variance == 0.0:
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.WARNING,
                "zero_temporal_variance",
                f"{name} frames have zero temporal variance",
                series=name,
            )
        )
    maximum_variance = parameters.maximum_temporal_variance_dn2
    if maximum_variance is not None and mean_temporal_variance > maximum_variance:
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.WARNING,
                "excessive_temporal_variance",
                f"{name} temporal variance exceeds the configured threshold",
                series=name,
                actual_dn2=mean_temporal_variance,
                maximum_dn2=maximum_variance,
            )
        )

    saturation_fraction = _fraction_at_or_above(
        value,
        parameters.saturation_dn,
        aggregation_block_size,
    )
    if saturation_fraction >= parameters.saturation_fraction_warning:
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.WARNING,
                "excessive_saturation",
                f"{name} contains an excessive fraction of saturated pixels",
                series=name,
                fraction=saturation_fraction,
                threshold=parameters.saturation_fraction_warning,
            )
        )
    return _StackInfo(
        name,
        value,
        value.shape[1:],
        value.dtype,
        saturation_fraction,
    )


def validate_camera_inputs(
    dark_frames_dn: np.ndarray | None,
    flat_series: Sequence[CameraExposureSeries] | None,
    parameters: CameraValidationParameters | None = None,
    *,
    aggregation_block_size: int = 1,
) -> CameraInputValidation:
    """Validate Camera inputs without mutating data or raising dataset errors.

    Args:
        dark_frames_dn: Dark frame stack shaped ``(frames, height, width)``
        flat_series: Uniform-illumination stacks in increasing exposure order
        parameters: Explicit validation thresholds
        aggregation_block_size: Maximum frames converted to float together

    Returns:
        Structured diagnostics; errors block characterization
    """
    parameters = parameters or CameraValidationParameters()
    _validate_aggregation_block_size(aggregation_block_size)
    diagnostics: list[CameraInputDiagnostic] = []
    stack_infos: list[_StackInfo] = []
    flat_stack_infos: list[_StackInfo] = []

    if dark_frames_dn is None:
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.ERROR,
                "missing_dark_series",
                "A dark frame series is required",
            )
        )
    else:
        dark_info = _validate_stack(
            dark_frames_dn,
            "dark",
            parameters,
            aggregation_block_size,
            diagnostics,
        )
        if dark_info is not None:
            stack_infos.append(dark_info)

    if flat_series is None or len(flat_series) == 0:
        diagnostics.append(
            _diagnostic(
                CameraDiagnosticLevel.ERROR,
                "missing_flat_series",
                "At least one uniform-illumination series is required",
            )
        )
        series_values: tuple[object, ...] = ()
    else:
        series_values = tuple(flat_series)
        if len(series_values) < parameters.minimum_flat_levels:
            diagnostics.append(
                _diagnostic(
                    CameraDiagnosticLevel.ERROR,
                    "insufficient_flat_levels",
                    "Not enough uniform-illumination exposure levels",
                    actual=len(series_values),
                    required=parameters.minimum_flat_levels,
                )
            )

    previous_exposure: float | None = None
    for index, series in enumerate(series_values):
        if not isinstance(series, CameraExposureSeries):
            diagnostics.append(
                _diagnostic(
                    CameraDiagnosticLevel.ERROR,
                    "invalid_flat_series",
                    "Flat inputs must be CameraExposureSeries values",
                    index=index,
                )
            )
            continue
        name = series.label or f"flat[{index}]"
        exposure = series.exposure_time_s
        if isinstance(exposure, bool) or not isinstance(exposure, Real):
            diagnostics.append(
                _diagnostic(
                    CameraDiagnosticLevel.ERROR,
                    "invalid_exposure",
                    f"{name} exposure time must be a real number",
                    series=name,
                )
            )
        else:
            normalized_exposure = float(exposure)
            if not math.isfinite(normalized_exposure) or normalized_exposure < 0.0:
                diagnostics.append(
                    _diagnostic(
                        CameraDiagnosticLevel.ERROR,
                        "invalid_exposure",
                        f"{name} exposure time must be finite and non-negative",
                        series=name,
                    )
                )
            else:
                if (
                    previous_exposure is not None
                    and normalized_exposure <= previous_exposure
                ):
                    diagnostics.append(
                        _diagnostic(
                            CameraDiagnosticLevel.ERROR,
                            "exposure_order",
                            "Flat exposure times must be strictly increasing",
                            series=name,
                            previous_s=previous_exposure,
                            actual_s=normalized_exposure,
                        )
                    )
                previous_exposure = normalized_exposure

        stack_info = _validate_stack(
            series.frames_dn,
            name,
            parameters,
            aggregation_block_size,
            diagnostics,
        )
        if stack_info is not None:
            stack_infos.append(stack_info)
            flat_stack_infos.append(stack_info)

    if len(series_values) >= parameters.minimum_flat_levels:
        unsaturated_count = sum(
            stack_info.saturation_fraction < parameters.saturation_fraction_warning
            for stack_info in flat_stack_infos
        )
        if unsaturated_count < 2:
            diagnostics.append(
                _diagnostic(
                    CameraDiagnosticLevel.ERROR,
                    "insufficient_unsaturated_levels",
                    "At least two unsaturated exposure levels are required",
                    actual=unsaturated_count,
                    required=2,
                )
            )

    if stack_infos:
        reference = stack_infos[0]
        for stack_info in stack_infos[1:]:
            if stack_info.spatial_shape != reference.spatial_shape:
                diagnostics.append(
                    _diagnostic(
                        CameraDiagnosticLevel.ERROR,
                        "shape_mismatch",
                        f"{stack_info.name} image size differs from {reference.name}",
                        series=stack_info.name,
                        expected=list(reference.spatial_shape),
                        actual=list(stack_info.spatial_shape),
                    )
                )
            if stack_info.dtype != reference.dtype:
                diagnostics.append(
                    _diagnostic(
                        CameraDiagnosticLevel.ERROR,
                        "dtype_mismatch",
                        f"{stack_info.name} dtype differs from {reference.name}",
                        series=stack_info.name,
                        expected=str(reference.dtype),
                        actual=str(stack_info.dtype),
                    )
                )

    return CameraInputValidation(diagnostics)


__all__ = [
    "CameraDiagnosticLevel",
    "CameraExposureSeries",
    "CameraInputDiagnostic",
    "CameraInputValidation",
    "CameraValidationParameters",
    "validate_camera_inputs",
]
