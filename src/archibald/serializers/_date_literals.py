"""Per-ESRI-type keyword/format rules for DATE/TIMESTAMP/TIME literals in WHERE clauses."""

from __future__ import annotations

import re
from datetime import datetime

_DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
_TIME_RE = r"^\d{2}:\d{2}:\d{2}$"
_TIMESTAMP_RE = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"
_TIMESTAMP_OFFSET_RE = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{2}:\d{2}$"

ESRI_DATE_TYPE_KEYWORDS: dict[str, dict[str, tuple[str, str, str]]] = {
    "esriFieldTypeDate": {
        "DATE": (_DATE_RE, "%Y-%m-%d", "DATE 'YYYY-MM-DD'"),
        "TIMESTAMP": (
            _TIMESTAMP_RE,
            "%Y-%m-%d %H:%M:%S",
            "TIMESTAMP 'YYYY-MM-DD HH:MM:SS'",
        ),
    },
    "esriFieldTypeDateOnly": {
        "DATE": (_DATE_RE, "%Y-%m-%d", "DATE 'YYYY-MM-DD'"),
    },
    "esriFieldTypeTimeOnly": {
        "TIME": (_TIME_RE, "%H:%M:%S", "TIME 'HH:MM:SS'"),
    },
    "esriFieldTypeTimestampOffset": {
        "TIMESTAMP": (
            _TIMESTAMP_OFFSET_RE,
            "%Y-%m-%d %H:%M:%S %z",
            "TIMESTAMP 'YYYY-MM-DD HH:MM:SS +HH:MM'",
        ),
    },
}


def matches_literal_format(value: str, esri_type: str, keyword: str) -> bool:
    """Check `value` against both the shape and calendar validity required for `keyword` on `esri_type`.

    The shape regex enforces exact zero-padded width (rejecting e.g.
    "2018-6-5"); `datetime.strptime` additionally rejects values that pass the
    shape regex but aren't real calendar dates/times (e.g. "2020-01-32",
    "2020-13-01"), since `strptime` alone is lenient about digit padding.
    """
    value_re, strptime_fmt, _ = ESRI_DATE_TYPE_KEYWORDS[esri_type][keyword]
    if not re.match(value_re, value):
        return False
    try:
        datetime.strptime(value, strptime_fmt)
    except ValueError:
        return False
    return True
