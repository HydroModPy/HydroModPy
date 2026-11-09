"""The bounds of a call reach the HTTP client every port class hands to its provider."""

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


def _empty_features(*args, **kwargs):
    return gpd.GeoDataFrame(geometry=[], crs=sandre_topage.QUERY_CRS)


def _empty_pages(*args, **kwargs):
    return iter(())


# (module, attribute the port class calls, what that stub returns, class, request kwargs)
CASES = {
    "piezometry": (
        piezometry_hubeau,
        "fetch",
        lambda **kw: [],
        lambda: piezometry_hubeau.HubeauPiezometry(),
        {"extent": WGS84, "period": PERIOD},
    ),
    "water_quality": (
        water_quality_hubeau,
        "fetch",
        lambda **kw: [],
        lambda: water_quality_hubeau.HubeauWaterQuality(),
        {"extent": WGS84, "period": PERIOD},
    ),
    "intermittency": (
        intermittency_hubeau,
        "fetch",
        lambda **kw: [],
        lambda: intermittency_hubeau.HubeauIntermittency(),
        {"extent": WGS84, "period": PERIOD},
    ),
    "bdtopage": (
        sandre_topage,
        "get_features",
        _empty_features,
        lambda: BdTopageSource(page_size=10),
        {"extent": LAMBERT},
    ),
    "roe": (
        roe,
        "fetch_pages",
        _empty_pages,
        lambda: roe.RoeCrossings(page_size=10),
        {"extent": LAMBERT},
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_client_of_the_provider_carries_the_bounds_of_the_request(name, monkeypatch, tmp_path):
    module, attribute, stub, build, request_kwargs = CASES[name]
    seen: list[object] = []

    def recorder(*args, **kwargs):
        seen.append(kwargs.get("client"))
        return stub(*args, **kwargs)

    monkeypatch.setattr(module, attribute, recorder)
    build().fetch(FetchRequest(out_dir=tmp_path, bounds=BOUNDS, **request_kwargs))

    assert len(seen) == 1
    assert seen[0] is not None
    assert seen[0].bounds is BOUNDS
