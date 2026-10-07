# Architecture

The package uses inward-facing dependencies:

```text
adapters -> workflow -> core
```

The scientific core must be reusable without DataLab or a GUI. Workflows may
use DataLab's headless recipe contracts, but must not import DataLab GUI modules.
Adapters translate between a host and the workflow; they do not own scientific
algorithms.

## Current Scope

The repository provides package identity, namespaced metadata, a deterministic
pure-NumPy camera simulator, structured dataset validation, batch reference
tests, bounded-memory characterization in DN, a registered headless recipe, and
explicit Desktop/Web integration boundaries. The recipe returns a response
curve anchor, useful mean images, an anchored metric table, and structured
warnings.

Two further recipes reuse the same aggregation and validation code: `core/photon_transfer.py` with `workflow/photon_transfer.py` estimate the conversion gain from the photon transfer curve, and `core/dark_current.py` with `workflow/dark_current.py` fit a dark-frame exposure ramp. `workflow/recipes.py` registers the three descriptors in `CAMERA_RECIPES`. The host-neutral `demo.py` module generates the photon transfer and dark-ramp examples in memory for both adapters; the relative-DN quickstart stays a packaged HDF5 file.

Mean and variance are owned by `core/aggregation.py`. Validation,
characterization, and workflows call that module rather than implementing
independent batch statistics. The accumulator accepts individual frames or
blocks. The convenience function accepts either an existing NumPy stack or a
sequence of 2D arrays and materializes at most the configured block size.
Characterization reduces each per-pixel result to campaign scalars before
processing the next exposure, so working memory does not grow with the number
of flat levels.

`workflow/relative_dn.py` translates recipe inputs and parameters into core
types, then translates the immutable characterization result into Sigima
objects. It never mutates a workspace. The DataLab recipe runner owns input
slot validation, transactional cross-panel commit, scalar-result attachment,
and `RecipeRunRecord` provenance.

`adapters/desktop.py` declares the Desktop actions and examples. It does not duplicate the parameter schema, input assignment, scientific calculation, or commit logic: the run actions call DataLab's generic recipe launcher, which uses the binding suggesters and input checks of `workflow/input_checks.py`, edits the declared parameters, and delegates validation, execution, provenance, and cross-panel commit to `RecipeRunner`.

The packaged quickstart is a native DataLab HDF5 resource declared by the
Desktop adapter through `PluginExample`. Its deterministic generation script
depends on DataLab only to serialize the workspace; simulation remains in
`core`, and opening the example still executes the normal workflow rather than
loading precomputed results.

Distribution and lifecycle qualification lives in
`tests/integration/test_distribution_lifecycle.py`. It imports the built wheel
outside the checkout, verifies entry-point discovery and action cleanup across
Desktop hot reload, then persists a complete Camera run through DataLab's
native HDF5 format. These are host integration tests; they do not add Desktop
dependencies to `core` or `workflow`.

`scripts/check_alpha_gate.py` composes the full automated suite with the fixed
representative memory campaign. The gate remains outside the production
dependency graph and emits machine-readable evidence for both traced and
resident-memory peaks.

Scientific and resource validation live outside the production dependency
graph. `tests/validation` compares characterization with simulator truth;
`benchmarks` contains explicit scripts that are not collected by pytest. See
[`validation.md`](validation.md) for the protocols and current baseline.
