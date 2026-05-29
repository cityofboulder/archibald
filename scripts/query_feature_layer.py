"""Quick smoke-test script — queries a real FeatureLayer end-to-end.

Usage:
    uv run python scripts/try_query.py \\
        --base-url https://gis.example.gov/ags/rest/services/ \\
        --service-path IT/SAMPS/FeatureServer \\
        --username py_automation \\
        --password secret \\
        --portal-url https://gis.example.gov/portal
"""

import argparse

import anyio

from archie.auth.user_token import UserTokenAuth
from archie.client import ArchieClient
from archie.services.feature_layer import FeatureLayer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query a FeatureLayer and print results."
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
    parser.add_argument("--username", required=True, help="ArcGIS portal username.")
    parser.add_argument("--password", required=True, help="ArcGIS portal password.")
    parser.add_argument(
        "--layer-id",
        type=int,
        default=0,
        help="Layer index within the FeatureServer. Defaults to 0.",
    )
    parser.add_argument(
        "--where", default="1=1", help="WHERE clause for the query. Defaults to '1=1'."
    )
    parser.add_argument(
        "--return-geometry", action="store_true", help="Include geometry in the result."
    )

    return parser.parse_args()


async def main(args: argparse.Namespace) -> None:
    auth = UserTokenAuth(
        username=args.username, password=args.password, base_url=args.portal_url
    )

    async with ArchieClient(base_url=args.base_url, auth=auth) as client:
        layer = FeatureLayer(
            client=client, service_path=args.service_path, layer_id=args.layer_id
        )

        fields = await layer.fields()
        print(f"fields        : {[f['name'] for f in fields.fields]}")
        print()

        result = await layer.query(
            where=args.where, return_geometry=args.return_geometry
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
