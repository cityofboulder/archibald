"""Rollback smoke-test script — checks rollbackOnFailure behavior on a real FeatureLayer.

Builds a two-row update: one existing feature re-sent with its current value
for a single field (a no-op apart from editor-tracking fields), and one copy of
it pointed at an OBJECTID that does not exist. The missing OBJECTID passes the
serializers untouched and is rejected by the server, so the request contains
exactly one failing edit. No features are added or deleted.

Two cases are run against the same payload:

1. ``rollback_on_failure=False``: on a layer that supports the parameter, the
   good update is applied and the missing OBJECTID comes back as a per-item
   ``success=False`` result. On a layer that does not, FeatureLayer warns and
   the server rolls the batch back.
2. Default (``rollback_on_failure=True``): the server rejects the whole batch
   with an error envelope ("Unable to complete operation." / "Operation rolled
   back."), surfaced as a ServiceError.

Usage:
    uv run python scripts/smoke_test_rollback.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username py_automation \\
        --password secret \\
        --portal-url https://gis.example.gov/portal

    # Pick the field to re-send and the seed feature explicitly:
    uv run python scripts/smoke_test_rollback.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username py_automation --password secret \\
        --field NOTES --where "OBJECTID = 42"
"""

import argparse
import sys
import warnings

import anyio
import pandas as pd

from archibald.auth import NoAuth, UserTokenAuth
from archibald.client import ArchieClient
from archibald.exceptions import ArcGISError
from archibald.models import ApplyEditsResult
from archibald.services import FeatureLayer

_SEP = "-" * 60


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="rollbackOnFailure smoke test using one valid and one missing-OBJECTID update."
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
        help="WHERE clause used to pick the seed feature. Defaults to '1=1'.",
    )
    parser.add_argument(
        "--field",
        default=None,
        help=(
            "Editable field whose current value is re-sent. Defaults to the first "
            "editable string field, else the first editable field."
        ),
    )
    parser.add_argument(
        "--missing-oid",
        type=int,
        default=999_999_999,
        help="OBJECTID that must not exist on the layer. Defaults to 999999999.",
    )
    return parser.parse_args()


def _section(title: str) -> None:
    """Print a section header."""
    print()
    print(_SEP)
    print(f"  {title}")
    print(_SEP)


def _pick_field(editable: list[dict], requested: str | None) -> str:
    """Return the field to re-send, validating an explicit choice."""
    names = [f["name"] for f in editable]
    if requested is not None:
        if requested not in names:
            raise SystemExit(f"ABORT: --field {requested!r} is not editable: {names}")
        return requested
    if not editable:
        raise SystemExit("ABORT: Layer has no editable fields.")
    strings = [f["name"] for f in editable if f.get("type") == "esriFieldTypeString"]
    return (strings or names)[0]


def _print_updates(result: ApplyEditsResult) -> None:
    """Print per-feature update results."""
    for item in result.update_results:
        status = "OK  " if item.success else "FAIL"
        extra = f"  error={item.error}" if not item.success else ""
        print(f"  [{status}] OBJECTID={item.object_id}{extra}")


async def _run_case(
    layer: FeatureLayer, updates: pd.DataFrame, **kwargs
) -> tuple[ApplyEditsResult | None, ArcGISError | None, list[str]]:
    """Run apply_edits, capturing the result or ESRI error and any warnings.

    Batch errors surface wrapped in an ExceptionGroup from the operation's
    task group, so ESRI errors are unwrapped with except*. Anything else
    propagates.
    """
    result, error = None, None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result = await layer.apply_edits(updates=updates, **kwargs)
        except* ArcGISError as group:
            leaf = group.exceptions[0]
            while isinstance(leaf, ExceptionGroup):
                leaf = leaf.exceptions[0]
            error = leaf
    messages = [str(w.message) for w in caught]
    for msg in messages:
        print(f"  warning: {msg}")
    if error is not None:
        print(f"  raised {type(error).__name__}: {error}")
        print(f"    details: {error.details}")
    if result is not None:
        _print_updates(result)
    return result, error, messages


