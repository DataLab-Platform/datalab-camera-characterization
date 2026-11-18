"""Check physical compatibility and prepare Camera frames in native LSB."""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass
from gettext import gettext as _
from numbers import Real
from typing import TypeVar

import guidata.dataset as gds
import numpy as np
from datalab.plugins.recipes import (
    RecipeDiagnostic,
    RecipeExecutionContext,
    RecipeInputs,
    RecipeValidationError,
)
from sigima.objects import ImageObj
from sigima.objects.base import ROI_KEY

from ..core.adc import NativeADC
from ..core.metadata import BIT_SHIFT_KEY, FRAME_ROLE_KEY, SATURATION_KEY, metadata_key

ADC_RESOLUTION_KEY = metadata_key("adc_resolution")
_SETTINGS = (
    "sensor_id",
    "camera_id",
    "binning",
    "roi",
    "readout_mode",
    "analog_gain",
    "conversion_gain_e_per_dn",
)
_MISSING_DECLARATIONS = {
    "missing-unit": _(
        "missing Z unit: confirm ADC codes with assume_lsb in the parameters"
    ),
    "missing-rail": _(
        "unknown ADC rail: enter the native saturation_dn in the parameters"
    ),
    "missing-shift": _(
        "unknown ADC alignment: enter bit_shift (0 for native codes) in the parameters"
    ),
}


class CameraADCParameters(gds.DataSet):
    """Acquisition declarations for files missing metadata; never force conflicts."""

    saturation_dn = gds.FloatItem(
        "Native ADC rail (LSB; 0 uses metadata)", default=0.0, min=0.0
    )
    bit_shift = gds.IntItem(
        "Unused low bits (-1 uses metadata; 0 = native)", default=-1, min=-1, max=31
    )
    assume_lsb = gds.BoolItem(
        "Confirm that images without a Z unit contain ADC codes", default=False
    )
    # Set only on the private, resolved copy returned by normalize().
    adc_provenance: dict[str, object]


P = TypeVar("P", bound=CameraADCParameters)


def explicit_frame_role(image: ImageObj) -> str | None:
    """A missing tag can be resolved by manual slot binding, not by exposure."""
    role = image.metadata.get(FRAME_ROLE_KEY)
    if isinstance(role, str) and role in ("dark", "flat"):
        return role
    return None


def infer_frame_role(image: ImageObj) -> str:
    """Return a known role, or require the caller to assign the frame explicitly."""
    role = explicit_frame_role(image)
    if role is None:
        raise RecipeValidationError(
            f"Image {image.title!r}: set frame_role to 'dark' or 'flat', or bind "
            "the image explicitly to the appropriate recipe slot"
        )
    return role


def _axis(image: ImageObj, axis: str) -> np.ndarray:
    size = image.data.shape[1 if axis == "x" else 0]
    if image.is_uniform_coords:
        step = getattr(image, f"d{axis}")
        return getattr(image, f"{axis}0") + step * np.arange(size)
    return np.asarray(getattr(image, f"{axis}coords"))


def _check_geometry(image: ImageObj, reference: ImageObj) -> None:
    if image.data.shape != reference.data.shape:
        raise ValueError("frames differ in size: select a common sensor ROI")
    if image.data.dtype != reference.data.dtype:
        raise ValueError("frames differ in dtype: use a consistent storage format")
    # ImageObj.roi may remove an unrecognized legacy entry while reading it.
    # These methods analyze full frames, never silently ignore a processing ROI.
    if image.metadata.get(ROI_KEY) is not None:
        raise ValueError("extract the same ROI from all frames before analysis")
    if (image.xunit, image.yunit) != (reference.xunit, reference.yunit):
        raise ValueError("axis units differ: use one calibrated coordinate system")
    for axis in ("x", "y"):
        if image.is_uniform_coords:
            origin, step = getattr(image, f"{axis}0"), getattr(image, f"d{axis}")
            if not np.isfinite(origin) or not np.isfinite(step) or step == 0:
                raise ValueError(f"invalid {axis} origin or pixel spacing")
            if reference.is_uniform_coords:
                if (origin, step) != (
                    getattr(reference, f"{axis}0"),
                    getattr(reference, f"d{axis}"),
                ):
                    raise ValueError(f"{axis} origins or pixel spacings differ")
                continue
        coords = _axis(image, axis)
        size = image.data.shape[1 if axis == "x" else 0]
        if (
            coords.dtype.kind not in "iuf"
            or coords.shape != (size,)
            or not np.isfinite(coords).all()
            or not (
                np.all(coords[1:] > coords[:-1]) or np.all(coords[1:] < coords[:-1])
            )
        ):
            raise ValueError(f"invalid {axis} coordinate vector")
        if not np.array_equal(coords, _axis(reference, axis)):
            raise ValueError(f"{axis} coordinate vectors differ")


