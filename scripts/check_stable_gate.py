"""Evaluate the fail-closed Camera Stable qualification gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parents[1]
DEFAULT_EVIDENCE_MANIFEST = PROJECT_ROOT / "qualification" / "stable-evidence.json"
LEGACY_RECIPE_ID = "org.datalab.camera-characterization:relative-dn-characterization"
SHA256 = re.compile(r"[0-9a-fA-F]{64}")


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


def _read_object(data: bytes, location: str, errors: list[dict[str, str]]) -> Mapping:
    """Read unambiguous UTF-8 JSON, including for method IDs used as keys."""

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique_keys)
    except (ValueError, RecursionError) as error:
        code = "manifest-invalid" if location == "manifest" else "artifact-invalid"
        _add_error(errors, code, f"Unable to read evidence JSON: {error}", location)
        return {}
    return _as_mapping(value, location, errors)


def _artifact_path(
    value: object,
    location: str,
    manifest_root: Path,
    errors: list[dict[str, str]],
) -> tuple[Path, str] | None:
    """Resolve a local evidence reference without accepting external targets."""
    reference = _as_mapping(value, location, errors)
    relative_path = _require_text(reference.get("path"), f"{location}.path", errors)
    expected_digest = _require_text(
        reference.get("sha256"), f"{location}.sha256", errors
    )
    if relative_path is None or expected_digest is None:
        return None
    if not SHA256.fullmatch(expected_digest):
        _add_error(
            errors,
            "invalid-sha256",
            "Expected a 64-character hexadecimal SHA-256 digest",
            f"{location}.sha256",
        )
        return None

    candidate_path = Path(relative_path)
    if candidate_path.anchor:
        _add_error(
            errors,
            "artifact-path-not-relative",
            "Evidence artifact paths must be relative to the manifest",
            f"{location}.path",
        )
        return None
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
        return None
    if not artifact_path.is_file():
        _add_error(
            errors,
            "artifact-not-found",
            f"Evidence artifact does not exist: {relative_path}",
            location,
        )
        return None
    if artifact_path.stat().st_nlink != 1:
        _add_error(
            errors,
            "artifact-hard-link",
            "Evidence artifacts must not have multiple hard links",
            f"{location}.path",
        )
        return None
    return artifact_path, expected_digest.lower()


@dataclass
class _Bundle:
    root: Path
    errors: list[dict[str, str]]
    archive_v1: bool = False
    verified_count: int = 0

    def verify(
        self, value: object, location: str, *, read_json: bool = False
    ) -> Mapping | None:
        """Check reviewed bytes; parse those same bytes for structured evidence."""
        try:
            reference = _artifact_path(value, location, self.root, self.errors)
            if reference is None:
                return None
            path, expected_digest = reference
            if not self.archive_v1 and path.stat().st_size == 0:
                _add_error(self.errors, "empty-artifact", "Evidence is empty", location)
                return None
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                if read_json:
                    data = stream.read()
                    digest.update(data)
                else:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
        except (OSError, RuntimeError, ValueError) as error:
            _add_error(self.errors, "artifact-unreadable", str(error), location)
            return None
        if digest.hexdigest() != expected_digest:
            _add_error(
                self.errors,
                "artifact-hash-mismatch",
                f"SHA-256 does not match the reviewed artifact: {path.name}",
                location,
            )
            return None
        self.verified_count += 1
        return _read_object(data, location, self.errors) if read_json else None


def _validate_campaign(
    campaign: Mapping, bundle: _Bundle, *, dark_only: bool = False
) -> Mapping:
    """Check acquisition metadata common to both dossier formats."""
    errors = bundle.errors
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
    no_flats = dark_only and all(
        type(acquisition.get(field)) is int and acquisition[field] == 0
        for field in ("flat_frame_count", "flat_level_count")
    )
    for field in ("dark_frame_count", "flat_frame_count", "flat_level_count"):
        if no_flats and field.startswith("flat_"):
            continue
        _require_positive_integer(
            acquisition.get(field), f"campaign.acquisition.{field}", errors
        )
    bundle.verify(campaign.get("artifact"), "campaign.artifact")
    bundle.verify(acquisition.get("protocol"), "campaign.acquisition.protocol")
    return acquisition


def _validate_review(review: Mapping, errors: list[dict[str, str]]) -> None:
    """The reviewer must explicitly declare independence and approval."""
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


def _expect(
    record: Mapping,
    field: str,
    expected: object,
    location: str,
    errors: list[dict[str, str]],
) -> None:
    """Compare a provenance field with the independently expected value."""
    if record.get(field) != expected or expected is None:
        _add_error(
            errors,
            field.replace("_", "-") + "-mismatch",
            f"{field} must match {expected!r}",
            f"{location}.{field}",
        )


def _passed(report: Mapping, location: str, errors: list[dict[str, str]]) -> None:
    if report.get("passed") is not True:
        _add_error(
            errors,
            "validation-not-passed",
            "The documented real-data validation must have passed",
            f"{location}.passed",
        )


def _validate_v1(manifest: Mapping, bundle: _Bundle) -> None:
    """Audit the original four artifacts under the original, frozen contract."""
    errors = bundle.errors
    _expect(manifest, "plugin_version", "0.1.0", "manifest", errors)
    _validate_campaign(
        _as_mapping(manifest.get("campaign"), "campaign", errors), bundle
    )
    validation = _as_mapping(manifest.get("validation"), "validation", errors)
    _passed(validation, "validation", errors)
    _expect(validation, "recipe_id", LEGACY_RECIPE_ID, "validation", errors)
    _expect(validation, "recipe_version", "1.1.0", "validation", errors)
    bundle.verify(validation.get("report"), "validation.report")
    review = _as_mapping(manifest.get("review"), "review", errors)
    _validate_review(review, errors)
    bundle.verify(review.get("report"), "review.report")


def _digest(reference: object) -> str | None:
    """References themselves must also pass _Bundle.verify."""
    value = reference.get("sha256") if isinstance(reference, Mapping) else None
    return value.lower() if isinstance(value, str) else None


def _candidate_scope(
    methods: list[str] | None, errors: list[dict[str, str]]
) -> tuple[str, dict[str, str]]:
    """Use the candidate checkout, never recipe versions asserted by a dossier."""
    import datalab_camera_characterization as plugin
    from datalab_camera_characterization.workflow.recipes import CAMERA_RECIPES

    source = PROJECT_ROOT / "src" / "datalab_camera_characterization" / "__init__.py"
    if Path(plugin.__file__).resolve() != source.resolve():
        _add_error(
            errors,
            "candidate-checkout-mismatch",
            "Install this checkout in editable mode before qualification",
            "candidate",
        )
    registry = {recipe.recipe_id: recipe.version for recipe in CAMERA_RECIPES}
    selected = list(registry) if methods is None else methods
    if (
        not selected
        or len(set(selected)) != len(selected)
        or set(selected) - registry.keys()
    ):
        _add_error(
            errors,
            "invalid-method-scope",
            "Select a nonempty set of distinct registered recipe IDs",
            "candidate",
        )
    return plugin.__version__, {
        key: registry[key] for key in selected if key in registry
    }


def _validate_method(
    report: Mapping, loc: str, provenance: Mapping, bundle: _Bundle
) -> None:
    """Validate a method report and both assessments of its results."""
    for field, expected in provenance.items():
        _expect(report, field, expected, loc, bundle.errors)
    _passed(report, loc, bundle.errors)
    for field in (
        "analyst",
        "environment",
        "parameters",
        "estimator",
        "population",
        "exclusions",
        "acceptance_criteria",
        "results",
        "repeatability",
    ):
        _require_text(report.get(field), f"{loc}.{field}", bundle.errors)
    for field, required in (
        (
            "independent_comparison",
            ("reference_method", "reference_results", "differences"),
        ),
        ("uncertainty_budget", ("sources", "propagation", "interval", "resolution")),
    ):
        attachment_loc = f"{loc}.{field}"
        attachment = bundle.verify(report.get(field), attachment_loc, read_json=True)
        if attachment is None:
            continue
        for key, expected in {
            **provenance,
            "population": report.get("population"),
        }.items():
            _expect(attachment, key, expected, attachment_loc, bundle.errors)
        for key in required:
            _require_text(attachment.get(key), f"{attachment_loc}.{key}", bundle.errors)
        if field == "independent_comparison":
            _passed(attachment, attachment_loc, bundle.errors)
            if attachment.get("independent") is not True:
                _add_error(
                    bundle.errors,
                    "comparison-not-independent",
                    "Require a reference independent of the plugin",
                    f"{attachment_loc}.independent",
                )


def _validate_v2(
    manifest: Mapping,
    bundle: _Bundle,
    plugin_version: str,
    wheel_sha256: str,
    methods: dict[str, str],
) -> None:
    """Bind each reviewed result to the same candidate, inputs and method."""
    errors = bundle.errors
    identity = {"plugin_version": plugin_version, "wheel_sha256": wheel_sha256}
    for field, expected in identity.items():
        _expect(manifest, field, expected, "manifest", errors)
    entries = _as_mapping(manifest.get("methods"), "methods", errors)
    if set(entries) != set(methods):
        _add_error(
            errors,
            "method-scope-mismatch",
            f"Evidence must cover exactly {sorted(methods)}",
            "methods",
        )
    if errors:
        return
    campaign = bundle.verify(manifest.get("campaign"), "campaign", read_json=True)
    if campaign is None:
        return
    acquisition = _validate_campaign(
        campaign,
        bundle,
        dark_only=set(methods) == {"org.datalab.camera-characterization:dark-current"},
    )
    if acquisition.get("linear_raw") is not True:
        _add_error(
            errors,
            "raw-required",
            "Require linear raw frames",
            "campaign.acquisition.linear_raw",
        )
    runs = acquisition.get("independent_run_count")
    if type(runs) is not int or runs < 2:
        _add_error(
            errors,
            "replication-required",
            "Require at least two independent acquisitions",
            "campaign.acquisition.independent_run_count",
        )

    authors = [acquisition.get("operator")]
    report_hashes = {}
    for recipe_id, version in methods.items():
        loc = f"methods.{recipe_id}"
        entry = _as_mapping(entries.get(recipe_id), loc, errors)
        _expect(entry, "recipe_version", version, loc, errors)
        report_hashes[recipe_id] = _digest(entry.get("report"))
        loc += ".report"
        report = bundle.verify(entry.get("report"), loc, read_json=True)
        if report is None:
            continue
        provenance = {
            **identity,
            "recipe_id": recipe_id,
            "recipe_version": version,
            "campaign_sha256": _digest(campaign.get("artifact")),
            "protocol_sha256": _digest(acquisition.get("protocol")),
        }
        _validate_method(report, loc, provenance, bundle)
        authors.append(report.get("analyst"))

    review = bundle.verify(manifest.get("review"), "review", read_json=True)
    if review is None:
        return
    _validate_review(review, errors)
    for field in ("qualification", "assessment"):
        _require_text(review.get(field), f"review.{field}", errors)
    for field, expected in {
        **identity,
        "campaign_record_sha256": _digest(manifest.get("campaign")),
        "reviewed_reports": report_hashes,
    }.items():
        _expect(review, field, expected, "review", errors)
    reviewer = review.get("reviewer_name")
    if isinstance(reviewer, str) and reviewer.strip().casefold() in {
        author.strip().casefold() for author in authors if isinstance(author, str)
    }:
        _add_error(
            errors,
            "review-not-independent",
            "The reviewer must not be the operator or analyst",
            "review.reviewer_name",
        )


def evaluate_stable_evidence(
    manifest_path: str | Path,
    *,
    wheel_sha256: str | None = None,
    methods: list[str] | None = None,
    archive_v1: bool = False,
) -> dict[str, Any]:
    """Check candidate evidence, or explicitly audit an immutable v1 archive."""
    path = Path(manifest_path)
    errors: list[dict[str, str]] = []
    bundle = _Bundle(path.parent, errors, archive_v1=archive_v1)
    gate = "camera-stable" if methods is None else "camera-method-scope"
    result = {
        "gate": "camera-archive-v1" if archive_v1 else gate,
        "manifest": str(path),
        "errors": errors,
    }
    try:
        manifest = _read_object(path.read_bytes(), "manifest", errors)
    except FileNotFoundError:
        _add_error(
            errors,
            "manifest-not-found",
            f"Missing evidence manifest: {path}",
            "manifest",
        )
    except OSError as error:
        _add_error(errors, "manifest-invalid", str(error), "manifest")
    else:
        schema = manifest.get("schema_version")
        if type(schema) is int and schema == 1 and archive_v1:
            _validate_v1(manifest, bundle)
        elif type(schema) is int and schema == 1:
            _add_error(
                errors,
                "historical-evidence-only",
                "Use --archive-v1; not evidence for the candidate",
                "schema_version",
            )
        elif type(schema) is int and schema == 2 and not archive_v1:
            if not wheel_sha256 or not SHA256.fullmatch(wheel_sha256):
                _add_error(
                    errors,
                    "candidate-digest-required",
                    "Supply the candidate build's SHA-256 independently",
                    "candidate",
                )
            else:
                try:
                    version, scope = _candidate_scope(methods, errors)
                except ImportError as error:
                    _add_error(errors, "candidate-unavailable", str(error), "candidate")
                else:
                    result.update(
                        plugin_version=version,
                        wheel_sha256=wheel_sha256.lower(),
                        methods=scope,
                    )
                    _validate_v2(manifest, bundle, version, wheel_sha256.lower(), scope)
        elif not errors:
            _add_error(
                errors,
                "unsupported-schema-version",
                "Expected schema_version 1 for archive or 2 for candidate",
                "schema_version",
            )
    result.update(
        passed=not errors,
        verified_artifact_count=bundle.verified_count,
        stage="archive" if archive_v1 else "evidence",
    )
    return result


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
    parser.add_argument(
        "--archive-v1",
        action="store_true",
        help="audit historical v1 evidence only; never run the Stable gate",
    )
    parser.add_argument(
        "--wheel-sha256",
        help="expected SHA-256 from the candidate build, not from its evidence",
    )
    parser.add_argument(
        "--method",
        action="append",
        help="assess this full recipe ID (repeatable); default: all methods",
    )
    arguments = parser.parse_args(argv)
    if arguments.archive_v1 and (arguments.method or arguments.wheel_sha256):
        parser.error("--archive-v1 cannot qualify a candidate")
    result = evaluate_stable_evidence(
        arguments.evidence,
        wheel_sha256=arguments.wheel_sha256,
        methods=arguments.method,
        archive_v1=arguments.archive_v1,
    )
    if not result["passed"] or arguments.archive_v1:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1

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
