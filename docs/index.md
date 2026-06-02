# archie

An async-first Python client for interacting with ESRI ArcGIS REST APIs, designed around a dataframe-first approach for seamless analysis with `pandas` and `geopandas`.

[![PyPI](https://img.shields.io/pypi/v/archie.svg)](https://pypi.org/project/archie/)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## Installation

```bash
pip install archie
```

Or with `uv`:

```bash
uv add archie
```

## Quick Start

```python
import archie as arc

auth = arc.UserTokenAuth(
    username="your_username",
    password="your_password",
)

async with arc.ArchieClient(
    base_url="https://services.arcgis.com/sharing/rest/services",
    auth=auth,
) as client:
    layer = arc.FeatureLayer(
        client=client,
        service_path="MyService/FeatureServer",
        layer_id=0,
    )

    result = await layer.query(where="1=1")
    df = result.to_frame()
    gdf = result.to_geodataframe()
```

See the [Usage Guide](usage.md) for a full walkthrough, or jump straight to the [API Reference](api/client.md).
