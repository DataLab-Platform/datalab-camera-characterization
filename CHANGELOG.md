# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

- Establish the independent Camera plugin package.
- Separate host-independent core and workflow code from host adapters.
- Add deterministic synthetic camera frames with explicit ground-truth maps.
- Add structured input diagnostics and batch relative characterization in DN.
- Bound mean, sample-variance, finite-value, and saturation processing by an
  explicit frame block size with numerical equivalence tests against NumPy.
- Register a headless relative-DN recipe with a response-curve anchor, mean
  dark and flat images, an anchored metric table, and structured warnings.
- Validate response, read noise, linearity, and saturation against deterministic
  synthetic truth, with additional invalid-campaign coverage.
- Add a reproducible 2048 x 2048 time and incremental-memory benchmark, and
  avoid retaining per-pixel statistics for every exposure level.
- Add a thin Desktop adapter for editing the declared relative-DN `DataSet`;
  input-role assignment and recipe launch remain a separate UI step.
- Add the Desktop run action with explicit per-image dark/flat roles, parameter
  editing, selection gating, and transactional cross-panel recipe commit.
- Add a packaged deterministic Camera quickstart that opens, selects, and runs
  from Desktop without requiring users to write Python.
- Qualify isolated wheel installation, entry-point hot reload, and native HDF5
  persistence of Camera UUIDs, provenance, and anchored metrics.
- Add an executable relative-DN Alpha gate covering synthetic reliability,
  complete Desktop quickstart UX, and a measured traced/RSS memory ceiling.
- Add relative DSNU/PRNU maps, candidate pixels, row and column profiles,
  distributions, spatial metrics, synthetic truth checks, and persistence
  coverage while preserving the existing Alpha memory ceiling.
- Add the thin DataLab-Web adapter, an explicit compatibility manifest,
  packaged quickstart byte access, and metadata-based browser input mapping,
  initially retaining the `untested` compatibility status.
- Qualify the bundled recipe in Chromium/Pyodide with visible response-curve,
  PRNU-map, and metrics-table assertions, transactional cross-panel commit,
  persisted provenance, rollback coverage, and explicit memory budgets.
- Promote the pinned DataLab-Web 0.9.0 / Pyodide 0.26.4 compatibility matrix
  to `verified` after its visible-output and memory qualification passed.
- Add a fail-closed Stable evidence gate for a hashed real camera campaign,
  documented validation, and approved independent scientific review; the
  project remains Alpha while those external evidence artifacts are absent.
- Connect the DataLab Applications catalog to the existing Camera workflow,
  packaged quickstart, and project documentation.
- Replace the per-image Dark/Flat radio blocks with one compact Dark-frame
  checklist where unchecked images are assigned to Flat.
- Give the packaged Camera quickstart physically meaningful dark frames with
  readout banding, amplifier glow, and defects, and flat frames with a uniform
  illuminated field, vignetting, dust shadows, PRNU, and shot noise.
- Add a dedicated plugin icon, shown on the Camera tile of the DataLab welcome page.
- Add a photon transfer recipe estimating conversion gain, read noise, saturation capacity, dynamic range and SNR, with a generated 16-level demonstration validated against simulator truth.
- Add a dark-current recipe fitting a dark-frame exposure ramp per pixel to map dark current, offset and isolated hot pixels, with a generated uncooled-sensor demonstration validated against simulator truth.
- Add opt-in simulator dark-current non-uniformity, dark hot pixels, exposure-proportional amplifier glow and independent noise streams, keeping existing campaigns bitwise identical.
- Let an explicit frame-role metadata value decide dark or flat roles before the exposure-time convention.
- Add a quickstart tile next to the Camera tile on the DataLab welcome page.
- Declare what each recipe expects (slot titles and descriptions, minimum frame counts, required exposure time) and check campaigns before the run, so DataLab can tell whether the current selection is usable and why.
- Propose dark and flat frames from their metadata and let DataLab's generic launcher run the recipes, replacing the Desktop dark/flat checklist.
- Pair the photon transfer ladder with both the photon transfer and relative-DN methods; example parameter values are now keyed by method.
