from __future__ import annotations

import json
from pathlib import Path

from matplotlib.figure import Figure

import hydromodpy.spatial.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_case_3d_fieldparam as run_visualize_module
from hydromodpy.spatial.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_case_3d_fieldparam import (
    run_reference_3d_visualization_from_toml,
)

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "reference_3d_visualization_signature.json"
CASE_TOML = (
    Path(__file__).resolve().parents[4]
    / "hydromodpy"
    / "spatial"
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


def test_reference_3d_visualization_case_non_regression(
    update_goldens: bool, tmp_path: Path
) -> None:
    output_dir = tmp_path / "runtime"
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


def test_reference_3d_visualization_ensures_backend_before_figure_build(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)

    ensured = {"done": False}

    monkeypatch.setattr(
        run_visualize_module,
        "build_reference_3d_visualization_state_from_toml",
        lambda config_toml, section="case": {
            "config_path": CASE_TOML,
            "config": {
                "output_summary_json": None,
                "output_layers_png": None,
                "output_profiles_png": None,
            },
            "mesh_with_values": object(),
            "marker_specs": [],
            "summary": {
                "n_layers": 2,
                "selected_layers": [0, 1],
                "selected_profiles": [],
            },
        },
    )

    def _fake_ensure() -> None:
        ensured["done"] = True

    def _build_layers(*args, **kwargs):
        assert ensured["done"]
        return Figure()

    def _build_profiles(*args, **kwargs):
        assert ensured["done"]
        return Figure()

    monkeypatch.setattr(run_visualize_module, "ensure_interactive_backend_for_show", _fake_ensure)
    monkeypatch.setattr(run_visualize_module, "build_layer_maps_figure", _build_layers)
    monkeypatch.setattr(run_visualize_module, "build_vertical_profiles_figure", _build_profiles)
    monkeypatch.setattr(
        run_visualize_module,
        "show_figures_blocking",
        lambda *figures: None,
    )

    summary = run_reference_3d_visualization_from_toml(
        CASE_TOML,
        output_summary_json=output_dir / "reference_3d_visualization_summary.json",
        output_layers_png=output_dir / "reference_3d_layers.png",
        output_profiles_png=output_dir / "reference_3d_profiles.png",
        show_plot=True,
    )

    assert ensured["done"] is True
    assert Path(summary["output_summary_json"]).exists()
    assert Path(summary["output_layers_png"]).exists()
    assert Path(summary["output_profiles_png"]).exists()
