from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_case_3d_fieldparam import (
    run_reference_3d_postprocess_from_toml,
)

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "reference_3d_postprocess_signature.json"
CASE_TOML = (
    Path(__file__).resolve().parents[4]
    / "hydromodpy"
    / "spatial"
    / "mesh"
    / "gmsh_grid"
    / "cases"
    / "reference_3d_fieldparam"
    / "case_postprocess_3d.toml"
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def test_reference_3d_postprocess_case_non_regression(update_goldens: bool) -> None:
    scratch_root = Path.cwd() / "scratch_tests" / "reference_3d_postprocess"
    output_dir = scratch_root / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = run_reference_3d_postprocess_from_toml(
        CASE_TOML,
        output_summary_json=output_dir / "reference_3d_postprocess_summary.json",
        output_values_npy=output_dir / "reference_3d_postprocess_values.npy",
        output_vtu=output_dir / "reference_3d_postprocess.vtu",
    )

    assert summary["n_layers"] > 0
    assert summary["n_cells_3d"] == summary["n_layers"] * summary["n_cells_2d"]
    assert Path(summary["output_summary_json"]).exists()
    assert Path(summary["output_values_npy"]).exists()
    if summary.get("output_vtu_status") == "written":
        assert Path(summary["output_vtu"]).exists()

    stable = dict(summary)
    stable.pop("output_summary_json", None)
    stable.pop("output_values_npy", None)
    stable.pop("output_vtu", None)
    stable.pop("output_vtu_status", None)

    if update_goldens:
        _write_json(GOLDEN_FILE, stable)
        return

    expected = _load_json(GOLDEN_FILE)
    assert stable == expected
