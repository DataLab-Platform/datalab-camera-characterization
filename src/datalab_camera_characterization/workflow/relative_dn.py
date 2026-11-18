"""Headless relative-LSB Camera characterization recipe."""

from __future__ import annotations

from collections.abc import Sequence

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
from sigima.objects import (
    NO_ROI,
    ImageObj,
    SignalObj,
    TableResult,
    create_image,
    create_signal,
)

from ..core import (
    CameraExposureSeries,
    CameraValidationParameters,
    ImageStackSource,
    characterize_relative_dn,
    characterize_spatial_dn,
    compute_image_stack_mean,
    metadata_key,
)
from .adc import CameraADCParameters, infer_frame_role
from .dark_reference import (
    DARK_REFERENCE_METADATA_KEY,
    EXPOSURE_TIME_METADATA_KEY,
    _image_exposure,
    dark_image_groups,
    dark_provenance,
    dark_reference_rows,
    reference_options,
    short_bias_item,
    single_reference_item,
)
from .input_checks import prepare_camera_inputs

FRAME_ROLE_METADATA_KEY = metadata_key("frame_role")
OUTPUT_ROLE_METADATA_KEY = metadata_key("output_role")
CANDIDATE_THRESHOLD_METADATA_KEY = metadata_key("candidate_threshold_sigma")


class CameraRecipeParameters(CameraADCParameters):
    """Parameters for relative Camera characterization in LSB."""

    minimum_frame_count = gds.IntItem(
        "Minimum frames per series",
        default=2,
        min=2,
    )
    minimum_flat_levels = gds.IntItem(
        "Minimum flat exposure levels",
        default=2,
        min=2,
    )
    saturation_fraction_warning = gds.FloatItem(
        "Saturation warning fraction",
        default=0.01,
        min=1e-12,
        max=1.0,
    )
    maximum_temporal_variance_dn2 = gds.FloatItem(
        "Maximum temporal variance warning (LSB^2, 0 disables)",
        default=0.0,
        min=0.0,
    )
    aggregation_block_size = gds.IntItem(
        "Aggregation block size",
        default=1,
        min=1,
    )
    candidate_threshold_sigma = gds.FloatItem(
        "Candidate pixel threshold (sigma)",
        default=5.0,
        min=1e-12,
    )
    spatial_histogram_bin_count = gds.IntItem(
        "Spatial histogram bins",
        default=64,
        min=2,
    )
    dark_reference_exposure_s = single_reference_item()
    short_dark_exposure_s = short_bias_item()

    def to_validation_parameters(self) -> CameraValidationParameters:
        """Return host-independent validation parameters."""
        maximum_variance = float(self.maximum_temporal_variance_dn2)
        return CameraValidationParameters(
            minimum_frame_count=int(self.minimum_frame_count),
            minimum_flat_levels=int(self.minimum_flat_levels),
            saturation_dn=float(self.saturation_dn),
            saturation_fraction_warning=float(self.saturation_fraction_warning),
            maximum_temporal_variance_dn2=(
                maximum_variance if maximum_variance > 0.0 else None
            ),
        )


def _image_data(image: ImageObj, slot_name: str) -> np.ndarray:
    """Return validated two-dimensional image data for one input frame."""
    data = image.data
    if not isinstance(data, np.ndarray) or data.ndim != 2 or 0 in data.shape:
        raise RecipeValidationError(
            f"Recipe input {slot_name!r} contains an empty or non-2D image"
        )
    return data


def _frame_arrays(
    images: Sequence[ImageObj],
    slot_name: str,
) -> tuple[np.ndarray, ...]:
    """Expose frame arrays without materializing a complete 3D stack."""
    return tuple(_image_data(image, slot_name) for image in images)


def _group_images_by_exposure(
    images: Sequence[ImageObj],
    slot_name: str = "flat_frames",
    role: str = "Flat",
) -> tuple[tuple[CameraExposureSeries, ...], tuple[tuple[ImageObj, ...], ...]]:
    """Group frames by exposure and return increasing exposure series."""
    grouped: dict[float, list[ImageObj]] = {}
    for image in images:
        grouped.setdefault(_image_exposure(image, role), []).append(image)

    series: list[CameraExposureSeries] = []
    image_groups: list[tuple[ImageObj, ...]] = []
    for exposure_time_s in sorted(grouped):
        group = tuple(grouped[exposure_time_s])
        series.append(
            CameraExposureSeries(
                _frame_arrays(group, slot_name),
                exposure_time_s,
                label=f"{role.casefold()}[{exposure_time_s:g} s]",
            )
        )
        image_groups.append(group)
    return tuple(series), tuple(image_groups)


