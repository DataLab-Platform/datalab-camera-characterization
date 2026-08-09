"""Evaluate the fail-closed Camera Stable qualification gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parents[1]
DEFAULT_EVIDENCE_MANIFEST = PROJECT_ROOT / "qualification" / "stable-evidence.json"
EXPECTED_PLUGIN_VERSION = "0.1.0"
EXPECTED_RECIPE_ID = "org.datalab.camera-characterization:relative-dn-characterization"
EXPECTED_RECIPE_VERSION = "1.1.0"


def _add_error(
    errors: list[dict[str, str]],
    code: str,
    message: str,
    location: str,
) -> None:
    """Append one structured evidence error."""
    errors.append({"code": code, "message": message, "location": location})


def _as_mapping(
    value: object,
    location: str,
    errors: list[dict[str, str]],
) -> Mapping[str, object]:
    """Return a mapping or record a required-object error."""
    if isinstance(value, Mapping):
        return value
    _add_error(errors, "required-object", "Expected a JSON object", location)
    return {}


def _require_text(
    value: object,
    location: str,
    errors: list[dict[str, str]],
) -> str | None:
    """Return stripped required text or record an error."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    _add_error(errors, "required-text", "Expected non-empty text", location)
    return None


def _require_positive_integer(
    value: object,
    location: str,
    errors: list[dict[str, str]],
) -> int | None:
    """Return a positive integer or record an error."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    _add_error(
        errors,
        "required-positive-integer",
        "Expected a positive integer",
        location,
    )
    return None


def _require_iso_date(
    value: object,
    location: str,
    errors: list[dict[str, str]],
) -> None:
    """Record an error unless value is an ISO 8601 calendar date."""
    text = _require_text(value, location, errors)
    if text is None:
        return
    try:
        date.fromisoformat(text)
    except ValueError:
        _add_error(
            errors,
            "invalid-date",
            "Expected an ISO 8601 date in YYYY-MM-DD form",
            location,
        )


def _verify_artifact(
    value: object,
    location: str,
    manifest_root: Path,
    errors: list[dict[str, str]],
) -> bool:
    """Verify one local evidence artifact and its SHA-256 digest."""
    reference = _as_mapping(value, location, errors)
    relative_path = _require_text(reference.get("path"), f"{location}.path", errors)
    expected_digest = _require_text(
        reference.get("sha256"), f"{location}.sha256", errors
    )
    if relative_path is None or expected_digest is None:
        return False
    if len(expected_digest) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in expected_digest
    ):
        _add_error(
            errors,
            "invalid-sha256",
            "Expected a 64-character hexadecimal SHA-256 digest",
            f"{location}.sha256",
        )
        return False

    candidate_path = Path(relative_path)
    if candidate_path.is_absolute():
        _add_error(
            errors,
            "artifact-path-not-relative",
            "Evidence artifact paths must be relative to the manifest",
            f"{location}.path",
        )
        return False
    root = manifest_root.resolve()
    artifact_path = (root / candidate_path).resolve()
    try:
        artifact_path.relative_to(root)
    except ValueError:
        _add_error(
            errors,
            "artifact-path-outside-manifest",
            "Evidence artifacts must remain inside the manifest directory",
            f"{location}.path",
        )
        return False
    if not artifact_path.is_file():
        _add_error(
            errors,
            "artifact-not-found",
            f"Evidence artifact does not exist: {relative_path}",
            location,
        )
        return False
    if artifact_path.stat().st_nlink != 1:
        _add_error(
            errors,
            "artifact-hard-link",
            "Evidence artifacts must not have multiple hard links",
            f"{location}.path",
        )
        return False

    digest = hashlib.sha256()
    with artifact_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest.lower():
        _add_error(
            errors,
            "artifact-hash-mismatch",
            f"SHA-256 does not match the reviewed artifact: {relative_path}",
            location,
        )
        return False
    return True


def _validate_manifest(
    manifest: Mapping[str, object],
    manifest_root: Path,
    errors: list[dict[str, str]],
) -> int:
    """Validate Stable evidence fields and return the verified artifact count."""
    if manifest.get("schema_version") != 1:
        _add_error(
            errors,
            "unsupported-schema-version",
            "Stable evidence schema_version must be 1",
            "schema_version",
        )
    if manifest.get("plugin_version") != EXPECTED_PLUGIN_VERSION:
        _add_error(
            errors,
            "plugin-version-mismatch",
            f"plugin_version must be {EXPECTED_PLUGIN_VERSION}",
            "plugin_version",
        )

    campaign = _as_mapping(manifest.get("campaign"), "campaign", errors)
    if campaign.get("synthetic") is not False:
        _add_error(
            errors,
            "campaign-not-real",
            "Stable evidence must identify the campaign as non-synthetic",
            "campaign.synthetic",
        )
    _require_text(campaign.get("license"), "campaign.license", errors)

    camera = _as_mapping(campaign.get("camera"), "campaign.camera", errors)
    for field in ("manufacturer", "model", "sensor", "serial_number"):
        _require_text(camera.get(field), f"campaign.camera.{field}", errors)
    for field in ("bit_depth", "width", "height"):
        _require_positive_integer(camera.get(field), f"campaign.camera.{field}", errors)

    acquisition = _as_mapping(
        campaign.get("acquisition"), "campaign.acquisition", errors
    )
    _require_iso_date(
        acquisition.get("captured_at"), "campaign.acquisition.captured_at", errors
    )
    _require_text(acquisition.get("operator"), "campaign.acquisition.operator", errors)
    for field in ("dark_frame_count", "flat_frame_count", "flat_level_count"):
        _require_positive_integer(
            acquisition.get(field), f"campaign.acquisition.{field}", errors
        )

    validation = _as_mapping(manifest.get("validation"), "validation", errors)
    if validation.get("passed") is not True:
        _add_error(
            errors,
            "validation-not-passed",
            "The documented real-data validation must have passed",
            "validation.passed",
        )
    if validation.get("recipe_id") != EXPECTED_RECIPE_ID:
        _add_error(
            errors,
            "recipe-id-mismatch",
            f"recipe_id must be {EXPECTED_RECIPE_ID}",
            "validation.recipe_id",
        )
    if validation.get("recipe_version") != EXPECTED_RECIPE_VERSION:
        _add_error(
            errors,
            "recipe-version-mismatch",
            f"recipe_version must be {EXPECTED_RECIPE_VERSION}",
            "validation.recipe_version",
        )

    review = _as_mapping(manifest.get("review"), "review", errors)
    _require_text(review.get("reviewer_name"), "review.reviewer_name", errors)
    _require_text(review.get("affiliation"), "review.affiliation", errors)
    _require_text(
        review.get("conflict_of_interest"),
        "review.conflict_of_interest",
        errors,
    )
    _require_iso_date(review.get("reviewed_at"), "review.reviewed_at", errors)
    if review.get("independent") is not True:
        _add_error(
            errors,
            "review-not-independent",
            "Stable requires an explicitly independent scientific reviewer",
            "review.independent",
        )
    if review.get("decision") != "approved":
        _add_error(
            errors,
            "review-not-approved",
            "The independent scientific review decision must be approved",
            "review.decision",
        )

    artifact_references = (
        (campaign.get("artifact"), "campaign.artifact"),
        (acquisition.get("protocol"), "campaign.acquisition.protocol"),
        (validation.get("report"), "validation.report"),
        (review.get("report"), "review.report"),
    )
    return sum(
        _verify_artifact(value, location, manifest_root, errors)
        for value, location in artifact_references
    )


def evaluate_stable_evidence(manifest_path: str | Path) -> dict[str, Any]:
    """Evaluate documented real-data and independent-review evidence."""
    path = Path(manifest_path)
    errors: list[dict[str, str]] = []
    if not path.is_file():
        _add_error(
            errors,
            "manifest-not-found",
            f"Stable evidence manifest does not exist: {path}",
            "manifest",
        )
        return {
            "gate": "camera-stable",
            "passed": False,
            "stage": "evidence",
            "manifest": str(path),
            "verified_artifact_count": 0,
            "errors": errors,
        }

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _add_error(
            errors,
            "manifest-invalid",
            f"Unable to read Stable evidence JSON: {error}",
            "manifest",
        )
        value = {}
    manifest = _as_mapping(value, "manifest", errors)
    verified_artifact_count = _validate_manifest(manifest, path.parent, errors)
    passed = not errors
    return {
        "gate": "camera-stable",
        "passed": passed,
        "stage": "complete" if passed else "evidence",
        "manifest": str(path),
        "verified_artifact_count": verified_artifact_count,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    """Check Stable evidence, then preserve the executable Alpha gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "evidence",
        nargs="?",
        type=Path,
        default=DEFAULT_EVIDENCE_MANIFEST,
        help="path to stable-evidence.json",
    )
    arguments = parser.parse_args(argv)
    result = evaluate_stable_evidence(arguments.evidence)
    if not result["passed"]:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.check_alpha_gate"],
            cwd=PROJECT_ROOT,
            check=False,
        )
    except OSError as error:
        _add_error(
            result["errors"],
            "alpha-gate-launch-failed",
            f"Unable to launch the Alpha gate: {error}",
            "alpha",
        )
        result["passed"] = False
        result["stage"] = "alpha"
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    result["alpha_gate_returncode"] = completed.returncode
    result["passed"] = completed.returncode == 0
    result["stage"] = "complete" if result["passed"] else "alpha"
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
