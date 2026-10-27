"""WP12 - dead code and defensive fallbacks are gone, live paths preserved."""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

import hydromodpy.solver.modflow_grid as grid_pkg
from hydromodpy.solver.modflow6 import Modflow6, Modflow6Transport
from hydromodpy.solver.modflow6.builders import build_evt_stress_period_data
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mf6_toy_models import toy_model
from tests._helpers.solver_meshes import solver_mesh_from, solver_mesh_from_structured_arrays

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


def test_mf6_evt_extinction_depth_from_process_specific() -> None:
    model = toy_model()
    model.flow_regime = "transient"
    model._evt_rate_payload = {0: 0.0, 1: 1.0e-6}
    model.modflow_config = _coerce_modflow6_config(
        {"process_specific": {"evt_extinction_depth": 2.5}}
    )
    solver_mesh = solver_mesh_from_structured_arrays(
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
    assert importlib.util.find_spec("hydromodpy.solver.modflow6.postprocess") is None
    assert importlib.util.find_spec("hydromodpy.solver.modflow6.support.diagnostics") is None
    assert importlib.util.find_spec("hydromodpy.solver.modflow_grid.grid_mapping") is None

    # Deleted public symbols.
    assert not hasattr(mf6_pkg, "Modflow6RuntimeParams")
    assert not hasattr(SolverMesh, "from_extruded_mesh")
    for name in ("describe_grid", "DisDescriptor", "DisvDescriptor", "DiscretizationKind"):
        assert not hasattr(grid_pkg, name)

    # Deleted delegator methods.
    for name in _DELETED_DELEGATORS:
        assert not hasattr(Modflow6, name)
    assert not hasattr(Modflow6, "post_processing")
    assert not hasattr(Modflow6Transport, "post_processing")
