from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.comparison_cartesian_vs_gmsh_3d.run_compare import (
    run_comparison_case,
)


GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "comparison_cartesian_vs_gmsh_3d_signature.json"
CASE_DIR = (
    Path(__file__).resolve().parents[6]
    / "hydromodpy"
    / "solver"
    / "utils"
    / "mesh"
    / "gmsh_grid"
    / "cases"
    / "comparison_cartesian_vs_gmsh_3d"
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _stable_signature(payload: dict) -> dict:
    cartesian = dict(payload["cartesian"])
    gmsh = dict(payload["gmsh"])
    comparison = dict(payload["comparison"])

    cartesian.pop("profile_targets", None)
    gmsh.pop("profile_targets", None)

    profiles = []
    for profile in payload["profiles"]:
        profiles.append(
            {
                "label": profile["label"],
                "comparison": dict(profile["comparison"]),
            }
        )

    artifacts = dict(payload["artifacts"])
    layer_figures = list(artifacts.get("layer_figures", []))

    return {
        "cartesian": cartesian,
        "gmsh": gmsh,
        "comparison": comparison,
        "profiles": profiles,
        "artifacts": {
            "layer_figure_count": len(layer_figures),
            "layer_figures": layer_figures,
            "vertical_profiles_figure": artifacts.get("vertical_profiles_figure"),
            "shared_bounds_xy": artifacts.get("shared_bounds_xy"),
        },
    }


def test_comparison_cartesian_vs_gmsh_3d_non_regression(update_goldens: bool) -> None:
    output_dir = Path.cwd() / "scratch_tests" / "comparison_cartesian_vs_gmsh_3d" / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = run_comparison_case(
        cartesian_config_toml=CASE_DIR / "case_config_cartesian.toml",
        gmsh_config_toml=CASE_DIR / "case_config_gmsh.toml",
        output_dir=output_dir,
        show_plot=False,
    )

    assert (output_dir / "cartesian_summary.json").exists()
    assert (output_dir / "gmsh_summary.json").exists()
    assert (output_dir / "comparison_summary.json").exists()
    assert (output_dir / "vertical_profiles_comparison.png").exists()
    assert (output_dir / "comparison_overview.png").exists()

    layer_figures = [output_dir / rel_path for rel_path in payload["artifacts"]["layer_figures"]]
    assert layer_figures
    for figure_path in layer_figures:
        assert figure_path.exists()
    assert payload["artifacts"]["comparison_overview_figure"] == "comparison_overview.png"

    if update_goldens:
        _write_json(GOLDEN_FILE, payload)
        return

    expected = _load_json(GOLDEN_FILE)
    assert _stable_signature(payload) == _stable_signature(expected)
