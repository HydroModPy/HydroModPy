"""Tests of `metrics.composite`."""

from __future__ import annotations

import inspect
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibPhaseDecl,
    CalibrationConfig,
    validate_calib_output,
    window_bounds,
)
from hydromodpy.calibration.metrics import composite
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.composite import (
    _area_id,
    _cell_id,
    _discharge_by_station,
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
from hydromodpy.calibration.protocols import expand_calibration_protocol
from hydromodpy.calibration.runners import promotion
from hydromodpy.calibration.runners.recap import scored_samples
from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.core.exceptions import CalibrationError, UncertaintyNotAvailableError
from hydromodpy.core.time.period_aggregation import period_edges
from hydromodpy.results.metric_rule import DateWindow, MetricRule
from hydromodpy.results.score import score_timeseries
from hydromodpy.solver.base.observables import series_observable
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

# From test_a_block_can_name_an_observation.py
# A weighted block had no way to score a real observed record.
#
# Two routes to a cost coexisted and excluded each other. ``variable`` +
# ``objective`` aligns genuine chronicles on their dates, but averages the
# stations it scores and cannot weight them. ``outputs`` +
# ``objective_blocks`` weights, normalizes and persists the per-block
# diagnostics, but read only ``observed_values``: a vector typed into the TOML
# by hand, positional, with no dates. So "the outlet carries 65 % of the cost,
# the piezometer 25 %, the lake 10 %" was expressible only against numbers
# somebody had transcribed.
#
# ``observes`` is the bridge: the output names a station, the loaded record is
# aligned on the simulated timestamps, and the block scores that.


class TestTheDeclaration:
    def test_an_output_may_name_a_station(self) -> None:
        output = boundary_output(observes="J7branch")

        assert output.observes == "J7branch"

    def test_naming_a_station_and_typing_the_values_is_refused(self) -> None:
        """Two answers to one question; picking one silently would hide it."""
        with pytest.raises(ValueError, match="observes"):
            boundary_output(observes="J7branch", observed_values=[1.0, 2.0])

    def test_a_network_output_cannot_observe_a_station(self) -> None:
        """Its criterion balances two simulated quantities; there is no record to fit."""
        with pytest.raises(ValueError):
            validate_calib_output(
                {
                    "support": "network",
                    "map": {"complete": "streams.gpkg"},
                    "observes": "J7branch",
                }
            )

    def test_a_config_declaring_it_loads(self) -> None:
        cfg = CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
                "outputs": {
                    "outlet": {
                        "variable": "discharge",
                        "support": "boundary",
                        "boundary_id": "outlet",
                        "observes": "J7branch",
                    }
                },
                "objective_blocks": [
                    {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["outlet"]}
                ],
            }
        )

        assert cfg.outputs["outlet"].observes == "J7branch"


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
_PIEZO = validate_calib_output(
    {"variable": "head", "support": "point", "x": 1.0, "y": 2.0, "observes": "P1"}
)
_TYPED = validate_calib_output(
    {"variable": "head", "support": "point", "x": 1.0, "y": 2.0, "observed_values": [1.0]}
)


class TestLoadingTheRecords:
    def test_it_reads_the_family_the_variable_names(self) -> None:
        loaded = observed_series_for_outputs({"outlet": _OUTLET, "piezo": _PIEZO}, _ctx())

        assert set(loaded) == {"outlet", "piezo"}
        assert list(loaded["outlet"]) == [1.0, 2.0]
        assert list(loaded["piezo"]) == [40.0, 41.0]

    def test_an_output_that_names_nothing_is_left_out(self) -> None:
        assert observed_series_for_outputs({"typed": _TYPED}, _ctx()) == {}

    def test_a_station_the_project_never_loaded_is_named_in_the_refusal(self) -> None:
        missing = boundary_output(observes="nowhere")

        with pytest.raises(ValueError, match="nowhere"):
            observed_series_for_outputs({"outlet": missing}, _ctx())


