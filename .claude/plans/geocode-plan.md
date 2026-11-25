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
- **Models:** `@dataclass`. Closed value sets are `Literal`s, never enums. Named `Literal`s used or
  exported in more than one place live in `models/_literals.py` (with `validate_literal_values`)
  and are re-exported publicly; one-off parameter `Literal`s stay inline.
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

## 3. ESRI API reference

Verified 2026-11-24 against the two reference locators (both public, ArcGIS Server 11.0, no auth):
- **City:** `locators/City_Of_Boulder_Address_Locator/GeocodeServer`
- **County:** `locators/Boulder_County_Address_Locator/GeocodeServer`

Both are under `https://gis.bouldercolorado.gov/ags_svr1/rest/services`. Raw captures are at
`C:\Users\nestj1\geocode-captures\{city,county}`, made by the Phase 0 script (§11). Anything still
unverified is marked ⚠.

Also verified against five Boulder County locators. These are public, run on ArcGIS Server 10.91,
and live under `https://maps.bouldercounty.org/arcgis/rest/services/GeocodingServices`; captures
are in `geocode-captures\bocounty\<name>`. Four are **classic** (built with the legacy Create Address Locator tool: `AddrParcels_…`,
`ParcelLocator_with_SitusAddress_ArcMap`, `…_ArcMap2`, `TRANSPORTATION_Loc_Centerlines_AliasSt_wCity`),
and one is **modern** (built with Create Locator: `BRETSA_StreetCenterline_…`). **The code must handle both families.**

**Family = locator format, not authoring app.** ESRI calls Create Address Locator output *classic locators*. That tool existed in ArcMap and in Pro up to 2.6–2.9, was deprecated in favor of Create Locator (Pro 2.2+, Enterprise 10.6.1+), and Pro 3.0 removed classic support. `AddrParcels_20220907_created_w_pro_2_6_3` was apparently built in Pro 2.6.3, yet it is classic and behaves exactly like the ArcMap-built ones. Modern locators carry `locatorProperties.LocatorVersion`; BRETSA reports `"11.0"` on a 10.91 server, so the key describes the locator format, not the server.

| Behavior | Modern (City, County, BRETSA) | Classic (4 County locators) |
|---|---|---|
| Single-line field | `SingleLine` | `Single Line Input` |
| `addressFields` | World-style | `Street, City[, ZIP]` |
| Unmatched `location` | key absent | `{"x": "NaN", "y": "NaN"}` (strings) |
| `attributes.X/Y` when U | `0` | `0` |
| `locatorProperties` scalars | ints / bools | **strings** (`"93"`, `"true"`), except `MaxBatchSize`/`SuggestedBatchSize`, which are ints |
| `IntersectionConnectors` | absent | TRANSPORTATION: `"& @ \| and at"` (space-separated) |
| Intersection input | U | TRANSPORTATION: T, `StreetInt`, score 95.76 |
| Bad `locationType` / `preferredLabelValues` / `featureTypes` | 400 / 400 / ignored | all silently ignored |
| Reverse `address` keys | rich (`Match_addr`, `Addr_type`, `LongLabel`, …) | `Street, City[, ZIP], Match_addr`, **no `Addr_type`** |
| Scores | ints in practice | floats (93.13, 94.95) |
| `MinimumMatchScore` | 75 | 85–93 |
| Response SR | `{wkid, latestWkid}`; BRETSA `wkid 102653`, `latestWkid 2231` | TRANSPORTATION: **`{"wkt": …}` only, no wkid** |
| Response order | shuffled | sometimes in input order, sometimes shuffled |

**Suggest support is unreliable:**
- `AddrParcels` advertises `Suggest` but `/suggest` returns 400 `"Invalid URL."` (details
  `"Server environment property not found: requestProperties"`).
- `ParcelLocator_…_ArcMap` and `TRANSPORTATION` don't advertise it and fail the same way.
- `…_ArcMap2` advertises it and it works, including the magicKey round-trip.
- So a capability check can't promise a working endpoint; the server's 400 propagates as
  `ServiceError`.

**Service resource `GeocodeServer`:**
- `capabilities`: `"Geocode,ReverseGeocode,Suggest"`, or `"Geocode,ReverseGeocode"` on two classic
  locators. Split on commas, because `"geocode" in "reversegeocode"` is true.
- `singleLineAddressField.name`: `SingleLine` (modern) or `Single Line Input` (classic). Always read
  the name from metadata.
- `addressFields`: World-style on both (`Address, Address2, Address3, Neighborhood, City,
  Subregion, Region, Postal, PostalExt, CountryCode`), all `required: false`. These fit
  `FieldsResult` as-is.
- `candidateFields`: 58 on both; these are the valid `outFields`. County also lists
  `locatorProperties.enabledOutputFields`.
