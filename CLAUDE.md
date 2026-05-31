# CLAUDE.md

## Project overview

`archie` is an async-first Python client for ESRI ArcGIS REST APIs, built around dependency injection and modern analysis libraries. The stack is `httpx`, `anyio`, `pydantic`, `pytest` + `pytest-anyio` + `pytest-mock`, `pandas`, `geopandas`.

Layers (bottom to top):

```
auth          →  token acquisition and header injection
client        →  HTTP methods, error handling, format enforcement
operations    →  ESRI-idiomatic calls (query, applyEdits, addAttachment, ...)
models        →  Models returned by operation calls (QueryResult, ApplyEditsResult, ...)
services      →  cohesive service APIs (FeatureLayer, FeatureService, MapService, ...)
```

## Project structure

```
src/
  archie/
    auth/
    models/
    operations/
    services/
    client.py
    errors.py
    exceptions.py
tests/
  auth/
  models/
  operations/
  services/
  helpers.py
  conftest.py
pyproject.toml
```

## Coding conventions

- Surface tradeoffs explicitly; do not assume or hide confusion
- Minimum code that solves the problem; nothing speculative
- Touch only what is necessary; clean up only your own mess
- Leverage existing library plumbing wherever possible
- No inline comments unless truly non-obvious
- Always add docstrings to non-test functions and methods

## Testing conventions

- Framework: `pytest` + `pytest-mock`; never `unittest`
- Async tests: `@pytest.mark.anyio` (or `anyio_mode = "auto"` in `pyproject.toml`)
- AAA format with blank lines separating Arrange / Act / Assert
- Do not write tests until the underlying code change is confirmed
- When mocks become excessive, flag it and suggest a refactor rather than adding more
- Fixtures should go in the root `tests/conftest.py` file
- Helper functions and globals should go in the `tests/helpers.py` file
- Prioritize parametrizing tests where logical
- Parametrized tests always include `ids=`
- Leverage existing fixtures and helpers wherever possible; if either need tweaks in order to make new tests work, prefer updating and verify that they will still work elsewhere.

## Architectural decisions

- Async-first throughout; use `anyio` primitives (not `asyncio` directly)
- `@handle_esri_errors` is applied at `_request`, not at the operations layer
- ESRI format param (`f=json`) is enforced by the client on every request; `f=geojson` is the only exception
- Per-feature edit errors (`applyEdits`) belong in `ApplyEditsResult` at the endpoint layer, not in the client