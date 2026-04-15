# overte-builder

`overte-builder` is a small CLI utility for driving Overte builds with Conan + CMake + Ninja.

## Features

- Configure and build Release or Debug outputs
- Toggle ASAN / TSAN build flags
- Optional Vulkan renderer build switch
- Optional desktop build progress notifications via Freedesktop DBus

## Installation

From PyPI:

```bash
pip install overte-builder
```

With desktop notifications support dependencies:

```bash
pip install "overte-builder[notifications]"
```

From source:

```bash
python -m pip install -e .
```

## Usage

```bash
overte-builder --help
overte-builder --debug --build
overte-builder --incremental-build
overte-builder --build --vulkan
```

Legacy script wrappers are still available:

```bash
./overte-builder.py --build
```

## Build and publish

Build artifacts:

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

Upload:

```bash
python -m twine upload dist/*
```

## Development notes

- Package source is in `src/overte_builder`
- CLI entry point is `overte_builder.cli:main`
- Top-level scripts are compatibility wrappers only
