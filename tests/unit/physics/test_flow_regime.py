from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.flow import (
    FlowConfig,
    normalize_flow_regime,
)
from hydromodpy.solver.boussinesq.discretization.time import resolve_time_scheme
from hydromodpy.solver.boussinesq.property_mapping import (
    resolve_required_flow_properties as resolve_boussinesq_required_properties,
)
from hydromodpy.solver.modflow_common.discretization_temporal import (
    build_temporal_discretization_from_time_grid,
)
from hydromodpy.solver.modflow_nwt.modflow.property_mapping import (
    resolve_required_flow_properties as resolve_modflow_required_properties,
)
from hydromodpy.solver.utils.temporal.tmesh_generation import TMesh_Generation


class _Window:
    start = None


class _TimeGrid:
    period_lengths_seconds = [86400.0, 86400.0]
    window = _Window()


def test_flow_regime_normalizes_supported_values() -> None:
    assert normalize_flow_regime("steady") == "steady"
    assert normalize_flow_regime("transient") == "transient"


def test_flow_config_accepts_steady() -> None:
    cfg = FlowConfig(flow_regime="steady")
    assert cfg.flow_regime == "steady"


def test_flow_config_steady_constructor_returns_steady_config() -> None:
    cfg = FlowConfig.steady(K=5e-5)
    assert cfg.flow_regime == "steady"
    assert cfg.param_list == ["K"]


def test_temporal_mesh_accepts_steady() -> None:
    builder = TMesh_Generation(flow_regime="steady", nper=2, lenper=1)
    assert builder.flow_regime == "steady"
    mesh = builder.run()
    assert np.all(mesh.steady_state)


def test_temporal_mesh_setter_validates_steady() -> None:
    builder = TMesh_Generation(flow_regime="transient", nper=2, lenper=1)
    builder.flow_regime = "steady"
    assert builder.flow_regime == "steady"
    mesh = builder.run()
    assert np.all(mesh.steady_state)


def test_solver_helpers_treat_steady_as_steady_state() -> None:
    assert resolve_time_scheme("steady").id == "steady_balance"
    assert resolve_modflow_required_properties(flow_regime="steady") == frozenset({"K"})
    assert resolve_boussinesq_required_properties(flow_regime="steady") == frozenset({"K"})
    temporal = build_temporal_discretization_from_time_grid(
        time_grid=_TimeGrid(),
        flow_regime="steady",
        firstpersteady=False,
    )
    assert np.all(temporal.steady)


def test_unknown_flow_regime_still_fails() -> None:
    with pytest.raises(ValueError, match="steady.*transient"):
        normalize_flow_regime("unknown")
