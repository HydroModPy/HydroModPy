from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.spatial.geographic.core.catchment_from_point import CatchmentFromPointProducts
from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.site_selection.pipelines.build import (
    build_site_selection_from_point_records,
)

from ._test_build_builders import make_config, make_record, make_wgs84_hubeau_record


@pytest.mark.fast
def test_build_site_selection_from_point_records_chains_candidates_delineation_selection_and_exports(
    tmp_path,
):
    flow_calls = {}
    delineation_calls = []

    def fake_flow_builder(**kwargs):
        flow_calls.update(kwargs)
        return FlowProducts(correc="fill.tif", direc="direc.tif", acc="acc.tif")

    def fake_delineation_builder(**kwargs):
        delineation_calls.append(kwargs)
        output_dir = Path(kwargs["output_dir"])
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    result = build_site_selection_from_point_records(
        config=make_config(tmp_path),
        point_records=[make_record("J123456701")],
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
    )

    assert flow_calls["dem_correc_type"] == "fill"
    assert delineation_calls[0]["snap_dist"] == 150
    assert [candidate.source_feature_id for candidate in result.candidates] == ["J123456701"]
    assert [catchment.site_id for catchment in result.selection.selected] == ["station_J123456701"]
    assert result.output_paths["selected_sites_csv"].is_file()
    assert result.output_paths["observation_evidence_jsonl"].is_file()
    assert result.output_paths["observation_points_geojson"].is_file()
    assert result.observation_evidence[0].feature_id == "J123456701"


@pytest.mark.fast
@pytest.mark.parametrize(
    "keep_intermediate_rasters, expect_exists",
    [
        pytest.param(
            False,
            False,
            id="test_build_site_selection_from_point_records_removes_intermediate_rasters_by_default",
        ),
        pytest.param(
            True,
            True,
            id="test_build_site_selection_from_point_records_can_keep_intermediate_rasters",
        ),
    ],
)
def test_build_site_selection_from_point_records_intermediate_rasters(
    tmp_path, keep_intermediate_rasters, expect_exists
):
    cfg = make_config(tmp_path)
    output_update = {"write_geojson": False}
    if keep_intermediate_rasters:
        output_update["keep_intermediate_rasters"] = True
    cfg = cfg.model_copy(update={"output": cfg.output.model_copy(update=output_update)})
    created: dict[str, list[Path] | Path] = {}

    def fake_flow_builder(**kwargs):
        output_dir = Path(kwargs["dem_out_dir_path"])
        output_dir.mkdir(parents=True, exist_ok=True)
        rasters = [
            output_dir / "dem_fill.tif",
            output_dir / "dem_direc.tif",
            output_dir / "dem_acc.tif",
        ]
        for raster in rasters:
            raster.write_text("raster", encoding="utf-8")
        created["flow"] = rasters
        return FlowProducts(
            correc=str(rasters[0]),
            direc=str(rasters[1]),
            acc=str(rasters[2]),
        )

    def fake_delineation_builder(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        watershed_tif = output_dir / "watershed.tif"
        watershed_tif.write_text("raster", encoding="utf-8")
        created["watershed"] = watershed_tif
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(watershed_tif),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    build_site_selection_from_point_records(
        config=cfg,
        point_records=[make_record("J123456701")],
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
    )

    assert all(path.exists() is expect_exists for path in created["flow"])
    assert created["watershed"].exists() is expect_exists


@pytest.mark.fast
def test_build_site_selection_from_point_records_reprojects_station_locations(tmp_path):
    delineation_calls = []

    def fake_flow_builder(**kwargs):
        assert kwargs["crs_project"] == "EPSG:2154"
        return FlowProducts(correc="fill.tif", direc="direc.tif", acc="acc.tif")

    def fake_delineation_builder(**kwargs):
        delineation_calls.append(kwargs)
        output_dir = Path(kwargs["output_dir"])
        return CatchmentFromPointProducts(
            outlet_shp=str(output_dir / "outlet.shp"),
            outlet_snap_shp=str(output_dir / "outlet_snap.shp"),
            watershed_tif=str(output_dir / "watershed.tif"),
            watershed_shp=str(output_dir / "watershed.shp"),
        )

    result = build_site_selection_from_point_records(
        config=make_config(tmp_path),
        point_records=[make_wgs84_hubeau_record("J123456701")],
        flow_products_builder=fake_flow_builder,
        delineation_builder=fake_delineation_builder,
        area_reader=lambda _path: 100.0,
        write_outputs=False,
    )

    assert result.candidates[0].x == pytest.approx(352000.0)
    assert result.candidates[0].y == pytest.approx(6812000.0)
    assert result.candidates[0].crs == "EPSG:2154"
    assert delineation_calls[0]["x_outlet"] == pytest.approx(352000.0)
    assert delineation_calls[0]["y_outlet"] == pytest.approx(6812000.0)


@pytest.mark.fast
def test_build_site_selection_from_point_records_requires_dem(tmp_path):
    cfg = make_config(tmp_path).model_copy(
        update={"dem": make_config(tmp_path).dem.model_copy(update={"path": None})}
    )

    with pytest.raises(ValueError, match="requires dem_init_path or dem.path"):
        build_site_selection_from_point_records(
            config=cfg,
            point_records=[make_record("J123456701")],
            flow_products_builder=lambda **_kwargs: FlowProducts(
                correc="fill.tif",
                direc="direc.tif",
                acc="acc.tif",
            ),
        )
