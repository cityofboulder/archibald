import pytest

from archie.auth.user_token import ARCGIS_ONLINE_BASE_URL, UserTokenAuth


@pytest.fixture
def auth() -> UserTokenAuth:
    """A default UserTokenAuth instance for use in tests."""
    return UserTokenAuth(
        username="user",
        password="pass",
        base_url=ARCGIS_ONLINE_BASE_URL,
        expiration=60,
    )
