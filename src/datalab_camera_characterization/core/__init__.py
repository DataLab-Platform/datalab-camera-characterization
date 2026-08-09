"""Host-independent Camera characterization domain code."""

from .metadata import metadata_key
from .simulation import (
    CameraSimulationParameters,
    CameraSimulationResult,
    CameraSimulationTruth,
    simulate_camera_frames,
)

__all__ = [
    "CameraSimulationParameters",
    "CameraSimulationResult",
    "CameraSimulationTruth",
    "metadata_key",
    "simulate_camera_frames",
]
