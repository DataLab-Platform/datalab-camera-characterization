# Camera & Detector Characterization

Headless workflows and DataLab adapters for relative characterization of
scientific cameras and detectors.

This repository currently provides a deterministic synthetic camera model,
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
- `adapters/web.py` is the thin DataLab-Web boundary and is currently marked
  `untested`.

`core` and `workflow` must not import Qt, DataLab GUI modules, Pyodide browser
shims, or host adapters. Tests enforce this dependency direction.

## Synthetic Frames

The simulator models photoelectron shot noise, dark current, read noise, PRNU,
DSNU, ADC saturation, quantization, and deterministic dead/hot pixels:

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

## Desktop Quickstart

After installing the plugin, choose **Plugins > Camera & Detector
Characterization > Open quickstart example**. DataLab loads and selects a
packaged synthetic campaign containing four dark frames and four flat exposure
levels. Then choose **Run camera characterization...** and accept the explicit
role and parameter forms to obtain the response curve, spatial maps, profiles,
distributions, and anchored metrics table without writing Python.

Opening the example asks before replacing a non-empty workspace. The complete
walkthrough and expected results are documented in
[`doc/quickstart.md`](doc/quickstart.md).

## DataLab Web Integration

DataLab-Web 0.8.0 explicitly bundles the pure-Python Camera wheel and adds that
local artifact to Pyodide's import path. The browser does not discover the
Desktop entry point and does not download the plugin from a package index at
runtime. The adapter declares the pinned DataLab-Web, Pyodide, plugin, and
recipe versions through `get_web_manifest()`.

The packaged `camera_quickstart.h5` is read with `importlib.resources` and
passed to DataLab-Web's existing byte-based HDF5 workspace loader. Images
imported through the browser use the same metadata contract as Desktop: images
with `EXPOSURE_TIME_METADATA_KEY` are flat frames and the others are dark
frames. Recipe execution delegates to the shared headless workflow.

The status intentionally remains `untested`: wheel import, resource access,
and HDF5 loading are covered in a real Pyodide browser, but visible rendering
of the curve, maps, and table and the Pyodide memory budget are separate
qualification gates.

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

Installing the project registers `org.datalab.camera-characterization` through the
`datalab.plugins` entry-point group. The Desktop adapter exposes the headless
recipe through the plugin SDK and provides a modal editor for its declared
`CameraRecipeParameters`. With at least six images selected, **Run camera
characterization...** assigns each image a dark or flat role, opens the recipe
parameters, and delegates the cross-panel commit to DataLab's transactional
`RecipeRunner`.
