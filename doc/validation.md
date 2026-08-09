# Validation And Performance Baseline

This document records the synthetic scientific checks, invalid input matrix,
and explicit resource benchmark for the relative-DN prototype. These results
support an alpha implementation; they are not metrological validation, an EMVA
1288 claim, or a replacement for documented real-camera data and scientific
review.

## Synthetic Truth Campaign

`tests/validation/test_synthetic_campaign.py` builds one deterministic sensor
with 64 x 64 pixels, 24 frames per series, six flat exposure levels, and one
dark series. The flat photoelectron count is coupled to exposure through a
fixed synthetic flux:

```text
signal_electrons = photoelectron_flux_per_s * exposure_time_s
```

The expected response slope uses the exact simulator PRNU map:

```text
expected_slope_dn_per_s = photoelectron_flux_per_s
                          * mean(prnu_gain_map)
                          / conversion_gain_e_per_dn
```

The expected dark temporal noise combines configured read noise and the
variance of ideal unit-step quantization:

```text
expected_dark_noise_dn = sqrt((read_noise_e / gain_e_per_dn)**2 + 1/12)
```

The test requires the recovered slope within 0.5 percent, dark noise within
2 percent, fitted means within 0.5 percent and 0.2 DN, and fitted residuals
below 0.2 DN. The final level is deliberately clipped and must be excluded
from the fit while identifying the expected saturation onset. These tolerances
are wider than the deterministic reference error but narrow enough to reject
unit, gain, dark-subtraction, fit-mask, and noise-definition mistakes.

A separate deterministic no-noise campaign compares the recovered DSNU-like
and PRNU-like maps with the simulator's static DSNU and PRNU truth maps. Its
tolerances cover ADC quantization while rejecting sign, centering,
dark-correction, and normalization errors.

## Invalid Campaigns

The automated matrix covers missing series, too few acquisitions or levels,
invalid array dimensions and types, empty arrays, non-numeric or non-finite
values, inconsistent frame shape or dtype, cross-series shape or dtype
mismatch, invalid or unordered exposure metadata, and too few unsaturated
levels. Core failures use stable structured diagnostic codes. Recipe metadata
failures raise `RecipeValidationError` and identify the namespaced metadata
key; characterization errors occur before any `RecipeOutcome` can be returned.

## Distribution And Lifecycle

`tests/integration/test_distribution_lifecycle.py` qualifies the installed
artifact and Desktop lifecycle. It builds an isolated wheel, installs it into a
temporary target, loads `CameraDetectorCharacterizationPlugin` through the
real `datalab.plugins` entry point, and resolves the packaged quickstart from
that target. It also verifies hot reload without duplicate instances or menus.

The persistence check runs the quickstart recipe, saves a native DataLab HDF5
workspace, reloads it, and resolves every input and output by its original
UUID. The shared `RecipeRunRecord` and complete anchored `TableResult` must be
unchanged after loading.

## Resource Benchmark

Run the default benchmark from an editable checkout:

```bash
python -m benchmarks.benchmark_characterization
```

The default campaign contains 16 resident contiguous `uint16` images: one
dark and three flat series, four 2048 x 2048 frames per series. The source
arrays occupy 128 MiB. Timing covers temporal characterization, retained mean
images, spatial maps, profiles, histograms, and the candidate display map.
`tracemalloc` starts only after source allocation, so
`peak_incremental_bytes` measures traced Python and NumPy allocations added by
validation and characterization. The JSON report records all parameters and
runtime versions. The benchmark harness reports evidence without deciding
pass/fail; `scripts/check_alpha_gate.py` evaluates its fixed Alpha campaign.

A reference run on Windows with CPython 3.9.10 and NumPy 2.0.2 produced:

| Block size | Time | Input throughput | Incremental peak |
| ---: | ---: | ---: | ---: |
| 1 | 2.974 s | 22.57 MP-frames/s | 264.04 MiB |
| 2 | 2.260 s | 29.69 MP-frames/s | 336.08 MiB |

The numbers are single-run observations on one host, not portable acceptance
limits. They demonstrate the expected speed-memory tradeoff and provide a
baseline for detecting large regressions.

## Alpha Memory Gate

On 2026-08-09, two fresh processes each ran the default 2048 x 2048 campaign
three times with CPython 3.9.10 and NumPy 2.0.2. A 5 ms sampler corroborated the
`tracemalloc` peak with process RSS after allocating the 128 MiB source arrays:

| Run | Time/run | Traced peak | RSS peak | RSS/input |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.893 s | 336.06 MiB | 336.77 MiB | 2.631 x |
| 2 | 1.749 s | 336.06 MiB | 336.78 MiB | 2.631 x |

The Alpha budget is three times the resident input size: both incremental
peaks must remain at or below 384 MiB for this fixed campaign. The independently
executed gate then passed at 336.06 MiB traced and 336.78 MiB RSS. This budget
is intentionally local to the defined campaign; elapsed time has no pass/fail
limit. See [`alpha-gate.md`](alpha-gate.md) for the complete gate and scope.

After spatial outputs were added, the same three-run protocol measured 336.08
MiB traced and 337.00 MiB RSS (`2.63 x` input). The benchmark releases one
run's outputs before starting the next, while retaining every scientific output
for the duration of each run. The original 384 MiB ceiling therefore remains
unchanged.

## Stable Qualification

Stable additionally requires a documented real camera campaign and an
independent scientific review. `scripts/check_stable_gate.py` verifies the
integrity and required declarations of that external evidence before invoking
the complete Alpha gate. The required evidence is currently absent, so Stable
is blocked rather than inferred from synthetic or browser qualification.

See [`stable-gate.md`](stable-gate.md) for the evidence manifest, required
scientific content, and limits of automated verification.
