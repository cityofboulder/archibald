"""Integration tests for FeatureLayer — full stack with mocked HTTP transport."""

import httpx
import pytest

from archie.exceptions import ArcGISError
from archie.models.query_result import QueryResult
from tests.integration.conftest import (
    FEATURES,
    LAYER_METADATA,
    LAYER_URL,
    QUERY_URL,
)

pytestmark = pytest.mark.integration


class TestQueryRoundTrip:
    @pytest.mark.anyio
    async def test_returns_query_result_with_correct_features(
        self, layer, standard_routes
    ):
        standard_routes.get(QUERY_URL).mock(
            return_value=httpx.Response(200, json={"features": FEATURES})
        )

        result = await layer.query(where="1=1", return_geometry=False)

        assert isinstance(result, QueryResult)
        assert result.features == FEATURES

    @pytest.mark.anyio
    async def test_auth_token_injected_into_request(self, layer, standard_routes):
        query_route = standard_routes.get(QUERY_URL).mock(
            return_value=httpx.Response(200, json={"features": []})
        )

        await layer.query(return_geometry=False)

        assert (
            query_route.calls[0].request.headers["authorization"] == "Bearer test-token"
        )

    @pytest.mark.anyio
    async def test_crs_set_from_layer_native_spatial_reference(
        self, layer, standard_routes
    ):
        # standard_routes provides SERVICE_URL → {"spatialReference": {"latestWkid": 4326}}
        # With no out_sr, execute() falls back to layer.crs() → 4326.
        standard_routes.get(QUERY_URL).mock(
            return_value=httpx.Response(200, json={"features": []})
        )

        result = await layer.query(return_geometry=True)

        assert result.crs == 4326


class TestQueryPagination:
    @pytest.mark.anyio
    async def test_aggregates_features_across_pages(self, layer, standard_routes):
        def query_side_effect(request):
            params = dict(request.url.params)
            if params.get("returnCountOnly") == "true":
                return httpx.Response(200, json={"count": 1500})
            if "resultOffset" in params:
                return httpx.Response(200, json={"features": [FEATURES[1]]})
            return httpx.Response(
                200, json={"features": [FEATURES[0]], "exceededTransferLimit": True}
            )

        standard_routes.get(QUERY_URL).mock(side_effect=query_side_effect)

        result = await layer.query(return_geometry=False)

        assert result.features == [FEATURES[0], FEATURES[1]]


class TestQueryErrors:
    @pytest.mark.anyio
    async def test_esri_error_propagates_as_arcgis_error(self, layer, standard_routes):
        standard_routes.get(QUERY_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "error": {"code": 400, "message": "Invalid query", "details": []}
                },
            )
        )

        with pytest.raises(ArcGISError):
            await layer.query(return_geometry=False)

    @pytest.mark.anyio
    async def test_raises_when_layer_does_not_support_query(self, layer, http):
        http.get(LAYER_URL).mock(
            return_value=httpx.Response(
                200,
                json={**LAYER_METADATA, "capabilities": "Create,Update,Delete"},
            )
        )
        query_route = http.get(QUERY_URL).mock(
            return_value=httpx.Response(200, json={"features": []})
        )

        with pytest.raises(ValueError, match="does not support query"):
            await layer.query()

        assert not query_route.called