class TestPairing:
    def test_the_record_is_aligned_on_the_simulated_timestamps(self) -> None:
        # A simulated stamp closes its period and a daily record is stamped at
        # the day it measures, so each record day pairs with the next stamp.
        times = pd.DatetimeIndex(["2000-01-01", "2000-01-02"])
        paired = pair_outputs_with_observations(
            observed={"outlet": pd.Series([1.0, 2.0], index=times)},
            simulated={
                "outlet": pd.Series(
                    [1.1, 2.2], index=pd.DatetimeIndex(["2000-01-02", "2000-01-03"])
                )
            },
        )

        assert paired.observed["outlet"] == [1.0, 2.0]
        assert paired.simulated["outlet"] == [1.1, 2.2]

    def test_a_simulated_step_the_record_does_not_cover_is_dropped_from_both(self) -> None:
        """The shared aligner matches within one simulated step; beyond it, nothing."""
        paired = pair_outputs_with_observations(
            observed={
                "outlet": pd.Series(
                    [1.0, 2.0, 3.0],
                    index=pd.DatetimeIndex(["2000-01-01", "2000-01-02", "2000-01-03"]),
                )
            },
            simulated={
                "outlet": pd.Series(
                    [1.1, 2.2, 3.3, 4.4, 5.5],
                    index=pd.date_range("2000-01-01", periods=5, freq="D"),
                )
            },
        )

        # 2000-01-01 closes a day before the record, 2000-01-05 closes a day
        # after it: neither carries a pair. The three stamps in between close
        # the three record days.
        assert paired.n_paired["outlet"] == 3
        assert paired.simulated["outlet"] == [2.2, 3.3, 4.4]

    def test_a_window_keeps_only_the_dates_inside_it(self) -> None:
        # The record is stamped one day before the stamps that close its days.
        times = pd.DatetimeIndex(["2000-01-01", "2000-01-02", "2000-01-03"])
        paired = pair_outputs_with_observations(
            observed={
                "outlet": pd.Series(
                    [0.0, 2.0, 3.0],
                    index=pd.DatetimeIndex(["1999-12-31", "2000-01-01", "2000-01-02"]),
                )
            },
            simulated={"outlet": pd.Series([1.1, 2.2, 3.3], index=times)},
            # The days of the last two records, which the last two stamps close.
            window=(pd.Timestamp("2000-01-01"), pd.Timestamp("2000-01-02")),
        )

        assert paired.observed["outlet"] == [2.0, 3.0]

    def test_a_pair_with_nothing_in_common_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="outlet"):
            pair_outputs_with_observations(
                observed={"outlet": pd.Series([1.0], index=pd.DatetimeIndex(["1990-01-01"]))},
                simulated={"outlet": pd.Series([1.1], index=pd.DatetimeIndex(["2020-01-01"]))},
            )

    def test_a_simulated_output_with_no_timestamps_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="outlet"):
            pair_outputs_with_observations(
                observed={"outlet": pd.Series([1.0], index=pd.DatetimeIndex(["2000-01-01"]))},
                simulated={"outlet": pd.Series([1.1])},
            )


class TestTheExtractor:
    """The weighted route, end to end, against records rather than typed vectors."""

    @staticmethod
    def _outputs() -> dict[str, object]:
        return {
            "outlet": boundary_output(observes="J7branch"),
            "piezo": validate_calib_output(
                {"variable": "head", "support": "point", "x": 1.0, "y": 2.0, "observes": "P1"}
            ),
        }

    @staticmethod
    def _blocks() -> list[object]:
        return [
            objective_block("hydrograph", "rmse", ["outlet"], weight=0.65),
            objective_block("piezometry", "rmse", ["piezo"], weight=0.35),
        ]

    @staticmethod
    def _extracted(
        monkeypatch,
        *,
        sim_outlet: list[float],
        sim_piezo: list[float],
    ) -> None:

        # A discharge is the mean of the period its stamp closes, so the outlet
        # stamps close the two days _ctx() records. A head is the state AT its
        # stamp, so the piezometer is stamped at the record instants.
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

    def test_a_perfect_match_costs_nothing(self, monkeypatch) -> None:
        self._extracted(monkeypatch, sim_outlet=[1.0, 2.0], sim_piezo=[40.0, 41.0])
        metric_fn = build_metric_extractor(
            None, None, _ctx(), outputs=self._outputs(), objective_blocks=self._blocks()
        )

        total, components = metric_fn(None)

        assert total == pytest.approx(0.0)
        assert components["outlet.n_paired"] == 2.0
        assert components["piezo.n_paired"] == 2.0

    def test_the_weights_decide_how_much_each_target_carries(self, monkeypatch) -> None:
        """One meter of error on the piezometer, one m3/s on the outlet."""

        self._extracted(monkeypatch, sim_outlet=[2.0, 3.0], sim_piezo=[41.0, 42.0])
        metric_fn = build_metric_extractor(
            None, None, _ctx(), outputs=self._outputs(), objective_blocks=self._blocks()
        )

        total, components = metric_fn(None)

        assert components["hydrograph.raw_cost"] == pytest.approx(1.0)
        assert components["piezometry.raw_cost"] == pytest.approx(1.0)
        assert total == pytest.approx(1.0)

    def test_a_window_now_applies_because_the_series_carry_dates(self, monkeypatch) -> None:
        # The window opens on 2000-01-02: the outlet keeps the period of that
        # day (stamped 2000-01-03), the piezometer its state at that instant.
        self._extracted(monkeypatch, sim_outlet=[9.0, 2.0], sim_piezo=[40.0, 41.0])
        metric_fn = build_metric_extractor(
            None,
            None,
            _ctx(),
            outputs=self._outputs(),
            objective_blocks=self._blocks(),
            window=(pd.Timestamp("2000-01-02"), None),
        )

        total, components = metric_fn(None)

        # The first day, where the outlet is out by 8, is outside the window.
        assert components["outlet.n_paired"] == 1.0
        assert total == pytest.approx(0.0)

    def test_a_window_is_still_refused_when_an_output_has_no_dates(self) -> None:

        outputs = self._outputs()
        outputs["typed"] = _TYPED
        blocks = [
            *self._blocks(),
            objective_block("typed", "rmse", ["typed"]),
        ]

        with pytest.raises(ValueError, match="typed"):
            build_metric_extractor(
                None,
                None,
                _ctx(),
                outputs=outputs,
                objective_blocks=blocks,
                window=(pd.Timestamp("2000-01-03"), None),
            )


