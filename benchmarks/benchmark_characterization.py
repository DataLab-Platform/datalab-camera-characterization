"""Benchmark relative characterization time and incremental memory."""

from __future__ import annotations

import argparse
import dataclasses
import gc
import json
import platform
import threading
import time
import tracemalloc
from typing import Sequence

import numpy as np
import psutil

from datalab_camera_characterization.core import (
    CameraExposureSeries,
    CameraValidationParameters,
    characterize_relative_dn,
)


@dataclasses.dataclass(frozen=True)
class BenchmarkConfiguration:
    """Shape and campaign size for one characterization benchmark."""

    height: int = 2_048
    width: int = 2_048
    frames_per_series: int = 4
    flat_levels: int = 3
    block_size: int = 2
    repetitions: int = 1

    def __post_init__(self) -> None:
        """Reject configurations that cannot produce a characterization."""
        for name, value in dataclasses.asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.frames_per_series < 2:
            raise ValueError("frames_per_series must be at least 2")
        if self.flat_levels < 2:
            raise ValueError("flat_levels must be at least 2")


class _PeakRssSampler:
    """Sample peak resident memory while a benchmark is running."""

    def __init__(self) -> None:
        self._process = psutil.Process()
        self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._sample,
            name="camera-benchmark-rss",
            daemon=True,
        )
        self.baseline_bytes = self._process.memory_info().rss
        self.peak_bytes = self.baseline_bytes

    def _record(self) -> None:
        """Record the current process resident set size."""
        self.peak_bytes = max(self.peak_bytes, self._process.memory_info().rss)

    def _sample(self) -> None:
        """Sample until the benchmark signals completion."""
        while not self._stopped.wait(0.005):
            self._record()

    def start(self) -> None:
        """Start sampling resident memory."""
        self._thread.start()

    def stop(self) -> None:
        """Stop sampling and capture the final resident-memory value."""
        self._record()
        self._stopped.set()
        self._thread.join()
        self._record()


def _series_frames(
    shape: tuple[int, int],
    frame_count: int,
    mean_dn: int,
) -> tuple[np.ndarray, ...]:
    """Allocate a contiguous uint16 series with deterministic temporal noise."""
    return tuple(
        np.full(shape, mean_dn + (-1 if index % 2 == 0 else 1), dtype=np.uint16)
        for index in range(frame_count)
    )


def _build_campaign(
    configuration: BenchmarkConfiguration,
) -> tuple[tuple[np.ndarray, ...], tuple[CameraExposureSeries, ...]]:
    """Build source arrays before starting incremental memory measurement."""
    shape = (configuration.height, configuration.width)
    dark_mean_dn = 100
    response_step_dn = 800
    dark = _series_frames(shape, configuration.frames_per_series, dark_mean_dn)
    flats = tuple(
        CameraExposureSeries(
            _series_frames(
                shape,
                configuration.frames_per_series,
                dark_mean_dn + response_step_dn * exposure_index,
            ),
            float(exposure_index),
        )
        for exposure_index in range(1, configuration.flat_levels + 1)
    )
    return dark, flats


def run_benchmark(configuration: BenchmarkConfiguration) -> dict[str, object]:
    """Run the benchmark and return a machine-readable measurement report."""
    dark, flats = _build_campaign(configuration)
    source_arrays: Sequence[np.ndarray] = (
        *dark,
        *(frame for series in flats for frame in series.frames_dn),
    )
    input_bytes = sum(frame.nbytes for frame in source_arrays)
    input_frame_count = len(source_arrays)
    parameters = CameraValidationParameters(saturation_dn=4_095.0)

    gc.collect()
    rss_sampler = _PeakRssSampler()
    tracemalloc.start()
    baseline_bytes = tracemalloc.get_traced_memory()[0]
    rss_sampler.start()
    started_at = time.perf_counter()
    try:
        for _ in range(configuration.repetitions):
            result = characterize_relative_dn(
                dark,
                flats,
                parameters,
                aggregation_block_size=configuration.block_size,
            )
        elapsed_s = time.perf_counter() - started_at
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        rss_sampler.stop()

    pixel_frames = configuration.height * configuration.width * input_frame_count
    return {
        "benchmark": "relative-dn-characterization",
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "configuration": dataclasses.asdict(configuration),
        "input_frame_count": input_frame_count,
        "input_bytes": input_bytes,
        "elapsed_s_total": elapsed_s,
        "elapsed_s_per_run": elapsed_s / configuration.repetitions,
        "input_megapixel_frames_per_s": (
            pixel_frames * configuration.repetitions / elapsed_s / 1_000_000.0
        ),
        "peak_incremental_bytes": peak_bytes - baseline_bytes,
        "baseline_rss_bytes": rss_sampler.baseline_bytes,
        "peak_rss_bytes": rss_sampler.peak_bytes,
        "peak_incremental_rss_bytes": (
            rss_sampler.peak_bytes - rss_sampler.baseline_bytes
        ),
        "memory_measurement": (
            "tracemalloc and sampled process RSS peaks after resident source allocation"
        ),
        "response_slope_dn_per_s": result.linear_fit_slope_dn_per_s,
    }


def _parse_arguments() -> BenchmarkConfiguration:
    """Parse command-line overrides for the representative campaign."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--height", type=int, default=2_048)
    parser.add_argument("--width", type=int, default=2_048)
    parser.add_argument("--frames-per-series", type=int, default=4)
    parser.add_argument("--flat-levels", type=int, default=3)
    parser.add_argument("--block-size", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=1)
    arguments = parser.parse_args()
    return BenchmarkConfiguration(
        height=arguments.height,
        width=arguments.width,
        frames_per_series=arguments.frames_per_series,
        flat_levels=arguments.flat_levels,
        block_size=arguments.block_size,
        repetitions=arguments.repetitions,
    )


def main() -> None:
    """Run the benchmark and print stable JSON suitable for archival."""
    print(json.dumps(run_benchmark(_parse_arguments()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
