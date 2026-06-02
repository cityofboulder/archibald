# Exceptions

## Exception Hierarchy

```
ArchieError
├── ArcGISError                  ← ESRI returned an error envelope
│   ├── TokenExpiredError        ← token invalid or expired (code 498)
│   ├── TokenMissingError        ← token required but absent (code 499)
│   ├── AuthorizationError       ← insufficient permissions (code 403)
│   ├── NotFoundError            ← resource does not exist (code 404)
│   └── ServiceError             ← catch-all for other ESRI error codes
└── ArchieClientError            ← archie itself caused this error
    ├── TokenRefreshError        ← token refresh attempted and failed
    ├── ConfigurationError       ← client or auth configured incorrectly
    ├── InvalidServiceURL        ← URL does not match expected service type
    ├── LayerCapabilityError     ← layer does not support the operation
    ├── InvalidParameterError    ← a caller-supplied parameter is invalid
    └── MissingGeometryError     ← geometry required but unavailable
```

## Reference

::: archie.exceptions.ArchieError

::: archie.exceptions.ArcGISError

::: archie.exceptions.TokenExpiredError

::: archie.exceptions.TokenMissingError

::: archie.exceptions.AuthorizationError

::: archie.exceptions.NotFoundError

::: archie.exceptions.ServiceError

::: archie.exceptions.ArchieClientError

::: archie.exceptions.TokenRefreshError

::: archie.exceptions.ConfigurationError

::: archie.exceptions.InvalidServiceURL

::: archie.exceptions.LayerCapabilityError

::: archie.exceptions.InvalidParameterError

::: archie.exceptions.MissingGeometryError