def _image_output(
    template: ImageObj,
    data: np.ndarray,
    title: str,
    role: str,
    *,
    zunit: str | None = None,
    zlabel: str | None = None,
) -> ImageObj:
    """Create one geometry-preserving image output."""
    output = create_image(
        title,
        data,
        units=(
            template.xunit,
            template.yunit,
            template.zunit if zunit is None else zunit,
        ),
        labels=(
            template.xlabel,
            template.ylabel,
            template.zlabel if zlabel is None else zlabel,
        ),
    )
    if template.is_uniform_coords:
        output.set_uniform_coords(template.dx, template.dy, template.x0, template.y0)
    else:
        output.set_coords(template.xcoords.copy(), template.ycoords.copy())
    output.metadata[OUTPUT_ROLE_METADATA_KEY] = role
    return output


def _mean_image(
    template: ImageObj,
    frames: ImageStackSource,
    title: str,
    role: str,
    block_size: int,
) -> ImageObj:
    """Create one geometry-preserving mean image output."""
    mean_data = compute_image_stack_mean(
        frames,
        block_size=block_size,
    )
    # Older input files may label one ADC step "DN"; preserve other source units.
    unit = "LSB" if template.zunit == "DN" else template.zunit
    return _image_output(template, mean_data, title, role, zunit=unit)


def _axis_coordinates(image: ImageObj, axis: int) -> np.ndarray:
    """Return physical row or column coordinates for an image."""
    if axis == 0:
        if image.is_uniform_coords:
            return image.y0 + image.dy * np.arange(image.data.shape[0])
        return image.ycoords.copy()
    if image.is_uniform_coords:
        return image.x0 + image.dx * np.arange(image.data.shape[1])
    return image.xcoords.copy()


def _signal_output(
    title: str,
    x: np.ndarray,
    y: np.ndarray,
    role: str,
    *,
    units: tuple[str, str],
    labels: tuple[str, str],
) -> SignalObj:
    """Create one signal output with stable role metadata."""
    output = create_signal(title, x, y, units=units, labels=labels)
    output.metadata[OUTPUT_ROLE_METADATA_KEY] = role
    return output


def _histogram_centers(edges: np.ndarray) -> np.ndarray:
    """Return bin centers for one histogram edge array."""
    return 0.5 * (edges[:-1] + edges[1:])


def _metrics_table(
    result,
    spatial_result,
    selected_flat_exposure_s: float,
    candidate_threshold_sigma: float,
    provenance: dict,
) -> TableResult:
    """Build a non-normative summary table for the response anchor."""
    fitted_residuals = result.linearity_residuals_dn[result.linear_fit_mask]
    rows: list[list[object]] = [
        ["Response slope", result.linear_fit_slope_dn_per_s, "LSB/s", "Not assessed"],
        ["Response intercept", result.linear_fit_intercept_dn, "LSB", "Not assessed"],
        ["Dark temporal noise", result.dark_temporal_noise_dn, "LSB", "Not assessed"],
        [
            "Maximum absolute linearity residual",
            float(np.max(np.abs(fitted_residuals))),
            "LSB",
            "Not assessed",
        ],
        [
            "Maximum unsaturated signal",
            result.maximum_unsaturated_signal_dn,
            "LSB",
            "Not assessed",
        ],
        [
            "Relative dynamic range",
            result.relative_dynamic_range,
            "ratio",
            "Not assessed",
        ],
        [
            "Dark spatial non-uniformity",
            spatial_result.dark_nonuniformity_dn,
            "LSB",
            "Not assessed",
        ],
        [
            "Flat-field spatial non-uniformity",
            100.0 * spatial_result.flat_field_nonuniformity_fraction,
            "%",
            "Not assessed",
        ],
        [
            "Candidate pixels",
            spatial_result.candidate_pixel_count,
            "pixel",
            "Not assessed",
        ],
        [
            "Candidate pixel fraction",
            1e6 * spatial_result.candidate_pixel_fraction,
            "ppm",
            "Not assessed",
        ],
        ["Mean flat exposure", selected_flat_exposure_s, "s", "Not assessed"],
        *dark_reference_rows(result.dark_reference),
    ]
    if result.saturation_onset_exposure_s is not None:
        rows.append(
            [
                "Saturation onset exposure",
                result.saturation_onset_exposure_s,
                "s",
                "Not assessed",
            ]
        )
    return TableResult(
        title="Relative Camera characterization metrics",
        kind="camera_characterization",
        headers=["Metric", "Value", "Unit", "Status"],
        data=rows,
        roi_indices=[NO_ROI] * len(rows),
        attrs={
            "measurement_domain": "relative_dn",
            "normative": False,
            "selected_flat_exposure_s": selected_flat_exposure_s,
            "candidate_threshold_sigma": candidate_threshold_sigma,
            "dark_reference": provenance,
        },
    )


