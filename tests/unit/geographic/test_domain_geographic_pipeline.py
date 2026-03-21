from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.geographic import GeographicConfig
from hydromodpy.geographic.core.domain_geographic_pipeline import (
    build_domain_geographic_context,
)
from hydromodpy.simulation.workspace import Workspace
from hydromodpy.simulation.workspace.config import WorkspaceConfig


def _write_dem(path: Path) -> None:
    transform = from_origin(1000.0, 2100.0, 50.0, 50.0)
    profile = {
        "driver": "GTiff",
        "height": 2,
        "width": 3,
        "count": 1,
        "dtype": rasterio.float32,
        "crs": "EPSG:2154",
        "transform": transform,
        "nodata": -9999.0,
    }
    values = np.array(
        [
            [10.0, 11.0, 12.0],
            [13.0, -9999.0, 15.0],
        ],
        dtype=np.float32,
    )
    with rasterio.open(str(path), "w", **profile) as dst:
        dst.write(values, 1)


def test_build_domain_geographic_context_from_dem(tmp_path: Path):
    dem_path = tmp_path / "domain_dem.tif"
    _write_dem(dem_path)

    workspace = Workspace(
        WorkspaceConfig(
            project_root=tmp_path / "results",
        )
    )
    config = GeographicConfig(
        catch_def="dem",
        dem_init_path=dem_path,
        crs_project="EPSG:2154",
    )

    context = build_domain_geographic_context(
        config=config,
        workspace=workspace,
    )

    assert context.catch_def == "dem"
    assert context.zone_kind == "uniform"
    assert context.river_mesh_trace is None
    assert context.x_outlet is None
    assert context.y_outlet is None
    assert Path(context.watershed_box_buff_dem).exists()
    assert Path(context.watershed_shp).exists()
    assert Path(context.box_buff_shp).exists()

    np.testing.assert_allclose(
        context.surface_topo.as_array(),
        np.array(
            [
                [10.0, 11.0, 12.0],
                [13.0, -9999.0, 15.0],
            ],
            dtype=float,
        ),
    )
    assert context.catchment_area_km2 == pytest.approx((5 * 50.0 * 50.0) / 1_000_000.0)

    watershed_gdf = gpd.read_file(context.watershed_shp)
    assert float(watershed_gdf.geometry.area.sum() / 1_000_000.0) == pytest.approx(
        context.catchment_area_km2
    )


def test_build_domain_geographic_context_from_synthetic_mode(tmp_path: Path):
    workspace = Workspace(
        WorkspaceConfig(
            project_root=tmp_path / "results",
        )
    )
    config = GeographicConfig(
        source_mode="synthetic",
        synthetic={
            "case_id": "domain_synth",
            "grid": {
                "length_x": "100 m",
                "length_y": "100 m",
                "nx": 2,
                "ny": 2,
                "xmin": 100.0,
                "ymin": 200.0,
            },
            "topography": {
                "kind": "flat",
                "base_elevation": 20.0,
            },
        },
    )

    context = build_domain_geographic_context(
        config=config,
        workspace=workspace,
    )

    assert context.catch_def == "synthetic"
    assert context.zone_kind == "uniform"
    assert context.river_mesh_trace is None
    assert context.catchment_area_km2 == pytest.approx(0.01)
    assert Path(context.watershed_box_buff_dem).exists()
    assert Path(context.watershed_shp).exists()
    np.testing.assert_allclose(context.surface_topo.as_array(), np.full((2, 2), 20.0))


