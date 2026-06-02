from __future__ import annotations

from archibald.services.base import BaseService


class FeatureService(BaseService):
    """ESRI FeatureServer service resource."""

    expected_type = "FeatureServer"
