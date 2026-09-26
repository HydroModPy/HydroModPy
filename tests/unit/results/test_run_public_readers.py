"""Module readers of ``results`` that other layers call instead of reaching into a run.

Display used to read ``run._catalog`` itself: the Zarr ``particles`` group, the
``crs_epsg`` column, the geographic metadata, the calibration sessions, the
stacks of the budget components. Each read now has one public function here,
taking the run. ``Run`` stays at its 50 public attributes.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.calibration_trials import calibration_sessions
from hydromodpy.results.run.array import acting_faces, acting_faces_over_run
from hydromodpy.results.run.geographic import crs_epsg, geographic_metadata
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


def _run_with_simulations(rows: pd.DataFrame) -> SimpleNamespace:
    asked: list[tuple[str, list]] = []

    def query(sql, params):
        asked.append((sql, params))
        return rows

    return SimpleNamespace(
        sim_id="sim-crs",
        asked=asked,
        _catalog=SimpleNamespace(backend=SimpleNamespace(query=query)),
    )


def test_the_run_crs_is_the_epsg_code_the_catalog_recorded() -> None:
    run = _run_with_simulations(pd.DataFrame({"crs_epsg": [2154]}))

    assert crs_epsg(run) == 2154
    assert run.asked[0][1] == ["sim-crs"]


@pytest.mark.parametrize(
    "rows",
    [
        pd.DataFrame({"crs_epsg": []}),
        pd.DataFrame({"crs_epsg": [None]}),
        pd.DataFrame({"crs_epsg": [np.nan]}),
        pd.DataFrame({"crs_epsg": pd.array([None], dtype="Int32")}),
    ],
)
def test_a_run_without_a_recorded_crs_has_none(rows) -> None:
    assert crs_epsg(_run_with_simulations(rows)) is None


def test_a_null_crs_read_through_duckdb_is_none() -> None:
    """``simulations.crs_epsg`` is an INTEGER column: DuckDB hands a NULL to
    pandas as ``pd.NA`` in a nullable ``Int32``, whose truth value raises."""
    duckdb = pytest.importorskip("duckdb")
    rows = duckdb.connect().execute("SELECT CAST(NULL AS INTEGER) AS crs_epsg").fetchdf()

    assert crs_epsg(_run_with_simulations(rows)) is None


def test_the_geographic_metadata_is_what_the_catalog_holds_for_the_run() -> None:
    asked: list[str] = []

    def read_geographic_metadata(sim_id):
        asked.append(sim_id)
        return {"x_outlet": "351200.0", "y_outlet": "6789000.0"}

    run = SimpleNamespace(
        sim_id="sim-geo",
        _catalog=SimpleNamespace(read_geographic_metadata=read_geographic_metadata),
    )

    assert geographic_metadata(run) == {"x_outlet": "351200.0", "y_outlet": "6789000.0"}
    assert asked == ["sim-geo"]


# -- calibration sessions ------------------------------------------------------


def test_a_run_reads_the_sessions_of_the_catalog_it_comes_from() -> None:
    sessions = pd.DataFrame({"session_id": ["s1", "s2"], "phase_index": [0, 1]})
    run = SimpleNamespace(_catalog=SimpleNamespace(calibration_sessions=sessions))

    assert calibration_sessions(run)["session_id"].tolist() == ["s1", "s2"]


def test_a_run_shaped_adapter_reads_the_sessions_it_carries() -> None:
    class _Adapter:
        calibration_sessions = [{"session_id": "s1", "phase_index": 0}]

    assert calibration_sessions(_Adapter())["session_id"].tolist() == ["s1"]


def test_a_source_with_no_session_behind_it_gives_an_empty_frame() -> None:
    frame = calibration_sessions(object())

    assert isinstance(frame, pd.DataFrame)
    assert frame.empty


# -- acting faces ------------------------------------------------------------


def test_a_face_acts_when_any_layer_carries_a_finite_non_zero_flux() -> None:
    values = np.array(
        [
            [[0.0, 1.0, 0.0, np.nan], [0.0, 0.0, 0.0, 0.0]],
            [[0.0, 0.0, 0.0, 0.0], [2.0, -2.0, 0.0, np.inf]],
        ]
    )

    assert acting_faces(values, "drain", 4).tolist() == [True, True, False, False]


def test_a_block_that_is_not_the_mesh_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="'drain' budget holds 3 values"):
        acting_faces(np.zeros((2, 3)), "drain", 4)


def test_the_whole_run_is_read_in_one_opening_of_the_store() -> None:
    """Asked one timestep at a time, a daily decade over six components is
    tens of thousands of openings; the whole run is one."""
    drain = np.zeros((200, 4))
    drain[0, 0] = -1.0
    drain[150, 3] = -1.0
    river = np.zeros((200, 4))
    river[:, 2] = -1.0
    run = _run_over({"budget": {"drain": drain, "river": river}})

    acting = acting_faces_over_run(run, ["drain", "river"], 4)

    assert acting["drain"].tolist() == [True, False, False, True]
    assert acting["river"].tolist() == [False, False, True, False]
    assert len(run.opened) == 1
    assert run.opened[0].closed, "the store is released once the stacks are read"


def test_a_component_missing_from_the_store_is_refused_by_name() -> None:
    run = _run_over({"budget": {}})

    with pytest.raises(ValueError, match="'drain' budget is not an array"):
        acting_faces_over_run(run, ["drain"], 4)
    assert run.opened[0].closed
