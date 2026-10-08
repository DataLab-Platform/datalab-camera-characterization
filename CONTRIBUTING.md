# Contributing

Install the project in editable mode with its development dependencies:

```bash
python -m pip install -e ".[test]"
```

Before submitting a change, run:

```bash
python -m ruff check .
python -m pytest
```

Scientific behavior belongs in `core`; campaign orchestration belongs in
`workflow`; DataLab Desktop and Web integration belongs in `adapters`. Core and
workflow code remains independent from Qt and browser-specific shims.

## Branches

Day-to-day work lands on `develop`, the default branch: open pull requests against it. `main` is the release branch. It will be created at the first release, once the DataLab version that provides the plugin SDK is published; after that, `develop` is merged into `main` only to cut a release. This is the same model as DataLab, Sigima and DataLab-Web.
