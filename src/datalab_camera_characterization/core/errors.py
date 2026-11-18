"""Errors shared by the camera characterization methods."""

from __future__ import annotations

from .validation import CameraInputValidation


class CameraCharacterizationError(ValueError):
    """Raised when structured input errors block characterization."""

    def __init__(self, validation: CameraInputValidation) -> None:
        self.validation = validation
        details = "; ".join(f"{d.code}: {d.message}" for d in validation.errors)
        super().__init__(f"Camera input validation failed: {details}")
