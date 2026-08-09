"""Regenerate the packaged synthetic Camera quickstart workspace."""

from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from datalab.env import execenv
from datalab.gui.main import DLMainWindow
from datalab.objectmodel import get_uuid
from datalab.utils.qthelpers import datalab_app_context
from sigima.objects import ImageObj, create_image

from datalab_camera_characterization import PLUGIN_ID
from datalab_camera_characterization.core import (
    CameraSimulationParameters,
    metadata_key,
    simulate_camera_frames,
)
from datalab_camera_characterization.workflow import EXPOSURE_TIME_METADATA_KEY

OUTPUT_FILE = (
    Path(__file__).parents[1]
    / "src"
    / "datalab_camera_characterization"
    / "examples"
    / "camera_quickstart.h5"
)
FRAME_SHAPE = (64, 64)
FRAMES_PER_SERIES = 4
FLAT_EXPOSURES_S = (0.005, 0.01, 0.02, 0.04)
PHOTOELECTRON_RATE_E_PER_S = 60_000.0
SIMULATION_SEED = 20260809
QUICKSTART_UUID_NAMESPACE = uuid5(
    NAMESPACE_URL,
    f"https://datalab-platform.com/plugins/{PLUGIN_ID}/quickstart",
)


def _stable_uuid(local_id: str) -> str:
    """Return a deterministic UUID for one quickstart group or image."""
    return str(uuid5(QUICKSTART_UUID_NAMESPACE, local_id))


def _simulate_series(
    title_prefix: str,
    exposure_time_s: float,
    signal_electrons: float,
) -> tuple[ImageObj, ...]:
    """Return one deterministic synthetic acquisition series."""
    parameters = CameraSimulationParameters(
        shape=FRAME_SHAPE,
        frame_count=FRAMES_PER_SERIES,
        exposure_time_s=exposure_time_s,
        signal_electrons=signal_electrons,
        offset_dn=100.0,
        conversion_gain_e_per_dn=2.0,
        read_noise_e=3.0,
        dark_current_e_per_s=0.2,
        prnu_fraction=0.01,
        dsnu_dn=1.0,
        saturation_dn=4_095.0,
        bit_depth=12,
        defective_pixel_fraction=0.0,
        seed=SIMULATION_SEED,
    )
    result = simulate_camera_frames(parameters)
    images: list[ImageObj] = []
    for index, frame in enumerate(result.frames_dn, start=1):
        image = create_image(f"{title_prefix} {index:02d}", frame.copy())
        image.set_metadata_option(
            "uuid",
            _stable_uuid(f"image/{title_prefix.casefold()}/{index}"),
        )
        image.metadata[metadata_key("synthetic")] = True
        image.metadata[metadata_key("simulation_seed")] = SIMULATION_SEED
        image.metadata[metadata_key("signal_electrons")] = signal_electrons
        if signal_electrons > 0.0:
            image.metadata[EXPOSURE_TIME_METADATA_KEY] = exposure_time_s
        images.append(image)
    return tuple(images)


def generate_quickstart(output_file: Path = OUTPUT_FILE) -> Path:
    """Write the deterministic Camera campaign as a native DataLab workspace."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    dark_images = _simulate_series("Dark", max(FLAT_EXPOSURES_S), 0.0)
    flat_series = tuple(
        (
            exposure_time_s,
            _simulate_series(
                f"Flat {exposure_time_s * 1_000:g} ms",
                exposure_time_s,
                PHOTOELECTRON_RATE_E_PER_S * exposure_time_s,
            ),
        )
        for exposure_time_s in FLAT_EXPOSURES_S
    )

    with (
        execenv.context(unattended=True),
        datalab_app_context(exec_loop=False),
    ):
        window = DLMainWindow(console=False)
        try:
            dark_group = window.imagepanel.add_group("Dark frames")
            for image in dark_images:
                window.imagepanel.add_object(
                    image,
                    group_id=get_uuid(dark_group),
                    set_current=False,
                )
            dark_group.uuid = _stable_uuid("group/dark")
            for exposure_time_s, images in flat_series:
                group = window.imagepanel.add_group(
                    f"Flat frames - {exposure_time_s * 1_000:g} ms"
                )
                for image in images:
                    window.imagepanel.add_object(
                        image,
                        group_id=get_uuid(group),
                        set_current=False,
                    )
                group.uuid = _stable_uuid(f"group/flat/{exposure_time_s:g}")
            window.save_h5_workspace(str(output_file))
        finally:
            window.set_modified(False)
            window.close()
    return output_file


if __name__ == "__main__":
    print(generate_quickstart())
