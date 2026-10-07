"""Host-neutral scientific camera simulator, shared by the Desktop and Web adapters.

The simulator behaves like a camera on a test bench: its settings describe one
sensor and its illumination, the live view shows a frame, and each acquisition
adds dark or flat frames tagged with the metadata the Camera methods expect.
"""

from __future__ import annotations

import itertools
import math
import re

import guidata.dataset as gds
import numpy as np
from datalab.plugin_instruments import (
    InstrumentAcquisition,
    InstrumentFrame,
    PluginInstrument,
)
from datalab.plugin_tools import PluginTool
from datalab.recipes import RecipeObjectType
from sigima.objects import ImageObj, create_image

from .core import CameraSimulationParameters, simulate_camera_frames
from .demo import series_images

#: Largest number of pixels created by one acquisition (all frames together)
MAX_ACQUISITION_PIXELS = 20_000_000
#: Live frames cycle through the first noise streams; acquisitions use the next
#: ones (the simulator spawns as many seeds as the stream number)
LIVE_NOISE_STREAMS = 64

CAMERA_SIMULATOR_TOOL = PluginTool(
    id="camera-simulator",
    title="Scientific camera simulator...",
    description="Acquire dark and flat frames from a simulated camera with live view",
    instrument="camera_simulator",
    object_type=RecipeObjectType.IMAGE,
)

_MODE = gds.ValueProp("single")
_SHUTTER = gds.ValueProp(True)


class CameraSimulatorSettings(gds.DataSet):
    """Scientific camera simulator"""

    _tabs = gds.BeginTabGroup("Settings")

    _acquisition = gds.BeginGroup("Acquisition")
    mode = gds.ChoiceItem(
        "Mode",
        (("single", "Single exposure"), ("sequence", "Exposure sequence")),
        default="single",
    ).set_prop("display", store=_MODE)
    exposure_ms = gds.FloatItem(
        "Exposure time", default=10.0, min=0.0, max=60_000.0, unit="ms"
    ).set_prop("display", active=gds.FuncProp(_MODE, lambda mode: mode == "single"))
    exposures_ms = gds.StringItem(
        "Exposure times",
        default="1, 2, 4, 8, 16, 32, 64, 96, 112, 120, 128, 136",
        help="Exposure times in milliseconds, separated by commas",
    ).set_prop("display", active=gds.FuncProp(_MODE, lambda mode: mode == "sequence"))
    frame_count = gds.IntItem("Frames per exposure", default=2, min=1, max=100)
    shutter_open = gds.BoolItem("Shutter open", default=True).set_prop(
        "display", store=_SHUTTER
    )
    dark_frame_count = gds.IntItem(
        "Dark frames",
        default=4,
        min=0,
        max=100,
        help="Frames acquired shutter closed at the longest exposure time",
    ).set_prop("display", active=_SHUTTER)
    _acquisition_end = gds.EndGroup("Acquisition")

    _illumination = gds.BeginGroup("Illumination")
    photoelectron_rate = gds.FloatItem(
        "Photoelectron rate",
        default=60_000.0,
        min=0.0,
        unit="e⁻/s",
        help="Mean photoelectrons collected per pixel and per second",
    ).set_prop("display", active=_SHUTTER)
    vignetting_percent = gds.FloatItem(
        "Vignetting", default=0.0, min=0.0, max=99.0, unit="%"
    )
    dust_shadow_count = gds.IntItem("Dust shadows", default=0, min=0, max=50)
    dust_shadow_depth_percent = gds.FloatItem(
        "Dust-shadow depth", default=20.0, min=0.0, max=99.0, unit="%"
    )
    _illumination_end = gds.EndGroup("Illumination")

    _sensor = gds.BeginGroup("Sensor")
    width = gds.IntItem("Width", default=128, min=8, max=2048, unit="px")
    height = gds.IntItem("Height", default=96, min=8, max=2048, unit="px")
    bit_depth = gds.IntItem("ADC resolution", default=12, min=8, max=16, unit="bits")
    conversion_gain = gds.FloatItem(
        "Conversion gain", default=2.0, min=0.01, max=1_000.0, unit="e⁻/DN"
    )
    read_noise = gds.FloatItem(
        "Read noise", default=3.0, min=0.0, max=1_000.0, unit="e⁻"
    )
    offset = gds.FloatItem("Offset", default=100.0, min=0.0, unit="DN")
    prnu_percent = gds.FloatItem("PRNU", default=1.0, min=0.0, max=99.0, unit="%")
    dsnu = gds.FloatItem("DSNU", default=1.0, min=0.0, unit="DN")
    row_pattern = gds.FloatItem("Row pattern", default=3.0, min=0.0, unit="DN")
    column_pattern = gds.FloatItem("Column pattern", default=2.0, min=0.0, unit="DN")
    defective_percent = gds.FloatItem(
        "Defective pixels", default=0.1, min=0.0, max=100.0, unit="%"
    )
    serial_number = gds.IntItem(
        "Serial number",
        default=20261007,
        min=0,
        help=(
            "Fixes the sensor maps (PRNU, DSNU, defects, hot pixels): change it "
            "to simulate another camera of the same model"
        ),
    )
    _sensor_end = gds.EndGroup("Sensor")

    _dark = gds.BeginGroup("Dark current")
    dark_current = gds.FloatItem("Dark current", default=0.2, min=0.0, unit="e⁻/s")
    dark_nonuniformity_percent = gds.FloatItem(
        "Non-uniformity", default=0.0, min=0.0, max=99.0, unit="%"
    )
    hot_pixel_percent = gds.FloatItem(
        "Hot pixels", default=0.0, min=0.0, max=100.0, unit="%"
    )
    hot_pixel_factor = gds.FloatItem(
        "Hot-pixel factor", default=30.0, min=1.0, max=10_000.0
    )
    glow = gds.FloatItem("Amplifier glow", default=0.0, min=0.0, unit="e⁻/s")
    _dark_end = gds.EndGroup("Dark current")

    _tabs_end = gds.EndTabGroup("Settings")


