"""Headless photon transfer Camera recipe."""

from __future__ import annotations

import dataclasses
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
    metadata_key,
)
from .adc import CameraADCParameters
from .dark_reference import (
    DARK_REFERENCE_METADATA_KEY,
    dark_image_groups,
    dark_provenance,
    dark_reference_rows,
    reference_options,
    short_bias_item,
    single_reference_item,
)
from .input_checks import prepare_camera_inputs
from .relative_dn import _frame_arrays, _group_images_by_exposure, _signal_output


class PhotonTransferRecipeParameters(CameraADCParameters):
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
    saturation_fraction_warning = gds.FloatItem(
        "Saturation warning fraction",
        default=0.01,
        min=1e-12,
        max=1.0,
    )
    fit_upper_fraction = gds.FloatItem(
        "Linear fit upper bound (fraction of available signal)",
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
    dark_reference_exposure_s = single_reference_item()
    short_dark_exposure_s = short_bias_item()
    variance_mode = gds.ChoiceItem(
        "Variance used for gain",
        (
            ("raw", "Raw temporal variance"),
            ("centered_pairs", "Centered differences of independent pairs"),
        ),
        default="raw",
        help="Pair adjacent independent acquisitions, subtract each difference "
        "image's spatial mean, and apply the same estimator to the correction darks.",
    )
    stable_illumination = gds.BoolItem(
        "Illumination independently verified stable across the ladder",
        default=False,
        help="Required to identify a repeated response plateau below the ADC "
        "rail. Not a measurement of physical full well.",
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
            variance_mode=self.variance_mode,
            stable_illumination=bool(self.stable_illumination),
        )


def _ptc_provenance(
    result: PhotonTransferCharacterization, parameters: PhotonTransferParameters
) -> dict:
    """Keep enough small, serializable observations to reconstruct both curves."""
    plan = result.dark_reference.plan
    return {
        "variance_mode": result.variance_mode,
        "raw_gain_e_per_dn": result.raw_gain_e_per_dn,
        "centered_gain_e_per_dn": result.centered_gain_e_per_dn,
        "pair_normalization": "mean_pairs(mean_pixels((D-mean_pixels(D))^2)/2)",
        "fit_upper_fraction": parameters.fit_upper_fraction,
        "fit_mask": result.fit_mask.tolist(),
        "exposures_s": result.exposure_times_s.tolist(),
        "valid_pixel_count": result.valid_pixel_count,
        "flat_temporal_variance_dn2": result.flat_temporal_variance_dn2.tolist(),
        "raw_temporal_variance_dn2": result.raw_temporal_variance_dn2.tolist(),
        "centered_temporal_variance_dn2": [
            float(v) if np.isfinite(v) else None
            for v in result.centered_temporal_variance_dn2
        ],
        "flat_pairs": [dataclasses.asdict(p) for p in result.flat_pairs],
        "dark_pairs": [
            {"exposure_s": t, **dataclasses.asdict(p)}
            for t, p in zip(plan.used_exposures, result.dark_pairs)
        ],
        "stable_illumination_confirmed": parameters.stable_illumination,
        "variance_peak_index": result.variance_peak_index,
        "saturation_evidence": result.saturation_evidence,
        "saturation_index": result.saturation_index,
        "usable_signal_index": result.usable_signal_index,
        "saturation_status": result.saturation_status,
        "dynamic_range_status": result.dynamic_range_status,
        "clipped_mask": result.clipped_mask.tolist(),
        "rail_population": result.rail_population,
        "rail_min_pixels_per_frame": result.rail_min_pixels,
        "adc_ceiling_dn": parameters.validation.saturation_dn,
        "adc_fraction": parameters.validation.saturation_fraction_warning,
    }


def _metrics_table(
    result: PhotonTransferCharacterization, provenance: dict, ptc_provenance: dict
) -> TableResult:
    """Build the photon transfer summary table for the curve anchor."""
    saturation_status = result.saturation_status
    evidence = {
        "adc_clipping": "Repeated significant ADC clipping",
        "response_plateau": "Observed sub-rail response plateau",
        "none": "No demonstrated ceiling",
    }[result.saturation_evidence]
    rows: list[list[object]] = [
        [
            "Conversion gain",
            result.conversion_gain_e_per_dn,
            "e-/LSB",
            result.variance_mode,
        ],
        [
            "Dark temporal noise (electrons)",
            result.dark_temporal_noise_e,
            "e-",
            "Measured",
        ],
        ["Dark temporal noise", result.dark_temporal_noise_dn, "LSB", "Not assessed"],
        *dark_reference_rows(result.dark_reference),
        [
            "Saturation capacity",
            result.saturation_capacity_e,
            "e-",
            saturation_status,
        ],
        ["Saturation signal", result.saturation_signal_dn, "LSB", saturation_status],
        ["Limiting response", evidence, "", "Not a physical full well"],
        [
            "Last demonstrated usable signal",
            None
            if result.usable_signal_index is None
            else float(result.mean_signal_dn[result.usable_signal_index]),
            "LSB",
            "Before the limiting response",
        ],
        ["Dynamic range", result.dynamic_range_db, "dB", result.dynamic_range_status],
        ["Dynamic range reference", "Measured raw dark temporal noise", "", "Non-EMVA"],
        [
            "Variance peak exposure",
            result.exposure_times_s[result.variance_peak_index],
            "s",
            "Not evidence of saturation",
        ],
        ["Fit intercept", result.fit_intercept_dn2, "LSB^2", "Not assessed"],
        ["Fit R^2", result.fit_r_squared, "", "Not assessed"],
        ["Levels in linear fit", int(np.count_nonzero(result.fit_mask)), "", ""],
        ["Excluded stuck pixels", result.excluded_pixel_count, "pixel", ""],
        ["Raw gain", result.raw_gain_e_per_dn, "e-/LSB", "Same fit levels"],
        [
            "Centered-pair gain",
            result.centered_gain_e_per_dn,
            "e-/LSB",
            "Same fit levels",
        ],
        [
            "Largest removed flat pair variance",
            max(p.removed_variance_dn2 for p in result.flat_pairs),
            "LSB^2",
            "Common mode",
        ],
        [
            "Largest removed dark pair variance",
            max(p.removed_variance_dn2 for p in result.dark_pairs),
            "LSB^2",
            "Common mode",
        ],
    ]
    for t, raw, centered in zip(
        result.exposure_times_s,
        result.raw_temporal_variance_dn2,
        result.centered_temporal_variance_dn2,
    ):
        rows.extend(
            (
                ["PTC raw variance", raw, "LSB^2", f"{t:g} s; dark subtracted"],
                [
                    "PTC centered-pair variance",
                    centered,
                    "LSB^2",
                    f"{t:g} s; dark subtracted",
                ],
            )
        )
    if result.read_noise_e is not None:
        rows.append(
            [
                "Estimated read noise",
                result.read_noise_e,
                "e-",
                "Short bias; includes quantization",
            ]
        )
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
            "dark_reference": provenance,
            "ptc_analysis": ptc_provenance,
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
    inputs, parameters = prepare_camera_inputs(inputs, parameters, context)
    context.raise_if_cancelled()
    context.report_progress(0.0, "Preparing photon transfer series")
    flat_series, _flat_groups = _group_images_by_exposure(inputs["flat_frames"])
    options = reference_options(parameters)
    dark_groups, exposure_source = dark_image_groups(
        inputs["dark_frames"], options["dark_reference_exposure_s"]
    )
    dark_frames = {
        t: _frame_arrays(group, "dark_frames") for t, group in dark_groups.items()
    }
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
        **options,
    )
    context.report_progress(0.85, "Building photon transfer outputs")
    context.raise_if_cancelled()

    ptc = _signal_output(
        "Photon transfer curve",
        result.mean_signal_dn.copy(),
        result.temporal_variance_dn2.copy(),
        "ptc",
        units=("LSB", "LSB^2"),
        labels=("Mean signal", "Temporal variance"),
    )
    ptc.metadata.update(parameters.adc_provenance)
    provenance = dark_provenance(result.dark_reference, exposure_source)
    ptc.metadata[DARK_REFERENCE_METADATA_KEY] = provenance
    analysis = _ptc_provenance(result, core_parameters)
    ptc.metadata[metadata_key("ptc_analysis")] = analysis
    fit_x = result.mean_signal_dn[result.fit_mask].copy()
    ptc_fit = _signal_output(
        "Photon transfer linear fit",
        fit_x,
        result.fit_slope_dn * fit_x + result.fit_intercept_dn2,
        "ptc_fit",
        units=("LSB", "LSB^2"),
        labels=("Mean signal", "Fitted variance"),
    )
    positive = result.mean_signal_dn > 0.0
    signal_e = result.signal_electrons[positive].copy()
    noise_e = result.conversion_gain_e_per_dn * np.sqrt(
        result.flat_temporal_variance_dn2[positive]
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
        result.signal_electrons[positive & np.isfinite(result.measured_snr)],
        result.measured_snr[positive & np.isfinite(result.measured_snr)],
        "snr_vs_signal",
        units=("e-", ""),
        labels=("Mean signal", "SNR"),
    )
    snr_model = _signal_output(
        "Model SNR vs signal",
        result.signal_electrons[positive & np.isfinite(result.model_snr)],
        result.model_snr[positive & np.isfinite(result.model_snr)],
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
                    "No persistent ADC clipping or verified response plateau: "
                    f"saturation capacity status is {result.saturation_status.lower()}"
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
            RecipeResultOutput(
                "metrics", _metrics_table(result, provenance, analysis), anchor_id="ptc"
            ),
        ),
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "PhotonTransferRecipeParameters",
    "run_photon_transfer_characterization",
]
