"""Resolve the native ADC scale from declared acquisition information only."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np

from .metadata import BIT_DEPTH_KEY, BIT_SHIFT_KEY, SATURATION_KEY


def _integer(value: object, key: str, low: int, high: int) -> int:
    if not isinstance(value, Integral) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer in [{low}, {high}]")
    if not low <= value <= high:
        raise ValueError(f"{key} must be in [{low}, {high}]")
    return int(value)


def _rail(value: object, key: str) -> int:
    if (
        not isinstance(value, Real)
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 1 <= value <= 2**32 - 1
        or value != int(value)
    ):
        raise ValueError(f"{key} must be a positive native ADC code (up to 32 bits)")
    return int(value)


@dataclass(frozen=True)
class IncompleteADC:
    """Checked declarations, not a decoder: no native codes can be produced."""

    bit_depth: int | None
    saturation_dn: int | None
    bit_shift: int | None


@dataclass(frozen=True)
class NativeADC:
    """One native LSB spans ``2**bit_shift`` stored counts."""

    bit_depth: int | None
    saturation_dn: int
    bit_shift: int
    rail_source: str
    shift_source: str

    @classmethod
    def inspect(
        cls,
        metadata: Mapping[str, object],
        data: np.ndarray,
        saturation_dn: float,
        bit_shift: int,
    ) -> NativeADC | IncompleteADC:
        """Check all declared constraints, even if a different field is missing."""
        dtype = data.dtype
        if dtype.kind not in "iuf":
            raise ValueError("use real numeric images of linear ADC codes")
        depth = (
            _integer(metadata[BIT_DEPTH_KEY], "bit_depth", 1, 32)
            if BIT_DEPTH_KEY in metadata
            else None
        )
        if isinstance(saturation_dn, bool) or not isinstance(saturation_dn, Real):
            raise ValueError("saturation_dn must be a numeric native ADC code")
        override = _rail(saturation_dn, "saturation_dn") if saturation_dn != 0 else None
        if SATURATION_KEY in metadata:
            rail = _rail(metadata[SATURATION_KEY], "saturation_dn")
            source = "metadata:saturation_dn"
            if override is not None and rail != override:
                raise ValueError(
                    "saturation_dn conflicts with the acquisition; use Auto (0) or "
                    "select frames with the intended native rail"
                )
        elif override is not None:
            rail, source = override, "parameter:saturation_dn"
        elif depth is not None:
            rail, source = 2**depth - 1, "metadata:bit_depth"
        else:
            rail, source = None, ""
        if depth is not None and rail is not None and rail >= 2**depth:
            raise ValueError("saturation_dn exceeds bit_depth; specify the native rail")

        requested = _integer(bit_shift, "bit_shift parameter", -1, 31)
        word_max = int(np.iinfo(dtype).max) if dtype.kind in "iu" else None
        if BIT_SHIFT_KEY in metadata:
            shift = _integer(metadata[BIT_SHIFT_KEY], "bit_shift", 0, 31)
            shift_source = "metadata:bit_shift"
            if requested != -1 and shift != requested:
                raise ValueError("bit_shift conflicts with metadata; use Auto (-1)")
        elif requested != -1:
            shift, shift_source = requested, "parameter:bit_shift"
        elif (
            word_max is not None
            and rail is not None
            and (depth or rail.bit_length()) == word_max.bit_length()
        ):
            shift, shift_source = 0, "declared scale fills storage word"
        else:
            shift, shift_source = None, ""
        if shift and word_max is None:
            raise ValueError("positive bit_shift requires integer stored codes")
        full_scale = 2**depth - 1 if depth is not None else (rail or 1)
        if word_max is not None and full_scale << (shift or 0) > word_max:
            raise ValueError("bit_depth, saturation_dn or bit_shift does not fit dtype")

        low, high = data.min().item(), data.max().item()
        limit = rail if rail is not None else 2**32 - 1
        check_shift = shift or 0
        if shift is None and word_max is not None:
            # Test only feasibility: even the smallest shift that could fit the
            # codes must fit the word and have zero padding. Never use it to decode.
            while check_shift < 31 and high > limit << check_shift:
                check_shift += 1
        if not (0 <= low <= high <= limit << check_shift) or (
            word_max is not None and full_scale << check_shift > word_max
        ):
            raise ValueError(
                "codes outside declared ADC range or non-finite; "
                "check the rail, units and alignment"
            )
        if check_shift and int(np.bitwise_or.reduce(data, axis=None)) & (
            (1 << check_shift) - 1
        ):
            raise ValueError("nonzero padding bits; verify bit_shift and input coding")
        if rail is None or shift is None:
            return IncompleteADC(depth, rail, shift)
        return cls(depth, rail, shift, source, shift_source)

    def native_codes(self, data: np.ndarray) -> np.ndarray:
        """Preserve native arrays; right shifts allocate without mutating sources."""
        return data >> self.bit_shift if self.bit_shift else data
