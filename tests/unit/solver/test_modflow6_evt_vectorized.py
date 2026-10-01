"""Vectorized EVTA build matches the list -> collapse -> array-payload chain.

``build_evt_array_stress_period_data`` is a numpy-only replacement for
``build_evt_stress_period_data`` -> ``collapse_identical_periods`` ->
``evt_list_spd_to_array_payload``, used when ``evt_routing_is_layer0_only``
holds (every kept EVT cell's first active layer is 0). It exists to avoid the
list builder's O(ncells x nper) Python records, which run into the tens of
millions and several GB on a real daily chronicle. These tests build both
paths on small synthetic models and assert byte-for-byte equality.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders import (
    build_evt_array_stress_period_data,
    build_evt_stress_period_data,
    collapse_identical_periods,
    evt_list_spd_to_array_payload,
    evt_routing_is_layer0_only,
)
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

from ._test_modflow6_boundary_conditions_builders import _build_model


def _single_layer_mesh() -> SolverMesh:
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype=float)
    return SolverMesh.from_structured_arrays(nrow=2, ncol=3, top=top, botm=np.stack([botm]))


def _reference_array_payload(
    model, solver_mesh, *, ocean_support_mask, stream_support_mask, lake_cell_ids
):
    """The pre-existing list -> collapse -> array chain, used as ground truth."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        evt_spd = build_evt_stress_period_data(
            model,
            solver_mesh,
            ocean_support_mask=ocean_support_mask,
            stream_support_mask=stream_support_mask,
            lake_cell_ids=lake_cell_ids,
        )
    if evt_spd is None:
        return None
    evt_spd = collapse_identical_periods(evt_spd)
    return evt_list_spd_to_array_payload(evt_spd, top_flat=solver_mesh.top, ncpl=int(model.ncpl))


def test_vectorized_evt_matches_list_path_with_masks_and_collapsing() -> None:
    """Steady first period, lake/ocean/stream masks, a quiet period and a repeat."""
    model = _build_model()
    model.nper = 5
    model.steady = np.array([True, False, False, False, False])
    solver_mesh = _single_layer_mesh()

    # Cell layout (row-major, 2x3): 0 1 2 / 3 4 5.
    ocean_mask = np.array([False, False, True, False, False, False])
    stream_mask = np.array([False, False, False, False, False, True])
    lake_cell_ids = [4]
    # Kept cells (not ocean/stream/lake): 0, 1, 3.

    model._evt_rate_payload = {
        # Period 0 (steady): mean deficit already folded in upstream. Cell 1 is
        # kept but non-positive -> no record either way.
        0: np.array([5.0e-7, 0.0, 9.0e-7, 3.0e-7, 9.0e-7, 9.0e-7], dtype=float),
        # Period 1: transient, different kept-cell pattern than period 0.
        1: np.array([1.0e-6, 2.0e-6, 0.0, 0.0, 5.0e-6, 0.0], dtype=float),
        # Period 2: no deficit anywhere (a real change point vs period 1).
        2: np.zeros(6, dtype=float),
        # Period 3: repeats period 1's values exactly (a change point vs period 2).
        3: np.array([1.0e-6, 2.0e-6, 0.0, 0.0, 5.0e-6, 0.0], dtype=float),
        # Period 4: repeats period 3 exactly -> dropped by collapsing.
        4: np.array([1.0e-6, 2.0e-6, 0.0, 0.0, 5.0e-6, 0.0], dtype=float),
    }

    assert evt_routing_is_layer0_only(
        model,
        solver_mesh,
        ocean_support_mask=ocean_mask,
        stream_support_mask=stream_mask,
        lake_cell_ids=lake_cell_ids,
    )

    reference = _reference_array_payload(
        model,
        solver_mesh,
        ocean_support_mask=ocean_mask,
        stream_support_mask=stream_mask,
        lake_cell_ids=lake_cell_ids,
    )
    assert reference is not None
    ref_rate_by_period, ref_surface, ref_depth = reference

    with pytest.warns(RuntimeWarning, match="fixed EVT extinction depth"):
        vectorized = build_evt_array_stress_period_data(
            model,
            solver_mesh,
            ocean_support_mask=ocean_mask,
            stream_support_mask=stream_mask,
            lake_cell_ids=lake_cell_ids,
        )
    assert vectorized is not None
    vec_rate_by_period, vec_surface, vec_depth = vectorized

    assert vec_depth == pytest.approx(ref_depth)
    assert np.array_equal(vec_surface, ref_surface)
    assert set(vec_rate_by_period) == set(ref_rate_by_period)
    # Change points only: period 4 collapses onto period 3, period 2 is kept
    # even though it carries no deficit (it differs from period 1).
    assert set(vec_rate_by_period) == {0, 1, 2, 3}
    for kper in ref_rate_by_period:
        assert np.array_equal(vec_rate_by_period[kper], ref_rate_by_period[kper])

    # Masked and non-positive cells never carry a rate.
    for arr in vec_rate_by_period.values():
        assert arr[2] == 0.0  # ocean
        assert arr[4] == 0.0  # lake
        assert arr[5] == 0.0  # stream
    assert vec_rate_by_period[0][1] == 0.0  # kept but rate <= 0


