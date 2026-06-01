from __future__ import annotations

import httpx
from pytest_mock import MockerFixture
from unittest.mock import AsyncMock

from archie.auth import ArcGISAuth, UserTokenAuth
from archie.client import ArchieClient
from archie.errors import handle_esri_errors
from archie.models import ApplyEditsResult, EditResultItem, FieldsResult, QueryResult
from archie.services import BaseService

BASE_URL = "https://example.com/arcgis/rest/services/MyService/FeatureServer"
SERVICE_PATH = "services/MyService/FeatureServer"
MAP_LAYER_PATH = "services/MyService/MapServer"

AnyClient = UserTokenAuth | ArchieClient


class MinimalService(BaseService):
    """Minimal BaseService subclass for testing."""

    expected_type = "FeatureServer"


class StaticTokenAuth(ArcGISAuth):
    """Minimal ArcGISAuth implementation for testing. Returns a static token with no I/O."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def get_token(self) -> str:
        """Return the static token provided at construction."""
        return self._token

    async def force_refresh(self) -> None:
        """No-op: static token never needs refreshing."""


def make_query_result(
    features: list[dict],
    fields: FieldsResult,
    *,
    geojson: bool = True,
    crs: int | None = None,
) -> QueryResult:
    """Create a QueryResult for use in tests."""
    return QueryResult(features=features, fields=fields, geojson=geojson, crs=crs)


def make_feature(
    objectid: int,
    name: str = "Feature",
    x: float = 0.0,
    y: float = 0.0,
) -> dict:
    """Create a minimal GeoJSON Feature dict for use in tests."""
    return {
        "type": "Feature",
        "properties": {"OBJECTID": objectid, "Name": name},
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def make_response(body: dict, *, status_code: int = 200) -> httpx.Response:
    """Create a minimal httpx.Response with a JSON body for use in tests."""
    response = httpx.Response(status_code, json=body)
    response.request = httpx.Request("GET", "https://example.com")
    return response


def make_edit_result_item(
    object_id: int,
    *,
    success: bool = True,
    global_id: str | None = None,
    error: dict | None = None,
) -> EditResultItem:
    """Create an EditResultItem for use in tests."""
    return EditResultItem(
        object_id=object_id,
        global_id=global_id,
        success=success,
        error=error,
    )


def make_apply_edits_result(
    adds: list[EditResultItem] | None = None,
    updates: list[EditResultItem] | None = None,
    deletes: list[EditResultItem] | None = None,
) -> ApplyEditsResult:
    """Create an ApplyEditsResult for use in tests."""
    return ApplyEditsResult(
        add_results=adds or [],
        update_results=updates or [],
        delete_results=deletes or [],
    )


def make_esri_apply_edits_response(
    add_ids: list[int] | None = None,
    update_ids: list[int] | None = None,
    delete_ids: list[int] | None = None,
) -> dict:
    """Build a raw ESRI applyEdits response dict for use in tests.

    Each ID list is expanded into success=True result dicts in the format
    expected by ApplyEditsResult.from_esri_response.

    Args:
        add_ids: OBJECTIDs for simulated add results.
        update_ids: OBJECTIDs for simulated update results.
        delete_ids: OBJECTIDs for simulated delete results.

    Returns:
        Dict with addResults, updateResults, and deleteResults keys.
    """

    def _items(ids: list[int]) -> list[dict]:
        return [
            {"objectId": oid, "success": True, "globalId": None, "error": None}
            for oid in ids
        ]

    body: dict = {}
    if add_ids:
        body["addResults"] = _items(add_ids)
    if update_ids:
        body["updateResults"] = _items(update_ids)
    if delete_ids:
        body["deleteResults"] = _items(delete_ids)
    return body


def make_small_feature(i: int = 1) -> dict:
    """Create a minimal ESRI feature dict for batch packing tests."""
    return {"attributes": {"id": i}}


def make_decorated_call(body: dict):
    """Return a handle_esri_errors-decorated coroutine that responds with body."""

    @handle_esri_errors
    async def _call():
        return make_response(body)

    return _call


def inject_mock_client(
    target: AnyClient,
    response: httpx.Response,
    mocker: MockerFixture,
) -> AsyncMock:
    """Inject a mock httpx.AsyncClient onto target._client.

    The mock returns *response* for any call to request() or post().
    Returns the mock so callers can make assertions against it.
    """
    mock_client = mocker.AsyncMock(spec=httpx.AsyncClient)
    mock_client.request.return_value = response
    mock_client.post.return_value = response
    target._client = mock_client
    return mock_client
