"""Cost of a trial from simulated series (m3/s, m) paired with observed records.

Builds the metric function a trial calls. Gauges are scored on the discharge at
their own cell, heads and lake levels on their stamps, and a window or a minimum
overlap decides which pairs count. Also covers the residual capture and the
station series a promoted run writes.
"""

from __future__ import annotations

import inspect
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config_objective import CalibObjectiveBlockDecl
from hydromodpy.calibration.config_outputs import validate_calib_output
from hydromodpy.calibration.config_phases import CalibPhaseDecl
from hydromodpy.calibration.config_terms import window_bounds
from hydromodpy.calibration.metrics import composite
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.composite import (
    _area_id,
    _cell_id,
    _discharge_by_station,
    _head_by_station,
    build_metric_extractor,
    build_paired_vector_capture,
)
from hydromodpy.calibration.metrics.observable_scoring import (
    ObservableScorer,
    select_observable_times,
)
from hydromodpy.calibration.metrics.observed_pairing import (
    observed_series_for_outputs,
    pair_outputs_with_observations,
)
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.calibration.metrics.solver_extract import ExtractedOutputs
from hydromodpy.calibration.protocols.registry import expand_calibration_protocol
from hydromodpy.calibration.runners import promotion
from hydromodpy.calibration.runners.recap import scored_samples
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.exceptions import CalibrationError, UncertaintyNotAvailableError
from hydromodpy.core.time.period_aggregation import period_edges
from tests.unit.calibration._factories import one_state
from tests.unit.calibration._factories_scoring import (
    SPIN_UP_RUN,
    WINDOW,
    FakeAdapter,
    adapter_result,
    boundary_output,
    network_output,
    objective_block,
    release_stack,
    seasonal_thresholds,
    stream_file_fixture,  # noqa: F401
    wire_stack,
)


def test_station_and_typed_values_refused() -> None:
    # Two answers to one question; picking one silently would hide it.
    with pytest.raises(ValueError, match="observes"):
        boundary_output(observes="J7branch", observed_values=[1.0, 2.0])


class _Point:
    def __init__(self, station_id: str, variable: str, frame: pd.DataFrame) -> None:
        self.station_id = station_id
        self.variable = variable
        self.data = frame


class _Loaded:
    def __init__(self, **families: object) -> None:
        for name, value in families.items():
            setattr(self, name, value)


class _Family:
    def __init__(self, points: list[_Point]) -> None:
        self.points = points


class _Ctx:
    def __init__(self, loaded_data: _Loaded) -> None:
        self.loaded_data = loaded_data


def _frame(dates: list[str], values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"datetime": pd.to_datetime(dates), "value": values})


def _ctx() -> _Ctx:
    return _Ctx(
        _Loaded(
            hydrometry=_Family(
                [_Point("J7branch", "discharge", _frame(["2000-01-01", "2000-01-02"], [1.0, 2.0]))]
            ),
            piezometry=_Family(
                [_Point("P1", "head", _frame(["2000-01-01", "2000-01-02"], [40.0, 41.0]))]
            ),
        )
    )


_OUTLET = boundary_output(observes="J7branch")
_TYPED = validate_calib_output(
    {"variable": "head", "support": "point", "x": 1.0, "y": 2.0, "observed_values": [1.0]}
)


def test_unnamed_station_left_out() -> None:
    assert observed_series_for_outputs({"typed": _TYPED}, _ctx()) == {}


def test_unloaded_station_refused() -> None:
    missing = boundary_output(observes="nowhere")

    with pytest.raises(ValueError, match="nowhere"):
        observed_series_for_outputs({"outlet": missing}, _ctx())


UNPAIRABLE = [
    pytest.param(
        pd.Series([1.0], index=pd.DatetimeIndex(["1990-01-01"])),
        pd.Series([1.1], index=pd.DatetimeIndex(["2020-01-01"])),
        id="nothing in common",
    ),
    pytest.param(
        pd.Series([1.0], index=pd.DatetimeIndex(["2000-01-01"])),
        pd.Series([1.1]),
        id="simulated without timestamps",
    ),
]


@pytest.mark.parametrize(("observed", "simulated"), UNPAIRABLE)
def test_unpairable_output_refused(observed, simulated) -> None:
    with pytest.raises(ValueError, match="outlet"):
        pair_outputs_with_observations(
            observed={"outlet": observed}, simulated={"outlet": simulated}
        )


