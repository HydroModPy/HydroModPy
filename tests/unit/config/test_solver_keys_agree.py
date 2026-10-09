"""``solver.backend`` and the flow process name one solver."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from hydromodpy.solver.base import registry


def _payload(**sections: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "geographic": {"catchment": {"catch_def": "dem", "dem_init_path": "dem.tif"}},
    }
    payload.update(sections)
    return payload


def _flow(solver: str) -> dict[str, Any]:
    return {"process": [{"id": "flow_main", "type": "flow", "solvers": [solver]}]}


@pytest.mark.parametrize(
    ("solver", "expected"),
    [("modflow6", "modflow6"), ("modflow_nwt", "modflow_nwt"), ("boussinesq", "boussinesq")],
)
def test_backend_follows_the_flow_process_when_unset(solver: str, expected: str) -> None:
    cfg = HydroModPyConfig.model_validate(_payload(simulation=_flow(solver)))

    assert cfg.solver.backend_name == expected


def test_backend_follows_the_process_and_keeps_the_other_solver_keys() -> None:
    cfg = HydroModPyConfig.model_validate(
        _payload(simulation=_flow("modflow_nwt"), solver={"sink_fill": True})
    )

    assert cfg.solver.backend_name == "modflow_nwt"
    assert cfg.solver.sink_fill is True


class _PluginAdapter:
    process_type = "flow"
    solver_name = "my_plugin"
    requires: tuple[tuple[str, str], ...] = ()

    def validate(self, ctx): ...

    def execute(self, ctx): ...

    def cleanup(self, ctx): ...

    def extract_observables(self, ctx, store, requests, **kwargs):
        return {}


def test_a_plugin_solver_name_gives_the_custom_backend() -> None:
    registry.register("flow", "my_plugin", _PluginAdapter)
    try:
        cfg = HydroModPyConfig.model_validate(_payload(simulation=_flow("my_plugin")))
    finally:
        registry.unregister("flow", "my_plugin")

    assert cfg.solver.backend.backend == "custom"
    assert cfg.solver.backend_name == "my_plugin"


def test_two_keys_with_the_same_name_load() -> None:
    cfg = HydroModPyConfig.model_validate(
        _payload(
            simulation=_flow("modflow_nwt"),
            solver={"backend": {"backend": "modflow_nwt"}},
        )
    )

    assert cfg.solver.backend_name == "modflow_nwt"


def test_two_keys_with_two_names_are_refused() -> None:
    with pytest.raises(ValidationError, match="must name the same solver"):
        HydroModPyConfig.model_validate(
            _payload(
                simulation=_flow("modflow_nwt"),
                solver={"backend": {"backend": "modflow6"}},
            )
        )


def test_backend_alone_still_selects_the_solver() -> None:
    cfg = HydroModPyConfig.model_validate(_payload(solver={"backend": {"backend": "modflow_nwt"}}))

    assert cfg.solver.backend_name == "modflow_nwt"


def test_checks_read_the_solver_the_process_names() -> None:
    # Before, the backend stayed at its default 'modflow6' and the check passed.
    with pytest.raises(IncompatibleCapabilitiesError, match="'sfr' boundary"):
        HydroModPyConfig.model_validate(
            _payload(simulation=_flow("modflow_nwt"), flow={"active_bc": ["drainage", "sfr"]})
        )


def test_a_transport_process_under_the_boussinesq_flow_is_refused() -> None:
    simulation = {
        "process": [
            {"id": "flow_main", "type": "flow", "solvers": ["boussinesq"]},
            {"id": "particles", "type": "transport", "solvers": ["modpath"]},
        ]
    }

    with pytest.raises(ValidationError, match=r"'boussinesq' runs no transport.*modpath"):
        HydroModPyConfig.model_validate(_payload(simulation=simulation))


def test_the_boussinesq_flow_alone_loads_with_its_default_transport_section() -> None:
    cfg = HydroModPyConfig.model_validate(_payload(simulation=_flow("boussinesq")))

    assert cfg.solver.backend_name == "boussinesq"
