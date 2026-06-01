"""BaseLayer: shared layer resource base class for ESRI REST API layers."""

from __future__ import annotations

from archie.client import ArchieClient
from archie.exceptions import LayerCapabilityError
from archie.models.fields_result import FieldsResult
from archie.models.query_result import QueryResult
from archie.operations.query import QueryOperation
from archie.services.base import BaseService


class BaseLayer(BaseService):
    """Abstract base for a single layer within an ESRI service.

    Provides layer init, metadata caching, field inspection, and query execution.
    Subclasses must define expected_type and may add editing support.
    """

    def __init__(self, client: ArchieClient, service_path: str, layer_id: int) -> None:
        """Construct a BaseLayer.

        Args:
            client: The ArchieClient instance.
            service_path: Service path validated by BaseService against expected_type.
            layer_id: Layer index within the service (e.g., 0, 1, 2).
        """
        super().__init__(client, service_path)
        self._layer_id = layer_id
        self._layer_path = f"{self._service_path}/{layer_id}"
        self._layer_metadata: dict | None = None
        self._query_op = QueryOperation(self)

    async def _get_layer_metadata(self) -> dict:
        """Fetch and cache layer-level metadata JSON.

        Subsequent calls return the cached result without I/O.
        """
        if self._layer_metadata is None:
            response = await self._client.get(endpoint=self._layer_path)
            self._layer_metadata = response.json()
        return self._layer_metadata  # type: ignore[return-value]

    async def objectid_field(self) -> str:
        """Name of the OBJECTID field for this layer.

        Returns:
            The name of the OBJECTID field, used for pagination and often as a
            unique identifier for features.
        """
        metadata = await self._get_layer_metadata()
        return metadata.get("objectIdField", "OBJECTID")

    async def globalid_field(self) -> str | None:
        """Name of the GlobalID field for this layer, if present.

        Returns:
            The name of the GlobalID field, a UUID string used for unique
            identification across systems. None if not defined.
        """
        metadata = await self._get_layer_metadata()
        return metadata.get("globalIdField")

    async def supports_query(self) -> bool:
        """Whether this layer supports query operations.

        Returns:
            True if the layer's capabilities include querying, False otherwise.
        """
        metadata = await self._get_layer_metadata()
        return "query" in metadata.get("capabilities", "").lower()

    async def fields(self) -> FieldsResult:
        """Field definitions from layer metadata.

        Returns:
            FieldsResult providing access to field names and definitions.
        """
        field_list = (await self._get_layer_metadata()).get("fields", [])
        return FieldsResult(fields=field_list)

    async def query(
        self,
        where: str = "1=1",
        out_fields: list[str] | str | None = None,
        return_geometry: bool = True,
        out_sr: int | None = None,
        **kwargs,
    ) -> QueryResult:
        """Execute a query on this layer.

        Args:
            where: WHERE clause (default "1=1" returns all features).
            out_fields: Field names to return. Can be None (→ all), a list, or
                a comma-separated string.
            return_geometry: Include feature geometries in the response.
            out_sr: Output spatial reference (EPSG code) for geometries.
            **kwargs: Additional query parameters (e.g., orderByFields, resultType).

        Returns:
            QueryResult with aggregated features, field definitions, and geometry type.

        Raises:
            InvalidParameterError: If out_fields contains unknown field names.
            LayerCapabilityError: If the layer does not support query operations.
        """
        if not await self.supports_query():
            raise LayerCapabilityError(
                f"Layer {self._layer_path} does not support query operations."
            )
        return await self._query_op.execute(
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            out_sr=out_sr,
            **kwargs,
        )
