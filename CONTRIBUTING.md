# Contributing to archie

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) for dependency management

## Getting started

1. Fork and clone the repository
2. Install dependencies:
   ```sh
   uv sync
   ```
3. Install the pre-commit hooks (runs ruff format and lint on every commit):
   ```sh
   pre-commit install
   ```
   If you don't have `pre-commit` installed: `uv tool install pre-commit`

## Running tests

```sh
uv run pytest
```

Tests marked `integration` hit a mocked HTTP transport and are included by default. To run only unit tests:

```sh
uv run pytest -m "not integration"
```

Coverage must stay at or above 80%. The suite will fail if it drops below that threshold.

## Code style

Ruff handles formatting and linting. The pre-commit hooks run both automatically on every commit. To run them manually:

```sh
uv run ruff format .
uv run ruff check .
```

All public functions and methods (outside of tests) require docstrings in [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).

## Documentation

Install the docs dependencies and serve locally:

```sh
uv sync --group docs
uv run mkdocs serve
```

Documentation is deployed automatically to GitHub Pages when changes are merged to `main` — you don't need to deploy manually.

## Opening issues

**Bug reports** — include steps to reproduce, expected vs. actual behavior, your Python version, and a stack trace if one is available.

**Feature requests** — describe the use case and, if possible, what you'd want the API to look like.

For non-trivial changes, open an issue to align on the approach before investing time in a PR.

## Submitting a pull request

- Open PRs against `main`
- CI runs the test suite on Ubuntu and Windows — both must pass
- Keep PRs focused; one logical change per PR

## Releases (maintainers only)

Releases are triggered by pushing a version tag:

```sh
git tag v1.1.0
git push --tags
```

The publish workflow builds the package and pushes it to PyPI automatically via OIDC — no manual upload or API token required.
