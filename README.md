# archie

An async Python client for interacting with ESRI ArcGIS REST APIs, designed around a dataframe-first approach for seamless analysis and data editing with `pandas` and `geopandas`.

[![PyPI](https://img.shields.io/pypi/v/archie.svg)](https://pypi.org/project/archie/)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-github%20pages-blue)](https://cityofboulder.github.io/archie/)

## Installation

Install via pip:

```bash
pip install archie
```

Or with `uv`:

```bash
uv add archie
```

## Quick Start

```python
import archie as arc

# Initialize a client with user token authentication
auth = arc.UserTokenAuth(
    username="your_username",
    password="your_password"
)

async with arc.ArchieClient(
    base_url="https://services.arcgis.com/sharing/rest/services",
    auth=auth
) as client:
    # Create a feature layer reference
    layer = arc.FeatureLayer(
        client=client,
        service_path="MyService/FeatureServer",
        layer_id=0
    )
    
    # Query features and convert directly to a pandas DataFrame
    result = await layer.query(where="1=1")
    df = result.to_frame()
    
    # Or work with spatial data as a GeoDataFrame
    gdf = result.to_geodataframe()
    
    # Add new features from a DataFrame
    new_features = df.head(5).copy()
    edits = await layer.append(new_features)
```

## Authentication

**NoAuth** — for public feature layers:

```python
auth = arc.NoAuth()
```

**UserTokenAuth** — for token-based authentication:

```python
auth = arc.UserTokenAuth(
    username="your_username",
    password="your_password",
    base_url="https://www.arcgis.com"  # optional; defaults to ArcGIS Online
)
```

**Custom auth** — implement the `ArcGISAuth` abstract base class:

```python
class MyCustomAuth(arc.ArcGISAuth):
    async def get_token(self) -> str:
        # your token logic
        
    async def force_refresh(self) -> None:
        # refresh logic
```

## Services

`archie` provides service and layer classes that wrap ESRI's REST endpoints:

- **FeatureLayer** — query, add, update, delete, upsert features; supports spatial and non-spatial operations
- **MapLayer** — query-only access to map service layers
- **FeatureService** — service-level metadata and capabilities
- **MapService** — map service metadata and operations

All layers inherit common methods:
- `query()` — retrieve features with optional filtering and field selection
- `fields()` — introspect layer schema
- `crs()` — coordinate reference system metadata

FeatureLayer additionally supports:
- `apply_edits()` — fine-grained control over add/update/delete operations
- `append()` — bulk insert from a DataFrame
- `upsert()` — insert or update based on key fields
- `sync()` — reconcile a DataFrame with the service (add missing, update changed, delete removed)

## Data Models

**QueryResult** — returned by `query()`:

```python
result = await layer.query(where="population > 10000")

# Convert to DataFrame
df = result.to_frame()

# Convert to GeoDataFrame (if geometry present)
gdf = result.to_geodataframe()

# Access raw features and field metadata
features = result.features
fields = result.fields
```

**ApplyEditsResult** — returned by `apply_edits()`, `append()`, `upsert()`, `sync()`:

```python
edits = await layer.apply_edits(adds=[...], updates=[...], deletes=[...])

# Check for errors
if edits.has_failures:
    print("Failed adds:", edits.failed_adds)
    print("Failed updates:", edits.failed_updates)
    print("Failed deletes:", edits.failed_deletes)
```

**FieldsResult** — layer schema information:

```python
fields = await layer.fields()

# Get field names
field_names = fields.names

# Filter by field type
numeric_fields = fields.filter(types=["esriFieldTypeSmallInteger", "esriFieldTypeInteger"])

# Convert to DataFrame for analysis
df = fields.to_frame()
```

## Error Handling

Catch `ArcGISError` for service-level errors (raised by ESRI endpoints):

```python
try:
    result = await layer.query(where="invalid syntax")
except arc.ArcGISError as e:
    print(f"Error {e.code}: {e.message}")
```

The exception hierarchy distinguishes specific error types:

- `TokenExpiredError` — authentication token has expired (auto-refreshed by archie)
- `TokenMissingError` — authentication token required but missing
- `AuthorizationError` — insufficient permissions for the operation
- `NotFoundError` — resource not found
- `ServiceError` — other ESRI service errors

`ArchieClientError` and its subclasses cover archie-originated errors (invalid parameters, missing capabilities, etc.).

## Roadmap

Planned features for upcoming releases:

1. **Attachment support** — query, add, and delete attachments on feature layers
2. **Geocoding operations** — suggest and batch geocode endpoints

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidance on setting up a development environment, running tests, and submitting pull requests.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release notes and version history.

## License

MIT License — see [LICENSE](LICENSE) for details.

## Contact

Email [Jesse Nestler](mailto:nestlerj@bouldercolorado.gov)