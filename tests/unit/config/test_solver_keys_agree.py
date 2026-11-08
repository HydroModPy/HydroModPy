"""``solver.backend`` and the flow process name one solver."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from tests._helpers.fake_solvers import fake_adapter


def _payload(**sections: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "site": {"name": "site_a"},
        "geographic": {"catchment": {"kind": "dem", "dem_init_path": "dem.tif"}},
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


@pytest.mark.parametrize(
    ("solver", "expected"),
    [("modflow6", "modflow6"), ("modflow_nwt", "modflow_nwt"), ("boussinesq", "boussinesq")],
)
def test_backend_follows_the_flow_process_when_unset(solver: str, expected: str) -> None:
    cfg = HydroModPyConfig.model_validate(_payload(simulation=_flow(solver), **_mesh(solver)))

    assert cfg.solver.backend_name == expected


def test_backend_follows_the_process_and_keeps_the_other_solver_keys() -> None:
    cfg = HydroModPyConfig.model_validate(
        _payload(simulation=_flow("modflow_nwt"), solver={"sink_fill": True})
    )

    assert cfg.solver.backend_name == "modflow_nwt"
    assert cfg.solver.sink_fill is True


def test_a_plugin_solver_name_is_the_backend_string(isolated_solvers) -> None:
    isolated_solvers.solvers.register(fake_adapter("my_plugin"))
    cfg = HydroModPyConfig.model_validate(_payload(simulation=_flow("my_plugin")))

    assert cfg.solver.backend == "my_plugin"
    assert cfg.solver.backend_name == "my_plugin"


def test_two_keys_with_the_same_name_load() -> None:
    cfg = HydroModPyConfig.model_validate(
        _payload(
            simulation=_flow("modflow_nwt"),
            solver={"backend": "modflow_nwt"},
        )
    )

    assert cfg.solver.backend_name == "modflow_nwt"


def test_two_keys_with_two_names_are_refused() -> None:
    with pytest.raises(ValidationError, match="must name the same solver"):
        HydroModPyConfig.model_validate(
            _payload(
                simulation=_flow("modflow_nwt"),
                solver={"backend": "modflow6"},
            )
        )


def test_backend_alone_still_selects_the_solver() -> None:
    cfg = HydroModPyConfig.model_validate(_payload(solver={"backend": "modflow_nwt"}))

    assert cfg.solver.backend_name == "modflow_nwt"


def test_checks_read_the_solver_the_process_names() -> None:
    # Before, the backend stayed at its default 'modflow6' and the check passed.
    with pytest.raises(
        IncompatibleCapabilitiesError,
        match=r"solver.backend = 'modflow_nwt' does not honor flow\.sinks_sources\.sfr",
    ):
        HydroModPyConfig.model_validate(
            _payload(
                simulation=_flow("modflow_nwt"),
                flow={"bc": {"drainage": {}}, "sinks_sources": {"sfr": {"main": {}}}},
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
        ValidationError,
        match=r"the transport solver 'modpath' follows modflow_nwt, and solver.backend is 'boussinesq'",
    ):
        HydroModPyConfig.model_validate(_payload(simulation=simulation))


def test_the_boussinesq_flow_alone_loads_with_its_default_transport_section() -> None:
    cfg = HydroModPyConfig.model_validate(
        _payload(simulation=_flow("boussinesq"), **_mesh("boussinesq"))
    )

    assert cfg.solver.backend_name == "boussinesq"


def test_a_derived_backend_follows_a_later_flow_solver() -> None:
    from hydromodpy.solver.base.simulation_config import SimulationConfig

    cfg = HydroModPyConfig.model_validate(_payload(simulation=_flow("modflow6")))
    assert "backend" not in cfg.solver.model_fields_set

    cfg.simulation = SimulationConfig.model_validate(_flow("modflow_nwt"))

    assert cfg.solver.backend_name == "modflow_nwt"
    assert "backend" not in cfg.solver.model_fields_set


def test_a_written_backend_still_refuses_a_later_flow_solver() -> None:
    from hydromodpy.solver.base.simulation_config import SimulationConfig

    cfg = HydroModPyConfig.model_validate(
        _payload(simulation=_flow("modflow6"), solver={"backend": "modflow6"})
    )

    with pytest.raises(ValidationError, match="must name the same solver"):
        cfg.simulation = SimulationConfig.model_validate(_flow("modflow_nwt"))
