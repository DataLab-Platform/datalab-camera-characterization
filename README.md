# Camera & Detector Characterization

Headless workflows and DataLab adapters for the characterization of scientific cameras and detectors.

The plugin offers three methods, each with its own demonstration campaign:

| Recipe | Physical question | Demonstration |
| --- | --- | --- |
| Relative Camera characterization | How do response, temporal noise and spatial non-uniformity behave, in DN? | Packaged quickstart: 4 dark frames and 4 flat levels with vignetting and dust |
| Photon transfer curve | What are the conversion gain (e⁻/DN), read noise, saturation capacity and dynamic range? | Generated ladder of 16 uniform-illumination levels up to ADC saturation |
| Dark current and hot pixels | How much dark current does each pixel generate, and which pixels are hot? | Generated uncooled-sensor dark ramp from 0.5 s to 8 s with amplifier glow |

This repository provides a deterministic synthetic camera model,
structured input diagnostics, relative temporal and spatial characterization
in DN, and a headless DataLab recipe producing curves, maps, profiles,
distributions, candidate pixels, and an anchored metric table. It does not
claim EMVA 1288 compliance; calibrated or normative capabilities require
dedicated scientific validation.

## Architecture

The package separates portable domain behavior from host integration:

```text
core  <---  workflow  <---  adapters/desktop.py
                  `---  adapters/web.py
```

- `core` contains host-independent domain code.
- `workflow` composes the core into headless recipes.
- `adapters/desktop.py` is the DataLab Desktop plugin entry point.
- `adapters/web.py` is the thin DataLab-Web boundary and reports `verified`
  for its pinned browser matrix.

`core` and `workflow` must not import Qt, DataLab GUI modules, Pyodide browser
shims, or host adapters. Tests enforce this dependency direction.

## Synthetic Frames

The simulator models photoelectron shot noise, dark current, read noise, PRNU,
pixel/row/column DSNU, amplifier glow, flat-field vignetting and dust shadows,
ADC saturation, quantization, and deterministic dead/hot pixels:

```python
from datalab_camera_characterization.core import (
  CameraSimulationParameters,
  simulate_camera_frames,
)

result = simulate_camera_frames(
  CameraSimulationParameters(shape=(256, 320), frame_count=10, seed=42)
)
frames = result.frames_dn
truth = result.truth
```

The same parameters and seed produce identical frames and truth maps. See
[`doc/simulation.md`](doc/simulation.md) for units, equations, and limitations.

## Relative Characterization in DN

The headless core validates dark and uniform-illumination frame stacks before
computing response, temporal variance/noise, relative SNR, saturation onset,
dynamic-range estimate, and linearity residuals:

```python
from datalab_camera_characterization.core import (
  CameraExposureSeries,
  CameraValidationParameters,
  characterize_relative_dn,
)

