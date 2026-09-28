"""A redrawn network figure reads the scoring window of the phase the run was scored in.

A phase's ``scoring_window`` replaces the calibration's for every block it
scores, and the protocol writes its default spin-up window on its transient
stage. The run's phase is the one of the session its trial belongs to.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pandas as pd

from hydromodpy.calibration.protocols import expand_calibration_protocol
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    STEADY_STAGE,
    TRANSIENT_STAGE,
)
from hydromodpy.results.derive.network_criterion_settings import network_criterion_settings

NETWORK = {"support": "network", "observed_network": "data.hydrography"}


def _run(calibration: dict, *, phase: str | None, dashed: bool = False) -> SimpleNamespace:
    """A run whose trial belongs to one session of the named phase."""
    session = uuid.uuid4()
    trial_id = str(session) if dashed else session.hex
    sessions = [
        {"session_id": session, "phase_name": phase},
        {"session_id": uuid.uuid4(), "phase_name": "other"},
    ]
    return SimpleNamespace(
        sim_id="sim-x",
        config_snapshot={"calibration": calibration},
        calibration_iterations=[{"session_id": trial_id, "iteration": 0}],
        calibration_sessions=pd.DataFrame(sessions),
    )


def _phases(window: dict | None) -> list[dict]:
    transient = {"name": "transient", "parameters": ["Sy"]}
    if window is not None:
        transient["scoring_window"] = window
    return [{"name": "steady", "parameters": ["K"]}, transient]


def test_the_window_of_the_run_s_phase_wins_over_the_calibration_s() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "scoring_window": {"start": "2001-01-01", "end": None},
        "phases": _phases({"start": "2003-01-01", "end": "2005-12-31"}),
    }

    settings = network_criterion_settings(_run(calibration, phase="transient"))

    assert settings.scoring_window == (pd.Timestamp("2003-01-01"), pd.Timestamp("2005-12-31"))
    assert settings.scoring_window_phase == "transient"
    assert settings.note().endswith("scoring_window 2003-01-01 to 2005-12-31 of phase 'transient'")


def test_a_session_id_spelled_with_dashes_finds_its_phase() -> None:
    calibration = {"outputs": {"streams": NETWORK}, "phases": _phases({"start": "2003-01-01"})}

    settings = network_criterion_settings(_run(calibration, phase="transient", dashed=True))

    assert settings.scoring_window == (pd.Timestamp("2003-01-01"), None)


def test_a_phase_without_a_window_reads_the_calibration_s() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "scoring_window": {"start": "2001-01-01", "end": None},
        "phases": _phases({"start": "2003-01-01"}),
    }

    settings = network_criterion_settings(_run(calibration, phase="steady"))

    assert settings.scoring_window == (pd.Timestamp("2001-01-01"), None)
    assert settings.scoring_window_phase is None
    assert settings.note().endswith("scoring_window 2001-01-01 to open")


def test_a_run_tied_to_no_phase_reads_the_calibration_s() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "scoring_window": {"start": "2001-01-01", "end": None},
        "phases": _phases({"start": "2003-01-01"}),
    }
    run = SimpleNamespace(sim_id="sim-x", config_snapshot={"calibration": calibration})

    assert network_criterion_settings(run).scoring_window == (pd.Timestamp("2001-01-01"), None)
    assert network_criterion_settings(_run(calibration, phase=None)).scoring_window_phase is None


def test_a_phase_window_open_on_both_ends_is_no_window() -> None:
    calibration = {
        "outputs": {"streams": NETWORK},
        "scoring_window": {"start": "2001-01-01", "end": None},
        "phases": _phases({"start": None, "end": None}),
    }

    settings = network_criterion_settings(_run(calibration, phase="transient"))

    assert settings.scoring_window is None
    assert "scoring_window" not in settings.note()


def test_the_protocol_s_spin_up_window_reaches_a_run_of_its_transient_stage() -> None:
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

    transient = network_criterion_settings(_run(calibration, phase=TRANSIENT_STAGE))
    steady = network_criterion_settings(_run(calibration, phase=STEADY_STAGE))

    assert transient.scoring_window == (pd.Timestamp("2021-01-01"), None)
    assert transient.scoring_window_phase == TRANSIENT_STAGE
    assert steady.scoring_window is None
