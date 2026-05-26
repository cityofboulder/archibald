from __future__ import annotations

from abc import ABC

from archie.client import ArchieClient
from archie.exceptions import InvalidServiceURL


class BaseService(ABC):
    """Base class for all ESRI REST service resources.

    Validates that the provided service path ends with the expected service type on
    construction. Provides a single async method for fetching and caching
    service-level metadata.
    """

    expected_type: str

    def __init__(self, client: ArchieClient, service_path: str) -> None:
        self._client = client
        self._service_path = self._validate_path(service_path.rstrip("/"))
        self._service_metadata: dict | None = None

    def _validate_path(self, path: str) -> str:
        """Validate that the path ends with the expected service type and return it.

        Args:
            path: Stripped service path (relative to client base_url).

        Returns:
            The validated path unchanged.

        Raises:
            InvalidServiceURL: If the path does not end with expected_type.
        """
        if not path.endswith(self.expected_type):
            raise InvalidServiceURL(
                f"Expected path ending in '{self.expected_type}', got: {path}"
            )
        return path

    async def _get_service_metadata(self) -> dict:
        """Fetch and cache the service-level metadata JSON.

        Subsequent calls return the cached result without I/O.
        """
        if self._service_metadata is None:
            response = await self._client.get(endpoint=self._service_path)
            self._service_metadata = response.json()
        return self._service_metadata  # type: ignore[return-value]