# From test_a_calibration_run_windows_its_two_bound_network.py
# A calibration run hands its scoring window to a two-bound network output.
#
# The metric function a calibration builds is the route every trial takes. It
# must pass the phase's window to the extraction, so the spin-up year leaves
# the score, and must not refuse the window on a network output scored by
# calendar year. A network output in one state is dated at the stamp of the
# state it reads: a window holding that stamp scores it, one that does not is
# refused at the first trial, naming both.


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


def test_the_run_scores_only_the_years_of_its_window(monkeypatch, bench, stream_file) -> None:  # noqa: F811
    scored = _components(monkeypatch, bench, _two_bound_output(stream_file), WINDOW)
    assert scored["net.n_years_scored"] == 2.0
    assert scored["net.year_scored_y2000"] == 0.0
    assert scored["net.n_years_outside_window"] == 1.0


def test_without_a_window_the_run_scores_every_year(monkeypatch, bench, stream_file) -> None:  # noqa: F811
    scored = _components(monkeypatch, bench, _two_bound_output(stream_file), None)
    assert scored["net.n_years_scored"] == 3.0
    assert scored["net.year_scored_y2000"] == 1.0


def test_a_window_holding_the_state_of_a_network_in_one_state_is_scored(
    monkeypatch,
    bench,  # noqa: F811
    stream_file,  # noqa: F811
) -> None:
    """The state read is dated at its stamp, 2003-01-01 for December 2002."""
    windowed = _components(
        monkeypatch, bench, one_state(stream_file), (pd.Timestamp("2001-01-01"), None)
    )
    plain = _components(monkeypatch, bench, one_state(stream_file), None)
    assert windowed["net.J_signed"] == plain["net.J_signed"]


