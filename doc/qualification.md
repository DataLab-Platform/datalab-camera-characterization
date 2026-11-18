# Qualification

[← Documentation index](README.md)

The plugin remains **Alpha**. The [local 0.3.0 acceptance checks](#local-030-candidate) cover synthetic measurements and both application hosts. They do not replace acquisition on a real camera, comparison with an independent reference or independent human approval. No metrological certification or EMVA 1288 compliance is claimed.

## Synthetic Validation

`tests/validation` compares each method with the simulator truth. The tolerances of the other methods are in the Demonstration sections of [Photon transfer curve](photon-transfer.md#demonstration) and [Dark current and hot pixels](dark-current.md#demonstration).

For the relative characterization, one sensor of 64 × 64 pixels gives one dark series and six flat levels of 24 frames. The test requires:

- response slope within 0.5 %, dark temporal noise within 2 %;
- fitted means within 0.5 % and 0.2 LSB, fit residuals below 0.2 LSB;
- the last, deliberately clipped level excluded from the fit and found as the saturation onset.

The expected values come from the simulator settings and its exact PRNU map:

```text
expected_slope_dn_per_s = photoelectron_flux_per_s * mean(prnu_gain_map) / conversion_gain_e_per_dn
expected_dark_noise_dn = sqrt((read_noise_e / gain_e_per_dn)**2 + 1/12)
```

The `1/12` term is the variance in LSB² for an approximately uniform rounding error over one native code step, not a universal noise correction for real data. A noiseless campaign checks the DSNU-like and PRNU-like maps against the truth maps. Other tests cover invalid campaigns (missing series, too few frames or levels, wrong shapes, types or values, unordered exposures) and their stable diagnostic codes.

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

## Real-camera campaign

Start with the [acquisition protocol and frame ledger](qualification-templates/acquisition-protocol.md). Before acquisition, identify the candidate wheel, the methods and operating range to be assessed. Set numerical acceptance limits, units, uncertainty decision rules, minimum sample sizes and exclusion criteria for each claim. Use sensor requirements or an independent measurement to justify limits, not the synthetic test tolerances above. If a criterion cannot be tested, record it as unqualified rather than moving the limit.

1. **Capture raw linear frames.** Record camera/firmware, sensor, optics, electronic gain and offset, readout rate, ROI, binning, exposure timing, ADC ceiling, native step and alignment. Disable or document all processing (gamma, auto exposure/gain, black subtraction, denoising, defect correction, compression). Verify linear codes, roles and units from the acquisition system; archive immutable originals and any unpacking/conversion applied to copies.
2. **Measure thermal and optical conditions.** Stabilize the sensor at a stated setpoint; retain time-stamped sensor/probe and ambient readings, stability band and drift through every run. Do not extrapolate with a universal dark-current doubling law. For flats, record source, spectrum, diffuser, optical geometry, spatial uniformity, source-monitor calibration and readings synchronized with the frames. A change in the frame mean alone does not distinguish source drift from sensor drift.
3. **Acquire by role and exposure.** For illuminated methods take short closed-shutter references, matched darks and repeated uniform flats at every exposure. Span the linear fit range and continue into a reproducible plateau or ADC clipping; monitor illumination throughout. Preserve the frame order, exact times and exposure groups. If using a single unmatched dark by design, identify its exposure and the resulting limitation; never pool unmatched dark levels. For dark current, acquire repeated dark ramps wide enough to identify a slope above the low rail and below clipping. A dark-only scope need not invent flats.
4. **Repeat the acquisition, not just the calculation.** Take at least two independent runs with the specified settings and enough repeats per exposure for the estimator and target precision. Record restart/re-equilibration, ordering and any interleaving. Disjoint frame pairs are not independent campaigns. Use reserved repeats for masks where selection would otherwise depend on the fit errors.

| Method (recipe contract unchanged) | Quantities and checks to record against the independent reference |
| --- | --- |
| Relative characterization (`1.1.0`) | Fit dark-subtracted mean against exposure (LSB/s); report dark-reference exposure, temporal noise, fit range, residuals, and clipped fraction. Compare DSNU-like/PRNU-like field maps on the same ROI; distinguish illumination structure and residual noise from intrinsic sensor non-uniformity. |
| Photon transfer (`1.0.0`) | Fit temporal variance (LSB²) against net signal (LSB), using the stated dark variance and fit levels; report reciprocal slope in e⁻/LSB. Retain the raw result; if pair centering is used, give the normalization, removed common mode and corrected result separately. Separate clipping or reproducible response plateau from a variance peak. Give observed/lower-bound/indeterminate status, not a physical full well inferred from a sub-rail plateau or SNR from a clipped pair. |
| Dark current (`1.0.0`) | Fit per-pixel slopes (LSB/s) separately from offsets (LSB); propagate any independent conversion gain to e⁻/s. Record censoring at each rail, levels used, class counts, map and summary populations. Distinguish observed slope spread from an intrinsic estimate: document disjoint slope fits, independent mask, covariance and spatial correlations. Report unresolved estimates, not measured zeros. |

For each claim, freeze and identify the same frames, ROI, fit levels, masks and denominator for the candidate and independent calculation. Log each excluded frame, level and pixel class, why it was excluded, and the counts before and after. Compare numerical values and categorical decisions, including indeterminate results. An independent implementation or calibrated reference must not simply call the plugin or use its simulator as truth.

Report differences between runs as well as within-run variability. Budget the contributions from finite repeats, exposure timing, gain/ADC, thermal drift, source stability/nonuniformity, reference calibration, fit and mask selection as applicable. Give units, sensitivities, correlations, propagation or resampling method, interval and coverage assumptions. Use spatial blocks or run-level resampling when pixels or frames are correlated. State what is resolved relative to the uncertainty and the predeclared limit.

## Stable Gate

Each dossier covers **one plugin version, one wheel SHA-256, one real campaign and an exact set of versioned recipes**. Keep separate folders for different versions/builds, even when recipe contracts are identical. A new analysis of old raw frames needs new reports and a new review. Do not edit historical evidence in place or copy a previous host or review decision into a new dossier.

### Prepare a schema 2 dossier

| Order | Worksheet | What to fill and freeze |
| --- | --- | --- |
| 1 | [Manifest](qualification-templates/stable-evidence.template.json), [campaign record](qualification-templates/campaign-record.template.json) and [protocol](qualification-templates/acquisition-protocol.md) | Copy outside the template folder. Record the candidate version and wheel digest from its build record. Freeze the camera ID, license, real-data declaration, dates (`YYYY-MM-DD`), counts and references to the raw artifact and completed protocol in the campaign record. For dark-only data set both flat counts to zero. |
| 2 | [Independent comparison](qualification-templates/independent-comparison.template.json) and [uncertainty budget](qualification-templates/uncertainty-budget.template.json), one pair per method | Identify the reference procedure, its version/calibration, values, units, differences and decision. Quantify uncertainty sources, propagation, interval and resolution. Repeat the exact candidate, recipe, raw/protocol digests and population identifier (e.g. frame ledger and mask digest) in both files. Keep the underlying tables, logs and reference calculations in the archived campaign. |
| 3 | [Method report](qualification-templates/method-report.template.json), one per method | Record the same provenance, actual software environment, analyst, parameters, estimator, population, exclusions, prespecified criteria, results and repeatability. Reference the two completed documents by path and digest. A missing comparison, unresolved requirement or failed criterion is not a pass. Hash the completed report. |
| 4 | [Independent review](qualification-templates/independent-review.template.json) | A qualified person independent of acquisition, implementation and analysis checks the original evidence, versions, calculations, uncertainty, exclusions and decisions. Record identity, competence, affiliation, conflicts, date, limitations and any corrections. Record the hash of the campaign record; `reviewed_reports` maps every in-scope full recipe ID to the hash of the exact report reviewed. Only the reviewer may give `approved`; edits after review require re-review. |

Finish the manifest by recording the review and method report hashes. All paths, including references inside method reports, are **relative to the manifest directory**, must resolve inside it and must not have other hard links. Use lowercase SHA-256 of the actual bytes, not filenames. The templates deliberately have no approved decisions, measured values or valid hashes.

### Run the gate

Run from the candidate checkout installed in editable mode. Supply the wheel digest independently (from the candidate build/verified wheel, **not** from the dossier). The plugin version and expected recipe IDs and versions come from that checkout. By default all registered recipes must have evidence.

```bash
python -m scripts.check_stable_gate path/to/stable-evidence.json --wheel-sha256 "$CANDIDATE_SHA256"
```

For a deliberately narrower claim, specify each full recipe ID with `--method`. For example, `--method org.datalab.camera-characterization:dark-current` requires exactly that entry in both the manifest and review. This is reported as `camera-method-scope`, **not** a plugin-wide `camera-stable` result. In either mode missing, mismatched or unapproved evidence stops the check before Alpha runs. A complete evidence check still requires the executable Alpha gate to pass. The default `qualification/stable-evidence.json` is intentionally absent.

The checker verifies structure, matching scope, artifact bytes and explicit decisions. Hashes are not signatures: authenticity, representativeness, actual independence, adequacy of the uncertainty budget and scientific approval are human responsibilities. The command does not promote or publish a release.

### Read an archive without requalifying it

```bash
python -m scripts.check_stable_gate --archive-v1 path/to/historical/stable-evidence.json
```

Schema 1 remains readable unchanged under its original checks: plugin `0.1.0`, relative recipe `1.1.0`, real campaign, acquisition protocol, validation report and independent approval. Success here means `camera-archive-v1` only: no Alpha invocation and no candidate qualification. For an older schema 2 build, use its matching checkout, wheel digest and scope.

## DataLab-Web

### Local 0.3.0 candidate

The local wheel tested on 2026-11-18 was 355,097 bytes, SHA-256 `2f7a86ad78f67425ee91ca39f8d42380c3be12af5b3b361009fde96e911bba49`. The static test bundle served those exact bytes. This digest identifies a test build, **not** a release artifact or a catalog entry.

| Host or check | Result |
| --- | --- |
| DataLab Desktop 1.4.2, Qt 5.15.2, CPython 3.11.6, NumPy 2.4.4 | All three examples ran from their Desktop actions. Alpha gate: 272 passed; one optional Web-host test was skipped without that host and passed when run with it. Peak incremental memory for 128 MiB of inputs was 336.0 MiB traced and 336.9 MiB RSS, below the 384 MiB limit. |
| DataLab-Web 0.11.1 (`d1ee075`), Pyodide 0.26.4, NumPy 1.26.4, Chromium 156.0.8078.4 | In clean browser contexts the versioned links for `quickstart`, `photon-transfer` and `dark-ramp` opened their examples; each method ran through the Applications dialog on the local static site. A request for 0.2.1 was rejected rather than silently running 0.3.0. |
| Browser rendering and failure handling | The instrumented run displayed the quickstart response, map and table. Retained arrays grew by 411,200 bytes (0.84 times input); the WASM heap did not grow over the recipe run. Failure on the second output restored both panel trees and the retained array size. An import with undeclared units and coding produced no partial results, then succeeded after explicit declarations. |
| Numerical agreement | On `dark-ramp`, the five means from 0.5 to 8 s agreed between hosts (113.92 to 322.89 LSB, including offset). The pixel classification and summary masks were byte-identical; 12,251 of 12,288 pixels contributed to the summary. Map medians in the upper-left 32 × 32 and lower-right 6 × 6 regions were 39.7 and 188.7 e⁻/s respectively. On the ±2% common-mode witness both hosts returned 1.086 e⁻/LSB raw and 2.000 e⁻/LSB centered; neither reported a measured capacity. |
| Historical workspace | A dark ramp saved in Desktop with the 0.2.1 wheel reopened under 0.3.0 without recalculation or rewriting the file. The 20 inputs and six historical outputs retained their UUIDs, data, units (including DN), result table and 0.2.1 provenance. |

The plugin version changes; the recipe IDs and versions do not: relative characterization `1.1.0`, photon transfer `1.0.0`, dark current `1.0.0`. The 0.3.0 manifest still says `unverified`: local acceptance is not verification of the **official** wheel. Repeat the browser checks with the CI-built wheel, verify the catalog and bundled checksums, and test the public link before advertising it.

### Previous versions

Version 0.2.0 was verified for this historical matrix:

| Component | Version |
| --- | --- |
| DataLab-Web | 0.9.0 |
| Pyodide | 0.26.4 |
| Camera plugin | 0.2.0 |
| Relative-LSB recipe | 1.1.0 |
| Photon transfer and dark-current recipes | 1.0.0 |

The 0.2.1 candidate was prequalified with the DataLab-Web 0.11.0 candidate and Pyodide 0.26.4 in Chromium, so its Web manifest reports `verified` for that combination. The final gate must be repeated with the exact official release wheel before DataLab-Web is released.

DataLab-Web's `tests/e2e/application_methods.spec.ts` opens each example through its deep link, runs its method from the **Applications** dialog and checks the outputs in the object tree. For the relative-LSB quickstart, a Playwright gate also requires:

- a visible **Camera response** curve, a non-blank **Relative PRNU-like map** and the metrics table;
- the removal of every object of a partial commit after an injected failure;
- an incremental WASM heap of at most 64 MiB, and retained output arrays of at most three times the input arrays.

The **0.2.1** prequalification used 491,520 bytes of input arrays, retained 411,200 bytes of output arrays (0.84 times the input), and grew the WASM heap by 0 bytes. The browser test injected a failure on the second output and verified that both panel trees and the retained array size were restored. These observations are not measurements of the 0.3.0 wheel.