def run_relative_dn_characterization(
    inputs: RecipeInputs,
    parameters: gds.DataSet | None,
    context: RecipeExecutionContext,
) -> RecipeOutcome:
    """Run relative Camera characterization and build host-neutral outputs.

    Recipe-level validation resolves acquisition metadata. Core validation then
    checks frame structure, consistency, saturation, and statistical criteria;
    its structured errors stop execution before an outcome can be committed.
    """
    if not isinstance(parameters, CameraRecipeParameters):
        raise RecipeValidationError(
            "Relative Camera characterization requires CameraRecipeParameters"
        )
    inputs, parameters = prepare_camera_inputs(inputs, parameters, context)
    dark_images = inputs["dark_frames"]
    flat_images = inputs["flat_frames"]
    context.raise_if_cancelled()
    context.report_progress(0.0, "Preparing Camera frame series")

    flat_series, flat_groups = _group_images_by_exposure(flat_images)
    options = reference_options(parameters)
    dark_groups, exposure_source = dark_image_groups(
        dark_images, options["dark_reference_exposure_s"]
    )
    dark_frames = {
        t: _frame_arrays(group, "dark_frames") for t, group in dark_groups.items()
    }
    context.report_progress(0.25, "Validating Camera frame series")
    context.raise_if_cancelled()

    block_size = int(parameters.aggregation_block_size)
    result = characterize_relative_dn(
        dark_frames,
        flat_series,
        parameters.to_validation_parameters(),
        aggregation_block_size=block_size,
        **options,
    )
    context.report_progress(0.65, "Building Camera outputs")
    context.raise_if_cancelled()

    response = create_signal(
        "Camera response",
        result.exposure_times_s.copy(),
        result.mean_signal_dn.copy(),
        units=("s", "LSB"),
        labels=("Exposure time", "Mean signal"),
    )
    response.metadata[OUTPUT_ROLE_METADATA_KEY] = "response"
    response.metadata.update(parameters.adc_provenance)
    provenance = dark_provenance(result.dark_reference, exposure_source)
    response.metadata[DARK_REFERENCE_METADATA_KEY] = provenance
    response.metadata[metadata_key("flat_temporal_variance_dn2")] = (
        result.temporal_variance_dn2.tolist()
    )
    response.metadata[metadata_key("signal_variance_dn2")] = (
        result.signal_variance_dn2.tolist()
    )

    selected_flat_index = int(np.flatnonzero(result.linear_fit_mask)[-1])
    spatial_dark_s = result.dark_reference.plan.correction_exposures_s[
        selected_flat_index
    ]
    mean_dark = _mean_image(
        dark_groups[spatial_dark_s][0],
        dark_frames[spatial_dark_s],
        f"Mean dark image ({spatial_dark_s:g} s)",
        "mean_dark",
        block_size,
    )
    mean_dark.metadata[EXPOSURE_TIME_METADATA_KEY] = spatial_dark_s
    mean_dark.metadata[metadata_key("frame_count")] = len(dark_frames[spatial_dark_s])
    selected_flat_series = flat_series[selected_flat_index]
    selected_flat_images = flat_groups[selected_flat_index]
    mean_flat = _mean_image(
        selected_flat_images[0],
        selected_flat_series.frames_dn,
        f"Mean flat image ({selected_flat_series.exposure_time_s:g} s)",
        "mean_flat",
        block_size,
    )
    mean_flat.metadata[EXPOSURE_TIME_METADATA_KEY] = (
        selected_flat_series.exposure_time_s
    )
    context.report_progress(0.8, "Building Camera spatial outputs")
    context.raise_if_cancelled()

    try:
        spatial_result = characterize_spatial_dn(
            mean_dark.data,
            mean_flat.data,
            candidate_threshold_sigma=float(parameters.candidate_threshold_sigma),
            histogram_bin_count=int(parameters.spatial_histogram_bin_count),
        )
    except ValueError as error:
        raise RecipeValidationError(str(error)) from error
    dsnu_like_map = _image_output(
        mean_dark,
        spatial_result.dsnu_like_map_dn,
        "Relative DSNU-like map",
        "dsnu_like_map",
        zunit="LSB",
        zlabel="Dark offset",
    )
    prnu_like_map = _image_output(
        mean_flat,
        spatial_result.prnu_like_map_fraction,
        "Relative PRNU-like map",
        "prnu_like_map",
        zunit="",
        zlabel="Relative response",
    )
    candidate_pixel_map = _image_output(
        mean_flat,
        spatial_result.candidate_pixel_mask.astype(np.uint8),
        "Candidate pixel map",
        "candidate_pixel_map",
        zunit="",
        zlabel="Candidate",
    )
    candidate_pixel_map.metadata[CANDIDATE_THRESHOLD_METADATA_KEY] = float(
        parameters.candidate_threshold_sigma
    )
    for image in (dsnu_like_map, prnu_like_map, candidate_pixel_map):
        image.metadata[metadata_key("spatial_dark_exposure_s")] = spatial_dark_s
        image.metadata[metadata_key("spatial_flat_exposure_s")] = (
            selected_flat_series.exposure_time_s
        )

    prnu_row_profile = _signal_output(
        "PRNU-like row profile",
        _axis_coordinates(mean_flat, 0),
        spatial_result.row_profile_fraction,
        "prnu_row_profile",
        units=(mean_flat.yunit, ""),
        labels=(mean_flat.ylabel or "Y", "Relative response"),
    )
    prnu_column_profile = _signal_output(
        "PRNU-like column profile",
        _axis_coordinates(mean_flat, 1),
        spatial_result.column_profile_fraction,
        "prnu_column_profile",
        units=(mean_flat.xunit, ""),
        labels=(mean_flat.xlabel or "X", "Relative response"),
    )
    dsnu_distribution = _signal_output(
        "DSNU-like distribution",
        _histogram_centers(spatial_result.dsnu_histogram_bin_edges_dn),
        spatial_result.dsnu_histogram_counts,
        "dsnu_distribution",
        units=("LSB", ""),
        labels=("Dark offset", "Pixel count"),
    )
    prnu_distribution = _signal_output(
        "PRNU-like distribution",
        _histogram_centers(spatial_result.prnu_histogram_bin_edges_fraction),
        spatial_result.prnu_histogram_counts,
        "prnu_distribution",
        units=("", ""),
        labels=("Relative response", "Pixel count"),
    )

    diagnostics = tuple(
        RecipeDiagnostic(
            level=diagnostic.level.value,
            code=diagnostic.code,
            message=diagnostic.message,
            details=dict(diagnostic.details),
        )
        for diagnostic in result.validation.warnings
    )
    metrics = _metrics_table(
        result,
        spatial_result,
        selected_flat_series.exposure_time_s,
        float(parameters.candidate_threshold_sigma),
        provenance,
    )
    context.report_progress(1.0, "Camera characterization complete")
    return RecipeOutcome(
        objects=(
            RecipeObjectOutput("response", response),
            RecipeObjectOutput("mean_dark", mean_dark),
            RecipeObjectOutput("mean_flat", mean_flat),
            RecipeObjectOutput("dsnu_like_map", dsnu_like_map),
            RecipeObjectOutput("prnu_like_map", prnu_like_map),
            RecipeObjectOutput("candidate_pixel_map", candidate_pixel_map),
            RecipeObjectOutput("prnu_row_profile", prnu_row_profile),
            RecipeObjectOutput("prnu_column_profile", prnu_column_profile),
            RecipeObjectOutput("dsnu_distribution", dsnu_distribution),
            RecipeObjectOutput("prnu_distribution", prnu_distribution),
        ),
        results=(RecipeResultOutput("metrics", metrics, anchor_id="response"),),
        diagnostics=diagnostics,
    )


__all__ = [
    "CameraRecipeParameters",
    "CANDIDATE_THRESHOLD_METADATA_KEY",
    "EXPOSURE_TIME_METADATA_KEY",
    "FRAME_ROLE_METADATA_KEY",
    "OUTPUT_ROLE_METADATA_KEY",
    "infer_frame_role",
    "run_relative_dn_characterization",
]