def test_a_window_missing_the_state_of_a_network_in_one_state_is_refused(
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


# From test_a_single_metric_calibration_is_scored_by_its_implicit_blocks.py
# ``variable`` + ``objective`` is scored by the block route, at the same cost.
#
# Decision m10 of the audit of 2026-10-20: the one-line form becomes, once the
# records are loaded, one implicit output and one implicit block per scored
# station, and the block route scores them. ``PINNED`` holds the costs the old
# single-metric route (``StationScorer`` and ``scalar.score``) returned on these
# exact series at 4ca07e106, so a cost that moves is caught here. One station
# reproduces the old cost to the bit; several are averaged by the block weights,
# which may round differently in the last place.
#
# What the old route did not publish is now there: the pairs each cost was
# scored on, which ``scored`` of ``session.json`` is read from.


FIRST = pd.Timestamp("2000-01-01")

# A monthly run stamps each period at the first day of the next month.
STAMPS = pd.date_range("2000-02-01", periods=36, freq="MS")
BOUNDARIES = tuple(period_edges(STAMPS, start=FIRST))
WINDOW__single_metric = (pd.Timestamp("2001-01-01"), None)

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


def _ctx__single_metric(family: str, records: list[SimpleNamespace]) -> SimpleNamespace:
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


def test_a_gauge_on_nse_log_and_a_window_costs_what_it_cost(monkeypatch) -> None:
    _serve(monkeypatch, {"catchment": _simulated(0.3)})
    ctx = _ctx__single_metric("hydrometry", [_gauge("NANCON", 0.0)])

    cost, components = _score("discharge", "nse_log", ctx, window=WINDOW__single_metric)

    assert cost == PINNED["discharge_nse_log_window"]
    assert components["nse_log@NANCON.raw_cost"] == cost
    assert _pairs(components)["discharge@NANCON"] == 24


def test_the_followed_gauge_alone_is_scored(monkeypatch) -> None:
    _serve(monkeypatch, {"catchment": _simulated(0.3)})
    ctx = _ctx__single_metric("hydrometry", [_gauge("OUTLET", 0.0), _gauge("UP", 1.0)])

    cost, components = _score("discharge", "nse", ctx, gauge="UP")

    assert cost == PINNED["discharge_followed_gauge"]
    assert set(_pairs(components)) == {"discharge@UP"}


def test_two_heads_average_as_they_did(monkeypatch) -> None:
    _serve(monkeypatch, {"PZ1": _state(0.1), "PZ2": _state(0.9)})
    ctx = _ctx__single_metric("piezometry", [_piezometer("PZ1", 0.0), _piezometer("PZ2", 1.0)])

    cost, components = _score("head", "rmse", ctx)

    assert cost == PINNED["head_rmse_two"]
    assert cost == pytest.approx(
        0.5 * (components["rmse@PZ1.raw_cost"] + components["rmse@PZ2.raw_cost"]), rel=1e-15
    )


def test_three_heads_average_to_the_last_place(monkeypatch) -> None:
    _serve(
        monkeypatch,
        {
            "PZ1": _state(0.1),
            "PZ2": _state(0.9),
            "PZ3": _state(2.0),
        },
    )
    ctx = _ctx__single_metric(
        "piezometry",
        [_piezometer("PZ1", 0.0), _piezometer("PZ2", 1.0), _piezometer("PZ3", 2.0)],
    )

    cost, _ = _score("head", "nse", ctx)

    assert cost == pytest.approx(PINNED["head_nse_three"], rel=1e-15, abs=0.0)


def test_a_piezometer_the_mesh_cannot_place_is_left_out(monkeypatch) -> None:
    _serve(monkeypatch, {"PZ1": _state(0.1)})
    ctx = _ctx__single_metric(
        "piezometry", [_piezometer("PZ1", 0.0), _piezometer("NOWHERE", 1.0, cell=None)]
    )

    cost, components = _score("head", "mae", ctx)

    assert cost == PINNED["head_one_unplaced"]
    assert set(_pairs(components)) == {"head@PZ1"}


@pytest.mark.parametrize(
    ("metric", "pin"), [("reservoir", "lake_reservoir"), ("nse_seasonal", "lake_nse_seasonal")]
)
def test_a_lake_on_a_seasonal_kernel_costs_what_it_cost(monkeypatch, metric, pin) -> None:
    _serve(monkeypatch, {"lac0": _state(0.4)})
    ctx = _ctx__single_metric("lake_levels", [_lake("lac0", 0.0)])

    cost, components = _score("lake_level", metric, ctx)

    assert np.isfinite(cost)
    assert cost == PINNED[pin]
    assert _pairs(components)["lake_level@lac0"] == 36


# The run promoted from a trial is scored on what the trial read.
#
# The derive step writes each station's series through the readers of a trial, and
# the table goes to the score of the run. Fake series on one served solve, no MODFLOW.


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


def _runoff_points() -> SimpleNamespace:
    days = pd.date_range(FIRST, STAMPS[-1], freq="D")
    values = 0.8 + 0.3 * np.sin(np.arange(days.size) / 11.0)
    record = pd.DataFrame({"datetime": days, "value": values})
    return SimpleNamespace(points=[SimpleNamespace(data=record)])


@pytest.mark.parametrize(
    ("variable", "family", "records", "answers", "station", "unscored"),
    [
        (
            "discharge",
            "hydrometry",
            [_gauge("OUTLET", 0.0), SimpleNamespace(**vars(_gauge("UP", 1.0)), cell_ij=(3, 4))],
            {"catchment": _simulated(0.3), "_cell:UP": _simulated(0.6, 0.4), "_area:UP": [2.0e6]},
            "UP",
            ["OUTLET"],
        ),
        (
            "head",
            "piezometry",
            [_piezometer("PZ1", 0.0), _piezometer("PZ2", 1.0)],
            {"PZ1": _state(0.1), "PZ2": _state(0.9)},
            "PZ2",
            [],
        ),
        ("lake_level", "lake_levels", [_lake("lac0", 0.0)], {"lac0": _state(0.4)}, "lac0", []),
    ],
    ids=["nested_gauge_with_its_runoff", "second_piezometer", "lake"],
)
def test_one_solve_costs_what_its_promoted_run_scores(
    monkeypatch, variable, family, records, answers, station, unscored
) -> None:
    _serve(monkeypatch, answers)
    ctx = _ctx__single_metric(family, records)
    ctx.loaded_data.runoff = _runoff_points()
    ctx.setup.geographic = SimpleNamespace(catch_area=3.0)
    window = (pd.Timestamp("2001-01-01"), pd.Timestamp("2002-12-31"))

    _, components = _score(variable, "nse", ctx, gauge=station, window=window)

    rows = _promoted(ctx) + [
        _table_rows(
            rec.station_id, rec.variable, rec.data["datetime"], rec.data["value"], "observed"
        )
        for rec in records
    ]
    rule = MetricRule(
        station=station, window=DateWindow(start=window[0].date(), end=window[1].date())
    )
    scores = score_timeseries(pd.concat(rows), rule=rule, period_start=FIRST)
    assert scores.score.n_samples == 24
    # A gauge the mesh does not place is left unscored, not read as the outlet.
    assert [item.station for item in scores.unscored] == unscored
    assert 1.0 - components[f"nse@{station}.raw_cost"] == scores.score.value


def test_an_output_that_observes_a_station_says_where_it_is_read(monkeypatch) -> None:
    """A snapped gauge is scored off the cell of its record, and the run writes that series."""
    snapped = _simulated(0.6, 0.4)
    _serve(monkeypatch, {"catchment": _simulated(0.3)})
    result = adapter_result("up", snapped, "-", times=STAMPS)
    monkeypatch.setattr(
        composite,
        "extract_outputs",
        lambda ctx, outputs: ExtractedOutputs({"up": result}, {}, {}, {}),
    )
    ctx = _ctx__single_metric("hydrometry", [_gauge("UP", 0.0)])

    (written,) = _promoted(ctx, {"up": boundary_output(observes="UP")})

    assert set(written["station_id"]) == {"UP"}
    np.testing.assert_array_equal(written["value"], snapped)


def test_the_gauge_of_the_site_takes_the_outlet_series_under_its_name(monkeypatch) -> None:
    outlet = _simulated(0.3)
    _serve(monkeypatch, {"PZ1": _state(0.1), "catchment": outlet})
    ctx = _ctx__single_metric("piezometry", [_piezometer("PZ1", 0.0)])
    ctx.loaded_data.hydrometry = SimpleNamespace(points=[_gauge("UP", 0.0)])

    written = pd.concat(_promoted(ctx, gauge="UP"))

    assert set(written["station_id"]) == {"PZ1", "UP"}
    up = written[written["station_id"] == "UP"]
    np.testing.assert_array_equal(up["value"], outlet)


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
    ids=[
        "a_family_the_backend_does_not_serve",
        "an_output_on_a_station_never_loaded",
        "a_gauge_the_mesh_does_not_place",
    ],
)
def test_what_cannot_be_read_is_logged_and_the_rest_is_written(
    monkeypatch, caplog, outputs, served, stations, said
) -> None:
    _serve(monkeypatch, served)
    monkeypatch.setattr(
        composite, "extract_outputs", lambda ctx, outputs: ExtractedOutputs({}, {}, {}, {})
    )
    ctx = _ctx__single_metric("piezometry", [_piezometer("PZ1", 0.0)])
    ctx.loaded_data.hydrometry = SimpleNamespace(points=[_gauge("UP", 0.0)])

    with caplog.at_level("WARNING"):
        written = _promoted(ctx, outputs)

    assert {frame["station_id"].iloc[0] for frame in written} == stations
    assert said in caplog.text


