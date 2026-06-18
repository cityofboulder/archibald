"""Attachment smoke-test script — uploads a file attachment to a real FeatureLayer.

If --file is not provided, a small synthetic text stub is generated in memory
so the script requires no external data files.

Usage:
    uv run python scripts/smoke_test_attachments.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username user \\
        --password secret \\
        --portal-url https://gis.example.gov/portal

    # Attach a real file to a specific feature:
    uv run python scripts/smoke_test_attachments.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username user --password secret \\
        --object-id 42 --file /path/to/photo.jpg

    # Public / unauthenticated service (omit credentials):
    uv run python scripts/smoke_test_attachments.py \\
        --base-url https://services.arcgis.com/abc/arcgis/rest/services/ \\
        --service-path PublicEditable/FeatureServer
"""

import argparse
import sys
from pathlib import Path

import anyio

from archibald.auth import NoAuth, UserTokenAuth
from archibald.client import ArchieClient
from archibald.services import FeatureLayer

_SEP = "-" * 60
_SYNTHETIC_BYTES = b"archie smoke test attachment"
_SYNTHETIC_FILENAME = "archie_smoke_test.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Attachment smoke test — uploads a file attachment to a FeatureLayer."
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
        help="WHERE clause used to auto-detect a seed OBJECTID. Defaults to '1=1'.",
    )
    parser.add_argument(
        "--object-id",
        type=int,
        default=None,
        help="Feature OBJECTID to attach to. Auto-detected from --where if omitted.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to the file to attach. Uses a synthetic text stub if omitted.",
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
        supports = await layer.supports_attachments()
        print(f"  supports_attachments : {supports}")
        if not supports:
            raise SystemExit("ABORT: Layer does not support attachments.")

        # --- Resolve OBJECTID ---
        object_id = args.object_id
        if object_id is None:
            _section("SEED QUERY")
            print(f"  where={args.where!r}, resultRecordCount=1")
            objectid_field = await layer.objectid_field()
            seed = await layer.query(
                where=args.where,
                out_fields=[objectid_field],
                return_geometry=False,
                resultRecordCount=1,
            )
            if not seed.features:
                raise SystemExit(
                    "ABORT: Seed query returned no features — pass --object-id explicitly."
                )
            object_id = seed.features[0]["attributes"][objectid_field]
            print(f"  using OBJECTID : {object_id}")

        # --- Resolve file ---
        if args.file is not None:
            file_arg: Path | bytes = args.file
            filename: str = args.file.name
            file_label = str(args.file)
        else:
            file_arg = _SYNTHETIC_BYTES
            filename = _SYNTHETIC_FILENAME
            file_label = f"<synthetic> {_SYNTHETIC_FILENAME}"

        # --- Upload ---
        _section("ADD ATTACHMENT")
        print(f"  object_id : {object_id}")
        print(f"  file      : {file_label}")
        result = await layer.add_attachment(object_id, file_arg, filename=filename)

        df = result.to_frame()
        print()
        print(df.to_string(index=False))

        if result.has_failures:
            overall_passed = False

        # --- Summary ---
        _section("SUMMARY")
        if overall_passed:
            print("  PASSED — attachment uploaded successfully.")
        else:
            print("  FAILED — attachment upload had errors (see above).")

    if not overall_passed:
        sys.exit(1)


if __name__ == "__main__":
    anyio.run(main, parse_args())
