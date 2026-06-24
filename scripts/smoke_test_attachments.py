"""Attachment smoke-test script — adds, updates, then deletes a file attachment on a real FeatureLayer.

The script adds an attachment, replaces its contents via updateAttachment (when
the layer supports updating), and finally deletes it so the layer is left as it
was found. If --file / --update-file are not provided, small synthetic text
stubs are generated in memory so the script requires no external data files.

Usage:
    uv run python scripts/smoke_test_attachments.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username user \\
        --password secret \\
        --portal-url https://gis.example.gov/portal

    # Add a real file then replace it with another on a specific feature:
    uv run python scripts/smoke_test_attachments.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username user --password secret \\
        --object-id 42 --file /path/to/photo.jpg --update-file /path/to/new_photo.jpg

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
_SYNTHETIC_UPDATE_BYTES = b"archie smoke test attachment (updated contents)"
_SYNTHETIC_UPDATE_FILENAME = "archie_smoke_test_updated.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Attachment smoke test — adds, updates, and deletes a file attachment on a FeatureLayer."
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
    parser.add_argument(
        "--update-file",
        type=Path,
        default=None,
        help="Path to the replacement file used in the update step. Uses a synthetic "
        "text stub if omitted.",
    )
    return parser.parse_args()


def _section(title: str) -> None:
    print()
    print(_SEP)
    print(f"  {title}")
    print(_SEP)


def _resolve_file(
    path: Path | None, synthetic_bytes: bytes, synthetic_filename: str
) -> tuple[Path | bytes, str, str]:
    """Resolve a CLI file path to (file_arg, filename, label).

    Falls back to an in-memory synthetic stub when no path is provided.
    """
    if path is not None:
        return path, path.name, str(path)
    return synthetic_bytes, synthetic_filename, f"<synthetic> {synthetic_filename}"


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
        supports_update = await layer.supports_update()
        print(f"  supports_attachments : {supports}")
        print(f"  supports_update      : {supports_update}")
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

        # --- Resolve files ---
        file_arg, filename, file_label = _resolve_file(
            args.file, _SYNTHETIC_BYTES, _SYNTHETIC_FILENAME
        )
        update_file_arg, update_filename, update_label = _resolve_file(
            args.update_file, _SYNTHETIC_UPDATE_BYTES, _SYNTHETIC_UPDATE_FILENAME
        )

        # --- Add ---
        _section("ADD ATTACHMENT")
        print(f"  object_id : {object_id}")
        print(f"  file      : {file_label}")
        add_result = await layer.add_attachment(object_id, file_arg, filename=filename)

        print()
        print(add_result.to_frame().to_string(index=False))

        if add_result.has_failures:
            overall_passed = False

        attachment_id = (
            add_result.results[0].object_id
            if add_result.results and not add_result.has_failures
            else None
        )

        # --- Update ---
        _section("UPDATE ATTACHMENT")
        if attachment_id is None:
            print("  SKIPPED — add step failed; nothing to update.")
        elif not supports_update:
            print("  SKIPPED — layer does not support updating attachments.")
        else:
            print(f"  object_id     : {object_id}")
            print(f"  attachment_id : {attachment_id}")
            print(f"  new file      : {update_label}")
            update_result = await layer.update_attachment(
                object_id, attachment_id, update_file_arg, filename=update_filename
            )

            print()
            print(update_result.to_frame().to_string(index=False))

            if update_result.has_failures:
                overall_passed = False

        # --- Delete ---
        _section("DELETE ATTACHMENT")
        if attachment_id is None:
            print("  SKIPPED — add step failed; nothing to delete.")
        else:
            print(f"  object_id     : {object_id}")
            print(f"  attachment_id : {attachment_id}")
            delete_result = await layer.delete_attachment(object_id, attachment_id)

            print()
            print(delete_result.to_frame().to_string(index=False))

            if delete_result.has_failures:
                overall_passed = False

        # --- Summary ---
        _section("SUMMARY")
        if overall_passed:
            print("  PASSED — attachment added, updated, and deleted successfully.")
        else:
            print("  FAILED — one or more steps had errors (see above).")

    if not overall_passed:
        sys.exit(1)


if __name__ == "__main__":
    anyio.run(main, parse_args())
