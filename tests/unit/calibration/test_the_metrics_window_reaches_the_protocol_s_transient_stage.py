"""Under a protocol, ``[metrics] window`` is the window of the transient stage.

The run is scored on ``[metrics] window`` and a calibration takes it by default
on every phase that writes no window (H45). The protocol used to write its own
default, one year past the start with no end, before the project defaults ran,
so the stage already carried a window and kept it: the end of ``[metrics]
window`` was lost and the session scored past it. The spin-up default now
applies only without ``[metrics] window``.
"""

from __future__ import annotations

import copy

from hydromodpy.calibration.config import apply_project_defaults
from hydromodpy.calibration.protocols import expand_calibration_protocol

NAME = "matching_hydrographic_network"
WINDOW = {"start": "2001-01-01", "end": "2003-12-31"}


def _doc(**calibration: object) -> dict:
    return {
        "simulation": {
            "time": {
                "start_datetime": "2000-01-01",
                "end_datetime": "2005-12-31",
                "step_value": 1,
                "step_unit": "month",
            }
        },
        "metrics": {"window": dict(WINDOW)},
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
        "calibration": {
            "protocol": NAME,
            "parameters": {
                "K": {"bounds": [1e-8, 1e-2], "search_space": "log"},
                "Sy": {"bounds": [1e-4, 0.5], "search_space": "log"},
            },
            "outputs": {
                "seepage_network": {"support": "network", "stream_geometry_path": "n.gpkg"}
            },
            **calibration,
        },
    }


def _loaded_stages(doc: dict) -> list[dict]:
    """Return the stages as the load writes them: expansion, then project defaults."""
    raw = expand_calibration_protocol(copy.deepcopy(doc))
    calibration = apply_project_defaults(
        raw["calibration"], site_gauge=None, metrics_window=raw["metrics"]["window"]
    )
    return calibration["phases"]


def test_the_transient_stage_scores_the_metrics_window_with_both_bounds() -> None:
    steady, transient = _loaded_stages(_doc())

    assert transient["scoring_window"] == WINDOW
    assert "scoring_window" not in steady


def test_the_expansion_itself_writes_the_window() -> None:
    _, transient = expand_calibration_protocol(_doc())["calibration"]["phases"]

    assert transient["scoring_window"] == WINDOW
    assert "spin-up" not in transient["description"]
    assert "2003-12-31" in transient["description"]


def test_without_a_metrics_window_the_spin_up_default_stays() -> None:
    doc = _doc()
    del doc["metrics"]

    _, transient = expand_calibration_protocol(doc)["calibration"]["phases"]

    assert transient["scoring_window"] == {"start": "2001-01-01"}


def test_a_window_on_the_protocol_still_wins() -> None:
    doc = _doc(protocol={"name": NAME, "scoring_window": {"start": "2002-01-01"}})

    _, transient = _loaded_stages(doc)

    assert transient["scoring_window"] == {"start": "2002-01-01"}


def test_a_stage_sealed_with_the_spin_up_window_replays_it() -> None:
    """A run sealed before this fix carries the spin-up window and reads back with it."""
    doc = _doc()
    del doc["metrics"]
    sealed = {**expand_calibration_protocol(doc), "metrics": {"window": dict(WINDOW)}}

    _, transient = expand_calibration_protocol(sealed)["calibration"]["phases"]

    assert transient["scoring_window"] == {"start": "2001-01-01"}


def test_a_stage_sealed_with_the_metrics_window_reads_back() -> None:
    sealed = expand_calibration_protocol(_doc())

    again = expand_calibration_protocol(sealed)["calibration"]["phases"]

    assert again == sealed["calibration"]["phases"]
