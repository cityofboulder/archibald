from __future__ import annotations

from archie.client import ArchieClient
from archie.services.base import BaseService


class FeatureService(BaseService):
    """ESRI FeatureServer service resource.

    Validates that the service path ends with 'FeatureServer' and exposes service-level
    metadata properties.
    """

    expected_type = "FeatureServer"

    def __init__(self, client: ArchieClient, service_path: str) -> None:
        super().__init__(client, service_path)

    async def crs(self) -> int:
        """Well-known ID of the service's spatial reference system.

        Defaults to 3857, Web Mercator.
        """
        return (
            (await self._get_service_metadata())
            .get("spatialReference", {})
            .get("latestWkid", 3857)
        )

    async def description(self) -> str:
        """Human-readable service description."""
        return (await self._get_service_metadata()).get("serviceDescription", "")

    async def max_record_count(self) -> int:
        """Maximum number of records the service returns per request."""
        return (await self._get_service_metadata()).get("maxRecordCount", 1000)
