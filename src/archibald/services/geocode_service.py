from __future__ import annotations

from archibald.services.base import BaseService


class GeocodeService(BaseService):
    """ESRI GeocodeServer (address locator) service resource.

    The ``supports_*`` checks report what the locator *advertises* in its
    ``capabilities``. A locator can advertise an operation and still fail it
    (e.g. a classic locator that lists Suggest but answers ``/suggest`` with a
    400), in which case the server's error propagates as ``ServiceError``.
    """

    expected_type = "GeocodeServer"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    async def max_batch_size(self) -> int | None:
        """Most addresses the locator accepts in one geocodeAddresses request.

        Returns:
            ``locatorProperties.MaxBatchSize`` as an int, or None when the
            locator does not report one.
        """
        properties = (await self._get_service_metadata()).get("locatorProperties", {})
        value = properties.get("MaxBatchSize")
        return None if value is None else int(value)

    # ------------------------------------------------------------------
    # Capability checks
    # ------------------------------------------------------------------

    async def supports_batch_geocode(self) -> bool:
        """Whether this locator advertises batch geocoding (geocodeAddresses).

        Returns:
            True if the locator advertises Geocode and its ``max_batch_size``
            is a positive number.
        """
        if not await self.supports_geocode():
            return False
        return (await self.max_batch_size() or 0) > 0

    async def supports_geocode(self) -> bool:
        """Whether this locator advertises geocoding (findAddressCandidates).

        Returns:
            True if ``capabilities`` lists Geocode.
        """
        return "geocode" in await self._capabilities()

    async def supports_reverse_geocode(self) -> bool:
        """Whether this locator advertises reverse geocoding (reverseGeocode).

        Returns:
            True if ``capabilities`` lists ReverseGeocode.
        """
        return "reversegeocode" in await self._capabilities()

    async def supports_suggest(self) -> bool:
        """Whether this locator advertises suggestions (suggest).

        Returns:
            True if ``capabilities`` lists Suggest.
        """
        return "suggest" in await self._capabilities()

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    async def _capabilities(self) -> set[str]:
        """Lowercased capability tokens from the locator's ``capabilities``.

        The string is split on commas rather than searched, because
        ``"geocode"`` is a substring of ``"reversegeocode"``.
        """
        capabilities = (await self._get_service_metadata()).get("capabilities", "")
        return {
            token.strip().lower() for token in capabilities.split(",") if token.strip()
        }
