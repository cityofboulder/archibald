import pytest

from archibald.auth import ARCGIS_ONLINE_BASE_URL, UserTokenAuth
from archibald.client import ArchieClient
from archibald.models import FieldsResult, QueryResult
from archibald.operations import (
    AddAttachmentsOperation,
    DeleteAttachmentsOperation,
    ApplyEditsOperation,
    QueryOperation,
)
from archibald.services import (
    BaseLayer,
    BaseService,
    FeatureLayer,
    FeatureService,
    MapLayer,
    MapService,
)
from tests.helpers import (
    MAP_LAYER_PATH,
    SERVICE_PATH,
    MinimalService,
    StaticTokenAuth,
    make_attachment_info,
)


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
def map_service(mock_client) -> MapService:
    """A default MapService instance backed by a mock client."""
    return MapService(client=mock_client, service_path="services/MyService/MapServer")


@pytest.fixture
def base_layer(mock_client) -> BaseLayer:
    """A default BaseLayer instance backed by a mock client, at layer 0."""
    return FeatureLayer(client=mock_client, service_path=SERVICE_PATH, layer_id=0)


@pytest.fixture
def map_layer(mock_client) -> MapLayer:
    """A default MapLayer instance backed by a mock client, at layer 0."""
    return MapLayer(client=mock_client, service_path=MAP_LAYER_PATH, layer_id=0)


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
def fields_result_with_domains(fields_result) -> FieldsResult:
    """fields_result with a coded-value domain added to the Status field.

    Domain: 0 → Inactive, 1 → Active, 2 → Pending.
    All other fields are inherited unchanged from fields_result.
    """
    domain = {
        "type": "codedValue",
        "name": "StatusDomain",
        "codedValues": [
            {"name": "Active", "code": 1},
            {"name": "Inactive", "code": 0},
            {"name": "Pending", "code": 2},
        ],
    }
    return FieldsResult(
        fields=[
            {**f, "domain": domain} if f["name"] == "Status" else f
            for f in fields_result.fields
        ]
    )


@pytest.fixture
def attachment_properties() -> list[dict]:
    """Layer metadata's attachmentProperties crosswalk.

    Maps each camelCase queryAttachments response property to its ESRI
    attachment-table field name, with isEnabled flags. Mirrors a real Enterprise
    feature service: id/globalId/name/size/contentType enabled,
    keywords/exifInfo disabled.
    """
    return [
        {"name": "id", "fieldName": "ATTACHMENTID", "isEnabled": True},
        {"name": "globalId", "fieldName": "GLOBALID", "isEnabled": True},
        {"name": "name", "fieldName": "ATT_NAME", "isEnabled": True},
        {"name": "size", "fieldName": "DATA_SIZE", "isEnabled": True},
        {"name": "contentType", "fieldName": "CONTENT_TYPE", "isEnabled": True},
        {"name": "keywords", "fieldName": "KEYWORDS", "isEnabled": False},
        {"name": "exifInfo", "fieldName": "EXIFINFO", "isEnabled": False},
    ]


@pytest.fixture
def full_attachment_groups() -> list[dict]:
    """Two attachmentGroups with dual-key attachmentInfos for to_frame tests.

    Each attachmentInfo carries both camelCase property names and ESRI field
    names, as a real Enterprise queryAttachments response does.
    """
    return [
        {
            "parentObjectId": 1,
            "parentGlobalId": "g1",
            "attachmentInfos": [make_attachment_info(10), make_attachment_info(11)],
        },
        {
            "parentObjectId": 2,
            "parentGlobalId": "g2",
            "attachmentInfos": [make_attachment_info(12)],
        },
    ]


@pytest.fixture
def enabled_property_columns(attachment_properties) -> list[str]:
    """Expected to_frame columns in property-name mode: parents + enabled names."""
    enabled = [p["name"] for p in attachment_properties if p.get("isEnabled", True)]
    return ["parentObjectId", "parentGlobalId", *enabled]


@pytest.fixture
def enabled_field_name_columns(attachment_properties) -> list[str]:
    """Expected to_frame columns in field-name mode: parents + enabled fieldNames."""
    enabled = [
        p["fieldName"] for p in attachment_properties if p.get("isEnabled", True)
    ]
    return ["parentObjectId", "parentGlobalId", *enabled]


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
def add_attachments_op(mock_layer) -> AddAttachmentsOperation:
    """An AddAttachmentsOperation instance backed by mock_layer."""
    return AddAttachmentsOperation(mock_layer)


@pytest.fixture
def delete_attachments_op(mock_layer) -> DeleteAttachmentsOperation:
    """A DeleteAttachmentsOperation instance backed by mock_layer."""
    return DeleteAttachmentsOperation(mock_layer)


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
