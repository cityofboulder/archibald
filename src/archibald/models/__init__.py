"""Data models returned by operations."""

from archibald.models.apply_edits_result import ApplyEditsResult, EditResultItem
from archibald.models.fields_result import FieldsResult
from archibald.models.query_result import QueryResult

__all__ = [
    "ApplyEditsResult",
    "EditResultItem",
    "FieldsResult",
    "QueryResult",
]
