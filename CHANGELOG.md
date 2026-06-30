# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.3] - 2026-06-29

### Fixed

- `_coerce_datetime` no longer raises `AttributeError` when serializing a date column that contains only null values (object-dtype Series with no `.dt` accessor). Object-dtype Series are now passed through `pd.to_datetime(errors="coerce")` before the timezone logic runs, enabling columns sourced from uncontrolled inputs — Python `datetime` objects, `pd.Timestamp` values, or ISO-format strings — to be coerced correctly. Values that cannot be parsed are sent as null with a `UserWarning`; Series that resolve entirely to `NaT` (all-null or all-unparseable) are returned as all-`None` without a spurious timezone warning.

## [1.1.2] - 2026-06-29

### Fixed

- `ArchieClient` now defaults to a 60-second request timeout instead of httpx's built-in
  5-second default. The timeout is configurable via a new `timeout` constructor parameter
  (`float`, `httpx.Timeout`, or `None` to disable). Large `applyEdits` batches no longer
  raise `ReadTimeoutError` under the default configuration.

## [1.1.1] - 2026-06-26

### Fixed

- Async `applyEdits` polling now uses the correct mixed-case ESRI status strings (`"Completed"`, `"CompletedWithErrors"`) instead of the all-caps `"COMPLETED"` that never matched, causing the poll loop to run until `poll_timeout` was exhausted even after the server had already committed all edits.
- A `"Failed"` async job status now raises `ServiceError` immediately rather than polling until timeout.
- Removed a redundant ESRI error-envelope check inside `_poll_status`; the client's `@handle_esri_errors` decorator already raises before the response reaches the polling loop.

## [1.1.0] - 2026-06-25

### Added

