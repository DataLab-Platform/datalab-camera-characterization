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
