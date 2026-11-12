"""Module readers of ``results`` that other layers call instead of reaching into a run.

Display used to read ``run._catalog`` itself: the Zarr ``particles`` group, the
``crs_epsg`` column, the geographic metadata, the calibration sessions, the
stacks of the budget components. A run reading the session its seal names is
covered by ``test_calibration_trials.py``. Each read now has one public function here,
taking the run. ``Run`` stays at its 50 public attributes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.calibration_trials import calibration_sessions
from hydromodpy.results.run.array import acting_faces, acting_faces_over_run
from hydromodpy.results.run.particles import (
    has_particle_tracks,
    particle_time_to_days,
    read_particle_tracks,
    travel_time,
)


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


# -- particles ---------------------------------------------------------------


def test_particle_tracks_drop_the_padding_and_the_particles_that_never_moved() -> None:
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
)
def test_a_run_has_particle_tracks_when_a_particle_moved(root, timed, expected) -> None:
    run = _run_over(root)

    assert has_particle_tracks(run, timed=timed) is expected
    assert all(store.closed for store in run.opened)


def test_a_run_without_particles_has_no_track() -> None:
    run = _run_over({})

    assert read_particle_tracks(run) == []
    assert particle_time_to_days(run) == 1.0


@pytest.mark.parametrize(
    ("unit", "factor"), [("days", 1.0), ("Hours", 1.0 / 24.0), ("year", 365.25)]
)
def test_particle_times_convert_to_days_from_the_unit_the_extractor_wrote(unit, factor) -> None:
    run = _run_over({"particles": _Group({"x": np.zeros((1, 2))}, attrs={"time_units": unit})})

    assert particle_time_to_days(run) == pytest.approx(factor)


def test_a_track_timed_once_has_no_travel_time() -> None:
    track = np.array([[0.0, 0.0, 0.0, 5.0], [1.0, 0.0, 0.0, np.nan]])

    assert np.isnan(travel_time(track))


# -- geographic --------------------------------------------------------------


def _run_with_row(row: dict) -> SimpleNamespace:
    """Return a run whose index row is *row*."""
    return SimpleNamespace(sim_id="sim-crs", _load_row=lambda: row)


# -- calibration sessions ------------------------------------------------------


def test_a_source_with_no_session_behind_it_gives_an_empty_frame() -> None:
    frame = calibration_sessions(object())

    assert isinstance(frame, pd.DataFrame)
    assert frame.empty


# -- acting faces ------------------------------------------------------------


def test_a_block_that_is_not_the_mesh_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="'drain' budget holds 3 values"):
        acting_faces(np.zeros((2, 3)), "drain", 4)


def test_a_component_missing_from_the_store_is_refused_by_name() -> None:
    run = _run_over({"budget": {}})

    with pytest.raises(ValueError, match="'drain' budget is not an array"):
        acting_faces_over_run(run, ["drain"], 4)
    assert run.opened[0].closed


# -- deliveries --------------------------------------------------------------


def test_a_run_reads_the_latest_delivery_of_each_pair(tmp_path: Path) -> None:
    """``Run.deliveries`` reads ``published.jsonl`` and keeps the last line of a pair."""
    from hydromodpy.results.publication import PublishedLine, append_published
    from hydromodpy.results.run.view import Run

    for state, attempts in (("pending", 0), ("delivered", 1)):
        append_published(
            tmp_path,
            PublishedLine(
                kind="delivery",
                file="exports/head_last.tif",
                destination="/data/depot/head_last.tif",
                state=state,
                sha256="a" * 64,
                bytes=3,
                attempts=attempts,
                published_at=datetime(2026, 11, 10, tzinfo=UTC),
            ),
        )
    run = Run("sim", SimpleNamespace(run_dir_for=lambda sim_id: tmp_path))  # type: ignore[arg-type]

    assert [(line.state, line.attempts) for line in run.deliveries] == [("delivered", 1)]
