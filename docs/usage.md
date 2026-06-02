# Usage Guide

## Introduction

This guide walks through the full workflow: authenticating, connecting to a service, querying data, editing features, and handling errors.

The `archibald` library is built around object-injection. In order to interact with a service, layer, geocoder, etc, an `auth` and `client` object both need to be defined first.

---

## Authentication

`ArcGISAuth` objects handle header management for http calls performed by an `ArchieClient`. Choose the implementation that matches your service's access requirements.

### Public services

Use `NoAuth` for services that require no credentials and are completely public. This is usually the best option when attempting to access ESRI Open Data layers.

```python
import archibald as arc

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

To access an item in an organization's enterprise Portal, inject the url into the `base_url` parameter (e.g. `base_url="https://gis.bouldercolorado.gov/portal`)

This url is separate from the one used to build the `client`. This URL tells the client where to go for generating a token, not where to go to access the service.

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

`ArchieClient` is the async HTTP layer in charge of making authenticated requests to the urls underlying the ArcGIS REST API. Every service and layer requires client to work.

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

`archibald` distinguishes between *services* (the REST endpoint root) and *layers* (individual layers within a service). In most cases you'll work with layers directly.

### Map layers

`MapLayer` supports querying only:

```python
layer = arc.MapLayer(
    client=client,
    service_path="MyService/MapServer",
    layer_id=0,
)
```

### Feature layers

`FeatureLayer` supports querying and all editing operations:

```python
layer = arc.FeatureLayer(
    client=client,
    service_path="MyService/FeatureServer",
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

### Inspecting fields

`layer.fields()` returns a `FieldsResult`: a container holding the full ESRI field definitions for the layer. It provides name lists, type metadata, and coded-value domain information, and can be filtered down to a subset or converted to a DataFrame for inspection:

```python
fields = await layer.fields()

# All field names in definition order
print(fields.names)

# Filter to editable integer fields
subset = fields.filter(types=["esriFieldTypeInteger"], editable=True)

# Full schema as a DataFrame (one row per field, columns: name, type, alias, length, …)
schema_df = fields.to_frame()
```

`FieldsResult` also appears at `result.fields` on every `QueryResult`, where it is pre-filtered to only the fields that were returned by that query.

---

## Querying

Use `layer.query()` to retrieve features. Results are automatically paginated when the record count exceeds the service maximum.

### Parameter reference

`layer.query()` accepts Pythonic arguments that archibald translates into ESRI REST parameters before sending the request:

| `layer.query()` argument | ESRI REST parameter | Default |
|---|---|---|
| `where` | `where` | `"1=1"` |
| `out_fields` | `outFields` | all fields |
| `return_geometry` | `returnGeometry` | `True` |
| `out_sr` | `outSR` | service CRS |
| `**kwargs` | passed through verbatim | — |

Two parameters are managed by archibald:

- **`f`** — set to `geojson` automatically when `return_geometry=True` (for reliable geometry decoding); falls back to `json` otherwise. This parameter cannot be overridden.
- **`orderByFields`** — defaults to `OBJECTID ASC` for deterministic pagination; override via kwargs if needed

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

Field names are validated against the layer schema before the request is sent; an `InvalidParameterError` is raised immediately if a name doesn't match (case-sensitive).

### Geometry control

```python
# Omit geometry (faster for attribute-only analysis)
result = await layer.query(where="1=1", return_geometry=False)

# Reproject to WGS 84
result = await layer.query(where="1=1", out_sr=4326)
```

### Additional kwargs

ESRI's query endpoint supports a wide array of [additional parameters](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/#request-parameters). Pass any of them as keyword arguments and they will be forwarded to the request verbatim.

Common examples:

```python
# Override default sort order
result = await layer.query(where="1=1", orderByFields="created_date DESC")

# Spatial filter — features within a bounding box (WGS 84)
result = await layer.query(
    where="1=1",
    geometry="-105.3,39.9,-105.1,40.1",
    geometryType="esriGeometryEnvelope",
    spatialRel="esriSpatialRelIntersects",
    inSR=4326,
)
```

### Converting results

`layer.query()` returns a `QueryResult`: a lightweight container holding the raw features and field metadata. Call `.to_frame()` or `.to_geodataframe()` on it to get a usable DataFrame:

```python
# Attributes only as a pandas DataFrame
df = result.to_frame()

# Attributes + geometry as a geopandas GeoDataFrame
gdf = result.to_geodataframe()

