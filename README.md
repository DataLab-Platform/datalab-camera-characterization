# Camera & Detector Characterization

Headless workflows and DataLab adapters for relative characterization of
scientific cameras and detectors.

This repository is an architecture scaffold. It does not yet implement camera
simulation or characterization metrics, and it does not claim EMVA 1288
compliance. Those capabilities require dedicated scientific validation.

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

## Development

```bash
python -m pip install -e ".[test]"
python -m pytest
python -m ruff check .
```

Installing the project registers `org.datalab.camera-characterization` through the
`datalab.plugins` entry-point group. The Desktop adapter intentionally exposes
no recipes or actions until the corresponding headless workflow exists.
