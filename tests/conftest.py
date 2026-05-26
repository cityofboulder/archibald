import pytest

from archie.auth.user_token import ARCGIS_ONLINE_BASE_URL, UserTokenAuth
from archie.client import ArchieClient
from archie.services.base import BaseService
from archie.services.feature_service import FeatureService
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
        base_url="https://services.arcgis.com/instance",
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
