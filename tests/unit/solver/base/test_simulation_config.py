"""``[[simulation.process]]``: each solver name is a registered solver of its process kind."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.solver.base.simulation_config import SimulationConfig

pytestmark = pytest.mark.fast

ACCEPTED = (
    ("flow", ["modflow6"], ["modflow6"]),
    ("flow", [" modflow_nwt "], ["modflow_nwt"]),
    ("transport", ["modpath"], ["modpath"]),
    ("transport", ["modflow6_prt"], ["modflow6_prt"]),
)


@pytest.mark.parametrize(("kind", "solvers", "expected"), ACCEPTED)
def test_a_registered_solver_of_the_kind_is_kept_stripped(
    kind: str, solvers: list[str], expected: list[str]
) -> None:
    cfg = SimulationConfig.model_validate(
        {"process": [{"id": f"{kind}_main", "kind": kind, "solvers": solvers}]}
    )

    assert cfg.process[0].solvers == expected


REFUSED = (
    ("flow", ["nope"], "boussinesq, modflow6, modflow_nwt"),
    ("flow", ["modpath"], "boussinesq, modflow6, modflow_nwt"),
    ("transport", ["nope"], "modflow6, modflow6_prt, modpath, mt3dms"),
    ("transport", ["boussinesq"], "modflow6, modflow6_prt, modpath, mt3dms"),
)


@pytest.mark.parametrize(("kind", "solvers", "served"), REFUSED)
def test_a_name_the_kind_does_not_serve_is_refused_with_the_names_served(
    kind: str, solvers: list[str], served: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        SimulationConfig.model_validate(
            {"process": [{"id": f"{kind}_main", "kind": kind, "solvers": solvers}]}
        )

    text = str(caught.value)
    assert f"simulation.process.solvers names {solvers[0]!r}" in text
    assert f"this installation serves {served}." in text
    assert "'hydromodpy.solver' entry-point group" in text


def test_a_plugin_solver_is_accepted_once_registered(isolated_solvers) -> None:
    from tests._helpers.fake_solvers import fake_adapter

    isolated_solvers.solvers.register(fake_adapter("plugged"))

    cfg = SimulationConfig.model_validate(
        {"process": [{"id": "flow_main", "kind": "flow", "solvers": ["plugged"]}]}
    )

    assert cfg.process[0].solvers == ["plugged"]


def test_a_process_without_a_solver_is_refused() -> None:
    with pytest.raises(ValidationError, match="require at least one solver"):
        SimulationConfig.model_validate(
            {"process": [{"id": "flow_main", "kind": "flow", "solvers": [" "]}]}
        )