def _record_outputs() -> dict[str, object]:
    return {
        "outlet": boundary_output(observes="J7branch"),
        "piezo": validate_calib_output(
            {"variable": "head", "support": "point", "x": 1.0, "y": 2.0, "observes": "P1"}
        ),
    }


def _record_blocks() -> list[object]:
    return [
        objective_block("hydrograph", "rmse", ["outlet"], weight=0.65),
        objective_block("piezometry", "rmse", ["piezo"], weight=0.35),
    ]


def _serve_extraction(
    monkeypatch,
    *,
    sim_outlet: list[float],
    sim_piezo: list[float],
) -> None:
    # A discharge is the mean of the period its stamp closes, so the outlet stamps close
    # the two days _ctx() records. A head is the state AT its stamp.
    times = pd.DatetimeIndex(["2000-01-02", "2000-01-03"])
    head_times = pd.DatetimeIndex(["2000-01-01", "2000-01-02"])
    monkeypatch.setattr(
        composite,
        "extract_outputs",
        lambda ctx, outputs, window=None: ExtractedOutputs(
            observables={
                "outlet": ObservableResult("outlet", np.asarray(sim_outlet), "m3/s", times),
                "piezo": ObservableResult("piezo", np.asarray(sim_piezo), "m", head_times),
            },
            values={"outlet": sim_outlet, "piezo": sim_piezo},
            series={
                "outlet": pd.Series(sim_outlet, index=times),
                "piezo": pd.Series(sim_piezo, index=head_times),
            },
            diagnostics={},
        ),
    )


# Outlet in m3/s and piezometer in m, weighted 0.65 and 0.35. RMSE is the constant error.
COSTS = [
    pytest.param([1.0, 2.0], [40.0, 41.0], 0.0, 0.0, 0.0, id="perfect match"),
    pytest.param([2.0, 3.0], [41.0, 42.0], 1.0, 1.0, 1.0, id="one unit of error"),
]


@pytest.mark.parametrize(("sim_outlet", "sim_piezo", "hydrograph", "piezometry", "total"), COSTS)
def test_weighted_cost(monkeypatch, sim_outlet, sim_piezo, hydrograph, piezometry, total) -> None:
    _serve_extraction(monkeypatch, sim_outlet=sim_outlet, sim_piezo=sim_piezo)
    metric_fn = build_metric_extractor(
        None, None, _ctx(), outputs=_record_outputs(), objective_blocks=_record_blocks()
    )

    cost, components = metric_fn(None)

    assert components["hydrograph.raw_cost"] == pytest.approx(hydrograph, abs=1e-12)
    assert components["piezometry.raw_cost"] == pytest.approx(piezometry, abs=1e-12)
    assert cost == pytest.approx(total, abs=1e-12)
    assert components["outlet.n_paired"] == 2.0
    assert components["piezo.n_paired"] == 2.0


def test_window_cuts_dated_series(monkeypatch) -> None:
    # The window opens on 2000-01-02: the outlet keeps the period of that
    # day (stamped 2000-01-03), the piezometer its state at that instant.
    _serve_extraction(monkeypatch, sim_outlet=[9.0, 2.0], sim_piezo=[40.0, 41.0])
    metric_fn = build_metric_extractor(
        None,
        None,
        _ctx(),
        outputs=_record_outputs(),
        objective_blocks=_record_blocks(),
        window=(pd.Timestamp("2000-01-02"), None),
    )

    total, components = metric_fn(None)

    # The first day, where the outlet is out by 8, is outside the window.
    assert components["outlet.n_paired"] == 1.0
    assert total == pytest.approx(0.0)


BLOCKS = [objective_block("network", "distance_gap", ["net"])]


def _two_bound_output(path):
    return network_output(path, model={"extent": {"visible_flow": "0 L/s"}})


def _components(monkeypatch, bench, output, window):
    stack = release_stack(bench, seasonal_thresholds(3, wet_first_year=True))
    ctx, _ = wire_stack(monkeypatch, bench, stack, SPIN_UP_RUN)
    metric_fn = build_metric_extractor(
        None, None, ctx, outputs={"net": output}, objective_blocks=BLOCKS, window=window
    )
    _, components = metric_fn(ctx)
    return components


def test_network_scored_on_window_years(monkeypatch, bench, stream_file) -> None:  # noqa: F811
    scored = _components(monkeypatch, bench, _two_bound_output(stream_file), WINDOW)
    assert scored["net.n_years_scored"] == 2.0
    assert scored["net.year_scored_y2000"] == 0.0
    assert scored["net.n_years_outside_window"] == 1.0


