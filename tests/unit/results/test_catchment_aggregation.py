"""The catchment series of a run: supports, sources, routed discharge, runoff and time axis."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import ExtractError
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.results.derive.catchment_aggregation import (
    _active_cells,
    _from_field,
    _n_steps,
    _runoff_area_m2,
    aggregate_catchment_timeseries,
    catchment_support,
    catchment_term,
    series_time_index,
    with_runoff,
)
from tests._helpers.run_builders import runs

__all__ = ["runs"]

# 1 mm/day over 86.4 km2 is exactly 1 m3/s.
_AREA_KM2 = 86.4


class _FakeArray:
    """Minimal Zarr-array stand-in supporting slice reads and ``.shape``."""

    def __init__(self, data):
        self._data = np.asarray(data)

    @property
    def shape(self):
        return self._data.shape

    def __getitem__(self, key):
        return self._data[key]


class _DictGroup:
    """Dict-backed Zarr group: get, in, getitem, iter, and the keys of a runoff group."""

    def __init__(self, mapping):
        self._mapping = dict(mapping)

    def get(self, key):
        return self._mapping.get(key)

    def __contains__(self, key):
        return key in self._mapping

    def __getitem__(self, key):
        return self._mapping[key]

    def __iter__(self):
        return iter(self._mapping)

    def array_keys(self):
        return [k for k, v in self._mapping.items() if isinstance(v, _FakeArray)]

    def group_keys(self):
        return [k for k, v in self._mapping.items() if isinstance(v, _DictGroup)]


def _station(values, stamps):
    return _DictGroup({"values": _FakeArray(values), "timestamps": _FakeArray(stamps)})


def _runoff_grp(values, stamps, *, mesh=None):
    """A root group whose forcing holds one runoff station."""
    stamps = np.asarray(stamps, dtype="datetime64[ns]")
    runoff = _DictGroup({"station0": _station(np.asarray(values, dtype="float64"), stamps)})
    return _DictGroup({"forcing": _DictGroup({"runoff": runoff}), "mesh": mesh})


def _basin_mesh(*, area_m2, rule):
    """A ``mesh`` group holding a stored basin of D."""
    import zarr

    mesh = zarr.group().require_group("mesh")
    node = mesh.create_array("descent_basin", data=np.ones(4, dtype=bool))
    node.attrs["basin_rule"] = rule
    if area_m2 is not None:
        node.attrs["basin_area_m2"] = area_m2
    return mesh


class _Store:
    """A run store with a ``timeseries`` table, gauged or not, and a ``catch_area``."""

    def __init__(self, *, gauged: bool = False, area_km2: float | None = _AREA_KM2) -> None:
        source = "observed" if gauged else "simulated"
        self._rows = pd.DataFrame({"variable": ["discharge"], "source": [source]})
        self._area = area_km2

    def read_table(self, view_name):
        assert view_name == "timeseries"
        return self._rows

    def read_geographic_metadata(self, sim_id):
        del sim_id
        return {} if self._area is None else {"catch_area": self._area}


def _daily(values, start="2020-01-01"):
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(np.asarray(values, dtype="float64"), index=idx, name="discharge")


def _forcing_stamps(n, start="2019-12-31"):
    # A run stamps each day at its end, a daily forcing at its start.
    return pd.date_range(start, periods=n, freq="D").values


# -- with_runoff -------------------------------------------------------------


@pytest.mark.parametrize(
    ("grp", "store", "area_km2", "expected"),
    [
        pytest.param(
            _runoff_grp([1.0, 1.0, 1.0], _forcing_stamps(3)),
            None,
            _AREA_KM2,
            [11.0, 21.0, 31.0],
            id="aligned_m3_per_s",
        ),
        pytest.param(
            _runoff_grp([1.0, 3.0, 0.0], _forcing_stamps(3)),
            None,
            2 * _AREA_KM2,
            [12.0, 26.0, 30.0],
            id="linear_in_area",
        ),
        pytest.param(
            _runoff_grp(
                [1.0, 2.0, 4.0], pd.date_range("2019-12-31 02:00", periods=3, freq="D").values
            ),
            None,
            _AREA_KM2,
            [11.0, 22.0, 34.0],
            id="offset_stamps",
        ),
        pytest.param(
            _runoff_grp(
                [1.0, 1.0, 1.0],
                _forcing_stamps(3),
                mesh=_basin_mesh(area_m2=2 * 86.4e6, rule="near_point"),
            ),
            None,
            _AREA_KM2,
            [12.0, 22.0, 32.0],
            id="basin_area_wins",
        ),
        pytest.param(
            _runoff_grp(
                [1.0, 1.0, 1.0],
                _forcing_stamps(3),
                mesh=_basin_mesh(area_m2=5.0e9, rule="largest_basin"),
            ),
            None,
            _AREA_KM2,
            [11.0, 21.0, 31.0],
            id="largest_basin_keeps_catch_area",
        ),
        pytest.param(
            _DictGroup({"forcing": _DictGroup({"temperature": None})}),
            _Store(gauged=False),
            _AREA_KM2,
            [10.0, 20.0, 30.0],
            id="no_runoff_group",
        ),
    ],
)
def test_with_runoff_adds_the_runoff_in_m3_per_s(grp, store, area_km2, expected) -> None:
    store = store or _Store(area_km2=area_km2)

    out = with_runoff(_daily([10.0, 20.0, 30.0]), str(uuid4()), store, grp)

    assert list(out.index) == list(_daily([0, 0, 0]).index)
    np.testing.assert_allclose(out.to_numpy(), expected)


@pytest.mark.parametrize(
    ("area_km2", "expected"),
    [(None, [5.0, 7.0]), (0.5e-6, [5.0 + 10.0e-3 * 0.5 / 86400.0, 7.0 + 10.0e-3 * 0.5 / 86400.0])],
    ids=["no_area", "tiny_area"],
)
def test_a_zero_area_skips_the_runoff_and_says_so(caplog, area_km2, expected) -> None:
    grp = _runoff_grp([10.0, 10.0], _forcing_stamps(2))

    with caplog.at_level("WARNING"):
        out = with_runoff(_daily([5.0, 7.0]), "sim-0", _Store(area_km2=area_km2), grp)

    np.testing.assert_allclose(out.to_numpy(), expected, rtol=1e-12)
    said = (
        "catchment discharge: catchment area unavailable for sim sim-0 — skipping runoff addition."
    )
    assert (said in caplog.text) is (area_km2 is None)


def test_a_station_that_cannot_be_read_is_skipped_and_the_next_one_is_kept() -> None:
    day = np.array(["2019-12-31"], dtype="datetime64[ns]")
    stations = {
        "flat": _FakeArray([9.0]),
        "bare": _DictGroup({"values": _FakeArray([9.0])}),
        "empty": _station(np.empty(0), np.empty(0, dtype="datetime64[ns]")),
        "good": _station([4.0], day),
    }
    grp = _DictGroup({"forcing": _DictGroup({"runoff": _DictGroup(stations)})})

    out = with_runoff(_daily([1.0]), "sim-0", _Store(), grp)

    np.testing.assert_allclose(out.to_numpy(), [5.0])


@pytest.mark.parametrize(
    ("gauged", "warnings"), [(False, 0), (True, 2)], ids=["ungauged", "gauged"]
)
def test_a_run_without_runoff_warns_at_each_call_only_against_a_gauge(caplog, gauged, warnings):
    # No state is kept between calls: each call that has something to say says it.
    sim_id = str(uuid4())
    discharge = _daily([1.0, 2.0])
    with caplog.at_level("WARNING"):
        for _ in range(2):
            out = with_runoff(discharge, sim_id, _Store(gauged=gauged), _DictGroup({}))

    pd.testing.assert_series_equal(out, discharge)
    said = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert (
        said
        == [
            "Simulated discharge is baseflow only: the run has no runoff forcing, "
            "so it underestimates a gauged total streamflow."
        ]
        * warnings
    )


def test_a_stored_basin_that_states_no_area_is_refused_by_name() -> None:
    grp = _runoff_grp(
        [1.0, 1.0], _forcing_stamps(2), mesh=_basin_mesh(area_m2=None, rule="near_point")
    )

    with pytest.raises(ExtractError, match="states no area"):
        with_runoff(_daily([0.0, 0.0]), str(uuid4()), _Store(), grp)


def test_the_runoff_area_does_not_compute_the_basin_again(monkeypatch) -> None:
    from hydromodpy.catchment.drainage import descent as core_descent
    from hydromodpy.solver.modflow_common import catchment_basin

    def refuse(*_args, **_kwargs):
        raise AssertionError("the runoff area computed the basin of D again")

    monkeypatch.setattr(core_descent, "descent_basin", refuse)
    monkeypatch.setattr(catchment_basin, "descent_basin", refuse)
    grp = _runoff_grp(
        [1.0, 1.0], _forcing_stamps(2), mesh=_basin_mesh(area_m2=2 * 86.4e6, rule="near_point")
    )

    out = with_runoff(_daily([0.0, 0.0]), str(uuid4()), _Store(), grp)

    np.testing.assert_allclose(out.to_numpy(), [2.0, 2.0])


def test_a_run_without_a_basin_scales_by_catch_area_and_says_so(caplog) -> None:
    grp = _runoff_grp([1.0, 1.0], _forcing_stamps(2))

    with caplog.at_level("INFO"):
        out = with_runoff(_daily([0.0, 0.0]), "sim-x", _Store(), grp)

    np.testing.assert_allclose(out.to_numpy(), [1.0, 1.0])
    assert (
        "Catchment discharge for sim sim-x: the run stores no basin of D, so the runoff is "
        "scaled by the old support 'catch_area' (86.400 km2)." in caplog.text
    )


@pytest.mark.parametrize(("stored", "area_m2"), [({"catch_area": 12.5}, 12.5e6), (None, 0.0)])
def test_the_catch_area_is_read_in_km2_and_returned_in_m2(runs, stored, area_m2) -> None:
    sid = runs.open(solver="modflow_nwt", n_cells=4, n_layers=1, n_timesteps=2).sim_id
    if stored is not None:
        runs.store(sid).write_geographic_metadata(sid, stored)

    assert _runoff_area_m2(runs.store(sid), sid, _DictGroup({})) == pytest.approx(area_m2)


# -- the zarr group: steps, active cells, per-cell field -----------------------


@pytest.mark.parametrize(
    ("grp", "n"),
    [
        (
            _DictGroup(
                {
                    "head": _FakeArray(np.zeros((5, 3))),
                    "derived": _DictGroup({"wt": _FakeArray(np.zeros((2, 3)))}),
                }
            ),
            5,
        ),
        (_DictGroup({"derived": _DictGroup({"wt": _FakeArray(np.zeros((4, 3)))})}), 4),
        (_DictGroup({}), 0),
    ],
    ids=["head_first", "first_derived", "nothing"],
)
def test_the_number_of_steps_is_read_from_head_then_derived(grp, n) -> None:
    assert _n_steps(grp) == n


@pytest.mark.parametrize(
    ("grp", "active"),
    [
        (_DictGroup({}), None),
        (_DictGroup({"mesh": _DictGroup({})}), None),
        (
            _DictGroup(
                {"mesh": _DictGroup({"topography": _FakeArray([10.0, -9999.0, 5.0, np.nan, 0.0])})}
            ),
            [True, False, True, False, True],
        ),
    ],
    ids=["no_mesh", "no_topography", "finite_above_sentinel"],
)
def test_the_active_cells_have_a_finite_top_above_the_sentinel(grp, active) -> None:
    got = _active_cells(grp)
    assert got is None if active is None else got.tolist() == active


@pytest.mark.parametrize(
    ("grp", "term", "support", "expected"),
    [
        pytest.param(
            _DictGroup({"drain": _FakeArray([[-1.0, 2.0, -3.0], [4.0, -5.0, 6.0]])}),
            "drain",
            None,
            ([2.0, 10.0], [4.0, 5.0]),
            id="root_array",
        ),
        pytest.param(
            _DictGroup(
                {
                    "derived": _DictGroup({"flux": _FakeArray([[10.0, 10.0]])}),
                    "flux": _FakeArray([[1.0, 1.0]]),
                }
            ),
            "flux",
            None,
            ([20.0], [0.0]),
            id="derived_over_root",
        ),
        pytest.param(
            _DictGroup(
                {
                    "budget": _DictGroup({"drain": _FakeArray([[-1.0, -2.0]])}),
                    "drain": _FakeArray([[-9.0, -9.0]]),
                }
            ),
            "drain",
            None,
            ([0.0], [3.0]),
            id="budget_over_root",
        ),
        pytest.param(
            _DictGroup({"drain": _FakeArray([[1.0, 999.0, 2.0]])}),
            "drain",
            np.array([True, False, True]),
            ([3.0], [0.0]),
            id="mask",
        ),
        pytest.param(
            _DictGroup({"drain": _FakeArray([[10.0, 20.0, -9999.0]])}),
            "drain",
            np.array([True, False]),
            ([30.0], [0.0]),
            id="mask_size_ignored",
        ),
        pytest.param(
            _DictGroup({"drain": _FakeArray([[[1.0, -2.0], [-0.4, 3.0]]])}),
            "drain",
            None,
            ([4.0], [2.4]),
            id="two_layers_split",
        ),
    ],
)
def test_a_per_cell_field_is_split_over_the_support(grp, term, support, expected) -> None:
    inflow, outflow = _from_field(grp, term, len(expected[0]), support)

    np.testing.assert_allclose(inflow, expected[0])
    np.testing.assert_allclose(outflow, expected[1])


@pytest.mark.parametrize(
    "grp",
    [
        _DictGroup({"head": _FakeArray(np.zeros((1, 3)))}),
        _DictGroup({"drain": _FakeArray([[1.0]])}),
    ],
    ids=["missing", "too_short"],
)
def test_a_field_the_run_does_not_hold_for_every_step_is_none(grp) -> None:
    assert _from_field(grp, "drain", 2, None) is None


# -- the time axis -----------------------------------------------------------


def _utc(day: str):
    """The instant a run records for a calendar day: midnight UTC."""
    return pd.Timestamp(day, tz="UTC").to_pydatetime()


def test_the_time_axis_falls_back_on_the_period_bounds(runs) -> None:
    sid = runs.open(
        solver="modflow_nwt",
        n_cells=3,
        n_layers=1,
        n_timesteps=4,
        period_start=_utc("2020-01-01"),
        period_end=_utc("2020-01-04"),
    ).sim_id

    idx = series_time_index(runs.store(sid), sid, 4)

    naive = idx.tz_localize(None) if idx.tz is not None else idx
    assert len(idx) == 4 and idx.is_monotonic_increasing
    assert naive[0].date().isoformat() == "2020-01-01"
    assert naive[-1].date().isoformat() == "2020-01-04"


def test_a_run_without_an_axis_or_bounds_has_no_time_axis(runs) -> None:
    sid = runs.open(solver="modflow_nwt", n_cells=3, n_layers=1, n_timesteps=2).sim_id
    with pytest.raises(RuntimeError, match="period_start"):
        series_time_index(runs.store(sid), sid, 2)


# -- the sources of a term ---------------------------------------------------


def _register(runs, n_ts: int = 3, n_cells: int = 4, solver: str = "modflow6") -> str:
    return runs.open(
        solver=solver,
        n_cells=n_cells,
        n_layers=1,
        n_timesteps=n_ts,
        period_start=_utc("2020-01-01"),
        period_end=_utc(f"2020-01-0{max(n_ts, 2)}"),
    ).sim_id


def _write_rows(runs, sid, zone, values, *, component="drain", flux_in=0.0):
    for timestep, flux_out in values.items():
        runs.store(sid).write_budget(
            sid,
            timestep=timestep,
            zone_id=zone,
            component=component,
            flux_in=flux_in,
            flux_out=flux_out,
        )


def _term(runs, sid, term, n, *, grp=None, support=None):
    return catchment_term(runs.store(sid), sid, grp or _DictGroup({}), term, n, support)


@pytest.mark.parametrize(
    ("rows", "term", "n", "inflow", "outflow"),
    [
        pytest.param(
            [("total", {0: 10.0, 1: 8.0, 2: 4.0})],
            "drain",
            3,
            [0, 0, 0],
            [10.0, 8.0, 4.0],
            id="domain_row",
        ),
        pytest.param(
            [("total", {0: 10.0, 2: 4.0})],
            "drain",
            3,
            [0, np.nan, 0],
            [10.0, np.nan, 4.0],
            id="gap_is_nan",
        ),
        pytest.param(
            [("0", {0: 2.119, 1: 2.0}), (CATCHMENT, {0: 0.888, 1: 0.8})],
            "drain",
            2,
            [0, 0],
            [0.888, 0.8],
            id="catchment_row_wins",
        ),
        pytest.param(
            [("0", {0: 2.0}), (CATCHMENT, {0: 0.5})], "drain", 1, [0], [0.5], id="rows_never_summed"
        ),
    ],
)
def test_a_term_is_read_from_its_lumped_rows(runs, rows, term, n, inflow, outflow) -> None:
    sid = _register(runs, n_ts=n)
    for zone, values in rows:
        _write_rows(runs, sid, zone, values, component=term)

    got_in, got_out = _term(runs, sid, term, n)

    np.testing.assert_allclose(got_in, inflow)
    np.testing.assert_allclose(got_out, outflow)


def test_a_signed_term_gives_its_inflow_and_outflow(runs) -> None:
    sid = _register(runs, n_ts=1)
    _write_rows(runs, sid, "total", {0: 4.0}, component="well", flux_in=1.0)

    inflow, outflow = _term(runs, sid, "well", 1)

    assert inflow[0] - outflow[0] == pytest.approx(-3.0)


def test_a_term_the_run_does_not_hold_is_none(runs) -> None:
    sid = _register(runs, n_ts=1)
    _write_rows(runs, sid, "total", {0: 1.0})

    assert _term(runs, sid, "river", 1) is None


def test_an_unreadable_budgets_table_is_refused(runs) -> None:
    class _BrokenStore:
        def read_table(self, view_name):
            raise RuntimeError(f"{view_name} table is unreadable")

    with pytest.raises(ExtractError, match="lumped budget"):
        catchment_term(_BrokenStore(), "sim", _DictGroup({}), "drain", 1, None)


def _grp_with_domain(n_cells: int):
    topography = _FakeArray(np.full(n_cells, 10.0))
    return _DictGroup({"mesh": _DictGroup({"topography": topography})})


@pytest.mark.parametrize(
    ("support", "said"),
    [
        pytest.param(np.arange(100) < 42, "42%", id="part_of_the_domain"),
        pytest.param(np.arange(4) < 2, "50%", id="half"),
        pytest.param(np.ones(100, dtype=bool), None, id="domain_is_the_catchment"),
        pytest.param(None, None, id="share_unknown"),
    ],
)
def test_a_domain_row_is_used_never_rescaled_and_warned_about(runs, caplog, support, said):
    sid = _register(runs, n_ts=1)
    _write_rows(runs, sid, "0", {0: 2.119})
    grp = _grp_with_domain(100 if support is None else support.size)

    with caplog.at_level("WARNING"):
        _, outflow = _term(runs, sid, "drain", 1, grp=grp, support=support)

    # A domain total rescaled by an area ratio would be a number nothing measured.
    np.testing.assert_allclose(outflow, [2.119])
    message = " ".join(r.getMessage() for r in caplog.records)
    if said is None:
        assert caplog.records == []
    else:
        assert "NOT rescaled" in message and said in message


def test_a_domain_with_no_active_cell_says_nothing(runs, caplog) -> None:
    sid = _register(runs, n_ts=1)
    _write_rows(runs, sid, "0", {0: 1.0})
    grp = _DictGroup({"mesh": _DictGroup({"topography": _FakeArray(np.full(4, np.nan))})})

    with caplog.at_level("WARNING"):
        _term(runs, sid, "drain", 1, grp=grp, support=np.zeros(4, dtype=bool))

    assert caplog.records == []


# -- the series written ------------------------------------------------------


def _with_head(runs, sid, n_ts, n_cells):
    for t in range(n_ts):
        runs.store(sid).write_field(
            sid, "head", t, np.full((1, n_cells), 5.0), n_timesteps=n_ts if t == 0 else None
        )


def _with_drain(runs, sid, frames):
    for t, frame in enumerate(frames):
        runs.store(sid).write_field(
            sid, "drain", t, np.asarray([frame]), n_timesteps=len(frames) if t == 0 else None
        )


def _discharge(runs, sid):
    aggregate_catchment_timeseries(sid, runs.store(sid))
    return runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge").values


_DRAINS = ([-1.0, -2.0, -3.0, -4.0], [-2.0, -2.0, -2.0, -2.0], [-1.0, -1.0, -1.0, -1.0])


def test_the_discharge_is_the_drain_outflow_summed_over_the_cells(runs) -> None:
    sid = _register(runs, solver="modflow_nwt")
    _with_head(runs, sid, 3, 4)
    _with_drain(runs, sid, [[-1.0, -2.0, -3.0, -4.0], [-2.0] * 4, [-1.0, -1.0, -1.0, 1.0]])

    np.testing.assert_allclose(sorted(_discharge(runs, sid)), [3.0, 8.0, 10.0])
    rows = runs.store(sid).read_table("timeseries")
    assert set(rows.loc[rows["variable"] == "discharge", "unit"]) == {"m3 s-1"}


def test_a_surface_excess_is_water_that_reaches_the_discharge(runs) -> None:
    # A Boussinesq run sends its water through the excess: the drain alone reads zero.
    sid = runs.open(solver="boussinesq", n_cells=4, n_layers=1, n_timesteps=2).sim_id
    store = runs.store(sid)
    store.write_time(sid, np.array([86400.0, 172800.0]), units="seconds since 1970-01-01")
    store.write_field(sid, "head", 0, np.zeros((1, 4)), n_timesteps=2)
    store.write_field(sid, "head", 1, np.zeros((1, 4)))
    for t, (drain, excess) in enumerate([(-1.0e-9, -2.0), (-1.0e-9, -3.0)]):
        kept = {"n_timesteps": 2} if t == 0 else {}
        store.write_field(sid, "drain", t, np.full(4, drain), subgroup="budget", **kept)
        store.write_field(sid, "surface_excess", t, np.full(4, excess), subgroup="budget", **kept)

    np.testing.assert_allclose(_discharge(runs, sid), [8.0 + 4e-9, 12.0 + 4e-9])


def test_a_run_with_nothing_to_aggregate_writes_nothing(runs) -> None:
    sid = _register(runs, solver="modflow_nwt")
    _with_head(runs, sid, 3, 4)

    aggregate_catchment_timeseries(sid, runs.store(sid))

    with pytest.raises(KeyError):
        runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")


def test_the_lumped_budget_alone_gives_the_discharge(runs) -> None:
    sid = _register(runs)
    _with_head(runs, sid, 3, 4)
    _write_rows(runs, sid, "total", {0: 10.0, 1: 8.0, 2: 4.0})

    np.testing.assert_allclose(_discharge(runs, sid), [10.0, 8.0, 4.0])


@pytest.mark.parametrize(
    ("zone", "values", "expected"),
    [
        pytest.param(
            CATCHMENT,
            {0: 3.141592653589793, 1: 2.718281828459045},
            [3.141592653589793, 2.718281828459045],
            id="catchment_row_exact",
        ),
        pytest.param("0", {0: 99.0, 1: 99.0}, [4.0, 4.0], id="domain_row_loses"),
    ],
)
def test_the_catchment_row_beats_the_rounded_per_cell_field(runs, zone, values, expected) -> None:
    sid = _register(runs, n_ts=2)
    _with_head(runs, sid, 2, 4)
    _with_drain(runs, sid, [[-1.0] * 4, [-1.0] * 4])
    _write_rows(runs, sid, zone, values)

    assert _discharge(runs, sid).tolist() == expected


def test_two_layers_of_mixed_sign_are_split_per_element(runs) -> None:
    sid = runs.open(
        solver="modflow6",
        n_cells=2,
        n_layers=2,
        n_timesteps=1,
        period_start=_utc("2020-01-01"),
        period_end=_utc("2020-01-02"),
    ).sim_id
    store = runs.store(sid)
    store.write_field(sid, "head", 0, np.zeros((2, 2)), n_timesteps=1)
    store.write_field(sid, "drain", 0, np.array([[-1.0, -2.0], [-0.5, 0.0]]), n_timesteps=1)
    store.write_field(sid, "well", 0, np.array([[1.0, 0.0], [-0.5, 0.0]]), n_timesteps=1)

    aggregate_catchment_timeseries(sid, store)

    np.testing.assert_allclose(store.query_timeseries(sid, CATCHMENT, "discharge").values, [3.5])
    np.testing.assert_allclose(store.query_timeseries(sid, CATCHMENT, "well_pumping").values, [0.5])
    inflow, outflow = _term(
        runs, sid, "well", 1, grp=_DictGroup({"well": _FakeArray([[[1.0, 0.0], [-0.4, 0.0]]])})
    )
    assert (inflow[0], outflow[0]) == pytest.approx((1.0, 0.4))


def test_a_second_aggregation_warns_again_without_module_state(runs, caplog) -> None:
    sid = _register(runs, n_ts=1)
    _with_head(runs, sid, 1, 4)
    _write_rows(runs, sid, "0", {0: 2.0})
    sz = runs.store(sid).open_zarr(sid)
    try:
        mesh = sz.root.require_group("mesh")
        mesh.create_array("topography", data=np.full(4, 10.0))
        basin = mesh.create_array("descent_basin", data=np.array([True, True, False, False]))
        basin.attrs["basin_rule"] = "near_point"
        basin.attrs["basin_area_m2"] = 2.0e6
    finally:
        sz.close()

    with caplog.at_level("WARNING"):
        for _ in range(2):
            aggregate_catchment_timeseries(sid, runs.store(sid))

    assert sum("NOT rescaled" in r.getMessage() for r in caplog.records) == 2


class TestRoutedDischarge:
    """discharge = SFR/LAK ext_outflow only (buffer DRN excluded) when routed."""

    def _sim(self, runs, *, with_drains=True):
        sid = _register(runs)
        _with_head(runs, sid, 3, 4)
        if with_drains:
            _with_drain(runs, sid, _DRAINS)
        return sid

    def _ext_outflow(self, runs, sid, station, values, source="simulated"):
        idx = pd.date_range("2020-01-01", periods=len(values), freq="D")
        runs.store(sid).write_timeseries(
            sid, station, "ext_outflow", pd.Series(values, index=idx), unit="m3/s", source=source
        )

    def test_discharge_is_routed_outflow_excluding_buffer_drains(self, runs):
        sid = self._sim(runs)
        self._ext_outflow(runs, sid, "net:7", [1.0, 2.0, 3.0])
        self._ext_outflow(runs, sid, "net:2", [0.0, 0.0, 0.0])
        self._ext_outflow(runs, sid, "lake:res", [0.5, 0.5, 1.0])

        np.testing.assert_allclose(_discharge(runs, sid), [1.5, 2.5, 4.0])

    def test_the_drains_are_added_when_no_network_routes_them(self, runs):
        sid = self._sim(runs)
        self._ext_outflow(runs, sid, "lake:res", [0.5, 0.5, 1.0])

        aggregate_catchment_timeseries(sid, runs.store(sid), drainage_outside_routed=True)

        got = runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge").values
        np.testing.assert_allclose(got, [10.5, 8.5, 5.0])

    def test_the_discharge_is_summed_over_the_stored_basin(self, runs):
        sid = self._sim(runs)
        sz = runs.store(sid).open_zarr(sid)
        try:
            mesh = sz.root.require_group("mesh")
            mesh.create_array("topography", data=np.full(4, 10.0))
            basin = mesh.create_array("descent_basin", data=np.array([True, True, False, False]))
            basin.attrs["basin_rule"] = "near_point"
            basin.attrs["basin_area_m2"] = 2.0e6
        finally:
            sz.close()
        for t in range(3):
            runs.store(sid).write_field(sid, "drain", t, np.array([[-1.0, -2.0, -4.0, -8.0]]))

        np.testing.assert_allclose(_discharge(runs, sid), [3.0, 3.0, 3.0])

    def test_the_routed_branch_adds_no_lumped_runoff(self, runs, monkeypatch):
        import hydromodpy.results.derive.catchment_aggregation as mod

        def _must_not_run(*args, **kwargs):
            raise AssertionError("lumped runoff must not be added on the routed branch")

        monkeypatch.setattr(mod, "with_runoff", _must_not_run)
        sid = self._sim(runs)
        self._ext_outflow(runs, sid, "net:7", [1.0, 1.0, 1.0])

        np.testing.assert_allclose(_discharge(runs, sid), [1.0, 1.0, 1.0])

    def test_routed_only_discharge_written_without_drain_field(self, runs):
        sid = self._sim(runs, with_drains=False)
        self._ext_outflow(runs, sid, "net:7", [2.0, 4.0, 6.0])

        np.testing.assert_allclose(_discharge(runs, sid), [2.0, 4.0, 6.0])

    def test_a_measured_outflow_does_not_trigger_routed_branch(self, runs):
        sid = self._sim(runs)
        self._ext_outflow(runs, sid, "G1", [100.0] * 3, source="observed")

        np.testing.assert_allclose(_discharge(runs, sid), [10.0, 8.0, 4.0])


# -- the support -------------------------------------------------------------


class TestTheCatchmentSeriesUseTheCatchment:
    """The station is named ``catchment``. The support has to be one.

    MODFLOW-NWT meshes the delineated basin so domain and catchment coincide,
    MODFLOW 6 meshes the buffered box so they do not. On the Nancon at 25 m,
    152.2 km2 of domain against 64.6 km2 of catchment, 2.119 m3/s of drain
    outflow against 0.888 m3/s inside the basin.
    """

    def _grp(self, n_cells: int):
        """A one-row mesh of unit squares, its frame where a run writes it."""
        import zarr

        root = zarr.group()
        mesh = root.require_group("mesh")
        x = np.arange(n_cells + 1, dtype="float64")
        vertices = np.array(
            [[float(v), 0.0, 0.0] for v in x] + [[float(v), 1.0, 0.0] for v in x], dtype="float64"
        )
        n_x = x.size
        connectivity = np.array(
            [[i, i + 1, n_x + i + 1, n_x + i] for i in range(n_cells)], dtype="int32"
        )
        mesh.create_array("vertices", data=vertices)
        mesh.create_array("face_node_connectivity", data=connectivity)
        mesh.create_array("topography", data=np.full(n_cells, 10.0, dtype="float64"))
        # The CF grid-mapping scalar at the root carries crs_wkt. A fixture that
        # put it on the mesh group stayed green while every real run failed.
        crs = root.create_array("crs", shape=(), dtype="int32")
        crs.attrs["grid_mapping_name"] = "lambert_conformal_conic"
        crs.attrs["crs_wkt"] = "EPSG:2154"
        return root

    def _with_basin(self, grp, mask, *, rule="within_polygon", area_m2=2.0e6):
        node = grp["mesh"].create_array("descent_basin", data=np.asarray(mask, dtype=bool))
        node.attrs["descent_outlet"] = 0
        node.attrs["basin_rule"] = rule
        node.attrs["basin_area_m2"] = area_m2
        return grp

    @staticmethod
    def _watershed(geometry):
        class _Store:
            def read_geographic_feature(self, sim_id, name):
                import geopandas as gpd

                del sim_id
                if geometry is None:
                    raise KeyError(name)
                return gpd.GeoDataFrame(geometry=[geometry], crs="EPSG:2154")

        return _Store()

    def test_only_the_cells_inside_the_watershed_are_kept(self, caplog):
        from shapely.geometry import box

        with caplog.at_level("INFO"):
            mask = catchment_support(
                self._watershed(box(-0.1, -0.1, 2.0, 1.1)), "sim", self._grp(6), np.ones(6, bool)
            )

        assert mask.tolist() == [True, True, False, False, False, False]
        assert (
            "Catchment timeseries for sim sim: the run stores no basin of D, so the "
            "catchment series keep the old support 'polygon_centroid'." in caplog.text
        )

    @pytest.mark.parametrize(
        ("geometry", "drop_crs", "said"),
        [
            pytest.param(None, False, "no delineated watershed", id="no_watershed"),
            pytest.param("near", True, "declares no CRS", id="no_frame"),
            pytest.param("far", False, "covers no cell", id="lands_nowhere"),
        ],
    )
    def test_a_watershed_that_cannot_be_placed_keeps_the_domain_and_says_so(
        self, caplog, geometry, drop_crs, said
    ):
        from shapely.geometry import box

        shapes = {"near": box(-0.1, -0.1, 2.0, 1.1), "far": box(1e6, 1e6, 1e6 + 10, 1e6 + 10)}
        grp = self._grp(4)
        if drop_crs:
            del grp["crs"]
        active = np.ones(4, dtype=bool)
        with caplog.at_level("WARNING"):
            mask = catchment_support(self._watershed(shapes.get(geometry)), "sim", grp, active)

        assert mask is active
        message = " ".join(r.getMessage() for r in caplog.records)
        assert said in message and "neighbouring basins" in message

    def test_a_mesh_without_geometry_keeps_the_domain(self):
        active = np.ones(3, dtype=bool)
        assert catchment_support(None, "sim", _grp_with_domain(3), active) is active

    def test_the_stored_basin_is_the_support_not_the_polygon(self, caplog):
        class _Store:
            def read_geographic_feature(self, sim_id, name):
                raise AssertionError("the polygon was read although the run stores a basin")

        grp = self._with_basin(self._grp(6), [1, 1, 1, 0, 0, 1])
        with caplog.at_level("INFO"):
            mask = catchment_support(_Store(), "sim", grp, np.array([1, 1, 0, 1, 1, 1], bool))

        assert mask.tolist() == [True, True, False, False, False, True]
        assert "the basin of D, 3 of 5 active cells (2.000 km2)" in caplog.text
        assert "polygon_centroid" not in caplog.text

    def test_a_basin_with_no_active_cell_is_refused(self):
        grp = self._with_basin(self._grp(4), [1, 1, 0, 0])
        with pytest.raises(ExtractError, match="holds no active cell"):
            catchment_support(None, "sim", grp, np.array([0, 0, 1, 1], dtype=bool))

    def test_the_largest_basin_of_a_synthetic_domain_keeps_the_domain(self, caplog):
        grp = self._with_basin(self._grp(4), [1, 1, 1, 1], rule="largest_basin")
        active = np.ones(4, dtype=bool)
        with caplog.at_level("INFO"):
            mask = catchment_support(self._watershed(None), "sim", grp, active)

        assert mask is active
        assert "stores no basin of D" not in caplog.text

    def test_no_series_computes_the_basin_again(self, monkeypatch):
        from hydromodpy.catchment.drainage import descent as core_descent
        from hydromodpy.solver.modflow_common import catchment_basin

        def refuse(*_args, **_kwargs):
            raise AssertionError("the aggregation computed the basin of D again")

        monkeypatch.setattr(core_descent, "descent_basin", refuse)
        monkeypatch.setattr(catchment_basin, "descent_basin", refuse)
        grp = self._with_basin(self._grp(4), [1, 0, 1, 0])

        mask = catchment_support(None, "sim", grp, np.ones(4, dtype=bool))

        assert mask.tolist() == [True, False, True, False]
