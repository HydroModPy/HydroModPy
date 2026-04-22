from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tools.mesh_bundle_viewer.loading import (
    get_toml_parameter_descriptions,
    load_toml_config,
)
from tools.mesh_bundle_viewer.loading.toml_loader import _looks_like_windows_absolute_path
from tools.mesh_bundle_viewer.runner.visualization_runner import (
    run_visualization_from_toml as run_root_mesh_visualization_from_toml,
)
from tools.mesh_bundle_viewer.schema import (
    DEFAULT_CONFIG_FILENAME as MESH_DEFAULT_CONFIG_FILENAME,
)
from tools.mesh_bundle_viewer.runner import run_visualization_from_toml


def _ecrire_csv_bundle(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _ecrire_bundle_minimal(bundle_dir: Path) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "mesh_2d.msh").write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n",
        encoding="utf-8",
    )
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
        json.dumps({"constraints_mode": "geology_rivers"}, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    _ecrire_csv_bundle(
        bundle_dir / "nodes.csv",
        "node_id,x,y,z_top",
        [
            "0,0.0,0.0,10.0",
            "1,1.0,0.0,12.0",
            "2,1.0,1.0,14.0",
            "3,0.0,1.0,16.0",
        ],
    )
    _ecrire_csv_bundle(
        bundle_dir / "cells.csv",
        "cell_id,geom_type,n0,n1,n2,n3,centroid_x,centroid_y,area_m2,z_top_centroid,z_top_mean,geology_code,geology_key",
        [
            "0,triangle,0,1,2,,0.666667,0.333333,0.5,12.0,12.0,1,granite",
            "1,triangle,0,2,3,,0.333333,0.666667,0.5,14.0,13.0,2,schist",
        ],
    )
    _ecrire_csv_bundle(
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
    _ecrire_csv_bundle(
        bundle_dir / "cell_geology_fractions.csv",
        "cell_id,geology_key,fraction",
        [
            "0,granite,1.0",
            "1,schist,1.0",
        ],
    )


def test_load_toml_config(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    _ecrire_bundle_minimal(bundle_dir)

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_distribution]",
                'bundle_dir = "bundle"',
                'figure_output_path = "outputs/vue.png"',
                "show_window = false",
                "",
                "[mesh_distribution.plot]",
                'color_field = "geology_key"',
                "figure_size = [10.0, 8.0]",
                "dpi = 150",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = load_toml_config(config_path)
    assert config.bundle_dir == bundle_dir.resolve()
    assert config.figure_output_path == (tmp_path / "outputs" / "vue.png").resolve()
    assert config.plot.color_field == "geology_key"
    assert config.plot.figure_size == (10.0, 8.0)


def test_run_visualization_from_toml_writes_outputs(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    _ecrire_bundle_minimal(bundle_dir)

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_distribution]",
                'bundle_dir = "bundle"',
                'figure_output_path = "outputs/vue.png"',
                'summary_output_path = "outputs/resume.json"',
                "show_window = false",
                "",
                "[mesh_distribution.plot]",
                'color_field = "geology_key"',
                'color_map = "tab20"',
                "show_river_edges = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = run_visualization_from_toml(config_path)

    assert (tmp_path / "outputs" / "vue.png").exists()
    assert (tmp_path / "outputs" / "resume.json").exists()
    assert summary["cell_count"] == 2
    assert summary["river_edge_count"] == 1
    assert summary["geology_available"] is True
    assert summary["hydraulic_properties_available"] is False
    assert summary["hydraulic_conductivity_cell_count"] == 0
    assert summary["storage_coefficient_cell_count"] == 0
    assert summary["topography_render_mode"] == "continuous_on_nodes"


def test_load_toml_config_rejects_invalid_color_field(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    _ecrire_bundle_minimal(bundle_dir)

    config_path = tmp_path / "config_invalide.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_distribution]",
                'bundle_dir = "bundle"',
                "",
                "[mesh_distribution.plot]",
                'color_field = "champ_inconnu"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="color_field"):
        load_toml_config(config_path)


def test_load_toml_config_rejects_unknown_root_key(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    _ecrire_bundle_minimal(bundle_dir)

    config_path = tmp_path / "config_unknown_root.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_distribution]",
                'bundle_dir = "bundle"',
                "unexpected_root_key = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown keys"):
        load_toml_config(config_path)


def test_load_toml_config_rejects_unknown_plot_key(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    _ecrire_bundle_minimal(bundle_dir)

    config_path = tmp_path / "config_unknown_plot.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_distribution]",
                'bundle_dir = "bundle"',
                "",
                "[mesh_distribution.plot]",
                'color_field = "geology_key"',
                "unexpected_plot_key = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown keys"):
        load_toml_config(config_path)


def test_distribution_mesh_default_config_filename_is_portable() -> None:
    assert MESH_DEFAULT_CONFIG_FILENAME == "config_example.toml"


def test_windows_absolute_path_detection_is_supported() -> None:
    assert _looks_like_windows_absolute_path(r"C:\codes\bundle")
    assert _looks_like_windows_absolute_path("D:/mesh/bundle")
    assert not _looks_like_windows_absolute_path("../sample_bundle")


def test_run_visualization_from_toml_without_bundle_reader(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    _ecrire_bundle_minimal(bundle_dir)

    config_path = tmp_path / "config_without_reader.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_distribution]",
                'bundle_dir = "bundle"',
                'figure_output_path = "outputs/vue_internal_reader.png"',
                'summary_output_path = "outputs/resume_internal_reader.json"',
                "show_window = false",
                "",
                "[mesh_distribution.plot]",
                'color_field = "geology_key"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = run_visualization_from_toml(config_path)

    assert (tmp_path / "outputs" / "vue_internal_reader.png").exists()
    assert summary["cell_count"] == 2
    assert summary["geology_available"] is True


def test_root_mesh_package_reads_bundle_without_bundle_reader(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    _ecrire_bundle_minimal(bundle_dir)

    config_path = tmp_path / "config_root_mesh.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_distribution]",
                'bundle_dir = "bundle"',
                'figure_output_path = "outputs/vue_root_mesh.png"',
                'summary_output_path = "outputs/resume_root_mesh.json"',
                "show_window = false",
                "",
                "[mesh_distribution.plot]",
                'color_field = "geology_key"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = run_root_mesh_visualization_from_toml(config_path)

    assert (tmp_path / "outputs" / "vue_root_mesh.png").exists()
    assert summary["cell_count"] == 2
    assert summary["geology_available"] is True


def test_root_mesh_package_ignores_bundle_reader_file(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    _ecrire_bundle_minimal(bundle_dir)
    (bundle_dir / "reader.py").write_text(
        "raise RuntimeError('bundle reader should not be imported')\n",
        encoding="utf-8",
    )

    config_path = tmp_path / "config_root_mesh_ignore_bundle_reader.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_distribution]",
                'bundle_dir = "bundle"',
                'figure_output_path = "outputs/vue_ignore_bundle_reader.png"',
                'summary_output_path = "outputs/resume_ignore_bundle_reader.json"',
                "show_window = false",
                "",
                "[mesh_distribution.plot]",
                'color_field = "geology_key"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = run_root_mesh_visualization_from_toml(config_path)

    assert (tmp_path / "outputs" / "vue_ignore_bundle_reader.png").exists()
    assert summary["cell_count"] == 2


def test_toml_schema_parameter_descriptions_cover_public_keys() -> None:
    descriptions = get_toml_parameter_descriptions()

    assert "[mesh_distribution].bundle_dir" in descriptions
    assert "bundle directory" in descriptions["[mesh_distribution].bundle_dir"]

    assert "[mesh_distribution.plot].color_field" in descriptions
    assert "Field used" in descriptions["[mesh_distribution.plot].color_field"]

    assert "[mesh_distribution.plot].show_river_edges" in descriptions
    assert "rivers" in descriptions["[mesh_distribution.plot].show_river_edges"]


def test_run_visualization_from_toml_accepts_missing_hydraulic_field(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "bundle"
    _ecrire_bundle_minimal(bundle_dir)

    config_path = tmp_path / "config_hydraulic.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_distribution]",
                'bundle_dir = "bundle"',
                'figure_output_path = "outputs/vue_hydraulic.png"',
                'summary_output_path = "outputs/resume_hydraulic.json"',
                "show_window = false",
                "",
                "[mesh_distribution.plot]",
                'color_field = "hydraulic_conductivity_m_s"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = run_visualization_from_toml(config_path)

    assert (tmp_path / "outputs" / "vue_hydraulic.png").exists()
    assert summary["color_field"] == "hydraulic_conductivity_m_s"
    assert summary["hydraulic_properties_available"] is False
    assert summary["hydraulic_conductivity_available"] is False
    assert summary["hydraulic_conductivity_cell_count"] == 0


@pytest.mark.allow_subprocess
def test_python_module_mesh_bundle_viewer_runs_from_distributed_folder(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "sample_bundle"
    _ecrire_bundle_minimal(bundle_dir)

    distribution_root = tmp_path / "distribution_package"
    mesh_source_dir = Path(__file__).resolve().parents[3] / "tools" / "mesh_bundle_viewer"
    mesh_target_dir = distribution_root / "mesh_bundle_viewer"
    shutil.copytree(mesh_source_dir, mesh_target_dir)

    config_path = distribution_root / "config_distributed.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mesh_distribution]",
                'bundle_dir = "../sample_bundle"',
                'figure_output_path = "outputs/vue_dist.png"',
                'summary_output_path = "outputs/resume_dist.json"',
                "show_window = false",
                "",
                "[mesh_distribution.plot]",
                'color_field = "hydraulic_conductivity_m_s"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mesh_bundle_viewer",
            "--config",
            str(config_path),
        ],
        cwd=str(distribution_root),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (distribution_root / "outputs" / "vue_dist.png").exists()
    summary = json.loads(completed.stdout)
    assert summary["hydraulic_conductivity_cell_count"] == 0
    assert summary["hydraulic_properties_available"] is False


@pytest.mark.allow_subprocess
def test_python_module_mesh_bundle_viewer_runs_with_default_example_bundle(
    tmp_path: Path,
) -> None:
    distribution_root = tmp_path / "rbflow_like_package"
    mesh_source_dir = Path(__file__).resolve().parents[3] / "tools" / "mesh_bundle_viewer"
    examples_source_dir = (
        Path(__file__).resolve().parents[3] / "examples" / "projects" / "08_mesh_viewer"
    )
    mesh_target_dir = distribution_root / "mesh_bundle_viewer"
    examples_target_dir = distribution_root / "examples" / "projects" / "08_mesh_viewer"
    shutil.copytree(mesh_source_dir, mesh_target_dir)
    shutil.copytree(examples_source_dir, examples_target_dir)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mesh_bundle_viewer",
        ],
        cwd=str(distribution_root),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (distribution_root / "outputs" / "mesh_viewer" / "apercu_maillage.png").exists()
    assert (distribution_root / "outputs" / "mesh_viewer" / "resume_apercu_maillage.json").exists()
    summary = json.loads(completed.stdout)
    assert summary["cell_count"] == 2
    assert summary["geology_available"] is True
