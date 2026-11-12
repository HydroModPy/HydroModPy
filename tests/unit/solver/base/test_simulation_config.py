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


REFUSED = (
    ("flow", ["nope"], "boussinesq, linear_reservoir, modflow6, modflow_nwt"),
    ("flow", ["modpath"], "boussinesq, linear_reservoir, modflow6, modflow_nwt"),
    ("transport", ["nope"], "modflow6, modflow6_prt, modpath, mt3dms"),
    ("transport", ["boussinesq"], "modflow6, modflow6_prt, modpath, mt3dms"),
)


def test_a_process_without_a_solver_is_refused() -> None:
    with pytest.raises(ValidationError, match="require at least one solver"):
        SimulationConfig.model_validate(
            {"process": [{"id": "flow_main", "kind": "flow", "solvers": [" "]}]}
        )
