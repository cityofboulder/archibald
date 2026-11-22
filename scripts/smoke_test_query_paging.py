"""Query paging smoke-test script — checks window-aware paging on a real layer.

Read-only. Fetches every matching OBJECTID with ``returnIdsOnly`` and sorts it
ascending as ground truth, then runs two groups of checks.

Server assumptions (raw requests, bypassing archibald's paging):

1. ``resultRecordCount`` below the number of matches sets
   ``exceededTransferLimit`` (the original bug's trigger).
2. ``resultOffset`` alone, with rows remaining past one page, sets
   ``exceededTransferLimit`` — the paging gate relies on it.
3. ``resultOffset`` counts from the start of the full ordered result, so an
   ``orderByFields=OBJECTID ASC`` window equals the same slice of the sorted
   ground truth (and lines up with the ``returnCountOnly`` total).

Library behavior (``layer.query()`` end to end, OBJECTIDs compared exactly, so
any gap, overlap or overrun fails):

4. ``resultRecordCount=3`` returns the first 3 rows.
5. ``resultRecordCount=maxRecordCount + 5`` returns exactly that many rows.
6. ``resultOffset=--offset`` returns every row from that position to the end.
7. ``resultOffset`` + ``resultRecordCount`` spanning a page boundary returns
   exactly that window.
8. No window returns every matching row.

Checks 6 and 8 fetch close to every matching row; use ``--where`` to keep the
match set modest (it must still exceed maxRecordCount + --offset + 5).

Usage:
    uv run python scripts/smoke_test_query_paging.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username py_automation \\
        --password secret \\
        --portal-url https://gis.example.gov/portal

    # Restrict the match set and choose the offset:
    uv run python scripts/smoke_test_query_paging.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --where "OBJECTID < 5000" --offset 13
"""

import argparse
import sys

import anyio

from archibald.auth import NoAuth, UserTokenAuth
from archibald.client import ArchieClient
from archibald.services import FeatureLayer

_SEP = "-" * 60


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Query paging smoke test for resultOffset/resultRecordCount windows."
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
    parser.add_argument(
        "--username",
        default=None,
        help="ArcGIS portal username. Omit for public/unauthenticated services.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="ArcGIS portal password. Omit for public/unauthenticated services.",
    )
    parser.add_argument(
        "--layer-id",
        type=int,
        default=0,
        help="Layer index within the FeatureServer. Defaults to 0.",
    )
    parser.add_argument(
        "--where",
        default="1=1",
        help="WHERE clause defining the match set. Defaults to '1=1'.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=7,
        help="resultOffset used by the offset checks. Defaults to 7.",
    )
    return parser.parse_args()


def _section(title: str) -> None:
    """Print a section header."""
    print()
    print(_SEP)
    print(f"  {title}")
    print(_SEP)


def _report(passed: bool) -> bool:
    """Print the PASS/FAIL line for a check and return ``passed``."""
    print(f"  => {'PASS' if passed else 'FAIL'}")
    return passed


def _compare(actual: list[int], expected: list[int]) -> bool:
    """Print a summary of two OBJECTID lists and whether they match exactly."""
    print(f"  expected {len(expected)} rows, got {len(actual)}")
    if actual != expected:
        mismatch = next(
            (i for i, (a, e) in enumerate(zip(actual, expected)) if a != e),
            min(len(actual), len(expected)),
        )
        print(f"  first difference at position {mismatch}")
    return _report(actual == expected)


def _exceeded(data: dict) -> bool:
    """Read exceededTransferLimit from a json or geojson query response."""
    return bool(
        data.get("exceededTransferLimit")
        or data.get("properties", {}).get("exceededTransferLimit")
    )


async def _raw_query(layer: FeatureLayer, params: dict) -> dict:
    """Send one /query request directly, without archibald's paging."""
    response = await layer._client.post(
        endpoint=f"{layer._layer_path}/query", data={**params, "f": "json"}
    )
    return response.json()


async def _library_oids(
    layer: FeatureLayer, where: str, oid_field: str, **kwargs
) -> list[int]:
    """Run layer.query() and return the OBJECTIDs it produced, in order."""
    result = await layer.query(
        where=where, out_fields=[oid_field], return_geometry=False, **kwargs
    )
    return [f["attributes"][oid_field] for f in result.features]


