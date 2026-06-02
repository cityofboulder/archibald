import pytest
from archibald.exceptions import (
    ArchieError,
    ArcGISError,
    TokenExpiredError,
    TokenMissingError,
    AuthorizationError,
    NotFoundError,
    ServiceError,
    ArchieClientError,
    TokenRefreshError,
    ConfigurationError,
    InvalidServiceURL,
    LayerCapabilityError,
    InvalidParameterError,
    MissingGeometryError,
)


class TestArcGISError:
    def test_message_format(self):
        err = ArcGISError(code=999, message="Something went wrong")

        assert str(err) == "ArcGIS error 999: Something went wrong"

    def test_parsed_attributes(self):
        err = ArcGISError(code=403, message="Access denied", details=["detail1"])

        assert err.code == 403
        assert err.message == "Access denied"
        assert err.details == ["detail1"]

    def test_details_defaults_to_empty_list(self):
        err = ArcGISError(code=403, message="Access denied")

        assert err.details == []
        assert isinstance(err.details, list)

    def test_raw_response_defaults_to_none(self):
        err = ArcGISError(code=403, message="Access denied")

        assert err.raw_response is None

    def test_raw_response_stored(self):
        raw = {"error": {"code": 403, "message": "Access denied", "details": []}}
        err = ArcGISError(code=403, message="Access denied", raw_response=raw)

        assert err.raw_response is raw


class TestHierarchy:
    @pytest.mark.parametrize(
        "exc_class",
        [
            TokenExpiredError,
            TokenMissingError,
            AuthorizationError,
            NotFoundError,
            ServiceError,
        ],
    )
    def test_arcgis_subclasses_inherit_from_arcgis_error(self, exc_class):
        err = exc_class(code=0, message="test")

        assert isinstance(err, ArcGISError)
        assert isinstance(err, ArchieError)
        assert isinstance(err, Exception)

    @pytest.mark.parametrize(
        "exc_class",
        [
            TokenRefreshError,
            ConfigurationError,
            InvalidServiceURL,
            LayerCapabilityError,
            InvalidParameterError,
            MissingGeometryError,
        ],
    )
    def test_client_subclasses_inherit_from_archibald_client_error(self, exc_class):
        err = exc_class("test")

        assert isinstance(err, ArchieClientError)
        assert isinstance(err, ArchieError)
        assert isinstance(err, Exception)

    def test_arcgis_error_is_not_archibald_client_error(self):
        err = ArcGISError(code=0, message="test")

        assert not isinstance(err, ArchieClientError)

    def test_archibald_client_error_is_not_arcgis_error(self):
        err = TokenRefreshError("test")

        assert not isinstance(err, ArcGISError)


class TestCatchability:
    def test_token_expired_caught_as_arcgis_error(self):
        with pytest.raises(ArcGISError):
            raise TokenExpiredError(code=498, message="Invalid token.")

    def test_token_expired_caught_as_archibald_error(self):
        with pytest.raises(ArchieError):
            raise TokenExpiredError(code=498, message="Invalid token.")

    def test_token_refresh_caught_as_archibald_client_error(self):
        with pytest.raises(ArchieClientError):
            raise TokenRefreshError("Refresh failed after retry.")

    def test_token_refresh_caught_as_archibald_error(self):
        with pytest.raises(ArchieError):
            raise TokenRefreshError("Refresh failed after retry.")

    def test_layer_capability_error_caught_as_archibald_client_error(self):
        with pytest.raises(ArchieClientError):
            raise LayerCapabilityError("Layer does not support query.")

    def test_invalid_parameter_error_caught_as_archibald_client_error(self):
        with pytest.raises(ArchieClientError):
            raise InvalidParameterError("key_fields must not be empty.")

    def test_missing_geometry_error_caught_as_archibald_client_error(self):
        with pytest.raises(ArchieClientError):
            raise MissingGeometryError("No geometry present.")
