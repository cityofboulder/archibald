"""ApplyEditsOperation: execute applyEdits against a feature layer with batching support."""

from __future__ import annotations

import json
import warnings
from typing import TYPE_CHECKING

import anyio
import geopandas as gpd
import pandas as pd

from archibald.exceptions import ServiceError
from archibald.models.apply_edits_result import ApplyEditsResult
from archibald.serializers._features import pack_batches, serialize_features

if TYPE_CHECKING:
    from archibald.services import FeatureLayer


class ApplyEditsOperation:
    """Execute applyEdits on a FeatureLayer with batching and async polling support.

    Holds a reference to its owning FeatureLayer to access the client, layer
    path, and metadata. Instantiated once at FeatureLayer.__init__ time.
    """

    def __init__(self, layer: FeatureLayer) -> None:
        self._layer = layer
        self._endpoint = f"{layer._layer_path}/applyEdits"

    async def execute(
        self,
        adds: pd.DataFrame | gpd.GeoDataFrame | None = None,
        updates: pd.DataFrame | gpd.GeoDataFrame | None = None,
        deletes: pd.DataFrame | pd.Series | list[int] | None = None,
        *,
        rollback_on_failure: bool = False,
        apply_coded_values: bool = False,
        poll_timeout: float = 300.0,
    ) -> ApplyEditsResult:
        """Serialize inputs, pack into batches, POST, and return aggregated results.

        Adds are serialized with include_objectid=False; updates with
        include_objectid=True. Deletes are normalized to list[int] from whatever
        the caller provides (list[int], DataFrame, or Series).

        Args:
            adds: Rows to add as new features. OBJECTIDs are excluded.
            updates: Rows to update (must include the OBJECTID column).
            deletes: OBJECTIDs to delete — list[int], DataFrame with an OBJECTID
                column, or a Series of integer OBJECTIDs.
            rollback_on_failure: Request server-side rollback on failure. The
                layer must support this capability; a ValueError is raised if it
                does not. When batching produces > 1 POST, rollback is per-batch
                only (a warning is emitted).
            apply_coded_values: When True, translate human-readable domain names
                in the DataFrame back to their raw codes before serialization.
            poll_timeout: Maximum seconds to wait for an async job to complete
                before raising TimeoutError. Applies per batch when the layer
                uses server-side async editing. Defaults to 300 seconds.

        Returns:
            ApplyEditsResult with all add, update, and delete results merged.

        Raises:
            ValueError: If rollback_on_failure=True but the layer does not support it.
            TimeoutError: If an async job does not complete within poll_timeout seconds.

        Warns:
            UserWarning: If rollback_on_failure=True and > 1 batch is produced
                (rollback is per-batch, not cross-batch).
            UserWarning: For each DataFrame column that falls outside the editable
                field set and will not be sent.
        """
        fields = await self._layer.fields()
        objectid_field = await self._layer.objectid_field()

        serialized_adds = (
            serialize_features(
                adds, fields, objectid_field=None, apply_coded_values=apply_coded_values
            )
            if adds is not None
            else []
        )
        serialized_updates = (
            serialize_features(
                updates,
                fields,
                objectid_field=objectid_field,
                apply_coded_values=apply_coded_values,
            )
            if updates is not None
            else []
        )
        delete_oids = await self._normalize_deletes(deletes)

        if not serialized_adds and not serialized_updates and not delete_oids:
            return ApplyEditsResult(
                add_results=[], update_results=[], delete_results=[]
            )

        batches = pack_batches(serialized_adds, serialized_updates, delete_oids)

        if rollback_on_failure and not await self._layer.supports_rollback_on_failure():
            warnings.warn(
                (
                    f"Layer {self._layer._layer_path} does not support rollbackOnFailure. "
                    "The applyEdits operation will proceed without rollback on failure."
                ),
                stacklevel=2,
            )
            rollback_on_failure = False

        if rollback_on_failure and len(batches) > 1:
            warnings.warn(
                "rollback_on_failure=True but the payload spans multiple batches. "
                "Rollback is per-batch only — a failure in one batch will not roll "
                "back successfully applied batches.",
                stacklevel=2,
            )

        use_async = len(batches) > 1 and await self._layer.supports_async_apply_edits()

        return await self._post_batches(
            batches,
            rollback_on_failure=rollback_on_failure,
            use_async=use_async,
            poll_timeout=poll_timeout,
        )

    async def _normalize_deletes(
        self,
        deletes: pd.DataFrame | pd.Series | list[int] | None,
    ) -> list[int]:
        """Normalize the deletes argument to a list of integer OBJECTIDs.

        Args:
            deletes: OBJECTIDs as list[int], DataFrame (uses objectid_field column),
                or Series. None returns an empty list.

        Returns:
            List of integer OBJECTIDs.
        """
        objectid_field = await self._layer.objectid_field()

        if deletes is None:
            return []
        if isinstance(deletes, list):
            return deletes
        if isinstance(deletes, pd.DataFrame):
            return deletes[objectid_field].tolist()
        return deletes.tolist()

    async def _post_batch(
        self,
        batch: dict,
        *,
        rollback_on_failure: bool,
        use_async: bool,
        poll_timeout: float,
    ) -> ApplyEditsResult:
        """POST a single batch and return its ApplyEditsResult.

        Encodes adds and updates as JSON strings for ESRI form-encoded POST.
        If use_async=True, the POST includes async=true and the response
        statusUrl is polled until the job completes.

        Args:
            batch: A single batch dict from pack_batches (may contain adds,
                updates, and/or deletes keys).
            rollback_on_failure: Include rollbackOnFailure=true in the POST body.
            use_async: Include async=true in the POST body and poll for results.
            poll_timeout: Forwarded to _poll_status as the per-job timeout.

        Returns:
            ApplyEditsResult parsed from the applyEdits response.
        """
        body: dict = {}
        if "adds" in batch:
            body["adds"] = json.dumps(batch["adds"])
        if "updates" in batch:
            body["updates"] = json.dumps(batch["updates"])
        if "deletes" in batch:
            body["deletes"] = batch["deletes"]  # already a comma-separated string
        if rollback_on_failure:
            body["rollbackOnFailure"] = "true"
        if use_async:
            body["async"] = "true"

        response = await self._layer._client.post(endpoint=self._endpoint, data=body)
        response_body = response.json()

        if use_async:
            status_url = response_body["statusUrl"]
            response_body = await self._poll_status(status_url, timeout=poll_timeout)

        return ApplyEditsResult.from_esri_response(response_body)

    async def _poll_status(self, status_url: str, *, timeout: float) -> dict:
        """Poll an async job status URL until the job reaches a terminal state.

        Uses exponential backoff starting at 0.5 s, doubling each retry up to
        a 5 s cap. The url= kwarg on client.get bypasses the base URL so the
        full status URL is used as-is.

        Terminal states per the ESRI async operations spec:
        - "Completed" / "CompletedWithErrors": fetches resultUrl and returns the body.
        - "Failed": raises ServiceError immediately.

        All other statuses ("Pending", "InProgress", etc.) are non-terminal and
        continue polling. HTTP-level and ESRI envelope errors are handled upstream
        by the client's @handle_esri_errors decorator.

        Args:
            status_url: Full URL of the async job status endpoint.
            timeout: Maximum seconds to wait before raising TimeoutError.

        Returns:
            Edit results body dict fetched from the resultUrl on completion.

        Raises:
            ServiceError: If the job status is "Failed".
            TimeoutError: If the job does not reach a terminal state within timeout seconds.
        """
        delay = 0.5
        max_delay = 5.0
        with anyio.fail_after(timeout):
            while True:
                response = await self._layer._client.get(url=status_url)
                body = response.json()
                status = body.get("status")
                if status in ("Completed", "CompletedWithErrors"):
                    result_response = await self._layer._client.get(
                        url=body["resultUrl"]
                    )
                    return result_response.json()
                if status == "Failed":
                    raise ServiceError(
                        code=-1,
                        message="Async applyEdits job failed.",
                        raw_response=body,
                    )
                await anyio.sleep(delay)
                delay = min(delay * 2, max_delay)

    async def _post_batches(
        self,
        batches: list[dict],
        *,
        rollback_on_failure: bool,
        use_async: bool,
        poll_timeout: float,
    ) -> ApplyEditsResult:
        """Fan out batch POSTs in parallel via anyio.create_task_group and merge results.

        Args:
            batches: List of batch body dicts from pack_batches.
            rollback_on_failure: Passed through to each _post_batch call.
            use_async: Passed through to each _post_batch call.
            poll_timeout: Passed through to each _post_batch call.

        Returns:
            Merged ApplyEditsResult from all batches in posting order.
        """
        batch_results: list[ApplyEditsResult | None] = [None] * len(batches)

        async def post_one(idx: int, batch: dict) -> None:
            batch_results[idx] = await self._post_batch(
                batch,
                rollback_on_failure=rollback_on_failure,
                use_async=use_async,
                poll_timeout=poll_timeout,
            )

        async with anyio.create_task_group() as tg:
            for idx, batch in enumerate(batches):
                tg.start_soon(post_one, idx, batch)

        return ApplyEditsResult.merge(batch_results)  # type: ignore[arg-type]
