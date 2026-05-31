"""Shared fixtures and data for FeatureLayer integration tests."""

import httpx
import pytest
import respx

from archie.client import ArchieClient
from archie.services import FeatureLayer
from tests.helpers import SERVICE_PATH, StaticTokenAuth

# ---------------------------------------------------------------------------
# URL constants
# ---------------------------------------------------------------------------

BASE_URL = "https://services.arcgis.com/test/arcgis/rest/services"
SERVICE_URL = f"{BASE_URL}/{SERVICE_PATH}"
LAYER_URL = f"{SERVICE_URL}/0"
QUERY_URL = f"{LAYER_URL}/query"

# ---------------------------------------------------------------------------
# Sample ESRI response data
# ---------------------------------------------------------------------------

SERVICE_METADATA = {
    "spatialReference": {"latestWkid": 4326},
    "maxRecordCount": 1000,
}

LAYER_METADATA = {
    "objectIdField": "OBJECTID",
    "capabilities": "Query,Create,Update,Delete",
    "fields": [
        {"name": "OBJECTID", "type": "esriFieldTypeOID", "editable": False},
        {"name": "Name", "type": "esriFieldTypeString", "editable": True},
    ],
}

FEATURES = [
    {
        "type": "Feature",
        "properties": {"OBJECTID": 1, "Name": "Alpha"},
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
    },
    {
        "type": "Feature",
        "properties": {"OBJECTID": 2, "Name": "Beta"},
        "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
    },
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def http():
    """respx mock transport — intercepts all httpx calls for the duration of the test.

    assert_all_called=False: standard_routes registers SERVICE_URL for all tests,
    but tests using return_geometry=False never trigger the crs() call that fetches
    it. Unused routes are silently ignored at teardown.
    """
    with respx.mock(assert_all_called=False) as m:
        yield m


@pytest.fixture
def layer(http) -> FeatureLayer:
    """Real FeatureLayer wired to a real ArchieClient; HTTP intercepted by respx.

    Depends on `http` to ensure the mock transport is active before the
    httpx.AsyncClient is lazily created on the first request.
    """
    client = ArchieClient(base_url=BASE_URL, auth=StaticTokenAuth("test-token"))
    return FeatureLayer(client=client, service_path=SERVICE_PATH, layer_id=0)


@pytest.fixture
def standard_routes(http):
    """Pre-register the service and layer metadata routes shared by most tests.

    Tests that need custom layer metadata use the `http` fixture directly and
    register their own LAYER_URL route.

    Returns the respx mock so tests can add further routes (e.g., QUERY_URL).
    """
    http.get(SERVICE_URL).mock(return_value=httpx.Response(200, json=SERVICE_METADATA))
    http.get(LAYER_URL).mock(return_value=httpx.Response(200, json=LAYER_METADATA))
    return http
