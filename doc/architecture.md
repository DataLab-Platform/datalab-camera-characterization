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
tests, bounded-memory characterization in DN, an empty recipe registry, and
explicit Desktop/Web integration boundaries. Recipe outcomes remain a separate
roadmap item and are intentionally absent.

Mean and variance are owned by `core/aggregation.py`. Validation and
characterization call that module rather than implementing independent batch
statistics. The accumulator accepts individual frames or blocks, while the
convenience function slices an existing NumPy stack along its frame axis.
