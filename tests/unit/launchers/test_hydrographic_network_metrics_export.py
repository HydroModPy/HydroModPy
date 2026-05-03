from __future__ import annotations

import uuid
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.analysis.comparison.exports import (
    write_hydrographic_network_metrics_export,
    write_simulated_active_network_distance_metrics_export,
    write_simulated_active_network_metrics_export,
    write_simulated_active_network_overlap_metrics_export,
)
from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
)


def _line_gdf(length_m: float) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(0.0, 0.0), (float(length_m), 0.0)])],
        crs="EPSG:2154",
    )


def _cell_mesh(n_cells: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    vertices = []
    for x in range(n_cells + 1):
        vertices.append([float(x), 0.0, 0.0])
        vertices.append([float(x), 1.0, 0.0])
    face_node_connectivity = []
    for cell in range(n_cells):
        lower_left = 2 * cell
        lower_right = 2 * (cell + 1)
        upper_right = lower_right + 1
        upper_left = lower_left + 1
        face_node_connectivity.append([lower_left, lower_right, upper_right, upper_left])
    return (
        np.asarray(vertices, dtype="float64"),
        np.asarray(face_node_connectivity, dtype="int32"),
        np.array([1.0, 0.0], dtype="float64"),
    )


def _write_simulation_config(path: Path, workspace_root: Path) -> None:
    path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "",
                "[workspace]",
                f'root = "{workspace_root.as_posix()}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _register_completed_run(
    workspace_root: Path,
    *,
    reference_length_m: float | None,
    generated_length_m: float | None,
    reference_gdf: gpd.GeoDataFrame | None = None,
    generated_gdf: gpd.GeoDataFrame | None = None,
    accumulation_flux: list[np.ndarray] | None = None,
    flow_regime: str | None = None,
) -> tuple[Path, str]:
    config_path = workspace_root.parent / f"run_{uuid.uuid4().hex[:8]}.toml"
    _write_simulation_config(config_path, workspace_root)

    catalog = SimulationCatalog(workspace_root)
    sim_id = str(uuid.uuid4())
    n_cells = (
        int(np.asarray(accumulation_flux[0]).size)
        if accumulation_flux is not None and accumulation_flux
        else 2
    )
    reg = catalog.register_simulation(
        sim_id,
        project="demo_compare",
        solver="modflow6",
        name="network_demo",
        n_cells=n_cells,
        n_layers=1,
        n_timesteps=(len(accumulation_flux) if accumulation_flux is not None else None),
        flow_regime=flow_regime,
    )
    if reg.zarr is not None:
        reg.zarr.close()
    if reference_gdf is not None:
        catalog.write_geographic_feature(
            sim_id,
            HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
            reference_gdf,
        )
    elif reference_length_m is not None:
        catalog.write_geographic_feature(
            sim_id,
            HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
            _line_gdf(reference_length_m),
        )
    if generated_gdf is not None:
        catalog.write_geographic_feature(
            sim_id,
            HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
            generated_gdf,
        )
    elif generated_length_m is not None:
        catalog.write_geographic_feature(
            sim_id,
            HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
            _line_gdf(generated_length_m),
        )
    if accumulation_flux is not None:
        sz = catalog.open_zarr(sim_id)
        vertices, face_node_connectivity, z_interfaces = _cell_mesh(n_cells)
        sz.write_mesh(vertices, face_node_connectivity, z_interfaces)
        mesh = sz.root.require_group("mesh")
        n_cells = int(np.asarray(accumulation_flux[0]).size)
        mesh.create_array(
            "surface_top",
            data=np.ones(n_cells, dtype="float64"),
            overwrite=True,
        )
        for timestep, values in enumerate(accumulation_flux):
            sz.write_field(
                "accumulation_flux",
                timestep,
                np.asarray(values, dtype="float64"),
                n_timesteps=len(accumulation_flux) if timestep == 0 else None,
                subgroup="derived",
            )
    catalog.finalize(sim_id, "completed", 1.0)
    catalog.close()
    return config_path, sim_id


