"""Deterministic synthetic camera frame generation."""

from __future__ import annotations

import dataclasses
import math

import numpy as np


@dataclasses.dataclass(frozen=True)
class CameraSimulationParameters:
    """Physical and acquisition parameters for a synthetic camera series.

    ``conversion_gain_e_per_dn`` is expressed in electrons per digital number.
    ``signal_electrons`` is the mean photoelectron count per pixel and frame,
    before applying the static PRNU and illumination gain maps.
    ``prnu_fraction`` is the relative standard deviation of the unit-mean
    sensor gain map, while vignetting and dust shadows define a separate
    unit-mean optical illumination map. ``dsnu_dn`` controls signed pixel
    offsets; row, column, and amplifier-glow parameters add fixed readout
    structure to the same DN offset map. The requested defective-pixel fraction
    is rounded to the nearest whole pixel, then split as evenly as possible
    between dead and hot pixels.
    """

    shape: tuple[int, int] = (64, 64)
    frame_count: int = 10
    exposure_time_s: float = 0.01
    signal_electrons: float = 1_000.0
    offset_dn: float = 100.0
    conversion_gain_e_per_dn: float = 2.0
    read_noise_e: float = 3.0
    dark_current_e_per_s: float = 0.1
    prnu_fraction: float = 0.01
    dsnu_dn: float = 1.0
    row_pattern_dn: float = 0.0
    column_pattern_dn: float = 0.0
    amplifier_glow_dn: float = 0.0
    vignetting_fraction: float = 0.0
    dust_shadow_count: int = 0
    dust_shadow_depth_fraction: float = 0.0
    saturation_dn: float = 4_095.0
    bit_depth: int = 12
    defective_pixel_fraction: float = 0.0
    shot_noise: bool = True
    seed: int = 0

    def __post_init__(self) -> None:
        """Validate simulator parameters before allocating arrays."""
        if (
            not isinstance(self.shape, tuple)
            or len(self.shape) != 2
            or any(
                isinstance(size, bool) or not isinstance(size, int) or size <= 0
                for size in self.shape
            )
        ):
            raise ValueError("Camera frame shape must contain two positive integers")
        _validate_positive_integer(self.frame_count, "Frame count")
        _validate_positive_integer(self.bit_depth, "Bit depth")
        if self.bit_depth > 32:
            raise ValueError("Bit depth must not exceed 32")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("Random seed must be an integer")
        if self.seed < 0:
            raise ValueError("Random seed must be non-negative")
        if not isinstance(self.shot_noise, bool):
            raise TypeError("Shot-noise flag must be a bool")

        _validate_nonnegative(self.exposure_time_s, "Exposure time")
        _validate_nonnegative(self.signal_electrons, "Signal electron count")
        _validate_nonnegative(self.offset_dn, "Offset")
        _validate_positive(self.conversion_gain_e_per_dn, "Conversion gain")
        _validate_nonnegative(self.read_noise_e, "Read noise")
        _validate_nonnegative(self.dark_current_e_per_s, "Dark current")
        _validate_nonnegative(self.dsnu_dn, "DSNU")
        _validate_nonnegative(self.row_pattern_dn, "Row-pattern amplitude")
        _validate_nonnegative(self.column_pattern_dn, "Column-pattern amplitude")
        _validate_nonnegative(self.amplifier_glow_dn, "Amplifier-glow amplitude")
        _validate_fraction(
            self.vignetting_fraction,
            "Vignetting fraction",
            upper_inclusive=False,
        )
        _validate_nonnegative_integer(self.dust_shadow_count, "Dust-shadow count")
        _validate_fraction(
            self.dust_shadow_depth_fraction,
            "Dust-shadow depth fraction",
            upper_inclusive=False,
        )
        _validate_positive(self.saturation_dn, "Saturation")
        _validate_fraction(self.prnu_fraction, "PRNU fraction", upper_inclusive=False)
        _validate_fraction(
            self.defective_pixel_fraction,
            "Defective-pixel fraction",
            upper_inclusive=True,
        )
        if self.saturation_dn > 2**self.bit_depth - 1:
            raise ValueError("Saturation must fit within the configured bit depth")


@dataclasses.dataclass(frozen=True)
class CameraSimulationTruth:
    """Static maps and noiseless expectation used to generate a frame series.

    ``expected_dn_map`` precedes defect overrides, clipping, and quantization.
    """

    seed: int
    prnu_gain_map: np.ndarray
    illumination_gain_map: np.ndarray
    dsnu_map_dn: np.ndarray
    expected_electrons_map: np.ndarray
    expected_dn_map: np.ndarray
    dead_pixel_mask: np.ndarray
    hot_pixel_mask: np.ndarray


