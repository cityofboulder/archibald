"""archie — async Python client for ESRI ArcGIS REST APIs."""

from archie.auth import ArcGISAuth, NoAuth, UserTokenAuth
from archie.client import ArchieClient
from archie.exceptions import (
    ArchieError,
    ArcGISError,
    ArchieClientError,
    AuthorizationError,
    ConfigurationError,
    InvalidParameterError,
    InvalidServiceURL,
    LayerCapabilityError,
    MissingGeometryError,
    NotFoundError,
    ServiceError,
    TokenExpiredError,
    TokenMissingError,
    TokenRefreshError,
)
from archie.models import ApplyEditsResult, EditResultItem, FieldsResult, QueryResult
from archie.services import BaseLayer, BaseService, FeatureLayer, FeatureService, MapLayer, MapService

__all__ = [
    # auth
    "ArcGISAuth",
    "NoAuth",
    "UserTokenAuth",
    # client
    "ArchieClient",
    # exceptions
    "ArchieError",
    "ArcGISError",
    "TokenExpiredError",
    "TokenMissingError",
    "AuthorizationError",
    "NotFoundError",
    "ServiceError",
    "ArchieClientError",
    "TokenRefreshError",
    "ConfigurationError",
    "InvalidServiceURL",
    "LayerCapabilityError",
    "InvalidParameterError",
    "MissingGeometryError",
    # models
    "QueryResult",
    "FieldsResult",
    "ApplyEditsResult",
    "EditResultItem",
    # services
    "BaseService",
    "BaseLayer",
    "FeatureService",
    "MapService",
    "FeatureLayer",
    "MapLayer",
]
