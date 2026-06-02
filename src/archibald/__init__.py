"""archibald — async Python client for ESRI ArcGIS REST APIs."""

from archibald.auth import ArcGISAuth, NoAuth, UserTokenAuth
from archibald.client import ArchieClient
from archibald.exceptions import (
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
from archibald.models import ApplyEditsResult, EditResultItem, FieldsResult, QueryResult
from archibald.services import (
    BaseLayer,
    BaseService,
    FeatureLayer,
    FeatureService,
    MapLayer,
    MapService,
)

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