@dataclasses.dataclass(frozen=True)
class CameraSimulationResult:
    """Synthetic DN frames and the exact ground truth that produced them."""

    parameters: CameraSimulationParameters
    frames_dn: np.ndarray
    truth: CameraSimulationTruth


def _validate_real(value: float, name: str) -> float:
    """Return a finite real value or raise a precise validation error."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _validate_nonnegative(value: float, name: str) -> None:
    """Validate a finite value greater than or equal to zero."""
    if _validate_real(value, name) < 0.0:
        raise ValueError(f"{name} must be non-negative")


def _validate_positive(value: float, name: str) -> None:
    """Validate a finite value strictly greater than zero."""
    if _validate_real(value, name) <= 0.0:
        raise ValueError(f"{name} must be positive")


def _validate_fraction(
    value: float,
    name: str,
    *,
    upper_inclusive: bool,
) -> None:
    """Validate a finite fraction bounded by zero and one."""
    normalized = _validate_real(value, name)
    valid_upper_bound = normalized <= 1.0 if upper_inclusive else normalized < 1.0
    if normalized < 0.0 or not valid_upper_bound:
        right_bracket = "]" if upper_inclusive else ")"
        raise ValueError(f"{name} must be in [0.0, 1.0{right_bracket}")


def _validate_positive_integer(value: int, name: str) -> None:
    """Validate a positive built-in integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _validate_nonnegative_integer(value: int, name: str) -> None:
    """Validate a non-negative built-in integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _readonly(array: np.ndarray) -> np.ndarray:
    """Mark an owned simulation array as read-only and return it."""
    array.setflags(write=False)
    return array


def _output_dtype(bit_depth: int) -> np.dtype:
    """Return the smallest unsigned NumPy dtype for an ADC bit depth."""
    if bit_depth <= 8:
        return np.dtype(np.uint8)
    if bit_depth <= 16:
        return np.dtype(np.uint16)
    return np.dtype(np.uint32)


def _defective_pixel_masks(
    shape: tuple[int, int],
    fraction: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Create disjoint dead and hot pixel masks."""
    pixel_count = math.prod(shape)
    defective_count = min(pixel_count, int(round(fraction * pixel_count)))
    dead_mask = np.zeros(pixel_count, dtype=bool)
    hot_mask = np.zeros(pixel_count, dtype=bool)
    if defective_count:
        indices = rng.choice(pixel_count, size=defective_count, replace=False)
        dead_count = defective_count // 2
        dead_mask[indices[:dead_count]] = True
        hot_mask[indices[dead_count:]] = True
    return dead_mask.reshape(shape), hot_mask.reshape(shape)


