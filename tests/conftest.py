import pytest

from archie.auth import ARCGIS_ONLINE_BASE_URL, UserTokenAuth
from archie.client import ArchieClient
from archie.models import FieldsResult, QueryResult
from archie.operations import ApplyEditsOperation, QueryOperation
from archie.services import BaseService, FeatureLayer, FeatureService
from tests.helpers import SERVICE_PATH, StaticTokenAuth, MinimalService


@pytest.fixture
def auth() -> UserTokenAuth:
    """A default UserTokenAuth instance for use in tests."""
    return UserTokenAuth(
        username="user",
        password="pass",
        base_url=ARCGIS_ONLINE_BASE_URL,
        expiration=60,
    )


@pytest.fixture
def client() -> ArchieClient:
    """A default ArchieClient instance for use in tests."""
    return ArchieClient(
        base_url="https://example.com/arcgis/rest/services",
        auth=StaticTokenAuth("test-token"),
    )


@pytest.fixture
def mock_client(mocker):
    return mocker.create_autospec(ArchieClient)


@pytest.fixture
def service(mock_client) -> BaseService:
    """A default BaseService instance for use in tests."""
    return MinimalService(client=mock_client, service_path=SERVICE_PATH)


@pytest.fixture
def feature_service(mock_client) -> FeatureService:
    """A default FeatureService instance backed by a mock client."""
    return FeatureService(client=mock_client, service_path=SERVICE_PATH)


@pytest.fixture
def fields_result() -> FieldsResult:
    """Layer field definitions covering a range of ESRI types used across tests.

    Non-editable: OBJECTID (OID).
    Editable: Name (String, length=10), Status (Integer), Score (Double), EventDate (Date).
    """
    return FieldsResult(
        fields=[
            {
                "name": "OBJECTID",
                "type": "esriFieldTypeOID",
                "editable": False,
                "nullable": False,
            },
            {
                "name": "Name",
                "type": "esriFieldTypeString",
                "editable": True,
                "nullable": True,
                "length": 10,
            },
            {
                "name": "Status",
                "type": "esriFieldTypeInteger",
                "editable": True,
            },  # nullable absent → defaults True
            {
                "name": "Score",
                "type": "esriFieldTypeDouble",
                "editable": True,
                "nullable": True,
            },
            {
                "name": "EventDate",
                "type": "esriFieldTypeDate",
                "editable": True,
                "nullable": True,
            },
        ]
    )


@pytest.fixture
def mock_layer(mocker, fields_result):
    """A mock FeatureLayer with sensible async method defaults.

    Uses create_autospec so callers can assert on method signatures.
    Layer path is constructed the same way FeatureLayer.__init__ does it.
    """
    layer = mocker.create_autospec(FeatureLayer)
    layer._layer_path = f"{SERVICE_PATH}/0"
    layer._client = mocker.create_autospec(ArchieClient)
    layer.fields.return_value = fields_result
    layer.objectid_field.return_value = "OBJECTID"
    layer.globalid_field.return_value = None
    layer.max_record_count.return_value = 1000
    layer.crs.return_value = 3857
    layer.supports_rollback_on_failure.return_value = True
    layer.supports_async_apply_edits.return_value = False
    return layer


@pytest.fixture
def apply_edits_op(mock_layer) -> ApplyEditsOperation:
    """An ApplyEditsOperation instance backed by mock_layer."""
    return ApplyEditsOperation(mock_layer)


@pytest.fixture
def query_op(mock_layer) -> QueryOperation:
    """A QueryOperation instance backed by mock_layer."""
    return QueryOperation(mock_layer)


@pytest.fixture
def feature_layer(mock_client) -> FeatureLayer:
    """A real FeatureLayer backed by mock_client, at layer 0."""
    return FeatureLayer(client=mock_client, service_path=SERVICE_PATH, layer_id=0)


@pytest.fixture
def geojson_query_result(fields_result):
    return QueryResult(
        features=[
            {
                "type": "Feature",
                "properties": {"OBJECTID": 1, "Name": "Feature1"},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            },
            {
                "type": "Feature",
                "properties": {"OBJECTID": 2, "Name": "Feature2"},
                "geometry": {"type": "Point", "coordinates": [1, 1]},
            },
        ],
        fields=fields_result.filter(names=["OBJECTID", "Name"]),
        geojson=True,
        crs=4326,
    )
