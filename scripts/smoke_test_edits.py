"""Edit smoke-test script — exercises add → update → delete on a real FeatureLayer.

Queries a small number of existing features, clones them as new records (add),
re-fetches and re-submits them (update), then removes them (delete). No external
data files are required.

Usage:
    uv run python scripts/smoke_test_edits.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username py_automation \\
        --password secret \\
        --portal-url https://gis.example.gov/portal

    # Public / unauthenticated editable service (omit credentials):
    uv run python scripts/smoke_test_edits.py \\
        --base-url https://services.arcgis.com/abc/arcgis/rest/services/ \\
        --service-path PublicEditable/FeatureServer
"""

import argparse
import sys

import anyio

from archibald.auth import NoAuth, UserTokenAuth
from archibald.client import ArchieClient
from archibald.models import ApplyEditsResult
from archibald.services import FeatureLayer

_SEP = "-" * 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Round-trip edit smoke test (add → update → delete) on a FeatureLayer."
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
        help="WHERE clause used to seed the test data. Defaults to '1=1'.",
    )
    parser.add_argument(
        "--rollback-on-failure",
        action="store_true",
        help="Request server-side rollback on failure.",
    )
    parser.add_argument(
        "--apply-coded-values",
        action="store_true",
        help=(
            "Translate coded-value domains in both directions: "
            "code → label on query results, label → code when submitting edits."
        ),
    )
    return parser.parse_args()


def _section(title: str) -> None:
    print()
    print(_SEP)
    print(f"  {title}")
    print(_SEP)


def _print_edit_result(
    result: ApplyEditsResult, items_attr: str, label: str
) -> list[int]:
    """Print per-feature results and return OBJECTIDs of successful operations."""
    items = getattr(result, items_attr)
    succeeded = []
    for item in items:
        status = "OK  " if item.success else "FAIL"
        extra = f"  error={item.error}" if not item.success else ""
        print(f"  [{status}] OBJECTID={item.object_id}{extra}")
        if item.success:
            succeeded.append(item.object_id)
    print(f"  => {len(succeeded)}/{len(items)} {label} succeeded")
    return succeeded


async def main(args: argparse.Namespace) -> None:
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
        supports_async = await layer.supports_async_apply_edits()
        print(f"  supports_apply_edits         : {supports_edits}")
        print(f"  supports_rollback_on_failure : {supports_rollback}")
        print(f"  supports_async_apply_edits   : {supports_async}")

        if not supports_edits:
            raise SystemExit("ABORT: Layer does not support applyEdits.")

        objectid_field = await layer.objectid_field()

        # --- Seed query ---
        _section("SEED QUERY")
        print(
            f"  where={args.where!r}, resultRecordCount=3, apply_coded_values={args.apply_coded_values}"
        )
        seed_result = await layer.query(
            where=args.where,
            return_geometry=True,
            apply_coded_values=args.apply_coded_values,
            resultRecordCount=3,
        )
        print(f"  features returned : {len(seed_result.features)}")

        if not seed_result.features:
            raise SystemExit(
                "ABORT: Seed query returned no features — nothing to clone as test data."
            )

        try:
            seed_df = seed_result.to_geodataframe(parse_dtypes=True)
        except Exception:
            seed_df = seed_result.to_frame(parse_dtypes=True)

        # Drop OBJECTID so these are treated as new features by the server.
        test_df = seed_df.drop(columns=[objectid_field], errors="ignore")
        print(f"  test rows         : {len(test_df)}")

        # --- Add ---
        _section("ADD")
        add_result = await layer.apply_edits(
            adds=test_df,
            rollback_on_failure=args.rollback_on_failure,
            apply_coded_values=args.apply_coded_values,
        )
        new_oids = _print_edit_result(add_result, "add_results", "adds")
        if add_result.has_failures:
            overall_passed = False

        if not new_oids:
            raise SystemExit(
                "ABORT: All adds failed — cannot continue with update/delete."
            )

        # --- Update ---
        _section("UPDATE")
        oids_clause = ", ".join(str(oid) for oid in new_oids)
        print(f"  re-querying: {objectid_field} IN ({oids_clause})")
        update_source = await layer.query(
            where=f"{objectid_field} IN ({oids_clause})",
            return_geometry=True,
            apply_coded_values=args.apply_coded_values,
        )
        try:
            update_df = update_source.to_geodataframe(parse_dtypes=True)
        except Exception:
            update_df = update_source.to_frame(parse_dtypes=True)

        update_result = await layer.apply_edits(
            updates=update_df,
            rollback_on_failure=args.rollback_on_failure,
            apply_coded_values=args.apply_coded_values,
        )
        _print_edit_result(update_result, "update_results", "updates")
        if update_result.has_failures:
            overall_passed = False

        # --- Delete ---
        _section("DELETE")
        print(f"  deleting OBJECTIDs: {new_oids}")
        delete_result = await layer.apply_edits(
            deletes=new_oids,
            rollback_on_failure=args.rollback_on_failure,
        )
        _print_edit_result(delete_result, "delete_results", "deletes")
        if delete_result.has_failures:
            overall_passed = False

        # --- Summary ---
        _section("SUMMARY")
        if overall_passed:
            print("  PASSED — all add / update / delete operations succeeded.")
        else:
            print("  FAILED — one or more operations had errors (see above).")

    if not overall_passed:
        sys.exit(1)


if __name__ == "__main__":
    anyio.run(main, parse_args())
