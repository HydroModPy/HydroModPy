"""``[solver]``: the flow solver named by a string, and the settings table of each solver.

``solver.backend`` is checked against the registry while the file is read, and
every other key of ``[solver]`` beyond its switches is the settings table of a
flow solver, checked by the ``options`` class that solver declares.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowConfig
from tests._helpers.fake_solvers import fake_adapter

pytestmark = pytest.mark.fast

SERVED = "this installation serves boussinesq, linear_reservoir, modflow6, modflow_nwt"


class _PluginOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relaxation: float = 1.0


ACCEPTED = (
    ("default", {}, "modflow6"),
    ("a shipped name", {"backend": "modflow_nwt"}, "modflow_nwt"),
    ("spaces and capitals", {"backend": " Boussinesq "}, "boussinesq"),
)


REFUSED = (
    ("an absent backend", {"backend": "nope"}, ("backend",), "solver.backend names 'nope'", True),
    ("an absent table", {"nope": {}}, ("nope",), "solver.nope names 'nope'", True),
    (
        "an unknown key of a table",
        {"modflow6": {"no_such_key": 1}},
        ("modflow6", "no_such_key"),
        "Extra inputs are not permitted",
        False,
    ),
    (
        "a bad value of a table",
        {"modflow6": {"runtime": {"mf6_ims_complexity": "x"}}},
        ("modflow6", "runtime", "mf6_ims_complexity"),
        "Input should be",
        False,
    ),
)


TABLES = (
    ("modflow6", Modflow6Config, {"process_specific": {"vka": 2.0}}),
    ("modflow_nwt", ModflowConfig, {"runtime": {}}),
    ("boussinesq", BoussinesqOptions, {"backend": "local"}),
)


def test_a_solver_that_declares_no_options_refuses_its_table(isolated_solvers) -> None:
    isolated_solvers.solvers.register(fake_adapter("bare"))

    with pytest.raises(ValidationError, match=r"\[solver.bare\] holds settings"):
        SolverConfig.model_validate({"bare": {"x": 1}})
    with pytest.raises(ValueError, match="declares no settings"):
        SolverConfig().options_of("bare")


def test_options_of_refuses_a_name_nothing_serves() -> None:
    with pytest.raises(ValueError, match="solver.nope names 'nope'"):
        SolverConfig().options_of("nope")


DUMPS = (
    ("every held table", {}, {"modflow6", "modflow_nwt"}, set()),
    ("the written tables", {"exclude_unset": True}, {"modflow_nwt"}, {"modflow6"}),
)


def test_a_new_backend_by_assignment_holds_its_table() -> None:
    cfg = SolverConfig()

    cfg.backend = "boussinesq"

    assert list(cfg.held_tables()) == ["boussinesq"]
    with pytest.raises(ValidationError, match="solver.backend names 'nope'"):
        cfg.backend = "nope"
