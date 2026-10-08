"""Headless photon transfer Camera recipe."""

from __future__ import annotations

import math

import guidata.dataset as gds
import numpy as np
from datalab.plugins.recipes import (
    RecipeDiagnostic,
    RecipeExecutionContext,
    RecipeInputs,
    RecipeObjectOutput,
    RecipeOutcome,
    RecipeResultOutput,
    RecipeValidationError,
)
from sigima.objects import NO_ROI, TableResult

from ..core import (
    CameraValidationParameters,
    PhotonTransferCharacterization,
    PhotonTransferParameters,
    characterize_photon_transfer,
)
from .relative_dn import _frame_arrays, _group_images_by_exposure, _signal_output


class PhotonTransferRecipeParameters(gds.DataSet):
    """Parameters for the photon transfer (mean-variance) method."""

    minimum_frame_count = gds.IntItem(
        "Minimum frames per series",
        default=2,
        min=2,
    )
    minimum_flat_levels = gds.IntItem(
        "Minimum flat exposure levels",
        default=5,
        min=2,
    )
    saturation_dn = gds.FloatItem(
        "Saturation level (DN)",
        default=4_095.0,
        min=1e-12,
    )
    saturation_fraction_warning = gds.FloatItem(
        "Saturation warning fraction",
        default=0.01,
        min=1e-12,
        max=1.0,
    )
    fit_upper_fraction = gds.FloatItem(
        "Linear fit upper bound (fraction of saturation signal)",
        default=0.7,
        min=1e-3,
        max=1.0,
    )
    minimum_fit_levels = gds.IntItem(
        "Minimum levels in the linear fit",
        default=3,
        min=2,
    )
    exclude_stuck_pixels = gds.BoolItem(
        "Exclude pixels stuck at ADC limits in the dark",
        default=True,
    )
    aggregation_block_size = gds.IntItem(
        "Aggregation block size",
        default=1,
        min=1,
    )

    def to_core_parameters(self) -> PhotonTransferParameters:
        """Return host-independent photon transfer parameters."""
        return PhotonTransferParameters(
            validation=CameraValidationParameters(
                minimum_frame_count=int(self.minimum_frame_count),
                minimum_flat_levels=int(self.minimum_flat_levels),
                saturation_dn=float(self.saturation_dn),
                saturation_fraction_warning=float(self.saturation_fraction_warning),
            ),
            fit_upper_fraction=float(self.fit_upper_fraction),
            minimum_fit_levels=int(self.minimum_fit_levels),
            exclude_stuck_pixels=bool(self.exclude_stuck_pixels),
        )


def _metrics_table(result: PhotonTransferCharacterization) -> TableResult:
    """Build the photon transfer summary table for the curve anchor."""
    saturation_status = "Reached" if result.saturation_reached else "Lower bound"
    rows: list[list[object]] = [
        [
            "Conversion gain",
            result.conversion_gain_e_per_dn,
            "e-/DN",
            "Not assessed",
        ],
        ["Read noise", result.read_noise_e, "e-", "Not assessed"],
        ["Dark temporal noise", result.dark_temporal_noise_dn, "DN", "Not assessed"],
        [
            "Saturation capacity",
            result.saturation_capacity_e,
            "e-",
            saturation_status,
        ],
        ["Saturation signal", result.saturation_signal_dn, "DN", saturation_status],
        ["Dynamic range", result.dynamic_range_db, "dB", "Not assessed"],
        ["Fit intercept", result.fit_intercept_dn2, "DN^2", "Not assessed"],
        ["Fit R^2", result.fit_r_squared, "", "Not assessed"],
        ["Levels in linear fit", int(np.count_nonzero(result.fit_mask)), "", ""],
        ["Excluded stuck pixels", result.excluded_pixel_count, "pixel", ""],
    ]
    return TableResult(
        title="Photon transfer metrics",
        kind="camera_photon_transfer",
        headers=["Metric", "Value", "Unit", "Status"],
        data=[
            [
                name,
                None
                if isinstance(value, float) and not math.isfinite(value)
                else value,
                unit,
                status,
            ]
            for name, value, unit, status in rows
        ],
        roi_indices=[NO_ROI] * len(rows),
        attrs={
            "measurement_domain": "photon_transfer",
            "normative": False,
            "saturation_reached": result.saturation_reached,
        },
    )