def test_missing_network_state_refused(
    monkeypatch,
    bench,  # noqa: F811
    stream_file,  # noqa: F811
) -> None:
    window = (pd.Timestamp("2001-01-01"), pd.Timestamp("2001-12-31"))
    with pytest.raises(ValueError) as caught:
        _components(monkeypatch, bench, one_state(stream_file, "2002-10-15"), window)
    message = str(caught.value)
    assert "window 2001-01-01 to 2001-12-31" in message
    assert "output 'net'" in message
    assert "2002-10" in message
    assert "2002-11-01" in message


FIRST = pd.Timestamp("2000-01-01")

# A monthly run stamps each period at the first day of the next month.
STAMPS = pd.date_range("2000-02-01", periods=36, freq="MS")
BOUNDARIES = tuple(period_edges(STAMPS, start=FIRST))

PINNED = {
    "discharge_nse_log_window": 0.17866174604070295,
    "discharge_followed_gauge": 0.7678948602751097,
    "head_rmse_two": 0.3228777051000766,
    "head_nse_three": 0.04659631074723684,
    "head_one_unplaced": 0.2619100296541183,
    "lake_reservoir": 19.937386769421664,
    "lake_nse_seasonal": 39.54011084560426,
}


def _daily_record(seed: float) -> pd.DataFrame:
    days = pd.date_range(FIRST, STAMPS[-1] - pd.Timedelta(1, unit="D"), freq="D")
    t = np.arange(days.size, dtype=float)
    values = 1.0 + 0.6 * np.cos(2.0 * np.pi * t / 365.25 + seed) + 0.2 * np.sin(t / 17.0)
    return pd.DataFrame({"datetime": days, "value": values})


def _state_record(seed: float) -> pd.DataFrame:
    months = np.arange(STAMPS.size, dtype=float)
    values = 50.0 + 2.0 * np.cos(2.0 * np.pi * months / 12.0 + seed) + 0.3 * np.sin(months)
    return pd.DataFrame({"datetime": STAMPS, "value": values})


def _simulated(seed: float, level: float = 1.0) -> np.ndarray:
    months = np.arange(STAMPS.size, dtype=float)
    return level * (1.0 + 0.5 * np.cos(2.0 * np.pi * months / 12.0 + seed)) + 0.1 * np.cos(
        3.0 * months + seed
    )


def _record_ctx(family: str, records: list[SimpleNamespace]) -> SimpleNamespace:
    loaded = {"hydrometry": None, "piezometry": None, "lake_levels": None, "runoff": None}
    loaded[family] = SimpleNamespace(points=records)
    return SimpleNamespace(
        setup=SimpleNamespace(
            time_grid=SimpleNamespace(boundaries=BOUNDARIES), geographic=None, cell_mesh=None
        ),
        loaded_data=SimpleNamespace(**loaded),
    )


def _serve(monkeypatch, answers: dict[str, np.ndarray]) -> None:
    """Answer every request the producers make from ``answers``, keyed by request id."""

    class _Adapter:
        def observables(self, ctx, requests, *, time_index=None):
            del ctx, time_index
            return {
                request.id: adapter_result(request.id, answers[request.id], "-", times=STAMPS)
                for request in requests
                if request.id in answers
            }

    monkeypatch.setattr(
        composite,
        "resolve_flow_adapter",
        lambda ctx: (
            _Adapter(),
            SimpleNamespace(
                run=SimpleNamespace(solver="modflow6"),
                solver_run=SimpleNamespace(solver_model=None),
            ),
        ),
    )


def _state(seed: float) -> np.ndarray:
    months = np.arange(STAMPS.size, dtype=float)
    return 50.0 + 1.8 * np.cos(2.0 * np.pi * months / 12.0 + seed) + 0.2 * np.cos(3.0 * months)


def _gauge(station: str, seed: float) -> SimpleNamespace:
    return SimpleNamespace(station_id=station, variable="discharge", data=_daily_record(seed))


def _piezometer(station: str, seed: float, cell=(3, 4)) -> SimpleNamespace:
    return SimpleNamespace(
        station_id=station, variable="head", data=_state_record(seed), cell_ij=cell
    )


def _lake(station: str, seed: float) -> SimpleNamespace:
    return SimpleNamespace(station_id=station, variable="lake_level", data=_state_record(seed))


def _pairs(components: dict[str, float]) -> dict[str, int]:
    """Return the pairs a session would keep, by output."""
    return {item.output: item.n for item in scored_samples(components, case_id="case")}


