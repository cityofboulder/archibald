# Usage Guide

This guide walks through the full workflow: authenticating, connecting to a service, querying data, editing features, and handling errors.

## Authentication

Every `ArchieClient` requires an auth object. Choose the implementation that matches your service's access requirements.

### Public services

Use `NoAuth` for services that require no credentials:

```python
import archie as arc

auth = arc.NoAuth()
```

### Token-based authentication

Use `UserTokenAuth` to authenticate via ESRI's `generateToken` endpoint. Tokens are cached and proactively refreshed before expiry:

```python
auth = arc.UserTokenAuth(
    username="your_username",
    password="your_password",
    base_url="https://your-portal.example.com",  # omit to use ArcGIS Online
    expiration=60,  # token lifetime in minutes; default is 60
)
```

### Custom authentication

Subclass `ArcGISAuth` to implement any custom token flow (OAuth, API keys, etc.):

```python
class MyAuth(arc.ArcGISAuth):
    async def get_token(self) -> str:
        # return a valid token string
        ...

    async def force_refresh(self) -> None:
        # invalidate any cache and fetch a fresh token
        ...
```

---

## Client

`ArchieClient` is the HTTP layer. Every service and layer requires one.

### As a context manager (recommended)

The context manager ensures the underlying HTTP connection pool is properly closed:

```python
async with arc.ArchieClient(
    base_url="https://services.arcgis.com/myOrg/rest/services",
    auth=auth,
) as client:
    # use client here
    ...
```

### Manual lifecycle

If you need to hold a client across multiple scopes, manage it manually:

```python
client = arc.ArchieClient(
    base_url="https://services.arcgis.com/myOrg/rest/services",
    auth=auth,
)
try:
    ...
finally:
    await client.aclose()
```

---

## Services and layers

`archie` distinguishes between *services* (the REST endpoint root) and *layers* (individual layers within a service). In most cases you'll work with layers directly.

### Feature layers

`FeatureLayer` supports querying and all editing operations:

```python
layer = arc.FeatureLayer(
    client=client,
    service_path="MyService/FeatureServer",
    layer_id=0,
)
```

### Map layers

`MapLayer` supports querying only:

```python
layer = arc.MapLayer(
    client=client,
    service_path="MyService/MapServer",
    layer_id=0,
)
```

### Service-level metadata

Use `FeatureService` or `MapService` directly when you need metadata about the service rather than a specific layer:

```python
service = arc.FeatureService(
    client=client,
    service_path="MyService/FeatureServer",
)

crs = await service.crs()
description = await service.description()
max_records = await service.max_record_count()
```

### Layer metadata

Layers expose the same metadata methods plus schema introspection:

```python
fields = await layer.fields()
print(fields.names)  # list of field name strings

objectid = await layer.objectid_field()
crs = await layer.crs()
```

---

## Querying

Use `layer.query()` to retrieve features. Results are automatically paginated when the record count exceeds the service maximum.

### Basic query

```python
result = await layer.query(where="status = 'open'")
```

### Select specific fields

```python
result = await layer.query(
    where="1=1",
    out_fields=["object_id", "name", "status"],
)
```

### Geometry control

```python
# Omit geometry (faster for attribute-only analysis)
result = await layer.query(where="1=1", return_geometry=False)

# Reproject to WGS 84
result = await layer.query(where="1=1", out_sr=4326)
```

### Converting results

```python
# Attributes only as a pandas DataFrame
df = result.to_frame()

# Attributes + geometry as a geopandas GeoDataFrame
gdf = result.to_geodataframe()

# Parse ESRI field types to native Python/pandas dtypes
df = result.to_frame(parse_dtypes=True)
```

### Coded-value domain translation

ESRI services often store numeric codes in fields that map to human-readable labels via a domain. Pass `apply_coded_values=True` to translate codes automatically:

```python
result = await layer.query(where="1=1", apply_coded_values=True)
df = result.to_frame()  # domain codes replaced with labels
```

### Inspecting fields

`FieldsResult` lets you inspect and filter the schema returned by a query:

```python
fields = result.fields

# All field names in response order
print(fields.names)

# Filter to editable integer fields
subset = fields.filter(types=["esriFieldTypeInteger"], editable=True)

# Full schema as a DataFrame
schema_df = fields.to_frame()
```

---

## Editing

Editing is available on `FeatureLayer` only.

### Append

Add all rows in a DataFrame as new features:

```python
edits = await layer.append(df)
```

### Upsert

Insert rows that don't exist yet and update rows that do, matched by one or more key fields:

```python
edits = await layer.upsert(df, key_fields=["service_request_id"])
```

### Sync

Full reconciliation: add missing rows, update changed rows, and delete rows that no longer appear in `df`:

```python
edits = await layer.sync(df, key_fields=["service_request_id"])
```

### Fine-grained control

Use `apply_edits()` directly when you need to mix adds, updates, and deletes in a single call:

```python
edits = await layer.apply_edits(
    adds=rows_to_add,       # DataFrame or list of feature dicts
    updates=rows_to_update,
    deletes=ids_to_delete,  # list of OBJECTID integers
    rollback_on_failure=True,
)
```

### Checking for failures

Edit operations on ESRI services can succeed at the HTTP level but report per-feature failures in the response. Always check `has_failures`:

```python
if edits.has_failures:
    print("Failed adds:", edits.failed_adds)
    print("Failed updates:", edits.failed_updates)
    print("Failed deletes:", edits.failed_deletes)
```

Each item in those lists is an `EditResultItem` with `object_id`, `success`, and `error` attributes.

---

## Error handling

### ESRI errors

`ArcGISError` is raised when ESRI returns an error envelope in the response body (even on HTTP 200). Catch specific subtypes for recoverable conditions:

```python
try:
    result = await layer.query(where="invalid syntax %%")
except arc.AuthorizationError:
    print("Check service permissions")
except arc.NotFoundError:
    print("Layer or service not found")
except arc.ArcGISError as e:
    print(f"ESRI error {e.code}: {e.message}")
    print("Details:", e.details)
```

Token errors (`TokenExpiredError`, `TokenMissingError`) are handled internally by `ArchieClient` — it will attempt a refresh before propagating the exception, so you typically won't need to catch them.

### Client errors

`ArchieClientError` and its subclasses cover configuration mistakes and invalid usage:

```python
try:
    layer = arc.FeatureLayer(
        client=client,
        service_path="MyService/MapServer",  # wrong service type
        layer_id=0,
    )
except arc.InvalidServiceURL:
    print("FeatureLayer requires a FeatureServer path")
```

See the [Exceptions reference](api/exceptions.md) for the full hierarchy.
