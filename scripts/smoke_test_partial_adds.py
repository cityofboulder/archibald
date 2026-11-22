"""Partial-adds smoke test: maps applyEdits results back to input rows on a real layer.

Clones one existing feature into five add rows (index 100..104), writes a
unique marker into a text "tag" field of each, and puts an invalid value in
another field of rows 101 and 103 so the server rejects exactly those adds.

Two cases are run, each with its own markers:

1. ``rollback_on_failure=False``: rows 100, 102, 104 are committed and 101,
   103 fail. Checks that applyEdits returned one result per input row, that
   ``filter(...).to_frame()`` returns the failed and succeeded input rows by
   their original index, and that ``to_frame()["_edit_object_id"]`` matches
   the OBJECTIDs the layer actually holds for each committed marker.
2. Default (``rollback_on_failure=True``): the batch is rolled back. Checks
   that all five rows come back failed, in order, with readable error text,
   and that nothing was committed.

Every feature this run creates is deleted in a ``finally`` block by its
marker, and the script reports any features still carrying the marker
prefix afterwards.

Usage:
    uv run python scripts/smoke_test_partial_adds.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path ci/IntegratedPestManagement/FeatureServer \\
        --username py_automation --password secret \\
        --portal-url https://gis.example.gov/portal \\
        --tag-field COMMENTS --bad-field SITEGUID --bad-value not-a-guid
"""

import argparse
import sys
import uuid

import anyio
import geopandas as gpd
import pandas as pd

from archibald.auth import NoAuth, UserTokenAuth
from archibald.client import ArchieClient
from archibald.models import ApplyEditsResult
from archibald.services import FeatureLayer

_SEP = "-" * 60
_INDEX = [100, 101, 102, 103, 104]
_BAD_ROWS = [101, 103]
_GOOD_ROWS = [100, 102, 104]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Partial-adds smoke test for ApplyEditsResult.filter / to_frame."
    )
    parser.add_argument(
        "--portal-url",
        default="https://www.arcgis.com",
        help="Portal URL for token generation. Defaults to ArcGIS Online.",
    )
    parser.add_argument(
        "--base-url", required=True, help="Base URL of the ArcGIS REST services root."
    )
    parser.add_argument(
        "--service-path",
        required=True,
        help="Path to the FeatureServer, relative to --base-url.",
    )
    parser.add_argument("--username", default=None, help="ArcGIS portal username.")
    parser.add_argument("--password", default=None, help="ArcGIS portal password.")
    parser.add_argument(
        "--layer-id", type=int, default=0, help="Layer index. Defaults to 0."
    )
    parser.add_argument(
        "--where",
        default="1=1",
        help="WHERE clause used to pick the feature to clone. Defaults to '1=1'.",
    )
    parser.add_argument(
        "--tag-field",
        required=True,
        help="Editable string field that holds each row's marker.",
    )
    parser.add_argument(
        "--bad-field",
        required=True,
        help="Editable field that receives --bad-value on rows 101 and 103.",
    )
    parser.add_argument(
        "--bad-value",
        required=True,
        help="Value the server rejects for --bad-field (e.g. not-a-guid for a GUID).",
    )
    parser.add_argument(
        "--marker-prefix",
        default="archie-probe",
        help="Prefix for row markers. Defaults to 'archie-probe'.",
    )
    return parser.parse_args()


def _section(title: str) -> None:
    """Print a section header."""
    print()
    print(_SEP)
    print(f"  {title}")
    print(_SEP)


def _check(label: str, passed: bool, detail: str = "") -> bool:
    """Print one check's outcome and return it."""
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{'PASS' if passed else 'FAIL'}] {label}{suffix}")
    return passed


def _payload(
    seed: pd.DataFrame, tag_field: str, markers: list[str], bad_field: str, bad: str
) -> pd.DataFrame:
    """Five copies of the seed row with markers, and bad values on rows 101 and 103."""
    rows = pd.concat([seed] * len(_INDEX))
    rows.index = _INDEX
    rows[tag_field] = markers
    rows[bad_field] = rows[bad_field].astype(object)
    rows.loc[_BAD_ROWS, bad_field] = bad
    return rows


