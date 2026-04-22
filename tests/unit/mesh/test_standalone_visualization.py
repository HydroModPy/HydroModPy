from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from tools.mesh_bundle_viewer import (
    VISUALIZATION_SUMMARY_SCHEMA_VERSION,
    CatchmentMeshBundle,
    VisualizationSummary,
    build_visualization_summary_contract,
    load_toml_config,
    load_visualization_data,
)
from tools.mesh_bundle_viewer.reader import load_catchment_mesh_bundle


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _example_bundle_dir() -> Path:
    return _repo_root() / "examples" / "projects" / "08_mesh_viewer" / "sample_bundle"


def _example_config_path() -> Path:
    return _repo_root() / "examples" / "projects" / "08_mesh_viewer" / "config_example.toml"


def test_standalone_bundle_reader_uses_shared_bundle_contracts() -> None:
    bundle = load_catchment_mesh_bundle(_example_bundle_dir())

    assert isinstance(bundle, CatchmentMeshBundle)
    assert bundle.n_nodes > 0
    assert bundle.n_cells > 0
    assert bundle.mesh_path.name == "mesh_2d.msh"


def test_build_visualization_summary_contract_returns_typed_summary() -> None:
    config = load_toml_config(_example_config_path())
    data = load_visualization_data(
        replace(
            config,
            figure_output_path=None,
            summary_output_path=None,
        )
    )

    summary = build_visualization_summary_contract(data)

    assert isinstance(summary, VisualizationSummary)
    assert summary.node_count == data.mesh.n_nodes
    assert summary.cell_count == data.mesh.n_cells
    assert summary.to_mapping()["summary_schema_version"] == (VISUALIZATION_SUMMARY_SCHEMA_VERSION)


@pytest.mark.allow_subprocess
def test_python_module_mesh_bundle_viewer_entrypoint_runs_on_example_bundle(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mesh_view.toml"
    summary_path = tmp_path / "summary.json"
    bundle_dir = _example_bundle_dir().as_posix()
    config_path.write_text(
        "\n".join(
            [
                "[mesh_distribution]",
                f'bundle_dir = "{bundle_dir}"',
                "show_window = false",
                "",
                "[mesh_distribution.plot]",
                'color_field = "geology_key"',
                "show_topography_panel = false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.mesh_bundle_viewer",
            "--config",
            str(config_path),
            "--output-json",
            str(summary_path),
        ],
        cwd=_repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["summary_schema_version"] == VISUALIZATION_SUMMARY_SCHEMA_VERSION
    assert payload["cell_count"] > 0
