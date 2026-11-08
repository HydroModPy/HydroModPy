"""``[solver]``: the flow solver named by a string, and the settings table of each solver.

``solver.backend`` is checked against the registry while the file is read, and
every other key of ``[solver]`` beyond its switches is the settings table of a
flow solver, checked by the ``options`` class that solver declares.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from hydromodpy.core.config_kit.base import frozen_copy
from hydromodpy.core.exceptions import FrozenConfigError
from hydromodpy.solver.base.solver_config import SolverConfig, backend_following_the_process
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowConfig
from tests._helpers.fake_solvers import fake_adapter

pytestmark = pytest.mark.fast

SERVED = "this installation serves boussinesq, modflow6, modflow_nwt"


class _PluginOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relaxation: float = 1.0


ACCEPTED = (
    ("default", {}, "modflow6"),
    ("a shipped name", {"backend": "modflow_nwt"}, "modflow_nwt"),
    ("spaces and capitals", {"backend": " Boussinesq "}, "boussinesq"),
)


@pytest.mark.parametrize(
    ("case", "payload", "expected"), ACCEPTED, ids=[case for case, _, _ in ACCEPTED]
)
def test_a_registered_name_is_read_as_the_solver(case: str, payload: dict, expected: str) -> None:
    del case
    cfg = SolverConfig.model_validate(payload)

    assert cfg.backend == expected
    assert cfg.backend_name == expected


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


@pytest.mark.parametrize(
    ("case", "payload", "loc", "refusal", "names_served"),
    REFUSED,
    ids=[case for case, *_ in REFUSED],
)
def test_a_name_or_a_table_nothing_serves_is_refused_at_its_key(
    case: str, payload: dict, loc: tuple[str, ...], refusal: str, names_served: bool
) -> None:
    del case
    with pytest.raises(ValidationError) as caught:
        SolverConfig.model_validate(payload)

    assert [error["loc"] for error in caught.value.errors()] == [loc]
    assert refusal in str(caught.value)
    assert (SERVED in str(caught.value)) is names_served


TABLES = (
    ("modflow6", Modflow6Config, {"process_specific": {"vka": 2.0}}),
    ("modflow_nwt", ModflowConfig, {"runtime": {}}),
    ("boussinesq", BoussinesqOptions, {"backend": "local"}),
)


@pytest.mark.parametrize(("name", "options", "table"), TABLES, ids=[row[0] for row in TABLES])
def test_a_table_is_read_by_the_options_class_of_its_solver(
    name: str, options: type[BaseModel], table: dict[str, Any]
) -> None:
    cfg = SolverConfig.model_validate({name: table})

    held = cfg.options_of(name)
    assert type(held) is options
    assert held == options.model_validate(table)


def test_the_table_of_a_solver_that_does_not_run_is_accepted_and_kept() -> None:
    cfg = SolverConfig.model_validate(
        {"backend": "boussinesq", "modflow6": {"process_specific": {"vka": 2.0}}}
    )

    assert cfg.options_of("modflow6").process_specific.vka == 2.0
    assert list(cfg.written_tables()) == ["modflow6"]


def test_a_table_left_out_reads_as_its_defaults_and_the_running_one_is_held() -> None:
    cfg = SolverConfig.model_validate({"backend": "modflow_nwt"})

    assert cfg.options_of("modflow6") == Modflow6Config()
    assert list(cfg.held_tables()) == ["modflow_nwt"]
    assert cfg.written_tables() == {}


def test_an_empty_table_of_another_solver_is_not_held() -> None:
    cfg = SolverConfig.model_validate({"backend": "modflow6", "modflow_nwt": {}})

    assert list(cfg.held_tables()) == ["modflow6"]


def test_a_solver_that_declares_no_options_refuses_its_table(isolated_solvers) -> None:
    isolated_solvers.solvers.register(fake_adapter("bare"))

    with pytest.raises(ValidationError, match=r"\[solver.bare\] holds settings"):
        SolverConfig.model_validate({"bare": {"x": 1}})
    with pytest.raises(ValueError, match="declares no settings"):
        SolverConfig().options_of("bare")


def test_a_plugin_table_is_checked_by_its_own_class(isolated_solvers) -> None:
    isolated_solvers.solvers.register(fake_adapter("plugged", options=_PluginOptions))

    cfg = SolverConfig.model_validate({"backend": "plugged", "plugged": {"relaxation": 0.5}})

    assert cfg.options_of("plugged") == _PluginOptions(relaxation=0.5)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SolverConfig.model_validate({"plugged": {"other": 1}})


def test_options_of_refuses_a_name_nothing_serves() -> None:
    with pytest.raises(ValueError, match="solver.nope names 'nope'"):
        SolverConfig().options_of("nope")


DUMPS = (
    ("every held table", {}, {"modflow6", "modflow_nwt"}, set()),
    ("the written tables", {"exclude_unset": True}, {"modflow_nwt"}, {"modflow6"}),
)


@pytest.mark.parametrize(
    ("case", "options", "present", "absent"), DUMPS, ids=[row[0] for row in DUMPS]
)
def test_a_table_is_written_flat_under_its_name(
    case: str, options: dict, present: set, absent: set
) -> None:
    del case
    cfg = SolverConfig.model_validate({"modflow_nwt": {"runtime": {"upw": {"hdry": -999.0}}}})

    dumped = cfg.model_dump(mode="json", **options)

    assert present <= set(dumped)
    assert not absent & set(dumped)
    assert dumped["modflow_nwt"]["runtime"]["upw"]["hdry"] == -999.0
    assert SolverConfig.model_validate(cfg.model_dump()) == cfg


def test_a_backend_taken_from_the_flow_process_is_not_a_written_field() -> None:
    cfg = SolverConfig.model_validate({"backend": backend_following_the_process("modflow_nwt")})

    assert cfg.backend == "modflow_nwt"
    assert type(cfg.backend) is str
    assert "backend" not in cfg.model_fields_set
    assert list(cfg.held_tables()) == ["modflow_nwt"]


def test_a_backend_written_by_the_file_is_a_written_field() -> None:
    cfg = SolverConfig.model_validate({"backend": "modflow_nwt"})

    assert "backend" in cfg.model_fields_set


def test_a_new_backend_by_assignment_holds_its_table() -> None:
    cfg = SolverConfig()

    cfg.backend = "boussinesq"

    assert list(cfg.held_tables()) == ["boussinesq"]
    with pytest.raises(ValidationError, match="solver.backend names 'nope'"):
        cfg.backend = "nope"


def test_named_tables_lists_the_shipped_solvers_that_declare_settings() -> None:
    assert SolverConfig.named_tables(shipped_only=True) == {
        "boussinesq": BoussinesqOptions,
        "modflow6": Modflow6Config,
        "modflow_nwt": ModflowConfig,
    }


def test_a_frozen_copy_freezes_its_tables() -> None:
    frozen = frozen_copy(SolverConfig())

    with pytest.raises(FrozenConfigError):
        frozen.options_of("modflow6").runtime.mf6_ims_complexity = "SIMPLE"
