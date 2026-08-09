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
pure-NumPy camera simulator, an empty recipe registry, and explicit Desktop/Web
integration boundaries. Dataset validation, characterization algorithms, and
recipe outcomes are separate roadmap items and remain intentionally absent.
