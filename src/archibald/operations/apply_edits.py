"""ApplyEditsOperation: execute applyEdits against a feature layer with batching support."""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

import anyio
import geopandas as gpd
import httpx
import pandas as pd

from archibald.errors import is_outcome_unknown
from archibald.exceptions import InvalidParameterError, ServiceError
from archibald.models.apply_edits_result import ApplyEditsResult
from archibald.models.edit_result_item import EditKind, EditResultItem
from archibald.serializers._features import (
    MAX_BATCH_BYTES,
    pack_batches,
    serialize_features,
)

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
        rollback_on_failure: bool = True,
        apply_coded_values: bool = False,
        poll_timeout: float | None = None,
        use_server_async: bool | None = None,
        max_batch_bytes: int | None = None,
    ) -> ApplyEditsResult:
        """Serialize inputs, pack into batches, POST, and return aggregated results.

        Adds are serialized with include_objectid=False; updates with
        include_objectid=True. Deletes are normalized to a DataFrame with an
        OBJECTID column from whatever the caller provides (list[int],
        DataFrame, or Series).

        Args:
            adds: Rows to add as new features. OBJECTIDs are excluded.
            updates: Rows to update (must include the OBJECTID column).
            deletes: OBJECTIDs to delete — list[int], DataFrame with an OBJECTID
                column, or a Series of integer OBJECTIDs.
            rollback_on_failure: Sent as rollbackOnFailure on every batch. When
                True (ESRI's default), a batch is applied only if all of its
                edits succeed; when False, successful edits are applied.
                Rollback is per batch, never across batches. Layers without
                supportsRollbackOnFailureParameter always roll back regardless;
                FeatureLayer.apply_edits warns about that case.
            apply_coded_values: When True, translate human-readable domain names
                in the DataFrame back to their raw codes before serialization.
            poll_timeout: Maximum seconds to wait for an async job to complete
                before its batch is reported as failed. Applies per batch when
                the layer uses server-side async editing, and is measured from
                when the batch holds a job permit, so time spent waiting behind
                other jobs is not counted. Defaults to the client's job_timeout.
                Ignored when batches are sent synchronously.
            use_server_async: Whether batches use server-side async processing.
                True sends every batch async, even a single one; False always
                sends synchronously. None falls back to the client's
                use_server_async, and if that is also None, auto-detects:
                async only when there is more than one batch and the layer
                advertises supportsAsyncApplyEdits. True is sent as-is;
                FeatureLayer.apply_edits falls back to sync for layers that
                do not support async.
            max_batch_bytes: Soft upper bound, in bytes, for each POST body.
                Defaults to the client's max_batch_bytes.

        Returns:
            ApplyEditsResult with all add, update, and delete results merged.
            A batch that fails (ESRI error envelope, transport or HTTP error,
            failed or timed-out async job) does not raise or cancel the other
            batches; each of its edits is instead a ``success=False`` item
            built by ``EditResultItem._from_exception``, carrying
            ``error["outcome_unknown"]`` and, for async jobs,
            ``error["status_url"]``. Failed adds report ``object_id`` -1 and
            line up with input rows only by position.
            Retrying an add whose outcome is unknown can create a duplicate.

            Every item's ``kind`` and ``position`` (its row in that kind's
            input frame) are set by ``ApplyEditsResult._merge``. The result
            keeps shallow copies of the input frames (deletes as a frame) so
            ``to_frame`` can return each edit's input row; this keeps them in
            memory while the result is.

        Raises:
            InvalidParameterError: If max_batch_bytes is not positive or
                exceeds MAX_BATCH_BYTES.

        Warns:
            UserWarning: For each DataFrame column that falls outside the editable
                field set and will not be sent.
        """
        serialized_adds: list[dict[str, Any]] = []
        serialized_updates: list[dict[str, Any]] = []
        delete_oids: list[int] = []
        inputs: dict[EditKind, pd.DataFrame | gpd.GeoDataFrame] = {}

        if max_batch_bytes is None:
            max_batch_bytes = self._layer._client._max_batch_bytes
        elif not 0 < max_batch_bytes <= MAX_BATCH_BYTES:
            raise InvalidParameterError(
                f"max_batch_bytes must be between 1 and {MAX_BATCH_BYTES}; "
                f"got {max_batch_bytes}."
            )
        if use_server_async is None:
            use_server_async = self._layer._client._use_server_async

        fields = await self._layer.fields()
        objectid_field = await self._layer.objectid_field()

        if adds is not None:
            serialized_adds = serialize_features(
                adds, fields, objectid_field=None, apply_coded_values=apply_coded_values
            )
            inputs["adds"] = adds.copy(deep=False)

        if updates is not None:
            serialized_updates = serialize_features(
                updates,
                fields,
                objectid_field=objectid_field,
                apply_coded_values=apply_coded_values,
            )
            inputs["updates"] = updates.copy(deep=False)

        delete_frame = self._normalize_deletes(deletes, objectid_field)
        if delete_frame is not None:
            delete_oids = delete_frame[objectid_field].tolist()
            inputs["deletes"] = delete_frame.copy(deep=False)

        if not serialized_adds and not serialized_updates and not delete_oids:
            return ApplyEditsResult(
                add_results=[], update_results=[], delete_results=[], _inputs=inputs
            )

        batches = pack_batches(
            serialized_adds,
            serialized_updates,
            delete_oids,
            max_bytes=max_batch_bytes,
        )

        if use_server_async is None:
            use_async = (
                len(batches) > 1 and await self._layer.supports_async_apply_edits()
            )
        else:
            use_async = use_server_async

        if poll_timeout is None:
            poll_timeout = self._layer._client._job_timeout

        result = await self._post_batches(
            batches,
            objectid_field=objectid_field,
            rollback_on_failure=rollback_on_failure,
            use_async=use_async,
            poll_timeout=poll_timeout,
        )
        result._inputs = inputs
        return result

    @staticmethod
    def _normalize_deletes(
        deletes: pd.DataFrame | pd.Series | list[int] | None, objectid_field: str
    ) -> pd.DataFrame | None:
        """Return the deletes argument as a DataFrame with an OBJECTID column.

        A DataFrame is returned as-is; a list or Series of OBJECTIDs becomes a
        one-column frame named ``objectid_field`` (a Series keeps its index).

        Args:
            deletes: OBJECTIDs as list[int], DataFrame (uses the objectid_field
                column), or Series. None returns None.
            objectid_field: Name of the layer's OBJECTID field.
        """
        if deletes is None or isinstance(deletes, pd.DataFrame):
            return deletes
        return pd.DataFrame({objectid_field: deletes})

    async def _post_batch(
        self,
        batch: dict,
        *,
        objectid_field: str,
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
            objectid_field: Name of the layer's OBJECTID field, used to report
                update IDs when the batch fails.
            rollback_on_failure: Value of rollbackOnFailure, always sent in the
                POST body because ESRI defaults it to true when omitted.
            use_async: Include async=true in the POST body and poll for results.
            poll_timeout: Forwarded to _poll_status as the per-job timeout.

        Returns:
            ApplyEditsResult parsed from the applyEdits response. Failures are
            returned via ``_failed_batch_result`` instead of raised: a failed
            POST is flagged ``outcome_unknown`` per ``is_outcome_unknown``; an
            async POST with no statusUrl, or a job that fails, times out, or
            cannot be polled, is flagged ``outcome_unknown`` and carries the
            job's ``status_url`` when known. ESRI error envelopes become items
            carrying the server's error dict.
        """
        body: dict = {}
        if "adds" in batch:
            body["adds"] = json.dumps(batch["adds"])
        if "updates" in batch:
            body["updates"] = json.dumps(batch["updates"])
        if "deletes" in batch:
            body["deletes"] = batch["deletes"]  # already a comma-separated string
        body["rollbackOnFailure"] = "true" if rollback_on_failure else "false"
        if use_async:
            body["async"] = "true"

        try:
            response = await self._layer._client.post(
                endpoint=self._endpoint, data=body
            )
            response_body = response.json()
        except Exception as exc:
            return self._failed_batch_result(
                batch, exc, objectid_field, outcome_unknown=is_outcome_unknown(exc)
            )

        if use_async:
            status_url = response_body.get("statusUrl")
            if status_url is None:
                exc = ServiceError(
                    code=-1,
                    message="Async applyEdits response had no statusUrl.",
                    raw_response=response_body,
                )
                return self._failed_batch_result(
                    batch, exc, objectid_field, outcome_unknown=True
                )
            try:
                response_body = await self._poll_status(
                    status_url, timeout=poll_timeout
                )
            except Exception as exc:
                return self._failed_batch_result(
                    batch,
                    exc,
                    objectid_field,
                    outcome_unknown=True,
                    status_url=status_url,
                )

        return ApplyEditsResult._from_esri_response(response_body)

    @staticmethod
    def _failed_batch_result(
        batch: dict,
        exc: Exception,
        objectid_field: str,
        *,
        outcome_unknown: bool,
        status_url: str | None = None,
    ) -> ApplyEditsResult:
        """Build a result marking every edit in a batch as failed.

        Adds report ``object_id`` -1 since no OBJECTID exists yet; updates
        report the OBJECTID from their attributes (-1 if absent); deletes
        report the OBJECTID being deleted. See ``errors.failure_error`` for the
        error dict each item carries.

        Args:
            batch: The batch dict from pack_batches that failed.
            exc: Exception raised while posting or polling the batch.
            objectid_field: Name of the layer's OBJECTID field.
            outcome_unknown: Whether the server may have applied the batch.
            status_url: Async job status URL, if the batch was submitted async.

        Returns:
            ApplyEditsResult with one ``success=False`` item per edit, in batch
            order.
        """
        add_ids = [-1] * len(batch.get("adds", []))
        update_ids = [
            feat.get("attributes", {}).get(objectid_field, -1)
            for feat in batch.get("updates", [])
        ]
        deletes = batch.get("deletes", "")
        delete_ids = [int(oid) for oid in deletes.split(",")] if deletes else []

        def items(ids: list[int]) -> list[EditResultItem]:
            """Failed items for ``ids`` sharing this batch's failure details."""
            return [
                EditResultItem._from_exception(
                    exc,
                    object_id=oid,
                    outcome_unknown=outcome_unknown,
                    status_url=status_url,
                )
                for oid in ids
            ]

        return ApplyEditsResult(
            add_results=items(add_ids),
            update_results=items(update_ids),
            delete_results=items(delete_ids),
        )

    async def _poll_status(self, status_url: str, *, timeout: float) -> dict:
        """Poll an async job status URL until the job reaches a terminal state.

        Uses exponential backoff starting at 0.5 s, doubling each retry up to
        a 5 s cap. The url= kwarg on client.get bypasses the base URL so the
        full status URL is used as-is.

        Terminal states per the ESRI async operations spec:
        - "Completed" / "CompletedWithErrors": fetches resultUrl and returns the body.
        - "Failed": raises ServiceError immediately.

        All other statuses ("Pending", "InProgress", etc.) are non-terminal and
        continue polling. A status or resultUrl GET that fails with a transport
        error or a 5xx response is retried with the same backoff until timeout,
        since the job keeps running server-side. ESRI envelope errors and 4xx
        responses are raised immediately.

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
                try:
                    response = await self._layer._client.get(url=status_url)
                    body = response.json()
                    status = body.get("status")
                    if status in ("Completed", "CompletedWithErrors"):
                        result_response = await self._layer._client.get(
                            url=body["resultUrl"]
                        )
                        return result_response.json()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code < 500:
                        raise
                except httpx.TransportError:
                    pass
                else:
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
        objectid_field: str,
        rollback_on_failure: bool,
        use_async: bool,
        poll_timeout: float,
    ) -> ApplyEditsResult:
        """Fan out batch POSTs in parallel via anyio.create_task_group and merge results.

        When use_async is True, each batch holds one of the client's job
        permits from POST until its result is fetched, so no more than
        max_concurrent_jobs async jobs exist on the server at once. Sync POSTs
        are bounded by the client's request limiter alone. _post_batch returns
        a failed batch as failed items rather than raising, so one batch's
        failure never cancels its siblings.

        Args:
            batches: List of batch body dicts from pack_batches.
            objectid_field: Passed through to each _post_batch call.
            rollback_on_failure: Passed through to each _post_batch call.
            use_async: Passed through to each _post_batch call.
            poll_timeout: Passed through to each _post_batch call.

        Returns:
            Merged ApplyEditsResult from all batches in posting order.
        """
        batch_results: list[ApplyEditsResult | None] = [None] * len(batches)

        async def post_one(idx: int, batch: dict) -> None:
            permit = (
                self._layer._client._job_limiter
                if use_async
                else contextlib.nullcontext()
            )
            async with permit:
                batch_results[idx] = await self._post_batch(
                    batch,
                    objectid_field=objectid_field,
                    rollback_on_failure=rollback_on_failure,
                    use_async=use_async,
                    poll_timeout=poll_timeout,
                )

        async with anyio.create_task_group() as tg:
            for idx, batch in enumerate(batches):
                tg.start_soon(post_one, idx, batch)

        return ApplyEditsResult._merge(batch_results)  # type: ignore[arg-type]
