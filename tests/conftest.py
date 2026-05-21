import pytest

from archie.auth.user_token import ARCGIS_ONLINE_BASE_URL, UserTokenAuth
from archie.client import ArchieClient
from tests.helpers import StaticTokenAuth


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
