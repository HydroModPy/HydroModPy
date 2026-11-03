"""Declaring a lake on a non-modflow6 backend raises a typed error.

A lake is a MODFLOW 6 LAK advanced package; no other backend implements it.
The cross-section config validator and the boussinesq
solver-contract fail-fast must both surface the typed
:class:`IncompatibleCapabilitiesError` (HMPY.E407), not a bare ValueError or a
silent pass.
"""

from __future__ import annotations

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.physics.flow.flow import Flow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.boussinesq.solver_contract import assert_supported_runtime_subset
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def _base_kwargs(tmp_path) -> dict:
    return {
        "workflow": {"mode": "simulation"},
        "workspace": WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        "geographic": GeographicConfig(source_mode="synthetic"),
    }


LAKES = {"lac0": {"bedleak": 0.1, "initial_stage": "85 m"}}


@pytest.mark.parametrize("backend", ["boussinesq", "modflow_nwt"])
def test_a_lake_on_another_backend_raises_typed_error(tmp_path, backend: str) -> None:
    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            solver=SolverConfig(backend={"kind": backend}),
            flow=FlowConfig(sinks_sources={"lakes": LAKES}),
        )
    assert excinfo.value.code == "HMPY.E407"
    assert backend in str(excinfo.value)


def test_a_switched_off_lake_is_accepted_on_any_backend(tmp_path) -> None:
    lakes = {"lac0": {**LAKES["lac0"], "enabled": False}}
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        solver=SolverConfig(backend={"kind": "modflow_nwt"}),
        flow=FlowConfig(sinks_sources={"lakes": lakes}),
    )
    assert cfg.flow.active_bc == []


def test_lake_on_modflow6_is_accepted(tmp_path) -> None:
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        solver=SolverConfig(backend={"kind": "modflow6"}),
        flow=FlowConfig(sinks_sources={"lakes": LAKES}),
    )
    assert cfg.solver.backend_name == "modflow6"
    assert "lake" in cfg.flow.active_bc
    assert "lac0" in cfg.flow.sinks_sources.lakes


def test_boussinesq_solver_contract_rejects_lake_with_typed_error() -> None:
    flow = Flow(FlowConfig(sinks_sources={"lakes": LAKES}))
    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        assert_supported_runtime_subset(flow)
    assert "lake" in str(excinfo.value)
    assert excinfo.value.code == "HMPY.E407"
