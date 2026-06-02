# Plan: Prepare `archie` for PyPI v1.0.0 Release

## Context

`archie` is an async-first Python client for ESRI ArcGIS REST APIs. The code is architecturally complete with a full test suite, but it's missing the packaging metadata, documentation, and automation expected of a production PyPI release. This plan addresses the gaps needed to publish a credible v1.0.0.

---

## Tasks

### 1. Update `pyproject.toml` metadata

**File:** `pyproject.toml`

Add/update the following fields under `[project]`:

- `version = "1.0.0"`
- `authors = [{name = "City of Boulder Department of Innovation and Technology", email = "nestlerj@bouldercolorado.gov"}]`
- `license = {file = "LICENSE"}`
- `keywords = ["arcgis", "esri", "gis", "rest", "async", "geospatial"]`
- `classifiers`:
  ```toml
  classifiers = [
    "Development Status :: 5 - Production/Stable",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering :: GIS",
    "Typing :: Typed",
  ]
  ```
- `[project.urls]` section:
  ```toml
  [project.urls]
  Repository = "https://github.com/cityofboulder/archie"  # adjust if needed
  ```

Also update `readme` to use explicit content type:
```toml
readme = {file = "README.md", content-type = "text/markdown"}
```

---

### 2. Write README.md

**File:** `README.md` (currently empty)

Minimum required content:
- Package name, one-paragraph description
- Installation: `pip install archie` or `uv add archie`
- Quick-start code snippet (create client, authenticate, query a layer)
- Brief API overview: `ArchieClient`, auth classes, service/layer classes
- Link to CHANGELOG

---

### 3. Update CHANGELOG.md for v1.0.0

**File:** `CHANGELOG.md`

- Rename `## [Unreleased]` → `## [1.0.0] - 2026-06-01`
- Add a new empty `## [Unreleased]` section above it
- Add the compare link at the bottom: `[1.0.0]: https://github.com/.../compare/v0.1.0...v1.0.0`

---

### 4. Add `py.typed` marker

**File:** `src/archie/py.typed` (empty file)

Required for PEP 561 so that type checkers know this package ships inline types. Also add it to `pyproject.toml` under `[tool.hatch.build.targets.wheel]`:
```toml
[tool.hatch.build.targets.wheel]
include = ["src/archie/py.typed"]
```
(Hatchling auto-includes everything under `src/`, so this may already be covered — verify.)

---

### 5. Expand public API in `__init__.py`

**File:** `src/archie/__init__.py`

Export commonly used symbols so users can do `from archie import FeatureLayer, ArcGISAuth, QueryResult` without digging into submodules:

```python
from archie.client import ArchieClient
from archie.auth import ArcGISAuth, NoAuth, UserTokenAuth
from archie.exceptions import (
    ArcGISError,
    TokenExpiredError,
    # ... other user-facing exceptions
)
from archie.models import QueryResult, FieldsResult, ApplyEditsResult
from archie.services import FeatureService, MapService
from archie.services.layers import FeatureLayer, MapLayer

__all__ = [
    "ArchieClient",
    "ArcGISAuth", "NoAuth", "UserTokenAuth",
    "ArcGISError", "TokenExpiredError", ...,
    "QueryResult", "FieldsResult", "ApplyEditsResult",
    "FeatureService", "MapService",
    "FeatureLayer", "MapLayer",
]
```

---

### 6. Add GitHub Actions CI

**Files:**
- `.github/workflows/ci.yml` — run `uv run pytest` on push/PR (Python 3.12, Windows + Ubuntu)
- `.github/workflows/publish.yml` — publish to PyPI on `v*` tag push using Trusted Publishing (OIDC, no API keys needed)

The publish workflow should:
1. Build with `uv build`
2. Publish with `uv publish` (or `twine upload dist/*`)
3. Use `environment: pypi` with PyPI Trusted Publishing configured on the repo

---

### 7. (Optional but recommended) Add `pytest-cov` and coverage config

Add to `pyproject.toml`:
```toml
[tool.coverage.run]
source = ["archie"]
branch = true

[tool.coverage.report]
fail_under = 80
```

Add `pytest-cov` to `[project.optional-dependencies]` dev group.

---

## Verification

1. `uv build` — confirm wheel and sdist build cleanly with no warnings
2. `pip install dist/archie-1.0.0-*.whl` in a fresh virtualenv, then `python -c "import archie; print(archie.__version__)"` (if `__version__` is added) and `from archie import FeatureLayer`
3. Check the PyPI preview: `twine check dist/*`
4. `uv run pytest` — full suite must pass
5. Review the PyPI upload form / package page preview for completeness

---

## Priority Order

| # | Task | Blocker? |
|---|------|----------|
| 1 | pyproject.toml metadata | Yes — bare minimum for PyPI |
| 2 | README.md | Yes — PyPI page will be blank |
| 3 | CHANGELOG v1.0.0 header | Yes — semver convention |
| 4 | py.typed marker | No, but important for type-checking users |
| 5 | Expanded __init__.py exports | No, but important for usability |
| 6 | GitHub Actions CI/publish | No, but important before ongoing development |
| 7 | pytest-cov | Optional |
