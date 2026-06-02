"""Quick smoke-test script — queries a real FeatureLayer or MapLayer end-to-end.

Usage:
    uv run python scripts/query_feature_layer.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username py_automation \\
        --password secret \\
        --portal-url https://gis.example.gov/portal

    # MapServer (read-only):
    uv run python scripts/query_feature_layer.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/MapServer \\
        --username py_automation --password secret

    # Public / unauthenticated service (omit credentials):
    uv run python scripts/query_feature_layer.py \\
        --base-url https://services.arcgis.com/abc/arcgis/rest/services/ \\
        --service-path PublicData/FeatureServer
"""

import argparse

import anyio

from archie.auth import NoAuth, UserTokenAuth
from archie.client import ArchieClient
from archie.services import FeatureLayer, MapLayer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query a FeatureLayer or MapLayer and print results."
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
        help="Path to the service (FeatureServer or MapServer), relative to --base-url.",
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
        help="Layer index within the service. Defaults to 0.",
    )
    parser.add_argument(
        "--where", default="1=1", help="WHERE clause for the query. Defaults to '1=1'."
    )
    parser.add_argument(
        "--return-geometry", action="store_true", help="Include geometry in the result."
    )
    parser.add_argument(
        "--apply-coded-values",
        action="store_true",
        help="Apply coded value domains to the result attributes.",
    )

    return parser.parse_args()


async def main(args: argparse.Namespace) -> None:
    if args.username and args.password:
        auth = UserTokenAuth(
            username=args.username, password=args.password, base_url=args.portal_url
        )
    else:
        auth = NoAuth()

    async with ArchieClient(base_url=args.base_url, auth=auth) as client:
        if "FeatureServer" in args.service_path:
            layer_type = "FeatureLayer"
            layer = FeatureLayer(
                client=client, service_path=args.service_path, layer_id=args.layer_id
            )
        elif "MapServer" in args.service_path:
            layer_type = "MapLayer"
            layer = MapLayer(
                client=client, service_path=args.service_path, layer_id=args.layer_id
            )
        else:
            raise SystemExit(
                "ERROR: --service-path must contain 'FeatureServer' or 'MapServer'."
            )

        print(f"layer type    : {layer_type}")

        fields = await layer.fields()
        print(f"fields        : {[f['name'] for f in fields.fields]}")
        print()

        result = await layer.query(
            where=args.where,
            return_geometry=args.return_geometry,
            apply_coded_values=args.apply_coded_values,
        )
        print(f"features returned : {len(result.features)}")
        print(f"crs               : {result.crs}")
        print()

        if args.return_geometry:
            gdf = result.to_geodataframe(parse_dtypes=True)
            print(gdf.head())
            print()
        else:
            df = result.to_frame(parse_dtypes=True)
            print(df.head())
            print()


if __name__ == "__main__":
    anyio.run(main, parse_args())
