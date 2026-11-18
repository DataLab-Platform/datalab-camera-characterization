"""Tests for the fail-closed Camera Stable evidence gate."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from datalab_camera_characterization import __version__
from scripts import check_stable_gate
from scripts.check_stable_gate import evaluate_stable_evidence

TEMPLATES = Path(__file__).parents[2] / "doc" / "qualification-templates"
WHEEL = hashlib.sha256(b"structural test fixture, not a wheel").hexdigest()
DARK = "org.datalab.camera-characterization:dark-current"


def _artifact(root: Path, name: str, content: bytes) -> dict[str, str]:
    """Create one evidence artifact and return its manifest reference."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "path": name,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _write_v1_manifest(tmp_path: Path) -> Path:
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


def _template(name):
    return json.loads((TEMPLATES / f"{name}.template.json").read_text(encoding="utf-8"))


def _write_v2_manifest(root, *, edit=None, changes=None, dark_only=False):
    """Fill copies of the shipping worksheets; never write a repository dossier."""
    manifest_path = _write_v1_manifest(root)
    legacy = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = _template("stable-evidence")
    candidate = {"plugin_version": __version__, "wheel_sha256": WHEEL}
    manifest.update(candidate)
    campaign = _template("campaign-record")
    campaign.update(legacy["campaign"])
    acq = campaign["acquisition"]
    acq.update(linear_raw=True, independent_run_count=2)
    if dark_only:
        manifest["methods"] = {DARK: manifest["methods"][DARK]}
        acq.update(flat_frame_count=0, flat_level_count=0)

    def save(role, name, document):
        if role == edit:
            document.update(changes)
        return _artifact(root, name, json.dumps(document).encode())

    if edit == "acquisition":
        acq.update(changes)
    manifest["campaign"] = save("campaign", manifest["campaign"]["path"], campaign)
    reviewed = {}
    for recipe_id, entry in manifest["methods"].items():
        scope = {
            **candidate,
            "recipe_id": recipe_id,
            "recipe_version": entry["recipe_version"],
            "campaign_sha256": campaign["artifact"]["sha256"],
            "protocol_sha256": acq["protocol"]["sha256"],
            "population": "mask and frame IDs in test ledger",
        }
        name = entry["report"]["path"]
        report = _template("method-report")
        for field in (
            "analyst",
            "environment",
            "parameters",
            "estimator",
            "exclusions",
            "acceptance_criteria",
            "results",
            "repeatability",
        ):
            report[field] = f"test {field}"
        report.update(scope, passed=True)
        budget = _template("uncertainty-budget")
        budget.update(
            scope,
            sources="test sources",
            propagation="test propagation",
            interval="test interval",
            resolution="test resolution",
        )
        comparison = _template("independent-comparison")
        comparison.update(
            scope,
            independent=True,
            passed=True,
            reference_method="test reference",
            reference_results="test values",
            differences="test differences",
        )
        for field, document in (
            ("independent_comparison", comparison),
            ("uncertainty_budget", budget),
        ):
            report[field] = save(field, name.replace("report", field), document)
        entry["report"] = save("report", name, report)
        reviewed[recipe_id] = entry["report"]["sha256"]
    review = _template("independent-review")
    review.update({k: v for k, v in legacy["review"].items() if k != "report"})
    review.update(
        candidate,
        campaign_record_sha256=manifest["campaign"]["sha256"],
        reviewed_reports=reviewed,
        qualification="test qualifications",
        assessment="test assessment",
    )
    manifest["review"] = save("review", "independent-review.json", review)
    if edit == "manifest":
        manifest.update(changes)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_stable_gate_archives_without_qualifying_candidate(tmp_path: Path) -> None:
    """Historical dossiers still verify without edits, but only as archives."""
    path = _write_v1_manifest(tmp_path)
    assert not evaluate_stable_evidence(path, wheel_sha256=WHEEL)["passed"]
    result = evaluate_stable_evidence(path, archive_v1=True)

    assert result["passed"] is True
    assert result["stage"] == "archive"
    assert result["gate"] == "camera-archive-v1"
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
        ("validation", "recipe_version", "1.1.1", "recipe-version-mismatch"),
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
    manifest_path = _write_v1_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[section][field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = evaluate_stable_evidence(manifest_path, archive_v1=True)

    assert result["passed"] is False
    assert code in {error["code"] for error in result["errors"]}


def test_stable_gate_rejects_artifact_hash_drift(tmp_path: Path) -> None:
    """Reviewed bytes cannot change after their digest was recorded."""
    manifest_path = _write_v1_manifest(tmp_path)
    (tmp_path / "campaign.h5").write_bytes(b"changed after review")

    result = evaluate_stable_evidence(manifest_path, archive_v1=True)

    assert result["passed"] is False
    assert "artifact-hash-mismatch" in {error["code"] for error in result["errors"]}


def test_stable_gate_rejects_artifact_outside_manifest_directory(
    tmp_path: Path,
) -> None:
    """Traversal and external symlink targets cannot escape the evidence bundle."""
    bundle = tmp_path / "bundle"
    manifest_path = _write_v1_manifest(bundle)
    external_path = tmp_path / "external.h5"
    external_path.write_bytes(b"real camera frames")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["campaign"]["artifact"]["path"] = "../external.h5"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = evaluate_stable_evidence(manifest_path, archive_v1=True)

    assert result["passed"] is False
    assert "artifact-path-outside-manifest" in {
        error["code"] for error in result["errors"]
    }


def test_stable_gate_rejects_hard_linked_artifact(tmp_path: Path) -> None:
    """An internal path cannot borrow an inode from outside the evidence bundle."""
    bundle = tmp_path / "bundle"
    manifest_path = _write_v1_manifest(bundle)
    campaign_path = bundle / "campaign.h5"
    external_path = tmp_path / "external.h5"
    external_path.write_bytes(campaign_path.read_bytes())
    campaign_path.unlink()
    os.link(external_path, campaign_path)

    result = evaluate_stable_evidence(manifest_path, archive_v1=True)

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

    archive = str(_write_v1_manifest(tmp_path))
    assert check_stable_gate.main([archive]) == 1
    assert not json.loads(capsys.readouterr().out)["passed"]
    assert check_stable_gate.main(["--archive-v1", archive]) == 0
    assert json.loads(capsys.readouterr().out)["gate"] == "camera-archive-v1"


def test_stable_gate_requires_external_pin_and_exact_scope(tmp_path: Path) -> None:
    path = _write_v2_manifest(tmp_path, dark_only=True)
    assert not evaluate_stable_evidence(path, methods=[DARK])["passed"]
    assert not evaluate_stable_evidence(path, wheel_sha256="b" * 64, methods=[DARK])[
        "passed"
    ]
    for methods in (None, [], [DARK, DARK], ["unknown"]):
        assert not evaluate_stable_evidence(path, wheel_sha256=WHEEL, methods=methods)[
            "passed"
        ]
    result = evaluate_stable_evidence(path, wheel_sha256=WHEEL, methods=[DARK])
    assert result["passed"] and result["gate"] == "camera-method-scope"
    assert result["methods"] == {DARK: "1.0.0"}


@pytest.mark.parametrize(
    ("edit", "changes", "code"),
    [
        ("manifest", {"plugin_version": "0.1.0"}, "plugin-version-mismatch"),
        ("campaign", {"synthetic": True}, "campaign-not-real"),
        ("acquisition", {"linear_raw": False}, "raw-required"),
        ("acquisition", {"independent_run_count": 1}, "replication-required"),
        ("acquisition", {"flat_frame_count": 8}, "required-positive-integer"),
        ("report", {"plugin_version": "0.1.0"}, "plugin-version-mismatch"),
        ("report", {"recipe_version": "1.0.1"}, "recipe-version-mismatch"),
        ("report", {"recipe_id": "another-recipe"}, "recipe-id-mismatch"),
        ("report", {"campaign_sha256": "a" * 64}, "campaign-sha256-mismatch"),
        ("report", {"protocol_sha256": "a" * 64}, "protocol-sha256-mismatch"),
        ("report", {"uncertainty_budget": None}, "required-object"),
        ("report", {"passed": False}, "validation-not-passed"),
        ("uncertainty_budget", {"wheel_sha256": "a" * 64}, "wheel-sha256-mismatch"),
        (
            "independent_comparison",
            {"population": "different ROI"},
            "population-mismatch",
        ),
        (
            "independent_comparison",
            {"independent": False},
            "comparison-not-independent",
        ),
        ("independent_comparison", {"passed": False}, "validation-not-passed"),
        ("review", {"reviewed_reports": {DARK: "a" * 64}}, "reviewed-reports-mismatch"),
        (
            "review",
            {"campaign_record_sha256": "a" * 64},
            "campaign-record-sha256-mismatch",
        ),
        ("review", {"decision": "pending"}, "review-not-approved"),
        ("review", {"reviewer_name": " TEST ANALYST "}, "review-not-independent"),
    ],
)
def test_stable_gate_rejects_rehashed_but_inapplicable_evidence(
    tmp_path, edit, changes, code
):
    """Even internally consistent artifact hashes cannot transfer a decision."""
    path = _write_v2_manifest(tmp_path, edit=edit, changes=changes, dark_only=True)
    result = evaluate_stable_evidence(path, wheel_sha256=WHEEL, methods=[DARK])
    assert not result["passed"]
    assert code in {err["code"] for err in result["errors"]}


def test_blank_template_is_not_evidence():
    result = evaluate_stable_evidence(
        TEMPLATES / "stable-evidence.template.json", wheel_sha256=WHEEL
    )
    assert not result["passed"] and not result["verified_artifact_count"]


@pytest.mark.parametrize("alpha_status", [0, 1])
def test_stable_gate_cli_preserves_alpha_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    alpha_status: int,
) -> None:
    """Structurally valid evidence cannot bypass the established Alpha gate."""
    calls: list[list[str]] = []

    def run_alpha(command, **kwargs):
        calls.append(command)
        return check_stable_gate.subprocess.CompletedProcess(command, alpha_status)

    monkeypatch.setattr(check_stable_gate.subprocess, "run", run_alpha)

    assert (
        check_stable_gate.main(
            [str(_write_v2_manifest(tmp_path)), "--wheel-sha256", WHEEL]
        )
        == alpha_status
    )
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] == (alpha_status == 0)
    assert result["alpha_gate_returncode"] == alpha_status
    assert result["verified_artifact_count"] == 13
    assert result["gate"] == "camera-stable"
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

    assert (
        check_stable_gate.main(
            [str(_write_v2_manifest(tmp_path)), "--wheel-sha256", WHEEL]
        )
        == 1
    )
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] is False
    assert result["stage"] == "alpha"
    assert {error["code"] for error in result["errors"]} == {"alpha-gate-launch-failed"}