# Parse ESRI field types to native Python/pandas dtypes
# Helpful for converting unix ms timestamps to pandas datetimes, among others
df = result.to_frame(parse_dtypes=True)
```

### Coded-value domain translation

ESRI services often store numeric codes in fields that map to human-readable labels via a coded-value domain. Pass `apply_coded_values=True` to translate those codes automatically on conversion:

```python
result = await layer.query(where="1=1", apply_coded_values=True)
df = result.to_frame()  # domain codes replaced with labels
```

**What happens to each value:**

| Value | Outcome |
|---|---|
| Code present in the domain | Replaced with its label (e.g. `1` → `"Active"`) |
| `None` / null | Preserved as `None` — never translated |
| Code absent from the domain | Passed through unchanged as the original code value |
| Field has no domain at all | Column left unchanged |

The pass-through behavior for unmapped codes is intentional — archibald never silently drops data. However, if a column contains a mix of successfully translated values *and* unmapped codes, the result will be a mixed-type column (e.g., some `str` labels alongside raw `int` codes). A `UserWarning` is emitted in that case to flag the inconsistency; a column where *all* non-null values are unmapped stays uniform and produces no warning.

`apply_coded_values=True` also implies `parse_dtypes=True` behavior for any field that has a domain — ESRI field types are coerced to their pandas equivalents first so that code lookups match on type (e.g., integer `1` matches integer keys in the domain map, not string `"1"`).

---

## Editing

Editing is available on `FeatureLayer` only. All editing methods accept a standard pandas `DataFrame` or geopandas `GeoDataFrame`. There is no need to construct ESRI JSON feature dicts by hand.

### What happens automatically

Before any data reaches the API, archibald runs a serialization pipeline on your DataFrame:

1. **Field selection** — only fields the service marks as editable are included. Any DataFrame column that doesn't map to an editable field is dropped, and a `UserWarning` is emitted so you know what was excluded. For updates, the OBJECTID column is always carried through regardless of editability.
2. **Type coercion** — pandas types are converted to ESRI JSON-compatible values automatically:
    - `datetime64` (tz-aware or naive) → integer milliseconds since UTC epoch; `NaT` → `null`
    - Nullable integers (`Int16`, `Int32`, `Int64`) → Python `int`; `pd.NA` → `null`
    - `float` → `NaN` becomes `null`
    - Strings → truncated to the field's defined `length` if one is set on the service, with a warning
3. **Geometry serialization** — if you pass a `GeoDataFrame`, each row's geometry is converted to ESRI JSON automatically. Null geometries are omitted from the feature dict rather than sent as null.
4. **Automatic batching** — large payloads are split into batches bounded by ~1.8 MB and POSTed to the service in parallel on the server side, so you can write large DataFrames without worrying about request size limits. 

### Append

Add all rows in a DataFrame as new features. OBJECTIDs are excluded and the service assigns them after upload:

```python
edits = await layer.append(df)

new_oids = [add.object_id for add in edits.add_results]
```

### Upsert

Insert rows that don't exist yet in the layer and update rows that do, matched by one or more key fields:

```python
edits = await layer.upsert(df, key_fields=["service_request_id"])
```

### Sync

Full reconciliation: add missing rows, update changed rows, and delete rows that no longer appear in `df`:

```python
edits = await layer.sync(df, key_fields=["service_request_id"])
```

### Fine-grained control

Use `apply_edits()` directly when you need explicit control over which rows are added, updated, or deleted. Deletes can be a list of OBJECTID integers, a `Series`, or a full `DataFrame` with an OBJECTID column:

```python
edits = await layer.apply_edits(
    adds=rows_to_add,
    updates=rows_to_update,
    deletes=ids_to_delete,
    rollback_on_failure=True,
)
```

### Round-trip domain translation

Because `apply_coded_values` works in both directions, archibald supports a clean read-modify-write workflow without ever touching raw domain codes:

```python
# 1. Query with labels — domain codes are expanded to human-readable strings
result = await layer.query(where="1=1", apply_coded_values=True)
df = result.to_frame()

# 2. Work with readable values
df.loc[df["status"] == "Pending", "status"] = "Active"

# 3. Write back — labels are translated back to codes before the request is sent
edits = await layer.append(df, apply_coded_values=True)
```

Unmapped values follow the same pass-through rules as on the read side — a value absent from the domain is sent as-is.

### Checking for failures

ESRI's `applyEdits` endpoint can return HTTP 200 while still reporting per-feature failures in the response body. Always check `has_failures` before assuming success:

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