@dataclass(frozen=True)
class FrameEncoding:
    adc: NativeADC
    unit_source: str
    role_source: str


@dataclass
class Acquisition:
    """Checked sources and their per-frame decoding instructions."""

    frames: dict[str, list[tuple[ImageObj, FrameEncoding]]]
    saturation_dn: int
    settings: dict[str, object]

    def normalize(
        self, parameters: P, context: RecipeExecutionContext
    ) -> tuple[RecipeInputs, P]:
        """Create private frame shells (keep original UUIDs) and effective settings."""
        inputs = {}
        encodings: Counter[FrameEncoding] = Counter()
        for slot, pairs in self.frames.items():
            images = []
            for image, encoding in pairs:
                context.raise_if_cancelled()
                adc = encoding.adc
                native = copy.copy(image)
                native.data = adc.native_codes(image.data).view()
                native.data.flags.writeable = False
                native.zunit = "LSB"
                native.metadata = dict(image.metadata)
                native.metadata.update(
                    {
                        BIT_SHIFT_KEY: 0,
                        SATURATION_KEY: adc.saturation_dn,
                        FRAME_ROLE_KEY: slot.removesuffix("_frames"),
                    }
                )
                images.append(native)
                encodings[encoding] += 1
            inputs[slot] = tuple(images)
        effective = copy.copy(parameters)
        effective.saturation_dn = float(self.saturation_dn)
        effective.bit_shift = 0
        effective.adc_provenance = {
            ADC_RESOLUTION_KEY: {
                "unit": "LSB",
                "saturation_dn": self.saturation_dn,
                "acquisition_settings": self.settings,
                "encodings": [
                    {
                        "bit_depth": encoding.adc.bit_depth,
                        "bit_shift": encoding.adc.bit_shift,
                        "stored_counts_per_lsb": 1 << encoding.adc.bit_shift,
                        "rail_source": encoding.adc.rail_source,
                        "shift_source": encoding.adc.shift_source,
                        "unit_source": encoding.unit_source,
                        "role_source": encoding.role_source,
                        "frame_count": count,
                    }
                    for encoding, count in encodings.items()
                ],
            }
        }
        return inputs, effective


def _unit_source(image: ImageObj, parameters: CameraADCParameters) -> str | None:
    unit = (image.zunit or "").strip()
    if unit.casefold() in ("lsb", "dn"):
        return f"image:{unit}"
    if unit:
        raise ValueError(f"Z unit {unit!r}: convert to linear ADC codes (LSB) first")
    return "parameter:assume_lsb" if parameters.assume_lsb is True else None


def _settings(image: ImageObj) -> dict[str, object]:
    """Canonical JSON values; ROI=(x, y, width, height) in unbinned pixels."""
    settings = {}
    for key in _SETTINGS:
        value = image.metadata.get(metadata_key(key))
        if value is None:
            continue
        if key in ("binning", "roi"):
            array = np.asarray(value)
            if key == "binning" and array.ndim == 0:
                array = np.repeat(array, 2)
            size = 2 if key == "binning" else 4
            if (
                array.dtype.kind not in "iu"
                or array.shape != (size,)
                or np.any(array < 0)
                or np.any(array[-2:] == 0)
            ):
                raise ValueError(f"{key}: specify pixel binning (x,y) or ROI (x,y,w,h)")
            value = array.tolist()
        elif key == "conversion_gain_e_per_dn":
            if (
                isinstance(value, bool)
                or not isinstance(value, Real)
                or not np.isfinite(value)
                or value <= 0
            ):
                raise ValueError(
                    "specify a positive conversion_gain_e_per_dn in e-/LSB"
                )
            value = float(value)
        else:
            if isinstance(value, np.generic):
                value = value.item()
            if not isinstance(value, (str, int, float)):
                raise ValueError(f"specify one {key} value per acquisition")
        settings[key] = value
    return settings


