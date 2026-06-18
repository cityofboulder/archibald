"""AddAttachmentsResult: aggregated response from an addAttachment operation."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import pandas as pd

from archibald.models.edit_result_item import EditResultItem


@dataclass
class AddAttachmentsResult:
    """Aggregated per-attachment results from one or more addAttachment calls.

    Each result item's ``object_id`` is the attachment OID assigned by the
    server, not the feature OID. Inspect ``has_failures`` and ``failed`` to
    detect partial failures without iterating manually.
    """

    results: list[EditResultItem]

    @property
    def has_failures(self) -> bool:
        """True if any attachment result reports success=False."""
        return any(not r.success for r in self.results)

    @property
    def failed(self) -> list[EditResultItem]:
        """Attachment results where success=False."""
        return [r for r in self.results if not r.success]

    def to_frame(self) -> pd.DataFrame:
        """Return results as a pandas DataFrame.

        Each row corresponds to one attachment result. Error dicts are
        flattened into prefixed columns (e.g. ``error_code``,
        ``error_description``); successful rows have ``NaN`` in those columns.

        Returns:
            DataFrame with columns ``object_id``, ``global_id``, ``success``,
            and any ``error_*`` columns present across the result set.
        """
        records = [
            {**dataclasses.asdict(r), "error": r.error or {}} for r in self.results
        ]
        return pd.json_normalize(records, sep="_")
