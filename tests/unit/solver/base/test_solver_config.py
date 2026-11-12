"""``[solver]``: the flow solver named by a string, and the settings table of each solver.

``solver.backend`` is checked against the registry while the file is read, and
every other key of ``[solver]`` beyond its switches is the settings table of a
flow solver, checked by the ``options`` class that solver declares.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.solver.base.solver_config import SolverConfig
from tests._helpers.fake_solvers import fake_adapter

pytestmark = pytest.mark.fast


def test_solver_without_options_refuses_its_table(isolated_solvers) -> None:
    isolated_solvers.solvers.register(fake_adapter("bare"))

    with pytest.raises(ValidationError, match=r"\[solver.bare\] holds settings"):
        SolverConfig.model_validate({"bare": {"x": 1}})
    with pytest.raises(ValueError, match="declares no settings"):
        SolverConfig().options_of("bare")


def test_options_of_refuses_a_name_nothing_serves() -> None:
    with pytest.raises(ValueError, match="solver.nope names 'nope'"):
        SolverConfig().options_of("nope")


def test_new_backend_by_assignment_holds_its_table() -> None:
    cfg = SolverConfig()

    cfg.backend = "boussinesq"

    assert list(cfg.held_tables()) == ["boussinesq"]
    with pytest.raises(ValidationError, match="solver.backend names 'nope'"):
        cfg.backend = "nope"
