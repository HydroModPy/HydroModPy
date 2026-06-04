from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "projects" / "13_transport_mf6_gwt_disv_visual_guard"
MODULE_PATH = EXAMPLE_ROOT / "run_visual_guard.py"


def _load_guard_module():
    spec = importlib.util.spec_from_file_location("transport_visual_guard", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fast_case(
    guard: Any,
    *,
    name: str,
    pattern: str,
    mesh_seed: int,
    k_seed: int | None = None,
    source_schedule: str = "internal_pulse",
    duration_days: float = 650.0,
    n_snapshots: int = 21,
    pulse_end_day: float = 0.0,
    diffusion_m2_per_day: float = 0.0119,
):
    return guard.CaseConfig(
        name=name,
        title=name,
        description="Fast numeric transport regression case without HTML output.",
        domain=guard.DomainConfig(
            length_m=120.0,
            width_m=24.0,
            nx=32,
            ny=8,
            perturbation_fraction=0.08,
            seed=mesh_seed,
            max_area_ratio=2.20,
        ),
        flow=guard.FlowConfig(
            head_left_m=3.6,
            head_right_m=0.0,
            hydraulic_conductivity_m_per_day=1.0,
            hydraulic_conductivity_pattern=pattern,
            hydraulic_conductivity_factor=5.0,
            hydraulic_conductivity_seed=k_seed,
            porosity=0.30,
        ),
        transport=guard.TransportConfig(
            duration_days=duration_days,
            n_snapshots=n_snapshots,
            source_concentration=1.0,
            source_schedule=source_schedule,
            pulse_end_day=pulse_end_day,
            pulse_center_m=35.0,
            pulse_width_m=2.0,
            pulse_y_center_m=12.0,
            pulse_y_width_m=4.0,
            longitudinal_dispersivity_m=0.0,
            transverse_dispersivity_m=0.0,
            diffusion_m2_per_day=diffusion_m2_per_day,
        ),
        source_path=Path("<in-memory-fast-transport-case>"),
    )


def _fast_cases(guard: Any):
    return [
        _fast_case(
            guard,
            name="fast_01_homogeneous_k_pulse",
            pattern="homogeneous",
            mesh_seed=101,
        ),
        _fast_case(
            guard,
            name="fast_02_longitudinal_channel_kx5_pulse",
            pattern="longitudinal_channel",
            mesh_seed=202,
        ),
        _fast_case(
            guard,
            name="fast_03_transverse_bands_kx5_pulse",
            pattern="transverse_bands",
            mesh_seed=303,
        ),
        _fast_case(
            guard,
            name="fast_04_random_blocks_kx5_pulse",
            pattern="random_blocks",
            mesh_seed=404,
            k_seed=4404,
        ),
        _fast_case(
            guard,
            name="fast_05_homogeneous_constant_upstream",
            pattern="homogeneous",
            mesh_seed=505,
            source_schedule="constant",
            duration_days=650.0,
            n_snapshots=21,
            pulse_end_day=650.0,
        ),
        _fast_case(
            guard,
            name="fast_06_homogeneous_upstream_pulse",
            pattern="homogeneous",
            mesh_seed=606,
            source_schedule="pulse",
            duration_days=650.0,
            n_snapshots=21,
            pulse_end_day=120.0,
        ),
        _fast_case(
            guard,
            name="fast_07_homogeneous_internal_pulse_pe_low",
            pattern="homogeneous",
            mesh_seed=707,
            diffusion_m2_per_day=0.0476,
        ),
        _fast_case(
            guard,
            name="fast_08_homogeneous_internal_pulse_pe_high",
            pattern="homogeneous",
            mesh_seed=808,
            diffusion_m2_per_day=0.00397,
        ),
    ]


def test_fast_perturbed_triangular_disv_mesh_is_bounded_and_clockwise() -> None:
    guard = _load_guard_module()
    case = _fast_case(
        guard,
        name="fast_mesh_check",
        pattern="longitudinal_channel",
        mesh_seed=202,
    )

    mesh = guard.build_triangular_disv_mesh(case.domain)

    assert mesh.n_cells == 2 * case.domain.nx * case.domain.ny
    assert mesh.n_cells == 512
    assert mesh.area_ratio <= case.domain.max_area_ratio
    assert mesh.left_cells.size > 0
    assert mesh.right_cells.size > 0
    assert np.all(mesh.areas > 0.0)
    for face in mesh.faces:
        assert guard._signed_area(mesh.vertices[face]) < 0.0


def test_fast_homogeneous_synthetic_plume_moves_downstream() -> None:
    guard = _load_guard_module()
    case = _fast_case(
        guard,
        name="fast_01_homogeneous_k_pulse",
        pattern="homogeneous",
        mesh_seed=101,
    )

    result = guard.run_synthetic_case(case)

    assert result.signatures["mesh"]["n_cells"] == 512
    assert all(result.signatures["checks"].values())
    assert result.signatures["analytical_comparison"]["available"]

    rows = result.signatures["time_signatures"]
    finite_centers = [
        row["center_x_m"]
        for row in rows
        if isinstance(row["center_x_m"], float) and np.isfinite(row["center_x_m"])
    ]
    assert finite_centers[-1] > finite_centers[0]


def test_fast_upstream_source_cases_stay_bounded_and_tag_ogata_banks_reference() -> None:
    guard = _load_guard_module()
    cases = [
        _fast_case(
            guard,
            name="fast_05_homogeneous_constant_upstream",
            pattern="homogeneous",
            mesh_seed=505,
            source_schedule="constant",
            pulse_end_day=650.0,
        ),
        _fast_case(
            guard,
            name="fast_06_homogeneous_upstream_pulse",
            pattern="homogeneous",
            mesh_seed=606,
            source_schedule="pulse",
            pulse_end_day=120.0,
        ),
    ]

    for case in cases:
        result = guard.run_synthetic_case(case)
        comparison = result.signatures["analytical_comparison"]

        assert comparison["available"]
        assert "ogata_banks" in comparison["reference"]
        assert np.all(result.concentration >= -1.0e-12)
        assert np.all(result.concentration <= case.transport.source_concentration + 1.0e-12)


def test_fast_internal_pulse_conserves_mass_before_downstream_exit() -> None:
    guard = _load_guard_module()
    case = _fast_case(
        guard,
        name="fast_01_homogeneous_k_pulse",
        pattern="homogeneous",
        mesh_seed=101,
    )

    result = guard.run_synthetic_case(case)
    masses = [row["area_weighted_mass"] for row in result.signatures["time_signatures"]]
    initial = masses[0]
    final = masses[-1]
    early = masses[:8]

    assert max(abs(mass - initial) / initial for mass in early) < 1.0e-2
    assert final / initial > 0.95


def test_fast_peclet_variants_control_plume_spreading() -> None:
    guard = _load_guard_module()
    low_pe = _fast_case(
        guard,
        name="fast_07_homogeneous_internal_pulse_pe_low",
        pattern="homogeneous",
        mesh_seed=707,
        diffusion_m2_per_day=0.0476,
    )
    high_pe = _fast_case(
        guard,
        name="fast_08_homogeneous_internal_pulse_pe_high",
        pattern="homogeneous",
        mesh_seed=808,
        diffusion_m2_per_day=0.00397,
    )

    low_result = guard.run_synthetic_case(low_pe)
    high_result = guard.run_synthetic_case(high_pe)
    low_numbers = low_result.signatures["transport_numbers"]
    high_numbers = high_result.signatures["transport_numbers"]
    low_final = low_result.signatures["time_signatures"][-1]
    high_final = high_result.signatures["time_signatures"][-1]

    assert 4.0 <= low_numbers["peclet_mean"] <= 6.0
    assert 55.0 <= high_numbers["peclet_mean"] <= 65.0
    assert low_final["width_x_m"] > high_final["width_x_m"]


def test_fast_homogeneous_case_is_configured_near_cell_peclet_20() -> None:
    guard = _load_guard_module()
    case = _fast_case(
        guard,
        name="fast_01_homogeneous_k_pulse",
        pattern="homogeneous",
        mesh_seed=101,
    )

    result = guard.run_synthetic_case(case)
    numbers = result.signatures["transport_numbers"]

    assert 18.0 <= numbers["peclet_mean"] <= 22.0
    assert 15.0 <= numbers["peclet_min"] <= 22.0
    assert 18.0 <= numbers["peclet_max"] <= 25.0


def test_fast_heterogeneous_cases_keep_fixed_diffusion_and_vary_peclet() -> None:
    guard = _load_guard_module()

    for case in _fast_cases(guard):
        if case.flow.hydraulic_conductivity_pattern == "homogeneous":
            continue
        result = guard.run_synthetic_case(case)
        numbers = result.signatures["transport_numbers"]

        assert not result.signatures["analytical_comparison"]["available"]
        assert case.transport.diffusion_m2_per_day == 0.0119
        k_ratio = (
            numbers["hydraulic_conductivity_max_m_per_day"]
            / numbers["hydraulic_conductivity_min_m_per_day"]
        )
        assert 3.0 <= k_ratio <= 5.0
        assert numbers["peclet_max"] > 3.0 * numbers["peclet_min"]


def test_fast_internal_pulse_is_initialized_away_from_upstream_boundary() -> None:
    guard = _load_guard_module()
    case = _fast_case(
        guard,
        name="fast_01_homogeneous_k_pulse",
        pattern="homogeneous",
        mesh_seed=101,
    )

    result = guard.run_synthetic_case(case)
    initial = result.concentration[0]
    peak_cell = int(np.argmax(initial))
    peak_x = float(result.mesh.centroids[peak_cell, 0])

    assert abs(peak_x - float(case.transport.pulse_center_m)) <= 3.0
    assert peak_x >= 0.20 * case.domain.length_m
