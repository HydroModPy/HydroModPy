from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.analysis.comparison.exports import (
    write_release_flux_network_distance_metrics_export,
    write_release_flux_network_overlap_metrics_export,
    write_simulated_active_network_distance_metrics_export,
    write_simulated_active_network_metrics_export,
    write_simulated_active_network_overlap_metrics_export,
)

from ._hydrographic_network_metrics_export_builders import (
    _register_completed_active_network_run,
    _register_completed_run,
)


def test_write_simulated_active_network_metrics_export_writes_csv(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    config_path, sim_id = _register_completed_active_network_run(workspace_root)

    artifacts, rows = write_simulated_active_network_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=[
            {
                "id": "mf6_demo",
                "label": "MF6 demo",
                "solver": "modflow6",
                "mesh_mode": "structured",
                "config_path": str(config_path),
                "run_folder": str(tmp_path / "run_folder"),
                "sim_id": sim_id,
                "run_name": "active_network_demo",
                "status": "completed",
            }
        ],
    )

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "simulated_active_network_metrics_csv"
    assert Path(artifacts[0]["path"]).exists()
    assert len(rows) == 1
    assert rows[0]["catchment_cell_count"] == 3
    assert rows[0]["active_cell_count_max"] == 1
    assert rows[0]["always_active_cell_count"] == 1
    assert rows[0]["drainage_density_last_pct"] == pytest.approx(100.0 / 3.0)


def test_write_simulated_active_network_overlap_metrics_export_writes_csv(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    config_path, sim_id = _register_completed_active_network_run(workspace_root)

    artifacts, rows = write_simulated_active_network_overlap_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=[
            {
                "id": "mf6_demo",
                "label": "MF6 demo",
                "solver": "modflow6",
                "mesh_mode": "structured",
                "config_path": str(config_path),
                "run_folder": str(tmp_path / "run_folder"),
                "sim_id": sim_id,
                "run_name": "active_network_demo",
                "status": "completed",
            }
        ],
        buffer_m=0.0,
    )

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "simulated_active_network_overlap_metrics_csv"
    assert Path(artifacts[0]["path"]).exists()
    assert len(rows) == 1
    row = rows[0]
    assert row["simulation_id"] == "mf6_demo"
    assert row["network_role"] == "reference"
    assert row["source_variable"] == "accumulation_flux"
    assert row["mode"] == "persistent"
    assert row["catchment_cell_count"] == 3
    assert row["active_cell_count"] == 1
    assert row["network_cell_count"] == 1
    assert row["overlap_cell_count"] == 1
    assert row["missing_network_cell_count"] == 0
    assert row["extra_active_cell_count"] == 0
    assert row["network_coverage_ratio"] == pytest.approx(1.0)
    assert row["active_precision_ratio"] == pytest.approx(1.0)
    assert row["cell_f1_ratio"] == pytest.approx(1.0)
    assert row["cell_jaccard_ratio"] == pytest.approx(1.0)


def test_write_simulated_active_network_distance_metrics_export_writes_csv(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    reference_gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(1.25, 0.5), (1.75, 0.5)])],
        crs="EPSG:2154",
    )
    config_path, sim_id = _register_completed_run(
        workspace_root,
        reference_length_m=None,
        generated_length_m=None,
        reference_gdf=reference_gdf,
        accumulation_flux=[
            np.array([0.0, 2.0, 0.0], dtype="float64"),
            np.array([1.0, 2.0, 0.0], dtype="float64"),
            np.array([0.0, 2.0, 4.0], dtype="float64"),
        ],
    )

    artifacts, rows = write_simulated_active_network_distance_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=[
            {
                "id": "mf6_demo",
                "label": "MF6 demo",
                "solver": "modflow6",
                "mesh_mode": "structured",
                "config_path": str(config_path),
                "run_folder": str(tmp_path / "run_folder"),
                "sim_id": sim_id,
                "run_name": "network_demo",
                "status": "completed",
            }
        ],
        threshold=0.5,
        persistence_threshold=0.5,
    )

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "simulated_active_network_distance_metrics_csv"
    assert Path(str(artifacts[0]["path"])).exists()
    assert len(rows) == 1
    row = rows[0]
    assert row["simulation_id"] == "mf6_demo"
    assert row["network_role"] == "reference"
    assert row["mode"] == "persistent"
    assert row["distance_method"] == "planar_cell_centroid_to_network"
    assert row["active_cell_count"] == 1
    assert row["network_cell_count"] == 1
    assert row["sim_to_network_sample_count"] == 1
    assert row["network_to_sim_sample_count"] == 1
    assert row["sim_to_network_distance_mean_m"] == pytest.approx(0.0)
    assert row["network_to_sim_distance_mean_m"] == pytest.approx(0.0)
    assert row["bidirectional_distance_mean_m"] == pytest.approx(0.0)
    assert row["bidirectional_distance_absolute_difference_m"] == pytest.approx(0.0)
    assert row["planar_distance_ratio"] == pytest.approx(1.0)
    assert row["planar_distance_log10_ratio"] == pytest.approx(0.0)