def test_no_flow_run_or_an_undated_answer_writes_nothing(monkeypatch, caplog) -> None:
    monkeypatch.setattr(composite, "resolve_flow_adapter", lambda ctx: None)
    ctx = _ctx__single_metric("piezometry", [_piezometer("PZ1", 0.0)])
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


# From test_discharge_per_station_series.py
# Each gauge is scored against the simulated discharge AT ITS OWN cell.
#
# The whole-catchment series answers for the outlet gauge alone. A station upstream
# closes a smaller catchment, so it gets its own routed series and its own upstream
# area for the runoff.


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


def _ctx__discharge_per(station_cells: dict[str, tuple[int, int, int]]) -> SimpleNamespace:
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
    ctx = _ctx__discharge_per(cells)
    return _discharge_by_station(
        adapter, _RUN_CTX, ctx, _observed(*stations), time_index=time_index
    )


def test_a_station_with_a_cell_gets_its_own_routed_series():
    served = _served_up()
    adapter = FakeAdapter(served)

    out = _by_station(adapter, {"UP": (0, 1, 2)}, "UP")

    assert out["UP"].values == pytest.approx([2.0, 2.0, 2.0])
    pd.testing.assert_index_equal(pd.DatetimeIndex(out["UP"].times), _INDEX)


def test_the_corrected_series_keeps_the_dates_it_was_read_on():
    """A dropped time axis turns every observation into a 1970 timestamp."""
    served = _served_up()

    out = _by_station(FakeAdapter(served), {"UP": (0, 1, 2)}, "UP")

    assert out["UP"].times is not None
    assert out["UP"].units == "m3 s-1"
    assert out["UP"].request_id == "UP"
    assert out["UP"].includes_runoff is True


