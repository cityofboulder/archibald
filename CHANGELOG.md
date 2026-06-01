# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add a suite of exceptions split into those that are raised by the ESRI API (`ArcGISError`) and those raised by the `archie` tool itself (`ArchieClientError`).
- Error handling for quirky ESRI response errors. Functions exist for both parsing ESRI errors (`parse_esri_error()`) and handling ESRI errors for callers as a decorator (`handle_esri_errors()`).
- Base async auth handler class called `ArcGISAuth` that mandates a `get_token()` method in any subclasses.
- User token auth flows, where a user supplies a username and password in exchange for a token from ESRI's generateToken endpoint. Implemented as `UserTokenAuth`.
- Base httpx client that handles authentication, enforces response formatting, and routes get and post requests from any endpoint. Implemented as `ArchieClient`.
- Base service class that handles service metadata retreival, url validation, and client injection, implemented as `BaseService`.
- `QueryResult` data class will be returned from all feature layer queries. Has attributes for features returned, field names, whether features are geojson, and the output crs if geometries are returned.
- `FieldsResult` data class returned from querying a feature layer for field names, types, etc.
- `QueryOperation` executes queries against a feature layer with automatic pagination. Validates requested field names against the layer's field metadata, builds ESRI REST query parameters with deterministic `OBJECTID ASC` ordering by default, and fans out remaining pages in parallel via `anyio` task groups when `exceededTransferLimit` is returned. Geometry output is always encoded as GeoJSON; CRS defaults to the layer's native spatial reference when `out_sr` is not provided.
- `FeatureLayer` service class represents a single ESRI FeatureServer layer. Caches layer-level metadata (field definitions, `objectIdField`, `globalIdField`, capabilities) on first access. Exposes `objectid_field()`, `globalid_field()`, `supports_query()`, and `fields()` accessors. Provides a `query()` method that guards against layers lacking query capability and delegates to `QueryOperation`.
- `NoAuth` auth handler for anonymous/public ArcGIS services. Satisfies the `ArcGISAuth` interface but injects no token.
- `FeatureService` service class representing a FeatureServer endpoint; validates the service path and provides service-level metadata.
- `MapService` service class representing a MapServer endpoint; same metadata interface as `FeatureService`.
- `BaseLayer` abstract base class for individual service layers. Extends `BaseService` with a `layer_id` parameter. Caches layer-level metadata (fields, `objectIdField`, `globalIdField`, capabilities) on first access and exposes `objectid_field()`, `globalid_field()`, `supports_query()`, `fields()`, and `query()`.
- `MapLayer` read-only layer class for MapServer layers. Inherits MapServer path validation from `MapService` and query capability from `BaseLayer`.
- `ApplyEditsResult` and `EditResultItem` data classes model the response from `applyEdits`. `ApplyEditsResult` exposes `has_failures`, `failed_adds`, `failed_updates`, and `failed_deletes` properties and supports merging multiple per-batch results via `ApplyEditsResult.merge()`.
- `ApplyEditsOperation` executes `applyEdits` calls against a `FeatureLayer`. Serializes adds (OBJECTID excluded) and updates (OBJECTID included), normalizes deletes from `DataFrame`, `Series`, or `list[int]`, greedy-packs payloads into ≤ 1.8 MB batches, fans out batch POSTs in parallel via `anyio` task groups, and polls async job status with exponential backoff (0.5–5 s) when the layer declares async edit support.
- `FeatureLayer.apply_edits()` accepts `adds`, `updates`, and `deletes` (all optional) and delegates to `ApplyEditsOperation`. Issues a `UserWarning` when `rollback_on_failure=True` but the layer does not advertise that capability.
- `FeatureLayer.append()` convenience method that adds all rows of a `DataFrame` or `GeoDataFrame` as new features.
- `FeatureLayer.upsert()` queries the layer to identify existing keys, partitions incoming rows into adds and updates, and applies both in a single `apply_edits` call. Raises `InvalidParameterError` if key fields are unknown or produce duplicates.
- `FeatureLayer.sync()` performs a full dataset replacement keyed on caller-supplied fields: adds absent features, updates matching ones, and deletes features in the layer that have no match in the incoming data.
- `FieldsResult.filter()` returns a new `FieldsResult` restricted by any combination of field names, ESRI type strings, editability, or nullability. `names` and `types` are mutually exclusive; raises `InvalidParameterError` on unrecognised type strings.
- `QueryResult.to_frame()` and `QueryResult.to_geodataframe()` convert query results to `pandas.DataFrame` and `geopandas.GeoDataFrame` respectively. Both accept `parse_dtypes=True` to apply ESRI→pandas type coercions automatically (dates to UTC-aware datetime, integer fields to nullable `Int64`/`Int32`, etc.). `to_geodataframe()` raises `MissingGeometryError` when the result contains no geometry.
- `geometry_to_esri()` converts shapely geometries (Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon) to ESRI JSON dicts with Z-coordinate support. Returns `None` for null geometries; raises `InvalidParameterError` for unsupported types.
- `serialize_features()` converts a `DataFrame` or `GeoDataFrame` to ESRI feature dicts, applying outbound type coercions and optionally pairing geometry. Issues a `UserWarning` for columns that are skipped (non-editable or absent from field metadata).
- `pack_batches()` greedy-packs serialized features and delete IDs into POST body dicts capped at a configurable byte limit (default 1.8 MB).

### Changed

- `FeatureLayer` now inherits from both `FeatureService` and `BaseLayer` via cooperative MRO; previously it inherited directly from `BaseService`.
- Layer classes (`FeatureLayer`, `MapLayer`, `BaseLayer`) moved to a `services/layers/` sub-package.
- `FieldsResult.names` is now a computed property (was a plain attribute). The `editable_only` parameter is removed; use `FieldsResult.filter(editable=True)` instead.
- `FieldsResult.field_type_map` replaces the former `esri_field_types` attribute.
- Custom exception classes from `archie.errors` are now used consistently throughout the package in place of built-in Python exceptions.
- Import paths simplified: all public symbols are re-exported from their respective sub-package `__init__.py` files.

### Fixed

- `ArchieClient` now validates that the base URL ends with `rest/services` at construction time, raising `InvalidServiceURL` on mismatch.
- Query pagination now correctly detects `exceededTransferLimit` in the response body before fanning out additional page requests.
- CRS defaults correctly to the layer's native spatial reference when `out_sr` is not supplied to `QueryOperation`.
- `LayerCapabilityError` is raised (instead of a generic exception) when a caller attempts to query a layer that lacks query capability.
- `UserTokenAuth` token request now sends `referer` instead of `requestip` in the POST body, matching the ESRI `generateToken` API contract.

[Unreleased]: https://github.com/cityofboulder/archie