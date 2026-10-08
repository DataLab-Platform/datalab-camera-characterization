"""Host-neutral generated Camera examples shared by the Desktop and Web adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from datalab.plugins.examples import PluginExample, PluginExampleData
from sigima.objects import ImageObj, create_image

from .core import CameraSimulationParameters, metadata_key, simulate_camera_frames
from .workflow import (
    DARK_CURRENT_RECIPE,
    EXPOSURE_TIME_METADATA_KEY,
    FRAME_ROLE_METADATA_KEY,
    PHOTON_TRANSFER_RECIPE,
    RELATIVE_DN_RECIPE,
)

FRAME_SHAPE = (96, 128)
CONVERSION_GAIN_E_PER_DN = 2.0

PHOTON_TRANSFER_SEED = 20260810
PHOTON_TRANSFER_RATE_E_PER_S = 60_000.0
PHOTON_TRANSFER_DARK_FRAMES = 4
PHOTON_TRANSFER_FRAMES_PER_LEVEL = 2
# Geometric low part, then dense steps around ADC saturation (about 133 ms).
PHOTON_TRANSFER_EXPOSURES_S = (
    0.001,
    0.002,
    0.004,
    0.008,
    0.016,
    0.032,
    0.064,
    0.096,
    0.112,
    0.116,
    0.120,
    0.124,
    0.128,
    0.132,
    0.136,
    0.140,
)

DARK_RAMP_SEED = 20260811
DARK_RAMP_FRAMES_PER_LEVEL = 4
DARK_RAMP_EXPOSURES_S = (0.5, 1.0, 2.0, 4.0, 8.0)
DARK_CURRENT_E_PER_S = 40.0
DARK_CURRENT_NONUNIFORMITY_FRACTION = 0.10
DARK_HOT_PIXEL_FRACTION = 0.002
DARK_HOT_PIXEL_FACTOR = 30.0
AMPLIFIER_GLOW_E_PER_S = 150.0

PHOTON_TRANSFER_DEMO = PluginExample(
    id="photon-transfer",
    title="Synthetic photon transfer ladder",
    description=(
        "Uniformly illuminated frames from 1 ms to 140 ms, two per level, up to "
        "ADC saturation (2 e-/DN, 3 e- read noise)."
    ),
    # Like EMVA 1288, one exposure ladder gives both the PTC and the linearity
    recipe_ids=(PHOTON_TRANSFER_RECIPE.recipe_id, RELATIVE_DN_RECIPE.recipe_id),
)
DARK_RAMP_DEMO = PluginExample(
    id="dark-ramp",
    title="Synthetic uncooled CMOS dark ramp",
    description=(
        "Dark frames from 0.5 s to 8 s with 40 e-/s dark current, 10% "
        "non-uniformity, hot pixels and amplifier glow."
    ),
    recipe_ids=(DARK_CURRENT_RECIPE.recipe_id,),
)


def _sensor_parameters(seed: int, **overrides: object) -> CameraSimulationParameters:
    """Return one 12-bit sensor shared by every series of a demonstration."""
    values: dict[str, object] = {
        "shape": FRAME_SHAPE,
        "offset_dn": 100.0,
        "conversion_gain_e_per_dn": CONVERSION_GAIN_E_PER_DN,
        "read_noise_e": 3.0,
        "dark_current_e_per_s": 0.2,
        "prnu_fraction": 0.01,
        "dsnu_dn": 1.0,
        "row_pattern_dn": 3.0,
        "column_pattern_dn": 2.0,
        "saturation_dn": 4_095.0,
        "bit_depth": 12,
        "defective_pixel_fraction": 0.001,
        "seed": seed,
    }
    values.update(overrides)
    return CameraSimulationParameters(**values)


def series_images(
    title_prefix: str,
    parameters: CameraSimulationParameters,
    role: str,
) -> list[ImageObj]:
    """Simulate one series and wrap its frames as tagged image objects."""
    images: list[ImageObj] = []
    frames = simulate_camera_frames(parameters).frames_dn
    for index, frame in enumerate(frames, start=1):
        image = create_image(f"{title_prefix} {index:02d}", frame.copy())
        image.metadata[metadata_key("synthetic")] = True
        image.metadata[metadata_key("simulation_seed")] = parameters.seed
        image.metadata[FRAME_ROLE_METADATA_KEY] = role
        image.metadata[EXPOSURE_TIME_METADATA_KEY] = parameters.exposure_time_s
        images.append(image)
    return images


def build_photon_transfer_campaign() -> PluginExampleData:
    """Build the deterministic photon transfer demonstration campaign."""
    stream = 1
    longest = max(PHOTON_TRANSFER_EXPOSURES_S)
    images = series_images(
        "Dark",
        _sensor_parameters(
            PHOTON_TRANSFER_SEED,
            frame_count=PHOTON_TRANSFER_DARK_FRAMES,
            exposure_time_s=longest,
            signal_electrons=0.0,
            noise_stream=stream,
        ),
        "dark",
    )
    for exposure_time_s in PHOTON_TRANSFER_EXPOSURES_S:
        stream += 1
        images.extend(
            series_images(
                f"Flat {exposure_time_s * 1_000:g} ms",
                _sensor_parameters(
                    PHOTON_TRANSFER_SEED,
                    frame_count=PHOTON_TRANSFER_FRAMES_PER_LEVEL,
                    exposure_time_s=exposure_time_s,
                    signal_electrons=PHOTON_TRANSFER_RATE_E_PER_S * exposure_time_s,
                    noise_stream=stream,
                ),
                "flat",
            )
        )
    return PluginExampleData(tuple(images))


def build_dark_ramp_campaign() -> PluginExampleData:
    """Build the deterministic dark-ramp demonstration campaign."""
    images: list[ImageObj] = []
    for stream, exposure_time_s in enumerate(DARK_RAMP_EXPOSURES_S, start=1):
        images.extend(
            series_images(
                f"Dark {exposure_time_s:g} s",
                _sensor_parameters(
                    DARK_RAMP_SEED,
                    frame_count=DARK_RAMP_FRAMES_PER_LEVEL,
                    exposure_time_s=exposure_time_s,
                    signal_electrons=0.0,
                    dark_current_e_per_s=DARK_CURRENT_E_PER_S,
                    dark_current_nonuniformity_fraction=(
                        DARK_CURRENT_NONUNIFORMITY_FRACTION
                    ),
                    dark_hot_pixel_fraction=DARK_HOT_PIXEL_FRACTION,
                    dark_hot_pixel_factor=DARK_HOT_PIXEL_FACTOR,
                    amplifier_glow_e_per_s=AMPLIFIER_GLOW_E_PER_S,
                    noise_stream=stream,
                ),
                "dark",
            )
        )
    return PluginExampleData(
        tuple(images),
        {
            DARK_CURRENT_RECIPE.recipe_id: {
                "conversion_gain_e_per_dn": CONVERSION_GAIN_E_PER_DN
            }
        },
    )


GENERATED_EXAMPLES: Mapping[str, Callable[[], PluginExampleData]] = {
    PHOTON_TRANSFER_DEMO.id: build_photon_transfer_campaign,
    DARK_RAMP_DEMO.id: build_dark_ramp_campaign,
}


def materialize_generated_example(example_id: str) -> PluginExampleData | None:
    """Return generated example data, or ``None`` for packaged examples."""
    builder = GENERATED_EXAMPLES.get(example_id)
    return None if builder is None else builder()


__all__ = [
    "DARK_RAMP_DEMO",
    "GENERATED_EXAMPLES",
    "PHOTON_TRANSFER_DEMO",
    "build_dark_ramp_campaign",
    "build_photon_transfer_campaign",
    "materialize_generated_example",
    "series_images",
]