def parse_exposures_ms(text: str) -> tuple[float, ...]:
    """Return the exposure times listed in a text, in milliseconds.

    Raises:
        ValueError: if the text does not list positive, finite numbers
    """
    try:
        values = tuple(float(item) for item in re.split(r"[,;\s]+", text.strip()))
    except ValueError:
        values = ()
    if not values or not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError(
            "Exposure times must be positive numbers in milliseconds, "
            "separated by commas"
        )
    return values


class CameraSimulator(PluginInstrument):
    """Scientific camera simulator.

    The serial number seeds the sensor: every frame of a session comes from
    the same pixels, while each frame draws new temporal noise.
    """

    live_interval_ms = 300

    def __init__(self) -> None:
        super().__init__(CameraSimulatorSettings())
        self._acquisition_count = 0
        self._noise_streams = itertools.count(LIVE_NOISE_STREAMS + 1)
        self._preview_streams = itertools.cycle(range(1, LIVE_NOISE_STREAMS + 1))

    @property
    def saturation_dn(self) -> int:
        """Return the largest value of the ADC."""
        return 2 ** int(self.settings.bit_depth) - 1

    def sensor_parameters(
        self,
        exposure_ms: float,
        frame_count: int,
        shutter_open: bool,
        noise_stream: int,
    ) -> CameraSimulationParameters:
        """Return the simulator parameters of one series of frames."""
        s = self.settings
        exposure_time_s = exposure_ms / 1_000.0
        return CameraSimulationParameters(
            shape=(int(s.height), int(s.width)),
            frame_count=frame_count,
            exposure_time_s=exposure_time_s,
            signal_electrons=(
                float(s.photoelectron_rate) * exposure_time_s if shutter_open else 0.0
            ),
            offset_dn=float(s.offset),
            conversion_gain_e_per_dn=float(s.conversion_gain),
            read_noise_e=float(s.read_noise),
            dark_current_e_per_s=float(s.dark_current),
            prnu_fraction=float(s.prnu_percent) / 100.0,
            dsnu_dn=float(s.dsnu),
            row_pattern_dn=float(s.row_pattern),
            column_pattern_dn=float(s.column_pattern),
            vignetting_fraction=float(s.vignetting_percent) / 100.0,
            dust_shadow_count=int(s.dust_shadow_count),
            dust_shadow_depth_fraction=float(s.dust_shadow_depth_percent) / 100.0,
            saturation_dn=float(self.saturation_dn),
            bit_depth=int(s.bit_depth),
            defective_pixel_fraction=float(s.defective_percent) / 100.0,
            seed=int(s.serial_number),
            dark_current_nonuniformity_fraction=(
                float(s.dark_nonuniformity_percent) / 100.0
            ),
            dark_hot_pixel_fraction=float(s.hot_pixel_percent) / 100.0,
            dark_hot_pixel_factor=float(s.hot_pixel_factor),
            amplifier_glow_e_per_s=float(s.glow),
            noise_stream=noise_stream,
        )

    def exposures_ms(self) -> tuple[float, ...]:
        """Return the exposure times of the next acquisition."""
        if self.settings.mode == "sequence":
            return parse_exposures_ms(self.settings.exposures_ms)
        return (float(self.settings.exposure_ms),)

    def preview(self) -> InstrumentFrame:
        """Return one frame at the exposure time of single mode.

        In sequence mode, the frame is taken at the longest exposure time,
        where saturation is most likely.
        """
        exposure_ms = max(self.exposures_ms())
        shutter_open = bool(self.settings.shutter_open)
        parameters = self.sensor_parameters(
            exposure_ms, 1, shutter_open, next(self._preview_streams)
        )
        frame = simulate_camera_frames(parameters).frames_dn[0]
        role = "Flat" if shutter_open else "Dark"
        image = create_image(f"{role} {exposure_ms:g} ms", frame.copy())
        saturated = 100.0 * np.count_nonzero(frame >= self.saturation_dn) / frame.size
        summary = (
            f"{role} frame, {exposure_ms:g} ms: mean {np.mean(frame):.1f} DN, "
            f"standard deviation {np.std(frame):.1f} DN, "
            f"{saturated:.2f} % saturated pixels"
        )
        return InstrumentFrame((image,), summary, (0.0, float(self.saturation_dn)))

    def acquire(self) -> InstrumentAcquisition:
        """Acquire the frames of single or sequence mode, with dark frames."""
        settings = self.settings
        exposures = self.exposures_ms()
        shutter_open = bool(settings.shutter_open)
        frame_count = int(settings.frame_count)
        dark_count = int(settings.dark_frame_count) if shutter_open else 0
        total_frames = frame_count * len(exposures) + dark_count
        pixels = total_frames * int(settings.width) * int(settings.height)
        if pixels > MAX_ACQUISITION_PIXELS:
            raise ValueError(
                f"This acquisition would create {pixels / 1e6:.1f} megapixels "
                f"(limit: {MAX_ACQUISITION_PIXELS / 1e6:g}): reduce the frame size "
                "or the number of frames"
            )
        images: list[ImageObj] = []
        if dark_count:
            longest = max(exposures)
            images.extend(
                series_images(
                    f"Dark {longest:g} ms",
                    self.sensor_parameters(
                        longest, dark_count, False, next(self._noise_streams)
                    ),
                    "dark",
                )
            )
        role = "flat" if shutter_open else "dark"
        for exposure_ms in exposures:
            images.extend(
                series_images(
                    f"{role.capitalize()} {exposure_ms:g} ms",
                    self.sensor_parameters(
                        exposure_ms,
                        frame_count,
                        shutter_open,
                        next(self._noise_streams),
                    ),
                    role,
                )
            )
        self._acquisition_count += 1
        return InstrumentAcquisition(
            f"Camera SN {settings.serial_number} - acquisition "
            f"{self._acquisition_count:03d}",
            images,
        )


__all__ = [
    "CAMERA_SIMULATOR_TOOL",
    "MAX_ACQUISITION_PIXELS",
    "CameraSimulator",
    "CameraSimulatorSettings",
    "parse_exposures_ms",
]
