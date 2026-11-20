from __future__ import annotations

import numpy as np

from tests._helpers.transport_guard import fast_case, fast_cases, load_guard_module


def test_fast_perturbed_triangular_disv_mesh_is_bounded_and_clockwise() -> None:
    guard = load_guard_module()
    case = fast_case(
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
    guard = load_guard_module()
    case = fast_case(
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
    guard = load_guard_module()
    cases = [
        fast_case(
            guard,
            name="fast_05_homogeneous_constant_upstream",
            pattern="homogeneous",
            mesh_seed=505,
            source_schedule="constant",
            pulse_end_day=650.0,
        ),
        fast_case(
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
    guard = load_guard_module()
    case = fast_case(
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
    guard = load_guard_module()
    low_pe = fast_case(
        guard,
        name="fast_07_homogeneous_internal_pulse_pe_low",
        pattern="homogeneous",
        mesh_seed=707,
        diffusion_m2_per_day=0.0476,
    )
    high_pe = fast_case(
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
    guard = load_guard_module()
    case = fast_case(
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
    guard = load_guard_module()

    for case in fast_cases(guard):
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
    guard = load_guard_module()
    case = fast_case(
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
