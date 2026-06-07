"""WP12 - dead code and defensive fallbacks are gone, live paths preserved."""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

import hydromodpy.solver.modflow_grid as grid_pkg
from hydromodpy.solver.modflow6 import Modflow6
from hydromodpy.solver.modflow6.builders import build_evt_stress_period_data
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

from ._test_modflow6_boundary_conditions_builders import _build_model

_DELETED_DELEGATORS = (
    "_get_budget_records_or_none",
    "_open_budget_file",
    "_build_unstructured_cell_adjacency",
    "_accumulate_unstructured_cell_values",
    "_native_mesh_exports_enabled",
    "_native_cell_series_payload",
    "_export_native_mesh_outputs",
    "_east_side_cell_ids",
    "_compute_chd_outlet_discharge_east_side_m3_s",
)


def test_to_export_array_structured_reshape_and_unstructured_identity() -> None:
    structured = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=np.full((2, 3), 10.0),
        botm=np.zeros((1, 2, 3)),
        xoff=300000.0,
        yoff=6800000.0,
    )
    model = _build_model()
    model.solver_mesh = structured

    out = model._to_export_array(np.arange(6, dtype=float))
    assert out.shape == (2, 3)
    assert out.tolist() == [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]]

    out_multilayer = model._to_export_array(np.arange(12, dtype=float).reshape(2, 6))
    assert out_multilayer.shape == (2, 2, 3)

    # Unstructured: reshape is the identity.
    from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

    planar = HydroMesh(
        vertices=np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=float),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2], [0, 2, 3]], dtype=int)),),
    )
    model.solver_mesh = SolverMesh(
        planar_mesh=planar,
        top=np.array([1.0, 1.0]),
        botm=np.array([[0.0, 0.0]]),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )
    flat = np.array([3.0, 7.0])
    assert model._to_export_array(flat).tolist() == [3.0, 7.0]


def test_mf6_evt_extinction_depth_from_process_specific() -> None:
    model = _build_model()
    model.flow_regime = "transient"
    model._evt_rate_payload = {0: 0.0, 1: 1.0e-6}
    model.modflow_config = _coerce_modflow6_config(
        {"process_specific": {"evt_extinction_depth": 2.5}}
    )
    solver_mesh = SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=np.full((2, 3), 10.0),
        botm=np.zeros((1, 2, 3)),
    )

    evt_spd = build_evt_stress_period_data(
        model,
        solver_mesh,
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )

    assert evt_spd is not None
    # Record layout: [layer, cell_id, surface, rate, extinction_depth].
    assert evt_spd[1][0][4] == pytest.approx(2.5)

    # Default config keeps the 1.0 m extinction depth.
    model.modflow_config = _coerce_modflow6_config({})
    evt_default = build_evt_stress_period_data(
        model,
        solver_mesh,
        ocean_support_mask=np.zeros(6, dtype=bool),
        stream_support_mask=np.zeros(6, dtype=bool),
    )
    assert evt_default[1][0][4] == pytest.approx(1.0)


def test_no_dead_symbols_after_cleanup() -> None:
    import hydromodpy.solver.modflow6 as mf6_pkg

    # Deleted modules.
    assert importlib.util.find_spec("hydromodpy.solver.modflow6.postprocess_ops") is None
    assert importlib.util.find_spec("hydromodpy.solver.modflow_grid.grid_mapping") is None

    # Deleted public symbols.
    assert not hasattr(mf6_pkg, "Modflow6RuntimeParams")
    assert not hasattr(SolverMesh, "from_extruded_mesh")
    for name in ("describe_grid", "DisDescriptor", "DisvDescriptor", "DiscretizationKind"):
        assert not hasattr(grid_pkg, name)

    # Deleted delegator methods.
    for name in _DELETED_DELEGATORS:
        assert not hasattr(Modflow6, name)

    # The live export reshaper is preserved (postprocess depends on it).
    assert hasattr(Modflow6, "_to_export_array")
