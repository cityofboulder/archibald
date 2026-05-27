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

[Unreleased]: https://github.com/cityofboulder/archie