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


def is_outcome_unknown(exc: Exception) -> bool:
    """Whether a failed request may still have been applied by the server.

    True when the request may have reached the server before failing: a
    transport error other than a failure to connect or acquire a connection, a
    5xx HTTP status, a response that could not be parsed, or a TimeoutError
    from waiting on a server-side job (e.g. ``anyio.fail_after`` while
    polling). False for local errors and for failures that happen before the
    request is sent or that the server definitively rejected (4xx).

    Args:
        exc: Exception raised while sending the request or reading its response.

    Returns:
        True if the outcome of the request is unknown.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
        return False
    return isinstance(exc, (httpx.TransportError, ValueError, KeyError, TimeoutError))


def failure_error(
    exc: BaseException,
    *,
    outcome_unknown: bool,
    status_url: str | None = None,
) -> dict:
    """Build the error dict reported for a request that failed.

    An ArcGISError carrying an ESRI error envelope (``raw_response`` with an
    ``"error"`` key) means the server rejected the request, so its error dict
    is returned. Anything else, including an ArcGISError whose
    ``raw_response`` is missing or is not an envelope (e.g. an async job's
    status body), gets a dict mirroring ESRI's ``code``/``description`` shape
    plus ``exception`` (the exception class name) and ``outcome_unknown``.
    ``status_url``, when given, is added in both cases; the envelope itself is
    never modified.

    Args:
        exc: Exception raised by the request.
        outcome_unknown: Whether the server may have applied the request
            anyway; ignored for ESRI error envelopes.
        status_url: Async job status URL to report, if any.

    Returns:
        The error dict.
    """
    envelope = exc.raw_response if isinstance(exc, ArcGISError) else None
    if envelope is not None and "error" in envelope:
        error = envelope["error"]
        if status_url is not None:
            error = {**error, "status_url": status_url}
        return error
    error = {
        "code": getattr(exc, "code", -1),
        "description": str(exc) or type(exc).__name__,
        "exception": type(exc).__name__,
        "outcome_unknown": outcome_unknown,
    }
    if status_url is not None:
        error["status_url"] = status_url
    return error


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
