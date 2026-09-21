"""A run has one simulated discharge series, so one station is the target."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.calibration.metrics.observable_scoring import discharge_target


def _observed(*station_ids: str) -> list:
    return [SimpleNamespace(station_id=sid) for sid in station_ids]


def test_a_single_station_needs_no_declaration():
    assert discharge_target(_observed("NANCON"), None).station_id == "NANCON"


def test_the_declared_station_wins_over_the_others():
    target = discharge_target(_observed("NANCON", "UPSTREAM"), "UPSTREAM")

    assert target.station_id == "UPSTREAM"


def test_several_stations_without_a_declaration_refuse_to_average():
    """The upstream gauge drains a smaller area and cannot match the outlet series."""
    with pytest.raises(ValueError, match="one simulated discharge series"):
        discharge_target(_observed("NANCON", "UPSTREAM"), None)


def test_the_refusal_names_the_route_that_handles_several_gauges():
    """This route reads one series; the weighted-block route scores each gauge instead."""
    with pytest.raises(ValueError, match="per-cell discharge observable"):
        discharge_target(_observed("NANCON", "UPSTREAM"), None)


def test_the_refusal_names_the_candidates_and_the_way_out():
    with pytest.raises(ValueError) as excinfo:
        discharge_target(_observed("NANCON", "UPSTREAM"), None)

    message = str(excinfo.value)
    assert "NANCON" in message and "UPSTREAM" in message
    assert "observed_station_id" in message
    assert "station_ids" in message


def test_a_declared_station_that_was_not_loaded_says_so():
    with pytest.raises(ValueError, match="is not among the loaded discharge stations"):
        discharge_target(_observed("NANCON"), "J001401001")


def test_no_station_at_all_says_so():
    with pytest.raises(ValueError, match="No observed discharge station"):
        discharge_target([], None)


def test_the_declaration_is_read_as_a_string():
    """A numeric station id in TOML must still match its loaded string form."""
    numeric_id: str = 42  # type: ignore[assignment]  # what a bare TOML integer gives

    assert discharge_target(_observed("42"), numeric_id).station_id == "42"
