from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_visualize_3d import (
    run_reference_3d_visualization_from_toml,
)


GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "reference_3d_visualization_signature.json"
CASE_TOML = (
    Path(__file__).resolve().parents[6]
    / "hydromodpy"
    / "solver"
    / "utils"
    / "mesh"
    / "gmsh_grid"
    / "cases"
    / "reference_3d_fieldparam"
    / "case_visualization_3d.toml"
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def test_reference_3d_visualization_case_non_regression(update_goldens: bool) -> None:
    scratch_root = Path.cwd() / "scratch_tests" / "reference_3d_visualization"
    output_dir = scratch_root / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = run_reference_3d_visualization_from_toml(
        CASE_TOML,
        output_summary_json=output_dir / "reference_3d_visualization_summary.json",
        output_layers_png=output_dir / "reference_3d_layers.png",
        output_profiles_png=output_dir / "reference_3d_profiles.png",
    )

    assert summary["n_layers"] > 0
    assert summary["selected_layers"]
    assert summary["selected_profiles"]
    assert Path(summary["output_summary_json"]).exists()
    assert Path(summary["output_layers_png"]).exists()
    assert Path(summary["output_profiles_png"]).exists()

    stable = dict(summary)
    stable.pop("output_summary_json", None)
    stable.pop("output_layers_png", None)
    stable.pop("output_profiles_png", None)

    if update_goldens:
        _write_json(GOLDEN_FILE, stable)
        return

    expected = _load_json(GOLDEN_FILE)
    assert stable == expected

