"""QueryResult: aggregated response from a query operation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd
import geopandas as gpd

from archie.models.fields_result import FieldsResult
from archie.serializers._coercions import ESRI_TO_PANDAS


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

        return self._apply_esri_types(df) if parse_dtypes else df

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
            ValueError: If the query returned no geometries.
        """
        if not self.geojson:
            raise ValueError(
                "Cannot convert to GeoDataFrame: no geometry present. "
                "Re-run query with return_geometry=True."
            )

        if not self.crs:
            raise ValueError(
                "Cannot convert to GeoDataFrame: no spatial reference (crs) provided. "
                "Re-run query with return_geometry=True and out_sr specified."
            )

        if not self.features:
            return self._construct_empty(type="geodataframe")  # type: ignore

        gdf = gpd.GeoDataFrame.from_features(self.features, crs=self.crs)

        return self._apply_esri_types(gdf) if parse_dtypes else gdf  # type: ignore

    def _apply_esri_types(self, df: pd.DataFrame) -> pd.DataFrame | gpd.GeoDataFrame:
        """Apply ESRI field type conversions to DataFrame columns.

        Iterates over registered converters in _ESRI_TYPE_CONVERTERS and
        applies each to any matching column. Columns whose ESRI type has no
        registered converter are left unchanged. Uses ``assign`` to return a
        copy rather than mutating in place.

        Args:
            df: DataFrame (or GeoDataFrame) to convert.

        Returns:
            DataFrame with converted columns.
        """
        field_types = self.fields.field_type_map
        conversions = {
            col: ESRI_TO_PANDAS[field_types[col]](df[col])
            for col in df.columns
            if field_types.get(col) in ESRI_TO_PANDAS
        }
        if not conversions:
            return df
        return df.assign(**conversions)

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
