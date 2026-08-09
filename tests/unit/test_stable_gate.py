"""Tests for the fail-closed Camera Stable evidence gate."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import check_stable_gate
from scripts.check_stable_gate import evaluate_stable_evidence


def _artifact(root: Path, name: str, content: bytes) -> dict[str, str]:
    """Create one evidence artifact and return its manifest reference."""
    path = root / name
    path.write_bytes(content)
    return {
        "path": name,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _write_valid_manifest(tmp_path: Path) -> Path:
    """Write a complete fictional evidence set for structural gate tests."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "plugin_version": "0.1.0",
        "campaign": {
            "artifact": _artifact(tmp_path, "campaign.h5", b"real camera frames"),
            "synthetic": False,
            "license": "CC-BY-4.0",
            "camera": {
                "manufacturer": "Example Instruments",
                "model": "Documented Camera",
                "sensor": "Documented Sensor",
                "serial_number": "REDACTED-WITH-JUSTIFICATION",
                "bit_depth": 12,
                "width": 640,
                "height": 480,
            },
            "acquisition": {
                "captured_at": "2026-08-09",
                "operator": "Qualified Operator",
                "protocol": _artifact(
                    tmp_path,
                    "acquisition-protocol.md",
                    b"documented acquisition protocol",
                ),
                "dark_frame_count": 16,
                "flat_frame_count": 96,
                "flat_level_count": 6,
            },
        },
        "validation": {
            "report": _artifact(
                tmp_path,
                "validation-report.json",
                b'{"passed": true}',
            ),
            "passed": True,
            "recipe_id": (
                "org.datalab.camera-characterization:relative-dn-characterization"
            ),
            "recipe_version": "1.1.0",
        },
        "review": {
            "report": _artifact(
                tmp_path,
                "independent-review.md",
                b"independent scientific review",
            ),
            "reviewer_name": "Independent Reviewer",
            "affiliation": "External Laboratory",
            "independent": True,
            "conflict_of_interest": "No conflict declared",
            "decision": "approved",
            "reviewed_at": "2026-08-09",
        },
    }
    manifest_path = tmp_path / "stable-evidence.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_stable_gate_accepts_complete_real_reviewed_evidence(tmp_path: Path) -> None:
    """A complete, hashed, real campaign and independent approval may pass."""
    result = evaluate_stable_evidence(_write_valid_manifest(tmp_path))

    assert result["passed"] is True
    assert result["stage"] == "complete"
    assert result["verified_artifact_count"] == 4
    assert result["errors"] == []


def test_stable_gate_fails_closed_without_evidence(tmp_path: Path) -> None:
    """The repository cannot claim Stable while its evidence is absent."""
    result = evaluate_stable_evidence(tmp_path / "missing.json")

    assert result["passed"] is False
    assert result["stage"] == "evidence"
    assert {error["code"] for error in result["errors"]} == {"manifest-not-found"}


@pytest.mark.parametrize(
    ("section", "field", "value", "code"),
    [
        ("campaign", "synthetic", True, "campaign-not-real"),
        ("review", "independent", False, "review-not-independent"),
        ("review", "decision", "changes-requested", "review-not-approved"),
        ("validation", "passed", False, "validation-not-passed"),
    ],
)
def test_stable_gate_rejects_unqualified_evidence(
    tmp_path: Path,
    section: str,
    field: str,
    value: object,
    code: str,
) -> None:
    """Scientific and review requirements are mandatory, not advisory."""
    manifest_path = _write_valid_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[section][field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = evaluate_stable_evidence(manifest_path)

    assert result["passed"] is False
    assert code in {error["code"] for error in result["errors"]}


def test_stable_gate_rejects_artifact_hash_drift(tmp_path: Path) -> None:
    """Reviewed bytes cannot change after their digest was recorded."""
    manifest_path = _write_valid_manifest(tmp_path)
    (tmp_path / "campaign.h5").write_bytes(b"changed after review")

    result = evaluate_stable_evidence(manifest_path)

    assert result["passed"] is False
    assert "artifact-hash-mismatch" in {error["code"] for error in result["errors"]}


def test_stable_gate_rejects_artifact_outside_manifest_directory(
    tmp_path: Path,
) -> None:
    """Traversal and external symlink targets cannot escape the evidence bundle."""
    bundle = tmp_path / "bundle"
    manifest_path = _write_valid_manifest(bundle)
    external_path = tmp_path / "external.h5"
    external_path.write_bytes(b"real camera frames")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["campaign"]["artifact"]["path"] = "../external.h5"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = evaluate_stable_evidence(manifest_path)

    assert result["passed"] is False
    assert "artifact-path-outside-manifest" in {
        error["code"] for error in result["errors"]
    }


def test_stable_gate_rejects_hard_linked_artifact(tmp_path: Path) -> None:
    """An internal path cannot borrow an inode from outside the evidence bundle."""
    bundle = tmp_path / "bundle"
    manifest_path = _write_valid_manifest(bundle)
    campaign_path = bundle / "campaign.h5"
    external_path = tmp_path / "external.h5"
    external_path.write_bytes(campaign_path.read_bytes())
    campaign_path.unlink()
    os.link(external_path, campaign_path)

    result = evaluate_stable_evidence(manifest_path)

    assert result["passed"] is False
    assert "artifact-hard-link" in {error["code"] for error in result["errors"]}


def test_stable_gate_cli_stops_before_alpha_without_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing human evidence fails before running the expensive Alpha gate."""

    def unexpected_alpha(*args, **kwargs):
        raise AssertionError("Alpha gate must not run without Stable evidence")

    monkeypatch.setattr(check_stable_gate.subprocess, "run", unexpected_alpha)

    assert check_stable_gate.main([str(tmp_path / "missing.json")]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] is False
    assert result["stage"] == "evidence"


def test_stable_gate_cli_preserves_alpha_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Structurally valid evidence cannot bypass the established Alpha gate."""
    calls: list[list[str]] = []

    def pass_alpha(command, **kwargs):
        calls.append(command)
        return check_stable_gate.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(check_stable_gate.subprocess, "run", pass_alpha)

    assert check_stable_gate.main([str(_write_valid_manifest(tmp_path))]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] is True
    assert result["alpha_gate_returncode"] == 0
    assert calls == [
        [check_stable_gate.sys.executable, "-m", "scripts.check_alpha_gate"]
    ]


def test_stable_gate_cli_reports_alpha_launch_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unavailable Alpha subprocess produces a structured failed result."""

    def fail_alpha(command, **kwargs):
        raise OSError("Python executable unavailable")

    monkeypatch.setattr(check_stable_gate.subprocess, "run", fail_alpha)

    assert check_stable_gate.main([str(_write_valid_manifest(tmp_path))]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] is False
    assert result["stage"] == "alpha"
    assert {error["code"] for error in result["errors"]} == {"alpha-gate-launch-failed"}