- `BaseLayer.supports_attachments()` checks whether a layer advertises `hasAttachments: true` in its metadata. Promoted from `FeatureLayer` so both feature and map layers inherit it.
- `BaseLayer.supports_query_attachments()`, `BaseLayer.supports_query_attachments_count_only()`, and `BaseLayer.supports_query_attachments_order_by_fields()` report `supportsQueryAttachments` / `supportsQueryAttachmentsCountOnly` / `supportsQueryAttachmentsOrderByFields` from the layer's `advancedQueryCapabilities`.
- `BaseLayer.attachment_fields()` returns a `FieldsResult` built from the layer metadata's `attachmentFields`, describing the columns available on each attachment.
- `BaseLayer.attachment_properties()` returns the layer metadata's `attachmentProperties` crosswalk — each entry maps a camelCase `queryAttachments` response property to its ESRI attachment-table `fieldName` with an `isEnabled` flag.
- `BaseLayer.query_attachments()` queries attachments on feature and map layers, exposing every ESRI `queryAttachments` parameter as a named argument. Guards on `supports_query_attachments()` and, for `return_count_only`, on `supports_query_attachments_count_only()` — the latter raises `LayerCapabilityError` on map layers, which do not support count-only.
- `AttachmentsQueryResult` aggregates the returned `attachmentGroups` plus the layer's `attachmentProperties` crosswalk. `to_frame()` flattens `attachmentInfos` into one row per attachment via `pd.json_normalize` (propagating `parentObjectId`/`parentGlobalId`), or returns one row per parent feature when counting only. Columns are projected onto the crosswalk's enabled entries so empty and non-empty results share an identical schema; `to_frame(use_field_names=True)` renames the default camelCase response columns to their ESRI attachment-table field names (e.g. `name` → `ATT_NAME`). Response-only columns with no crosswalk entry (e.g. `url` from `return_url`) are preserved under either naming mode. When the layer omits `attachmentProperties`, the frame falls back to the raw response columns; requesting `use_field_names` in that case cannot be honored and emits a warning.
- `QueryAttachmentsOperation` validates parameter combinations (requires at least one of `object_ids`/`global_ids`/`definition_expression`, rejects supplying both `object_ids` and `global_ids` since the server silently ignores the former, requires `size` to be a single minimum or a `(min, max)` pair with a present minimum since the server ignores a max-only range, rejects `keywords` / `return_metadata` when the layer's `attachmentProperties` mark the `keywords` / `exifInfo` property disabled, and rejects `order_by_fields` when the layer does not advertise `supportsQueryAttachmentsOrderByFields`), maps named arguments to camelCase API parameters, calls the `queryAttachments` endpoint, and attaches the layer's `attachmentProperties` crosswalk to the result.
- `FeatureLayer.add_attachments()` uploads one or more files to one or more features concurrently via `anyio` task groups. Accepts a scalar `object_id` with a single file (single mode), a scalar `object_id` with an iterable of files (fan-out mode), or parallel `object_ids` and `files` iterables (multi mode). Accepts `Path`, open binary file objects, or raw `bytes`; filenames are auto-detected from the file object and MIME types are guessed from the resolved filename. Guards on `supports_attachments()` and raises `LayerCapabilityError` when the layer does not support attachments.
- `FeatureLayer.update_attachments()` replaces the files of one or more existing attachments concurrently. Accepts the same single / fan-out / multi calling modes as `add_attachments()`, with a parallel `attachment_ids` argument identifying the attachment to replace in each case. Guards on `supports_attachments()` and `supports_update()`, raising `LayerCapabilityError` when the layer does not support attachments or updating.
- `FeatureLayer.supports_update()` reports whether the layer's `capabilities` include the `Update` operation.
- `FeatureLayer.delete_attachments()` deletes one or more attachments from one or more features. Accepts a scalar `object_id` with a scalar `attachment_id` (single mode), a scalar `object_id` with an iterable of `attachment_ids` (fan-out mode), or parallel `object_ids` and `attachment_ids` iterables (multi mode). Groups pairs by OBJECTID internally and fires one concurrent `deleteAttachments` request per unique feature. Result order matches input pair order. Guards on `supports_attachments()` and raises `LayerCapabilityError` when the layer does not support attachments.
- `AttachmentsResult` aggregates per-attachment `EditResultItem` results from add and delete operations. Exposes `has_failures` and `failed` properties, and `to_frame()` which returns a `DataFrame` with error dicts flattened into prefixed columns via `pd.json_normalize`.
- `BaseAttachmentUploadOperation` holds the shared attachment-upload machinery (coercion of parallel iterables, filename resolution, MIME-type guessing, file reading, and concurrent POSTs); concrete subclasses set `_endpoint` (the per-feature endpoint action, from which the response key `f"{_endpoint}Result"` is derived). `AddAttachmentsOperation` (`addAttachment`) and `UpdateAttachmentsOperation` (`updateAttachment`) subclass it. `_coerce_attachments` accepts an optional `attachment_ids` iterable, threaded into each POST as the `attachmentId` form field when updating.
- `DeleteAttachmentsOperation` accepts flat `(object_id, attachment_id)` pairs, groups them by OBJECTID, and fires one concurrent `deleteAttachments` POST per unique feature. Maps response items back to input order by matching on the returned attachment OID.

### Changed

- `EditResultItem` extracted from `apply_edits_result.py` into its own `models/edit_result_item.py` module so it can be imported independently. Re-exported from `apply_edits_result.py` to preserve existing import paths.

## [1.0.0] - 2026-06-01

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
- `FieldsResult.domain_maps` property returns `{field_name: {"to_name": {code: name}, "to_code": {name: code}}}` for all fields carrying a `codedValue` domain. Fields without a domain or with a non-`codedValue` domain type (e.g. `range`) are excluded.
- `QueryResult.to_frame()` and `QueryResult.to_geodataframe()` convert query results to `pandas.DataFrame` and `geopandas.GeoDataFrame` respectively. Both accept `parse_dtypes=True` to apply ESRI→pandas type coercions automatically (dates to UTC-aware datetime, integer fields to nullable `Int64`/`Int32`, etc.). `to_geodataframe()` raises `MissingGeometryError` when the result contains no geometry.
- `QueryResult.apply_coded_values` flag: when `True`, `to_frame()` and `to_geodataframe()` automatically translate coded domain values to their human-readable names after type coercion. Set by passing `apply_coded_values=True` to `BaseLayer.query()`.
- `geometry_to_esri()` converts shapely geometries (Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon) to ESRI JSON dicts with Z-coordinate support. Returns `None` for null geometries; raises `InvalidParameterError` for unsupported types.
- `serialize_features()` converts a `DataFrame` or `GeoDataFrame` to ESRI feature dicts, applying outbound type coercions and optionally pairing geometry. Issues a `UserWarning` for columns that are skipped (non-editable or absent from field metadata). Accepts `apply_coded_values=True` to translate human-readable domain names back to their codes before type coercion.
- `pack_batches()` greedy-packs serialized features and delete IDs into POST body dicts capped at a configurable byte limit (default 1.8 MB).
- `recode_domains(df, fields, *, direction)` added to `archie.serializers._coercions`. Translates coded domain values bidirectionally: `from_esri` maps codes to names, `to_esri` maps names to codes. Unmapped values pass through unchanged. Emits a `UserWarning` when mapped and unmapped non-null values coexist in the same column, as the result will be mixed-type.
- `ApplyEditsOperation.execute()` accepts a `poll_timeout` keyword argument (default 300 s) that caps how long the async polling loop will wait for a server-side job to complete before raising `TimeoutError`.

### Changed

- `enforce_types(df, fields, *, direction)` added to `archie.serializers._coercions` as a unified ESRI ↔ pandas type-coercion function. `direction="from_esri"` applies `ESRI_TO_PANDAS` conversions (integer fields → nullable dtype, dates → UTC-aware datetime); `direction="to_esri"` applies `PANDAS_TO_ESRI` conversions for serialization. `QueryResult._apply_esri_types` and `_coerce_columns` both delegate to it internally.
- `BaseLayer.query()`, `FeatureLayer.apply_edits()`, `append()`, `upsert()`, and `sync()` all accept an `apply_coded_values` keyword argument (default `False`) that threads through to the serialization and result-construction layers.
- `FeatureLayer` now inherits from both `FeatureService` and `BaseLayer` via cooperative MRO; previously it inherited directly from `BaseService`.
- Layer classes (`FeatureLayer`, `MapLayer`, `BaseLayer`) moved to a `services/layers/` sub-package.
- `FieldsResult.names` is now a computed property (was a plain attribute). The `editable_only` parameter is removed; use `FieldsResult.filter(editable=True)` instead.
- `FieldsResult.field_type_map` replaces the former `esri_field_types` attribute.
- Custom exception classes from `archie.errors` are now used consistently throughout the package in place of built-in Python exceptions.
- Import paths simplified: all public symbols are re-exported from their respective sub-package `__init__.py` files.
- `ApplyEditsOperation` now uses server-side async editing only when the payload spans multiple batches. Single-batch payloads always use the synchronous path to avoid unnecessary polling round-trips.

### Fixed

- `ArchieClient` now validates that the base URL ends with `rest/services` at construction time, raising `InvalidServiceURL` on mismatch.
- Query pagination now correctly detects `exceededTransferLimit` in the response body before fanning out additional page requests.
- CRS defaults correctly to the layer's native spatial reference when `out_sr` is not supplied to `QueryOperation`.
- `LayerCapabilityError` is raised (instead of a generic exception) when a caller attempts to query a layer that lacks query capability.
- `UserTokenAuth` token request now sends `referer` instead of `requestip` in the POST body, matching the ESRI `generateToken` API contract.
- Async `applyEdits` polling now uses the correct ESRI status strings (`"COMPLETED"` / `"PROCESSING"`) instead of the geoprocessing-task strings (`esriJobSucceeded` / `esriJobFailed`) that were previously used and caused the polling loop to never exit.
- When an async `applyEdits` job completes, the operation now follows the `resultUrl` returned in the status body to fetch the actual edit results (`addResults`, `updateResults`, `deleteResults`). Previously the status body itself was parsed as the result, which always produced empty result sets.
- Async polling loop is now bounded by `anyio.fail_after`; previously it could spin indefinitely if the server never returned a terminal status.

[Unreleased]: https://github.com/cityofboulder/archibald/compare/v1.1.3...HEAD
[1.1.3]: https://github.com/cityofboulder/archibald/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/cityofboulder/archibald/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/cityofboulder/archibald/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/cityofboulder/archibald/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/cityofboulder/archibald/releases/tag/v1.0.0