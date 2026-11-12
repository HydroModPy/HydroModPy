"""Download box of the crossings (m, Lambert-93): the domain extent plus a margin, not 60 km.

Without a domain the box is the outlet box. A polygon catchment gives its own
bounds, grown by its buffer.
"""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import box

from hydromodpy.data.variables.crossings import resolver

BASIN_M = (498000.0, 6798000.0, 503000.0, 6803000.0)


def outlet_config() -> SimpleNamespace:
    return SimpleNamespace(
        geographic=SimpleNamespace(
            x_outlet=500000.0, y_outlet=6800000.0, crs_project="EPSG:2154", dem_init_path=None
        )
    )


def polygon_config(path) -> SimpleNamespace:
    return SimpleNamespace(
        geographic=SimpleNamespace(
            x_outlet=None,
            y_outlet=None,
            polyg_shp_path=path,
            crs_project="EPSG:2154",
            dem_init_path=None,
        )
    )


def write_basin(path, crs="EPSG:2154"):
    gpd.GeoDataFrame(geometry=[box(*BASIN_M)], crs="EPSG:2154").to_crs(crs).to_file(path)
    return path


def test_without_a_domain_the_box_stays_the_outlet_box():
    bbox = resolver._bootstrap_bbox(outlet_config(), "EPSG:2154")

    assert bbox[2] - bbox[0] == pytest.approx(2 * resolver._BOOTSTRAP_BUFFER_M)


def test_a_known_domain_gives_its_extent_plus_a_margin():
    bbox = resolver._bootstrap_bbox(outlet_config(), "EPSG:2154", domain_bounds=BASIN_M)

    margin = resolver.DOMAIN_MARGIN_M
    expected = (BASIN_M[0] - margin, BASIN_M[1] - margin, BASIN_M[2] + margin, BASIN_M[3] + margin)
    assert bbox == pytest.approx(expected)
    assert bbox[2] - bbox[0] < 20_000


def test_a_polygon_catchment_gives_its_own_bounds(tmp_path):
    shp = write_basin(tmp_path / "basin.shp")

    assert resolver.polygon_bounds(polygon_config(shp), "EPSG:2154") == pytest.approx(BASIN_M)


def test_a_polygon_in_another_crs_is_read_in_the_project_crs(tmp_path):
    gpkg = write_basin(tmp_path / "basin.gpkg", crs="EPSG:4326")

    bounds = resolver.polygon_bounds(polygon_config(gpkg), "EPSG:2154")

    assert bounds[0] == pytest.approx(498000.0, abs=200.0)
    assert bounds[3] == pytest.approx(6803000.0, abs=200.0)


def test_the_resolver_asks_the_polygon_box_when_the_catchment_is_a_polygon(tmp_path, monkeypatch):
    cfg = polygon_config(write_basin(tmp_path / "basin.shp"))
    cfg.data = SimpleNamespace(crossings=SimpleNamespace(sources=[SimpleNamespace(source="roe")]))
    seen = {}

    def fake_bbox(_cfg, _crs, *, domain_bounds=None, **_kw):
        seen["bounds"] = domain_bounds
        raise RuntimeError("stop")

    monkeypatch.setattr(resolver, "_bootstrap_bbox", fake_bbox)
    with pytest.raises(RuntimeError, match="stop"):
        resolver.resolve_crossings_path_from_data_sources(cfg, config_path=tmp_path / "c.toml")

    assert seen["bounds"] == pytest.approx(BASIN_M)


def test_a_polygon_domain_reaches_as_far_as_its_buffer(tmp_path):
    cfg = polygon_config(write_basin(tmp_path / "basin.shp"))
    cfg.geographic.buff_area = "3 km"

    bounds = resolver.polygon_bounds(cfg, "EPSG:2154")

    assert bounds == pytest.approx((495000.0, 6795000.0, 506000.0, 6806000.0))
    bbox = resolver._bootstrap_bbox(cfg, "EPSG:2154", domain_bounds=bounds)
    assert bbox[2] - bbox[0] == pytest.approx(11_000.0 + 2 * resolver.DOMAIN_MARGIN_M)
