"""ApplyEditsOperation: execute applyEdits against a feature layer with batching support."""

from __future__ import annotations

import json
import warnings
from typing import TYPE_CHECKING

import anyio
import geopandas as gpd
import pandas as pd

from archie.exceptions import ServiceError
from archie.models.apply_edits_result import ApplyEditsResult
from archie.serializers._features import pack_batches, serialize_features

if TYPE_CHECKING:
    from archie.services import FeatureLayer


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

        Returns:
            ApplyEditsResult with all add, update, and delete results merged.

        Raises:
            ValueError: If rollback_on_failure=True but the layer does not support it.

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

        use_async = await self._layer.supports_async_apply_edits()

        return await self._post_batches(
            batches,
            rollback_on_failure=rollback_on_failure,
            use_async=use_async,
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
            response_body = await self._poll_status(status_url)

        return ApplyEditsResult.from_esri_response(response_body)

    async def _poll_status(self, status_url: str) -> dict:
        """Poll an async job status URL until the job completes.

        Uses exponential backoff starting at 0.5 s, doubling each retry up to
        a 5 s cap. The url= kwarg on client.get bypasses the base URL so the
        full status URL is used as-is.

        Args:
            status_url: Full URL of the async job status endpoint.

        Returns:
            Final response body dict when the job status is esriJobSucceeded.

        Raises:
            ServiceError: If the job status is esriJobFailed.
        """
        delay = 0.5
        max_delay = 5.0
        while True:
            response = await self._layer._client.get(url=status_url)
            body = response.json()
            status = body.get("status")
            if status == "esriJobSucceeded":
                return body
            if status == "esriJobFailed":
                message = body.get("statusMessage", "Async applyEdits job failed.")
                raise ServiceError(code=-1, message=message, raw_response=body)
            await anyio.sleep(delay)
            delay = min(delay * 2, max_delay)

    async def _post_batches(
        self,
        batches: list[dict],
        *,
        rollback_on_failure: bool,
        use_async: bool,
    ) -> ApplyEditsResult:
        """Fan out batch POSTs in parallel via anyio.create_task_group and merge results.

        Args:
            batches: List of batch body dicts from pack_batches.
            rollback_on_failure: Passed through to each _post_batch call.
            use_async: Passed through to each _post_batch call.

        Returns:
            Merged ApplyEditsResult from all batches in posting order.
        """
        batch_results: list[ApplyEditsResult | None] = [None] * len(batches)

        async def post_one(idx: int, batch: dict) -> None:
            batch_results[idx] = await self._post_batch(
                batch,
                rollback_on_failure=rollback_on_failure,
                use_async=use_async,
            )

        async with anyio.create_task_group() as tg:
            for idx, batch in enumerate(batches):
                tg.start_soon(post_one, idx, batch)

        return ApplyEditsResult.merge(batch_results)  # type: ignore[arg-type]
