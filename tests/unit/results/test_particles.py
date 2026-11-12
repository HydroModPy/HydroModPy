"""Particle paths of a run, read from the ``particles`` group of its Zarr store.

Positions are in meters, times in the unit the extractor wrote (``time_units``)
and ``time_days`` in days. NaN padding and particles that never moved are dropped.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import zarr

import hydromodpy.results.run.particles as particles
from hydromodpy.results.run.particles import (
    PARTICLE_COLUMNS,
    has_particle_tracks,
    particle_frame,
    particle_time_to_days,
    read_particle_tracks,
    travel_time,
)
from hydromodpy.results.run.view import Run


class _Group(dict):
    """A Zarr group reduced to ``name in group``, ``group[name]`` and ``attrs``."""

    def __init__(self, arrays: dict[str, np.ndarray], attrs: dict[str, str] | None = None):
        super().__init__(arrays)
        self.attrs = dict(attrs or {})


class _Store:
    def __init__(self, root: dict) -> None:
        self.root = root
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _run_over(root: dict, **catalog_members) -> SimpleNamespace:
    """Return a run whose store holds ``root``, recording every opening."""
    opened: list[_Store] = []

    def open_zarr(_sim_id):
        opened.append(_Store(root))
        return opened[-1]

    return SimpleNamespace(
        sim_id="sim-readers",
        opened=opened,
        _catalog=SimpleNamespace(open_zarr=open_zarr, **catalog_members),
    )


def _run_over_file(path: Path) -> SimpleNamespace:
    def open_zarr(_sim_id: str) -> SimpleNamespace:
        return SimpleNamespace(root=zarr.open_group(str(path), mode="r"), close=lambda: None)

    return SimpleNamespace(sim_id="sim", _catalog=SimpleNamespace(open_zarr=open_zarr))


def test_frame_has_one_row_per_position(tmp_path: Path) -> None:
    root = zarr.open_group(str(tmp_path / "fields.zarr"), mode="w")
    group = root.create_group("particles")
    nan = np.nan
    group.create_array("x", data=np.array([[0.0, 1.0, 2.0], [5.0, 6.0, nan]]))
    group.create_array("y", data=np.array([[0.0, 0.0, 0.0], [5.0, 5.0, nan]]))
    group.create_array("z", data=np.array([[9.0, 8.0, 7.0], [4.0, 3.0, nan]]))
    group.create_array("time", data=np.array([[0.0, 12.0, 24.0], [0.0, 2.0, nan]]))
    group.attrs.update(
        {"time_units": "hours", "source_solver": "modflow6_prt", "source_file": "m_prt.trk.csv"}
    )

    frame = particle_frame(_run_over_file(tmp_path / "fields.zarr"))

    assert list(frame.columns) == list(PARTICLE_COLUMNS)
    assert frame["particle"].tolist() == [0, 0, 0, 1, 1]
    assert frame["step"].tolist() == [0, 1, 2, 0, 1]
    assert frame["time_days"].tolist() == [0.0, 0.5, 1.0, 0.0, 2.0 / 24.0]
    assert frame.attrs == {"source_solver": "modflow6_prt", "source_file": "m_prt.trk.csv"}


def test_empty_frame_without_particles(tmp_path: Path) -> None:
    zarr.open_group(str(tmp_path / "fields.zarr"), mode="w")

    frame = particle_frame(_run_over_file(tmp_path / "fields.zarr"))

    assert frame.empty
    assert list(frame.columns) == list(PARTICLE_COLUMNS)
    assert str(frame["particle"].dtype) == "int64"


def test_read_particles(monkeypatch) -> None:
    frame = pd.DataFrame(columns=list(PARTICLE_COLUMNS))
    monkeypatch.setattr(particles, "particle_frame", lambda run: frame)
    run = Run.__new__(Run)

    assert run.read("particles") is frame
    with pytest.raises(ValueError):
        run.read("particles", time=0)


def test_tracks_drop_padding_and_still_particles() -> None:
    nan = np.nan
    x = np.array([[0.0, 1.0, 2.0, nan], [5.0, nan, nan, nan], [0.0, 0.5, nan, nan]])
    y = np.array([[0.0, 0.0, 1.0, nan], [5.0, nan, nan, nan], [1.0, 1.5, nan, nan]])
    time = np.array([[0.0, 10.0, 30.0, nan], [0.0, nan, nan, nan], [2.0, 4.0, nan, nan]])
    run = _run_over({"particles": _Group({"x": x, "y": y, "time": time})})

    tracks = read_particle_tracks(run)

    assert [track.shape for track in tracks] == [(3, 4), (2, 4)]
    assert np.isnan(tracks[0][:, 2]).all(), "a store without z gives NaN depths"
    assert [travel_time(track) for track in tracks] == [30.0, 2.0]
    assert all(store.closed for store in run.opened)


_MOVED = np.array([[0.0, 1.0, np.nan], [2.0, np.nan, np.nan]])
_RELEASED = np.array([[0.0, np.nan, np.nan], [2.0, np.nan, np.nan]])
_CLOCK = np.array([[0.0, 5.0, np.nan], [0.0, np.nan, np.nan]])


@pytest.mark.parametrize(
    ("root", "timed", "expected"),
    [
        ({}, False, False),
        ({"particles": _Group({})}, False, False),
        ({"particles": _Group({"x": _MOVED})}, False, False),
        ({"particles": _Group({"x": _RELEASED, "y": _RELEASED})}, False, False),
        (
            {"particles": _Group({"x": np.array([[1.0], [2.0]]), "y": np.array([[1.0], [2.0]])})},
            False,
            False,
        ),
        ({"particles": _Group({"x": _MOVED, "y": _MOVED})}, False, True),
        ({"particles": _Group({"x": _MOVED, "y": _MOVED})}, True, False),
        ({"particles": _Group({"x": _MOVED, "y": _MOVED, "time": _RELEASED})}, True, False),
        ({"particles": _Group({"x": _MOVED, "y": _MOVED, "time": _CLOCK})}, True, True),
    ],
    ids=[
        "no group",
        "empty group",
        "x only",
        "never moved",
        "one position",
        "moved",
        "moved, no time",
        "time never advances",
        "moved and timed",
    ],
)
def test_has_particle_tracks(root, timed, expected) -> None:
    run = _run_over(root)

    assert has_particle_tracks(run, timed=timed) is expected
    assert all(store.closed for store in run.opened)


def test_no_track_without_particles() -> None:
    run = _run_over({})

    assert read_particle_tracks(run) == []
    assert particle_time_to_days(run) == 1.0


@pytest.mark.parametrize(
    ("unit", "factor"),
    [("days", 1.0), ("Hours", 1.0 / 24.0), ("year", 365.25)],
    ids=["days", "hours", "year"],
)
def test_time_unit_to_days(unit, factor) -> None:
    run = _run_over({"particles": _Group({"x": np.zeros((1, 2))}, attrs={"time_units": unit})})

    assert particle_time_to_days(run) == pytest.approx(factor)


def test_travel_time_needs_two_times() -> None:
    track = np.array([[0.0, 0.0, 0.0, 5.0], [1.0, 0.0, 0.0, np.nan]])

    assert np.isnan(travel_time(track))
