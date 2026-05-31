from __future__ import annotations

from archie.services.base import BaseService


class MapService(BaseService):
    """ESRI MapServer service resource."""

    expected_type = "MapServer"
