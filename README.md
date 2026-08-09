# Camera & Detector Characterization

Headless workflows and DataLab adapters for relative characterization of
scientific cameras and detectors.

This repository currently provides a deterministic synthetic camera model,
structured input diagnostics, relative characterization metrics in DN, and a
headless DataLab recipe producing a response curve, useful mean images, and an
anchored metric table. It does not claim EMVA 1288 compliance; calibrated or
normative capabilities require dedicated scientific validation.

## Architecture

The package separates portable domain behavior from host integration:

```text
core  <---  workflow  <---  adapters/desktop.py
                  `---  adapters/web.py
```

- `core` contains host-independent domain code.
- `workflow` composes the core into headless recipes.
- `adapters/desktop.py` is the DataLab Desktop plugin entry point.
- `adapters/web.py` reserves the Web boundary and is currently marked
  `unsupported`.

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
- `metrics`: a non-normative `TableResult` attached to `response`.

See [`doc/workflow.md`](doc/workflow.md) for the input, parameter, diagnostic,
output, and provenance contracts.

## Development

```bash
python -m pip install -e ".[test]"
python -m pytest
python -m ruff check .
python -m benchmarks.benchmark_characterization
```

The benchmark is explicit and excluded from the default test suite. Its
reported time and memory are observations for the current host, not portable
acceptance thresholds.

Installing the project registers `org.datalab.camera-characterization` through the
`datalab.plugins` entry-point group. The Desktop adapter exposes the headless
recipe through the plugin SDK and intentionally adds no custom GUI action.