def test_write_release_flux_network_overlap_metrics_export_writes_csv(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    reference_gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(1.25, 0.5), (1.75, 0.5)])],
        crs="EPSG:2154",
    )
    config_path, sim_id = _register_completed_run(
        workspace_root,
        reference_length_m=None,
        generated_length_m=None,
        reference_gdf=reference_gdf,
        release_flux=[
            np.array([0.0, 2.0, 0.0], dtype="float64"),
            np.array([1.0, 2.0, 0.0], dtype="float64"),
            np.array([0.0, 2.0, 4.0], dtype="float64"),
        ],
    )

    artifacts, rows = write_release_flux_network_overlap_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=[
            {
                "id": "bouss_demo",
                "label": "Boussinesq demo",
                "solver": "boussinesq",
                "mesh_mode": "unstructured",
                "config_path": str(config_path),
                "run_folder": str(tmp_path / "run_folder"),
                "sim_id": sim_id,
                "run_name": "network_demo",
                "status": "completed",
            }
        ],
        threshold=0.5,
        persistence_threshold=0.5,
        buffer_m=0.0,
    )

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "release_flux_network_overlap_metrics_csv"
    assert Path(str(artifacts[0]["path"])).exists()
    row = rows[0]
    assert row["simulation_id"] == "bouss_demo"
    assert row["source_variable"] == "release_flux"
    assert row["active_cell_count"] == 1
    assert row["network_cell_count"] == 1
    assert row["overlap_cell_count"] == 1
    assert row["cell_jaccard_ratio"] == pytest.approx(1.0)


def test_write_release_flux_network_distance_metrics_export_writes_raw_distances(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    reference_gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(1.25, 0.5), (1.75, 0.5)])],
        crs="EPSG:2154",
    )
    config_path, sim_id = _register_completed_run(
        workspace_root,
        reference_length_m=None,
        generated_length_m=None,
        reference_gdf=reference_gdf,
        release_flux=[
            np.array([0.0, 2.0, 0.0], dtype="float64"),
            np.array([1.0, 2.0, 0.0], dtype="float64"),
            np.array([0.0, 2.0, 4.0], dtype="float64"),
        ],
    )

    artifacts, rows = write_release_flux_network_distance_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=[
            {
                "id": "bouss_demo",
                "label": "Boussinesq demo",
                "solver": "boussinesq",
                "mesh_mode": "unstructured",
                "config_path": str(config_path),
                "run_folder": str(tmp_path / "run_folder"),
                "sim_id": sim_id,
                "run_name": "network_demo",
                "status": "completed",
            }
        ],
        threshold=0.5,
        persistence_threshold=0.5,
    )

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "release_flux_network_distance_metrics_csv"
    assert Path(str(artifacts[0]["path"])).exists()
    row = rows[0]
    assert row["simulation_id"] == "bouss_demo"
    assert row["source_variable"] == "release_flux"
    assert row["network_buffer_m"] == 0.0
    assert row["distance_method"] == "raw_planar_cell_centroid_to_network"
    assert row["active_cell_count"] == 1
    assert row["sim_to_network_distance_mean_m"] == pytest.approx(0.0)
    assert row["network_to_sim_distance_mean_m"] == pytest.approx(0.0)


def test_write_simulated_active_network_overlap_metrics_export_uses_steady_default(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    reference_gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(2.25, 0.5), (2.75, 0.5)])],
        crs="EPSG:2154",
    )
    config_path, sim_id = _register_completed_run(
        workspace_root,
        reference_length_m=None,
        generated_length_m=None,
        reference_gdf=reference_gdf,
        accumulation_flux=[
            np.array([0.0, 2.0, 0.0], dtype="float64"),
            np.array([0.0, 2.0, 0.0], dtype="float64"),
            np.array([0.0, 2.0, 4.0], dtype="float64"),
        ],
        flow_regime="steady",
    )

    _artifacts, rows = write_simulated_active_network_overlap_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=[
            {
                "id": "mf6_demo",
                "label": "MF6 demo",
                "solver": "modflow6",
                "mesh_mode": "structured",
                "config_path": str(config_path),
                "run_folder": str(tmp_path / "run_folder"),
                "sim_id": sim_id,
                "run_name": "network_demo",
                "status": "completed",
            }
        ],
        threshold=0.5,
        persistence_threshold=0.5,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["mode"] == "last"
    assert row["active_cell_count"] == 2
    assert row["network_cell_count"] == 1
    assert row["overlap_cell_count"] == 1
    assert row["network_coverage_ratio"] == pytest.approx(1.0)
    assert row["active_precision_ratio"] == pytest.approx(0.5)


def test_write_simulated_active_network_overlap_metrics_export_reports_missing_reference(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    config_path, sim_id = _register_completed_run(
        workspace_root,
        reference_length_m=None,
        generated_length_m=None,
        accumulation_flux=[
            np.array([0.0, 2.0, 0.0], dtype="float64"),
            np.array([1.0, 2.0, 0.0], dtype="float64"),
        ],
    )

    artifacts, rows = write_simulated_active_network_overlap_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=[
            {
                "id": "mf6_demo",
                "label": "MF6 demo",
                "solver": "modflow6",
                "mesh_mode": "structured",
                "config_path": str(config_path),
                "run_folder": str(tmp_path / "run_folder"),
                "sim_id": sim_id,
                "run_name": "network_demo",
                "status": "completed",
            }
        ],
    )

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "simulated_active_network_overlap_metrics_skipped_json"
    assert Path(str(artifacts[0]["path"])).exists()
    assert rows == []
    payload = Path(str(artifacts[0]["path"])).read_text(encoding="utf-8")
    assert "missing_vector_network_role" in payload
    assert "reference" in payload
