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
from archibald.models.edit_result_item import EditResultItem

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


def failed_items(
    exc: Exception,
    object_ids: list[int],
    *,
    outcome_unknown: bool,
) -> list[EditResultItem]:
    """Build one failed EditResultItem per ID from a single request failure.

    An ArcGISError carrying an ESRI error envelope (``raw_response`` with an
    ``"error"`` key) means the server rejected the request, so each item
    carries that error dict. Anything else, including an ArcGISError whose
    ``raw_response`` is missing or is not an envelope (e.g. an async job's
    status body), becomes an item built from the exception, flagged with
    ``outcome_unknown``.

    Args:
        exc: Exception raised by the request.
        object_ids: ID to report on each item, one item per ID.
        outcome_unknown: Whether the server may have applied the request
            anyway; ignored for ESRI error envelopes.

    Returns:
        List of ``success=False`` items in ``object_ids`` order.
    """
    envelope = exc.raw_response if isinstance(exc, ArcGISError) else None
    if envelope is not None and "error" in envelope:
        return [
            EditResultItem._from_esri({**envelope, "objectId": oid})
            for oid in object_ids
        ]
    return [
        EditResultItem._from_exception(
            exc, object_id=oid, outcome_unknown=outcome_unknown
        )
        for oid in object_ids
    ]


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
