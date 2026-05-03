from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.flow import (
    FlowConfig,
    is_permanent_flow_regime,
    normalize_flow_regime,
)
from hydromodpy.solver.boussinesq.discretization.time import resolve_time_scheme
from hydromodpy.solver.boussinesq.property_mapping import (
    resolve_required_flow_properties as resolve_boussinesq_required_properties,
)
from hydromodpy.solver.modflow_common.property_mapping import (
    resolve_required_flow_properties as resolve_modflow_required_properties,
)
from hydromodpy.solver.modflow_grid.discretization_temporal import (
    build_temporal_discretization_from_time_grid,
)
from hydromodpy.solver.utils.temporal.tmesh_generation import TmeshGenerator


class _Window:
    start = None


class _TimeGrid:
    period_lengths_seconds = [86400.0, 86400.0]
    window = _Window()


def test_permanent_flow_regime_normalizes_to_steady() -> None:
    assert normalize_flow_regime("permanent") == "steady"
    assert is_permanent_flow_regime("permanent") is True
    assert is_permanent_flow_regime("steady") is True
    assert is_permanent_flow_regime("transient") is False


def test_flow_config_accepts_permanent_alias() -> None:
    cfg = FlowConfig(flow_regime="permanent")
    assert cfg.flow_regime == "steady"


def test_flow_config_permanent_constructor_returns_steady_config() -> None:
    cfg = FlowConfig.permanent(K=5e-5)
    assert cfg.flow_regime == "steady"
    assert cfg.param_list == ["K"]


def test_temporal_mesh_accepts_permanent_alias() -> None:
    builder = TmeshGenerator(flow_regime="permanent", nper=2, lenper=1)
    assert builder.flow_regime == "steady"
    mesh = builder.run()
    assert np.all(mesh.steady_state)


def test_temporal_mesh_setter_validates_permanent_alias() -> None:
    builder = TmeshGenerator(flow_regime="transient", nper=2, lenper=1)
    builder.flow_regime = "permanent"
    assert builder.flow_regime == "steady"
    mesh = builder.run()
    assert np.all(mesh.steady_state)


def test_solver_helpers_treat_permanent_as_steady() -> None:
    assert resolve_time_scheme("permanent").id == "steady_balance"
    assert resolve_modflow_required_properties(flow_regime="permanent") == frozenset({"K"})
    assert resolve_boussinesq_required_properties(flow_regime="permanent") == frozenset({"K"})
    temporal = build_temporal_discretization_from_time_grid(
        time_grid=_TimeGrid(),
        flow_regime="permanent",
        firstpersteady=False,
    )
    assert np.all(temporal.steady)


def test_unknown_flow_regime_still_fails() -> None:
    with pytest.raises(ValueError, match="steady.*permanent.*transient"):
        normalize_flow_regime("unknown")