def test_write_hydrographic_network_metrics_export_writes_csv(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    config_path, sim_id = _register_completed_run(
        workspace_root,
        reference_length_m=1000.0,
        generated_length_m=800.0,
    )

    artifacts, rows = write_hydrographic_network_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        variant_summaries=[
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
        tolerance_m=0.0,
    )

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "hydrographic_network_metrics_csv"
    assert Path(artifacts[0]["path"]).exists()
    assert len(rows) == 1
    row = rows[0]
    assert row["comparison_id"] == "demo_compare"
    assert row["variant_id"] == "mf6_demo"
    assert row["reference_total_length_m"] == pytest.approx(1000.0)
    assert row["candidate_total_length_m"] == pytest.approx(800.0)
    assert row["reference_coverage_ratio"] == pytest.approx(0.8)
    assert row["candidate_match_ratio"] == pytest.approx(1.0)


def test_write_hydrographic_network_metrics_export_skips_missing_networks(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    config_path, sim_id = _register_completed_run(
        workspace_root,
        reference_length_m=1000.0,
        generated_length_m=None,
    )

    artifacts, rows = write_hydrographic_network_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        variant_summaries=[
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
        tolerance_m=0.0,
    )

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "hydrographic_network_metrics_skipped_json"
    assert Path(str(artifacts[0]["path"])).exists()
    assert rows == []

    payload = Path(str(artifacts[0]["path"])).read_text(encoding="utf-8")
    assert "missing_required_roles" in payload
    assert "reference" in payload


def test_write_hydrographic_network_metrics_export_reports_partial_skips(
    tmp_path: Path,
) -> None:
    workspace_ok = tmp_path / "workspace_ok"
    config_path_ok, sim_id_ok = _register_completed_run(
        workspace_ok,
        reference_length_m=1000.0,
        generated_length_m=800.0,
    )
    workspace_missing = tmp_path / "workspace_missing"
    config_path_missing, sim_id_missing = _register_completed_run(
        workspace_missing,
        reference_length_m=1000.0,
        generated_length_m=None,
    )

    artifacts, rows = write_hydrographic_network_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        variant_summaries=[
            {
                "id": "mf6_ok",
                "label": "MF6 ok",
                "solver": "modflow6",
                "mesh_mode": "structured",
                "config_path": str(config_path_ok),
                "run_folder": str(tmp_path / "run_ok"),
                "sim_id": sim_id_ok,
                "run_name": "network_demo",
                "status": "completed",
            },
            {
                "id": "mf6_missing",
                "label": "MF6 missing",
                "solver": "modflow6",
                "mesh_mode": "structured",
                "config_path": str(config_path_missing),
                "run_folder": str(tmp_path / "run_missing"),
                "sim_id": sim_id_missing,
                "run_name": "network_demo",
                "status": "completed",
            },
        ],
        tolerance_m=0.0,
    )

    artifact_kinds = {item["kind"] for item in artifacts}
    assert "hydrographic_network_metrics_csv" in artifact_kinds
    assert "hydrographic_network_metrics_skipped_json" in artifact_kinds
    assert len(rows) == 1


def test_write_simulated_active_network_metrics_export_writes_csv(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    config_path, sim_id = _register_completed_run(
        workspace_root,
        reference_length_m=None,
        generated_length_m=None,
        accumulation_flux=[
            np.array([0.0, 2.0, 0.0], dtype="float64"),
            np.array([1.0, 2.0, 0.0], dtype="float64"),
            np.array([0.0, 2.0, 4.0], dtype="float64"),
        ],
    )

    artifacts, rows = write_simulated_active_network_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        variant_summaries=[
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
    assert artifacts[0]["kind"] == "simulated_active_network_metrics_csv"
    assert Path(str(artifacts[0]["path"])).exists()
    assert len(rows) == 1
    row = rows[0]
    assert row["variant_id"] == "mf6_demo"
    assert row["source_variable"] == "accumulation_flux"
    assert row["catchment_cell_count"] == 3
    assert row["active_cell_count_mean"] == pytest.approx(5.0 / 3.0)
    assert row["drainage_density_mean_pct"] == pytest.approx(100.0 * 5.0 / 9.0)
    assert row["persistent_cell_count"] == 1
    assert row["always_active_cell_count"] == 1


def test_write_simulated_active_network_metrics_export_reports_missing_field(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    config_path, sim_id = _register_completed_run(
        workspace_root,
        reference_length_m=None,
        generated_length_m=None,
    )

    artifacts, rows = write_simulated_active_network_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        variant_summaries=[
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
    assert artifacts[0]["kind"] == "simulated_active_network_metrics_skipped_json"
    assert Path(str(artifacts[0]["path"])).exists()
    assert rows == []
    payload = Path(str(artifacts[0]["path"])).read_text(encoding="utf-8")
    assert "simulated_active_metrics_failed" in payload
    assert "accumulation_flux" in payload


def test_write_simulated_active_network_overlap_metrics_export_writes_csv(
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

    artifacts, rows = write_simulated_active_network_overlap_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        variant_summaries=[
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
    assert artifacts[0]["kind"] == "simulated_active_network_overlap_metrics_csv"
    assert Path(str(artifacts[0]["path"])).exists()
    assert len(rows) == 1
    row = rows[0]
    assert row["variant_id"] == "mf6_demo"
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
        variant_summaries=[
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
    assert row["variant_id"] == "mf6_demo"
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
        variant_summaries=[
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
        variant_summaries=[
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
