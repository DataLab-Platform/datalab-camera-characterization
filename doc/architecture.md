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
warnings. Web remains explicitly unsupported.

Mean and variance are owned by `core/aggregation.py`. Validation,
characterization, and workflows call that module rather than implementing
independent batch statistics. The accumulator accepts individual frames or
blocks. The convenience function accepts either an existing NumPy stack or a
sequence of 2D arrays and materializes at most the configured block size.

`workflow/relative_dn.py` translates recipe inputs and parameters into core
types, then translates the immutable characterization result into Sigima
objects. It never mutates a workspace. The DataLab recipe runner owns input
slot validation, transactional cross-panel commit, scalar-result attachment,
and `RecipeRunRecord` provenance.
