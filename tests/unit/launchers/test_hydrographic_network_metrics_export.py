from __future__ import annotations

import uuid
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.analysis.comparison.exports import (
    write_hydrographic_network_metrics_export,
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
) -> tuple[Path, str]:
    config_path = workspace_root.parent / f"run_{uuid.uuid4().hex[:8]}.toml"
    _write_simulation_config(config_path, workspace_root)

    catalog = SimulationCatalog(workspace_root)
    sim_id = str(uuid.uuid4())
    reg = catalog.register_simulation(
        sim_id,
        project="demo_compare",
        solver="modflow6",
        name="network_demo",
        n_cells=2,
        n_layers=1,
    )
    if reg.zarr is not None:
        reg.zarr.close()
    if reference_length_m is not None:
        catalog.write_geographic_feature(
            sim_id,
            HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
            _line_gdf(reference_length_m),
        )
    if generated_length_m is not None:
        catalog.write_geographic_feature(
            sim_id,
            HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
            _line_gdf(generated_length_m),
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
