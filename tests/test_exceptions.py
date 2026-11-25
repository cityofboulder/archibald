import pytest
from archibald.exceptions import (
    AddressNotFoundError,
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
    CapabilityError,
    LayerCapabilityError,
    ServiceCapabilityError,
    InvalidParameterError,
    RejectedAddressError,
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
            AddressNotFoundError,
        ],
        ids=[
            "token-expired",
            "token-missing",
            "authorization",
            "not-found",
            "service",
            "address-not-found",
        ],
    )
    def test_arcgis_subclasses_inherit_from_arcgis_error(self, exc_class):
        err = exc_class(code=0, message="test")

        assert isinstance(err, ArcGISError)
        assert isinstance(err, ArchieError)
        assert isinstance(err, Exception)

    @pytest.mark.parametrize(
        "err",
        [
            TokenRefreshError("test"),
            ConfigurationError("test"),
            InvalidServiceURL("test"),
            CapabilityError("test"),
            LayerCapabilityError("test"),
            ServiceCapabilityError("test"),
            InvalidParameterError("test"),
            RejectedAddressError("empty", "test"),
            MissingGeometryError("test"),
        ],
        ids=[
            "token-refresh",
            "configuration",
            "invalid-service-url",
            "capability",
            "layer-capability",
            "service-capability",
            "invalid-parameter",
            "rejected-address",
            "missing-geometry",
        ],
    )
    def test_client_subclasses_inherit_from_archibald_client_error(self, err):
        assert isinstance(err, ArchieClientError)
        assert isinstance(err, ArchieError)
        assert isinstance(err, Exception)

    @pytest.mark.parametrize(
        "err, parent",
        [
            (AddressNotFoundError(code=400, message="test"), ServiceError),
            (LayerCapabilityError("test"), CapabilityError),
            (ServiceCapabilityError("test"), CapabilityError),
            (RejectedAddressError("empty", "test"), InvalidParameterError),
        ],
        ids=[
            "address-not-found-is-service",
            "layer-capability-is-capability",
            "service-capability-is-capability",
            "rejected-address-is-invalid-parameter",
        ],
    )
    def test_subclasses_inherit_from_intermediate_parent(self, err, parent):
        assert isinstance(err, parent)

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

    @pytest.mark.parametrize(
        "exc_class",
        [LayerCapabilityError, ServiceCapabilityError],
        ids=["layer", "service"],
    )
    def test_capability_errors_caught_as_capability_error(self, exc_class):
        with pytest.raises(CapabilityError, match="does not support"):
            raise exc_class("Service does not support batch geocoding.")


class TestRejectedAddressError:
    def test_carries_rule_and_reason_when_constructed(self):
        err = RejectedAddressError("po_box", "PO Box addresses are not geocodable.")

        assert err.rule == "po_box"
        assert err.reason == "PO Box addresses are not geocodable."

    def test_message_names_rule_and_reason_when_raised(self):
        with pytest.raises(
            RejectedAddressError,
            match=r"^Address rejected by 'empty' rule: Address is blank\.$",
        ):
            raise RejectedAddressError("empty", "Address is blank.")
