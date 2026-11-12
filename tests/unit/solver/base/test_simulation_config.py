"""``[simulation]``: the time window, the processes and what a run does with a taken name.

A time window has a start, an end and a step such as ``30 day``. A process names
a solver of its kind, or a backend for a mesh process. Dates are calendar dates,
steps and window lengths are calendar lengths.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.solver.base.planner import SimulationPlanner
from hydromodpy.solver.base.simulation_config import SimulationConfig

pytestmark = pytest.mark.fast

ONE_DAY = {"start_datetime": "2020-01-01 00:00:00", "end_datetime": "2020-01-02 00:00:00"}
ONE_YEAR = {"start_datetime": "2020-01-01", "end_datetime": "2020-12-31", "step_value": "1 month"}
BAD_WINDOW = "window is 'all' or a window number"


def config_of(time: dict[str, object]) -> SimulationConfig:
    return SimulationConfig.model_validate({"name": "w", "time": time, "process": []})


def test_step_is_read_from_value_and_unit() -> None:
    cfg = config_of(ONE_DAY | {"step_value": "30 day", "coverage_policy": "warn"})

    assert cfg.time is not None
    assert cfg.time.step_value == 30
    assert cfg.time.step_unit == "day"


STEPS = [
    pytest.param("3 mo", 3, "month", id="month alias"),
    pytest.param("1 hours", 1, "hour", id="plural hour"),
    pytest.param("2 years", 2, "year", id="plural year"),
]


@pytest.mark.parametrize(("step", "value", "unit"), STEPS)
def test_step_unit_spellings(step, value, unit) -> None:
    cfg = config_of(ONE_DAY | {"step_value": step})

    assert (cfg.time.step_value, cfg.time.step_unit) == (value, unit)


WINDOWS = [
    pytest.param({"window_length": "6 months"}, "6 months", "all", id="length"),
    pytest.param({"window_length": "1 year", "window": 2}, "1 year", 2, id="one window"),
    pytest.param({"window_length": "30 days", "window": "all"}, "30 days", "all", id="all"),
    pytest.param({"window": 1}, None, 1, id="one window of one"),
]


@pytest.mark.parametrize(("extra", "window_length", "window"), WINDOWS)
def test_windows_of_the_time_section(extra, window_length, window) -> None:
    cfg = config_of(ONE_YEAR | extra)

    assert (cfg.time.window_length, cfg.time.window) == (window_length, window)


def test_transient_helper_builds_flow_and_transport() -> None:
    cfg = SimulationConfig.transient(
        time=("2020-01-01", "2020-01-02", "1 day"),
        flow="modflow_nwt",
        transport="mt3dms",
    )

    assert [process.id for process in cfg.process] == ["flow_main", "transport_main"]
    assert [process.kind for process in cfg.process] == ["flow", "transport"]
    assert cfg.process[1].solvers == ["mt3dms"]


def test_steady_helper_builds_one_flow_run() -> None:
    cfg = SimulationConfig.steady(step="1 month")

    assert [process.kind for process in cfg.process] == ["flow"]
    assert cfg.process[0].solvers == ["modflow_nwt"]
    assert (cfg.time.step_value, cfg.time.step_unit) == (1, "month")


def test_mesh_process_uses_backend_not_solvers() -> None:
    cfg = SimulationConfig.model_validate(
        {
            "name": "mesh-only",
            "process": [{"id": "mesh_main", "kind": "mesh", "backend": "catchment"}],
        }
    )

    process = cfg.process[0]
    assert process.kind == "mesh"
    assert process.backend == "catchment"
    assert process.solvers == []

    plan = SimulationPlanner().build(cfg)
    assert len(plan.runs) == 1
    assert plan.runs[0].id == "mesh_main::catchment"
    assert plan.runs[0].process_type == "mesh"
    assert plan.runs[0].backend == "catchment"
    assert plan.runs[0].is_solver_backed is False


def test_if_exists_does_not_claim_a_name_is_taken_over() -> None:
    description = SimulationConfig.model_fields["if_exists"].description or ""

    assert "takes the name" not in description
    assert "``replace``" not in description
    assert "never reused" in description


def test_if_exists_names_the_next_free_version() -> None:
    description = SimulationConfig.model_fields["if_exists"].description or ""

    assert "next free" in description
    assert "stem.vN" in description


REFUSALS = [
    pytest.param(
        {
            "time": ONE_DAY
            | {"start_datetime": "2020-01-02 00:00:00", "end_datetime": "2020-01-01 00:00:00"}
        },
        "end_datetime must be greater than or equal",
        id="inverted bounds",
    ),
    pytest.param(
        {"time": ONE_DAY | {"step_value": "30 day", "step_unit": "hour"}},
        "unit conflicts with simulation.time.step_unit",
        id="two units",
    ),
    # A negative step with no unit gets the sign diagnosis, not "has no unit".
    pytest.param(
        {"time": ONE_DAY | {"step_value": -5}},
        "must be a positive integer",
        id="negative step",
    ),
    pytest.param(
        {"time": ONE_DAY | {"step_value": 1}},
        "simulation.time.step_value has no unit",
        id="bare step",
    ),
    pytest.param(
        {"time": ONE_DAY | {"step_value": "1 week"}},
        "step_unit must be one of: hour, day, month, year",
        id="week step",
    ),
    pytest.param(
        {"time": ONE_DAY | {"step_value": "1.5 day"}},
        "must be a positive integer",
        id="fractional step",
    ),
    pytest.param(
        {"time": ONE_DAY | {"step_value": "0 day"}},
        "must be a positive integer",
        id="zero step",
    ),
    pytest.param(
        {
            "process": [
                {"id": "a", "kind": "flow", "solvers": ["modflow6"]},
                {"id": "b", "kind": "flow", "solvers": ["modflow_nwt"]},
            ]
        },
        "At most one process of each kind is supported. Duplicate 'flow'",
        id="two flow processes",
    ),
    pytest.param(
        {"time": ONE_YEAR | {"window_length": "6"}},
        "window_length is a calendar length",
        id="bare window length",
    ),
    pytest.param(
        {"time": ONE_YEAR | {"window_length": "2 weeks"}},
        "positive whole number",
        id="weeks",
    ),
    pytest.param(
        {"time": ONE_YEAR | {"window_length": "6 months", "window": 0}},
        BAD_WINDOW,
        id="window zero",
    ),
    pytest.param(
        {"time": ONE_YEAR | {"window_length": "6 months", "window": True}},
        BAD_WINDOW,
        id="window boolean",
    ),
    pytest.param(
        {"time": ONE_YEAR | {"window_length": "6 months", "window": "last"}},
        BAD_WINDOW,
        id="window word",
    ),
    pytest.param(
        {"time": ONE_YEAR | {"window": 2}},
        "window_length, which is not set",
        id="window without length",
    ),
    pytest.param(
        {"process": [{"id": "flow_main", "kind": "flow", "solvers": [" "]}]},
        "require at least one solver",
        id="process without solver",
    ),
    pytest.param(
        {"process": {"id": "flow_main", "kind": "flow", "solvers": ["modflow6"]}},
        "Input should be a valid list",
        id="one process, not a list",
    ),
    pytest.param(
        {"if_exists": "replace"},
        "'replace' is gone.*'version'.*'fail'",
        id="replace",
    ),
]


@pytest.mark.parametrize(("raw", "match"), REFUSALS)
def test_refusals(raw: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        SimulationConfig.model_validate({"name": "w", "process": []} | raw)