async def main(args: argparse.Namespace) -> None:
    """Run the server-assumption and library checks and report the outcome."""
    if args.username and args.password:
        auth = UserTokenAuth(
            username=args.username, password=args.password, base_url=args.portal_url
        )
    else:
        auth = NoAuth()

    results: list[bool] = []

    async with ArchieClient(base_url=args.base_url, auth=auth) as client:
        layer = FeatureLayer(
            client=client, service_path=args.service_path, layer_id=args.layer_id
        )

        # --- Layer ---
        _section("LAYER")
        metadata = await layer._get_layer_metadata()
        adv = metadata.get("advancedQueryCapabilities", {})
        oid_field = await layer.objectid_field()
        max_records = await layer.max_record_count()
        print(f"  supportsPagination : {adv.get('supportsPagination')}")
        print(f"  objectid field     : {oid_field}")
        print(f"  maxRecordCount     : {max_records}")
        if not adv.get("supportsPagination"):
            raise SystemExit("ABORT: Layer does not support pagination.")

        ids_data = await _raw_query(
            layer, {"where": args.where, "returnIdsOnly": "true"}
        )
        truth = sorted(ids_data.get("objectIds") or [])
        count_data = await _raw_query(
            layer, {"where": args.where, "returnCountOnly": "true"}
        )
        total = count_data.get("count", 0)
        print(f"  matching rows      : {total} (returnIdsOnly gave {len(truth)})")
        if len(truth) != total:
            raise SystemExit("ABORT: returnIdsOnly and returnCountOnly disagree.")
        needed = max_records + args.offset + 5
        if total <= needed:
            raise SystemExit(
                f"ABORT: Need more than {needed} matching rows; got {total}. "
                "Widen --where or lower --offset."
            )

        base = {"where": args.where, "outFields": oid_field, "returnGeometry": "false"}
        ordered = {**base, "orderByFields": f"{oid_field} ASC"}

        # --- Server assumptions ---
        _section("1. resultRecordCount=1 sets exceededTransferLimit")
        data = await _raw_query(layer, {**ordered, "resultRecordCount": 1})
        print(f"  rows={len(data.get('features', []))}  exceeded={_exceeded(data)}")
        results.append(_report(_exceeded(data)))

        _section(f"2. resultOffset={args.offset} alone sets exceededTransferLimit")
        data = await _raw_query(layer, {**ordered, "resultOffset": args.offset})
        print(f"  rows={len(data.get('features', []))}  exceeded={_exceeded(data)}")
        results.append(_report(_exceeded(data)))

        window = (max_records - 2, 5)
        _section(
            f"3. resultOffset={window[0]}, resultRecordCount={window[1]} "
            "matches the sorted ground truth"
        )
        data = await _raw_query(
            layer,
            {**ordered, "resultOffset": window[0], "resultRecordCount": window[1]},
        )
        actual = [f["attributes"][oid_field] for f in data.get("features", [])]
        results.append(_compare(actual, truth[window[0] : window[0] + window[1]]))

        # --- Library behavior ---
        _section("4. query(resultRecordCount=3)")
        actual = await _library_oids(layer, args.where, oid_field, resultRecordCount=3)
        results.append(_compare(actual, truth[:3]))

        count = max_records + 5
        _section(f"5. query(resultRecordCount={count})")
        actual = await _library_oids(
            layer, args.where, oid_field, resultRecordCount=count
        )
        results.append(_compare(actual, truth[:count]))

        _section(f"6. query(resultOffset={args.offset})")
        actual = await _library_oids(
            layer, args.where, oid_field, resultOffset=args.offset
        )
        results.append(_compare(actual, truth[args.offset :]))

        span = max_records + 3
        _section(f"7. query(resultOffset={args.offset}, resultRecordCount={span})")
        actual = await _library_oids(
            layer,
            args.where,
            oid_field,
            resultOffset=args.offset,
            resultRecordCount=span,
        )
        results.append(_compare(actual, truth[args.offset : args.offset + span]))

        _section("8. query() with no window")
        actual = await _library_oids(layer, args.where, oid_field)
        results.append(_compare(actual, truth))

        # --- Summary ---
        _section("SUMMARY")
        passed = sum(results)
        print(f"  {passed}/{len(results)} checks passed")
        if all(results):
            print("  PASSED — server assumptions hold and paging fills each window.")
        else:
            print("  FAILED — one or more checks did not match (see above).")

    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    anyio.run(main, parse_args())