- `spatialReference`: City is `2876` (State Plane CO North, ftUS); County is `4326`.
- `locatorProperties`:

  | Locator | MaxBatchSize | SuggestedBatchSize | MinimumMatchScore | MinimumCandidateScore |
  |---|---|---|---|---|
  | City | 500 | 150 | 75 | 70 |
  | County | 1000 | 1000 | 75 | 70 |

  Both also have `supportsBatchOutFields: "True"` (a string). **Neither has
  `IntersectionConnectors`**, so the fallback connector list is what gets used. `MaxBatchSize` is
  treated as the batch-support signal; there is no no-batch locator to compare against ⚠.

**findAddressCandidates:** `SingleLine` | multiline fields | `SingleLine`+`magicKey`; all three
verified.
- Returns `{spatialReference, candidates:[{address, location, score, attributes, extent}]}`, and a
  miss returns empty `candidates`.
- Ambiguous input ("Broadway, Boulder, CO") returns 5 candidates, all scoring 100 with
  `Addr_type` StreetName.
- `Addr_type` and the other attributes are absent unless `outFields` asks for them.

**geocodeAddresses:** `addresses={"records":[{"attributes":{"OBJECTID":n, ...}}]}`.
- Each record's `OBJECTID` is echoed as `attributes.ResultID`; non-sequential IDs were verified.
- **Response order is shuffled on both locators**, so map by `ResultID` only.
- `Status` is M/T/U.
- **An unmatched (`U`) location has no `location` key at all, and `attributes.X`/`Y` are `0.0`.**
  Use `Status`; never read coordinates from `X`/`Y`.
- Response keys are `{locations, spatialReference}`, and each location has
  `{address, score, attributes[, location]}`.
- An oversize batch was not captured; a hand-built fixture is used instead (batch_size is
  validated before sending).
- There is no async/statusUrl mode.

**reverseGeocode:**
- A hit returns `{address: {...Match_addr, Addr_type...}, location: {x, y, spatialReference}}`.
- A miss is verified as `{"error": {"code": 400, "message": "Cannot perform query. Invalid query
  parameters.", "details": ["Unable to find address for the specified location."]}}`. Other 400s
  read "Unable to complete operation." with their own details, so the D8 regex does not catch them.
- **A plain `"x,y"` location without a spatialReference is read in the locator's SR, not WGS84.** A
  lon/lat pair missed on City (2876) and hit on County (4326). This confirms the SR rule; always
  send `spatialReference`.