def test_an_undated_series_is_carried_back_undated():
    """The solver returned no time grid; nothing here invents one."""
    served = _served_up(dated=False)

    out = _by_station(FakeAdapter(served), {"UP": (0, 1, 2)}, "UP", time_index=None)

    assert out["UP"].times is None
    assert out["UP"].values == pytest.approx([2.0, 2.0, 2.0])


def test_two_stations_get_two_different_series():
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


def test_an_upstream_area_is_requested_for_every_placed_station():
    """The runoff a gauge sees must be the runoff of the area it drains."""
    served = _served_up()
    adapter = FakeAdapter(served)

    _by_station(adapter, {"UP": (0, 1, 2)}, "UP")

    assert _area_id("UP") in adapter.requested[0]


def test_a_station_without_a_cell_falls_back_to_the_catchment_series():
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


def test_the_solver_is_asked_for_the_catchment_and_for_the_cell_and_area_of_a_gauge():
    adapter = _Recorder(_served_up())

    _by_station(adapter, {"UP": (0, 1, 2)}, "UP")

    ((solver_run, asked, time_index),) = adapter.calls
    assert solver_run is _RUN_CTX.solver_run and time_index is _INDEX
    cell = asked[1][3]
    assert asked == [
        ("catchment", "discharge", "domain", None),
        (_cell_id("UP"), "discharge", "cell", cell),
        (_area_id("UP"), "upstream_area", "cell", cell),
    ]
    assert cell is not None


def test_a_backend_without_per_cell_discharge_falls_back_and_warns(caplog):
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


def test_a_catchment_the_solver_does_not_answer_is_named():
    class _Silent:
        def observables(self, *_args, **_kwargs):
            return {}

    with pytest.raises(
        NotImplementedError, match="returned no discharge observable for 'catchment'"
    ):
        _by_station(_Silent(), {}, "UP")


def test_the_runoff_is_added_by_the_area_each_series_drains(monkeypatch):
    added, reported = [], []

    def _add(series, ctx, *, area_m2=None):
        added.append((series.name, ctx, area_m2))
        return series

    def _area(run_ctx, trial_ctx):
        reported.append(("sums", run_ctx, trial_ctx))
        return 5.0e6

    monkeypatch.setattr(composite, "add_runoff_to_discharge", _add)
    monkeypatch.setattr(composite, "catchment_area_the_discharge_sums", _area)
    monkeypatch.setattr(
        composite,
        "report_the_area_a_gauge_drains",
        lambda station, ctx, *, area_m2: reported.append((station, ctx, area_m2)),
    )
    served = _served_up() | {_area_id("UP"): _result([1.0e6, 7.0])}
    ctx = _ctx__discharge_per({"UP": (0, 1, 2)})

    _discharge_by_station(FakeAdapter(served), _RUN_CTX, ctx, _observed("UP"), time_index=_INDEX)

    assert reported == [("sums", _RUN_CTX, ctx), ("UP", ctx, 1.0e6)]
    assert added == [("discharge", ctx, 5.0e6), ("discharge", ctx, 1.0e6)]


def test_an_empty_catchment_series_is_refused():
    adapter = FakeAdapter({"catchment": _result([])})

    with pytest.raises(NotImplementedError, match="no discharge calibration series"):
        _by_station(adapter, {}, "NOWHERE")


def test_a_routed_reach_series_is_not_given_the_runoff_twice(monkeypatch):
    """A reach already carries the runoff injected into the network."""
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


# From test_residual_capture_shares_the_scorer.py
# The residuals a width is taken from come from the scorer the search used.
#
# A first-order width is read off the residual at each observation. Those
# residuals used to be aligned by a second reader holding its own copy of the
# records, the window and the minimum overlap; now they come from
# ``ObservableScorer.pair``, one step short of the cost. What this pins is that
# the two cannot drift apart, and that a burn-in, which the cost applies and a
# residual vector cannot, is refused instead of ignored.


_INDEX__residual_capture = pd.date_range("2020-01-01", periods=4, freq="D")

# The record is stamped at the day each simulated stamp closes, one day before.
_RECORD_INDEX = pd.date_range("2019-12-31", periods=4, freq="D")


def _outputs():
    return {"gauge": boundary_output(observes="NANCON")}


def _block(**extra):
    return CalibObjectiveBlockDecl.model_validate(
        {"name": "b", "metric": "rmse", "uses_outputs": ["gauge"], **extra}
    )


def _ctx__residual_capture():
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
        times=_INDEX__residual_capture[: len(values)],
    )


def _extracted(values, *, time="all"):
    """What `extract_outputs` returns: the selection is already applied."""
    result = select_observable_times(_answer(values), time)
    return ExtractedOutputs(
        observables={"gauge": result},
        values={"gauge": [float(v) for v in result.values]},
        series={"gauge": pd.Series(result.values, index=result.times)},
        diagnostics={},
    )


