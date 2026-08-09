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

The initial repository establishes package identity, namespaced metadata, an
empty recipe registry, and explicit Desktop/Web integration boundaries. Camera
simulation, validation, characterization algorithms, and recipe outcomes are
separate roadmap items and remain intentionally absent.