def inspect_acquisition(
    inputs: RecipeInputs,
    parameters: CameraADCParameters,
    slots: tuple[str, ...],
    context: RecipeExecutionContext | None = None,
) -> tuple[Acquisition | None, list[RecipeDiagnostic]]:
    """Return a decodable acquisition or the outstanding parameter declarations.

    Contradictions raise even if another frame or field is incomplete.
    """
    if set(inputs) != set(slots) or any(not inputs[slot] for slot in slots):
        raise RecipeValidationError(f"Assign images explicitly to {', '.join(slots)}")
    reference = None
    seen: set[int] = set()
    known: dict[str, object] = {}
    missing: dict[str, str] = {}
    frames: dict[str, list[tuple[ImageObj, FrameEncoding]]] = {}
    for slot in slots:
        frames[slot] = []
        for image in inputs[slot]:
            if context is not None:
                context.raise_if_cancelled()
            if not isinstance(image, ImageObj):
                raise RecipeValidationError(f"{slot}: select image objects only")
            try:
                if id(image) in seen:
                    raise ValueError("duplicate frame: bind each acquisition only once")
                seen.add(id(image))
                data = image.data
                if not isinstance(data, np.ndarray) or data.ndim != 2 or not data.size:
                    raise ValueError("supply non-empty 2-D camera frames")
                role = explicit_frame_role(image)
                if FRAME_ROLE_KEY in image.metadata and role != slot.removesuffix(
                    "_frames"
                ):
                    raise ValueError(
                        f"frame_role and {slot} disagree; correct the role or binding"
                    )
                if reference is None:
                    reference = image
                _check_geometry(image, reference)
                unit = _unit_source(image, parameters)
                adc = NativeADC.inspect(
                    image.metadata,
                    data,
                    parameters.saturation_dn,
                    parameters.bit_shift,
                )
                settings = _settings(image)
                settings.update(
                    bit_depth=adc.bit_depth, saturation_dn=adc.saturation_dn
                )
                for key, value in settings.items():
                    if value is not None and known.setdefault(key, value) != value:
                        raise ValueError(
                            f"incompatible {key}; select one acquisition configuration"
                        )
                if unit is not None and isinstance(adc, NativeADC):
                    source = "metadata" if role else "binding"
                    frames[slot].append((image, FrameEncoding(adc, unit, source)))
                else:
                    for code, value in (
                        ("missing-unit", unit),
                        ("missing-rail", adc.saturation_dn),
                        ("missing-shift", adc.bit_shift),
                    ):
                        if value is None:
                            missing.setdefault(code, f"{slot}: image {image.title!r}")
            except (TypeError, ValueError) as error:
                raise RecipeValidationError(
                    f"{slot}: image {image.title!r}: {error}"
                ) from error
    if "roi" in known and "binning" in known:
        bx, by = known["binning"]
        rows, cols = reference.data.shape
        if known["roi"][2:] != [cols * bx, rows * by]:
            raise RecipeValidationError(
                "ROI width/height and binning disagree with image dimensions; "
                "specify the acquisition ROI in unbinned sensor pixels"
            )
    gain = known.get("conversion_gain_e_per_dn")
    if slots == ("dark_frames",) and gain is not None:
        if parameters.conversion_gain_e_per_dn not in (0, gain):
            raise RecipeValidationError(
                "conversion_gain_e_per_dn conflicts with the acquisition: use the "
                "calibrated gain in e-/native LSB, or 0 to report native LSB/s"
            )
    if missing:
        return None, [
            RecipeDiagnostic("warning", code, f"{where}: {_MISSING_DECLARATIONS[code]}")
            for code, where in missing.items()
        ]
    rail = int(known.pop("saturation_dn"))
    known.pop("bit_depth", None)
    return Acquisition(frames, rail, known), []
