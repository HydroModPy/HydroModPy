from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy_annex.distribution.mesh_bundle_viewer import (
    load_mesh_bundle_viewer_config_from_toml,
    run_mesh_bundle_viewer_from_toml,
)


def _write_bundle_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _write_minimal_bundle(bundle_dir: Path) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "mesh_2d.msh").write_text("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n", encoding="utf-8")
    (bundle_dir / "metadata.json").write_text(
        json.dumps(
            {
                "bundle_schema_version": "mesh_catchment_bundle_v1",
                "crs": "EPSG:2154",
                "constraints_mode": "geology_rivers",
                "geology": {
                    "available": True,
                    "zone_keys": ["granite", "schist"],
                },
                "files": {"mesh": "mesh_2d.msh"},
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle_dir / "mesh_summary.json").write_text(
        json.dumps({"constraints_mode": "geology_rivers"}, indent=2, ensure_ascii=True)
        + "\n",
        encoding="utf-8",
    )
    _write_bundle_csv(
        bundle_dir / "nodes.csv",
        "node_id,x,y,z_top",
        [
            "0,0.0,0.0,10.0",
            "1,1.0,0.0,12.0",
            "2,1.0,1.0,14.0",
            "3,0.0,1.0,16.0",
        ],
    )
    _write_bundle_csv(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,geology_code,geology_key",
        [
            "0,triangle,0,1,2,,0.666667,0.333333,0.5,12.0,12.0,1,granite",
            "1,triangle,0,2,3,,0.333333,0.666667,0.5,14.0,13.0,2,schist",
        ],
    )
    _write_bundle_csv(
        bundle_dir / "edges.csv",
        "edge_id,node_a,node_b,cell_a,cell_b,length_m,edge_kind,is_river,geology_a_key,geology_b_key",
        [
            "0,0,1,0,,1.0,boundary,false,granite,",
            "1,1,2,0,,1.0,boundary,true,granite,",
            "2,0,2,0,1,1.414214,geology_interface,false,granite,schist",
            "3,2,3,1,,1.0,boundary,false,schist,",
            "4,0,3,1,,1.0,boundary,false,schist,",
        ],
    )
    _write_bundle_csv(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        [
            "0,granite,1.0",
            "1,schist,1.0",
        ],
    )


def test_load_mesh_bundle_viewer_config_from_toml(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    _write_minimal_bundle(bundle_dir)

    config_path = tmp_path / "viewer.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_bundle_viewer]",
                'bundle_dir = "bundle"',
                'output_figure = "outputs/view.png"',
                "show_plot = false",
                "",
                "[mesh_bundle_viewer.plot]",
                'color_by = "geology_key"',
                "figsize = [10.0, 8.0]",
                "dpi = 150",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = load_mesh_bundle_viewer_config_from_toml(config_path)
    assert cfg.bundle_dir == bundle_dir.resolve()
    assert cfg.output_figure == (tmp_path / "outputs" / "view.png").resolve()
    assert cfg.plot.color_by == "geology_key"
    assert cfg.plot.figsize == (10.0, 8.0)


def test_run_mesh_bundle_viewer_from_toml_writes_outputs(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    _write_minimal_bundle(bundle_dir)

    config_path = tmp_path / "viewer.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_bundle_viewer]",
                'bundle_dir = "bundle"',
                'output_figure = "outputs/view.png"',
                'output_summary_json = "outputs/view_summary.json"',
                "show_plot = false",
                "",
                "[mesh_bundle_viewer.plot]",
                'color_by = "geology_key"',
                'cmap = "tab20"',
                "show_river_edges = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = run_mesh_bundle_viewer_from_toml(config_path)

    figure_path = tmp_path / "outputs" / "view.png"
    summary_path = tmp_path / "outputs" / "view_summary.json"
    assert figure_path.exists()
    assert summary_path.exists()
    assert summary["n_cells"] == 2
    assert summary["river_edge_count"] == 1
    assert summary["geology_available"] is True
    assert summary["topography_render_mode"] == "node_continuous"


def test_load_mesh_bundle_viewer_config_rejects_invalid_color_field(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    _write_minimal_bundle(bundle_dir)

    config_path = tmp_path / "viewer_invalid.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_bundle_viewer]",
                'bundle_dir = "bundle"',
                "",
                "[mesh_bundle_viewer.plot]",
                'color_by = "unknown_field"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="color_by"):
        load_mesh_bundle_viewer_config_from_toml(config_path)