def _score(variable: str, objective: str, ctx, **kwargs) -> tuple[float, dict[str, float]]:
    metric_fn = build_metric_extractor(variable, objective, ctx, **kwargs)
    cost, components = metric_fn(ctx, objective=objective, variable=variable)
    return float(cost), dict(components)


def test_two_heads_average(monkeypatch) -> None:
    _serve(monkeypatch, {"PZ1": _state(0.1), "PZ2": _state(0.9)})
    ctx = _record_ctx("piezometry", [_piezometer("PZ1", 0.0), _piezometer("PZ2", 1.0)])

    cost, components = _score("head", "rmse", ctx)

    assert cost == PINNED["head_rmse_two"]
    assert cost == pytest.approx(
        0.5 * (components["rmse@PZ1.raw_cost"] + components["rmse@PZ2.raw_cost"]), rel=1e-15
    )


def test_three_heads_average(monkeypatch) -> None:
    _serve(
        monkeypatch,
        {
            "PZ1": _state(0.1),
            "PZ2": _state(0.9),
            "PZ3": _state(2.0),
        },
    )
    ctx = _record_ctx(
        "piezometry",
        [_piezometer("PZ1", 0.0), _piezometer("PZ2", 1.0), _piezometer("PZ3", 2.0)],
    )

    cost, _ = _score("head", "nse", ctx)

    assert cost == pytest.approx(PINNED["head_nse_three"], rel=1e-15, abs=0.0)


@pytest.mark.parametrize(
    ("metric", "pin"), [("reservoir", "lake_reservoir"), ("nse_seasonal", "lake_nse_seasonal")]
)
def test_lake_cost_pinned(monkeypatch, metric, pin) -> None:
    _serve(monkeypatch, {"lac0": _state(0.4)})
    ctx = _record_ctx("lake_levels", [_lake("lac0", 0.0)])

    cost, components = _score("lake_level", metric, ctx)

    assert np.isfinite(cost)
    assert cost == PINNED[pin]
    assert _pairs(components)["lake_level@lac0"] == 36


# A promoted run is scored on what its trial read: the derive step writes each station
# series through the readers of a trial. Fake series on one served solve, no MODFLOW.


def _table_rows(station, variable, times, values, source) -> pd.DataFrame:
    return pd.DataFrame(
        {"station_id": station, "variable": variable, "source": source}
        | {"time": times, "value": values}
    )


def _promoted(ctx, outputs=None, gauge=None) -> list[pd.DataFrame]:
    """The simulated rows the derive step writes in the table of the run."""
    written: list[pd.DataFrame] = []

    def write_timeseries_columns(sim_id, columns):
        assert sim_id == "sim-1"
        assert set(columns["unit"]) == {"-"}
        frame = pd.DataFrame(columns)
        for station, rows in frame.groupby("station_id", sort=False):
            for variable, chunk in rows.groupby("variable", sort=False):
                written.append(
                    _table_rows(
                        station, variable, chunk["time"], chunk["value"].to_numpy(), "simulated"
                    )
                )

    ctx.cfg = SimpleNamespace(
        calibration=outputs and SimpleNamespace(outputs=outputs),
        site=SimpleNamespace(gauge=gauge),
    )
    store = SimpleNamespace(sim_id="sim-1", write_timeseries_columns=write_timeseries_columns)
    promotion.write_station_series(ctx, store=store)
    return written


def test_output_written_at_station(monkeypatch) -> None:
    """A snapped gauge is scored off the cell of its record, and the run writes that series."""
    snapped = _simulated(0.6, 0.4)
    _serve(monkeypatch, {"catchment": _simulated(0.3)})
    result = adapter_result("up", snapped, "-", times=STAMPS)
    monkeypatch.setattr(
        composite,
        "extract_outputs",
        lambda ctx, outputs: ExtractedOutputs({"up": result}, {}, {}, {}),
    )
    ctx = _record_ctx("hydrometry", [_gauge("UP", 0.0)])

    (written,) = _promoted(ctx, {"up": boundary_output(observes="UP")})

    assert set(written["station_id"]) == {"UP"}
    np.testing.assert_array_equal(written["value"], snapped)