class TestTheCaptureAndTheCostReadTheSamePairing:
    def test_the_captured_vectors_are_what_the_former_reader_produced(self, monkeypatch) -> None:
        """The reference is the reader this replaced, not the one that replaced it."""
        simulated = [1.5, 2.5, 3.5, 4.5]
        extracted = _extracted(simulated)
        monkeypatch.setattr(
            composite, "extract_outputs", lambda ctx, outputs, window=None: extracted
        )
        capture_fn, captured = build_paired_vector_capture(
            _outputs(), ctx=_ctx__residual_capture(), objective_blocks=[_block()]
        )

        capture_fn(None)

        # What HEAD did: load the records itself, and pair them on the dated
        # series `extract_outputs` had already built.
        former = pair_outputs_with_observations(
            observed=observed_series_for_outputs(_outputs(), _ctx__residual_capture()),
            simulated={"gauge": extracted.series["gauge"]},
            window=None,
            min_samples=1,
        )

        assert captured["order"] == ("gauge",)
        assert list(captured["simulated"]) == pytest.approx(former.simulated["gauge"])
        assert list(captured["observed"]) == pytest.approx(former.observed["gauge"])

    def test_a_selected_timestep_is_paired_the_way_it_always_was(self, monkeypatch) -> None:
        """`pair` re-selects the times `extract_outputs` had already selected."""
        outputs = {"gauge": boundary_output(observes="NANCON", time="last")}
        extracted = _extracted([1.5, 2.5, 3.5, 4.5], time="last")
        monkeypatch.setattr(
            composite, "extract_outputs", lambda ctx, outputs_, window=None: extracted
        )
        capture_fn, captured = build_paired_vector_capture(
            outputs, ctx=_ctx__residual_capture(), objective_blocks=[_block()]
        )

        # The selection left one stamp, 2020-01-04. The run's time grid says its
        # period is the day 2020-01-03, which the record measured at 4.0.
        grid = SimpleNamespace(boundaries=tuple(pd.date_range("2019-12-31", periods=5, freq="D")))
        capture_fn(SimpleNamespace(setup=SimpleNamespace(time_grid=grid)))

        former = pair_outputs_with_observations(
            observed=observed_series_for_outputs(outputs, _ctx__residual_capture()),
            simulated={"gauge": extracted.series["gauge"]},
            window=None,
            min_samples=1,
        )
        assert list(captured["simulated"]) == pytest.approx(former.simulated["gauge"])
        assert list(captured["observed"]) == pytest.approx([4.0])

    def test_the_cost_and_the_residuals_pair_the_same_samples(self, monkeypatch) -> None:
        """One reader: what the search scored is what the derivatives are taken on."""
        simulated = [1.5, 2.5, 3.5, 4.5]
        monkeypatch.setattr(
            composite,
            "extract_outputs",
            lambda ctx, outputs, window=None: _extracted(simulated),
        )
        capture_fn, captured = build_paired_vector_capture(
            _outputs(), ctx=_ctx__residual_capture(), objective_blocks=[_block()]
        )
        capture_fn(None)

        scorer = ObservableScorer(
            _outputs(),
            [_block()],
            observed_records=observed_series_for_outputs(_outputs(), _ctx__residual_capture()),
        )
        _, components = scorer.score({"gauge": _answer(simulated)})

        assert components["gauge.n_paired"] == float(len(captured["simulated"]))
        assert components["b.n_values"] == float(len(captured["observed"]))

    def test_the_window_the_search_used_cuts_the_residuals_too(self, monkeypatch) -> None:
        monkeypatch.setattr(
            composite,
            "extract_outputs",
            lambda ctx, outputs, window=None: _extracted([1.5, 2.5, 3.5, 4.5]),
        )
        capture_fn, captured = build_paired_vector_capture(
            _outputs(),
            ctx=_ctx__residual_capture(),
            objective_blocks=[_block()],
            # The days from 2020-01-02 on: the periods the last two stamps close.
            window=(pd.Timestamp("2020-01-02"), None),
        )

        capture_fn(None)

        assert list(captured["observed"]) == pytest.approx([3.0, 4.0])

    def test_a_shorter_overlap_than_the_document_asks_for_is_refused(self, monkeypatch) -> None:
        monkeypatch.setattr(
            composite,
            "extract_outputs",
            lambda ctx, outputs, window=None: _extracted([1.5, 2.5]),
        )
        capture_fn, _ = build_paired_vector_capture(
            _outputs(), ctx=_ctx__residual_capture(), objective_blocks=[_block()], min_samples=3
        )

        with pytest.raises(ValueError, match="min_samples"):
            capture_fn(None)