def _unit_deviation_pattern(
    length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return one deterministic zero-mean pattern with unit deviation."""
    values = rng.normal(size=length)
    values -= np.mean(values)
    deviation = np.std(values)
    if deviation:
        values /= deviation
    return values


def _structured_offset_map(
    parameters: CameraSimulationParameters,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return fixed row/column readout structure and amplifier glow in DN."""
    height, width = parameters.shape
    row_pattern = (
        parameters.row_pattern_dn * _unit_deviation_pattern(height, rng)[:, np.newaxis]
    )
    column_pattern = (
        parameters.column_pattern_dn
        * _unit_deviation_pattern(width, rng)[np.newaxis, :]
    )
    y_grid, x_grid = np.mgrid[:height, :width].astype(float)
    x_distance = (width - 1 - x_grid) / max(width - 1, 1)
    y_distance = (height - 1 - y_grid) / max(height - 1, 1)
    amplifier_glow = parameters.amplifier_glow_dn * np.exp(
        -0.5 * ((x_distance / 0.22) ** 2 + (y_distance / 0.30) ** 2)
    )
    return row_pattern + column_pattern + amplifier_glow


def _illumination_gain_map(
    parameters: CameraSimulationParameters,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return a unit-mean flat-field illumination/transmission map."""
    height, width = parameters.shape
    y_grid, x_grid = np.mgrid[:height, :width].astype(float)
    x_center = 0.5 * (width - 1)
    y_center = 0.5 * (height - 1)
    x_normalized = (x_grid - x_center) / max(x_center, 1.0)
    y_normalized = (y_grid - y_center) / max(y_center, 1.0)
    corner_radius_squared = 2.0
    radial_fraction = np.clip(
        (x_normalized**2 + y_normalized**2) / corner_radius_squared,
        0.0,
        1.0,
    )
    vignetting = 1.0 - parameters.vignetting_fraction * radial_fraction

    dust_transmission = np.ones(parameters.shape, dtype=float)
    minimum_dimension = min(parameters.shape)
    for _index in range(parameters.dust_shadow_count):
        center_x = rng.uniform(0.15, 0.85) * (width - 1)
        center_y = rng.uniform(0.15, 0.85) * (height - 1)
        radius_x = rng.uniform(0.035, 0.075) * minimum_dimension
        radius_y = rng.uniform(0.035, 0.075) * minimum_dimension
        squared_radius = ((x_grid - center_x) / radius_x) ** 2 + (
            (y_grid - center_y) / radius_y
        ) ** 2
        dust_transmission *= 1.0 - parameters.dust_shadow_depth_fraction * np.exp(
            -0.5 * squared_radius
        )

    illumination = vignetting * dust_transmission
    illumination /= np.mean(illumination)
    return illumination


def simulate_camera_frames(
    parameters: CameraSimulationParameters,
) -> CameraSimulationResult:
    """Generate a deterministic stack of quantized camera frames.

    The model applies static PRNU and flat-field illumination to
    photoelectrons, adds dark-current electrons, optional Poisson shot noise
    and Gaussian read noise, converts to DN, adds the sensor-wide offset and
    fixed pixel/row/column/glow structure, applies defective pixels, then clips
    and quantizes to the configured ADC range.

    Args:
        parameters: Camera model and acquisition settings

    Returns:
        Read-only frames and exact static/noiseless ground truth
    """
    seed_sequences = np.random.SeedSequence(parameters.seed).spawn(6)
    prnu_rng, dsnu_rng, defect_rng, frame_rng, pattern_rng, illumination_rng = (
        np.random.default_rng(seed_sequence) for seed_sequence in seed_sequences
    )

    prnu_log_variance = math.log1p(parameters.prnu_fraction**2)
    prnu_gain_map = prnu_rng.lognormal(
        mean=-0.5 * prnu_log_variance,
        sigma=math.sqrt(prnu_log_variance),
        size=parameters.shape,
    )
    dsnu_map_dn = dsnu_rng.normal(
        loc=0.0,
        scale=parameters.dsnu_dn,
        size=parameters.shape,
    )
    dsnu_map_dn += _structured_offset_map(parameters, pattern_rng)
    illumination_gain_map = _illumination_gain_map(parameters, illumination_rng)
    dead_pixel_mask, hot_pixel_mask = _defective_pixel_masks(
        parameters.shape,
        parameters.defective_pixel_fraction,
        defect_rng,
    )

    expected_electrons_map = (
        parameters.signal_electrons * prnu_gain_map * illumination_gain_map
        + parameters.dark_current_e_per_s * parameters.exposure_time_s
    )
    frame_shape = (parameters.frame_count, *parameters.shape)
    if parameters.shot_noise:
        electrons = frame_rng.poisson(
            lam=expected_electrons_map,
            size=frame_shape,
        ).astype(float)
    else:
        electrons = np.broadcast_to(expected_electrons_map, frame_shape).copy()
    if parameters.read_noise_e:
        electrons += frame_rng.normal(
            loc=0.0,
            scale=parameters.read_noise_e,
            size=frame_shape,
        )

    expected_dn_map = (
        parameters.offset_dn
        + dsnu_map_dn
        + expected_electrons_map / parameters.conversion_gain_e_per_dn
    )
    frames_dn = (
        parameters.offset_dn
        + dsnu_map_dn[np.newaxis, :, :]
        + electrons / parameters.conversion_gain_e_per_dn
    )
    frames_dn[:, dead_pixel_mask] = 0.0
    frames_dn[:, hot_pixel_mask] = parameters.saturation_dn
    np.clip(frames_dn, 0.0, parameters.saturation_dn, out=frames_dn)
    frames_dn = np.rint(frames_dn).astype(_output_dtype(parameters.bit_depth))

    truth = CameraSimulationTruth(
        seed=parameters.seed,
        prnu_gain_map=_readonly(prnu_gain_map),
        illumination_gain_map=_readonly(illumination_gain_map),
        dsnu_map_dn=_readonly(dsnu_map_dn),
        expected_electrons_map=_readonly(expected_electrons_map),
        expected_dn_map=_readonly(expected_dn_map),
        dead_pixel_mask=_readonly(dead_pixel_mask),
        hot_pixel_mask=_readonly(hot_pixel_mask),
    )
    return CameraSimulationResult(
        parameters=parameters,
        frames_dn=_readonly(frames_dn),
        truth=truth,
    )


__all__ = [
    "CameraSimulationParameters",
    "CameraSimulationResult",
    "CameraSimulationTruth",
    "simulate_camera_frames",
]