@pytest.mark.parametrize(
    ("outputs", "served", "stations", "said"),
    [
        (None, {"PZ1": _state(0.1)}, {"PZ1"}, "no simulated discharge"),
        (
            {"up": boundary_output(observes="NEVER")},
            {"PZ1": _state(0.1), "catchment": _simulated(0.3)},
            {"PZ1"},
            "no series for its output 'up'",
        ),
        (
            None,
            {"PZ1": _state(0.1), "catchment": _simulated(0.3)},
            {"PZ1"},
            "Gauge UP is not placed on the mesh",
        ),
    ],
    ids=["family not served", "output on unloaded station", "gauge not on mesh"],
)
def test_unreadable_logged_rest_written(
    monkeypatch, caplog, outputs, served, stations, said
) -> None:
    _serve(monkeypatch, served)
    monkeypatch.setattr(
        composite, "extract_outputs", lambda ctx, outputs: ExtractedOutputs({}, {}, {}, {})
    )
    ctx = _record_ctx("piezometry", [_piezometer("PZ1", 0.0)])
    ctx.loaded_data.hydrometry = SimpleNamespace(points=[_gauge("UP", 0.0)])

    with caplog.at_level("WARNING"):
        written = _promoted(ctx, outputs)

    assert {frame["station_id"].iloc[0] for frame in written} == stations
    assert said in caplog.text


def test_no_flow_run_writes_nothing(monkeypatch, caplog) -> None:
    monkeypatch.setattr(composite, "resolve_flow_adapter", lambda ctx: None)
    ctx = _record_ctx("piezometry", [_piezometer("PZ1", 0.0)])
    with caplog.at_level("WARNING"):
        assert _promoted(ctx) == []
    assert (
        "The run holds no solver model, as a run resumed at its derive step: "
        "no station series is written and its observed stations are left unscored."
    ) in caplog.text

    undated = adapter_result("PZ1", _state(0.1), "-")
    monkeypatch.setattr(
        promotion, "series_at_the_stations", lambda ctx, outputs: {("PZ1", "head"): undated}
    )
    assert _promoted(ctx) == []


_INDEX = pd.date_range("2000-01-01", periods=3, freq="D")


def _result(
    values, *, request_id: str = "_served", includes_runoff: bool = False, dated: bool = True
):
    """Serve the contract class itself: a producer answers with one of those."""
    array = np.asarray(values, dtype=float)
    return ObservableResult(
        request_id=request_id,
        values=array,
        units="m3 s-1",
        times=_INDEX[: array.size] if dated and array.ndim else None,
        includes_runoff=includes_runoff,
    )


def _observed(*station_ids: str) -> list[ObservedSeries]:
    return [
        ObservedSeries(
            station_id=sid,
            variable="discharge",
            series=pd.Series([1.0, 1.0, 1.0], index=_INDEX),
        )
        for sid in station_ids
    ]


def _station_ctx(station_cells: dict[str, tuple[int, int, int]]) -> SimpleNamespace:
    points = [
        SimpleNamespace(station_id=sid, cell_ij=(cell[1], cell[2], cell[0]))
        for sid, cell in station_cells.items()
    ]
    return SimpleNamespace(
        setup=SimpleNamespace(cell_mesh=None, domain=None, geographic=None),
        loaded_data=SimpleNamespace(
            hydrometry=SimpleNamespace(points=points),
            piezometry=None,
            runoff=None,
        ),
    )


_RUN_CTX = SimpleNamespace(
    run=SimpleNamespace(solver="fake_solver"), solver_run=SimpleNamespace(solver_model=None)
)


def _served_up(**flags):
    """A catchment series and the series and area of one station placed on a cell."""
    return {
        "catchment": _result([9.0, 9.0, 9.0], **flags),
        _cell_id("UP"): _result([2.0, 2.0, 2.0], **flags),
        _area_id("UP"): _result(1.0e6),
    }


def _by_station(adapter, cells, *stations, time_index=_INDEX):
    ctx = _station_ctx(cells)
    return _discharge_by_station(
        adapter, _RUN_CTX, ctx, _observed(*stations), time_index=time_index
    )


def test_station_cell_series():
    served = _served_up()
    adapter = FakeAdapter(served)

    out = _by_station(adapter, {"UP": (0, 1, 2)}, "UP")

    assert out["UP"].values == pytest.approx([2.0, 2.0, 2.0])
    pd.testing.assert_index_equal(pd.DatetimeIndex(out["UP"].times), _INDEX)


def test_undated_series_stays_undated():
    # The solver returned no time grid; nothing here invents one.
    served = _served_up(dated=False)

    out = _by_station(FakeAdapter(served), {"UP": (0, 1, 2)}, "UP", time_index=None)

    assert out["UP"].times is None
    assert out["UP"].values == pytest.approx([2.0, 2.0, 2.0])