def test_build_domain_geographic_context_retries_with_fill_after_empty_breach_watershed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = SimpleNamespace(
        catch_folder=tmp_path / "results",
        stable_folder=tmp_path / "results" / "results_stable",
    )
    config = GeographicConfig(
        catch_def="from_outlet_coord",
        dem_init_path=tmp_path / "regional_dem.tif",
        x_outlet=1000.0,
        y_outlet=2000.0,
        snap_dist="50 m",
        buff_area="20%",
        crs_project="EPSG:2154",
        dem_correc_type="breach",
        river_network={"enabled": False},
    )
    setup = SimpleNamespace(
        dem_init_path=str(tmp_path / "regional_dem.tif"),
        crs_project="EPSG:2154",
        dem_res=50.0,
        paths=SimpleNamespace(
            correcflow_path=str(tmp_path / "results" / "results_stable" / "demcorrecflow"),
            watershed_shp=str(tmp_path / "results" / "results_stable" / "geographic" / "watershed.shp"),
            watershed_box_shp=str(tmp_path / "results" / "results_stable" / "geographic" / "watershed_box.shp"),
            box_buff=str(tmp_path / "results" / "results_stable" / "geographic" / "watershed_box_buff.shp"),
            watershed_box_buff_dem=str(tmp_path / "results" / "results_stable" / "geographic" / "watershed_box_buff_dem.tif"),
            geographic_path=str(tmp_path / "results" / "results_stable" / "geographic"),
            river_streams_tif=str(tmp_path / "results" / "results_stable" / "geographic" / "river_streams.tif"),
            river_streams_pruned_tif=str(tmp_path / "results" / "results_stable" / "geographic" / "river_streams_pruned.tif"),
            river_stream_order_strahler_tif=str(tmp_path / "results" / "results_stable" / "geographic" / "river_stream_order_strahler.tif"),
            river_stream_link_id_tif=str(tmp_path / "results" / "results_stable" / "geographic" / "river_stream_link_id.tif"),
            river_network_shp=str(tmp_path / "results" / "results_stable" / "geographic" / "river_network.shp"),
            river_network_summary_json=str(tmp_path / "results" / "results_stable" / "geographic" / "river_network_summary.json"),
        ),
    )
    flow_calls: list[str] = []
    catchment_calls: list[str] = []

    monkeypatch.setattr(
        "hydromodpy.geographic.core.domain_geographic_pipeline.prepare_geographic_run",
        lambda **kwargs: setup,
    )

    def _fake_build_flow(**kwargs):
        dem_correc_type = str(kwargs["dem_correc_type"])
        flow_calls.append(dem_correc_type)
        return SimpleNamespace(
            correc=f"{dem_correc_type}_correc.tif",
            direc=f"{dem_correc_type}_direc.tif",
            acc=f"{dem_correc_type}_acc.tif",
            correc_data=object(),
            direc_data=object(),
            acc_data=object(),
        )

    monkeypatch.setattr(
        "hydromodpy.geographic.core.domain_geographic_pipeline.build_regional_flow_products",
        _fake_build_flow,
    )

    def _fake_build_standard_catchment(**kwargs):
        catchment_calls.append(str(kwargs["direc_path"]))
        if str(kwargs["direc_path"]).startswith("breach_"):
            raise ValueError(
                "Watershed delineation produced an empty polygon. Check outlet placement, "
                "DEM conditioning, and snap distance before rerunning the geographic pipeline."
            )
        return None

    monkeypatch.setattr(
        "hydromodpy.geographic.core.domain_geographic_pipeline.build_standard_catchment",
        _fake_build_standard_catchment,
    )
    monkeypatch.setattr(
        "hydromodpy.geographic.core.domain_geographic_pipeline.compute_catchment_area_km2",
        lambda path: 12.5,
    )
    monkeypatch.setattr(
        "hydromodpy.geographic.core.domain_geographic_pipeline.build_standard_domain_polygons",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.geographic.core.domain_geographic_pipeline.clip_dem_to_box_buffer",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.geographic.core.domain_geographic_pipeline.build_river_network_products",
        lambda **kwargs: SimpleNamespace(river_mesh_trace=None),
    )
    monkeypatch.setattr(
        "hydromodpy.geographic.core.domain_geographic_pipeline.build_surface_topo_from_dem",
        lambda path: object(),
    )

    context = build_domain_geographic_context(config=config, workspace=workspace)

    assert flow_calls == ["breach", "fill"]
    assert catchment_calls == ["breach_direc.tif", "fill_direc.tif"]
    assert context.catch_def == "from_outlet_coord"
    assert context.catchment_area_km2 == pytest.approx(12.5)
