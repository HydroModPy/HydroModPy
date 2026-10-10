"""A cell with an imposed head takes no recharge, no well and no drain.

The natural-basin comparison reported a Boussinesq recharge 13 % above the
forcing integrated over the aquifer: the eight cells of its two fixed-head sides
(11.6 % of the area) took recharge, which left at once as constant-head outflow.
A well or a drain on such a cell was counted the same way, fed by the boundary.
MODFLOW applies none of them on a constant-head cell. These tests pin that
convention from the residual to the lumped budget table.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.assembly.residual_facade import (
    assemble_steady_residual,
    assemble_transient_residual,
)
from hydromodpy.solver.boussinesq.drivers.forcing import (
    _warn_wells_on_cells_with_an_imposed_head,
)
from hydromodpy.solver.boussinesq.drivers.state import TransientRuntimeHistory
from hydromodpy.solver.boussinesq.export_payload import (
    build_state_history_export_payload,
    first_period_snapshot,
)
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter
from hydromodpy.solver.boussinesq.runtimes.local import solve_backward_euler_step
from hydromodpy.solver.boussinesq.runtimes.picard.picard import assemble_strict_steady_residual
from tests._helpers.mesh_doubles import _MiniMesh

RECHARGE_M_S = 5.0e-3 / 86400.0
DAY_S = 86400.0
WELL_M3_S = -2.0e-4
DRAIN_M2_S = 1.0e-3


def _strip(n_cells: int, *, outlet_top_m: float = 50.0) -> _MiniMesh:
    """Return a row of 10 m square cells, 50 m thick, joined by their sides.

    ``outlet_top_m`` sets the ground of the first cell: under its 20 m held
    head, a drain there would run.
    """
    n_edges = n_cells - 1
    z_top = np.full(n_cells, 50.0)
    z_top[0] = outlet_top_m
    return _MiniMesh(
        cell_area_m2=np.full(n_cells, 100.0),
        z_top_m=z_top,
        z_bottom_m=np.zeros(n_cells),
        hydraulic_conductivity_m_s=np.full(n_cells, 1.0e-4),
        storage_coefficient=np.full(n_cells, 0.1),
        edge_ids=np.arange(n_edges),
        edge_cell_a=np.arange(n_edges),
        edge_cell_b=np.arange(1, n_cells),
        edge_length_m=np.full(n_edges, 10.0),
        edge_distance_m=np.full(n_edges, 10.0),
        edge_midpoint_distance_to_cell_a_m=np.full(n_edges, 5.0),
        edge_midpoint_distance_to_cell_b_m=np.full(n_edges, 5.0),
    )


def _outlet_heads(n_cells: int, outlet_m: float) -> np.ndarray:
    """Return the prescribed heads: the first cell held, the others free."""
    prescribed = np.full(n_cells, np.nan)
    prescribed[0] = outlet_m
    return prescribed


def _wells(n_cells: int, *, on_fixed_cell: bool) -> np.ndarray:
    """Return a well on the last free cell, and one on the held cell when asked."""
    wells = np.zeros(n_cells)
    wells[-1] = WELL_M3_S
    if on_fixed_cell:
        wells[0] = WELL_M3_S
    return wells


def test_transient_residual_gives_no_recharge_to_a_cell_with_an_imposed_head() -> None:
    mesh = _strip(4)
    head = np.asarray([20.0, 21.0, 21.5, 21.8])
    assembly = assemble_transient_residual(
        mesh,
        head_m=head,
        head_prev_m=head,
        dt_seconds=DAY_S,
        recharge_rate_m_s=RECHARGE_M_S,
        prescribed_head_m_by_cell=_outlet_heads(4, 20.0),
    )

    np.testing.assert_allclose(assembly.recharge_rate_m_s, [0.0, *[RECHARGE_M_S] * 3])
    # The constant-head flux is the flow the free neighbour sends in, positive out.
    inflow_from_free_cell = -assembly.internal_edge_flux_m3_s[0]
    assert inflow_from_free_cell > 0.0
    assert assembly.prescribed_head_flux_m3_s[0] == pytest.approx(inflow_from_free_cell)
    np.testing.assert_allclose(assembly.prescribed_head_flux_m3_s[1:], 0.0)


@pytest.mark.parametrize("assemble", ["canonical", "picard_strict"])
def test_steady_residuals_give_nothing_to_a_cell_with_an_imposed_head(assemble) -> None:
    # The held head stands 1 m above the ground of its cell, under a well.
    mesh = _strip(3, outlet_top_m=19.0)
    head = np.asarray([20.0, 21.0, 21.5])
    kwargs = {
        "recharge_rate_m_s": RECHARGE_M_S,
        "well_flux_m3_s": _wells(3, on_fixed_cell=True),
        "prescribed_head_m_by_cell": _outlet_heads(3, 20.0),
        "drainage_conductance_m2_s": DRAIN_M2_S,
    }
    if assemble == "canonical":
        assembly = assemble_steady_residual(mesh, head_m=head, **kwargs)
    else:
        assembly = assemble_strict_steady_residual(mesh, head, **kwargs)

    np.testing.assert_allclose(assembly.recharge_rate_m_s, [0.0, RECHARGE_M_S, RECHARGE_M_S])
    np.testing.assert_allclose(assembly.well_flux_m3_s, [0.0, 0.0, WELL_M3_S])
    np.testing.assert_allclose(assembly.drainage_flux_m3_s, 0.0)
    assert assembly.prescribed_head_flux_m3_s[0] == pytest.approx(
        -assembly.internal_edge_flux_m3_s[0]
    )


def _run_strip(
    mesh: _MiniMesh,
    *,
    rates: tuple[float, ...],
    wells: np.ndarray | None = None,
    drainage_m2_s: float | None = None,
):
    """Run one transient strip through the driver history and the store extractor."""
    n_cells = int(mesh.n_cells)
    prescribed = _outlet_heads(n_cells, 20.0)
    head = np.full(n_cells, 20.0)
    history = TransientRuntimeHistory.initialize(
        mesh=mesh,
        head_m=head,
        saturated_thickness_m=head - mesh.z_bottom_m,
    )
    for rate in rates:
        step = solve_backward_euler_step(
            mesh,
            head_prev_m=head,
            dt_seconds=DAY_S,
            recharge_rate_m_s=rate,
            well_flux_m3_s=wells,
            prescribed_head_m_by_cell=prescribed,
            drainage_conductance_m2_s=drainage_m2_s,
            tol_residual_inf=1.0e-13,
        )
        assert step.converged
        head = np.asarray(step.head_m, dtype=float)
        history.append_step(
            mesh=mesh,
            head_m=head,
            assembly=step.assembly,
            prescribed_head_m_by_cell=prescribed,
        )
    state = history.build_runtime_state(
        period_lengths_seconds=(DAY_S,) * len(rates),
        nonlinear_iterations=(1,) * len(rates),
        converged_by_period=(True,) * len(rates),
    )
    payload = build_state_history_export_payload(state)
    first = first_period_snapshot(payload, n_snapshots=len(rates) + 1)
    assert first == 1
    components = BoussinesqOutputAdapter._budget_components(
        payload,
        n_timesteps=len(rates),
        n_cells=n_cells,
        cell_area_m2=mesh.cell_area_m2,
        first_snapshot=first,
    )
    return state, payload, components


def _assert_budget_closes(mesh: _MiniMesh, state, components) -> None:
    """What enters is stored or leaves by a well, a drain or the fixed head."""
    free = np.arange(mesh.n_cells) > 0
    storage = np.diff(state.head_history_m, axis=0) * mesh.storage_coefficient * mesh.cell_area_m2
    stored_m3_s = storage[:, free].sum(axis=1) / DAY_S
    inflow = components["recharge"].sum(axis=1) + components["well"].sum(axis=1)
    outflow = components["drain"].sum(axis=1) + components["constant_head"].sum(axis=1)
    np.testing.assert_allclose(inflow, stored_m3_s + outflow, rtol=1e-9, atol=1e-15)


def test_exported_recharge_is_the_forcing_on_the_free_cells_and_the_budget_closes() -> None:
    n_cells = 6
    mesh = _strip(n_cells)
    rates = (RECHARGE_M_S, 0.4 * RECHARGE_M_S, 0.0)
    state, payload, components = _run_strip(mesh, rates=rates)

    # One row per period, the forcing on the free cells, not on the whole strip.
    expected = np.asarray(rates) * mesh.cell_area_m2[1:].sum()
    np.testing.assert_allclose(components["recharge"].sum(axis=1), expected, rtol=1e-12)
    _assert_budget_closes(mesh, state, components)

    # The residual history is a closure error: none on the cell with an imposed head.
    residual = np.asarray(payload["residual_history_m3_s"], dtype=float)
    np.testing.assert_allclose(residual[:, 0], 0.0, atol=0.0)
    assert np.max(np.abs(residual.sum(axis=1))) <= n_cells * 1.0e-13


def test_a_well_and_a_drain_on_a_fixed_cell_change_neither_heads_nor_budget() -> None:
    mesh = _strip(5, outlet_top_m=19.0)
    rates = (RECHARGE_M_S, 0.0)
    plain_state, _, plain = _run_strip(mesh, rates=rates, wells=_wells(5, on_fixed_cell=False))
    held_state, held_payload, held = _run_strip(
        mesh, rates=rates, wells=_wells(5, on_fixed_cell=True), drainage_m2_s=DRAIN_M2_S
    )

    np.testing.assert_allclose(held_state.head_history_m, plain_state.head_history_m, atol=1e-12)
    for name in ("recharge", "well", "constant_head"):
        np.testing.assert_allclose(held[name], plain[name], rtol=1e-12, atol=1e-18)
    np.testing.assert_allclose(held["drain"], 0.0)
    np.testing.assert_allclose(held["well"].sum(axis=1), WELL_M3_S)
    _assert_budget_closes(mesh, held_state, held)
    np.testing.assert_allclose(held_payload["residual_history_m3_s"][:, 0], 0.0, atol=0.0)


def test_a_well_on_a_fixed_cell_is_reported(caplog) -> None:
    wells = np.asarray([[WELL_M3_S, 0.0, WELL_M3_S]] * 2)
    prescribed = (np.asarray([20.0, np.nan, np.nan]),) * 2
    with caplog.at_level(logging.WARNING):
        _warn_wells_on_cells_with_an_imposed_head(wells, prescribed)

    assert "[0]" in caplog.text
    assert "pump nothing" in caplog.text
