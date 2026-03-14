from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.comparison_cartesian_vs_gmsh_2d.run_compare import (
    run_comparison_case,
)


GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "comparison_cartesian_vs_gmsh_2d_signature.json"
CASE_DIR = (
    Path(__file__).resolve().parents[6]
    / "hydromodpy"
    / "solver"
    / "utils"
    / "mesh"
    / "gmsh_grid"
    / "cases"
    / "comparison_cartesian_vs_gmsh_2d"
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def test_comparison_cartesian_vs_gmsh_2d_non_regression(update_goldens: bool) -> None:
    output_dir = Path.cwd() / "scratch_tests" / "comparison_cartesian_vs_gmsh_2d" / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = run_comparison_case(
        cartesian_config_toml=CASE_DIR / "case_config_cartesian.toml",
        gmsh_config_toml=CASE_DIR / "case_config_gmsh.toml",
        output_dir=output_dir,
        show_plot=False,
    )

    assert (output_dir / "cartesian_reference.png").exists()
    assert (output_dir / "gmsh_reference.png").exists()
    assert (output_dir / "comparison_overview.png").exists()
    assert (output_dir / "comparison_legend_metrics.png").exists()
    assert (output_dir / "comparison_summary.json").exists()

    if update_goldens:
        _write_json(GOLDEN_FILE, payload)
        return

    expected = _load_json(GOLDEN_FILE)
    assert payload == expected
