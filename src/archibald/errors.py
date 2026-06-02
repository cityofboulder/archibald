from __future__ import annotations

import functools
from typing import Any, Callable

import httpx

from archibald.exceptions import (
    ArcGISError,
    AuthorizationError,
    NotFoundError,
    ServiceError,
    TokenExpiredError,
    TokenMissingError,
)

_ESRI_CODE_MAP: dict[int, type[ArcGISError]] = {
    498: TokenExpiredError,
    499: TokenMissingError,
    403: AuthorizationError,
    404: NotFoundError,
}


def parse_esri_error(response: httpx.Response) -> ArcGISError | None:
    """Parse an ESRI error envelope from a 200 response body.

    Returns the appropriate ArcGISError subclass if an error envelope is
    present, or None if the response body contains no error key.
    """
    body = response.json()
    error = body.get("error")
    if error is None:
        return None

    code = error.get("code", -1)
    message = error.get("message", "Unknown error")
    details = error.get("details", [])
    exc_class = _ESRI_CODE_MAP.get(code, ServiceError)

    return exc_class(code=code, message=message, details=details, raw_response=body)


def handle_esri_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that raises typed exceptions for ESRI error envelopes.

    Expects the wrapped coroutine to return an httpx.Response. If the
    response body contains an ESRI error envelope, the appropriate
    ArcGISError subclass is raised. Responses without an error envelope
    are returned unchanged.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Invoke the wrapped coroutine and raise on any ESRI error envelope."""
        response: httpx.Response = await func(*args, **kwargs)
        exc = parse_esri_error(response)
        if exc is not None:
            raise exc
        return response

    return wrapper