def test_vectorized_evt_respects_extinction_depth_floor() -> None:
    model = _build_model()
    model.nper = 1
    model.steady = np.array([False])
    model.modflow_config = _coerce_modflow6_config(
        {"process_specific": {"evt_extinction_depth": 1.0e-10}}
    )
    model._evt_rate_payload = {0: 1.0e-6}
    solver_mesh = _single_layer_mesh()
    ocean_mask = np.zeros(6, dtype=bool)
    stream_mask = np.zeros(6, dtype=bool)

    assert evt_routing_is_layer0_only(
        model,
        solver_mesh,
        ocean_support_mask=ocean_mask,
        stream_support_mask=stream_mask,
    )

    reference = _reference_array_payload(
        model,
        solver_mesh,
        ocean_support_mask=ocean_mask,
        stream_support_mask=stream_mask,
        lake_cell_ids=(),
    )
    assert reference is not None
    _, _, ref_depth = reference
    assert ref_depth == pytest.approx(1.0e-6)

    with pytest.warns(RuntimeWarning):
        vectorized = build_evt_array_stress_period_data(
            model,
            solver_mesh,
            ocean_support_mask=ocean_mask,
            stream_support_mask=stream_mask,
        )
    assert vectorized is not None
    _, _, vec_depth = vectorized
    assert vec_depth == pytest.approx(1.0e-6)


def test_vectorized_evt_returns_none_without_deficit() -> None:
    model = _build_model()
    model.nper = 2
    model.steady = np.array([False, False])
    solver_mesh = _single_layer_mesh()
    ocean_mask = np.zeros(6, dtype=bool)
    stream_mask = np.zeros(6, dtype=bool)

    # No _evt_rate_payload attribute at all.
    assert (
        build_evt_array_stress_period_data(
            model, solver_mesh, ocean_support_mask=ocean_mask, stream_support_mask=stream_mask
        )
        is None
    )

    # Payload present but never positive once masked: same None as the list path.
    model._evt_rate_payload = {0: np.zeros(6, dtype=float), 1: -np.ones(6, dtype=float)}
    assert (
        build_evt_stress_period_data(
            model, solver_mesh, ocean_support_mask=ocean_mask, stream_support_mask=stream_mask
        )
        is None
    )
    assert (
        build_evt_array_stress_period_data(
            model, solver_mesh, ocean_support_mask=ocean_mask, stream_support_mask=stream_mask
        )
        is None
    )


def _two_layer_mesh(inactive_mask: np.ndarray) -> SolverMesh:
    ncpl = 3
    vertices = np.array(
        [[0, 0], [1, 0], [2, 0], [3, 0], [0, 1], [1, 1], [2, 1], [3, 1]], dtype=float
    )
    conn = np.array([[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6]], dtype=int)
    return SolverMesh(
        planar_mesh=HydroMesh(
            vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),)
        ),
        top=np.full(ncpl, 10.0),
        botm=np.array([[5.0, 5.0, 5.0], [0.0, 0.0, 0.0]]),
        inactive_mask=inactive_mask,
    )


def test_vectorized_evt_not_eligible_when_a_kept_cell_sits_on_a_lower_layer() -> None:
    """A kept cell whose first active layer is 1 forces the list fallback."""
    # cell0 active in layer 0; cell1 inactive in layer 0 but active in layer 1.
    inactive = np.array([[False, True, True], [False, False, True]])
    mesh = _two_layer_mesh(inactive)
    model = _build_model()
    model.nper = 1
    model.ncpl = 3
    model._evt_rate_payload = {0: 1.0e-6}
    ocean_mask = np.zeros(3, dtype=bool)
    stream_mask = np.zeros(3, dtype=bool)

    assert not evt_routing_is_layer0_only(
        model, mesh, ocean_support_mask=ocean_mask, stream_support_mask=stream_mask
    )

    # The list path (unaffected by this change) still places EVT on layer 1 for cell 1.
    with pytest.warns(RuntimeWarning):
        evt_spd = build_evt_stress_period_data(
            model, mesh, ocean_support_mask=ocean_mask, stream_support_mask=stream_mask
        )
    assert evt_list_spd_to_array_payload(evt_spd, top_flat=mesh.top, ncpl=3) is None
