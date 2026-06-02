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
└── ArchieClientError            ← archibald itself caused this error
    ├── TokenRefreshError        ← token refresh attempted and failed
    ├── ConfigurationError       ← client or auth configured incorrectly
    ├── InvalidServiceURL        ← URL does not match expected service type
    ├── LayerCapabilityError     ← layer does not support the operation
    ├── InvalidParameterError    ← a caller-supplied parameter is invalid
    └── MissingGeometryError     ← geometry required but unavailable
```

## Reference

::: archibald.exceptions.ArchieError

::: archibald.exceptions.ArcGISError

::: archibald.exceptions.TokenExpiredError

::: archibald.exceptions.TokenMissingError

::: archibald.exceptions.AuthorizationError

::: archibald.exceptions.NotFoundError

::: archibald.exceptions.ServiceError

::: archibald.exceptions.ArchieClientError

::: archibald.exceptions.TokenRefreshError

::: archibald.exceptions.ConfigurationError

::: archibald.exceptions.InvalidServiceURL

::: archibald.exceptions.LayerCapabilityError

::: archibald.exceptions.InvalidParameterError

::: archibald.exceptions.MissingGeometryError