- **The search radius works differently by locator family** (verified 2026-11-24 with sweeps and
  a 16-point walk into open space; the Enterprise reverseGeocode reference documents the modern
  rules):
  - **Modern locators: `featureTypes` controls the radius, and `distance` does not exist.**
    The 11.0 server's own reverseGeocode form lists `location, featureTypes, langCode,
    locationType, outFields, outSR, preferredLabelValues, returnInputLocation`, with no
    `distance` and no unit parameter. Rules:
    - With no `featureTypes`, the default hierarchy applies, each type with its own tolerance:
      StreetInt 10 m (returned only if requested), near StreetAddress/StreetName 3 m, POI/Parcel
      centroid 25 m, Subaddress 10 m, PointAddress 50 m, distant StreetAddress/StreetName 100 m,
      then area features "within boundary".
    - **A single `featureTypes` value searches only that type, out to 500 m.**
    - Multiple values use the per-type defaults again.
    - Measured: the default and multi-value runs hit at 86–87 m and missed beyond. Single
      `PointAddress`, `StreetAddress` or `StreetName` hit up to 482 m and missed past ~500 m.
      `distance=500`, alone or with `distanceUnit=meters` or `units=esriSRUnit_Meter`, changed
      nothing.
  - **Classic locators honor `distance`, in meters, defaulting to ~100 m, and ignore `featureTypes` entirely, both as a radius and as a filter.** On `AddrParcels`, `parcel2` and `transp`, a single `featureTypes` value returned the same result as the default, including the same `Addr_type`. Hits flip exactly where
    the radius crosses the true distance (68 m: miss at 25, hit at 100; 411 m: miss at 250, hit
    at 1000; 3 m: miss at 0.01, hit at 5). The World geocoder also documents `distance` (out of
    scope, D11).
  - **Family detection:** modern locators carry `locatorProperties.LocatorVersion` (`"11.0"`
    on City, County, BRETSA). The four classic locators lack it and instead carry
    `SpellingSensitivity`/`MatchIfScoresTie` with string-typed scalars. Exposed as
    `GeocodeService.is_classic_locator()` (D15).
- `outFields` (address object only) and `returnInputLocation` (bool; when true, the location
  object holds the input x/y) exist on modern-locator reverseGeocode. `returnIntersection` is undocumented
  in the Enterprise reference; `featureTypes=StreetInt` is the documented route. Both returned
  the same intersection on the modern City locator.
- `featureTypes=StreetInt` and `returnIntersection=true` both return an intersection
  (`Addr_type` StreetInt).

**suggest:**
- Returns `{suggestions:[{text, magicKey, isCollection}]}`, and gibberish returns `[]`.
- `maxSuggestions=1000` is accepted silently (2 results).
- The `magicKey` round-trip through findAddressCandidates was verified.

**All four endpoints, and the service resource itself, accept POST** on both locators.

**Validation of tuning values on the server is inconsistent.** An invalid `locationType` returns
400 "The locationType value entered is not supported." An invalid `preferredLabelValues` returns
400 `Invalid values for "preferredValueNames"`. An invalid `featureTypes` is **silently ignored**.
Client-side `Literal` validation is therefore the only guard for some options.

### Tuning options (named kwargs; anything else goes through `**kwargs`)

| Option (python → ESRI) | Type | Endpoints |
|---|---|---|
| `location_type` → `locationType` | `LocationType = Literal["rooftop", "street"]` | find, geocode, reverse |
| `preferred_label_values` → `preferredLabelValues` | `list[PreferredLabelValue]`, `Literal["postalCity","localCity","matchedCity","primaryStreet","matchedStreet"]` (`matchedCity`/`primaryStreet` verified; rest per ESRI docs) | all four |
| `feature_types` → `featureTypes` | `list[FeatureType]`, `Literal["StreetInt","Subaddress","PointAddress","Parcel","StreetAddress","StreetName","POI","DistanceMarker","Locality","Postal"]` (the Enterprise reference list). **On modern locators one value widens the search to 500 m; several values use per-type defaults. Classic locators ignore it entirely (D15 warns).** The server ignores bad values, so client validation matters. | reverse |
| `return_input_location` → `returnInputLocation` | `bool \| None` | reverse (modern) |
| `out_fields` → `outFields` | validated against `candidateFields` | reverse (address object only) |
| `category` | `str \| list[str]` (open set, no Literal) | suggest, find, geocode |
| `source_country` / `country_code` | `str` (ISO) | find, geocode / suggest |
| `lang_code` → `langCode` | `str` | find, geocode, reverse |
| `match_out_of_range` → `matchOutOfRange` | `bool \| None` | find, geocode |
| `for_storage` → `forStorage` | `bool \| None` | find, geocode, reverse |
| ~~`return_intersection`~~ | not a named kwarg; the documented route is `feature_types=["StreetInt"]`, and the legacy param still works via `**kwargs` | (reverse) |
| `location` + `in_sr` | shapely `Point` (bias) | suggest, find |
| `search_extent` + `in_sr` | shapely geometry → envelope from `.bounds` | suggest, find, geocode |
| `max_locations` / `max_suggestions` | positive int / positive int | find / suggest |
| `distance` | float meters `> 0`; **classic locators only**. On a modern locator it warns (D15) and is still sent; there, use a single `feature_types` value for a 500 m radius. | reverse |
| `out_fields`, `out_sr` | validated against `candidateFields` / int | find, geocode (out_sr also reverse) |

`Literal` values are runtime-validated with the shared helper (D10). Classic locators silently
ignore every tuning option tested, and modern locators reject some invalid values with a 400.
Docstrings say an option may be a no-op depending on the locator.

### Spatial reference rule (applies everywhere geometry is passed in)
The SR is never assumed. An SR is `int | str`: a WKID, or a WKT string for services that have no
WKID.
- `GeoSeries`/`GeoDataFrame` supply it via `.crs.to_epsg()`, falling back to
  `.crs.to_wkt("WKT1_ESRI")`. A missing `.crs` raises.
- Bare shapely geometry requires `in_sr`; otherwise `InvalidParameterError`.
- An explicit `in_sr` that disagrees with `.crs` raises.
- Serialized as `{"wkid": n}` or `{"wkt": s}`.

**Output SR** always comes from the response's `spatialReference`, never `service.crs()`. It is
resolved in the order `latestWkid` → `wkid` → `wkt`. One small private helper,
`sr_from_esri(sr_json) -> int | str | None` in `serializers/_geometry.py`, is shared by every
model; its pair `sr_to_esri(sr) -> dict` is used for requests. Both pyproj and geopandas accept a
WKID or WKT directly.

**Pre-existing bug (not part of this feature):** `BaseService.crs()` reads only `latestWkid` and
defaults to 3857, so a WKT-only service (like `TRANSPORTATION_…`) would report 3857. It affects
any MapServer or FeatureServer published with a custom SR. Fix it separately as a `fix/` branch
→ `main`.

### Geometry serialization
No new geometry serializer. The existing `geometry_to_esri()` (`serializers/_geometry.py`) already
produces the point/envelope bodies. Callers attach `"spatialReference": sr_to_esri(in_sr)` and
`json.dumps` at the call site. The only addition is `esri_geometry_type(geom) -> str` in `_geometry.py` (Point →
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
  errors.py                            + failure_error(); + AddressNotFoundError classification in parse_esri_error
  exceptions.py                        + CapabilityError, ServiceCapabilityError, RejectedAddressError, AddressNotFoundError
  services/geocode_service.py          GeocodeService
  services/layers/base.py              query(): + geometry / in_sr / spatial_rel
  operations/query.py                  geometry param building
  operations/{suggest,find_address_candidates,geocode_addresses,reverse_geocode}.py
  serializers/_addresses.py            normalize, single/multiline formatting, screening rules, records, dedupe, chunking
  serializers/_geometry.py             + esri_geometry_type()
  serializers/_frames.py               shared frame helpers extracted from ApplyEditsResult
  models/_literals.py                  shared named Literals (EditKind, EditStatus, then the geocode ones) + validate_literal_values()
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
- a `crs: int | str | None` field (WKID or WKT, from the response's `spatialReference` via
  `sr_from_esri`);
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
| D4 | Screening: **only `empty` is on by default**; `screen=None` or `screen=()` disables screening completely; `po_box`, `numeric_only` and `alpha_only` are opt-in (`screen=SCREEN_RULES` for all). See **D4 detail** below the table. |
| D5 | `RejectedAddressError(InvalidParameterError)` with `.rule` and `.reason` attributes. `find_candidates()` raises it. Batch `geocode()` returns `rejected` items instead. With the D4 defaults, only an empty address raises by default; other rules raise only when the caller opts in. `screen=None`/`()` never raises. |
| D6 | A locator without batch support → `geocode()` raises `ServiceCapabilityError`. No fallback for now. |
| D7 | `dedupe=True` by default. The key is the casefolded normalized single line, or a tuple of normalized multiline values. Only the first occurrence is sent (its position is the OBJECTID); its result is copied to every duplicate position. `dedupe=False` sends every row. |
| D8 | `AddressNotFoundError(ServiceError)` lives in `exceptions.py` (ESRI-originated section). `errors.parse_esri_error` picks the class through a new private `_error_class(code, message, details)`: first `_ESRI_CODE_MAP`, then code 400 with any detail or message matching the module constant `_ADDRESS_NOT_FOUND = re.compile(r"unable to find address", re.I)` → `AddressNotFoundError`, else `ServiceError`. Because `handle_esri_errors` already calls `parse_esri_error` at `_request`, the classification applies automatically with no new decorator. It stays backwards compatible: it subclasses `ServiceError`, which is what those envelopes raise today. `ReverseGeocodeOperation` catches `AddressNotFoundError` → `unmatched` item; any other exception → `failed`. Trade-off: one regex runs per error envelope (negligible), and if the text varies across server versions, only the constant changes. Verified in Phase 0: the miss is a code-400 envelope with details `["Unable to find address for the specified location."]` on both locators, and other 400s ("Unable to complete operation.") don't match. |
| D9 | `min_score: float \| None` (0–100, validated). In `geocode()`, an M/T result scoring below it becomes status `low_score` and keeps score, match address and location. In `find_candidates()`, candidates below it are dropped. `score` is always a column. |
| D10 | Generalize, don't duplicate. (a) `errors.failure_error(exc, *, outcome_unknown, status_url=None) -> dict` holds the envelope-vs-exception logic now inside `failed_items`/`EditResultItem._from_exception`; both become thin callers. Geocode failures use it with `outcome_unknown=is_outcome_unknown(exc)`. (b) `ApplyEditsResult`'s `_attach_metadata`, `_concat_frames`, `_geometry_spec`, `_restore_int_columns`, `_error_frame`, `_fallback_description` move to `serializers/_frames.py` as functions (revised 2026-11-25: serializers already holds module-level pandas helpers; models are one class per module), and `ApplyEditsResult` delegates to them. (c) `_filter_values` → `models._literals.validate_literal_values(values, literal_type, name)`, reused by `filter()` and the tuning-option `Literal`s. All three are behavior-preserving refactors: the existing tests must pass unchanged. |
| D11 | World Geocoder is out of scope beyond `**kwargs`/`for_storage`; the City locators are the target. |
| D12 | Batch concurrency is bounded by the client's `max_concurrent_requests`. |
| D13 | Query geometry: `BaseLayer.query(..., geometry=None, in_sr=None, spatial_rel="esriSpatialRelIntersects")`. A shapely geometry is serialized with `geometry_to_esri`, `geometryType` comes from `esri_geometry_type`, and `inSR` is required (SR rule). A `str` or `dict` geometry passes through unchanged (a dict is `json.dumps`'d) so existing `**kwargs` callers keep working. `SpatialRel` is a `Literal` of the ESRI `esriSpatialRel*` names. Buffering (`distance`/`units`) stays `**kwargs`. |
| D15 | **DECIDED 2026-11-24.** Locator-family warnings for options the family ignores. `GeocodeService.is_classic_locator()` returns True when `locatorProperties` lacks `LocatorVersion` (ESRI's term for Create Address Locator output; verified on 7 locators, including a Pro-2.6.3-built classic one). `reverse_geocode` emits a `UserWarning` when (a) `distance` is passed to a modern locator (ignored; a single `feature_types` value searches up to 500 m) or (b) `feature_types` is passed to a classic locator (ignored as both filter and radius; use `distance`). The values are still sent (harmless). This mirrors `apply_edits`' warnings for unsupported `rollback_on_failure` / `use_server_async`. There is no client-side emulation. The method is named for the format, never the authoring app. |
| D14 | Async/job-based batch geocoding is **dropped**. `geocodeAddresses` has no async mode; the only job route is the `GeocodingTools/GPServer/BatchGeocode` GP task, which needs a staged hosted table or portal item. |

### D4 detail: screening

Screening rules are pure functions `(text, ctx) -> Rejection | None`, keyed by name. **Only `empty` is on by default** (revised 2026-11-24 per CLAUDE.md's no-assumptions rule). The test for a default: a rule may be on by default only if it can never change a result the locator would otherwise produce, so it only saves a request and explains the miss. `empty` passes that test; the other three encode locator-dependent policy and are opt-in.

**API:**

- `screen: Iterable[ScreenRule] | None = ("empty",)`, where `ScreenRule = Literal["empty", "po_box", "numeric_only", "alpha_only"]`.
- **`screen=()` or `screen=None` turns screening off completely**, including `empty`.
- An exported `SCREEN_RULES` tuple holds all four, so "everything" is `screen=SCREEN_RULES`.
- Unknown names → `InvalidParameterError`, via `validate_literal_values`.

**Rules** (definitions finalized from Phase 0 data):

- `empty`: all fields blank / None / NaN / NA after normalization.
- `po_box`: all forms (P.O. Box / PO Box / PO BX / POB / Post Office Box / bare "Box N" / PMB, even with a street present / General Delivery / RR N Box N / HC N Box N). Every form returned `U` on all 7 locators, but the World geocoder and postal-role locators can match these, so it is opt-in.
- `numeric_only`: exempts 5- and 9-digit ZIPs. Whether those match depends on the locator having a postal role, so it is opt-in.
- `alpha_only`: rejects digit-free input, **including street-only addresses such as "Broadway, Boulder, CO"**. Those match at StreetName level (T, score 100) on all three modern locators. This demonstrably changes outcomes, so it is opt-in. It exempts strings containing a locator `IntersectionConnectors` token. The property is a space-separated string (`"& @ | and at"` on `TRANSPORTATION_…`, which does geocode intersections). When the key is absent, as on most locators, the fallback is that same list. Symbol connectors match anywhere; word connectors (`and`, `at`) match only as whole words, so "Atlantic Ave" is not exempt.

**Scope:** single-line input screens the normalized string. Multiline screens the street field (the locator's first `addressFields` entry, overridable with `street_field=`); `empty` checks all mapped fields.

## 7. Phases

### Phase 0: Discovery (no PR)
- [x] 0.1 Capture `GeocodeServer` metadata from each City locator. Record capability tokens,
      single-line field name, addressFields, candidateFields, locatorProperties keys and SR.
- [x] 0.2 Capture POST responses:
      - find: match / tie / none;
      - geocodeAddresses: mixed M/T/U and the unmatched location shape;
      - reverse: a hit, plus the exact no-match envelope (finalizes `_ADDRESS_NOT_FOUND`);
      - suggest: a hit and an empty result.
      Confirm each endpoint accepts POST. The oversize-batch error was skipped by decision; it
      gets a hand-built fixture.
- [x] 0.3 Check which tuning values the City locator honors (`locationType`,
      `preferredLabelValues`, `featureTypes`) and settle the edge cases of the `po_box` rule
      against real address data.
- [x] 0.4 Clear the ⚠ marks. The few that remain can't be verified on these locators. Writing the
      captures into fixture builders moved into the phases: each bullet adds the
      `tests/helpers.py` builders it needs, modeled on the captures in
      `C:\Users\nestj1\geocode-captures`. The captures come from public services and public
      addresses and contain no secrets.

### Phase 1: Foundations (`feat/geocode-foundations`)
- [x] 1.1 Exceptions per D2/D5/D8 in `exceptions.py`, exported from `archibald/__init__.py`:
      - `AddressNotFoundError(ServiceError)` (ESRI section; class only, classification is 6.1);
      - `CapabilityError(ArchieClientError)`; `LayerCapabilityError` re-parented under it;
        `ServiceCapabilityError(CapabilityError)`;
      - `RejectedAddressError(InvalidParameterError)`, `__init__(rule, reason)` stores `.rule` /
        `.reason`, message `"Address rejected by '<rule>' rule: <reason>"`.
      - Tests: the existing `TestHierarchy` gained the new classes and `ids=`; plus
        catchability and `RejectedAddressError` attribute/message tests.
- [x] 1.2 Refactor: `errors.failure_error()` (D10a).
      - Envelope `ArcGISError` → its error dict (`{**error, "status_url": ...}` only when given);
        otherwise the dict `_from_exception` used to build.
      - `EditResultItem._from_exception` builds its error with `failure_error`. `failed_items` is
        **deprecated** (shipped in 1.3.0, public by name; removal in 2.0): it was a model factory
        living in `errors.py` (the cause of the import cycle). Its callers (`apply_edits.py`,
        `attachments.py` ×2) call `_from_exception` directly; the deprecated wrapper keeps a
        function-local `EditResultItem` import until 2.0.
      - No shared item superclass: edit and geocode items share only `error`. Revisit a base
        class for the located items (`crs` + `to_shapely()`) in Phases 4–6.
      - Tests: `TestFailedItems` became `TestFailureError` (same cases; the per-ID ordering test
        was dropped as covered by `_from_exception`'s tests).
- [x] 1.3 Refactor: `models/_literals.py` (D10c), decided 2026-11-25 over `archibald/` and
      `serializers/` (keeps the aliases next to their validator; avoids the `_date_literals` name clash).
      - `validate_literal_values(values, literal_type, name) -> set | None`: body of
        `ApplyEditsResult._filter_values`, calling `get_args` itself. `filter()` uses it;
        `_filter_values` is deleted.
      - `EditKind` / `EditStatus` move here; `edit_result_item.py` re-imports them (in its
        `__all__`), so every existing import path still works. Same objects, so no deprecation.
      - Later `Literal`s (`GeocodeStatus`, `ReverseGeocodeStatus`, `ScreenRule`, `LocationType`,
        `PreferredLabelValue`, `FeatureType`, `SpatialRel`) are defined here too. Private module so
        the validator isn't public API; aliases are public via `models/__init__` / `archibald`.
      - No new tests.
- [x] 1.4 Refactor: `serializers/_frames.py` extraction (D10b).
      - Public: `attach_metadata`, `concat_frames`, `error_frame(errors: list[dict | None])`
        (generalized from items to raw error dicts), `geometry_spec`; private:
        `_fallback_description`, `_restore_int_columns`. Bodies moved as-is.
      - `ApplyEditsResult` drops the six methods and calls the functions.
      - Tests: the `_concat_frames` / `_geometry_spec` / `_error_frame` test classes move from
        `tests/models/test_apply_edits_result.py` to `tests/serializers/test_frames.py`
        (`TestConcatFrames` / `TestGeometrySpec` / `TestErrorFrame`), assertions unchanged, in their
        own `test(...)` commit. Decided 2026-11-25 over keeping delegate methods.
- [x] 1.5 `GeocodeService(BaseService)`, `expected_type = "GeocodeServer"`, with the private
      `_capabilities() -> set[str]` and `supports_{geocode,batch_geocode,reverse_geocode,suggest}()`.
      Export from `services/__init__.py`. Docstrings say these report *advertised* support:
      `AddrParcels_…` advertises Suggest and still returns 400.
      - `_capabilities`: comma-split, strip, lowercase, drop empties.
      - `max_batch_size() -> int | None` (Properties banner; async like `crs()`), `int()`-coerced,
        None when absent. Pulled forward from 5.3.
      - `supports_batch_geocode`: `supports_geocode()` and `max_batch_size()` `> 0`.
      - Tests: `geocode_service` fixture (conftest), `make_geocode_metadata(capabilities=...,
        locator_properties=...)` builder and `GEOCODE_SERVICE_PATH` (helpers), modeled on
        `city/01_metadata.json`. Cases: path validation; each `supports_*` across full caps,
        classic `"Geocode,ReverseGeocode"`, `"ReverseGeocode"` only (substring trap), missing key;
        batch across MaxBatchSize present / absent / `0` / Geocode not advertised.

### Phase 2: Query geometry (`feat/geocode-query-geometry`)
- [ ] 2.1 In `serializers/_geometry.py`: `esri_geometry_type()`, plus `sr_to_esri()` /
      `sr_from_esri()` (WKID or WKT; `latestWkid` → `wkid` → `wkt`; see the SR rule).
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
- [ ] 4.2 Screening rules, `ScreenRule`/`SCREEN_RULES`, and `screen_address()` (D4): `empty` is the only default; `None`/`()` disables screening.
- [ ] 4.3 Service accessors: `single_line_field()`, `address_fields()`, `candidate_fields()`,
      `intersection_connectors()` (space-split, with the D4 fallback). A private
      `_locator_property(name, cast, default)` coerces the classic locators' string scalars
      (`"93"`, `"true"`) and is reused by the 5.3 accessors.
- [ ] 4.4 `AddressCandidate` + `CandidatesResult`:
      - `to_frame()` and `to_geodataframe()`;
      - `crs` from the response via `sr_from_esri`, so it may be a WKT string;
      - `score` is a float;
      - attributes vary by locator (26 to 58 candidate fields), so they are kept as a raw dict and
        flattened in frames;
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
- [ ] 5.3 `suggested_batch_size()` (`max_batch_size()` landed in 1.5), batch-size resolution
      (`1 ≤ n ≤ MaxBatchSize`), and count-based chunking.
- [ ] 5.4 `GeocodeResultItem` + `GeocodeResult` + `GeocodeStatus`, built on `serializers/_frames.py`.
- [ ] 5.5 `GeocodeAddressesOperation`:
      - fan out with a task group;
      - map `ResultID → position`, then fan results out to duplicates;
      - M/T/U → status, with the `min_score` → `low_score` relabel;
      - status alone decides whether there is a location. A `U` result's location is absent
        (modern) or `{"x": "NaN", "y": "NaN"}` strings (classic), and `attributes.X/Y` are `0`, so
        never read coordinates for `U`;
      - a failed batch becomes `failed` items via `failure_error`, without cancelling its siblings;
      - merge in the `rejected` items and order everything by position.
- [ ] 5.6 `GeocodeService.geocode()`: checks Geocode and batch capability (D6).

### Phase 6: Reverse geocode (`feat/geocode-reverse`)
- [ ] 6.1 `AddressNotFoundError` classification in `errors.parse_esri_error` (D8).
- [ ] 6.2 Input normalization: `Point | Iterable[Point] | GeoSeries | GeoDataFrame`, following the
      SR rule.
- [ ] 6.3 `ReverseGeocodeItem` + `ReverseGeocodeResult`: input join, `to_geodataframe()` using the
      returned location, and `to_shapely()`. The `address` dict varies by locator: modern locators return
      `Match_addr`, `Addr_type`, `LongLabel`, …, while classic returns only
      `Street, City[, ZIP], Match_addr`. Keep the raw dict, and make `match_address` required and
      `address_type` optional.
- [ ] 6.4 `ReverseGeocodeOperation`:
      - one POST per point, fanned out;
      - `distance > 0`; the D15 warnings for `distance` on modern and `feature_types` on classic locators (need `is_classic_locator()`, added with
        the 4.3 accessors);
      - `out_fields`, `return_input_location`;
      - `feature_types` / `location_type` are Literal-validated;
      - `AddressNotFoundError` → `unmatched`, anything else → `failed`.
- [ ] 6.5 `GeocodeService.reverse_geocode()`.

### Phase 7: Release polish (`feat/geocode-docs`)
- [ ] 7.1 Top-level and `models/__init__` exports: the service, results, items, and the status /
      tuning Literals.
- [ ] 7.2 Docs: `docs/api/services.md`, `docs/api/models.md`, `docs/api/exceptions.md` (lists each
      exception explicitly and lacks the four from 1.1: `CapabilityError`,
      `ServiceCapabilityError`, `RejectedAddressError`, `AddressNotFoundError`), and a `docs/usage.md` geocoding
      section covering:
      - the suggest → magic_key → find_candidates flow;
      - screening;
      - dedupe;
      - min_score;
      - geocode → `layer.query(geometry=item.to_shapely(), in_sr=item.crs)`.
- [ ] 7.3 CHANGELOG `Unreleased`: `Added`, plus `Changed` for the `LayerCapabilityError` parent and
      the `query` geometry param, plus `Deprecated`: "`archibald.errors.failed_items()` emits
      `DeprecationWarning` and will be removed in 2.0; use `failure_error()` for the error dict." This can also be done per phase as separate `docs(changelog)`
      commits.
- [ ] 7.4 `scripts/smoke_test_geocode.py` against a City locator.
- [ ] 7.5 `tests/integration/test_geocode_service.py` (respx, `@pytest.mark.integration`).

## 8. Testing strategy

- Mirrored test files for every new module. Refactor bullets (1.2–1.4) add no tests and must leave
  the existing suite green and unchanged (except the 1.2 `failed_items` → `failure_error` test
  rework and the 1.4 test move to `tests/serializers/test_frames.py`).
- Fixtures cover these metadata variants, modeled on the real captures:
  - modern (City) vs classic (`TRANSPORTATION_…`): `SingleLine` vs `Single Line Input`, World-style
    vs `Street/City/ZIP` fields, int vs string `locatorProperties`, and present vs absent
    `IntersectionConnectors`;
  - a locator without Suggest;
  - a locator without batch support (hand-built);
  - a WKT-only spatialReference;
  - `wkid` ≠ `latestWkid` (102653/2231).
- Response shapes to cover:
  - an unmatched location that is absent vs `{"x": "NaN", "y": "NaN"}`;
  - a classic reverse `address` with no `Addr_type`;
  - float scores;
  - the advertised-but-broken suggest 400 propagating as `ServiceError`.
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
| 2026-11-24 | Phase 0 (0.1–0.4) | none (no code) | Both reference locators captured; §3 verified; D4/D8 finalized. Oversize capture skipped. |
| 2026-11-24 | Phase 0 addendum | none (no code) | 5 Boulder County 10.91 locators captured (4 classic, 1 Pro). Added the classic-vs-Pro table, the WKT/`latestWkid` SR handling (`sr_from_esri`/`sr_to_esri`), string `locatorProperties` coercion, the real `IntersectionConnectors` format, and the advertised-but-broken Suggest. Found pre-existing `BaseService.crs()` WKT bug (separate fix). |
| 2026-11-24 | Reverse radius | none (no code) | First conclusion ("Pro ignores distance") was wrong. Pro locators have no `distance` param; the radius comes from `featureTypes` (one value = 500 m, verified to 482 m). Classic locators honor `distance` in meters. Unit params do nothing. Added the `Parcel` feature type, `out_fields`/`return_input_location`, dropped the named `return_intersection`, D15 proposed. |
| 2026-11-24 | Locator family naming | none (no code) | Family is the locator format (classic = Create Address Locator, modern = Create Locator), not Pro vs ArcMap: Pro-2.6.3-built `AddrParcels` is classic. Classic locators also ignore `featureTypes` entirely. `is_pro_locator()` → `is_classic_locator()`; D15 now warns in both directions. |
| 2026-11-24 | D4 defaults | none (no code) | Per CLAUDE.md's no-assumptions rule, only `empty` is on by default; `po_box`/`numeric_only`/`alpha_only` are opt-in. `screen=None` or `()` disables screening; `SCREEN_RULES` enables all. D5 note updated. |
| 2026-11-24 | D15 approved | none (no code) | `is_classic_locator()` plus two-way reverse_geocode warnings approved. |
| 2026-11-25 | Phase 1 detailed | none (no code) | Phase 1 bullets expanded. Frame helpers go to `serializers/_frames.py`, not `models/` (models are one class per module; serializers already holds module-level pandas helpers). Their direct tests move to `tests/serializers/test_frames.py` instead of keeping delegate methods. |
| 2026-11-25 | 1.1 | `feat/geocode-foundations` c707441, e240954 | Exceptions added and exported; `TestHierarchy` reworked with ids. `RejectedAddressError` stays under `InvalidParameterError`. |
| 2026-11-25 | 1.2 | `feat/geocode-foundations` bc10489, 28e1d72 | `failure_error` added; `failed_items` deleted (callers use `_from_exception`), so `errors.py` imports no models. Superclass for items rejected for now. |
| 2026-11-25 | 1.2 follow-up | `feat/geocode-foundations` cd60130, 11b4c20 | `failed_items` restored as a deprecated wrapper instead of removed (shipped in 1.3.0; mirrors the `merge`/`from_esri_response` precedent). CHANGELOG entry queued in 7.3. |
| 2026-11-25 | 1.3 | `feat/geocode-foundations` (see git log) | `models/_literals.py` holds shared named Literals + `validate_literal_values`; `EditKind`/`EditStatus` moved there and re-exported (no deprecation needed). Frame helpers (1.4) confirmed for `serializers/_frames.py`. |
| 2026-11-25 | 1.4 | `feat/geocode-foundations` (see git log) | Frame helpers moved to `serializers/_frames.py`; `error_frame` takes error dicts. Direct helper tests moved to `tests/serializers/test_frames.py`; the two `_metadata_frame`-based error tests stayed with `ApplyEditsResult`. |
| 2026-11-25 | 1.5 | `feat/geocode-foundations` (see git log) | `GeocodeService` with comma-split capability checks and `max_batch_size()`; verified against all 7 captured locators. `make_geocode_metadata` builder + `geocode_service` fixture added. Phase 1 complete → PR into `next-minor`. |

## 11. Discovery tooling

The `C:\Users\nestj1\geocode-captures\capture_geocode.py` script is read-only and is not part of
the repo.
- It POSTs to every endpoint with a bare `httpx.AsyncClient` plus archibald's auth, so error
  envelopes are saved verbatim. A GET is sent only when a POST fails.
- It writes one JSON file per call and prints a summary.
- Re-run it against any new locator before relying on §3 for it:
  `uv run python C:/Users/nestj1/geocode-captures/capture_geocode.py --base-url <.../rest/services>
  --service-path <.../GeocodeServer> --out-dir <dir> [--username/--password/--portal-url]
  [--address ...] [--point x,y --point-wkid N] [--oversize]`.
- The shipped `scripts/smoke_test_geocode.py` (7.4) is separate. It exercises archibald itself.
