# Plan: Geocoding support (`GeocodeService`)

> **For future chats:** this is the source of truth for the geocode feature. Read §1 (workflow),
> find the first unchecked bullet in §7, and follow the decision log (§6), which is all DECIDED.
> Update checkboxes and the progress log (§10) as work lands.

## 1. Workflow and conventions

- **Bullet lifecycle:** code → user review → tests → user review → commit only when told. One
  bullet at a time.
- **Commits:** atomic (`feat(...)`, `refactor(...)`, `test(...)`, `docs(changelog)`), never combined.
- **Branching:** one `feat/geocode-<phase>` branch per phase → PR into `next-minor`. Don't cut a
  minor release from `next-minor` mid-feature; top-level exports wait until Phase 7.
- **Tests:** `uv run pytest`. Fixtures go in `tests/conftest.py`, builders in `tests/helpers.py`,
  parametrized with `ids=`.
- **Class layout:** `Properties` / `Public methods` / `Private methods` banners, each alphabetical.
- **Models:** `@dataclass`. Closed value sets are `Literal`s, never enums.
- **Operations:** one class per endpoint, constructed with the owning service, `execute()` entry
  point, parameter validation inside the operation (as in `QueryOperation`).
- **All requests are POST** via `client.post(endpoint=..., data=...)` (like `/query` since 1.3.0),
  which avoids URL length limits. `f=json` is enforced by the client.
- Capability checks run in the public service method before delegating to the operation.
- Per-item failures are returned, not raised.

## 2. Goal

| Service method      | Endpoint (POST)          | Shape                                  | Result |
|---------------------|--------------------------|----------------------------------------|--------|
| `suggest()`         | `suggest`                | 1 text → N suggestions                 | `SuggestResult` |
| `find_candidates()` | `findAddressCandidates`  | 1 address → N candidates               | `CandidatesResult` |
| `geocode()`         | `geocodeAddresses`       | N addresses → N best matches (batched) | `GeocodeResult` |
| `reverse_geocode()` | `reverseGeocode`         | N points → N addresses (fan-out)       | `ReverseGeocodeResult` |

Plus `BaseLayer.query(geometry=<shapely>, in_sr=..., spatial_rel=...)`, so that
`layer.query(geometry=item.to_shapely(), in_sr=item.crs)` works for any located result item.

## 3. ESRI API reference (⚠ = verify in Phase 0)

**Service resource `GeocodeServer`:**
- `capabilities`: comma tokens such as `Geocode,ReverseGeocode,Suggest`. Split on commas, because
  `"geocode" in "reversegeocode"` is true.
- `singleLineAddressField.name`: `SingleLine`, or `Single Line Input` on older locators ⚠.
- `addressFields`: multiline inputs. Names vary by locator. These fit `FieldsResult` as-is
  (`names`, `filter(names=)`); `required` is read directly.
- `candidateFields`: valid `outFields`.
- `spatialReference`.
- `locatorProperties`: `SuggestedBatchSize`, `MaxBatchSize` (batch support signal ⚠),
  `MinimumMatchScore`, `MinimumCandidateScore`, `IntersectionConnectors` ⚠.

**findAddressCandidates:** `SingleLine` | multiline fields | `SingleLine`+`magicKey`. Returns
`{spatialReference, candidates:[{address, location, score, attributes, extent}]}`. A miss returns
empty `candidates`, not an error.

**geocodeAddresses:** `addresses={"records":[{"attributes":{"OBJECTID":n, ...}}]}`. Each record's
`OBJECTID` comes back as `attributes.ResultID`, which is how results map to inputs (response order
is irrelevant). `Status` is M/T/U. An unmatched location may be NaN or absent ⚠. Batches larger than
`MaxBatchSize` are rejected. This endpoint has no async/statusUrl mode (confirmed).

**reverseGeocode:** `location`, `distance`, `outSR`, `featureTypes`, `locationType`,
`returnIntersection`, `langCode`, `preferredLabelValues`. A miss is an error envelope with code 400
and the detail text "Unable to find address for the specified location." ⚠

**suggest:** `text`, `location`, `searchExtent`, `maxSuggestions`, `category`, `countryCode`,
`preferredLabelValues`. Returns `{suggestions:[{text, magicKey, isCollection}]}`.

**All four accept POST** ⚠ (verify on the City locator).

### Tuning options (named kwargs; anything else goes through `**kwargs`)

