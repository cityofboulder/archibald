"""QueryOperation: execute queries against a layer with pagination support."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import anyio

from archibald.exceptions import InvalidParameterError
from archibald.models import QueryResult
from archibald.serializers._date_literals import (
    ESRI_DATE_TYPE_KEYWORDS,
    matches_literal_format,
)

if TYPE_CHECKING:
    from archibald.services import BaseLayer


class QueryOperation:
    """Execute queries on a BaseLayer with automatic pagination.

    Holds a reference to its owning layer to access the client, layer path,
    and metadata. Instantiated once at BaseLayer.__init__ time.
    """

    def __init__(self, layer: BaseLayer) -> None:
        self._layer = layer
        self._endpoint = f"{layer._layer_path}/query"

    async def execute(
        self,
        where: str = "1=1",
        out_fields: list[str] | str | None = None,
        return_geometry: bool = True,
        out_sr: int | None = None,
        **kwargs,
    ) -> QueryResult:
        """Execute a query, handling pagination and field validation.

        Args:
            where: WHERE clause (default "1=1" returns all).
            out_fields: Field names to return (None → "*" for all). Can be a list
                or comma-separated string.
            return_geometry: Include feature geometries in response.
            out_sr: Output spatial reference (EPSG code) for geometries.
            **kwargs: Additional query parameters (e.g., orderByFields, resultType).
                If orderByFields is not provided, defaults to "OBJECTID ASC".

        Returns:
            QueryResult with aggregated features, field definitions, and geometry type.

        Raises:
            InvalidParameterError: If out_fields contains unknown field names.
            InvalidParameterError: If where compares a date/time-typed field
                to an improperly formatted or unwrapped literal.
        """
        # Normalize out_fields and validate against available fields on the layer
        normalized_fields = await self._normalize_out_fields(out_fields)
        normalized_fields = await self._validate_fields(normalized_fields)
        await self._validate_date_literals(where)

        crs = (out_sr or await self._layer.crs()) if return_geometry else None

        # Build initial params
        params = await self._build_params(
            where=where,
            out_fields=normalized_fields,
            return_geometry=return_geometry,
            out_sr=crs,
            **kwargs,
        )

        # First request
        first_response = await self._layer._client.get(
            endpoint=self._endpoint,
            params=params,
        )
        first_data = first_response.json()
        features = first_data.get("features", [])

        # Paginate the rest if needed
        exceeded = (first_data.get("exceededTransferLimit", False)) or (
            first_data.get("properties", {}).get("exceededTransferLimit", False)
        )
        if exceeded:
            additional_features = await self._fetch_remaining_pages(params, first_data)
            features.extend(additional_features)

        fields_result = await self._layer.fields()
        fields_result = fields_result.filter(names=normalized_fields.split(","))

        return QueryResult(
            features=features,
            fields=fields_result,
            geojson=return_geometry,
            crs=crs,
        )

    async def _normalize_out_fields(self, out_fields: list[str] | str | None) -> str:
        """Normalize out_fields to a string.

        Args:
            out_fields: None, "*", list of field names, or comma-separated string.

        Returns:
            Comma-separated field string.
        """
        if out_fields is None or out_fields == "*":
            return ",".join((await self._layer.fields()).names)
        if isinstance(out_fields, str):
            return out_fields.strip()
        return ",".join(f.strip() for f in out_fields)

    async def _validate_fields(self, out_fields: str) -> str:
        """Validate that requested field names exist on the layer.

        Raises:
            InvalidParameterError: If any field name is not found (case-sensitive).
        """
        fields_result = await self._layer.fields()
        valid_names = set(fields_result.names)

        requested = set(out_fields.split(","))
        unknown = requested - valid_names

        if unknown:
            raise InvalidParameterError(
                f"Unknown field names: {', '.join(sorted(unknown))}. "
                f"Valid fields: {', '.join(sorted(valid_names))}"
            )

        return out_fields

    async def _validate_date_literals(self, where: str) -> None:
        """Validate DATE/TIMESTAMP/TIME literal formatting for date-typed fields in a WHERE clause.

        Scans `where` for comparisons, BETWEEN/NOT BETWEEN, and IN/NOT IN
        clauses against any field typed esriFieldTypeDate, esriFieldTypeDateOnly,
        esriFieldTypeTimeOnly, or esriFieldTypeTimestampOffset, and checks that
        each literal uses a keyword and value format valid for that field's type.

        This is a regex-based scan, not a full SQL parser: field names embedded
        inside unrelated string literals can false-positive, nested IN(...)
        sub-expressions aren't supported, and function-style literals like
        CURRENT_TIMESTAMP are not recognized.

        Raises:
            InvalidParameterError: A date/time-typed field is compared to a bare
                string literal, uses a keyword not valid for its type, or the
                literal's value does not match the expected format.
        """
        fields = await self._layer.fields()

        validators = {
            "esriFieldTypeDate": self._validate_esri_date_fields,
            "esriFieldTypeDateOnly": self._validate_esri_date_only_fields,
            "esriFieldTypeTimeOnly": self._validate_esri_time_only_fields,
            "esriFieldTypeTimestampOffset": self._validate_esri_timestamp_offset_fields,
        }
        for esri_type, validate in validators.items():
            names = fields.filter(types=esri_type).names
            if names:
                validate(where, names)

    def _validate_esri_date_fields(self, where: str, field_names: list[str]) -> None:
        """Validate literals against fields of type esriFieldTypeDate."""
        self._scan_where_for_literals(where, field_names, "esriFieldTypeDate")

    def _validate_esri_date_only_fields(
        self, where: str, field_names: list[str]
    ) -> None:
        """Validate literals against fields of type esriFieldTypeDateOnly."""
        self._scan_where_for_literals(where, field_names, "esriFieldTypeDateOnly")

    def _validate_esri_time_only_fields(
        self, where: str, field_names: list[str]
    ) -> None:
        """Validate literals against fields of type esriFieldTypeTimeOnly."""
        self._scan_where_for_literals(where, field_names, "esriFieldTypeTimeOnly")

    def _validate_esri_timestamp_offset_fields(
        self, where: str, field_names: list[str]
    ) -> None:
        """Validate literals against fields of type esriFieldTypeTimestampOffset."""
        self._scan_where_for_literals(
            where, field_names, "esriFieldTypeTimestampOffset"
        )

    def _scan_where_for_literals(
        self, where: str, field_names: list[str], esri_type: str
    ) -> None:
        """Find every comparison/BETWEEN/IN literal against `field_names` in `where` and validate it.

        Raises:
            InvalidParameterError: Any matched literal is invalid for `esri_type`.
        """
        field_alt = "|".join(
            re.escape(n) for n in sorted(field_names, key=len, reverse=True)
        )
        literal = r"(?:(?P<kw>[A-Za-z]+)\s+)?'(?P<val>[^']*)'"

        simple_re = re.compile(
            rf"\b(?P<field>{field_alt})\b\s*(?:=|<>|!=|>=|<=|>|<)\s*{literal}"
        )
        between_re = re.compile(
            rf"\b(?P<field>{field_alt})\b\s+(?i:NOT\s+)?(?i:BETWEEN)\s+"
            rf"(?:(?P<kw1>[A-Za-z]+)\s+)?'(?P<val1>[^']*)'\s+(?i:AND)\s+"
            rf"(?:(?P<kw2>[A-Za-z]+)\s+)?'(?P<val2>[^']*)'"
        )
        in_re = re.compile(
            rf"\b(?P<field>{field_alt})\b\s+(?i:NOT\s+)?(?i:IN)\s*\(\s*(?P<list>[^)]*)\)"
        )
        literal_re = re.compile(literal)

        for match in simple_re.finditer(where):
            self._validate_literal(match["field"], esri_type, match["kw"], match["val"])

        for match in between_re.finditer(where):
            self._validate_literal(
                match["field"], esri_type, match["kw1"], match["val1"]
            )
            self._validate_literal(
                match["field"], esri_type, match["kw2"], match["val2"]
            )

        for match in in_re.finditer(where):
            for lit in literal_re.finditer(match["list"]):
                self._validate_literal(match["field"], esri_type, lit["kw"], lit["val"])

    def _validate_literal(
        self, field: str, esri_type: str, kw: str | None, val: str
    ) -> None:
        """Raise InvalidParameterError if one extracted (keyword, value) literal is invalid.

        Raises:
            InvalidParameterError: `kw` is missing, not valid for `esri_type`,
                or `val` does not match the format required by `kw`.
        """
        allowed = ESRI_DATE_TYPE_KEYWORDS[esri_type]
        examples = [example for _, _, example in allowed.values()]

        if kw is None:
            raise InvalidParameterError(
                f"Field '{field}' is date/time-typed ({esri_type}) and cannot be "
                f"compared to a bare string literal '{val}'. Wrap it in one of: "
                f"{', '.join(examples)}."
            )

        kw_upper = kw.upper()
        if kw_upper not in allowed:
            raise InvalidParameterError(
                f"Field '{field}' ({esri_type}) does not support the '{kw}' keyword. "
                f"Use one of: {', '.join(examples)}."
            )

        if not matches_literal_format(val, esri_type, kw_upper):
            example = allowed[kw_upper][-1]
            raise InvalidParameterError(
                f"Field '{field}' ({esri_type}) has a malformed {kw_upper} literal "
                f"'{val}'. Expected format: {example}."
            )

    async def _build_params(
        self,
        where: str,
        out_fields: str,
        return_geometry: bool,
        out_sr: int | None = None,
        **kwargs,
    ) -> dict:
        """Build the query parameter dict.

        Always includes orderByFields=OBJECTID ASC unless the caller provides
        their own orderByFields in kwargs.

        Args:
            where: WHERE clause.
            out_fields: Normalized field string or "*".
            return_geometry: Include geometries.
            out_sr: Output spatial reference (EPSG code) for geometries.
            **kwargs: Additional params (e.g., orderByFields, resultType).

        Returns:
            Dict of query parameters for the ESRI REST API.
        """
        params = kwargs.copy()

        params.update(
            {
                "where": where,
                "outFields": out_fields,
                "returnGeometry": "true" if return_geometry else "false",
            }
        )

        if out_sr is not None:
            params["outSR"] = str(out_sr)

        # Always order by OBJECTID for deterministic pagination,
        # unless caller specified their own ordering.
        if "orderByFields" not in params:
            objectid_field = await self._layer.objectid_field()
            params["orderByFields"] = f"{objectid_field} ASC"

        # Enforce geojson format after merging kwargs so a caller-supplied
        # f= value cannot suppress geometry encoding.
        if return_geometry:
            params["f"] = "geojson"

        return params

    async def _fetch_remaining_pages(
        self, initial_params: dict, first_data: dict
    ) -> list[dict]:
        """Fetch remaining pages in parallel if pagination is needed.

        Args:
            initial_params: Query parameters from the first request.
            first_data: Response JSON from the first request.

        Returns:
            List of all remaining feature objects from subsequent pages.
        """
        max_record_count = await self._layer.max_record_count()
        total_count_response = await self._layer._client.get(
            endpoint=self._endpoint,
            params={
                "where": initial_params.get("where", "1=1"),
                "returnCountOnly": "true",
                "f": "json",
            },
        )
        total_count = total_count_response.json().get("count", 0)

        # Calculate offsets for remaining pages
        offsets = list(range(max_record_count, total_count, max_record_count))

        if not offsets:
            return []

        # Fan out page requests in parallel
        page_results: list[list[dict]] = [[] for _ in offsets]

        async def fetch_page(idx: int, offset: int) -> None:
            response = await self._layer._client.get(
                endpoint=self._endpoint,
                params={
                    **initial_params,
                    "resultOffset": offset,
                    "resultRecordCount": max_record_count,
                },
            )
            page_results[idx] = response.json().get("features", [])

        async with anyio.create_task_group() as tg:
            for idx, offset in enumerate(offsets):
                tg.start_soon(fetch_page, idx, offset)

        # Flatten page results in order
        all_remaining = []
        for page in page_results:
            all_remaining.extend(page)

        return all_remaining
