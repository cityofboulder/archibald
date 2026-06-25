# archibald

[![PyPI](https://img.shields.io/pypi/v/archibald.svg)](https://pypi.org/project/archibald/)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/cityofboulder/archibald/blob/main/LICENSE)
[![Docs](https://img.shields.io/badge/docs-github%20pages-blue)](https://cityofboulder.github.io/archibald/)

An async Python client for interacting with ESRI ArcGIS REST APIs, designed around a
dataframe-first approach for seamless analysis and data editing with `pandas` and `geopandas`.

## Why archibald?

Esri's official [`arcgis`](https://developers.arcgis.com/python/) Python library is comprehensive,
but it comes with tradeoffs that make it difficult to use in modern data engineering contexts.
`archibald` is/has:

- **Async first.** Every call blocks in `arcgis`, which makes concurrent operations across multiple
  layers awkward, expensive, and time-consuming. archibald is `async`-native throughout.
- **Light.** The `arcgis` package pulls in hundreds of megabytes of dependencies — map
  rendering, notebook widgets, spatial analysis services, and more. archibald's dependency
  surface is `httpx`, `pandas`, and `geopandas`. Ideal for AWS Lambdas and other contexts
  where bloat comes at a premium.
- **Clear error handling.** Esri's API frequently returns HTTP 200 responses with embedded
  error bodies that the official library doesn't always surface. archibald treats these as
  first-class exceptions with a typed hierarchy.
- **Robust DataFrame integration.** The official library's `SpatialDataFrame` type has
  historically been finicky. archibald deals entirely in `pd.DataFrame` and `gpd.GeoDataFrame`
  objects.
- **Editing that meets you at the DataFrame.** Pass a GeoDataFrame and archibald handles
  the rest: geometry serialization, field type coercion, and validation before anything
  hits the wire. Write operations range from fine-grained `apply_edits()` to a full
  DataFrame `sync()`, all returning structured results with per-operation failure details.

archibald is deliberately narrow in scope: FeatureServer and MapServer interactions, done well.
It is not a replacement for the full `arcgis` SDK if you need portal management, hosted
notebooks, or Esri's spatial analysis services.

## Installation

```bash
pip install archibald
```

Or with `uv`:

```bash
uv add archibald
```

## Quick Start

```python
import archibald as arc

auth = arc.UserTokenAuth(
    username="your_username",
    password="your_password",
)

async with arc.ArchieClient(
    base_url="https://services.arcgis.com/sharing/rest/services",
    auth=auth,
) as client:
    layer = arc.FeatureLayer(
        client=client,
        service_path="MyService/FeatureServer",
        layer_id=0,
    )

    # Query features and convert to a pandas DataFrame
    result = await layer.query(where="1=1")
    df = result.to_frame()

    # Or work with spatial data as a GeoDataFrame
    gdf = result.to_geodataframe()

    # Bulk insert from a DataFrame
    edits = await layer.append(df.head(5).copy())
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
    base_url="https://www.arcgis.com",  # optional; defaults to ArcGIS Online
)
```

**Custom auth** — implement the `ArcGISAuth` abstract base class to plug in your own token
strategy (API keys, OAuth2, keyring-backed credentials, etc.):

```python
class MyCustomAuth(arc.ArcGISAuth):
    async def get_token(self) -> str:
        # your token logic

    async def force_refresh(self) -> None:
        # refresh logic
```

## Services

archibald wraps Esri's REST endpoints with typed service and layer classes:

| Class | Description |
|---|---|
| `FeatureLayer` | Query, add, update, delete, upsert, and sync features; attach, update, and delete attachments |
| `MapLayer` | Query-only access to map service layers |
| `FeatureService` | Service-level metadata and capabilities |
| `MapService` | Map service metadata and operations |

All layers expose:

- `query()` — retrieve features with optional filtering and field selection
- `fields()` — introspect layer schema
- `crs()` — coordinate reference system metadata
- `query_attachments()` — list attachment metadata for one or more features

`FeatureLayer` additionally supports a layered write API:

- `apply_edits()` — fine-grained control over add/update/delete in a single call
- `append()` — bulk insert from a DataFrame
- `upsert()` — insert or update based on key fields
- `sync()` — reconcile a DataFrame with the service: adds missing records, updates changed
  ones, deletes removed ones
- `add_attachments()` — attach files to one or more features
- `update_attachments()` — replace existing attachment files
- `delete_attachments()` — remove attachments from features

## Data Models

**QueryResult** — returned by `query()`:

```python
result = await layer.query(where="population > 10000")

df = result.to_frame()          # pandas DataFrame
gdf = result.to_geodataframe()  # GeoDataFrame (when geometry is present)

# Access raw features and field metadata
features = result.features
fields = result.fields
```

**ApplyEditsResult** — returned by `apply_edits()`, `append()`, `upsert()`, and `sync()`:

```python
edits = await layer.apply_edits(adds=[...], updates=[...], deletes=[...])

if edits.has_failures:
    print("Failed adds:", edits.failed_adds)
    print("Failed updates:", edits.failed_updates)
    print("Failed deletes:", edits.failed_deletes)
```

**FieldsResult** — layer schema information:

```python
fields = await layer.fields()

field_names = fields.names
numeric_fields = fields.filter(
    types=["esriFieldTypeSmallInteger", "esriFieldTypeInteger"]
)
df = fields.to_frame()
```

**AttachmentsQueryResult** — returned by `query_attachments()`:

```python
result = await layer.query_attachments(definition_expression="status = 'open'")

df = result.to_frame()                          # camelCase column names
df = result.to_frame(use_field_names=True)      # ESRI attachment-table field names
```

**AttachmentsResult** — returned by `add_attachments()`, `update_attachments()`, and
`delete_attachments()`:

```python
result = await layer.add_attachments(
    object_ids=42,
    files=Path("photo.jpg"),
)

if result.has_failures:
    print("Failed attachments:", result.failed)

df = result.to_frame()
```

All three attachment write methods accept the same three calling modes:

- **Single** — one object ID and one file
- **Fan-out** — one object ID and multiple files (all attached to the same feature)
- **Multi** — parallel iterables of object IDs and files (one file per feature, run
  concurrently)

## Error Handling

archibald raises typed exceptions for both Esri service errors and client-side errors, including
the common case of HTTP 200 responses that contain embedded error payloads.

```python
try:
    result = await layer.query(where="invalid syntax")
except arc.ArcGISError as e:
    print(f"Error {e.code}: {e.message}")
```

The `ArcGISError` hierarchy:

| Exception | When it's raised |
|---|---|
| `TokenExpiredError` | Token has expired (archibald auto-refreshes and retries) |
| `TokenMissingError` | Token required but not present |
| `AuthorizationError` | Insufficient permissions for the operation |
| `NotFoundError` | Resource not found |
| `ServiceError` | Other Esri service errors |

`ArchieClientError` and its subclasses cover archibald-originated errors (invalid parameters,
unsupported capabilities, etc.).

## Roadmap

1. **Geocoding operations** — suggest and batch geocode endpoints

## Contributing

See [CONTRIBUTING.md](https://github.com/cityofboulder/archibald/blob/main/CONTRIBUTING.md) for
guidance on setting up a development environment, running tests, and submitting pull requests.

## Changelog

See [CHANGELOG.md](https://github.com/cityofboulder/archibald/blob/main/CHANGELOG.md) for
release notes and version history.

## License

MIT — see [LICENSE](https://github.com/cityofboulder/archibald/blob/main/LICENSE) for details.