async def _committed(
    layer: FeatureLayer, objectid_field: str, tag_field: str, pattern: str
) -> dict[str, int]:
    """Return {marker: OBJECTID} for features whose tag matches ``pattern``."""
    result = await layer.query(
        where=f"{tag_field} LIKE '{pattern}'",
        out_fields=[objectid_field, tag_field],
        return_geometry=False,
    )
    if not result.features:
        return {}
    frame = result.to_frame()
    return dict(zip(frame[tag_field], frame[objectid_field].astype(int)))


def _print_result(result: ApplyEditsResult) -> None:
    """Print the full to_frame() output: input rows plus _edit_ metadata."""
    with pd.option_context(
        "display.max_columns",
        None,
        "display.width",
        None,
        "display.max_colwidth",
        60,
    ):
        print(result.to_frame())


async def _case_partial(
    layer: FeatureLayer,
    payload: pd.DataFrame,
    markers: list[str],
    objectid_field: str,
    tag_field: str,
    pattern: str,
) -> bool:
    """Rollback off: rows 101 and 103 fail, the rest commit and map to their OIDs."""
    result = await layer.apply_edits(adds=payload, rollback_on_failure=False)
    _print_result(result)

    failed = result.filter(kinds="adds", statuses="failed").to_frame(
        include_metadata=False
    )
    succeeded = result.filter(kinds="adds", statuses="succeeded").to_frame(
        include_metadata=False
    )
    frame = result.to_frame()
    committed = await _committed(layer, objectid_field, tag_field, pattern)
    good_markers = [markers[_INDEX.index(i)] for i in _GOOD_ROWS]
    ok_frame = frame.loc[_GOOD_ROWS]
    mapped = dict(zip(ok_frame[tag_field], ok_frame["_edit_object_id"].astype(int)))

    checks = [
        _check(
            "one result per input row",
            len(result.add_results) == len(payload),
            f"{len(result.add_results)} results for {len(payload)} rows",
        ),
        _check(
            "failed rows are 101 and 103",
            failed.index.tolist() == _BAD_ROWS,
            f"got {failed.index.tolist()}",
        ),
        _check(
            "succeeded rows are 100, 102, 104",
            succeeded.index.tolist() == _GOOD_ROWS,
            f"got {succeeded.index.tolist()}",
        ),
        _check(
            "failed rows carry their own markers",
            failed[tag_field].tolist() == [markers[1], markers[3]],
        ),
        _check(
            "layer holds exactly the succeeded markers",
            sorted(committed) == sorted(good_markers),
            f"committed {sorted(committed)}",
        ),
        _check(
            "_edit_object_id matches the committed OBJECTIDs",
            mapped == committed,
            f"to_frame {mapped} vs layer {committed}",
        ),
        _check(
            "failed rows have error text",
            frame.loc[_BAD_ROWS, "_edit_error_description"].notna().all(),
        ),
    ]
    return all(checks)


async def _case_rolled_back(
    layer: FeatureLayer,
    payload: pd.DataFrame,
    objectid_field: str,
    tag_field: str,
    pattern: str,
) -> bool:
    """Default rollback: every row comes back failed and nothing is committed."""
    result = await layer.apply_edits(adds=payload)
    _print_result(result)

    frame = result.to_frame()
    committed = await _committed(layer, objectid_field, tag_field, pattern)
    checks = [
        _check(
            "one result per input row",
            len(result.add_results) == len(payload),
            f"{len(result.add_results)} results for {len(payload)} rows",
        ),
        _check(
            "all rows failed, in input order",
            frame.index.tolist() == _INDEX
            and (frame["_edit_status"] == "failed").all(),
            f"statuses {frame['_edit_status'].tolist()}",
        ),
        _check(
            "every row has error text",
            frame["_edit_error_description"].notna().all(),
            str(frame["_edit_error_description"].iloc[0]),
        ),
        _check("nothing committed", not committed, f"committed {sorted(committed)}"),
    ]
    return all(checks)


