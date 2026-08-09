# Camera Stable Gate

The Camera workflow is not Stable yet. Stable requires both a documented real
camera campaign and an independent scientific review. Synthetic truth, Desktop
qualification, and the verified DataLab-Web matrix remain necessary evidence,
but they do not satisfy these two requirements.

## Run The Gate

From the repository root, run:

```bash
python -m scripts.check_stable_gate
```

By default, the command expects
`qualification/stable-evidence.json`. It exits nonzero with the structured
error `manifest-not-found` while that reviewed evidence bundle is absent. A
different local manifest may be checked explicitly:

```bash
python -m scripts.check_stable_gate path/to/stable-evidence.json
```

The gate first checks the evidence bundle. Only a passing bundle starts the
existing executable Alpha gate, so Stable cannot bypass the full tests or the
fixed memory budget.

## Evidence Bundle

The JSON manifest uses `schema_version` 1 and is tied to Camera plugin 0.1.0
and relative-DN recipe 1.1.0. It references four artifacts:

1. The real camera campaign.
2. The acquisition protocol.
3. The real-data validation report.
4. The independent scientific review report.

Every artifact path must be relative to the manifest, remain inside its
directory, have no additional hard links, and include the SHA-256 of the
reviewed bytes. This permits a self-contained evidence directory or archive
without requiring the campaign to be shipped in the Python wheel.

The manifest has this structure; angle-bracket values and hashes are
placeholders, not qualification evidence:

```json
{
  "schema_version": 1,
  "plugin_version": "0.1.0",
  "campaign": {
    "artifact": {
      "path": "camera-campaign.h5",
      "sha256": "<64 hexadecimal characters>"
    },
    "synthetic": false,
    "license": "<dataset license or access terms>",
    "camera": {
      "manufacturer": "<manufacturer>",
      "model": "<model>",
      "sensor": "<sensor>",
      "serial_number": "<serial or documented redaction>",
      "bit_depth": 12,
      "width": 2048,
      "height": 2048
    },
    "acquisition": {
      "captured_at": "YYYY-MM-DD",
      "operator": "<operator>",
      "protocol": {
        "path": "acquisition-protocol.md",
        "sha256": "<64 hexadecimal characters>"
      },
      "dark_frame_count": 16,
      "flat_frame_count": 96,
      "flat_level_count": 6
    }
  },
  "validation": {
    "report": {
      "path": "validation-report.json",
      "sha256": "<64 hexadecimal characters>"
    },
    "passed": true,
    "recipe_id": "org.datalab.camera-characterization:relative-dn-characterization",
    "recipe_version": "1.1.0"
  },
  "review": {
    "report": {
      "path": "independent-review.md",
      "sha256": "<64 hexadecimal characters>"
    },
    "reviewer_name": "<reviewer>",
    "affiliation": "<independent affiliation>",
    "independent": true,
    "conflict_of_interest": "<declaration>",
    "decision": "approved",
    "reviewed_at": "YYYY-MM-DD"
  }
}
```

## Required Scientific Content

The acquisition protocol must document hardware identification, operating and
optical conditions, exposure and illumination schedule, dark and flat frame
roles, acquisition settings, raw-data handling, and dataset licensing or
access terms. Any redaction must be explicit and justified.

The validation report must record the exact input digest, plugin and recipe
versions, parameters, software environment, acceptance criteria, measured
results, uncertainty or repeatability considerations, exclusions, diagnostics,
and the final pass/fail decision. Criteria derived only from the deterministic
simulator are insufficient for real-data acceptance.

The review report must identify the reviewer and affiliation, declare
independence and conflicts of interest, describe the reviewed scope, assess the
protocol and interpretation, list required corrections, and state an explicit
final decision. The decision must be `approved` in both the report and the
manifest.

## Automation Boundary

The checker verifies required fields, version binding, local artifact
containment, SHA-256 integrity, declared real-data status, declared validation
success, and declared independent approval. It does not parse the scientific
claims inside the reports and cannot determine whether a camera campaign is
representative, whether tolerances are appropriate, or whether a reviewer is
genuinely independent. Those remain human responsibilities and must be
supported by the reviewed reports.

Passing this gate qualifies only the documented relative-DN scope and hardware
coverage in the evidence bundle. It does not establish EMVA 1288 compliance,
calibrated metrology, or validity for unreviewed sensor families.
