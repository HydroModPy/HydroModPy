from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from hydromodpy_annex.distribution.mesh.config import (
    load_toml_config,
)
from hydromodpy_annex.distribution.mesh.toml_schema import (
    get_toml_parameter_descriptions,
)
from hydromodpy_annex.distribution.mesh.workflow import (
    run_visualization_from_toml,
)


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
        json.dumps({"constraints_mode": "geology_rivers"}, indent=2, ensure_ascii=True)
        + "\n",
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
    (bundle_dir / "reader.py").write_text(
        "\n".join(
            [
                '"""Lecteur minimal autonome pour un bundle de test."""',
                "",
                "from __future__ import annotations",
                "",
                "from dataclasses import dataclass",
                "import csv",
                "import json",
                "from pathlib import Path",
                "from typing import Any",
                "",
                "",
                "@dataclass(frozen=True)",
                "class CatchmentMeshBundleNode:",
                "    node_id: int",
                "    x: float",
                "    y: float",
                "    z_top: float | None",
                "",
                "",
                "@dataclass(frozen=True)",
                "class CatchmentMeshBundleCell:",
                "    cell_id: int",
                "    geom_type: str",
                "    node_indices: tuple[int, ...]",
                "    centroid_x: float",
                "    centroid_y: float",
                "    area_m2: float",
                "    z_top_centroid: float | None",
                "    z_top_mean: float | None",
                "    geology_code: int | None",
                "    geology_key: str",
                "",
                "",
                "@dataclass(frozen=True)",
                "class CatchmentMeshBundleEdge:",
                "    edge_id: int",
                "    node_a: int",
                "    node_b: int",
                "    cell_a: int",
                "    cell_b: int | None",
                "    length_m: float",
                "    edge_kind: str",
                "    is_river: bool",
                "    geology_a_key: str",
                "    geology_b_key: str",
                "",
                "",
                "@dataclass(frozen=True)",
                "class CatchmentMeshBundleGeologyFraction:",
                "    cell_id: int",
                "    geology_key: str",
                "    fraction: float",
                "",
                "",
                "@dataclass(frozen=True)",
                "class CatchmentMeshBundle:",
                "    bundle_dir: Path",
                "    metadata: dict[str, Any]",
                "    nodes: tuple[CatchmentMeshBundleNode, ...]",
                "    cells: tuple[CatchmentMeshBundleCell, ...]",
                "    edges: tuple[CatchmentMeshBundleEdge, ...]",
                "    geology_fractions: tuple[CatchmentMeshBundleGeologyFraction, ...]",
                "    mesh_summary: dict[str, Any] | None = None",
                "",
                "    @property",
                "    def n_nodes(self) -> int:",
                "        return len(self.nodes)",
                "",
                "    @property",
                "    def n_cells(self) -> int:",
                "        return len(self.cells)",
                "",
                "    @property",
                "    def n_edges(self) -> int:",
                "        return len(self.edges)",
                "",
                "    @property",
                "    def mesh_path(self) -> Path:",
                "        return self.bundle_dir / self.metadata['files']['mesh']",
                "",
                "",
                "def _float_optional(value: str) -> float | None:",
                "    if value is None or value.strip() == '':",
                "        return None",
                "    return float(value)",
                "",
                "",
                "def _int_optional(value: str) -> int | None:",
                "    if value is None or value.strip() == '':",
                "        return None",
                "    return int(value)",
                "",
                "",
                "def load_catchment_mesh_bundle(bundle_dir: str | Path) -> CatchmentMeshBundle:",
                "    bundle_dir = Path(bundle_dir).resolve()",
                "    metadata = json.loads((bundle_dir / 'metadata.json').read_text(encoding='utf-8'))",
                "    mesh_summary_path = bundle_dir / 'mesh_summary.json'",
                "    mesh_summary = None",
                "    if mesh_summary_path.exists():",
                "        mesh_summary = json.loads(mesh_summary_path.read_text(encoding='utf-8'))",
                "",
                "    with (bundle_dir / 'nodes.csv').open('r', encoding='utf-8', newline='') as stream:",
                "        reader = csv.DictReader(stream)",
                "        nodes = tuple(",
                "            CatchmentMeshBundleNode(",
                "                node_id=int(row['node_id']),",
                "                x=float(row['x']),",
                "                y=float(row['y']),",
                "                z_top=_float_optional(row['z_top']),",
                "            )",
                "            for row in reader",
                "        )",
                "",
                "    with (bundle_dir / 'cells.csv').open('r', encoding='utf-8', newline='') as stream:",
                "        reader = csv.DictReader(stream)",
                "        cells = []",
                "        for row in reader:",
                "            node_indices = tuple(",
                "                int(row[key])",
                "                for key in ('n0', 'n1', 'n2', 'n3')",
                "                if row.get(key) not in (None, '')",
                "            )",
                "            cells.append(",
                "                CatchmentMeshBundleCell(",
                "                    cell_id=int(row['cell_id']),",
                "                    geom_type=row['geom_type'],",
                "                    node_indices=node_indices,",
                "                    centroid_x=float(row['centroid_x']),",
                "                    centroid_y=float(row['centroid_y']),",
                "                    area_m2=float(row['area_m2']),",
                "                    z_top_centroid=_float_optional(row['z_top_centroid']),",
                "                    z_top_mean=_float_optional(row['z_top_mean']),",
                "                    geology_code=_int_optional(row['geology_code']),",
                "                    geology_key=row['geology_key'],",
                "                )",
                "            )",
                "        cells = tuple(cells)",
                "",
                "    with (bundle_dir / 'edges.csv').open('r', encoding='utf-8', newline='') as stream:",
                "        reader = csv.DictReader(stream)",
                "        edges = tuple(",
                "            CatchmentMeshBundleEdge(",
                "                edge_id=int(row['edge_id']),",
                "                node_a=int(row['node_a']),",
                "                node_b=int(row['node_b']),",
                "                cell_a=int(row['cell_a']),",
                "                cell_b=_int_optional(row['cell_b']),",
                "                length_m=float(row['length_m']),",
                "                edge_kind=row['edge_kind'],",
                "                is_river=str(row['is_river']).strip().lower() == 'true',",
                "                geology_a_key=row['geology_a_key'],",
                "                geology_b_key=row['geology_b_key'],",
                "            )",
                "            for row in reader",
                "        )",
                "",
                "    with (bundle_dir / 'cell_geology_fractions.csv').open('r', encoding='utf-8', newline='') as stream:",
                "        reader = csv.DictReader(stream)",
                "        fractions = tuple(",
                "            CatchmentMeshBundleGeologyFraction(",
                "                cell_id=int(row['cell_id']),",
                "                geology_key=row['geology_key'],",
                "                fraction=float(row['fraction']),",
                "            )",
                "            for row in reader",
                "        )",
                "",
                "    return CatchmentMeshBundle(",
                "        bundle_dir=bundle_dir,",
                "        metadata=metadata,",
                "        nodes=nodes,",
                "        cells=cells,",
                "        edges=edges,",
                "        geology_fractions=fractions,",
                "        mesh_summary=mesh_summary,",
                "    )",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
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


def test_toml_schema_parameter_descriptions_cover_public_keys() -> None:
    descriptions = get_toml_parameter_descriptions()

    assert "[mesh_distribution].bundle_dir" in descriptions
    assert "dossier bundle" in descriptions["[mesh_distribution].bundle_dir"]

    assert "[mesh_distribution.plot].color_field" in descriptions
    assert "Champ utilise" in descriptions["[mesh_distribution.plot].color_field"]

    assert "[mesh_distribution.plot].show_river_edges" in descriptions
    assert "rivieres" in descriptions["[mesh_distribution.plot].show_river_edges"]


def test_run_visualization_from_toml_accepts_missing_legacy_hydraulic_field(
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


def test_run_visualization_script_from_distributed_folder(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sample_bundle"
    _ecrire_bundle_minimal(bundle_dir)

    distribution_root = tmp_path / "distribution_package"
    mesh_source_dir = (
        Path(__file__).resolve().parents[3] / "hydromodpy_annex" / "distribution" / "mesh"
    )
    mesh_target_dir = distribution_root / "hydromodpy_annex" / "distribution" / "mesh"
    shutil.copytree(mesh_source_dir, mesh_target_dir)
    (distribution_root / "hydromodpy_annex" / "__init__.py").write_text(
        '"""Paquet minimal de distribution de test."""\n',
        encoding="utf-8",
    )
    (distribution_root / "hydromodpy_annex" / "distribution" / "__init__.py").write_text(
        '"""Sous-paquet minimal de distribution de test."""\n',
        encoding="utf-8",
    )

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
            str(mesh_target_dir / "run_visualization.py"),
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
