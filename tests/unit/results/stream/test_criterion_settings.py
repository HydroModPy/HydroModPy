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
from hydromodpy.results.derive.stream_network.criterion_settings import network_criterion_settings
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