| Option (python → ESRI) | Type | Endpoints |
|---|---|---|
| `location_type` → `locationType` | `LocationType = Literal["rooftop", "street"]` | find, geocode, reverse |
| `preferred_label_values` → `preferredLabelValues` | `list[PreferredLabelValue]`, `Literal["postalCity","localCity","matchedCity","primaryStreet","matchedStreet"]` ⚠ | all four |
| `feature_types` → `featureTypes` | `list[FeatureType]`, `Literal["StreetInt","DistanceMarker","StreetAddress","StreetName","POI","Subaddress","PointAddress","Postal","Locality"]` ⚠ | reverse |
| `category` | `str \| list[str]` (open set, no Literal) | suggest, find, geocode |
| `source_country` / `country_code` | `str` (ISO) | find, geocode / suggest |
| `lang_code` → `langCode` | `str` | find, geocode, reverse |
| `match_out_of_range` → `matchOutOfRange` | `bool \| None` | find, geocode |
| `for_storage` → `forStorage` | `bool \| None` | find, geocode, reverse |
| `return_intersection` → `returnIntersection` | `bool` | reverse |
| `location` + `in_sr` | shapely `Point` (bias) | suggest, find |
| `search_extent` + `in_sr` | shapely geometry → envelope from `.bounds` | suggest, find, geocode |
| `max_locations` / `max_suggestions` / `distance` | positive int / int / float (m) | find / suggest / reverse |
| `out_fields`, `out_sr` | validated against `candidateFields` / int | find, geocode (out_sr also reverse) |

`Literal` values are runtime-validated with the shared helper (D10). Custom locators may ignore
some options; docstrings say so.

### Spatial reference rule (applies everywhere geometry is passed in)
The SR is never assumed:
- `GeoSeries`/`GeoDataFrame` supply it via `.crs.to_epsg()` (raise if it has none).
- Bare shapely geometry requires `in_sr`; otherwise `InvalidParameterError`.
- An explicit `in_sr` that disagrees with `.crs` raises.

Output CRS always comes from the response's `spatialReference`, never `service.crs()`.

### Geometry serialization
No new serializer. The existing `geometry_to_esri()` (`serializers/_geometry.py`) already produces
the point/envelope bodies. Callers attach `"spatialReference": {"wkid": in_sr}` and `json.dumps` at
the call site. The only addition is `esri_geometry_type(geom) -> str` in `_geometry.py` (Point →
`esriGeometryPoint`, MultiPoint → `esriGeometryMultipoint`, (Multi)LineString →
`esriGeometryPolyline`, (Multi)Polygon → `esriGeometryPolygon`), which query needs for
`geometryType`.

## 4. Gaps the plan covers (beyond the original sketch)

Capability token parsing; locator-driven field names; 1:1 input/result alignment via
`OBJECTID = position`; input joins in `to_frame`; per-batch failure capture; locator-aware
screening exemptions; reverse no-match arriving as an exception; the SR rule; batch-size bounds;
no-batch locators; normalization; dedupe; `LayerCapabilityError` naming; query geometry; docs,
changelog, exports, smoke script, integration test.

## 5. Target architecture

```
src/archibald/
  _literals.py                         validate_literal_values() (generalized from ApplyEditsResult._filter_values)
  errors.py                            + failure_error(); + AddressNotFoundError classification in parse_esri_error
  exceptions.py                        + CapabilityError, ServiceCapabilityError, RejectedAddressError, AddressNotFoundError
  services/geocode_service.py          GeocodeService
  services/layers/base.py              query(): + geometry / in_sr / spatial_rel
  operations/query.py                  geometry param building
  operations/{suggest,find_address_candidates,geocode_addresses,reverse_geocode}.py
  serializers/_addresses.py            normalize, single/multiline formatting, screening rules, records, dedupe, chunking
  serializers/_geometry.py             + esri_geometry_type()
  models/_frames.py                    shared frame helpers extracted from ApplyEditsResult
  models/{suggest_result,candidates_result,geocode_result,reverse_geocode_result}.py
```

**Statuses**
```python
GeocodeStatus = Literal["matched", "tied", "low_score", "unmatched", "rejected", "failed"]
ReverseGeocodeStatus = Literal["matched", "unmatched", "failed"]
```
- `rejected` items carry `rule` + `reason`.
- `failed` items carry the `failure_error()` dict (`code`, `description`, `exception`,
  `outcome_unknown`, optional `status_url`), the same shape as edits, so the frame columns match.

