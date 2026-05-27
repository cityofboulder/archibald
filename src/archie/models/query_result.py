"""QueryResult: aggregated response from a query operation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd
import geopandas as gpd


@dataclass
class QueryResult:
    """Aggregated features and metadata from a query operation.

    Provides access to raw features and field definitions, plus conversion
    methods to DataFrame and GeoDataFrame.
    """

    features: list[dict]
    fields: list[str]
    geojson: bool
    crs: int | None = None

    def to_frame(self) -> pd.DataFrame:
        """Return attributes only as a pandas DataFrame.

        Returns:
            DataFrame with one row per feature, columns from attributes.
        """
        if not self.features:
            return self._construct_empty(type="dataframe")

        key = "properties" if self.geojson else "attributes"
        records = [f.get(key, {}) for f in self.features]
        return pd.DataFrame(records)

    def to_geodataframe(self) -> gpd.GeoDataFrame:
        """Return attributes + geometry as a geopandas GeoDataFrame.

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

        return gpd.GeoDataFrame.from_features(self.features, crs=self.crs)

    def _construct_empty(
        self, type: Literal["dataframe", "geodataframe"]
    ) -> pd.DataFrame | gpd.GeoDataFrame:
        """Construct an empty DataFrame or GeoDataFrame with appropriate columns."""
        if type == "dataframe":
            return pd.DataFrame(columns=self.fields)
        return gpd.GeoDataFrame(
            {col: pd.Series([], dtype=object) for col in self.fields},
            geometry=gpd.GeoSeries([], crs=self.crs),
        )