async def main(args: argparse.Namespace) -> None:
    """Run both cases, always clean up, and report the outcome."""
    if "FeatureServer" not in args.service_path:
        raise SystemExit("ERROR: --service-path must contain 'FeatureServer'.")

    if args.username and args.password:
        auth = UserTokenAuth(
            username=args.username, password=args.password, base_url=args.portal_url
        )
    else:
        auth = NoAuth()

    run_prefix = f"{args.marker_prefix}-{uuid.uuid4().hex[:8]}"
    passed = True

    async with ArchieClient(base_url=args.base_url, auth=auth) as client:
        layer = FeatureLayer(
            client=client, service_path=args.service_path, layer_id=args.layer_id
        )

        _section("CAPABILITIES")
        supports_edits = await layer.supports_apply_edits()
        supports_rollback = await layer.supports_rollback_on_failure()
        print(f"  supports_apply_edits         : {supports_edits}")
        print(f"  supports_rollback_on_failure : {supports_rollback}")
        if not supports_edits:
            raise SystemExit("ABORT: Layer does not support applyEdits.")

        objectid_field = await layer.objectid_field()
        fields = await layer.fields()
        editable = fields.filter(editable=True)
        for name in (args.tag_field, args.bad_field):
            if name not in editable.names:
                raise SystemExit(f"ABORT: {name!r} is not editable: {editable.names}")
        tag_def = next(f for f in editable.fields if f["name"] == args.tag_field)
        longest = len(f"{run_prefix}-c1-4")
        if tag_def.get("length") and tag_def["length"] < longest:
            raise SystemExit(
                f"ABORT: {args.tag_field} holds {tag_def['length']} characters; "
                f"markers need {longest}."
            )

        _section("SEED")
        seed_ids = await layer.query(
            where=args.where, out_fields=[objectid_field], return_geometry=False
        )
        if not seed_ids.features:
            raise SystemExit("ABORT: Seed query returned no features.")
        seed_oid = int(seed_ids.to_frame()[objectid_field].iloc[0])
        seed_result = await layer.query(
            where=f"{objectid_field} = {seed_oid}",
            out_fields=[n for n in editable.names if n != objectid_field],
            return_geometry=True,
        )
        has_geometry = "geometry" in seed_result.features[0]
        seed: pd.DataFrame | gpd.GeoDataFrame = (
            seed_result.to_geodataframe(parse_dtypes=True)
            if has_geometry
            else seed_result.to_frame(parse_dtypes=True)
        ).iloc[:1]
        print(f"  seed OID   : {seed_oid}")
        print(f"  run prefix : {run_prefix}")
        print(f"  geometry   : {has_geometry}")
        print(f"  tag field  : {args.tag_field}")
        print(f"  bad field  : {args.bad_field} = {args.bad_value!r} on {_BAD_ROWS}")

        try:
            _section("CASE 1: rollback_on_failure=False")
            if supports_rollback:
                markers = [f"{run_prefix}-c1-{i}" for i in range(len(_INDEX))]
                payload = _payload(
                    seed, args.tag_field, markers, args.bad_field, args.bad_value
                )
                case1 = await _case_partial(
                    layer,
                    payload,
                    markers,
                    objectid_field,
                    args.tag_field,
                    f"{run_prefix}-c1-%",
                )
                print(f"  => {'PASS' if case1 else 'FAIL'}")
                passed &= case1
            else:
                print("  SKIPPED: layer always rolls back.")

            _section("CASE 2: default rollback_on_failure (True)")
            markers = [f"{run_prefix}-c2-{i}" for i in range(len(_INDEX))]
            payload = _payload(
                seed, args.tag_field, markers, args.bad_field, args.bad_value
            )
            case2 = await _case_rolled_back(
                layer, payload, objectid_field, args.tag_field, f"{run_prefix}-c2-%"
            )
            print(f"  => {'PASS' if case2 else 'FAIL'}")
            passed &= case2
        finally:
            _section("CLEANUP")
            created = await _committed(
                layer, objectid_field, args.tag_field, f"{run_prefix}-%"
            )
            if created:
                cleanup = await layer.apply_edits(deletes=list(created.values()))
                print(
                    f"  deleted {len(created)} feature(s); "
                    f"failures: {len(cleanup.failed_deletes)}"
                )
            else:
                print("  nothing to delete")
            leftover = await _committed(
                layer, objectid_field, args.tag_field, f"{args.marker_prefix}-%"
            )
            passed &= _check(
                f"no {args.marker_prefix}-% features remain",
                not leftover,
                f"remaining {sorted(leftover)}",
            )

        _section("SUMMARY")
        print("  PASSED" if passed else "  FAILED (see above)")

    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    anyio.run(main, parse_args())
