"""Tests for the explicit Camera Alpha gate."""

from __future__ import annotations

import pytest

from scripts import check_alpha_gate
from scripts.check_alpha_gate import (
    ALPHA_MEMORY_MULTIPLIER,
    evaluate_memory_budget,
)


def _report(traced_bytes: int, rss_bytes: int) -> dict[str, object]:
    """Return the memory fields consumed by the gate evaluator."""
    return {
        "input_bytes": 100,
        "peak_incremental_bytes": traced_bytes,
        "peak_incremental_rss_bytes": rss_bytes,
    }


def test_alpha_memory_budget_accepts_both_measurements_at_limit() -> None:
    """Both independent memory measurements may reach the explicit limit."""
    result = evaluate_memory_budget(_report(300, 300))

    assert ALPHA_MEMORY_MULTIPLIER == 3.0
    assert result["passed"] is True
    assert result["limit_bytes"] == 300
    assert result["peak_incremental_input_multiplier"] == pytest.approx(3.0)
    assert result["peak_incremental_rss_input_multiplier"] == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("traced_bytes", "rss_bytes", "failed_measurement"),
    [(301, 299, "tracemalloc_passed"), (299, 301, "rss_passed")],
)
def test_alpha_memory_budget_rejects_either_measurement_above_limit(
    traced_bytes: int,
    rss_bytes: int,
    failed_measurement: str,
) -> None:
    """A regression seen by either memory instrument fails the gate."""
    result = evaluate_memory_budget(_report(traced_bytes, rss_bytes))

    assert result["passed"] is False
    assert result[failed_measurement] is False


@pytest.mark.parametrize(
    "report",
    [
        {
            "input_bytes": 0,
            "peak_incremental_bytes": 0,
            "peak_incremental_rss_bytes": 0,
        },
        {
            "input_bytes": 100,
            "peak_incremental_bytes": -1,
            "peak_incremental_rss_bytes": 0,
        },
    ],
)
def test_alpha_memory_budget_rejects_impossible_measurements(
    report: dict[str, object],
) -> None:
    """Invalid measurement reports cannot accidentally pass the gate."""
    with pytest.raises(ValueError):
        evaluate_memory_budget(report)


def test_alpha_gate_reports_benchmark_failure_as_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Benchmark exceptions produce a structured failed gate result."""
    monkeypatch.setattr(
        check_alpha_gate.subprocess,
        "run",
        lambda *args, **kwargs: check_alpha_gate.subprocess.CompletedProcess([], 0),
    )

    def fail_benchmark(configuration):
        raise RuntimeError("measurement failed")

    monkeypatch.setattr(check_alpha_gate, "run_benchmark", fail_benchmark)

    assert check_alpha_gate.main() == 1
    output = capsys.readouterr().out
    assert '"passed": false' in output
    assert '"stage": "memory"' in output
    assert '"error_type": "RuntimeError"' in output