def run_photon_transfer_characterization(
    inputs: RecipeInputs,
    parameters: gds.DataSet | None,
    context: RecipeExecutionContext,
) -> RecipeOutcome:
    """Run the photon transfer method and build host-neutral outputs."""
    if not isinstance(parameters, PhotonTransferRecipeParameters):
        raise RecipeValidationError(
            "Photon transfer characterization requires PhotonTransferRecipeParameters"
        )
    context.raise_if_cancelled()
    context.report_progress(0.0, "Preparing photon transfer series")
    dark_frames = _frame_arrays(inputs["dark_frames"], "dark_frames")
    flat_series, _flat_groups = _group_images_by_exposure(inputs["flat_frames"])
    try:
        core_parameters = parameters.to_core_parameters()
    except ValueError as error:
        raise RecipeValidationError(str(error)) from error
    context.report_progress(0.2, "Computing photon transfer statistics")
    context.raise_if_cancelled()
    result = characterize_photon_transfer(
        dark_frames,
        flat_series,
        core_parameters,
        aggregation_block_size=int(parameters.aggregation_block_size),
    )
    context.report_progress(0.85, "Building photon transfer outputs")
    context.raise_if_cancelled()

    ptc = _signal_output(
        "Photon transfer curve",
        result.mean_signal_dn.copy(),
        result.temporal_variance_dn2.copy(),
        "ptc",
        units=("DN", "DN^2"),
        labels=("Mean signal", "Temporal variance"),
    )
    curve_levels = slice(0, result.saturation_index + 1)
    fit_x = result.mean_signal_dn[curve_levels].copy()
    ptc_fit = _signal_output(
        "Photon transfer linear fit",
        fit_x,
        result.fit_slope_dn * fit_x + result.fit_intercept_dn2,
        "ptc_fit",
        units=("DN", "DN^2"),
        labels=("Mean signal", "Fitted variance"),
    )
    positive = result.mean_signal_dn > 0.0
    signal_e = result.signal_electrons[positive].copy()
    noise_e = result.conversion_gain_e_per_dn * np.sqrt(
        np.maximum(
            result.temporal_variance_dn2[positive] + result.dark_temporal_noise_dn**2,
            0.0,
        )
    )
    noise_vs_signal = _signal_output(
        "Temporal noise vs signal",
        signal_e,
        noise_e,
        "noise_vs_signal",
        units=("e-", "e-"),
        labels=("Mean signal", "Temporal noise"),
    )
    snr_vs_signal = _signal_output(
        "Measured SNR vs signal",
        signal_e.copy(),
        result.measured_snr[positive].copy(),
        "snr_vs_signal",
        units=("e-", ""),
        labels=("Mean signal", "SNR"),
    )
    snr_model = _signal_output(
        "Model SNR vs signal",
        signal_e.copy(),
        result.model_snr[positive].copy(),
        "snr_model",
        units=("e-", ""),
        labels=("Mean signal", "SNR"),
    )

    diagnostics = [
        RecipeDiagnostic(
            level=diagnostic.level.value,
            code=diagnostic.code,
            message=diagnostic.message,
            details=dict(diagnostic.details),
        )
        for diagnostic in result.validation.warnings
    ]
    if not result.saturation_reached:
        diagnostics.append(
            RecipeDiagnostic(
                level="warning",
                code="saturation_not_reached",
                message=(
                    "The temporal variance still increases at the last level: "
                    "the saturation capacity is only a lower bound"
                ),
            )
        )
    context.report_progress(1.0, "Photon transfer characterization complete")
    return RecipeOutcome(
        objects=(
            RecipeObjectOutput("ptc", ptc),
            RecipeObjectOutput("ptc_fit", ptc_fit),
            RecipeObjectOutput("noise_vs_signal", noise_vs_signal),
            RecipeObjectOutput("snr_vs_signal", snr_vs_signal),
            RecipeObjectOutput("snr_model", snr_model),
        ),
        results=(
            RecipeResultOutput("metrics", _metrics_table(result), anchor_id="ptc"),
        ),
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "PhotonTransferRecipeParameters",
    "run_photon_transfer_characterization",
]
