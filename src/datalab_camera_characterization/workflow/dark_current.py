"""Headless dark-current (dark ramp) Camera recipe."""

from __future__ import annotations

import math
from gettext import gettext as _

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
    DarkCurrentCharacterization,
    DarkCurrentParameters,
    characterize_dark_current,
    metadata_key,
)
from .adc import CameraADCParameters
from .input_checks import prepare_camera_inputs
from .relative_dn import (
    _group_images_by_exposure,
    _histogram_centers,
    _image_output,
    _signal_output,
)

#: Pixel classes stored in the hot-pixel map output.
REGULAR_PIXEL, HOT_PIXEL, STUCK_PIXEL, INDETERMINATE_PIXEL = 0, 1, 2, 3


class DarkCurrentRecipeParameters(CameraADCParameters):
    """Parameters for the dark-ramp (dark current versus exposure) method."""

    minimum_frame_count = gds.IntItem(
        "Minimum frames per exposure",
        default=2,
        min=2,
    )
    minimum_exposure_levels = gds.IntItem(
        "Minimum dark exposure levels",
        default=3,
        min=2,
    )
    saturation_fraction_warning = gds.FloatItem(
        "Saturation warning fraction",
        default=0.01,
        min=1e-12,
        max=1.0,
    )
    conversion_gain_e_per_dn = gds.FloatItem(
        "Conversion gain (e-/LSB, 0 keeps LSB units)",
        default=0.0,
        min=0.0,
    )
    hot_pixel_threshold_sigma = gds.FloatItem(
        "Hot-pixel threshold above local background (sigma)",
        default=5.0,
        min=1e-3,
    )
    background_window = gds.IntItem(
        "Local background window (odd, pixels)",
        default=5,
        min=3,
    )
    dispersion_block_side = gds.IntItem(
        _("Intrinsic dispersion: spatial block side (pixels)"),
        default=8,
        min=1,
    )
    histogram_bin_count = gds.IntItem(
        "Dark-current histogram bins",
        default=128,
        min=2,
    )
    aggregation_block_size = gds.IntItem(
        "Aggregation block size",
        default=1,
        min=1,
    )

    def to_core_parameters(self) -> DarkCurrentParameters:
        """Return host-independent dark-current parameters."""
        gain = float(self.conversion_gain_e_per_dn)
        return DarkCurrentParameters(
            validation=CameraValidationParameters(
                minimum_frame_count=int(self.minimum_frame_count),
                saturation_dn=float(self.saturation_dn),
                saturation_fraction_warning=float(self.saturation_fraction_warning),
            ),
            minimum_exposure_levels=int(self.minimum_exposure_levels),
            conversion_gain_e_per_dn=gain if gain > 0.0 else None,
            hot_pixel_threshold_sigma=float(self.hot_pixel_threshold_sigma),
            background_window=int(self.background_window),
            dispersion_block_side=int(self.dispersion_block_side),
        )


def _rate_unit(result: DarkCurrentCharacterization) -> tuple[float, str]:
    """Return the factor and unit used for dark-current outputs."""
    if result.conversion_gain_e_per_dn is None:
        return 1.0, "LSB/s"
    return result.conversion_gain_e_per_dn, "e-/s"


