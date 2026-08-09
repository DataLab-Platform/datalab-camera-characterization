"""Tests for the explicit characterization benchmark harness."""

import pytest

from benchmarks.benchmark_characterization import (
    BenchmarkConfiguration,
    run_benchmark,
)


def test_small_benchmark_reports_campaign_time_and_memory() -> None:
    """The harness runs a complete campaign without imposing host budgets."""
    configuration = BenchmarkConfiguration(
        height=8,
        width=10,
        frames_per_series=2,
        flat_levels=2,
        block_size=1,
    )

    report = run_benchmark(configuration)

    assert report["configuration"] == {
        "height": 8,
        "width": 10,
        "frames_per_series": 2,
        "flat_levels": 2,
        "block_size": 1,
        "repetitions": 1,
    }
    assert report["input_frame_count"] == 6
    assert report["input_bytes"] == 6 * 8 * 10 * 2
    assert report["elapsed_s_per_run"] > 0.0
    assert report["peak_incremental_bytes"] > 0
    assert report["response_slope_dn_per_s"] == pytest.approx(800.0)
