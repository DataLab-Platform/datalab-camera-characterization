# Contributing

## Setup and Checks

Install the project in editable mode, in a Python environment where DataLab 1.3 or later is available:

```bash
python -m pip install -e ".[test]"
```

Before submitting a change, run:

```bash
python -m ruff check .
python -m pytest
```

## Architecture

Dependencies point inward:

```text
adapters -> workflow -> core
```

- `core` holds the scientific code, in NumPy only: simulator, statistics, relative characterization, photon transfer and dark current. It does not import DataLab.
- `workflow` turns the core into headless DataLab recipes, registered in `CAMERA_RECIPES`. It checks inputs, suggests the dark and flat bindings, and converts results to Sigima objects. It never changes a workspace and never imports GUI modules.
- `adapters/desktop.py` and `adapters/web.py` declare the actions, examples, tools and welcome tiles. The run actions call DataLab's generic recipe launcher; DataLab's `RecipeRunner` owns validation, transactional commit and provenance.
- `simulator.py` exposes the core simulator as a DataLab instrument. `demo.py` generates the photon transfer and dark-ramp examples in memory; the quickstart is a packaged HDF5 file.

`tests/unit/test_architecture.py` checks these boundaries.

Mean and variance belong to `core/aggregation.py`. A block accumulator (Chan/Welford) processes at most `aggregation_block_size` frames at a time, one by default. Memory therefore grows with the block size and the frame size, not with the number of frames. Each exposure level is reduced to scalars before the next one.

## Tests

- `tests/unit`: core, workflow and adapters.
- `tests/validation`: results against the simulator truth.
- `tests/integration`: installed wheel, hot reload and DataLab workspace round trip.

`benchmarks` holds explicit scripts that pytest does not collect. See [Qualification](doc/qualification.md) for the Alpha and Stable gates.

## Maintenance

- **Quickstart resource:** regenerate `src/datalab_camera_characterization/examples/camera_quickstart.h5` from fixed simulator parameters:

  ```powershell
  $env:PYTHONPATH="src;../DataLab;../Sigima;../guidata;../PlotPy;../PythonQwt"
  python scripts/generate_quickstart.py
  ```

- **Screenshots:** regenerate `doc/images/*.png` with the plugin installed in DataLab's environment:

  ```bash
  python -m scripts.take_screenshots
  ```

- **DataLab-Web:** the wheel embeds this README. DataLab-Web bundles the wheel and checks its size and SHA-256 (`src/runtime/bundledPlugins.ts`): update them when bumping the plugin version.

## Branches

Day-to-day work lands on `develop`, the default branch: open pull requests against it. `main` is the release branch. It will be created at the first release, once the DataLab version that provides the plugin SDK is published; after that, `develop` is merged into `main` only to cut a release. This is the same model as DataLab, Sigima and DataLab-Web.
