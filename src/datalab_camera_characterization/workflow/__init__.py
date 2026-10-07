"""Headless Camera characterization workflows."""

from .dark_current import DarkCurrentRecipeParameters, run_dark_current_characterization
from .input_checks import (
    check_dark_current_inputs,
    check_photon_transfer_inputs,
    check_relative_dn_inputs,
    suggest_dark_flat_bindings,
    suggest_dark_ramp_bindings,
)
from .photon_transfer import (
    PhotonTransferRecipeParameters,
    run_photon_transfer_characterization,
)
from .recipes import (
    CAMERA_RECIPES,
    DARK_CURRENT_RECIPE,
    PHOTON_TRANSFER_RECIPE,
    RELATIVE_DN_RECIPE,
)
from .relative_dn import (
    CANDIDATE_THRESHOLD_METADATA_KEY,
    EXPOSURE_TIME_METADATA_KEY,
    FRAME_ROLE_METADATA_KEY,
    OUTPUT_ROLE_METADATA_KEY,
    CameraRecipeParameters,
    infer_frame_role,
    run_relative_dn_characterization,
)

__all__ = [
    "CAMERA_RECIPES",
    "CANDIDATE_THRESHOLD_METADATA_KEY",
    "DARK_CURRENT_RECIPE",
    "EXPOSURE_TIME_METADATA_KEY",
    "FRAME_ROLE_METADATA_KEY",
    "OUTPUT_ROLE_METADATA_KEY",
    "PHOTON_TRANSFER_RECIPE",
    "RELATIVE_DN_RECIPE",
    "CameraRecipeParameters",
    "DarkCurrentRecipeParameters",
    "PhotonTransferRecipeParameters",
    "check_dark_current_inputs",
    "check_photon_transfer_inputs",
    "check_relative_dn_inputs",
    "infer_frame_role",
    "run_dark_current_characterization",
    "run_photon_transfer_characterization",
    "run_relative_dn_characterization",
    "suggest_dark_flat_bindings",
    "suggest_dark_ramp_bindings",
]
