# Camera Alpha Gate

The relative-DN Camera workflow passes an executable Alpha gate. This status
means that the current synthetic scientific scope, bounded-memory Desktop
workflow, packaging lifecycle, and no-Python quickstart are qualified together.
It is not metrological validation or an EMVA 1288 compliance claim.

## Run The Gate

Install the development dependencies, then run the single gate command from
the repository root:

```bash
python -m pip install -e ".[test]"
python -m scripts.check_alpha_gate
```

The command exits nonzero if the test suite fails or if either memory
measurement exceeds the fixed budget. Its final JSON object records the exact
configuration, runtime versions, measurements, individual checks, and overall
status.

## Scientific Reliability

The full test suite includes a deterministic synthetic campaign with known
sensor truth. It verifies response slope, dark temporal noise, fitted means,
linearity residuals, saturation onset, and relative spatial maps within
documented tolerances. It also covers deterministic simulation, invalid inputs,
stable diagnostics, batch/block numerical equivalence, recipe outputs, and
anchor attachment.

These checks validate the implemented relative-DN equations against the
versioned simulator. They do not substitute for documented real-camera data
or independent scientific review.

## Memory Budget

The fixed Alpha campaign contains 16 resident contiguous `uint16` images: four
dark frames and three four-frame flat levels, each 2048 x 2048 pixels. Inputs
occupy 128 MiB. The characterization uses block size 2 and runs three times.

Both incremental peaks after source allocation must remain at or below three
times the input size:

```text
tracemalloc peak <= 384 MiB
sampled RSS peak <= 384 MiB
```

The factor was fixed after fresh three-run measurements on the reference
Windows host. The phase 4.2 pipeline, including retained mean images, spatial
maps, profiles, histograms, and candidate display map, measured 336.08 MiB
traced and 337.00 MiB RSS, or about 2.63 times the input size. The 3.0 limit
leaves about 14 percent headroom. Raising it requires a documented new baseline
and review. Elapsed time and throughput remain recorded evidence, not an Alpha
pass/fail threshold.

## Desktop UX

Automated Desktop tests exercise the forms and the complete visible quickstart
path: open and select the packaged campaign, assign every image explicitly to
dark or flat, edit parameters, run the registered recipe, and obtain one
response curve, two mean images, three spatial maps, four profiles or
distributions, and the anchored metrics table. Cancellation, invalid campaigns,
transactional commit, installed-wheel discovery, hot reload, and native HDF5
provenance round-trips are also covered.

"UX complete" applies to this non-normative relative-DN Alpha scope, including
the spatial screening outputs. A stable release additionally requires
documented real-camera data and an independent scientific review.
