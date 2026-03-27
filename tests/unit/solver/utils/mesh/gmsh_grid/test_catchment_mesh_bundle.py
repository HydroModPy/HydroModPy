from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
import hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle as catchment_mesh_bundle_mod
from hydromodpy.solver.utils.mesh.gmsh_grid._bundle_export_contracts import (
    CatchmentBundleGeologyExportConfig,
    CatchmentBundleHydraulicPropertiesConfig,
    CatchmentBundleSummaryReference,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle import (
    export_catchment_mesh_bundle,
    load_catchment_mesh_bundle,
)


def _write_raster(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": int(values.shape[0]),
        "width": int(values.shape[1]),
        "count": 1,
        "dtype": rasterio.float32,
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, 1.0, 0.5, 0.5),
        "nodata": -9999.0,
    }
    with rasterio.open(str(path), "w", **profile) as dst:
        dst.write(np.asarray(values, dtype=np.float32), 1)


def _write_ascii_triangle_mesh(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "$MeshFormat",
                "2.2 0 8",
                "$EndMeshFormat",
                "$Nodes",
                "4",
                "1 0.0 0.0 0.0",
                "2 1.0 0.0 0.0",
                "3 1.0 1.0 0.0",
                "4 0.0 1.0 0.0",
                "$EndNodes",
                "$Elements",
                "2",
                "1 2 0 1 2 3",
                "2 2 0 1 3 4",
                "$EndElements",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_export_and_load_catchment_mesh_bundle(tmp_path: Path) -> None:
    mesh_path = tmp_path / "mesh.msh"
    _write_ascii_triangle_mesh(mesh_path)

    support = RasterSupport(
        crs="EPSG:2154",
        dx=0.5,
        dy=0.5,
        xmin=0.0,
        xmax=1.0,
        ymin=0.0,
        ymax=1.0,
        nrows=2,
        ncols=2,
        nodata=-9999.0,
    )
    surface = Surface(
        name="surface_topo",
        values=np.array([[10.0, 20.0], [30.0, 40.0]], dtype=float),
        support=support,
    )
    dem_path = tmp_path / "topography.tif"
    _write_raster(dem_path, np.array([[10.0, 20.0], [30.0, 40.0]], dtype=float))

    geology_path = tmp_path / "geology.tif"
    _write_raster(geology_path, np.array([[1.0, 2.0], [1.0, 2.0]], dtype=float))

    summary_path = tmp_path / "mesh_summary.json"
    summary_payload = {
        "summary_schema_version": "zone_conformal_sidecar_v1",
        "constraints_mode": "geology_only",
        "output_summary_json": str(summary_path),
    }
    summary_path.write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    domain_geographic = SimpleNamespace(
        surface_topo=surface,
        watershed_box_buff_dem=dem_path,
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text("# test config\n", encoding="utf-8")

    bundle_summary = export_catchment_mesh_bundle(
        mesh_path=mesh_path,
        domain_geographic=domain_geographic,
        domain_cfg={
            "depth_model": {
                "type": "flat_substratum",
                "substratum_elevation": 5.0,
            }
        },
        geology_cfg=CatchmentBundleGeologyExportConfig.from_mapping(
            {
                "id": "field_geology",
                "source": {
                    "path": "geology.tif",
                    "kind": "raster",
                },
                "cell_samples_per_axis": 8,
            }
        ),
        hydraulic_properties_cfg=CatchmentBundleHydraulicPropertiesConfig.from_mapping(
            {
                "conductivity": {
                    "values_source": "inline",
                    "unit": "m/day",
                    "values": {"1": 8.64, "2": 17.28},
                },
                "storage_coefficient": {
                    "values_source": "inline",
                    "values": {"1": 0.10, "2": 0.20},
                },
            }
        ),
        river_trace=None,
        summary=CatchmentBundleSummaryReference.from_mapping(summary_payload),
        config_path=config_path,
    )

    bundle_dir = Path(bundle_summary["bundle_dir"])
    assert bundle_summary["bundle_schema_version"] == "mesh_catchment_bundle_v1"
    assert bundle_summary["geology_available"] is True
    assert bundle_summary["hydraulic_properties_available"] is True
    assert bundle_summary["vertical_available"] is True
    assert (bundle_dir / "mesh_2d.msh").exists()
    assert (bundle_dir / "nodes.csv").exists()
    assert (bundle_dir / "cells.csv").exists()
    assert (bundle_dir / "edges.csv").exists()
    assert (bundle_dir / "cell_geology_fractions.csv").exists()
    assert (bundle_dir / "metadata.json").exists()
    assert (bundle_dir / "README.md").exists()
    assert (bundle_dir / "mesh_summary.json").exists()
    assert "reader" not in loaded_metadata_files(bundle_dir)

    loaded = load_catchment_mesh_bundle(bundle_dir)

    assert loaded.n_nodes == 4
    assert loaded.n_cells == 2
    assert loaded.n_edges == 5
    assert loaded.metadata_view.files.mesh == "mesh_2d.msh"
    assert loaded.metadata_view.geology.available is True
    assert loaded.metadata_view.topography.source_path == str(dem_path)
    assert loaded.metadata_view.vertical.derived_from == "domain.depth_model"
    assert loaded.metadata_view.vertical.depth_model["type"] == "flat_substratum"
    assert (
        loaded.metadata_view.hydraulic_properties.conductivity.unit == "m/s"
    )
    assert loaded.metadata["geology"]["available"] is True
    assert loaded.metadata["hydraulic_properties"]["available"] is True
    assert loaded.metadata["topography"]["source_path"] == str(dem_path)
    assert loaded.metadata["vertical"]["derived_from"] == "domain.depth_model"
    assert loaded.metadata["vertical"]["depth_model"]["type"] == "flat_substratum"
    assert loaded.metadata["vertical"]["depth_model"]["substratum_elevation_m"] == 5.0
    assert loaded.mesh_summary is not None
    assert loaded.mesh_summary["constraints_mode"] == "geology_only"

    assert loaded.cells[0].geology_key in {"1", "2"}
    assert loaded.cells[1].geology_key in {"1", "2"}
    assert loaded.cells[0].geology_key != loaded.cells[1].geology_key
    assert loaded.cells[0].hydraulic_conductivity_m_s is not None
    assert loaded.cells[1].hydraulic_conductivity_m_s is not None
    assert loaded.cells[0].storage_coefficient is not None
    assert loaded.cells[1].storage_coefficient is not None
    assert all(cell.area_m2 > 0.0 for cell in loaded.cells)
    assert all(node.z_top is not None for node in loaded.nodes)
    assert all(np.isclose(float(node.z_bottom), 5.0) for node in loaded.nodes)
    assert all(np.isclose(float(cell.z_bottom_centroid), 5.0) for cell in loaded.cells)
    assert all(np.isclose(float(cell.z_bottom_mean), 5.0) for cell in loaded.cells)

    interface_edges = [edge for edge in loaded.edges if edge.edge_kind == "geology_interface"]
    assert len(interface_edges) == 1
    assert interface_edges[0].cell_b is not None

    geology_fraction_cells = {row.cell_id for row in loaded.geology_fractions}
    assert geology_fraction_cells == {0, 1}


def test_export_catchment_mesh_bundle_uses_constant_thickness_depth_model(
    tmp_path: Path,
) -> None:
    mesh_path = tmp_path / "mesh.msh"
    _write_ascii_triangle_mesh(mesh_path)

    support = RasterSupport(
        crs="EPSG:2154",
        dx=0.5,
        dy=0.5,
        xmin=0.0,
        xmax=1.0,
        ymin=0.0,
        ymax=1.0,
        nrows=2,
        ncols=2,
        nodata=-9999.0,
    )
    surface = Surface(
        name="surface_topo",
        values=np.array([[10.0, 20.0], [30.0, 40.0]], dtype=float),
        support=support,
    )
    domain_geographic = SimpleNamespace(surface_topo=surface, watershed_box_buff_dem=None)

    bundle_summary = export_catchment_mesh_bundle(
        mesh_path=mesh_path,
        domain_geographic=domain_geographic,
        domain_cfg={
            "depth_model": {
                "type": "constant_thickness",
                "thickness": "7 m",
            }
        },
    )

    loaded = load_catchment_mesh_bundle(bundle_summary["bundle_dir"])

    assert loaded.metadata["vertical"]["depth_model"]["type"] == "constant_thickness"
    assert loaded.metadata["vertical"]["depth_model"]["thickness_m"] == 7.0
    assert all(node.z_top is not None for node in loaded.nodes)
    assert all(node.z_bottom is not None for node in loaded.nodes)
    for node in loaded.nodes:
        assert np.isclose(float(node.z_top) - float(node.z_bottom), 7.0)
    for cell in loaded.cells:
        assert np.isclose(
            float(cell.z_top_centroid) - float(cell.z_bottom_centroid),
            7.0,
        )
        assert np.isclose(
            float(cell.z_top_mean) - float(cell.z_bottom_mean),
            7.0,
        )


def test_export_catchment_mesh_bundle_uses_bulk_surface_sampling(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mesh_path = tmp_path / "mesh.msh"
    _write_ascii_triangle_mesh(mesh_path)

    support = RasterSupport(
        crs="EPSG:2154",
        dx=0.5,
        dy=0.5,
        xmin=0.0,
        xmax=1.0,
        ymin=0.0,
        ymax=1.0,
        nrows=2,
        ncols=2,
        nodata=-9999.0,
    )
    surface = Surface(
        name="surface_topo",
        values=np.array([[10.0, 20.0], [30.0, 40.0]], dtype=float),
        support=support,
    )
    domain_geographic = SimpleNamespace(surface_topo=surface, watershed_box_buff_dem=None)

    def _forbidden_sample(*args, **kwargs):
        raise AssertionError("_sample_surface should not be used inside bundle export")

    monkeypatch.setattr(catchment_mesh_bundle_mod, "_sample_surface", _forbidden_sample)

    bundle_summary = export_catchment_mesh_bundle(
        mesh_path=mesh_path,
        domain_geographic=domain_geographic,
        domain_cfg={
            "depth_model": {
                "type": "constant_thickness",
                "thickness": "7 m",
            }
        },
    )

    loaded = load_catchment_mesh_bundle(bundle_summary["bundle_dir"])
    assert loaded.n_nodes == 4
    assert loaded.n_cells == 2


def test_export_catchment_mesh_bundle_marks_river_edges(tmp_path: Path) -> None:
    mesh_path = tmp_path / "mesh.msh"
    _write_ascii_triangle_mesh(mesh_path)

    support = RasterSupport(
        crs="EPSG:2154",
        dx=0.5,
        dy=0.5,
        xmin=0.0,
        xmax=1.0,
        ymin=0.0,
        ymax=1.0,
        nrows=2,
        ncols=2,
        nodata=-9999.0,
    )
    surface = Surface(
        name="surface_topo",
        values=np.array([[10.0, 20.0], [30.0, 40.0]], dtype=float),
        support=support,
    )
    domain_geographic = SimpleNamespace(surface_topo=surface, watershed_box_buff_dem=None)
    river_trace = SimpleNamespace(lines=(LineString([(0.0, 0.0), (1.0, 1.0)]),))

    bundle_summary = export_catchment_mesh_bundle(
        mesh_path=mesh_path,
        domain_geographic=domain_geographic,
        domain_cfg={
            "depth_model": {
                "type": "constant_thickness",
                "thickness": "7 m",
            }
        },
        river_trace=river_trace,
    )

    loaded = load_catchment_mesh_bundle(bundle_summary["bundle_dir"])
    river_edges = [edge for edge in loaded.edges if edge.is_river]

    assert len(river_edges) == 1
    assert river_edges[0].node_a == 0
    assert river_edges[0].node_b == 2


def test_export_catchment_mesh_bundle_uses_default_csv_conductivity_for_unmapped_zone(
    tmp_path: Path,
) -> None:
    mesh_path = tmp_path / "mesh.msh"
    _write_ascii_triangle_mesh(mesh_path)

    support = RasterSupport(
        crs="EPSG:2154",
        dx=0.5,
        dy=0.5,
        xmin=0.0,
        xmax=1.0,
        ymin=0.0,
        ymax=1.0,
        nrows=2,
        ncols=2,
        nodata=-9999.0,
    )
    surface = Surface(
        name="surface_topo",
        values=np.array([[10.0, 20.0], [30.0, 40.0]], dtype=float),
        support=support,
    )
    domain_geographic = SimpleNamespace(surface_topo=surface, watershed_box_buff_dem=None)

    geology_path = tmp_path / "geology_missing_zone.tif"
    _write_raster(geology_path, np.array([[1.0, 3.0], [1.0, 3.0]], dtype=float))

    conductivity_csv = tmp_path / "conductivity.csv"
    conductivity_csv.write_text(
        "zone_key,K_value\n1,8.64e-5\n",
        encoding="utf-8",
    )

    bundle_summary = export_catchment_mesh_bundle(
        mesh_path=mesh_path,
        domain_geographic=domain_geographic,
        domain_cfg={
            "depth_model": {
                "type": "constant_thickness",
                "thickness": "7 m",
            }
        },
        geology_cfg=CatchmentBundleGeologyExportConfig.from_mapping(
            {
                "id": "field_geology",
                "source": {
                    "path": str(geology_path),
                    "kind": "raster",
                },
                "cell_samples_per_axis": 8,
            }
        ),
        hydraulic_properties_cfg=CatchmentBundleHydraulicPropertiesConfig.from_mapping(
            {
                "conductivity": {
                    "values_source": "csv",
                    "values_csv_file": str(conductivity_csv),
                    "csv_value_column": "K_value",
                    "default_value": 1.0e-5,
                }
            }
        ),
        config_path=tmp_path / "config.toml",
    )

    loaded = load_catchment_mesh_bundle(bundle_summary["bundle_dir"])

    conductivity_values = np.asarray(
        [float(cell.hydraulic_conductivity_m_s) for cell in loaded.cells],
        dtype=float,
    )
    assert np.all(np.isfinite(conductivity_values))
    assert np.all(conductivity_values >= 1.0e-5)
    assert np.all(conductivity_values <= 8.64e-5)
    assert np.any(conductivity_values < 8.64e-5)
    assert loaded.metadata["hydraulic_properties"]["conductivity"]["missing_zone_keys"] == []


def loaded_metadata_files(bundle_dir: Path) -> dict[str, str | None]:
    metadata = json.loads((bundle_dir / "metadata.json").read_text(encoding="utf-8"))
    return dict(metadata.get("files", {}))
