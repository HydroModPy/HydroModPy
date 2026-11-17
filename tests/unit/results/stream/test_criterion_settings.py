"""Settings of the stream criterion that a figure reads back from a sealed run.

A figure redraws what a trial scored, so it reads the network output the run
sealed under ``[calibration.outputs]`` (lengths in m, flows in m3/s, dates as
timestamps), and the defaults when the run sealed none.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    STEADY_STAGE,
    TRANSIENT_STAGE,
)
from hydromodpy.calibration.protocols.registry import expand_calibration_protocol
from hydromodpy.results.derive.stream_network.criterion_settings import (
    DEFAULT_EXTENT_RULES,
    network_criterion_settings,
)
from tests._helpers.sealed_runs import sealed_search

# 36 monthly periods, 2000-01 to 2002-12. October 2002 is period 33.
MONTHS = pd.date_range("2000-01-01", "2003-01-01", freq="MS")
OCTOBER_2002 = 33

NETWORK = {"support": "network", "observed_network": "data.hydrography"}


def run_with_time(time, *, edges=MONTHS, n_timesteps=None) -> SimpleNamespace:
    """A run with one network output sealed at ``time``, a date or a word."""
    search = {
        "outputs": {
            "seepage_network": {
                "support": "network",
                "observed_network": "data.hydrography",
                "time": time,
            }
        }
    }
    run = SimpleNamespace(sim_id="sim-x", dir=sealed_search(search))
    if edges is not None:
        run.periods = SimpleNamespace(edges=pd.DatetimeIndex(edges))
    if n_timesteps is not None:
        run.n_timesteps = n_timesteps
    return run


def network_output(**fields) -> dict:
    """The seal of a network output, at the names of today."""
    return {"support": "network", "map": {"complete": "data.hydrography"}, **fields}


def run_with_outputs(outputs: dict | None = None, *, window: dict | None = None, **sections):
    run = SimpleNamespace(sim_id="sim-x", config_snapshot=dict(sections))
    if outputs is not None:
        window = {} if window is None else {"window": window}
        run.dir = sealed_search({"outputs": outputs, **window})
    return run


def run_of_phase(calibration: dict, *, phase: str | None) -> SimpleNamespace:
    """A run whose trial belongs to one session of the named phase."""
    session = uuid.uuid4()
    sessions = [
        {"session_id": session, "phase_name": phase},
        {"session_id": uuid.uuid4(), "phase_name": "other"},
    ]
    return SimpleNamespace(
        sim_id="sim-x",
        dir=sealed_search(calibration),
        calibration_iterations=[{"session_id": session.hex, "iteration": 0}],
        calibration_sessions=pd.DataFrame(sessions),
    )


def phases(window: dict | None) -> list[dict]:
    transient = {"name": "transient", "parameters": ["Sy"]}
    if window is not None:
        transient["window"] = window
    return [{"name": "steady", "parameters": ["K"]}, transient]


# A date is read as the period [s, e) that holds it, by the rule of
# core.time.selection.resolve_state. The stamp of a period names the state it closes.
def test_stamp_reads_closed_state() -> None:
    assert network_criterion_settings(run_with_time("2002-10-01")).timestep == OCTOBER_2002 - 1


def test_one_state_without_dates() -> None:
    run = run_with_time("2002-10-15", edges=None, n_timesteps=1)

    assert network_criterion_settings(run).timestep == 0


def test_positional_accuracy_is_read_in_metres() -> None:
    run = run_with_outputs({"streams": network_output(map={"position_accuracy": "0.05 km"})})

    assert network_criterion_settings(run).observed_position_accuracy_m == pytest.approx(50.0)


def test_several_outputs_read_first() -> None:
    run = run_with_outputs(
        {
            "first": network_output(model={"seepage_threshold": 0.0}),
            "head": {"support": "point", "variable": "head"},
            "second": network_output(model={"seepage_threshold": 1.0e-2}),
        }
    )

    settings = network_criterion_settings(run)

    assert settings.output == "first"
    assert settings.n_network_outputs == 2
    assert "one of 2 network outputs" in settings.note()
    assert network_criterion_settings(run, output="second").tau_specific_ratio == 1.0e-2


PERMANENT = {"complete": "data.hydrography", "permanent": "data.hydrography"}


@pytest.mark.parametrize(
    ("drawn", "expected"),
    [
        ({"complete": "data.hydrography"}, False),
        ({**PERMANENT, "calibrate_on": "complete"}, False),
        ({**PERMANENT, "calibrate_on": "permanent"}, True),
    ],
)
def test_the_map_in_the_cost_is_read(drawn: dict, expected: bool) -> None:
    run = run_with_outputs({"streams": network_output(map=drawn)})

    settings = network_criterion_settings(run)

    assert settings.scores_permanent_map is expected
    assert ("scored on the permanent map" in settings.note()) is expected


# A staged search keeps one session row, so only the seal of a promoted run says
# which phase scored it. The output and the window are those of that phase.
def test_a_promoted_run_reads_the_output_and_the_window_of_its_phase() -> None:
    calibration = {
        "outputs": {
            "permanent": network_output(map={**PERMANENT, "calibrate_on": "permanent"}),
            "full": network_output(),
        },
        "objective_blocks": [
            {"name": "steady_net", "uses_outputs": ["permanent"]},
            {"name": "transient_net", "uses_outputs": ["full"]},
        ],
        "phases": [
            {"name": "steady", "objective_blocks": ["steady_net"]},
            {
                "name": "transient",
                "objective_blocks": ["transient_net"],
                "window": {"start": "2003-01-01"},
            },
        ],
    }
    trial = run_of_phase(calibration, phase="steady")
    promoted = run_of_phase(calibration, phase="steady")
    promoted.checks = SimpleNamespace(calibrated_by=SimpleNamespace(phase="transient"))

    read = [network_criterion_settings(run) for run in (trial, promoted)]

    assert [settings.output for settings in read] == ["permanent", "full"]
    assert [settings.scores_permanent_map for settings in read] == [True, False]
    assert [settings.window_phase for settings in read] == [None, "transient"]


def test_sealed_scoring_window() -> None:
    run = run_with_outputs(
        {"streams": network_output()}, window={"start": "2002-01-01T00:00:00+01:00"}
    )

    settings = network_criterion_settings(run)

    assert settings.window == (pd.Timestamp("2002-01-01"), None)
    assert settings.note().endswith("window 2002-01-01 to open")


def test_open_window_is_none() -> None:
    sealed_open = run_with_outputs({"streams": network_output()}, window={})
    sealed_none = run_with_outputs({"streams": network_output()})

    assert network_criterion_settings(sealed_open).window is None
    assert network_criterion_settings(sealed_none).window is None


# A phase window replaces the calibration window, and the protocol writes its
# default spin-up window on its transient stage. The phase of a run is the one
# of the session its trial belongs to.
def test_phase_window_wins() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "window": {"start": "2001-01-01"},
        "phases": phases({"start": "2003-01-01", "end": "2005-12-31"}),
    }

    settings = network_criterion_settings(run_of_phase(calibration, phase="transient"))

    assert settings.window == (pd.Timestamp("2003-01-01"), pd.Timestamp("2005-12-31"))
    assert settings.window_phase == "transient"
    assert settings.note().endswith("window 2003-01-01 to 2005-12-31 of phase 'transient'")


def test_open_phase_window_is_none() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "window": {"start": "2001-01-01"},
        "phases": phases({}),
    }

    settings = network_criterion_settings(run_of_phase(calibration, phase="transient"))

    assert settings.window is None
    assert "window" not in settings.note()


def test_protocol_spin_up_window() -> None:
    document = {
        "simulation": {"time": {"start_datetime": "2020-01-01", "end_datetime": "2023-12-31"}},
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
        "calibration": {
            "protocol": {"name": "matching_hydrographic_network"},
            "parameters": {"K": {"bounds": [1e-8, 1e-2]}, "Sy": {"bounds": [1e-4, 0.5]}},
            "outputs": {"net": {"support": "network", "stream_geometry_path": "map.gpkg"}},
        },
    }
    calibration = expand_calibration_protocol(document)["calibration"]

    transient = network_criterion_settings(run_of_phase(calibration, phase=TRANSIENT_STAGE))
    steady = network_criterion_settings(run_of_phase(calibration, phase=STEADY_STAGE))

    assert transient.window == (pd.Timestamp("2021-01-01"), None)
    assert transient.window_phase == TRANSIENT_STAGE
    assert steady.window is None


TIME_REFUSALS = [
    pytest.param("2004-01-15", "names no state of this run", id="date outside the run"),
    pytest.param("all", "seepage_network", id="all states"),
    pytest.param(["2001-10-15", "2002-10-15"], "seepage_network", id="a list of dates"),
    pytest.param(3, "seepage_network", id="an integer"),
]


@pytest.mark.parametrize(("time", "match"), TIME_REFUSALS)
def test_refused_times(time, match) -> None:
    with pytest.raises(ValueError, match=match):
        network_criterion_settings(run_with_time(time))


SEAL_REFUSALS = [
    pytest.param(
        {"streams": network_output()},
        None,
        {"output": "other"},
        "sealed no network output 'other'",
        id="output not sealed",
    ),
    pytest.param(
        {"streams": network_output(map={"drawn_by": "all"})},
        None,
        {},
        "unknown map.drawn_by",
        id="unknown rule",
    ),
    pytest.param(
        {"streams": network_output(model={"extent": {"visible_flow": "1"}})},
        None,
        {},
        "carries no unit",
        id="flow without unit",
    ),
    pytest.param(
        {"streams": network_output()},
        {"start": "spring"},
        {},
        "window.start 'spring' is not a date",
        id="window bound not a date",
    ),
]


@pytest.mark.parametrize(("outputs", "window", "kwargs", "match"), SEAL_REFUSALS)
def test_refused_seals(outputs, window, kwargs, match) -> None:
    run = run_with_outputs(outputs, window=window)

    with pytest.raises(ValueError, match=match):
        network_criterion_settings(run, **kwargs)


def test_a_run_without_a_seal_reads_the_defaults() -> None:
    settings = network_criterion_settings(SimpleNamespace(sim_id="sim-x"))

    assert settings.output is None
    assert settings.note() == "criterion settings: the defaults, this run sealed no network output"
    assert settings.extent_rules is DEFAULT_EXTENT_RULES


VALUE_REFUSALS = [
    pytest.param(
        {"model": {"seepage_threshold": -1.0}}, "seepage_threshold must be positive", id="tau"
    ),
    pytest.param(
        {"map": {"heads": {"radius": "0 m"}}}, "heads.radius must be positive", id="radius"
    ),
    pytest.param(
        {"map": {"heads": {"min_drained_area": -2.0}}},
        "min_drained_area must not be negative",
        id="area",
    ),
    pytest.param({"model": {"extent": "yearly"}}, "model.extent is not a mapping", id="extent"),
]


@pytest.mark.parametrize(("fields", "match"), VALUE_REFUSALS)
def test_a_sealed_value_no_trial_could_read_is_refused(fields, match) -> None:
    run = run_with_outputs({"streams": network_output(**fields)})

    with pytest.raises(ValueError, match=match):
        network_criterion_settings(run)


def test_a_window_that_is_not_a_mapping_is_refused() -> None:
    run = run_with_outputs({"streams": network_output()}, window="2002")

    with pytest.raises(ValueError, match="calibration.window is not a mapping"):
        network_criterion_settings(run)


def test_a_sealed_extent_keeps_its_rules_and_fills_the_rest_with_defaults() -> None:
    extent = {"flowing_at_least": "3 months", "dry_at_most": "1 month"}
    run = run_with_outputs({"streams": network_output(model={"extent": extent})})

    rules = network_criterion_settings(run).extent_rules

    assert (rules.maximal_flowing_duration, rules.minimal_dry_duration) == ("3 months", "1 month")
    assert rules.year_quorum == DEFAULT_EXTENT_RULES.year_quorum
    assert rules.visible_flow == DEFAULT_EXTENT_RULES.visible_flow


def test_four_neighbours_turn_the_diagonals_off() -> None:
    run = run_with_outputs({"streams": network_output(model={"neighbours": "D4"})})

    assert network_criterion_settings(run).diagonal_neighbors is False


def test_a_run_without_dates_or_a_count_reads_one_state() -> None:
    run = run_with_time("2002-10-15", edges=None)

    assert network_criterion_settings(run).timestep == 0


def test_the_phase_of_a_run_is_unknown_without_a_session_column() -> None:
    run = run_of_phase({"outputs": {"streams": NETWORK}, "phases": phases(None)}, phase="transient")
    run.calibration_iterations = [{"iteration": 0}]

    settings = network_criterion_settings(run)

    assert settings.window_phase is None


def test_the_phase_of_a_run_is_unknown_when_its_trials_name_two_sessions() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "phases": phases({"start": "2003-01-01"}),
    }
    run = run_of_phase(calibration, phase="transient")
    run.calibration_iterations = [
        {"session_id": uuid.uuid4().hex, "iteration": 0},
        {"session_id": uuid.uuid4().hex, "iteration": 1},
    ]

    assert network_criterion_settings(run).window_phase is None


@pytest.mark.parametrize(
    "sessions",
    [
        pd.DataFrame({"session_id": []}),
        pd.DataFrame({"name": ["x"]}),
        pd.DataFrame({"session_id": [uuid.uuid4()], "phase_name": ["transient"]}),
    ],
    ids=["empty", "no id column", "other session"],
)
def test_the_phase_of_a_run_is_unknown_when_no_session_row_names_it(sessions) -> None:
    calibration = {"outputs": {"streams": NETWORK}, "phases": phases({"start": "2003-01-01"})}
    run = run_of_phase(calibration, phase="transient")
    run.calibration_sessions = sessions

    assert network_criterion_settings(run).window_phase is None


@pytest.mark.parametrize("phase_name", [None, float("nan")])
def test_a_session_without_a_phase_name_gives_no_phase(phase_name) -> None:
    calibration = {"outputs": {"streams": NETWORK}, "phases": phases({"start": "2003-01-01"})}
    run = run_of_phase(calibration, phase=phase_name)

    assert network_criterion_settings(run).window_phase is None


def test_the_blocks_of_a_phase_that_use_no_sealed_output_fall_back_to_the_first_output() -> None:
    calibration = {
        "outputs": {"a": NETWORK, "b": NETWORK},
        "objective_blocks": ["junk", {"name": "blk", "uses_outputs": ["ghost"]}],
        "phases": ["junk", {"name": "transient", "objective_blocks": ["blk"]}],
    }
    run = run_of_phase(calibration, phase="transient")

    assert network_criterion_settings(run).output == "a"


def test_a_run_whose_seal_cannot_be_read_gets_the_defaults(tmp_path) -> None:
    run = SimpleNamespace(sim_id="sim-x", dir=tmp_path / "missing")

    assert network_criterion_settings(run).output is None


def test_a_phase_the_calibration_never_declared_reads_the_calibration_window() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "window": {"start": "2001-01-01"},
        "phases": [{"name": "other", "window": {"start": "2005-01-01"}}],
    }

    settings = network_criterion_settings(run_of_phase(calibration, phase="transient"))

    assert settings.window == (pd.Timestamp("2001-01-01"), None)
    assert settings.window_phase is None


def test_a_run_whose_step_count_cannot_be_read_holds_one_state() -> None:
    class Counting(SimpleNamespace):
        @property
        def n_timesteps(self):
            raise RuntimeError("no count")

    run = Counting(**vars(run_with_time("2002-10-15", edges=None)))

    assert network_criterion_settings(run).timestep == 0