result = characterize_relative_dn(
  dark_frames,
  (
    CameraExposureSeries(flat_low, exposure_time_s=0.01),
    CameraExposureSeries(flat_high, exposure_time_s=0.02),
  ),
  CameraValidationParameters(saturation_dn=4095),
  aggregation_block_size=4,
)
```

Input anomalies are returned as structured diagnostics before characterization.
Mean, sample variance, finite-value scans, and saturation counts process at
most `aggregation_block_size` frames together; the default of one frame
minimizes temporary memory.
All metrics remain relative quantities in DN; no conversion gain, quantum
efficiency, or calibrated radiometric quantity is estimated. See
[`doc/characterization.md`](doc/characterization.md). Synthetic truth tests,
invalid campaigns, and the performance baseline are described in
[`doc/validation.md`](doc/validation.md).

## Headless Recipe

The registered `relative-dn-characterization` recipe accepts many dark images
and many flat images. Each flat image carries its exposure time in the stable
metadata key returned by `EXPOSURE_TIME_METADATA_KEY`; frames sharing an
exposure are grouped into one statistical series.

The recipe returns:

- `response`: the response curve and anchor object;
- `mean_dark`: the mean dark image;
- `mean_flat`: the last unsaturated mean flat image;
- `dsnu_like_map`: the centered mean dark image in DN;
- `prnu_like_map`: the normalized dark-corrected flat image;
- `candidate_pixel_map`: pixels exceeding the configured relative threshold;
- row and column PRNU-like profiles;
- DSNU-like and PRNU-like distributions;
- `metrics`: a non-normative `TableResult` attached to `response`.

See [`doc/workflow.md`](doc/workflow.md) for the input, parameter, diagnostic,
output, and provenance contracts.

## Photon Transfer and Dark Current

The `photon-transfer` recipe fits the dark-corrected temporal variance against the dark-corrected mean signal. Its slope is the inverse conversion gain, from which the read noise, saturation capacity, dynamic range and SNR curve follow in electrons. See [`doc/photon-transfer.md`](doc/photon-transfer.md).

The `dark-current` recipe fits every pixel's dark signal against exposure time. It returns dark-current and offset maps, hot pixels detected against the local background, the dark-current non-uniformity and an indicative gain from dark shot noise. See [`doc/dark-current.md`](doc/dark-current.md).

Both demonstrations are generated in memory from the simulator and tag every frame with `FRAME_ROLE_METADATA_KEY` (`dark` or `flat`). This explicit role wins over the exposure-time convention, so dark-ramp frames carrying an exposure time stay dark frames.

## Desktop Quickstart

After installing the plugin, choose **Plugins > Camera & Detector
Characterization > Open quickstart example**. DataLab loads and selects a
packaged synthetic campaign containing four dark frames and four flat exposure
levels. Then choose **Run camera characterization...**. The plugin assigns the dark and flat frames from their metadata, checks the campaign, and DataLab opens the recipe parameters. Accept them to obtain the response curve, spatial maps, profiles, distributions, and anchored metrics table without writing Python.

The 96 x 128 dark frames represent shutter-closed sensor readout: bias,
fixed-pattern banding, amplifier glow, read noise, and defective pixels. The
flat frames represent an illuminated uniform field at four exposure times,
with vignetting, dust shadows, PRNU, shot noise, and the same static defects.
They are calibration acquisitions rather than arbitrary scene images.

Opening the example asks before replacing a non-empty workspace. The complete
walkthrough and expected results are documented in
[`doc/quickstart.md`](doc/quickstart.md).

The DataLab welcome page also shows a **Camera & Detector Characterization** tile in its Applications section. The tile is derived from the plugin information and icon, and opens the Camera page of the **Applications** catalog. A second **Open quickstart example** tile opens and selects the quickstart; when the section is short of room, it moves to the menu of the main tile.

The same plugin menu offers **Open photon transfer example** and **Open dark-ramp example**, then **Run photon transfer analysis...** and **Run dark-current analysis...**. The **Applications** catalog presents each method with the inputs it expects, a live status telling whether the current selection can run it, and the examples designed for it. **Try with this example** opens such an example, prefills the method parameters, and runs the method once they are accepted. The photon transfer ladder serves both the photon transfer and the relative-DN methods; the dark ramp serves the dark-current method.

## DataLab Web Integration

DataLab-Web 0.9.0 explicitly bundles the pure-Python Camera wheel and adds that
local artifact to Pyodide's import path. The browser does not discover the
Desktop entry point and does not download the plugin from a package index at
runtime. The adapter declares the pinned DataLab-Web, Pyodide, plugin, and
recipe versions through `get_web_manifest()`.

The packaged `camera_quickstart.h5` is read with `importlib.resources` and
passed to DataLab-Web's existing byte-based HDF5 workspace loader. Images
imported through the browser use the same metadata contract as Desktop: an explicit frame role wins; otherwise images
with `EXPOSURE_TIME_METADATA_KEY` are flat frames and the others are dark
frames. Recipe execution delegates to the shared headless workflow. The manifest lists every recipe and example.

A real Chromium/Pyodide qualification now executes the shared recipe and
checks a visible response curve, PRNU-like map, and anchored metrics table. It
also enforces incremental WASM-heap and retained-array budgets on the packaged
campaign. The separately reviewed manifest reports `verified` only for the
exact versions recorded by the adapter and qualification report. See
[`doc/web-qualification.md`](doc/web-qualification.md).

## Alpha Gate

The current relative-DN Desktop scope has one executable qualification gate:

```bash
python -m scripts.check_alpha_gate
```

It runs the complete test suite and a fixed 2048 x 2048 benchmark, then checks
both traced allocations and sampled process RSS against the measured memory
budget. Scope, evidence, thresholds, and exclusions are documented in
[`doc/alpha-gate.md`](doc/alpha-gate.md).

## Development

```bash
python -m pip install -e ".[test]"
python -m pytest
python -m ruff check .
python -m benchmarks.benchmark_characterization
```

The integration suite builds and installs a wheel in a temporary directory,
loads the plugin through its real `datalab.plugins` entry point, exercises a
Desktop hot reload, and round-trips a characterized quickstart workspace
through native HDF5.

The benchmark is explicit and excluded from the default test suite. Elapsed
time and throughput remain observations rather than portable acceptance
thresholds; only the documented Alpha memory ceiling is enforced by the gate.

## Stable Gate

The Stable gate is intentionally fail-closed. It requires a self-contained,
SHA-256-bound evidence bundle containing a documented real camera campaign,
its acquisition protocol and validation report, and an approved independent
scientific review. Only then does it run the existing Alpha gate:

```bash
python -m scripts.check_stable_gate
```

No such evidence bundle is currently present, so the command exits nonzero
and the project remains Alpha. See [`doc/stable-gate.md`](doc/stable-gate.md)
for the manifest contract, scientific content requirements, and automation
boundary.

Installing the project registers `org.datalab.camera-characterization` through the
`datalab.plugins` entry-point group. The Desktop adapter exposes the headless recipes through the plugin SDK. Each recipe declares its input slots (count, required `exposure_time` metadata, frame-role hint), proposes the dark and flat frames from their metadata, and checks the campaign (frame shapes, dark count, exposure levels, frames per level) before the run. The run actions delegate to DataLab's generic recipe launcher: it asks for an assignment only when the selection is ambiguous or invalid, opens the recipe parameters, and delegates the cross-panel commit to the transactional `RecipeRunner`.
