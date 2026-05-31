from __future__ import annotations


class ArchieError(Exception):
    """Root exception for all archie errors."""


# ---------------------------------------------------------------------------
# ESRI-originated errors
# ---------------------------------------------------------------------------


class ArcGISError(ArchieError):
    """ESRI returned an error envelope in the response body."""

    def __init__(
        self,
        code: int,
        message: str,
        details: list | None = None,
        raw_response: dict | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or []
        self.raw_response = raw_response
        super().__init__(f"ArcGIS error {code}: {message}")


class TokenExpiredError(ArcGISError):
    """Token is invalid or expired (ESRI code 498)."""


class TokenMissingError(ArcGISError):
    """Token is required but absent (ESRI code 499)."""


class AuthorizationError(ArcGISError):
    """Caller lacks permission for this resource (ESRI code 403)."""


class NotFoundError(ArcGISError):
    """Requested resource does not exist (ESRI code 404)."""


class ServiceError(ArcGISError):
    """Catch-all for unrecognised ESRI error codes."""


# ---------------------------------------------------------------------------
# archie-originated errors
# ---------------------------------------------------------------------------


class ArchieClientError(ArchieError):
    """archie itself caused this error, not ESRI."""


class TokenRefreshError(ArchieClientError):
    """A token refresh was attempted and failed."""


class ConfigurationError(ArchieClientError):
    """The client or auth object was configured incorrectly."""


class InvalidServiceURL(ArchieClientError):
    """The provided URL does not match the expected service type."""


class LayerCapabilityError(ArchieClientError):
    """The layer does not support the requested operation."""


class InvalidParameterError(ArchieClientError):
    """A parameter supplied by the caller is invalid."""


class MissingGeometryError(ArchieClientError):
    """A geometry-dependent operation was requested but geometry is unavailable."""
