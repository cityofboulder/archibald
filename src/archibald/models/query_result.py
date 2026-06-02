"""QueryResult: aggregated response from a query operation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd
import geopandas as gpd

from archibald.exceptions import MissingGeometryError
from archibald.models.fields_result import FieldsResult
from archibald.serializers._coercions import enforce_types, recode_domains


@dataclass
class QueryResult:
    """Aggregated features and metadata from a query operation.

    Provides access to raw features and field definitions, plus conversion
    methods to DataFrame and GeoDataFrame. The ``fields`` attribute carries
    both field names and ESRI type metadata for the fields returned by the
    query (filtered to only those that were requested).
    """

    features: list[dict]
    fields: FieldsResult
    geojson: bool
    crs: int | None = None
    apply_coded_values: bool = False

    def to_frame(self, *, parse_dtypes: bool = False) -> pd.DataFrame:
        """Return attributes only as a pandas DataFrame.

        Args:
            parse_dtypes: If True, convert columns to their appropriate pandas
                types based on the ESRI field type metadata. Dates become
                UTC-aware datetimes, integer fields become nullable integer
                types, etc. Defaults to False.

        Returns:
            DataFrame with one row per feature, columns from attributes.
        """
        if not self.features:
            return self._construct_empty(type="dataframe")

        key = "properties" if self.geojson else "attributes"
        records = [f.get(key, {}) for f in self.features]
        df = pd.DataFrame(records)

        return self._parse_and_decode(df, parse_dtypes=parse_dtypes)

    def to_geodataframe(self, *, parse_dtypes: bool = False) -> gpd.GeoDataFrame:
        """Return attributes + geometry as a geopandas GeoDataFrame.

        Args:
            parse_dtypes: If True, convert attribute columns to their
                appropriate pandas types based on the ESRI field type
                metadata. The geometry column is always preserved unchanged.
                Defaults to False.

        Returns:
            GeoDataFrame with one row per feature.

        Raises:
            MissingGeometryError: If the query returned no geometries.
        """
        if not self.geojson:
            raise MissingGeometryError(
                "Cannot convert to GeoDataFrame: no geometry present. "
                "Re-run query with return_geometry=True."
            )

        if not self.crs:
            raise MissingGeometryError(
                "Cannot convert to GeoDataFrame: no spatial reference (crs) provided. "
                "Re-run query with return_geometry=True and out_sr specified."
            )

        if not self.features:
            return self._construct_empty(type="geodataframe")  # type: ignore

        gdf = gpd.GeoDataFrame.from_features(self.features, crs=self.crs)

        return self._parse_and_decode(gdf, parse_dtypes=parse_dtypes)  # type: ignore

    def _parse_and_decode(
        self, df: pd.DataFrame | gpd.GeoDataFrame, parse_dtypes: bool
    ) -> pd.DataFrame | gpd.GeoDataFrame:
        """Parse data types and apply coded-value domain translation if enabled.

        Type coercion always runs before domain lookup when apply_coded_values is
        True and the fields actually carry domain maps — domain codes must be typed
        consistently for the mapping to match. When apply_coded_values is True but
        no fields have domains, coercion is skipped unless parse_dtypes is also True.
        """
        apply_domains = self.apply_coded_values and bool(self.fields.domain_maps)
        if parse_dtypes or apply_domains:
            df = enforce_types(df, self.fields, direction="from_esri")
        if apply_domains:
            return recode_domains(df, self.fields, direction="from_esri")
        return df

    def _construct_empty(
        self, type: Literal["dataframe", "geodataframe"]
    ) -> pd.DataFrame | gpd.GeoDataFrame:
        """Construct an empty DataFrame or GeoDataFrame with appropriate columns."""
        if type == "dataframe":
            return pd.DataFrame(columns=self.fields.names)
        return gpd.GeoDataFrame(
            {col: pd.Series([], dtype=object) for col in self.fields.names},
            geometry=gpd.GeoSeries([], crs=self.crs),
        )
