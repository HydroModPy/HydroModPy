"""X-PERF: the crossings download box is the domain extent plus a margin, not 60 km."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.data.variables.crossings import resolver


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        geographic=SimpleNamespace(
            x_outlet=500000.0,
            y_outlet=6800000.0,
            crs_project="EPSG:2154",
            dem_init_path=None,
        )
    )


def test_without_a_domain_the_box_stays_the_outlet_box() -> None:
    box = resolver._bootstrap_bbox(_cfg(), "EPSG:2154")

    assert box[2] - box[0] == pytest.approx(2 * resolver._BOOTSTRAP_BUFFER_M)


def test_a_known_domain_gives_a_box_of_its_extent_plus_a_margin() -> None:
    bounds = (498000.0, 6798000.0, 503000.0, 6803000.0)

    box = resolver._bootstrap_bbox(_cfg(), "EPSG:2154", domain_bounds=bounds)

    margin = resolver.DOMAIN_MARGIN_M
    assert box == pytest.approx(
        (bounds[0] - margin, bounds[1] - margin, bounds[2] + margin, bounds[3] + margin)
    )
    assert box[2] - box[0] < 20_000


def _polygon_cfg(path) -> SimpleNamespace:
    return SimpleNamespace(
        geographic=SimpleNamespace(
            x_outlet=None,
            y_outlet=None,
            polyg_shp_path=path,
            crs_project="EPSG:2154",
            dem_init_path=None,
        )
    )


def test_a_polygon_catchment_gives_its_own_bounds(tmp_path) -> None:
    import geopandas as gpd
    from shapely.geometry import box

    shp = tmp_path / "basin.shp"
    gpd.GeoDataFrame(geometry=[box(498000, 6798000, 503000, 6803000)], crs="EPSG:2154").to_file(shp)

    bounds = resolver.polygon_bounds(_polygon_cfg(shp), "EPSG:2154")

    assert bounds == pytest.approx((498000.0, 6798000.0, 503000.0, 6803000.0))


def test_a_polygon_in_another_crs_is_read_in_the_project_crs(tmp_path) -> None:
    import geopandas as gpd
    from shapely.geometry import box

    shp = tmp_path / "basin.gpkg"
    gpd.GeoDataFrame(geometry=[box(498000, 6798000, 503000, 6803000)], crs="EPSG:2154").to_crs(
        "EPSG:4326"
    ).to_file(shp)

    bounds = resolver.polygon_bounds(_polygon_cfg(shp), "EPSG:2154")

    assert bounds[0] == pytest.approx(498000.0, abs=200.0)
    assert bounds[3] == pytest.approx(6803000.0, abs=200.0)


def test_an_outlet_catchment_has_no_polygon_bounds() -> None:
    assert resolver.polygon_bounds(_cfg(), "EPSG:2154") is None


def test_the_resolver_asks_the_polygon_box_when_the_catchment_is_a_polygon(
    tmp_path, monkeypatch
) -> None:
    import geopandas as gpd
    from shapely.geometry import box

    shp = tmp_path / "basin.shp"
    gpd.GeoDataFrame(geometry=[box(498000, 6798000, 503000, 6803000)], crs="EPSG:2154").to_file(shp)
    cfg = _polygon_cfg(shp)
    seen: dict = {}

    def fake_bbox(_cfg, _crs, *, domain_bounds=None):
        seen["bounds"] = domain_bounds
        raise RuntimeError("stop")

    monkeypatch.setattr(resolver, "_bootstrap_bbox", fake_bbox)
    cfg.data = SimpleNamespace(crossings=SimpleNamespace(sources=[SimpleNamespace(source="roe")]))
    with pytest.raises(RuntimeError, match="stop"):
        resolver.resolve_crossings_path_from_data_sources(cfg, config_path=tmp_path / "c.toml")

    assert seen["bounds"] == pytest.approx((498000.0, 6798000.0, 503000.0, 6803000.0))


def test_a_polygon_domain_reaches_as_far_as_its_buffer(tmp_path) -> None:
    import geopandas as gpd
    from shapely.geometry import box

    shp = tmp_path / "basin.shp"
    gpd.GeoDataFrame(geometry=[box(498000, 6798000, 503000, 6803000)], crs="EPSG:2154").to_file(shp)
    cfg = _polygon_cfg(shp)
    cfg.geographic.buff_area = "3 km"

    bounds = resolver.polygon_bounds(cfg, "EPSG:2154")

    assert bounds == pytest.approx((495000.0, 6795000.0, 506000.0, 6806000.0))
    box_m = resolver._bootstrap_bbox(cfg, "EPSG:2154", domain_bounds=bounds)
    assert box_m[2] - box_m[0] == pytest.approx(11_000.0 + 2 * resolver.DOMAIN_MARGIN_M)
