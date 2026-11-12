"""``solver.backend`` and the flow process name one solver."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import IncompatibleCapabilitiesError


def _validate(payload: dict[str, Any]) -> HydroModPyConfig:
    """Validate a payload that declares its DEM under ``[[data.dem.sources]]``."""
    return HydroModPyConfig.model_validate(payload, context={"allow_dem_bootstrap": True})


def _payload(**sections: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "site": {"name": "site_a"},
        "geographic": {"catchment": {"kind": "dem"}},
        "data": {"dem": {"sources": [{"source": "file", "path": "inputs/dem.tif"}]}},
    }
    payload.update(sections)
    return payload


def _flow(solver: str) -> dict[str, Any]:
    return {"process": [{"id": "flow_main", "kind": "flow", "solvers": [solver]}]}


def _mesh(solver: str) -> dict[str, Any]:
    """The mesh section the solver reads: Boussinesq reads triangles only."""
    if solver != "boussinesq":
        return {}
    return {"mesh": {"engine": "triangle", "families": {"rivers": "none"}}}


def test_two_keys_with_two_names_are_refused() -> None:
    with pytest.raises(ValidationError, match="must name the same solver"):
        _validate(
            _payload(
                simulation=_flow("modflow_nwt"),
                solver={"backend": "modflow6"},
            )
        )


def test_a_transport_process_under_the_boussinesq_flow_is_refused() -> None:
    simulation = {
        "process": [
            {"id": "flow_main", "kind": "flow", "solvers": ["boussinesq"]},
            {"id": "particles", "kind": "transport", "solvers": ["modpath"]},
        ]
    }

    with pytest.raises(
        IncompatibleCapabilitiesError,
        match=r"the transport solver 'modpath' reads face_flow, and solver.backend = 'boussinesq'",
    ):
        _validate(_payload(simulation=simulation))


def test_a_written_backend_still_refuses_a_later_flow_solver() -> None:
    from hydromodpy.solver.base.simulation_config import SimulationConfig

    cfg = _validate(_payload(simulation=_flow("modflow6"), solver={"backend": "modflow6"}))

    with pytest.raises(ValidationError, match="must name the same solver"):
        cfg.simulation = SimulationConfig.model_validate(_flow("modflow_nwt"))
