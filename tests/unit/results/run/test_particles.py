"""The time of a particle track is stored in the unit of the solver and read in days.

``particle_time_to_days`` reads the ``time_units`` attribute of the ``particles`` group and
turns one stored unit into days. A run that wrote no unit holds days, and a unit nothing
knows is refused, never read as one day.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.results.run.particles import (
    moving_tracks,
    particle_time_to_days,
    particle_travel_years,
    read_particle_tracks,
    travel_time,
    travel_time_to_exit,
    water_ages,
)


class _Group:
    def __init__(self, attrs: dict, **arrays: np.ndarray) -> None:
        self.attrs = attrs
        self._arrays = arrays

    def get(self, name: str):
        return self if name == "particles" else None

    def __contains__(self, name: str) -> bool:
        return name in self._arrays

    def __getitem__(self, name: str) -> np.ndarray:
        return self._arrays[name]


class _Store:
    def __init__(self, group: _Group) -> None:
        self.root = group

    def close(self) -> None:
        pass


def _run(attrs: dict, **arrays: np.ndarray) -> SimpleNamespace:
    group = _Group(attrs, **arrays)
    return SimpleNamespace(
        sim_id="sim", _catalog=SimpleNamespace(open_zarr=lambda _id: _Store(group))
    )


# One row per stored unit: the factor to days. A second is 1/86 400 day, a year 365.25 days.
_UNITS = [
    pytest.param("seconds", 1.0 / 86400.0, id="seconds"),
    pytest.param("s", 1.0 / 86400.0, id="second_symbol"),
    pytest.param("minutes", 1.0 / 1440.0, id="minutes"),
    pytest.param("hours", 1.0 / 24.0, id="hours"),
    pytest.param("days", 1.0, id="days"),
    pytest.param("DAY", 1.0, id="day_in_capitals"),
    pytest.param("years", 365.25, id="years"),
]


@pytest.mark.parametrize(("unit", "factor"), _UNITS)
def test_unit_to_days(unit, factor) -> None:
    assert particle_time_to_days(_run({"time_units": unit})) == pytest.approx(factor, rel=1e-12)


def test_no_unit_is_days() -> None:
    assert particle_time_to_days(_run({})) == 1.0


def test_unknown_unit_refused() -> None:
    with pytest.raises(ValueError, match="Unsupported time unit 'fortnights'"):
        particle_time_to_days(_run({"time_units": "fortnights"}))


# One row per stored unit: the travel years of one track that ran for the stored time 730.5.
@pytest.mark.parametrize(
    ("unit", "years"),
    [
        pytest.param("days", 2.0, id="days"),
        pytest.param("years", 730.5, id="years"),
        pytest.param("hours", 730.5 / 24.0 / 365.25, id="hours"),
    ],
)
def test_travel_years(unit, years) -> None:
    run = _run(
        {"time_units": unit},
        x=np.array([[0.0, 1.0, 2.0]]),
        y=np.array([[0.0, 0.0, 0.0]]),
        time=np.array([[0.0, 100.0, 730.5]]),
    )

    assert particle_travel_years(run) == pytest.approx([years], rel=1e-12)


def test_padding_stripped() -> None:
    run = _run(
        {},
        x=np.array([[0.0, 1.0, np.nan], [5.0, np.nan, np.nan]]),
        y=np.array([[0.0, 0.0, np.nan], [5.0, np.nan, np.nan]]),
        time=np.array([[0.0, 3.0, np.nan], [0.0, np.nan, np.nan]]),
    )

    tracks = read_particle_tracks(run)

    assert len(tracks) == 1
    assert tracks[0].shape == (2, 4)
    assert travel_time(tracks[0]) == 3.0


GRID = np.array([[x, y] for y in range(3) for x in range(3)], dtype=float)
"""Centres of a 3 x 3 grid, row by row from y = 0."""


def _two_rows() -> SimpleNamespace:
    """Two particles along x: on y = 0 in two years, on y = 2 in four years."""
    return _run(
        {"time_units": "days"},
        x=np.array([[0.0, 1.0, 2.0], [0.0, 1.0, 2.0]]),
        y=np.array([[0.0, 0.0, 0.0], [2.0, 2.0, 2.0]]),
        time=np.array([[0.0, 365.25, 730.5], [0.0, 730.5, 1461.0]]),
    )


def test_the_age_of_the_water_runs_from_zero_to_the_travel_time() -> None:
    tracks, years = moving_tracks(_two_rows())
    young, old = water_ages(tracks, years)
    assert young == pytest.approx([0.0, 1.0, 2.0]) and old == pytest.approx([0.0, 2.0, 4.0])


def test_the_travel_time_to_exit_is_what_is_left_and_is_interpolated_between_pathlines() -> None:
    field = travel_time_to_exit(_two_rows(), GRID).reshape(3, 3)
    assert field[0] == pytest.approx([2.0, 1.0, 0.0])  # what is left of two years
    assert field[2] == pytest.approx([4.0, 2.0, 0.0])
    assert field[1] == pytest.approx([3.0, 1.5, 0.0])  # no pathline: between its neighbours
    line = np.array([[x, 0.0] for x in range(5)])
    alone = travel_time_to_exit(_two_rows(), line)
    assert np.isnan(alone[3:]).all() and np.isfinite(alone[:3]).all()  # one line, no triangle
