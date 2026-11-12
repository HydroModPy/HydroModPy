"""The bounds of a call (timeout in s) reach the HTTP client every port class hands to its provider."""

from __future__ import annotations

from datetime import datetime

import geopandas as gpd
import pytest

from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.common.clients import sandre_topage
from hydromodpy.data.source.port import Extent, FetchRequest, Period
from hydromodpy.data.variables.crossings.apis import roe
from hydromodpy.data.variables.hydrography.apis.bdtopage import BdTopageSource
from hydromodpy.data.variables.intermittency.apis import hubeau as intermittency_hubeau
from hydromodpy.data.variables.piezometry.apis import hubeau as piezometry_hubeau
from hydromodpy.data.variables.water_quality.apis import hubeau as water_quality_hubeau

BOUNDS = Bounds(timeout_s=7.0)
LAMBERT = Extent(xmin=340000.0, ymin=6800000.0, xmax=350000.0, ymax=6810000.0, crs="EPSG:2154")
WGS84 = Extent(xmin=-2.0, ymin=48.0, xmax=-1.9, ymax=48.1, crs="EPSG:4326")
PERIOD = Period(start=datetime(2020, 1, 1), end=datetime(2020, 2, 1))


def empty_features(*args, **kwargs):
    return gpd.GeoDataFrame(geometry=[], crs=sandre_topage.QUERY_CRS)


def empty_pages(*args, **kwargs):
    return iter(())


def no_stations(*args, **kwargs):
    return []


HUBEAU_REQUEST = {"extent": WGS84, "period": PERIOD}

# (module, function the port calls, stub it gets, port class, port arguments, request arguments)
PORTS = [
    pytest.param(
        piezometry_hubeau,
        "fetch",
        no_stations,
        piezometry_hubeau.HubeauPiezometry,
        {},
        HUBEAU_REQUEST,
        id="piezometry",
    ),
    pytest.param(
        water_quality_hubeau,
        "fetch",
        no_stations,
        water_quality_hubeau.HubeauWaterQuality,
        {},
        HUBEAU_REQUEST,
        id="water quality",
    ),
    pytest.param(
        intermittency_hubeau,
        "fetch",
        no_stations,
        intermittency_hubeau.HubeauIntermittency,
        {},
        HUBEAU_REQUEST,
        id="intermittency",
    ),
    pytest.param(
        sandre_topage,
        "get_features",
        empty_features,
        BdTopageSource,
        {"page_size": 10},
        {"extent": LAMBERT},
        id="bdtopage",
    ),
    pytest.param(
        roe,
        "fetch_pages",
        empty_pages,
        roe.RoeCrossings,
        {"page_size": 10},
        {"extent": LAMBERT},
        id="roe",
    ),
]


@pytest.mark.parametrize(
    ("module", "attribute", "stub", "port_cls", "port_kwargs", "request_kwargs"), PORTS
)
def test_the_client_carries_the_bounds_of_the_request(
    module, attribute, stub, port_cls, port_kwargs, request_kwargs, monkeypatch, tmp_path
):
    seen = []

    def recorder(*args, **kwargs):
        seen.append(kwargs.get("client"))
        return stub(*args, **kwargs)

    monkeypatch.setattr(module, attribute, recorder)
    port_cls(**port_kwargs).fetch(FetchRequest(out_dir=tmp_path, bounds=BOUNDS, **request_kwargs))

    assert len(seen) == 1
    assert seen[0].bounds is BOUNDS
