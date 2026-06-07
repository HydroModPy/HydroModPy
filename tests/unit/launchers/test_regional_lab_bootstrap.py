from __future__ import annotations

import csv
import json
from pathlib import Path

from hydromodpy.analysis.testbed.child_artifacts import extract_comparison_child_artifacts
from hydromodpy.analysis.testbed.regional_lab_bootstrap import build_site_catalog_from_outlet_table


def test_regional_lab_extracts_simulation_comparison_child_artifacts(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "compare_case.toml"
    comparison_root = tmp_path / "comparison_outputs"
    comparison_root.mkdir(parents=True, exist_ok=True)
    (comparison_root / "comparison_manifest.json").write_text(
        json.dumps(
            {
                "comparison_id": "demo_compare",
                "reference_simulation": "reference",
                "wall_time_seconds": 12.5,
                "n_metric_rows": 3,
                "n_difference_rows": 2,
                "n_observable_rows": 1,
                "simulations": [
                    {"id": "reference", "status": "completed"},
                    {"id": "candidate", "status": "failed"},
                ],
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (comparison_root / "comparison_metrics.json").write_text(
        json.dumps(
            {
                "summary": [
                    {"observable": "head", "rmse": 1.5, "mae": 0.8},
                    {"observable": "flow", "rmse": 2.0, "mae": 1.1},
                ],
                "differences": [{"observable": "head"}, {"observable": "flow"}],
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_compare"',
                f'output_root = "{comparison_root.as_posix()}"',
                "",
                "[[comparison.simulation]]",
                'id = "reference"',
                'run_folder = "runs/reference"',
                "",
                "[[comparison.observable]]",
                'name = "head"',
                'variable = "head"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = extract_comparison_child_artifacts(config_path)

    assert artifacts["child_artifact_kind"] == "comparison"
    assert artifacts["child_artifact_status"] == "resolved"
    assert artifacts["child_comparison_id"] == "demo_compare"
    assert artifacts["child_reference_simulation"] == "reference"
    assert artifacts["child_wall_time_seconds"] == 12.5
    assert artifacts["child_simulation_count"] == 2
    assert artifacts["child_completed_simulation_count"] == 1
    assert artifacts["child_failed_simulation_count"] == 1
    assert artifacts["child_summary_max_rmse"] == 2.0
    assert artifacts["child_summary_max_mae"] == 1.1


def test_regional_lab_extracts_canonical_comparison_child_artifacts(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "compare_case.toml"
    comparison_root = tmp_path / "comparison_outputs"
    comparison_root.mkdir(parents=True, exist_ok=True)
    (comparison_root / "comparison_manifest.json").write_text(
        json.dumps(
            {
                "comparison_id": "demo_compare",
                "reference_simulation": "reference",
                "wall_time_seconds": 12.5,
                "n_metric_rows": 3,
                "n_difference_rows": 2,
                "n_observable_rows": 1,
                "simulations": [
                    {"id": "reference", "status": "completed"},
                    {"id": "candidate", "status": "failed"},
                ],
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (comparison_root / "comparison_metrics.json").write_text(
        json.dumps(
            {
                "summary": [{"observable": "head", "rmse": 1.5, "mae": 0.8}],
                "differences": [{"observable": "head"}],
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "demo_compare"',
                f'output_root = "{comparison_root.as_posix()}"',
                "",
                "[[comparison.simulation]]",
                'id = "reference"',
                'run_folder = "runs/reference"',
                "",
                "[[comparison.observable]]",
                'name = "head"',
                'variable = "head"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = extract_comparison_child_artifacts(config_path)

    assert artifacts["child_artifact_kind"] == "comparison"
    assert artifacts["child_artifact_status"] == "resolved"
    assert artifacts["child_comparison_id"] == "demo_compare"
    assert artifacts["child_reference_simulation"] == "reference"
    assert artifacts["child_summary_max_rmse"] == 1.5


def test_regional_lab_bootstrap_catalog_merges_manifest(tmp_path: Path) -> None:
    outlets_path = tmp_path / "outlets.csv"
    outlets_path.write_text(
        "\n".join(
            [
                "outlet_id,x_outlet,y_outlet,area_km2",
                "2,100.0,200.0,98.5",
                "3,110.0,210.0,101.2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "mesh_manifest.csv"
    manifest_path.write_text(
        "\n".join(
            [
                "outlet_id,catch_name,status,x_outlet,y_outlet,output_mesh,output_summary_json,output_figure,output_figure_regional,error",
                "2,headwater_2,ok,100.0,200.0,C:/tmp/mesh_2.msh,C:/tmp/summary_2.json,,,",
                "3,headwater_3,failed,110.0,210.0,,,,boom",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "site_catalog_bootstrapped.csv"

    summary = build_site_catalog_from_outlet_table(
        outlets_table_path=outlets_path,
        output_path=output_path,
        cluster_id="headwater_100km2",
        cluster_label="Headwater 100 km2",
        cluster_family="headwater",
        cluster_scale="100km2",
        region_id="brittany",
        source_selection_id="scan_headwater_100km2",
        manifest_csv=manifest_path,
        default_tags=("regional_screening",),
    )

    assert summary["site_count"] == 2
    rows = output_path.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("site_id,site_label,cluster_id")
    assert "headwater_100km2_outlet_2" in rows[1]
    assert "mesh_ready" in rows[1]
    assert "C:/tmp" in rows[1]


def test_regional_lab_bootstrap_catalog_scans_mesh_run_root(tmp_path: Path) -> None:
    outlets_path = tmp_path / "outlets.csv"
    outlets_path.write_text(
        "\n".join(
            [
                "outlet_id,x_outlet,y_outlet,area_km2",
                "3,100.0,200.0,10.2",
                "4,110.0,210.0,10.1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    mesh_run_root = tmp_path / "mesh_runs"
    bundle_dir = mesh_run_root / "mesh_outlet_3" / "mesh_catchment_outlet_3_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (mesh_run_root / "mesh_outlet_3" / "mesh_catchment_outlet_3.msh").write_text(
        "", encoding="utf-8"
    )
    (mesh_run_root / "mesh_outlet_3" / "mesh_catchment_outlet_3_summary.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (mesh_run_root / "mesh_outlet_3" / "mesh_catchment_outlet_3.png").write_text(
        "", encoding="utf-8"
    )
    (mesh_run_root / "mesh_outlet_3" / "mesh_catchment_outlet_3_regional.png").write_text(
        "",
        encoding="utf-8",
    )

    output_path = tmp_path / "site_catalog_bootstrapped.csv"
    summary = build_site_catalog_from_outlet_table(
        outlets_table_path=outlets_path,
        output_path=output_path,
        cluster_id="s3_10km2",
        cluster_label="S3 10 km2",
        cluster_family="s3",
        cluster_scale="10km2",
        region_id="brittany",
        source_selection_id="scan_s3_10km2",
        mesh_run_root=mesh_run_root,
    )

    assert summary["mesh_run_root_scanned"] is True
    rows = output_path.read_text(encoding="utf-8").splitlines()
    assert "mesh_ready" in rows[1]
    assert "discovered" in rows[1]
    assert "mesh_catchment_outlet_3_bundle" in rows[1]


def test_regional_lab_bootstrap_catalog_inspects_bundle_readiness(
    tmp_path: Path,
) -> None:
    outlets_path = tmp_path / "outlets.csv"
    outlets_path.write_text(
        "\n".join(
            [
                "outlet_id,x_outlet,y_outlet,area_km2",
                "3,100.0,200.0,10.2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    mesh_run_root = tmp_path / "mesh_runs"
    mesh_dir = mesh_run_root / "mesh_outlet_3"
    bundle_dir = mesh_dir / "mesh_catchment_outlet_3_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (mesh_dir / "mesh_catchment_outlet_3.msh").write_text("", encoding="utf-8")
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
                "0,triangle,0,1,2,,1.0,2.0,3.0,100.0,100.0,50.0,50.0,1,1,1.0e-6,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "hydraulic_properties": {
                    "storage_coefficient": {
                        "default_value": None,
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "site_catalog_bootstrapped.csv"
    build_site_catalog_from_outlet_table(
        outlets_table_path=outlets_path,
        output_path=output_path,
        cluster_id="s3_10km2",
        cluster_label="S3 10 km2",
        cluster_family="s3",
        cluster_scale="10km2",
        region_id="brittany",
        source_selection_id="scan_s3_10km2",
        mesh_run_root=mesh_run_root,
    )

    with output_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["mesh_bundle_dir"].endswith("mesh_catchment_outlet_3_bundle")
    assert rows[0]["bundle_cell_count"] == "1"
    assert rows[0]["bundle_missing_top_centroid_count"] == "0"
    assert rows[0]["bundle_missing_storage_coefficient_count"] == "1"
    assert rows[0]["bundle_boussinesq_steady_ready"] == "true"
    assert rows[0]["bundle_boussinesq_transient_ready"] == "false"
    assert "boussinesq_steady_ready" in rows[0]["tags"]


def test_regional_lab_bootstrap_catalog_infers_bundle_dir_from_manifest_mesh_path(
    tmp_path: Path,
) -> None:
    outlets_path = tmp_path / "outlets.csv"
    outlets_path.write_text(
        "\n".join(
            [
                "outlet_id,x_outlet,y_outlet,area_km2",
                "27,100.0,200.0,98.5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    mesh_dir = tmp_path / "mesh_gallery_outlet_27"
    bundle_dir = mesh_dir / "mesh_catchment_outlet_27_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = mesh_dir / "mesh_catchment_outlet_27.msh"
    mesh_path.write_text("", encoding="utf-8")
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,z_bottom_centroid,z_bottom_mean,geology_code,geology_key,hydraulic_conductivity_m_s,storage_coefficient",
                "0,triangle,0,1,2,,1.0,2.0,3.0,100.0,100.0,50.0,50.0,1,1,1.0e-6,0.15",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "metadata.json").write_text("{}\n", encoding="utf-8")
    manifest_path = tmp_path / "mesh_manifest.csv"
    manifest_path.write_text(
        "\n".join(
            [
                "outlet_id,catch_name,status,x_outlet,y_outlet,output_mesh,output_summary_json,output_figure,output_figure_regional,error",
                f"27,headwater_27,ok,100.0,200.0,{mesh_path.as_posix()},,,,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "site_catalog_bootstrapped.csv"

    build_site_catalog_from_outlet_table(
        outlets_table_path=outlets_path,
        output_path=output_path,
        cluster_id="headwater_100km2",
        cluster_label="Headwater 100 km2",
        cluster_family="headwater",
        cluster_scale="100km2",
        region_id="brittany",
        source_selection_id="scan_headwater_100km2",
        manifest_csv=manifest_path,
    )

    with output_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["mesh_bundle_dir"] == str(bundle_dir.resolve())
    assert rows[0]["bundle_boussinesq_steady_ready"] == "true"
    assert rows[0]["bundle_boussinesq_transient_ready"] == "true"
    assert "boussinesq_transient_ready" in rows[0]["tags"]
