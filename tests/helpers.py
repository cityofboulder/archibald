from __future__ import annotations

from dataclasses import replace

import geopandas as gpd
import httpx
import pandas as pd
import pytest
from pytest_mock import MockerFixture
from shapely.geometry import Point
from unittest.mock import AsyncMock

from archibald.auth import ArcGISAuth, UserTokenAuth
from archibald.client import ArchieClient
from archibald.errors import handle_esri_errors
from archibald.exceptions import (
    ArcGISError,
    AuthorizationError,
    ServiceError,
    TokenRefreshError,
)
from archibald.models import (
    AttachmentsResult,
    ApplyEditsResult,
    EditKind,
    EditResultItem,
    FieldsResult,
    QueryResult,
)
from archibald.services import BaseService

BASE_URL = "https://example.com/arcgis/rest/services/MyService/FeatureServer"
SERVICE_PATH = "services/MyService/FeatureServer"
MAP_LAYER_PATH = "services/MyService/MapServer"
GEOCODE_SERVICE_PATH = "locators/City_Of_Boulder_Address_Locator/GeocodeServer"
CITY_LOCATOR_PROPERTIES = {
    "MinimumCandidateScore": 70,
    "MinimumMatchScore": 75,
    "SuggestedBatchSize": 150,
    "MaxBatchSize": 500,
    "LocatorVersion": "11.0",
    "supportsBatchOutFields": "True",
}
STATUS_URL = f"{BASE_URL}/0/applyEdits/jobs/abc123"
ESRI_ITEM_ERROR = {"code": 1016, "description": "Setting of value for SITEGUID failed."}
ESRI_ROLLBACK_ERROR = {
    "code": 400,
    "extendedCode": -2146,
    "message": "Unable to complete operation.",
    "details": ["Operation rolled back.", "Setting of value for SITEGUID failed."],
}
OUTCOME_UNKNOWN_ERROR = {
    "code": -1,
    "description": "timed out",
    "exception": "ReadTimeout",
    "outcome_unknown": True,
}
CORE_FRAME_DTYPES = {
    "kind": "category",
    "status": "category",
    "object_id": "int64",
    "global_id": "string",
    "position": "Int64",
    "error_code": "Int64",
    "error_description": "string",
    "error_exception": "string",
    "error_outcome_unknown": "boolean",
    "error_status_url": "string",
}

DEFAULT_BATCHING_KWARGS = {
    "rollback_on_failure": True,
    "use_server_async": None,
    "max_batch_bytes": None,
    "poll_timeout": None,
}

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


class NonRecoverableSignal(BaseException):
    """BaseException stand-in for cancellation, which operations must not swallow."""


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


def make_geocode_metadata(
    capabilities: str | None = "Geocode,ReverseGeocode,Suggest",
    locator_properties: dict | None = CITY_LOCATOR_PROPERTIES,
) -> dict:
    """GeocodeServer metadata modeled on the City locator capture.

    Pass None for either argument to leave that key out entirely.
    """
    metadata: dict = {
        "singleLineAddressField": {"name": "SingleLine", "type": "esriFieldTypeString"},
        "spatialReference": {"wkid": 2876, "latestWkid": 2876},
    }
    if capabilities is not None:
        metadata["capabilities"] = capabilities
    if locator_properties is not None:
        metadata["locatorProperties"] = dict(locator_properties)
    return metadata


def make_first_page(
    start: int, size: int, *, exceeded: bool = True, in_properties: bool = False
) -> dict:
    """Create a first query response holding OBJECTIDs start..start+size-1.

    ``in_properties`` puts exceededTransferLimit under ``properties``, as
    f=geojson responses do, instead of at the top level.
    """
    data: dict = {"features": [make_feature(oid) for oid in range(start, start + size)]}
    if in_properties:
        data["properties"] = {"exceededTransferLimit": exceeded}
    else:
        data["exceededTransferLimit"] = exceeded
    return data


