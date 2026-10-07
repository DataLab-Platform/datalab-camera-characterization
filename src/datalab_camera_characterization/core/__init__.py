"""Host-independent Camera characterization domain code."""

from .aggregation import (
    ImageStackAccumulator,
    ImageStackSource,
    ImageStackStatistics,
    compute_image_stack_mean,
    compute_image_stack_statistics,
)
from .characterization import (
    CameraCharacterizationError,
    RelativeCameraCharacterization,
    characterize_relative_dn,
)
from .dark_current import (
    DarkCurrentCharacterization,
    DarkCurrentParameters,
    characterize_dark_current,
    validate_dark_ramp_inputs,
)
from .metadata import metadata_key
from .photon_transfer import (
    PhotonTransferCharacterization,
    PhotonTransferParameters,
    characterize_photon_transfer,
)
from .simulation import (
    CameraSimulationParameters,
    CameraSimulationResult,
    CameraSimulationTruth,
    simulate_camera_frames,
)
from .spatial import RelativeSpatialCharacterization, characterize_spatial_dn
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
    "DarkCurrentCharacterization",
    "DarkCurrentParameters",
    "PhotonTransferCharacterization",
    "PhotonTransferParameters",
    "RelativeCameraCharacterization",
    "RelativeSpatialCharacterization",
    "CameraSimulationParameters",
    "CameraSimulationResult",
    "CameraSimulationTruth",
    "CameraValidationParameters",
    "ImageStackAccumulator",
    "ImageStackSource",
    "ImageStackStatistics",
    "characterize_dark_current",
    "characterize_photon_transfer",
    "characterize_relative_dn",
    "characterize_spatial_dn",
    "compute_image_stack_mean",
    "compute_image_stack_statistics",
    "metadata_key",
    "simulate_camera_frames",
    "validate_camera_inputs",
    "validate_dark_ramp_inputs",
]
