# Contributing

## Development setup

```bash
python -m pip install -e .
```

## Build package artifacts

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

## Local CLI test

```bash
overte-builder --help
python -m overte_builder --help
```

## Release process

1. Update `CHANGELOG.md` and version in `pyproject.toml`.
2. Create a Git tag (example: `v0.1.1`).
3. Push the tag to trigger the publish workflow.