def make_paging_side_effect(total: int):
    """Create a client.post side effect simulating a layer of ``total`` rows.

    Count requests return ``total``; page requests return features whose
    OBJECTID equals their row position, honouring resultOffset and
    resultRecordCount.
    """

    def side_effect(endpoint, *, data=None, **kwargs):
        if data.get("returnCountOnly") == "true":
            return make_response({"count": total})
        offset = data["resultOffset"]
        stop = min(offset + data["resultRecordCount"], total)
        return make_response(
            {"features": [make_feature(oid) for oid in range(offset, stop)]}
        )

    return side_effect


def get_count_request_params(post_mock) -> dict:
    """Return the body of the single returnCountOnly request made on ``post_mock``."""
    (count_params,) = [
        call.kwargs["data"]
        for call in post_mock.call_args_list
        if call.kwargs["data"].get("returnCountOnly") == "true"
    ]
    return count_params


def make_edit_result_item(
    object_id: int,
    *,
    success: bool = True,
    global_id: str | None = None,
    error: dict | None = None,
    kind: EditKind | None = None,
    position: int | None = None,
) -> EditResultItem:
    """Create an EditResultItem for use in tests."""
    return EditResultItem(
        object_id=object_id,
        global_id=global_id,
        success=success,
        error=error,
        kind=kind,
        position=position,
    )


def make_apply_edits_result(
    adds: list[EditResultItem] | None = None,
    updates: list[EditResultItem] | None = None,
    deletes: list[EditResultItem] | None = None,
    *,
    inputs: dict[EditKind, pd.DataFrame] | None = None,
) -> ApplyEditsResult:
    """Create an ApplyEditsResult the way applyEdits builds one.

    Each item is copied with ``kind`` set from the list it is passed in, as
    ``ApplyEditsOperation.execute`` does; the passed items are not modified.
    """

    def tagged(items: list[EditResultItem] | None, kind: EditKind) -> list:
        """Copies of ``items`` with ``kind`` set."""
        return [replace(item, kind=kind) for item in items or []]

    return ApplyEditsResult(
        add_results=tagged(adds, "adds"),
        update_results=tagged(updates, "updates"),
        delete_results=tagged(deletes, "deletes"),
        _inputs=inputs or {},
    )


def make_single_kind_result(
    kind: EditKind, items: list[EditResultItem]
) -> ApplyEditsResult:
    """Create an ApplyEditsResult whose only items are ``items``, all of ``kind``."""
    return make_apply_edits_result(
        adds=items if kind == "adds" else None,
        updates=items if kind == "updates" else None,
        deletes=items if kind == "deletes" else None,
    )


def make_geo_frame(
    n: int, *, crs: str = "EPSG:4326", geometry_name: str = "geometry"
) -> gpd.GeoDataFrame:
    """Create an ``n``-row point GeoDataFrame with a ``name`` column (f0, f1, ...)."""
    gdf = gpd.GeoDataFrame(
        {"name": [f"f{i}" for i in range(n)]},
        geometry=[Point(i, i) for i in range(n)],
        crs=crs,
    )
    return gdf.rename_geometry(geometry_name) if geometry_name != "geometry" else gdf


def positions_by_kind(result: ApplyEditsResult) -> tuple[list, list, list]:
    """Item positions in each of the result's add, update, and delete lists."""
    return (
        [i.position for i in result.add_results],
        [i.position for i in result.update_results],
        [i.position for i in result.delete_results],
    )


