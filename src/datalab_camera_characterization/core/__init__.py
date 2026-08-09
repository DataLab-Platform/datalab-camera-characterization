"""Host-independent Camera characterization domain code."""

from .aggregation import (
    ImageStackAccumulator,
    ImageStackStatistics,
    compute_image_stack_statistics,
)
from .characterization import (
    CameraCharacterizationError,
    RelativeCameraCharacterization,
    characterize_relative_dn,
)
from .metadata import metadata_key
from .simulation import (
    CameraSimulationParameters,
    CameraSimulationResult,
    CameraSimulationTruth,
    simulate_camera_frames,
)
from .validation import (
    CameraDiagnosticLevel,
    CameraExposureSeries,
    CameraInputDiagnostic,
    CameraInputValidation,
    CameraValidationParameters,
    validate_camera_inputs,
)

__all__ = [
    "CameraCharacterizationError",
    "CameraDiagnosticLevel",
    "CameraExposureSeries",
    "CameraInputDiagnostic",
    "CameraInputValidation",
    "RelativeCameraCharacterization",
    "CameraSimulationParameters",
    "CameraSimulationResult",
    "CameraSimulationTruth",
    "CameraValidationParameters",
    "ImageStackAccumulator",
    "ImageStackStatistics",
    "characterize_relative_dn",
    "compute_image_stack_statistics",
    "metadata_key",
    "simulate_camera_frames",
    "validate_camera_inputs",
]