def test_two_stations_two_series():
    served = {
        "catchment": _result([9.0, 9.0, 9.0]),
        _cell_id("UP"): _result([2.0, 2.0, 2.0]),
        _area_id("UP"): _result(1.0e6),
        _cell_id("DOWN"): _result([8.0, 8.0, 8.0]),
        _area_id("DOWN"): _result(9.0e6),
    }
    adapter = FakeAdapter(served)

    out = _by_station(adapter, {"UP": (0, 1, 2), "DOWN": (0, 3, 4)}, "UP", "DOWN")

    assert out["UP"].values == pytest.approx([2.0, 2.0, 2.0])
    assert out["DOWN"].values == pytest.approx([8.0, 8.0, 8.0])


def test_no_cell_gets_catchment():
    served = {"catchment": _result([9.0, 9.0, 9.0])}
    adapter = FakeAdapter(served)

    out = _by_station(adapter, {}, "NOWHERE")

    assert out["NOWHERE"].values == pytest.approx([9.0, 9.0, 9.0])
    assert adapter.requested[0] == ["catchment"]


class _Recorder(FakeAdapter):
    """A FakeAdapter that keeps every call whole: the solver run, the requests and the time index."""

    def __init__(self, served, **kwargs):
        super().__init__(served, **kwargs)
        self.calls = []

    def observables(self, solver_run, requests, *, time_index=None):
        asked = [(r.id, r.name, r.support, r.cell) for r in requests]
        self.calls.append((solver_run, asked, time_index))
        return super().observables(solver_run, requests, time_index=time_index)


def test_no_per_cell_backend_warns(caplog):
    served = {"catchment": _result([9.0, 9.0, 9.0])}
    adapter = _Recorder(served, fail_on_cell=True)

    with caplog.at_level("WARNING"):
        out = _by_station(adapter, {"UP": (0, 1, 2)}, "UP")

    assert out["UP"].values == pytest.approx([9.0, 9.0, 9.0])
    assert (
        "Per-cell discharge is unavailable on solver 'fake_solver' (this backend serves no "
        "per-cell discharge); every gauge is scored against the catchment outlet series, "
        "which is only right for the outlet one."
    ) in caplog.text
    (_, first, _), (solver_run, second, time_index) = adapter.calls
    assert len(first) == 3 and second == first[:1]
    assert solver_run is _RUN_CTX.solver_run and time_index is _INDEX


def test_silent_solver_names_catchment():
    class _Silent:
        def observables(self, *_args, **_kwargs):
            return {}

    with pytest.raises(
        NotImplementedError, match="returned no discharge observable for 'catchment'"
    ):
        _by_station(_Silent(), {}, "UP")


def test_heads_without_station_cells_refused():
    # The context loads no piezometry, so no piezometer sits on a cell.
    ctx = _station_ctx({})

    with pytest.raises(NotImplementedError, match="No station-to-cell mapping"):
        _head_by_station(FakeAdapter({}), _RUN_CTX, ctx, _observed("PZ1"), time_index=_INDEX)


def test_empty_catchment_refused():
    adapter = FakeAdapter({"catchment": _result([])})

    with pytest.raises(NotImplementedError, match="no discharge calibration series"):
        _by_station(adapter, {}, "NOWHERE")


def test_routed_reach_no_second_runoff(monkeypatch):
    # A reach already carries the runoff injected into the network.
    calls: list[float | None] = []

    def _spy(series, ctx, *, area_m2=None):
        del ctx
        calls.append(area_m2)
        return series

    monkeypatch.setattr("hydromodpy.calibration.metrics.composite.add_runoff_to_discharge", _spy)
    served = _served_up(includes_runoff=True)

    _by_station(FakeAdapter(served), {"UP": (0, 1, 2)}, "UP")

    # The catchment series is routed, so it is not given the runoff. The station
    # series is routed too and must not be either.
    assert calls == []


_CAPTURE_INDEX = pd.date_range("2020-01-01", periods=4, freq="D")

# The record is stamped at the day each simulated stamp closes, one day before.
_RECORD_INDEX = pd.date_range("2019-12-31", periods=4, freq="D")


def _outputs():
    return {"gauge": boundary_output(observes="NANCON")}


def _block(**extra):
    return CalibObjectiveBlockDecl.model_validate(
        {"name": "b", "metric": "rmse", "uses_outputs": ["gauge"], **extra}
    )


