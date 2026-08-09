"""Run the Camera Alpha qualification gate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from benchmarks.benchmark_characterization import (
    BenchmarkConfiguration,
    run_benchmark,
)

PROJECT_ROOT = Path(__file__).parents[1]
ALPHA_MEMORY_MULTIPLIER = 3.0
ALPHA_BENCHMARK_CONFIGURATION = BenchmarkConfiguration(repetitions=3)


def evaluate_memory_budget(report: dict[str, object]) -> dict[str, object]:
    """Evaluate traced and resident peaks against the Alpha memory budget."""
    input_bytes = int(report["input_bytes"])
    traced_bytes = int(report["peak_incremental_bytes"])
    rss_bytes = int(report["peak_incremental_rss_bytes"])
    if input_bytes <= 0:
        raise ValueError("input_bytes must be positive")
    if traced_bytes < 0 or rss_bytes < 0:
        raise ValueError("incremental memory measurements must be non-negative")
    limit_bytes = int(input_bytes * ALPHA_MEMORY_MULTIPLIER)
    traced_passed = traced_bytes <= limit_bytes
    rss_passed = rss_bytes <= limit_bytes
    return {
        "passed": traced_passed and rss_passed,
        "input_bytes": input_bytes,
        "limit_bytes": limit_bytes,
        "limit_input_multiplier": ALPHA_MEMORY_MULTIPLIER,
        "peak_incremental_bytes": traced_bytes,
        "peak_incremental_input_multiplier": traced_bytes / input_bytes,
        "tracemalloc_passed": traced_passed,
        "peak_incremental_rss_bytes": rss_bytes,
        "peak_incremental_rss_input_multiplier": rss_bytes / input_bytes,
        "rss_passed": rss_passed,
    }


def main() -> int:
    """Run tests and the representative memory benchmark."""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if completed.returncode:
        print(
            json.dumps(
                {
                    "gate": "camera-alpha",
                    "passed": False,
                    "stage": "tests",
                    "test_returncode": completed.returncode,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return completed.returncode

    try:
        report = run_benchmark(ALPHA_BENCHMARK_CONFIGURATION)
        memory = evaluate_memory_budget(report)
    except Exception as error:  # pylint: disable=broad-except
        print(
            json.dumps(
                {
                    "gate": "camera-alpha",
                    "passed": False,
                    "stage": "memory",
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    passed = bool(memory["passed"])
    print(
        json.dumps(
            {
                "gate": "camera-alpha",
                "passed": passed,
                "stage": "complete" if passed else "memory",
                "memory": memory,
                "benchmark": report,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
