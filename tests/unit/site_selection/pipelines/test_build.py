from __future__ import annotations

from functools import partial
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.spatial.site_selection.config.dem_config import DemAreaLightConfig
from hydromodpy.spatial.site_selection.config.site_selection_config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.config.strategy_config import TerritoryConfig
from hydromodpy.spatial.site_selection.pipelines.build import (
    build_site_selection_from_dem_area_light,
    build_site_selection_from_generated_network,
    build_site_selection_from_point_records,
)
from hydromodpy.spatial.terrain import registry
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.site_selection_cases import (
    delineation_spy,
    flow_spy,
    make_config,
    make_record,
    make_wgs84_hubeau_record,
)
from tests._helpers.terrain_doubles import fake_flow_products

pytestmark = pytest.mark.fast
from_stations = partial(build_site_selection_from_point_records, reference_network_fetcher=None)
from_network = partial(build_site_selection_from_generated_network, reference_network_fetcher=None)
ONE, TWO = "J123456701", "J123456702"


def _area(_path):
    return 100.0


def test_station_records_chain_candidates_delineation_selection_and_exports(tmp_path):
    flow_calls: dict = {}
    delineation_calls: list = []

    result = from_stations(
        config=make_config(tmp_path), point_records=[make_record(ONE), make_wgs84_hubeau_record(TWO)],
        flow_products_builder=flow_spy(flow_calls), area_reader=_area,
        delineation_builder=delineation_spy(delineation_calls),
    )  # fmt: skip

    assert (flow_calls["dem_correc_type"], flow_calls["crs_project"]) == ("fill", "EPSG:2154")
    assert [call["snap_dist"] for call in delineation_calls] == [150, 150]
    assert [call["x_outlet"] for call in delineation_calls] == [350000.0, 352000.0]
    assert [one.area_km2 for one in result.delineated] == [100.0, 100.0]
    assert [candidate.source_feature_id for candidate in result.candidates] == [ONE, TWO]
    reprojected = result.candidates[1]
    assert (reprojected.x, reprojected.y, reprojected.crs) == (352000.0, 6812000.0, "EPSG:2154")
    assert f"station_{ONE}" in [site.site_id for site in result.selection.selected]
    for name in ("selected_sites_csv", "observation_evidence_jsonl", "observation_points_geojson"):
        assert result.output_paths[name].is_file()
    assert [one.feature_id for one in result.observation_evidence] == [ONE, TWO]


@pytest.mark.parametrize("keep", [False, True], ids=["removed_by_default", "kept_on_request"])
def test_the_intermediate_rasters_are_removed_unless_kept(tmp_path, keep):
    cfg = make_config(tmp_path)
    # The removal case leaves the default in place.
    update = {"write_geojson": False} | ({"keep_intermediate_rasters": True} if keep else {})
    created: list[Path] = []

    def flow_builder(**kwargs):
        rasters = [Path(kwargs["dem_out_dir_path"]) / f"dem_{name}.tif" for name in "abc"]
        created.extend(rasters)
        for raster in rasters:
            raster.parent.mkdir(parents=True, exist_ok=True)
            raster.write_text("raster", encoding="utf-8")
        return fake_flow_products(correc=rasters[0], direc=rasters[1], acc=rasters[2])

    def delineation_builder(**kwargs):
        products = delineation_spy()(**kwargs)
        Path(products.watershed_tif).parent.mkdir(parents=True, exist_ok=True)
        Path(products.watershed_tif).write_text("raster", encoding="utf-8")
        created.append(Path(products.watershed_tif))
        return products

    from_stations(
        config=cfg.model_copy(update={"output": cfg.output.model_copy(update=update)}),
        point_records=[make_record(ONE)], flow_products_builder=flow_builder,
        delineation_builder=delineation_builder, area_reader=_area,
    )  # fmt: skip

    assert len(created) == 4
    assert all(path.exists() is keep for path in created)