def _capture_ctx():
    frame = pd.DataFrame({"datetime": _RECORD_INDEX, "value": [1.0, 2.0, 3.0, 4.0]})
    record = SimpleNamespace(station_id="NANCON", variable="discharge", data=frame)
    return SimpleNamespace(
        setup=SimpleNamespace(time_grid=None),
        loaded_data=SimpleNamespace(hydrometry=SimpleNamespace(points=[record])),
    )


def _answer(values):
    return adapter_result(
        "gauge",
        np.asarray(values, dtype=float),
        "m3 s-1",
        times=_CAPTURE_INDEX[: len(values)],
    )


def _extracted(values, *, time="all"):
    """What `extract_outputs` returns, with the time selection applied."""
    result = select_observable_times(_answer(values), time)
    return ExtractedOutputs(
        observables={"gauge": result},
        values={"gauge": [float(v) for v in result.values]},
        series={"gauge": pd.Series(result.values, index=result.times)},
        diagnostics={},
    )


def test_captured_vectors_match_pairing(monkeypatch) -> None:
    # The reference is the reader this replaced, not the one that replaced it.
    simulated = [1.5, 2.5, 3.5, 4.5]
    extracted = _extracted(simulated)
    monkeypatch.setattr(composite, "extract_outputs", lambda ctx, outputs, window=None: extracted)
    capture_fn, captured = build_paired_vector_capture(
        _outputs(), ctx=_capture_ctx(), objective_blocks=[_block()]
    )

    capture_fn(None)

    # What HEAD did: load the records itself, and pair them on the dated
    # series `extract_outputs` had already built.
    former = pair_outputs_with_observations(
        observed=observed_series_for_outputs(_outputs(), _capture_ctx()),
        simulated={"gauge": extracted.series["gauge"]},
        window=None,
        min_samples=1,
    )

    assert captured["order"] == ("gauge",)
    assert list(captured["simulated"]) == pytest.approx(former.simulated["gauge"])
    assert list(captured["observed"]) == pytest.approx(former.observed["gauge"])


def test_selected_timestep_pairing(monkeypatch) -> None:
    # `pair` re-selects the times `extract_outputs` had already selected.
    outputs = {"gauge": boundary_output(observes="NANCON", time="last")}
    extracted = _extracted([1.5, 2.5, 3.5, 4.5], time="last")
    monkeypatch.setattr(composite, "extract_outputs", lambda ctx, outputs_, window=None: extracted)
    capture_fn, captured = build_paired_vector_capture(
        outputs, ctx=_capture_ctx(), objective_blocks=[_block()]
    )

    # The selection left one stamp, 2020-01-04. The run's time grid says its
    # period is the day 2020-01-03, which the record measured at 4.0.
    grid = SimpleNamespace(boundaries=tuple(pd.date_range("2019-12-31", periods=5, freq="D")))
    capture_fn(SimpleNamespace(setup=SimpleNamespace(time_grid=grid)))

    former = pair_outputs_with_observations(
        observed=observed_series_for_outputs(outputs, _capture_ctx()),
        simulated={"gauge": extracted.series["gauge"]},
        window=None,
        min_samples=1,
    )
    assert list(captured["simulated"]) == pytest.approx(former.simulated["gauge"])
    assert list(captured["observed"]) == pytest.approx([4.0])


def test_window_cuts_residuals(monkeypatch) -> None:
    monkeypatch.setattr(
        composite,
        "extract_outputs",
        lambda ctx, outputs, window=None: _extracted([1.5, 2.5, 3.5, 4.5]),
    )
    capture_fn, captured = build_paired_vector_capture(
        _outputs(),
        ctx=_capture_ctx(),
        objective_blocks=[_block()],
        # The days from 2020-01-02 on: the periods the last two stamps close.
        window=(pd.Timestamp("2020-01-02"), None),
    )

    capture_fn(None)

    assert list(captured["observed"]) == pytest.approx([3.0, 4.0])


def test_short_overlap_refused(monkeypatch) -> None:
    monkeypatch.setattr(
        composite,
        "extract_outputs",
        lambda ctx, outputs, window=None: _extracted([1.5, 2.5]),
    )
    capture_fn, _ = build_paired_vector_capture(
        _outputs(), ctx=_capture_ctx(), objective_blocks=[_block()], min_samples=3
    )

    with pytest.raises(ValueError, match="min_samples"):
        capture_fn(None)


def test_unobserved_output_cannot_pair() -> None:
    typed = {"typed": boundary_output(observed_values=[1.0, 2.0])}
    block = objective_block("b", "rmse", ["typed"])
    scorer = ObservableScorer(typed, [block])

    with pytest.raises(ValueError, match="no residual to align"):
        scorer.pair({"typed": _answer([1.0, 2.0])})


