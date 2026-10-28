from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.spatial.site_selection.config import DemAreaLightConfig, SiteSelectionConfig
from hydromodpy.spatial.site_selection.pipelines.build import (
    build_site_selection_from_dem_area_light,
    build_site_selection_from_generated_network,
    build_site_selection_from_point_records,
)
from hydromodpy.spatial.terrain import registry
from tests._helpers.site_selection_cases import (
    delineation_spy,
    flow_spy,
    make_config,
    make_record,
    make_wgs84_hubeau_record,
)
from tests._helpers.terrain_doubles import fake_flow_products

pytestmark = pytest.mark.fast


def test_station_records_chain_candidates_delineation_selection_and_exports(tmp_path):
    flow_calls: dict = {}
    delineation_calls: list = []

    result = build_site_selection_from_point_records(
        config=make_config(tmp_path),
        point_records=[make_record("J123456701"), make_wgs84_hubeau_record("J123456702")],
        flow_products_builder=flow_spy(flow_calls),
        delineation_builder=delineation_spy(delineation_calls),
        area_reader=lambda _path: 100.0,
    )

    assert flow_calls["dem_correc_type"] == "fill"
    assert flow_calls["crs_project"] == "EPSG:2154"
    assert [call["snap_dist"] for call in delineation_calls] == [150, 150]
    assert [call["x_outlet"] for call in delineation_calls] == [350000.0, 352000.0]
    assert [candidate.source_feature_id for candidate in result.candidates] == [
        "J123456701",
        "J123456702",
    ]
    reprojected = result.candidates[1]
    assert (reprojected.x, reprojected.y, reprojected.crs) == (352000.0, 6812000.0, "EPSG:2154")
    assert "station_J123456701" in [site.site_id for site in result.selection.selected]
    for name in ("selected_sites_csv", "observation_evidence_jsonl", "observation_points_geojson"):
        assert result.output_paths[name].is_file()
    assert [one.feature_id for one in result.observation_evidence] == ["J123456701", "J123456702"]


@pytest.mark.parametrize("keep", [False, True], ids=["removed_by_default", "kept_on_request"])
def test_the_intermediate_rasters_are_removed_unless_kept(tmp_path, keep):
    cfg = make_config(tmp_path)
    update: dict[str, bool] = {"write_geojson": False}
    if keep:  # the removal case leaves the default in place
        update["keep_intermediate_rasters"] = True
    output = cfg.output.model_copy(update=update)
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

    build_site_selection_from_point_records(
        config=cfg.model_copy(update={"output": output}),
        point_records=[make_record("J123456701")],
        flow_products_builder=flow_builder,
        delineation_builder=delineation_builder,
        area_reader=lambda _path: 100.0,
    )

    assert len(created) == 4
    assert all(path.exists() is keep for path in created)


@pytest.mark.parametrize(
    "build",
    [
        build_site_selection_from_point_records,
        build_site_selection_from_generated_network,
        build_site_selection_from_dem_area_light,
    ],
)
def test_a_build_without_a_dem_is_refused(tmp_path, build):
    cfg = make_config(tmp_path)
    cfg = cfg.model_copy(update={"dem": cfg.dem.model_copy(update={"path": None})})
    if build is build_site_selection_from_dem_area_light:
        with pytest.raises(ValueError, match="requires dem_area_light config"):
            build(config=cfg)
        cfg = cfg.model_copy(update={"dem_area_light": DemAreaLightConfig()})
    kwargs = {"point_records": []} if build is build_site_selection_from_point_records else {}

    with pytest.raises(ValueError, match="requires dem_init_path or dem.path"):
        build(config=cfg, **kwargs)


@pytest.mark.parametrize("engine", [registry.builtin_engine_ids()[0], None])
def test_the_configured_engine_reaches_the_flow_and_delineation_builders(tmp_path, engine):
    """An unset engine reaches them as an explicit None, never as a missing keyword."""
    flow_calls: dict = {}
    delineation_calls: list = []

    build_site_selection_from_point_records(
        config=SiteSelectionConfig.model_validate(
            make_config(tmp_path).model_dump() | {"terrain_engine": engine}
        ),
        point_records=[make_record("J123456701")],
        flow_products_builder=flow_spy(flow_calls),
        delineation_builder=delineation_spy(delineation_calls),
        area_reader=lambda _path: 100.0,
        write_outputs=False,
    )

    assert "engine_id" in flow_calls and "engine_id" in delineation_calls[0]
    assert flow_calls["engine_id"] == delineation_calls[0]["engine_id"] == engine


def test_a_station_snapped_to_the_reference_network_records_it_in_the_manifest(tmp_path):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import LineString

    network = tmp_path / "network.gpkg"
    river = LineString([(349000.0, 6810040.0), (351000.0, 6810040.0)])
    gpd.GeoDataFrame(geometry=[river], crs="EPSG:2154").to_file(network)
    cfg = make_config(tmp_path)
    outlets = cfg.outlets.model_copy(
        update={
            "snap_strategy": "bdtopage_then_dem",
            "reference_network_source": "custom",
            "reference_network_path": network,
            "reference_network_max_distance_m": 100.0,
        }
    )
    calls: list = []

    result = build_site_selection_from_point_records(
        config=cfg.model_copy(update={"outlets": outlets}),
        point_records=[make_record("J123456701")],
        flow_products_builder=flow_spy(),
        delineation_builder=delineation_spy(calls),
        area_reader=lambda _path: 100.0,
    )

    assert calls[0]["y_outlet"] == pytest.approx(6810040.0)
    assert result.delineated[0].outlet.attributes["reference_network_snap_distance_m"] == 40.0
    manifest = result.output_paths["site_selection_manifest_json"].read_text(encoding="utf-8")
    assert '"feature_count": 1' in manifest
