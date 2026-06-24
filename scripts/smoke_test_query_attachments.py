"""Query-attachments smoke-test script — queries attachments on a real layer.

Runs a full queryAttachments (one row per attachment) and, when the layer
supports it, a count-only queryAttachments (one row per parent feature). Works
against a FeatureServer layer.

Usage:
    uv run python scripts/smoke_test_query_attachments.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username user \\
        --password secret \\
        --portal-url https://gis.example.gov/portal

    # Filter to a subset of parent features and a single layer:
    uv run python scripts/smoke_test_query_attachments.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username user --password secret \\
        --layer-id 0 --where "STATUS = 'active'"

    # Public / unauthenticated service (omit credentials):
    uv run python scripts/smoke_test_query_attachments.py \\
        --base-url https://services.arcgis.com/abc/arcgis/rest/services/ \\
        --service-path PublicAttachments/FeatureServer
"""

import argparse
import sys

import anyio

from archibald.auth import NoAuth, UserTokenAuth
from archibald.client import ArchieClient
from archibald.services import FeatureLayer

_SEP = "-" * 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query-attachments smoke test against a FeatureLayer."
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
        help="definitionExpression filtering parent features. Defaults to '1=1'.",
    )
    parser.add_argument(
        "--result-record-count",
        type=int,
        default=10,
        help="Cap on attachments returned by the full query. Defaults to 10.",
    )
    return parser.parse_args()


def _section(title: str) -> None:
    print()
    print(_SEP)
    print(f"  {title}")
    print(_SEP)


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
        supports = await layer.supports_query_attachments()
        supports_count = await layer.supports_query_attachments_count_only()
        print(f"  supports_query_attachments            : {supports}")
        print(f"  supports_query_attachments_count_only : {supports_count}")
        if not supports:
            raise SystemExit("ABORT: Layer does not support querying attachments.")

        attachment_fields = await layer.attachment_fields()
        attachment_properties = await layer.attachment_properties()
        print(f"  attachment_fields                     : {attachment_fields.names}")
        enabled = [p["name"] for p in attachment_properties if p.get("isEnabled", True)]
        print(f"  attachment_properties (enabled)       : {enabled}")

        # --- Full query ---
        _section("QUERY ATTACHMENTS (full)")
        print(f"  where={args.where!r}, resultRecordCount={args.result_record_count}")
        result = await layer.query_attachments(
            definition_expression=args.where,
            result_record_count=args.result_record_count,
            return_url=True,
        )
        df = result.to_frame()
        print(f"  attachment groups : {len(result.attachment_groups)}")
        print(f"  attachments       : {len(df)}")
        print()
        if df.empty:
            print("  (no attachments returned)")
        else:
            print("  --- camelCase property names (default) ---")
            print(df.to_string(index=False))
            print()
            print("  --- ESRI field names (use_field_names=True) ---")
            print(result.to_frame(use_field_names=True).to_string(index=False))

        # --- Count-only query ---
        _section("QUERY ATTACHMENTS (count only)")
        if not supports_count:
            print("  SKIPPED — layer does not support returnCountOnly.")
        else:
            count_result = await layer.query_attachments(
                definition_expression=args.where, return_count_only=True
            )
            count_df = count_result.to_frame()
            print(f"  parent features : {len(count_df)}")
            print()
            if count_df.empty:
                print("  (no parent features returned)")
            else:
                print(count_df.to_string(index=False))

        # --- Summary ---
        _section("SUMMARY")
        if overall_passed:
            print("  PASSED — queryAttachments returned without errors.")
        else:
            print("  FAILED — one or more steps had errors (see above).")

    if not overall_passed:
        sys.exit(1)


if __name__ == "__main__":
    anyio.run(main, parse_args())