def test_runoff_flag_defaults_false():
    result = adapter_result("x", np.zeros(3), "m3/s")
    assert result.includes_runoff is False


def test_runoff_addition_guarded():
    # The guard lives in a branch a unit test cannot reach without a solver run,
    # so assert the source: a refactor that drops it would double-count the
    # runoff on every routed SFR calibration, inflating discharge by ~25 %.

    source = inspect.getsource(composite)
    # Assert the guard, not the variable name a refactor is free to change.
    assert "add_runoff_to_discharge(" in source
    guard = next(
        line for line in source.splitlines() if "includes_runoff" in line and "if " in line
    )
    assert "not " in guard, (
        "The runoff must be added ONLY when the observable does not already hold it."
    )
    added = source.index("add_runoff_to_discharge(", source.index(guard))
    between = source[source.index(guard) : added]
    assert between.count("\n") <= 2, (
        "The runoff addition must sit directly under its includes_runoff guard."
    )


class _Raises:
    calls = 0

    def observables(self, *_args, **_kwargs):
        self.calls += 1
        raise RuntimeError("boom")


def test_outlet_error_raised() -> None:
    adapter = _Raises()
    with pytest.raises(RuntimeError, match="boom"):
        _by_station(adapter, {}, "UP")
    assert adapter.calls == 1


@pytest.mark.parametrize(
    ("ctx", "producer", "error", "message"),
    [
        (_Ctx(_Loaded()), None, ValueError, "No observations available"),
        (_ctx(), RuntimeError("boom"), RuntimeError, "boom"),
    ],
)
def test_variable_route_errors(monkeypatch, caplog, ctx, producer, error, message) -> None:
    run_ctx = SimpleNamespace(run=SimpleNamespace(solver="s"), solver_run=None)
    monkeypatch.setattr(composite, "resolve_flow_adapter", lambda _ctx: (object(), run_ctx))

    def failing(*_args, **_kwargs):
        raise producer

    monkeypatch.setitem(composite.PRODUCERS, "discharge", failing)
    metric_fn = build_metric_extractor("discharge", "rmse", ctx)

    with caplog.at_level("ERROR"), pytest.raises(error, match=message):
        metric_fn(ctx, objective="rmse", variable="discharge")

    assert ("Metric extractor failed" in caplog.text) is (producer is not None)


def test_no_solver_is_silent(monkeypatch, caplog) -> None:
    monkeypatch.setattr(composite, "resolve_flow_adapter", lambda _ctx: None)

    with caplog.at_level("WARNING"):
        assert composite.series_at_the_stations(_Ctx(_Loaded()), {}) == {}

    assert caplog.text == ""


def test_producers_get_run_and_grid(
    monkeypatch,
) -> None:
    ctx, pair = object(), ("adapter", "run_ctx")
    seen = []
    produced = adapter_result("UP", [1.0], "-")
    replaced = adapter_result("up", [2.0], "-")
    output = boundary_output(observes="UP")

    def producer(*args, time_index):
        seen.append((args, time_index))
        return {"UP": produced}

    def load(c, family):
        assert c is ctx
        return [SimpleNamespace(station_id="UP", variable="discharge")] * (family == "discharge")

    def extract(c, outputs):
        assert c is ctx and outputs == {"up": output}
        return ExtractedOutputs({"up": replaced}, {}, {}, {})

    monkeypatch.setattr(composite, "PRODUCERS", {"discharge": producer, "head": producer})
    monkeypatch.setattr(composite, "load_observed", load)
    monkeypatch.setattr(composite, "resolve_flow_adapter", lambda c: pair if c is ctx else None)
    monkeypatch.setattr(composite, "resolve_time_index", lambda c: "T" if c is ctx else None)
    monkeypatch.setattr(composite, "extract_outputs", extract)

    assert composite.series_at_the_stations(ctx, {}) == {("UP", "discharge"): produced}
    assert composite.series_at_the_stations(ctx, {"up": output}) == {("UP", "discharge"): replaced}
    # Only the family with a record is asked, once per call, with the run, the trial and the grid.
    record = load(ctx, "discharge")
    assert seen == [(("adapter", "run_ctx", ctx, record), "T")] * 2


def test_covariance_needs_a_station() -> None:
    with pytest.raises(ValueError, match="no calibration output names a station"):
        build_paired_vector_capture({}, ctx=_Ctx(_Loaded()))
