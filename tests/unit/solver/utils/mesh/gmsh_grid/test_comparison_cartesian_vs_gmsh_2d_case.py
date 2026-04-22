from __future__ import annotations

import json
from numbers import Real
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from matplotlib.figure import Figure

import hydromodpy.solver.utils.mesh.gmsh_grid.cases._comparison_utils as comparison_utils_module
import hydromodpy.solver.utils.mesh.gmsh_grid.cases.comparison_cartesian_vs_gmsh_2d.run_compare as compare_2d_module
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


def _stable_signature(payload: dict) -> dict:
    cartesian = dict(payload["cartesian"])
    gmsh = dict(payload["gmsh"])
    comparison = dict(payload["comparison"])

    cartesian.pop("dominant_zone_counts", None)
    gmsh.pop("dominant_zone_counts", None)
    comparison.pop("dominant_zone_count_delta", None)

    return {
        "cartesian": cartesian,
        "gmsh": gmsh,
        "comparison": comparison,
    }


def _assert_nested_close(actual, expected, *, rtol: float = 2.0e-4, atol: float = 2.0e-6) -> None:
    if isinstance(actual, dict) and isinstance(expected, dict):
        assert set(actual) == set(expected)
        for key in actual:
            _assert_nested_close(actual[key], expected[key], rtol=rtol, atol=atol)
        return
    if isinstance(actual, list) and isinstance(expected, list):
        assert len(actual) == len(expected)
        for a_item, e_item in zip(actual, expected):
            _assert_nested_close(a_item, e_item, rtol=rtol, atol=atol)
        return
    if (
        isinstance(actual, Real)
        and isinstance(expected, Real)
        and not isinstance(actual, bool)
        and not isinstance(expected, bool)
    ):
        assert np.isclose(float(actual), float(expected), rtol=rtol, atol=atol)
        return
    assert actual == expected


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
    _assert_nested_close(_stable_signature(payload), _stable_signature(expected))


def test_comparison_case_ensures_interactive_backend_before_show_build(
    monkeypatch,
) -> None:
    output_dir = Path.cwd() / "scratch_tests" / "comparison_cartesian_vs_gmsh_2d_show" / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)

    ensured = {"done": False}

    def _save_dummy_image(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        compare_2d_module.plt.imsave(path, np.zeros((4, 4, 3), dtype=float))

    class _DummyFieldParam:
        def to_mesh_field(self, field_discretization, depth):
            return SimpleNamespace(cell_values=np.array([1.0], dtype=float))

    monkeypatch.setattr(
        compare_2d_module.SGridFieldParamDiscretizationConfig,
        "from_toml",
        staticmethod(
            lambda path, section="case": SimpleNamespace(geology={}, field_param={}, depth=1.0)
        ),
    )
    monkeypatch.setattr(
        compare_2d_module,
        "run_discretization_case",
        lambda cfg: SimpleNamespace(
            field_discretization="disc", mesh="mesh", values_2d=np.array([1.0])
        ),
    )
    monkeypatch.setattr(
        compare_2d_module.GeologyField,
        "from_dict",
        staticmethod(lambda data: SimpleNamespace()),
    )
    monkeypatch.setattr(
        compare_2d_module.FieldParam,
        "from_dict",
        staticmethod(lambda data: _DummyFieldParam()),
    )
    monkeypatch.setattr(
        compare_2d_module,
        "_build_cartesian_summary",
        lambda **kwargs: {"kind": "cartesian"},
    )
    monkeypatch.setattr(
        compare_2d_module,
        "_build_comparison_summary",
        lambda **kwargs: {"kind": "comparison"},
    )
    monkeypatch.setattr(
        compare_2d_module,
        "_plot_cartesian_geology_and_result",
        lambda **kwargs: _save_dummy_image(Path(kwargs["output_path"])),
    )
    monkeypatch.setattr(
        compare_2d_module,
        "build_reference_case_state_from_toml",
        lambda path, section="case": {
            "config": {},
            "geology_field": None,
            "mesh": None,
            "field_discretization": None,
            "mesh_values": None,
            "summary": {"kind": "gmsh"},
        },
    )
    monkeypatch.setattr(compare_2d_module, "build_reference_case_figure", lambda **kwargs: Figure())

    def _stub_build_comparison_figure(*, output_path, **kwargs):
        _save_dummy_image(Path(output_path))
        return []

    def _stub_build_legend_metrics(*, output_path, **kwargs):
        _save_dummy_image(Path(output_path))

    monkeypatch.setattr(
        compare_2d_module, "_build_comparison_figure", _stub_build_comparison_figure
    )
    monkeypatch.setattr(
        compare_2d_module,
        "_build_comparison_legend_metrics_figure",
        _stub_build_legend_metrics,
    )
    monkeypatch.setattr(compare_2d_module, "write_json", _write_json)

    def _fake_ensure() -> None:
        ensured["done"] = True

    monkeypatch.setattr(
        comparison_utils_module, "ensure_interactive_backend_for_show", _fake_ensure
    )

    def _wrapped_subplots(nrows=1, ncols=1, *args, squeeze=True, **kwargs):
        assert ensured["done"]
        fig = Figure(figsize=kwargs.get("figsize"), dpi=kwargs.get("dpi"))
        axes = np.empty((nrows, ncols), dtype=object)
        subplot_index = 1
        for row_idx in range(nrows):
            for col_idx in range(ncols):
                axes[row_idx, col_idx] = fig.add_subplot(nrows, ncols, subplot_index)
                subplot_index += 1
        if squeeze:
            if nrows == 1 and ncols == 1:
                axes = axes[0, 0]
            elif nrows == 1 or ncols == 1:
                axes = axes.reshape(max(nrows, ncols))
        return fig, axes

    monkeypatch.setattr(compare_2d_module.plt, "subplots", _wrapped_subplots)
    shown = {"called": False}

    def _fake_show_saved_images(image_paths, **kwargs):
        comparison_utils_module.ensure_interactive_backend_for_show()
        assert ensured["done"]
        shown["called"] = True
        assert len(image_paths) == 4

    monkeypatch.setattr(compare_2d_module, "show_saved_images_blocking", _fake_show_saved_images)

    payload = run_comparison_case(
        cartesian_config_toml=CASE_DIR / "case_config_cartesian.toml",
        gmsh_config_toml=CASE_DIR / "case_config_gmsh.toml",
        output_dir=output_dir,
        show_plot=True,
    )

    assert ensured["done"] is True
    assert shown["called"] is True
    assert payload["comparison"]["kind"] == "comparison"
    assert (output_dir / "comparison_overview.png").exists()
    assert (output_dir / "comparison_legend_metrics.png").exists()