class TestTheScorerRefusesToPairWhatHasNoRecord:
    def test_a_scorer_with_no_observing_output_cannot_pair(self) -> None:
        typed = {"typed": boundary_output(observed_values=[1.0, 2.0])}
        block = objective_block("b", "rmse", ["typed"])
        scorer = ObservableScorer(typed, [block])

        with pytest.raises(ValueError, match="no residual to align"):
            scorer.pair({"typed": _answer([1.0, 2.0])})


# From test_routed_discharge_skips_runoff.py
# A routed discharge already carries the runoff; adding it again double-counts.


def test_the_flag_defaults_to_false_so_drain_discharge_still_gets_its_runoff():
    result = adapter_result("x", np.zeros(3), "m3/s")
    assert result.includes_runoff is False


def test_series_observable_carries_the_flag_through():
    index = pd.date_range("2000-01-01", periods=3, freq="D")
    request = ObservableRequest(id="catchment", name="discharge", support="domain")
    series = pd.Series([1.0, 2.0, 3.0], index=index)
    assert series_observable(request, series, units="m3/s").includes_runoff is False
    routed = series_observable(request, series, units="m3/s", includes_runoff=True)
    assert routed.includes_runoff is True


def test_the_composite_metric_guards_the_runoff_addition():
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


# From test_the_protocol_s_window_reaches_a_two_bound_network.py
# The window the protocol writes on its transient stage reaches a two-bound network.
#
# The window is the phase's, not the hydrograph block's, so a network output
# scored in that phase over calendar years leaves the spin-up year out too. The
# protocol's window is expanded from the dates of the run, validated as a phase
# window, and handed to the metric route every trial takes.


def _protocol_window(start: str, end: str, **protocol: object):
    """Return the ``(start, end)`` the protocol's transient stage scores between."""
    document = {
        "simulation": {"time": {"start_datetime": start, "end_datetime": end}},
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
        "calibration": {
            "protocol": {"name": "matching_hydrographic_network", **protocol},
            "parameters": {"K": {"bounds": [1e-8, 1e-2]}, "Sy": {"bounds": [1e-4, 0.5]}},
            "outputs": {"net": {"support": "network", "map": {"complete": "map.gpkg"}}},
        },
    }
    transient = expand_calibration_protocol(document)["calibration"]["phases"][1]
    return window_bounds(CalibPhaseDecl.model_validate(transient).window)


def test_the_default_window_leaves_the_spin_up_year_out(monkeypatch, bench, stream_file) -> None:  # noqa: F811
    window = _protocol_window("2000-01-01", "2002-12-31")

    scored = _components(monkeypatch, bench, _two_bound_output(stream_file), window)

    assert scored["net.year_scored_y2000"] == 0.0
    assert scored["net.n_years_scored"] == 2.0
    assert scored["net.first_year_scored"] == 2001.0


def test_a_declared_window_still_wins(monkeypatch, bench, stream_file) -> None:  # noqa: F811
    window = _protocol_window("2000-01-01", "2002-12-31", window={"start": "2000-01-01"})

    scored = _components(monkeypatch, bench, _two_bound_output(stream_file), window)

    assert scored["net.year_scored_y2000"] == 1.0
    assert scored["net.n_years_scored"] == 3.0


# The refusals of the routes, on the state a run can be in.


class _Raises:
    calls = 0

    def observables(self, *_args, **_kwargs):
        self.calls += 1
        raise RuntimeError("boom")


def test_an_outlet_series_the_solver_cannot_serve_is_raised_as_it_is() -> None:
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
def test_the_variable_route_names_what_stops_a_trial(
    monkeypatch, caplog, ctx, producer, error, message
) -> None:
    run_ctx = SimpleNamespace(run=SimpleNamespace(solver="s"), solver_run=None)
    monkeypatch.setattr(composite, "resolve_flow_adapter", lambda _ctx: (object(), run_ctx))

    def failing(*_args, **_kwargs):
        raise producer

    monkeypatch.setitem(composite.PRODUCERS, "discharge", failing)
    metric_fn = build_metric_extractor("discharge", "rmse", ctx)

    with caplog.at_level("ERROR"), pytest.raises(error, match=message):
        metric_fn(ctx, objective="rmse", variable="discharge")

    assert ("Metric extractor failed" in caplog.text) is (producer is not None)


def test_a_run_with_no_solver_and_no_station_says_nothing(monkeypatch, caplog) -> None:
    monkeypatch.setattr(composite, "resolve_flow_adapter", lambda _ctx: None)

    with caplog.at_level("WARNING"):
        assert composite.series_at_the_stations(_Ctx(_Loaded()), {}) == {}

    assert caplog.text == ""


def test_each_producer_is_given_the_run_and_its_time_index_and_an_output_replaces_its_answer(
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


def test_a_covariance_needs_an_output_that_names_a_station() -> None:
    with pytest.raises(ValueError, match="no calibration output names a station"):
        build_paired_vector_capture({}, ctx=_Ctx(_Loaded()))
