# Qualification

[← Documentation index](README.md)

The plugin is **Alpha**: it is validated on synthetic data with known truth, in DataLab Desktop and DataLab-Web. Stable also needs a documented real camera campaign and an independent scientific review. None of these steps is metrological validation or an EMVA 1288 claim.

## Synthetic Validation

`tests/validation` compares each method with the simulator truth. The tolerances of the other methods are in the Demonstration sections of [Photon transfer curve](photon-transfer.md#demonstration) and [Dark current and hot pixels](dark-current.md#demonstration).

For the relative characterization, one sensor of 64 × 64 pixels gives one dark series and six flat levels of 24 frames. The test requires:

- response slope within 0.5 %, dark temporal noise within 2 %;
- fitted means within 0.5 % and 0.2 DN, fit residuals below 0.2 DN;
- the last, deliberately clipped level excluded from the fit and found as the saturation onset.

The expected values come from the simulator settings and its exact PRNU map:

```text
expected_slope_dn_per_s = photoelectron_flux_per_s * mean(prnu_gain_map) / conversion_gain_e_per_dn
expected_dark_noise_dn = sqrt((read_noise_e / gain_e_per_dn)**2 + 1/12)
```

A noiseless campaign checks the DSNU-like and PRNU-like maps against the truth maps. Other tests cover invalid campaigns (missing series, too few frames or levels, wrong shapes, types or values, unordered exposures) and their stable diagnostic codes.

`tests/integration` builds the wheel, installs it in a temporary folder and loads the plugin through its entry point. It checks hot reload, then saves and reloads a characterized quickstart in a DataLab workspace, with its UUIDs, provenance and metrics table.

## Alpha Gate

```bash
python -m scripts.check_alpha_gate
```

The gate runs the full test suite, then a fixed memory campaign: 16 resident `uint16` images of 2048 × 2048 pixels (4 dark frames and 3 flat levels of 4 frames, 128 MiB), with a block size of 2, three times. Both incremental peaks, traced by `tracemalloc` and sampled from the process RSS, must stay at or below 384 MiB, three times the input size. The command exits nonzero on failure and prints a JSON report.

The reference run measured 336.08 MiB traced and 337.00 MiB RSS, 2.63 times the input (Windows, CPython 3.9.10, NumPy 2.0.2). Raising the limit needs a new documented baseline and a review. Elapsed time is recorded but not checked.

## Benchmark

```bash
python -m benchmarks.benchmark_characterization
```

The benchmark uses the same 2048 × 2048 campaign and reports time, throughput and incremental memory in JSON. It is not collected by pytest. A reference run on Windows with CPython 3.9.10 and NumPy 2.0.2 gave:

| Block size | Time | Input throughput | Incremental peak |
| ---: | ---: | ---: | ---: |
| 1 | 2.974 s | 22.57 MP-frames/s | 264.04 MiB |
| 2 | 2.260 s | 29.69 MP-frames/s | 336.08 MiB |

These are single-run observations, not portable limits.

## Stable Gate

```bash
python -m scripts.check_stable_gate [path/to/stable-evidence.json]
```

The gate checks an evidence bundle, then runs the Alpha gate. The default manifest is `qualification/stable-evidence.json`. It does not exist yet, so the command exits with `manifest-not-found` and the project stays Alpha.

The manifest (`schema_version` 1) is bound to plugin 0.1.0 and relative-DN recipe 1.1.0. It references four artifacts by a path relative to the manifest and the SHA-256 of the reviewed bytes: the real camera campaign, the acquisition protocol, the validation report and the independent review. Paths must stay inside the manifest folder and have no other hard links. Angle-bracket values and hashes below are placeholders:

```json
{
  "schema_version": 1,
  "plugin_version": "0.1.0",
  "campaign": {
    "artifact": {"path": "camera-campaign.h5", "sha256": "<64 hexadecimal characters>"},
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
      "protocol": {"path": "acquisition-protocol.md", "sha256": "<64 hexadecimal characters>"},
      "dark_frame_count": 16,
      "flat_frame_count": 96,
      "flat_level_count": 6
    }
  },
  "validation": {
    "report": {"path": "validation-report.json", "sha256": "<64 hexadecimal characters>"},
    "passed": true,
    "recipe_id": "org.datalab.camera-characterization:relative-dn-characterization",
    "recipe_version": "1.1.0"
  },
  "review": {
    "report": {"path": "independent-review.md", "sha256": "<64 hexadecimal characters>"},
    "reviewer_name": "<reviewer>",
    "affiliation": "<independent affiliation>",
    "independent": true,
    "conflict_of_interest": "<declaration>",
    "decision": "approved",
    "reviewed_at": "YYYY-MM-DD"
  }
}
```

The reports must contain:

- **Acquisition protocol:** hardware, operating and optical conditions, exposure and illumination schedule, frame roles, acquisition settings, raw-data handling and data license. Any redaction is explicit and justified.
- **Validation report:** input digest, plugin and recipe versions, parameters, software environment, acceptance criteria, results, uncertainty or repeatability, exclusions, diagnostics and the final decision. Criteria taken only from the simulator are not enough.
- **Independent review:** reviewer and affiliation, independence and conflicts of interest, reviewed scope, assessment of the protocol and interpretation, required corrections, and the final decision, `approved` in both the report and the manifest.

The checker verifies the fields, versions, paths, hashes and declared statuses. It does not judge the scientific content: whether the campaign is representative, the tolerances are suitable or the reviewer is independent remains a human responsibility.

## DataLab-Web

The Web adapter reports `verified` only for this matrix:

| Component | Version |
| --- | --- |
| DataLab-Web | 0.9.0 |
| Pyodide | 0.26.4 |
| Camera plugin | 0.2.0 |
| Relative-DN recipe | 1.1.0 |
| Photon transfer and dark-current recipes | 1.0.0 |

DataLab-Web's `tests/e2e/application_methods.spec.ts` opens each example through its deep link, runs its method from the **Applications** dialog and checks the outputs in the object tree. For the relative-DN quickstart, a Playwright gate also requires:

- a visible **Camera response** curve, a non-blank **Relative PRNU-like map** and the metrics table;
- the removal of every object of a partial commit after an injected failure;
- an incremental WASM heap of at most 64 MiB, and retained output arrays of at most three times the input arrays.

The reference run on 2026-08-11 grew the WASM heap by 0.00 MiB and retained 0.39 MiB of output arrays, 0.84 times the input.
