"""Named ``Literal`` types shared across archibald, and their runtime validation.

A ``Literal`` lives here once it has a name and is used or exported in more
than one place; one-off parameter ``Literal``s stay inline.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal, get_args

from archibald.exceptions import InvalidParameterError

EditKind = Literal["adds", "updates", "deletes"]
"""Kind of edit an applyEdits result item belongs to."""

EditStatus = Literal["succeeded", "failed", "unknown"]
"""Outcome of a single edit, derived from ``success`` and ``error``."""


def validate_literal_values(
    values: str | Iterable[str] | None, literal_type: Any, name: str
) -> set[str] | None:
    """Validate an argument against a ``Literal`` type and return its values as a set.

    Type checkers already reject invalid literals; this catches them at
    runtime for callers who pass untyped strings.

    Args:
        values: One value (e.g. ``"adds"``), an iterable of values, or None.
        literal_type: The ``Literal`` type whose arguments are the valid values.
        name: The argument name (e.g. ``"kinds"``), quoted in the error.

    Returns:
        The values as a set, or None when ``values`` is None.

    Raises:
        InvalidParameterError: If any value is not one of the ``Literal``'s
            arguments. The message lists every invalid value and every valid
            one.
    """
    if values is None:
        return None
    allowed = get_args(literal_type)
    items = {values} if isinstance(values, str) else set(values)
    invalid = sorted(str(v) for v in items - set(allowed))
    if invalid:
        raise InvalidParameterError(
            f"Invalid {name}: {', '.join(invalid)}. "
            f"Expected one of: {', '.join(allowed)}."
        )
    return items
