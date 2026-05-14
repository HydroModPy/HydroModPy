from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "projects" / "13_transport_mf6_gwt_disv_visual_guard"
MODULE_PATH = EXAMPLE_ROOT / "run_visual_guard.py"
REFERENCE_PATH = EXAMPLE_ROOT / "reference" / "synthetic_signatures.json"


def _load_guard_module():
    spec = importlib.util.spec_from_file_location("transport_visual_guard", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_perturbed_triangular_disv_mesh_is_bounded_and_clockwise() -> None:
    guard = _load_guard_module()
    case = guard.load_case(EXAMPLE_ROOT / "cases" / "case_02_perturbed_tri_constant_source.toml")

    mesh = guard.build_triangular_disv_mesh(case.domain)

    assert mesh.n_cells == 2 * case.domain.nx * case.domain.ny
    assert mesh.area_ratio <= case.domain.max_area_ratio
    assert mesh.left_cells.size > 0
    assert mesh.right_cells.size > 0
    assert np.all(mesh.areas > 0.0)
    for face in mesh.faces:
        assert guard._signed_area(mesh.vertices[face]) < 0.0


def test_synthetic_visual_guard_writes_html_figures_and_signatures(tmp_path: Path) -> None:
    guard = _load_guard_module()

    results = guard.run_cases(
        mode="synthetic",
        output_dir=tmp_path,
        case_names={"case_01_uniform_tri_constant_source"},
    )

    assert len(results) == 1
    case_dir = tmp_path / "case_01_uniform_tri_constant_source"
    assert (tmp_path / "index.html").exists()
    assert (case_dir / "index.html").exists()
    assert (case_dir / "figures" / "mesh_area.png").exists()
    assert (case_dir / "figures" / "head_final.png").exists()
    assert (case_dir / "figures" / "concentration_snapshots.png").exists()
    assert (case_dir / "signatures.csv").exists()

    signatures = json.loads((case_dir / "signatures.json").read_text(encoding="utf-8"))
    assert all(signatures["checks"].values())
    assert signatures["mesh"]["n_cells"] == 216
    rows = signatures["time_signatures"]
    finite_centers = [
        row["center_x_m"]
        for row in rows
        if isinstance(row["center_x_m"], float) and np.isfinite(row["center_x_m"])
    ]
    assert finite_centers[-1] > finite_centers[0]


def test_high_dispersion_case_has_wider_final_front_than_baseline() -> None:
    guard = _load_guard_module()
    baseline = guard.run_synthetic_case(
        guard.load_case(EXAMPLE_ROOT / "cases" / "case_02_perturbed_tri_constant_source.toml")
    )
    high_dispersion = guard.run_synthetic_case(
        guard.load_case(EXAMPLE_ROOT / "cases" / "case_04_perturbed_tri_dispersion.toml")
    )

    baseline_width = baseline.signatures["time_signatures"][-1]["width_x_m"]
    high_dispersion_width = high_dispersion.signatures["time_signatures"][-1]["width_x_m"]

    assert high_dispersion_width > baseline_width


def test_synthetic_signatures_match_committed_reference() -> None:
    guard = _load_guard_module()
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))

    actual = {}
    for case in guard.load_cases(EXAMPLE_ROOT / "cases"):
        result = guard.run_synthetic_case(case)
        actual[case.name] = {
            "mesh": result.signatures["mesh"],
            "flow": result.signatures["flow"],
            "final": result.signatures["time_signatures"][-1],
        }

    assert actual == reference["cases"]
