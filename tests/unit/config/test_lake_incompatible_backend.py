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
from hydromodpy.physics.flow.sinks_sources import FlowSinksSourcesConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.boussinesq.solver_contract import assert_supported_runtime_subset
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def _base_kwargs(tmp_path) -> dict:
    return {
        "workflow": {"mode": "simulation"},
        "workspace": WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        "geographic": GeographicConfig(source_mode="synthetic"),
    }


def test_lake_active_bc_on_boussinesq_raises_typed_error(tmp_path) -> None:
    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            solver=SolverConfig(backend={"backend": "boussinesq"}),
            flow=FlowConfig(active_bc=["lake"]),
        )
    assert excinfo.value.code == "HMPY.E407"
    assert "boussinesq" in str(excinfo.value)


def test_reservoir_active_bc_on_modflow_nwt_raises_typed_error(tmp_path) -> None:
    with pytest.raises(IncompatibleCapabilitiesError):
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            solver=SolverConfig(backend={"backend": "modflow_nwt"}),
            flow=FlowConfig(active_bc=["reservoir"]),
        )


def test_lake_on_modflow6_is_accepted(tmp_path) -> None:
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        solver=SolverConfig(backend={"backend": "modflow6"}),
        flow=FlowConfig(active_bc=["lake"]),
    )
    assert cfg.solver.backend_name == "modflow6"
    assert "lake" in cfg.flow.active_bc


def test_lakes_declared_without_active_bc_is_rejected(tmp_path) -> None:
    # Declaring lakes but not listing 'lake'/'reservoir' in active_bc would build
    # no LAK package: the builder only activates on active_bc. The validator must
    # catch this rather than let the lakes be silently ignored.
    with pytest.raises(ValueError, match="active_bc"):
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            solver=SolverConfig(backend={"backend": "modflow6"}),
            flow=FlowConfig(
                active_bc=[],
                sinks_sources=FlowSinksSourcesConfig(
                    lakes={"lac0": {"bedleak": 0.1, "stageinit": "85 m"}}
                ),
            ),
        )


def test_lakes_with_active_bc_lake_is_accepted(tmp_path) -> None:
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        solver=SolverConfig(backend={"backend": "modflow6"}),
        flow=FlowConfig(
            active_bc=["lake"],
            sinks_sources=FlowSinksSourcesConfig(
                lakes={"lac0": {"bedleak": 0.1, "stageinit": "85 m"}}
            ),
        ),
    )
    assert "lac0" in cfg.flow.sinks_sources.lakes


def test_boussinesq_solver_contract_rejects_lake_with_typed_error() -> None:
    flow = Flow(FlowConfig(active_bc=["lake"]))
    with pytest.raises(IncompatibleCapabilitiesError) as excinfo:
        assert_supported_runtime_subset(flow)
    assert "lake" in str(excinfo.value)
    assert excinfo.value.code == "HMPY.E407"
