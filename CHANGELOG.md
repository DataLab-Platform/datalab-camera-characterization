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