def _metrics_table(result: DarkCurrentCharacterization) -> TableResult:
    """Build the dark-current summary table for the ramp anchor."""
    factor, unit = _rate_unit(result)
    mean_rate = result.dark_current_dn_per_s
    nonuniformity_percent = (
        100.0 * result.dark_current_nonuniformity_dn_per_s / mean_rate
        if mean_rate > 0.0
        else math.nan
    )
    pixel_count = result.hot_pixel_mask.size
    summary = f"Summary pixels: {result.summary_pixel_count}/{pixel_count}"
    all_pixels = f"All {pixel_count} sensor pixels"
    intrinsic = result.intrinsic_dispersion
    status = intrinsic.status.value
    population = "Selection unavailable"
    if intrinsic.pixel_mask is not None:
        population = (
            f"Reserved frames: {intrinsic.pixel_count}/{pixel_count} pixels; "
            f"excluded {intrinsic.pilot_rail_pixels} at a rail and "
            f"{intrinsic.pilot_hot_pixels} hot candidates"
        )
    cov_unit = f"({unit})^2"
    rows: list[list[object]] = [
        ["Mean dark current", factor * mean_rate, unit, summary],
        [
            "Median dark current",
            factor * result.median_dark_current_dn_per_s,
            unit,
            summary,
        ],
        [
            "Dark-current non-uniformity",
            factor * result.dark_current_nonuniformity_dn_per_s,
            unit,
            f"Observed sample SD; {summary}",
        ],
        [
            "Relative dark-current non-uniformity",
            nonuniformity_percent,
            "%",
            summary,
        ],
        ["Dark offset", result.offset_dn, "LSB", summary],
        [
            "Dark ramp fit R^2",
            result.fit_r_squared,
            "",
            summary if math.isfinite(result.fit_r_squared) else f"Undefined; {summary}",
        ],
        ["Total pixels", pixel_count, "pixel", "Full image"],
        ["Measurable slopes", result.measured_pixel_count, "pixel", all_pixels],
        ["Summary pixels", result.summary_pixel_count, "pixel", all_pixels],
        ["Hot pixels", result.hot_pixel_count, "pixel", all_pixels],
        [
            "Hot-pixel fraction",
            1e6 * result.hot_pixel_count / pixel_count,
            "ppm",
            all_pixels,
        ],
        ["Stuck pixels", result.stuck_pixel_count, "pixel", all_pixels],
        ["Indeterminate pixels", result.indeterminate_pixel_count, "pixel", all_pixels],
        [
            "Conversion gain from dark shot noise",
            result.conversion_gain_from_dark_e_per_dn,
            "e-/LSB",
            f"Indicative; {summary}",
        ],
        ["Exposure levels", int(result.exposure_times_s.size), "", ""],
        ["Intrinsic dispersion pixels", intrinsic.pixel_count, "pixel", population],
        [
            "Split-slope covariance",
            factor**2 * intrinsic.covariance,
            cov_unit,
            f"Signed; {status}",
        ],
        [
            "Intrinsic dark-current dispersion",
            factor * intrinsic.sd_dn_per_s,
            unit,
            f"{status}; assumes independent repeated acquisitions",
        ],
    ]
    for label, bounds, scale, units in (
        ("Split-slope covariance", intrinsic.covariance_ci95, factor**2, cov_unit),
        ("Intrinsic dispersion", intrinsic.sd_ci95, factor, unit),
    ):
        for endpoint, bound in zip(("lower", "upper"), bounds):
            rows.append([f"{label} 95% {endpoint}", scale * bound, units, status])
    return TableResult(
        title="Dark-current metrics",
        kind="camera_dark_current",
        headers=["Metric", "Value", "Unit", "Status"],
        data=[
            [
                name,
                None
                if isinstance(value, float) and not math.isfinite(value)
                else value,
                unit_name,
                status,
            ]
            for name, value, unit_name, status in rows
        ],
        roi_indices=[NO_ROI] * len(rows),
        attrs={
            "measurement_domain": "dark_current",
            "normative": False,
            "rate_unit": unit,
            "hot_pixel_threshold_sigma": result.hot_pixel_threshold_sigma,
            "dispersion_status": intrinsic.status.name.lower(),
            "dispersion_population": population,
            "dispersion_exposures_s": result.exposure_times_s.tolist(),
            "dispersion_frames_per_level": list(intrinsic.frames_per_level),
            "dispersion_split_reserved_a_b": [list(x) for x in intrinsic.split_counts],
            "dispersion_pilot_rail_pixels": intrinsic.pilot_rail_pixels,
            "dispersion_pilot_hot_pixels": intrinsic.pilot_hot_pixels,
            "dispersion_fit_rail_pixels": intrinsic.fit_rail_pixels,
            "dispersion_block_side": intrinsic.block_side,
            "dispersion_populated_blocks": intrinsic.block_count,
            "dispersion_effective_blocks": intrinsic.effective_blocks,
            "dispersion_assumptions": (
                "Independent repeats, stable linear unclipped signal; matched "
                "approximately Gaussian slope errors, independent across blocks"
            ),
        },
    )


