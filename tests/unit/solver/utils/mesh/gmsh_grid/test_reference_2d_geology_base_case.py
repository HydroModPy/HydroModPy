from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_base.run_case_gmsh import (
    run_reference_case_from_toml,
)


GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "reference_2d_geology_base_signature.json"
CASE_TOML = (
    Path(__file__).resolve().parents[6]
    / "hydromodpy"
    / "solver"
    / "utils"
    / "mesh"
    / "gmsh_grid"
    / "cases"
    / "reference_2d_geology_base"
    / "case_config_gmsh.toml"
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def test_reference_2d_geology_base_case_non_regression(update_goldens: bool) -> None:
    scratch_root = Path.cwd() / "scratch_tests" / "reference_2d_geology_base"
    output_dir = scratch_root / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = run_reference_case_from_toml(
        CASE_TOML,
        output_figure=output_dir / "reference_case.png",
        output_summary_json=output_dir / "reference_case_summary.json",
        show_plot=False,
    )

    assert summary["n_cells"] > 0
    assert summary["n_zone_keys"] > 0
    assert Path(summary["output_figure"]).exists()
    assert Path(summary["output_summary_json"]).exists()

    stable = dict(summary)
    stable.pop("output_figure", None)
    stable.pop("output_summary_json", None)

    if update_goldens:
        _write_json(GOLDEN_FILE, stable)
        return

    expected = _load_json(GOLDEN_FILE)
    assert stable == expected