@pytest.mark.parametrize(
    "build", [from_stations, from_network, build_site_selection_from_dem_area_light]
)
def test_a_build_without_a_dem_is_refused(tmp_path, build):
    cfg = make_config(tmp_path)
    cfg = cfg.model_copy(update={"dem": cfg.dem.model_copy(update={"path": None})})
    if build is build_site_selection_from_dem_area_light:
        with pytest.raises(ValueError, match="requires dem_area_light config"):
            build(config=cfg)
        cfg = cfg.model_copy(update={"dem_area_light": DemAreaLightConfig()})
    kwargs = {"point_records": []} if build is from_stations else {}

    with pytest.raises(ValueError, match="requires dem_init_path or dem.path"):
        build(config=cfg, **kwargs)


LAMBERT_DEM, DEGREE_DEM = ((350000.0, 6815000.0), 100.0), ((-1.7, 48.2), 0.01)


@pytest.mark.parametrize(("dem", "bbox", "what"), [
    (LAMBERT_DEM, None, None),
    (DEGREE_DEM, None, "the DEM"),
    (LAMBERT_DEM, [-1.7, 48.0, -1.5, 48.2], "site_selection.territory.bbox"),
])  # fmt: skip
def test_a_dem_without_crs_takes_lambert_93_only_inside_france(tmp_path, dem, bbox, what):
    cfg, flow_calls = make_config(tmp_path), {}
    write_geotiff(cfg.dem.path, np.ones((2, 2)), origin=dem[0], cell=dem[1], crs=None)
    if bbox is not None:
        cfg = cfg.model_copy(update={"territory": TerritoryConfig(mode="bbox", bbox=bbox)})
    run = partial(
        from_stations, config=cfg, point_records=[make_record(ONE)], area_reader=_area,
        flow_products_builder=flow_spy(flow_calls), delineation_builder=delineation_spy(),
        write_outputs=False,
    )  # fmt: skip
    if what is None:
        run()
        assert flow_calls["crs_project"] == "EPSG:2154"
        return
    with pytest.raises(ConfigValidationError, match=f"{what}.*outside its area.*crs_project"):
        run()


@pytest.mark.parametrize("engine", [registry.builtin_engine_ids()[0], None])
def test_the_configured_engine_reaches_the_flow_and_delineation_builders(tmp_path, engine):
    """An unset engine reaches them as an explicit None, never as a missing keyword."""
    flow_calls: dict = {}
    delineation_calls: list = []

    config = make_config(tmp_path).model_dump() | {"terrain_engine": engine}

    from_stations(
        config=SiteSelectionConfig.model_validate(config), point_records=[make_record(ONE)],
        flow_products_builder=flow_spy(flow_calls), area_reader=_area, write_outputs=False,
        delineation_builder=delineation_spy(delineation_calls),
    )  # fmt: skip

    assert "engine_id" in flow_calls and "engine_id" in delineation_calls[0]
    assert flow_calls["engine_id"] == delineation_calls[0]["engine_id"] == engine


def test_a_station_snapped_to_the_reference_network_records_it_in_the_manifest(tmp_path):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import LineString

    network = tmp_path / "network.gpkg"
    river = LineString([(349000.0, 6810040.0), (351000.0, 6810040.0)])
    gpd.GeoDataFrame(geometry=[river], crs="EPSG:2154").to_file(network)
    cfg = make_config(tmp_path)
    update = {
        "snap_strategy": "bdtopage_then_dem", "reference_network_source": "custom",
        "reference_network_path": network, "reference_network_max_distance_m": 100.0,
    }  # fmt: skip
    calls: list = []

    result = from_stations(
        config=cfg.model_copy(update={"outlets": cfg.outlets.model_copy(update=update)}),
        point_records=[make_record(ONE)], flow_products_builder=flow_spy(),
        delineation_builder=delineation_spy(calls), area_reader=_area,
    )  # fmt: skip

    assert calls[0]["y_outlet"] == pytest.approx(6810040.0)
    assert calls[0]["snap_dist"] == 150
    assert result.delineated[0].outlet.attributes["reference_network_snap_distance_m"] == 40.0
    manifest = result.output_paths["site_selection_manifest_json"].read_text(encoding="utf-8")
    assert '"feature_count": 1' in manifest