def run_dark_current_characterization(
    inputs: RecipeInputs,
    parameters: gds.DataSet | None,
    context: RecipeExecutionContext,
) -> RecipeOutcome:
    """Run the dark-ramp method and build host-neutral outputs."""
    if not isinstance(parameters, DarkCurrentRecipeParameters):
        raise RecipeValidationError(
            "Dark-current characterization requires DarkCurrentRecipeParameters"
        )
    inputs, parameters = prepare_camera_inputs(inputs, parameters, context, ramp=True)
    dark_images = inputs["dark_frames"]
    context.raise_if_cancelled()
    context.report_progress(0.0, "Preparing dark exposure ramp")
    dark_series, dark_groups = _group_images_by_exposure(
        dark_images,
        "dark_frames",
        "Dark",
    )
    try:
        core_parameters = parameters.to_core_parameters()
    except ValueError as error:
        raise RecipeValidationError(str(error)) from error
    context.report_progress(0.2, "Fitting per-pixel dark current")
    context.raise_if_cancelled()
    result = characterize_dark_current(
        dark_series,
        core_parameters,
        aggregation_block_size=int(parameters.aggregation_block_size),
    )
    context.report_progress(0.85, "Building dark-current outputs")
    context.raise_if_cancelled()

    factor, unit = _rate_unit(result)
    template = dark_groups[0][0]
    dark_ramp = _signal_output(
        "Dark signal ramp",
        result.exposure_times_s.copy(),
        result.mean_dark_dn.copy(),
        "dark_ramp",
        units=("s", "LSB"),
        labels=("Exposure time", "Mean dark signal"),
    )
    dark_ramp.metadata.update(parameters.adc_provenance)
    dark_variance_ramp = _signal_output(
        "Dark temporal variance ramp",
        result.exposure_times_s.copy(),
        result.temporal_variance_dn2.copy(),
        "dark_variance_ramp",
        units=("s", "LSB^2"),
        labels=("Exposure time", "Temporal variance"),
    )
    dark_current_map = _image_output(
        template,
        factor * result.dark_current_map_dn_per_s,
        "Dark-current map",
        "dark_current_map",
        zunit=unit,
        zlabel="Dark current",
    )
    offset_map = _image_output(
        template,
        result.offset_map_dn.copy(),
        "Dark offset map",
        "offset_map",
        zunit="LSB",
        zlabel="Offset",
    )
    pixel_classes = np.full(result.hot_pixel_mask.shape, REGULAR_PIXEL, np.uint8)
    pixel_classes[result.hot_pixel_mask] = HOT_PIXEL
    pixel_classes[result.stuck_pixel_mask] = STUCK_PIXEL
    pixel_classes[result.indeterminate_pixel_mask] = INDETERMINATE_PIXEL
    hot_pixel_map = _image_output(
        template,
        pixel_classes,
        "Hot-pixel map (0 regular, 1 hot, 2 stuck, 3 indeterminate)",
        "hot_pixel_map",
        zunit="",
        zlabel="Pixel class",
    )
    summary_pixel_mask = _image_output(
        template,
        result.summary_pixel_mask.astype(np.uint8),
        "Dark-ramp summary mask (1 included, 0 excluded)",
        "summary_pixel_mask",
        zunit="",
        zlabel="Included in summary",
    )
    finite_rates = dark_current_map.data[np.isfinite(dark_current_map.data)]
    counts, edges = np.histogram(
        finite_rates,
        bins=int(parameters.histogram_bin_count),
    )
    distribution = _signal_output(
        "Dark-current distribution",
        _histogram_centers(edges),
        counts.astype(float),
        "dark_current_distribution",
        units=(unit, ""),
        labels=("Dark current", "Measurable pixel count"),
    )
    total = pixel_classes.size
    for outputs, population, size in (
        ((hot_pixel_map,), "all_sensor_pixels", total),
        (
            (dark_current_map, offset_map, distribution),
            "measurable_slopes",
            len(finite_rates),
        ),
        (
            (dark_ramp, dark_variance_ramp, summary_pixel_mask),
            "summary_pixel_mask",
            result.summary_pixel_count,
        ),
    ):
        for output in outputs:
            output.metadata[metadata_key("pixel_population")] = population
            output.metadata[metadata_key("population_pixel_count")] = size
            output.metadata[metadata_key("total_pixel_count")] = total

    diagnostics = tuple(
        RecipeDiagnostic(
            level=diagnostic.level.value,
            code=diagnostic.code,
            message=diagnostic.message,
            details=dict(diagnostic.details),
        )
        for diagnostic in result.validation.warnings
    )
    context.report_progress(1.0, "Dark-current characterization complete")
    return RecipeOutcome(
        objects=(
            RecipeObjectOutput("dark_ramp", dark_ramp),
            RecipeObjectOutput("dark_variance_ramp", dark_variance_ramp),
            RecipeObjectOutput("dark_current_map", dark_current_map),
            RecipeObjectOutput("offset_map", offset_map),
            RecipeObjectOutput("hot_pixel_map", hot_pixel_map),
            RecipeObjectOutput("summary_pixel_mask", summary_pixel_mask),
            RecipeObjectOutput("dark_current_distribution", distribution),
        ),
        results=(
            RecipeResultOutput(
                "metrics",
                _metrics_table(result),
                anchor_id="dark_ramp",
            ),
        ),
        diagnostics=diagnostics,
    )


__all__ = [
    "DarkCurrentRecipeParameters",
    "run_dark_current_characterization",
]