def _check_partial(result: ApplyEditsResult | None, real_oid: int) -> bool:
    """True when the real update succeeded and the other one failed."""
    if result is None or len(result.update_results) != 2:
        return False
    succeeded = [item for item in result.update_results if item.success]
    return len(succeeded) == 1 and succeeded[0].object_id == real_oid


async def main(args: argparse.Namespace) -> None:
    """Run both rollback cases and report whether each matched expectations."""
    if "FeatureServer" not in args.service_path:
        raise SystemExit("ERROR: --service-path must contain 'FeatureServer'.")

    if args.username and args.password:
        auth = UserTokenAuth(
            username=args.username, password=args.password, base_url=args.portal_url
        )
    else:
        auth = NoAuth()

    overall_passed = True

    async with ArchieClient(base_url=args.base_url, auth=auth) as client:
        layer = FeatureLayer(
            client=client, service_path=args.service_path, layer_id=args.layer_id
        )

        # --- Capabilities ---
        _section("CAPABILITIES")
        supports_edits = await layer.supports_apply_edits()
        supports_rollback = await layer.supports_rollback_on_failure()
        print(f"  supports_apply_edits         : {supports_edits}")
        print(f"  supports_rollback_on_failure : {supports_rollback}")
        if not supports_edits:
            raise SystemExit("ABORT: Layer does not support applyEdits.")

        objectid_field = await layer.objectid_field()
        fields = await layer.fields()
        editable = [
            f
            for f in fields.filter(editable=True).fields
            if f["name"] != objectid_field
        ]
        field = _pick_field(editable, args.field)

        # --- Seed ---
        _section("SEED")
        missing = await layer.query(
            where=f"{objectid_field} = {args.missing_oid}",
            out_fields=[objectid_field],
            return_geometry=False,
        )
        if missing.features:
            raise SystemExit(
                f"ABORT: OBJECTID {args.missing_oid} exists — pass a different --missing-oid."
            )

        seed = await layer.query(
            where=args.where,
            out_fields=[objectid_field, field],
            return_geometry=False,
            resultRecordCount=1,
        )
        if not seed.features:
            raise SystemExit("ABORT: Seed query returned no features.")

        real = seed.to_frame(parse_dtypes=True)
        real_oid = int(real[objectid_field].iloc[0])
        bad = real.assign(**{objectid_field: args.missing_oid})
        updates = pd.concat([real, bad], ignore_index=True)
        print(f"  field re-sent : {field}")
        print(f"  real OBJECTID : {real_oid} (current value re-sent)")
        print(f"  missing OID   : {args.missing_oid}")

        # --- Case 1: rollback disabled ---
        _section("CASE 1: rollback_on_failure=False")
        result, error, messages = await _run_case(
            layer, updates, rollback_on_failure=False
        )
        if supports_rollback:
            print("  expected: 1 OK (real), 1 FAIL (missing), no exception, no warning")
            case1 = error is None and not messages and _check_partial(result, real_oid)
        else:
            print("  expected: rollback warning, then ServiceError (batch rolled back)")
            case1 = error is not None and any(
                "rollbackOnFailure=False" in m for m in messages
            )
        print(f"  => {'PASS' if case1 else 'FAIL'}")
        overall_passed &= case1

        # --- Case 2: default (rollback) ---
        _section("CASE 2: default rollback_on_failure (True)")
        result, error, messages = await _run_case(layer, updates)
        print("  expected: ServiceError (batch rolled back), no warning")
        case2 = error is not None and result is None and not messages
        print(f"  => {'PASS' if case2 else 'FAIL'}")
        overall_passed &= case2

        # --- Summary ---
        _section("SUMMARY")
        if overall_passed:
            print("  PASSED — rollbackOnFailure behaved as ESRI documents.")
        else:
            print(
                "  FAILED — one or more cases did not match expectations (see above)."
            )

    if not overall_passed:
        sys.exit(1)


if __name__ == "__main__":
    anyio.run(main, parse_args())
