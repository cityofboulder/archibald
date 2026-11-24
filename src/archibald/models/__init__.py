"""Data models returned by operations."""

from archibald.models.apply_edits_result import ApplyEditsResult
from archibald.models.attachments_query_result import AttachmentsQueryResult
from archibald.models.attachments_result import AttachmentsResult
from archibald.models.edit_result_item import EditKind, EditResultItem, EditStatus
from archibald.models.fields_result import FieldsResult
from archibald.models.query_result import QueryResult

__all__ = [
    "AttachmentsQueryResult",
    "AttachmentsResult",
    "ApplyEditsResult",
    "EditKind",
    "EditResultItem",
    "EditStatus",
    "FieldsResult",
    "QueryResult",
]
