"""Dark exposure selection and provenance shared by both illuminated recipes."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from numbers import Real

import guidata.dataset as gds
from datalab.plugins.recipes import (
    RecipeDiagnostic,
    RecipeInputs,
    RecipeValidationError,
)
from sigima.objects import ImageObj

from ..core import CameraCharacterizationError, metadata_key
from ..core.dark_reference import DarkReferenceStatistics, select_dark_references

EXPOSURE_TIME_METADATA_KEY = metadata_key("exposure_time_s")
DARK_REFERENCE_METADATA_KEY = metadata_key("dark_reference")


def single_reference_item() -> gds.FloatItem:
    """Create the explicit single-series selector for a recipe DataSet."""
    return gds.FloatItem(
        "Single dark reference (s; -1: automatic)",
        default=-1.0,
        min=-1.0,
        help="Select one dark exposure instead of matching the full ladder. If "
        "no dark has exposure metadata, enter the common exposure of one series.",
    )


def short_bias_item() -> gds.FloatItem:
    """Create the independently selectable camera-minimum bias setting."""
    return gds.FloatItem(
        "Known short bias exposure (s; -1: automatic)",
        default=-1.0,
        min=-1.0,
        help="Declare a camera-minimum bias with negligible dark current. "
        "In automatic mode only a zero-exposure bias qualifies as short.",
    )


def _image_exposure(image: ImageObj, role: str = "Flat") -> float:
    """Return one finite non-negative exposure from namespaced metadata."""
    value = image.metadata.get(EXPOSURE_TIME_METADATA_KEY)
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RecipeValidationError(
            f"{role} image {image.title!r} requires numeric metadata "
            f"{EXPOSURE_TIME_METADATA_KEY!r}"
        )
    exposure_time_s = float(value)
    if not math.isfinite(exposure_time_s) or exposure_time_s < 0.0:
        raise RecipeValidationError(
            f"{role} image {image.title!r} has invalid metadata "
            f"{EXPOSURE_TIME_METADATA_KEY!r}"
        )
    return exposure_time_s


def reference_options(parameters: gds.DataSet) -> dict[str, float | None]:
    """Translate the two host sentinels to optional core exposure times."""
    return {
        key: None if value == -1.0 else value
        for key, value in (
            ("dark_reference_exposure_s", parameters.dark_reference_exposure_s),
            ("short_dark_exposure_s", parameters.short_dark_exposure_s),
        )
    }


class _UndeclaredDarkExposure(RecipeValidationError):
    """No selection yet; report whether a selectable series has enough repeats."""

    def __init__(self, max_repeats: int) -> None:
        super().__init__(
            "Unknown dark exposure: supply exposure metadata, select a labelled "
            "dark reference, or specify the common exposure of one unlabelled group"
        )
        self.max_repeats = max_repeats


def dark_image_groups(
    images: Sequence[ImageObj], selected_s: float | None
) -> tuple[dict[float, list[ImageObj]], str]:
    """Group only exact exposures. Never attribute untagged frames to a known group."""
    groups: dict[float, list[ImageObj]] = {}
    unlabelled = []
    for image in images:
        if EXPOSURE_TIME_METADATA_KEY in image.metadata:
            groups.setdefault(_image_exposure(image, "Dark"), []).append(image)
        else:
            unlabelled.append(image)
    if unlabelled:
        if selected_s is None:
            raise _UndeclaredDarkExposure(
                max(map(len, groups.values()), default=len(unlabelled))
            )
        if not groups:
            return {selected_s: unlabelled}, "operator"
        if selected_s not in groups:
            raise RecipeValidationError(
                f"No labelled dark series at selected exposure {selected_s} s"
            )
        # Explicit selection of tagged images; never pool in unlabelled frames.
    return groups, "metadata"


def check_dark_reference_inputs(
    inputs: RecipeInputs, parameters: gds.DataSet
) -> list[RecipeDiagnostic]:
    """Fast host preflight; the runner uses the same grouping and core selection."""
    options = reference_options(parameters)
    minimum = max(2, int(parameters.minimum_frame_count))
    try:
        groups, _ = dark_image_groups(
            inputs["dark_frames"], options["dark_reference_exposure_s"]
        )
        times = sorted({_image_exposure(image) for image in inputs["flat_frames"]})
        select_dark_references(
            {t: len(group) for t, group in groups.items()},
            times,
            minimum_frame_count=minimum,
            **options,
        )
    except CameraCharacterizationError as error:
        return [
            RecipeDiagnostic(
                "warning"
                if d.code == "incomplete_dark_coverage"
                and any(len(group) >= minimum for group in groups.values())
                else "error",
                d.code,
                d.message,
            )
            for d in error.validation.errors
        ]
    except _UndeclaredDarkExposure as error:
        return [
            RecipeDiagnostic(
                "warning" if error.max_repeats >= minimum else "error",
                "unknown-dark-exposure",
                str(error),
            )
        ]
    except RecipeValidationError as error:
        return [RecipeDiagnostic("error", "invalid-reference-exposure", str(error))]
    return []


def dark_provenance(reference: DarkReferenceStatistics, exposure_source: str) -> dict:
    """Return JSON-compatible quantities sufficient to replay each subtraction."""
    return {
        **dataclasses.asdict(reference.plan),
        "dark_exposure_source": exposure_source,
        "mean_dn_by_level": reference.mean_dn_by_level.tolist(),
        "variance_dn2_by_level": reference.variance_dn2_by_level.tolist(),
        "noise_mean_dn": reference.noise_mean_dn,
        "noise_variance_dn2": reference.noise_variance_dn2,
        "noise_status": reference.noise_status,
    }


def dark_reference_rows(reference: DarkReferenceStatistics) -> list[list[object]]:
    """Explain correction mode and noise origin in the user-visible summary."""
    plan = reference.plan
    status = (
        "Exposure-matched means and variances"
        if plan.mode == "matched"
        else "Exposure-dependent dark signal is not removed by one reference"
    )
    rows = [
        ["Dark correction", plan.mode, "", status],
        ["Noise reference exposure", plan.noise_exposure_s, "s", plan.noise_source],
        ["Noise reference frames", plan.noise_frame_count, "", reference.noise_status],
    ]
    for t, n in dict(
        zip(plan.correction_exposures_s, plan.correction_frame_counts)
    ).items():
        label = "Unknown exposure" if t is None else f"{t} s"
        rows.append(["Correction dark frames", n, "frames", label])
    return rows
