from __future__ import annotations

from abc import ABC

from archie.client import ArchieClient
from archie.exceptions import InvalidServiceURL


class BaseService(ABC):
    """Base class for all ESRI REST service resources.

    Validates that the provided URL ends with the expected service type on
    construction. Provides a single async method for fetching and caching
    service-level metadata.
    """

    expected_type: str

    def __init__(self, client: ArchieClient, url: str) -> None:
        self._client = client
        self._url = self._validate_url(url.rstrip("/"))
        self._service_metadata: dict | None = None

    def _validate_url(self, url: str) -> str:
        """Validate that the URL ends with the expected service type and return it.

        Args:
            url: Stripped service URL.

        Returns:
            The validated URL unchanged.

        Raises:
            InvalidServiceURL: If the URL does not end with expected_type.
        """
        if not url.endswith(self.expected_type):
            raise InvalidServiceURL(
                f"Expected URL ending in '{self.expected_type}', got: {url}"
            )
        return url

    async def _get_service_metadata(self) -> dict:
        """Fetch and cache the service-level metadata JSON.

        Subsequent calls return the cached result without I/O.
        """
        if self._service_metadata is None:
            response = await self._client.get(url=self._url)
            self._service_metadata = response.json()
        return self._service_metadata  # type: ignore[return-value]