def make_esri_apply_edits_response(
    add_ids: list[int] | None = None,
    update_ids: list[int] | None = None,
    delete_ids: list[int] | None = None,
) -> dict:
    """Build a raw ESRI applyEdits response dict for use in tests.

    Each ID list is expanded into success=True result dicts in the format
    expected by ApplyEditsResult._from_esri_response.

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


def make_attachment_result_item(
    object_id: int,
    *,
    success: bool = True,
    global_id: str | None = None,
    error: dict | None = None,
) -> EditResultItem:
    """Create an EditResultItem representing an attachment result for use in tests."""
    return EditResultItem(
        object_id=object_id,
        global_id=global_id,
        success=success,
        error=error,
    )


def make_attachments_result(
    results: list[EditResultItem] | None = None,
) -> AttachmentsResult:
    """Create an AttachmentsResult for use in tests."""
    return AttachmentsResult(results=results or [])


def make_esri_add_attachment_response(
    object_id: int,
    *,
    success: bool = True,
) -> dict:
    """Build a raw ESRI addAttachment response dict for use in tests.

    Args:
        object_id: Attachment OID returned by the server.
        success: Whether the attachment operation succeeded.

    Returns:
        Dict with addAttachmentResult key in the format expected by
        EditResultItem._from_esri.
    """
    return {
        "addAttachmentResult": {
            "objectId": object_id,
            "globalId": None,
            "success": success,
            "error": None,
        }
    }


def make_esri_update_attachment_response(
    object_id: int,
    *,
    success: bool = True,
) -> dict:
    """Build a raw ESRI updateAttachment response dict for use in tests.

    Args:
        object_id: Attachment OID returned by the server.
        success: Whether the attachment operation succeeded.

    Returns:
        Dict with updateAttachmentResult key in the format expected by
        EditResultItem._from_esri.
    """
    return {
        "updateAttachmentResult": {
            "objectId": object_id,
            "globalId": None,
            "success": success,
            "error": None,
        }
    }


def make_arcgis_error(
    exc_class: type[ArcGISError] = AuthorizationError,
    code: int = 403,
    message: str = "Unsupported attachment type.",
) -> ArcGISError:
    """Build an ArcGISError the way parse_esri_error does, for use in tests.

    Args:
        exc_class: ArcGISError subclass to instantiate.
        code: ESRI error code.
        message: ESRI error message.

    Returns:
        Exception whose ``raw_response`` is the full ``{"error": {...}}`` envelope.
    """
    return exc_class(
        code=code,
        message=message,
        raw_response={"error": {"code": code, "message": message}},
    )


def make_http_status_error(status_code: int) -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError the way ``raise_for_status`` does.

    Args:
        status_code: HTTP status code carried by the error's response.

    Returns:
        HTTPStatusError with a matching request and response attached.
    """
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}", request=request, response=response
    )


def make_rejecting_post(
    rejected_filenames: set[str],
    exc: Exception,
    success_body: dict,
):
    """Build an async ``client.post`` side effect that rejects chosen filenames.

    Args:
        rejected_filenames: Multipart attachment filenames that should raise.
        exc: Exception raised for a rejected filename.
        success_body: JSON body returned for every other filename.

    Returns:
        Async callable usable as ``client.post.side_effect``.
    """

    async def post(*, endpoint: str, files: dict, **kwargs) -> httpx.Response:
        """Raise exc for rejected filenames, otherwise return success_body."""
        if files["attachment"][0] in rejected_filenames:
            raise exc
        return make_response(success_body)

    return post


def make_delete_post_failing_for(failing_oids: set[int], exc: Exception):
    """Build an async ``client.post`` side effect for deleteAttachments calls.

    Args:
        failing_oids: Feature OBJECTIDs whose request should raise.
        exc: Exception raised for a failing OBJECTID.

    Returns:
        Async callable usable as ``client.post.side_effect``. Requests for other
        OBJECTIDs succeed for every attachment ID in the request.
    """

    async def post(*, endpoint: str, data: dict, **kwargs) -> httpx.Response:
        """Raise exc for failing OBJECTIDs, otherwise report every ID deleted."""
        if int(endpoint.split("/")[-2]) in failing_oids:
            raise exc
        att_ids = [int(i) for i in data["attachmentIds"].split(",")]
        return make_response(make_esri_delete_attachments_response(att_ids))

    return post


def make_esri_delete_attachments_response(
    attachment_ids: list[int],
    *,
    success: bool = True,
) -> dict:
    """Build a raw ESRI deleteAttachments response dict for use in tests.

    Args:
        attachment_ids: Attachment OIDs returned by the server.
        success: Whether all deletions succeeded.

    Returns:
        Dict with deleteAttachmentResults key in the format expected by
        EditResultItem._from_esri.
    """
    return {
        "deleteAttachmentResults": [
            {"objectId": att_id, "globalId": None, "success": success, "error": None}
            for att_id in attachment_ids
        ]
    }


