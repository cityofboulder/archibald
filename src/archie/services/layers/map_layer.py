"""MapLayer: API for a single layer within an ESRI MapServer."""

from __future__ import annotations

from archie.services.layers.base import BaseLayer
from archie.services.map_service import MapService


class MapLayer(MapService, BaseLayer):
    """Single layer within an ESRI MapServer service.

    Inherits MapServer path validation from MapService and shared layer
    capability (metadata caching, field inspection, querying) from BaseLayer.
    Supports querying only.
    """