**Located items** (`AddressCandidate`, `GeocodeResultItem`, `ReverseGeocodeItem`) have:
- a `crs: int | None` field (from the response's `spatialReference`);
- `to_shapely() -> Point`, which raises `MissingGeometryError` when there is no location
  (unmatched, rejected, failed).

**`GeocodeResult`** mirrors `ApplyEditsResult`:
- `has_failures` and per-status properties;
- `filter(statuses=)`;
- `to_frame(include_input=, include_metadata=, metadata_prefix="_geocode_")` and `to_geodataframe()`;
- `_inputs`.

## 6. Decision log (all DECIDED 2026-11-24)

| ID | Decision |
|----|----------|
| D1 | `feat/geocode-<phase>` branch per phase → PR into `next-minor`. |
| D2 | Add `CapabilityError(ArchieClientError)`. Re-parent `LayerCapabilityError` under it (non-breaking) and add `ServiceCapabilityError(CapabilityError)`. |
| D3 | `geocode()` → `geocodeAddresses` (batch best match); `find_candidates()` → `findAddressCandidates` (single, N candidates, `magic_key`). |
| D4 | Screening rules are pure functions `(text, ctx) -> Rejection \| None`, keyed by name. **All four on by default:** `empty` (all fields blank / None / NaN / NA after normalization), `po_box` (P.O. Box / PO BX / POB / Post Office Box / "Box 12"; PMB, General Delivery and RR/HC-Box are settled in Phase 0 with real data), `numeric_only` (exempts 5- and 9-digit ZIPs), `alpha_only` (exempts strings containing a locator `IntersectionConnectors` token, falling back to `&`, `@`, `\|`, ` and `). `screen=True` (default set) / `False` / collection of rule names (unknown names → `InvalidParameterError`). Single-line input screens the normalized string. Multiline screens the street field (the locator's first `addressFields` entry, overridable with `street_field=`); `empty` checks all mapped fields. |
| D5 | `RejectedAddressError(InvalidParameterError)` with `.rule` and `.reason` attributes. `find_candidates()` raises it. Batch `geocode()` returns `rejected` items instead. |
| D6 | A locator without batch support → `geocode()` raises `ServiceCapabilityError`. No fallback for now. |
| D7 | `dedupe=True` by default. The key is the casefolded normalized single line, or a tuple of normalized multiline values. Only the first occurrence is sent (its position is the OBJECTID); its result is copied to every duplicate position. `dedupe=False` sends every row. |
| D8 | `AddressNotFoundError(ServiceError)` lives in `exceptions.py` (ESRI-originated section). `errors.parse_esri_error` picks the class through a new private `_error_class(code, message, details)`: first `_ESRI_CODE_MAP`, then code 400 with any detail or message matching the module constant `_ADDRESS_NOT_FOUND = re.compile(r"unable to find address", re.I)` → `AddressNotFoundError`, else `ServiceError`. Because `handle_esri_errors` already calls `parse_esri_error` at `_request`, the classification applies automatically with no new decorator. It stays backwards compatible: it subclasses `ServiceError`, which is what those envelopes raise today. `ReverseGeocodeOperation` catches `AddressNotFoundError` → `unmatched` item; any other exception → `failed`. Trade-off: one regex runs per error envelope (negligible), and if the text varies across server versions, only the constant changes (verified in Phase 0). |
| D9 | `min_score: float \| None` (0–100, validated). In `geocode()`, an M/T result scoring below it becomes status `low_score` and keeps score, match address and location. In `find_candidates()`, candidates below it are dropped. `score` is always a column. |
| D10 | Generalize, don't duplicate. (a) `errors.failure_error(exc, *, outcome_unknown, status_url=None) -> dict` holds the envelope-vs-exception logic now inside `failed_items`/`EditResultItem._from_exception`; both become thin callers. Geocode failures use it with `outcome_unknown=is_outcome_unknown(exc)`. (b) `ApplyEditsResult`'s `_attach_metadata`, `_concat_frames`, `_geometry_spec`, `_restore_int_columns`, `_error_frame`, `_fallback_description` move to `models/_frames.py` as functions, and `ApplyEditsResult` delegates to them. (c) `_filter_values` → `_literals.validate_literal_values(values, literal_type, name)`, reused by `filter()` and the tuning-option `Literal`s. All three are behavior-preserving refactors: the existing tests must pass unchanged. |
| D11 | World Geocoder is out of scope beyond `**kwargs`/`for_storage`; the City locators are the target. |
| D12 | Batch concurrency is bounded by the client's `max_concurrent_requests`. |
| D13 | Query geometry: `BaseLayer.query(..., geometry=None, in_sr=None, spatial_rel="esriSpatialRelIntersects")`. A shapely geometry is serialized with `geometry_to_esri`, `geometryType` comes from `esri_geometry_type`, and `inSR` is required (SR rule). A `str` or `dict` geometry passes through unchanged (a dict is `json.dumps`'d) so existing `**kwargs` callers keep working. `SpatialRel` is a `Literal` of the ESRI `esriSpatialRel*` names. Buffering (`distance`/`units`) stays `**kwargs`. |
| D14 | Async/job-based batch geocoding is **dropped**. `geocodeAddresses` has no async mode; the only job route is the `GeocodingTools/GPServer/BatchGeocode` GP task, which needs a staged hosted table or portal item. |

## 7. Phases

### Phase 0: Discovery (no PR)
- [ ] 0.1 Capture `GeocodeServer` metadata from each City locator. Record capability tokens,
      single-line field name, addressFields, candidateFields, locatorProperties keys and SR.
- [ ] 0.2 Capture POST responses:
      - find: match / tie / none;
      - geocodeAddresses: mixed M/T/U, the unmatched location shape, and an oversize-batch error;
      - reverse: a hit, plus the exact no-match envelope (finalizes `_ADDRESS_NOT_FOUND`);
      - suggest: a hit and an empty result.
      Confirm each endpoint accepts POST.
- [ ] 0.3 Check which tuning values the City locator honors (`locationType`,
      `preferredLabelValues`, `featureTypes`) and settle the edge cases of the `po_box` rule
      against real address data.
- [ ] 0.4 Turn the captures into sanitized builders in `tests/helpers.py`, and clear the ⚠ marks.

### Phase 1: Foundations (`feat/geocode-foundations`)
- [ ] 1.1 Exceptions per D2/D5/D8 in `exceptions.py`, exported from `archibald/__init__.py`.
- [ ] 1.2 Refactor: `errors.failure_error()` (D10a).
- [ ] 1.3 Refactor: `_literals.validate_literal_values()` (D10c).
- [ ] 1.4 Refactor: `models/_frames.py` extraction (D10b).
- [ ] 1.5 `GeocodeService(BaseService)`, `expected_type = "GeocodeServer"`, with the private
      `_capabilities() -> set[str]` and `supports_{geocode,batch_geocode,reverse_geocode,suggest}()`.
      Export from `services/__init__.py`.

### Phase 2: Query geometry (`feat/geocode-query-geometry`)
- [ ] 2.1 `esri_geometry_type()` in `serializers/_geometry.py`.
- [ ] 2.2 `geometry` / `in_sr` / `spatial_rel` on `BaseLayer.query` → `QueryOperation._build_params`
      (D13). Check that `_fetch_remaining_pages` keeps `geometry`, `geometryType`, `inSR` and
      `spatialRel` in the count request; it should, since they are not in `not_for_count`.

### Phase 3: Suggest (`feat/geocode-suggest`)
- [ ] 3.1 `Suggestion` + `SuggestResult` (`to_frame()`).
- [ ] 3.2 `SuggestOperation`:
      - `text` is non-empty after strip;
      - `max_suggestions` is a positive int;
      - `location` / `search_extent` follow the SR rule;
      - `preferred_label_values` are Literal-validated.
- [ ] 3.3 `GeocodeService.suggest()`.

### Phase 4: Find candidates (`feat/geocode-candidates`)
- [ ] 4.1 `serializers/_addresses.py` formatting functions:
      - `normalize_address()`: strip, collapse whitespace, NFC, and None/NaN/NA → "";
      - `format_single_line()`;
      - `format_multiline(record, field_map, address_fields)`: validates that targets exist and
        that required fields are present.
- [ ] 4.2 Screening rules + `screen_address()` (D4).
- [ ] 4.3 Service accessors: `single_line_field()`, `address_fields()`, `candidate_fields()`,
      `intersection_connectors()`.
- [ ] 4.4 `AddressCandidate` + `CandidatesResult`:
      - `to_frame()` and `to_geodataframe()`;
      - `crs` taken from the response;
      - `to_shapely()` on candidates.
- [ ] 4.5 `FindAddressCandidatesOperation`:
      - single-line, multiline and `magic_key` modes, mutually exclusive;
      - `out_fields` validated like `QueryOperation._validate_fields`;
      - `max_locations` is a positive int;
      - `min_score` drops candidates below it;
      - a screened-out address raises `RejectedAddressError`;
      - tuning options per §3.
- [ ] 4.6 `GeocodeService.find_candidates()`.

### Phase 5: Batch geocode (`feat/geocode-batch`)
- [ ] 5.1 Input normalization:
      - accepts `str | Iterable[str] | Iterable[dict] | Series | DataFrame`, plus
        `address_column` / `field_map` / `street_field`;
      - keeps a shallow copy of the input frame for joins;
      - positions are taken from a reset index, and the original index is preserved for
        `to_frame`.
- [ ] 5.2 Record building:
      - set `OBJECTID = position`;
      - screened-out rows become `rejected` and are set aside;
      - dedupe (D7) builds the representative → duplicates map.
- [ ] 5.3 `suggested_batch_size()` / `max_batch_size()`, batch-size resolution
      (`1 ≤ n ≤ MaxBatchSize`), and count-based chunking.
- [ ] 5.4 `GeocodeResultItem` + `GeocodeResult` + `GeocodeStatus`, built on `models/_frames.py`.
- [ ] 5.5 `GeocodeAddressesOperation`:
      - fan out with a task group;
      - map `ResultID → position`, then fan results out to duplicates;
      - M/T/U → status, with the `min_score` → `low_score` relabel;
      - handle the NaN location;
      - a failed batch becomes `failed` items via `failure_error`, without cancelling its siblings;
      - merge in the `rejected` items and order everything by position.
- [ ] 5.6 `GeocodeService.geocode()`: checks Geocode and batch capability (D6).

### Phase 6: Reverse geocode (`feat/geocode-reverse`)
- [ ] 6.1 `AddressNotFoundError` classification in `errors.parse_esri_error` (D8).
- [ ] 6.2 Input normalization: `Point | Iterable[Point] | GeoSeries | GeoDataFrame`, following the
      SR rule.
- [ ] 6.3 `ReverseGeocodeItem` + `ReverseGeocodeResult`: input join, `to_geodataframe()` using the
      returned location, and `to_shapely()`.
- [ ] 6.4 `ReverseGeocodeOperation`:
      - one POST per point, fanned out;
      - `distance > 0`;
      - `feature_types` / `location_type` are Literal-validated;
      - `AddressNotFoundError` → `unmatched`, anything else → `failed`.
- [ ] 6.5 `GeocodeService.reverse_geocode()`.

### Phase 7: Release polish (`feat/geocode-docs`)
- [ ] 7.1 Top-level and `models/__init__` exports: the service, results, items, and the status /
      tuning Literals.
- [ ] 7.2 Docs: `docs/api/services.md`, `docs/api/models.md`, and a `docs/usage.md` geocoding
      section covering:
      - the suggest → magic_key → find_candidates flow;
      - screening;
      - dedupe;
      - min_score;
      - geocode → `layer.query(geometry=item.to_shapely(), in_sr=item.crs)`.
- [ ] 7.3 CHANGELOG `Unreleased`: `Added`, plus `Changed` for the `LayerCapabilityError` parent and
      the `query` geometry param. This can also be done per phase as separate `docs(changelog)`
      commits.
- [ ] 7.4 `scripts/smoke_test_geocode.py` against a City locator.
- [ ] 7.5 `tests/integration/test_geocode_service.py` (respx, `@pytest.mark.integration`).

## 8. Testing strategy

- Mirrored test files for every new module. Refactor bullets (1.2–1.4) add no tests and must leave
  the existing suite green and unchanged.
- Fixtures cover these metadata variants:
  - `SingleLine` vs `Single Line Input`;
  - a locator without Suggest;
  - a locator without batch support;
  - World-style vs custom address fields.
- Must-have cases:
  - Capabilities and errors:
    - a `ReverseGeocode`-only locator → `supports_geocode()` is False;
    - an `AddressNotFoundError` classification that leaves other 400s as `ServiceError`.
  - Batch geocode:
    - shuffled `ResultID`s;
    - one failed batch among several;
    - all rows rejected (no request sent);
    - empty input;
    - duplicates fanned out (and `dedupe=False`);
    - `low_score` relabel;
    - `batch_size > MaxBatchSize`.
  - Input validation:
    - the SR rule (bare shapely without `in_sr`, and a disagreeing CRS);
    - an invalid Literal value;
    - `RejectedAddressError` carrying `.rule`.
  - Query backcompat: a string `geometry` via kwargs is unchanged.
- Screening rules get heavy parametrization, including every exemption.

## 9. Out of scope

- Async/job-based batch geocoding (D14).
- API-key auth / World Geocoder specifics (D11).
- Address parsing or standardization beyond normalization.
- A batch-to-candidates fallback (D6).

## 10. Progress log

| Date | Bullet | Branch / commit | Notes |
|------|--------|-----------------|-------|
|      |        |                 |       |
