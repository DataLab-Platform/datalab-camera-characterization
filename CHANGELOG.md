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