def make_attachment_info(
    attachment_id: int,
    *,
    name: str = "photo.jpg",
    content_type: str = "image/jpeg",
    size: int = 1024,
    global_id: str = "{00000000-0000-0000-0000-000000000000}",
    url: str | None = None,
) -> dict:
    """Build a single attachmentInfo dict as returned by queryAttachments.

    Mirrors a real Enterprise response, where each value appears under both its
    camelCase property name and its ESRI attachment-table field name. When ``url``
    is given it is included as the response-only ``url`` key (as with returnUrl).
    """
    info = {
        "id": attachment_id,
        "ATTACHMENTID": attachment_id,
        "globalId": global_id,
        "GLOBALID": global_id,
        "name": name,
        "ATT_NAME": name,
        "contentType": content_type,
        "CONTENT_TYPE": content_type,
        "size": size,
        "DATA_SIZE": size,
    }
    if url is not None:
        info["url"] = url
    return info


def make_esri_query_attachments_response(attachment_groups: list[dict]) -> dict:
    """Build a raw ESRI queryAttachments response dict for use in tests.

    Args:
        attachment_groups: The attachmentGroups list. Each group is either a full
            group ({parentObjectId, parentGlobalId, attachmentInfos}) or a
            count-only group ({parentObjectId, parentGlobalId, count}).

    Returns:
        Dict with an attachmentGroups key.
    """
    return {"attachmentGroups": attachment_groups}


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


OUTCOME_UNKNOWN_CASES = [
    pytest.param(make_http_status_error(500), True, id="http-500"),
    pytest.param(make_http_status_error(502), True, id="http-502"),
    pytest.param(make_http_status_error(400), False, id="http-400"),
    pytest.param(make_http_status_error(413), False, id="http-413"),
    pytest.param(httpx.ConnectError("refused"), False, id="connect-error"),
    pytest.param(httpx.ConnectTimeout("slow"), False, id="connect-timeout"),
    pytest.param(httpx.PoolTimeout("busy"), False, id="pool-timeout"),
    pytest.param(httpx.ReadTimeout("slow"), True, id="read-timeout"),
    pytest.param(httpx.WriteTimeout("slow"), True, id="write-timeout"),
    pytest.param(httpx.ReadError("reset"), True, id="read-error"),
    pytest.param(httpx.RemoteProtocolError("bad"), True, id="remote-protocol-error"),
    pytest.param(ValueError("not json"), True, id="value-error"),
    pytest.param(KeyError("addAttachmentResult"), True, id="key-error"),
    pytest.param(make_arcgis_error(), False, id="arcgis-error"),
    pytest.param(TokenRefreshError("refresh failed"), False, id="token-refresh"),
    pytest.param(OSError("boom"), False, id="os-error"),
    pytest.param(TimeoutError(), True, id="timeout-error"),
]

NON_ENVELOPE_FAILURE_CASES = [
    pytest.param(
        ServiceError(code=-1, message="No response."), id="arcgis-error-no-response"
    ),
    pytest.param(
        ServiceError(
            code=-1,
            message="Async applyEdits job failed.",
            raw_response={"status": "Failed"},
        ),
        id="service-error-status-body",
    ),
    pytest.param(httpx.ReadTimeout("slow"), id="read-timeout"),
]

TRANSIENT_POLL_ERROR_CASES = [
    pytest.param(httpx.ReadTimeout("slow"), id="read-timeout"),
    pytest.param(httpx.ConnectError("refused"), id="connect-error"),
    pytest.param(make_http_status_error(503), id="http-503"),
]

REJECTED_POLL_ERROR_CASES = [
    pytest.param(make_http_status_error(404), "HTTP 404", id="http-404"),
    pytest.param(
        make_arcgis_error(ServiceError, 400, "Invalid job id."),
        "Invalid job id.",
        id="esri-envelope",
    ),
]

DEPRECATED_METHOD_CASES = [
    pytest.param(
        "from_esri_response",
        make_esri_apply_edits_response(add_ids=[1], update_ids=[2], delete_ids=[3]),
        id="from_esri_response",
    ),
    pytest.param(
        "merge",
        [
            make_apply_edits_result(adds=[make_edit_result_item(1)]),
            make_apply_edits_result(updates=[make_edit_result_item(2)]),
        ],
        id="merge",
    ),
]
