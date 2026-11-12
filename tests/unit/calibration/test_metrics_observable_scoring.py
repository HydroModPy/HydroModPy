"""Cost of simulated observables against observed records, with the pairs behind it.

Pairs each output with its record on the stress-period stamps (m3/s, m), applies the
window and the minimum overlap, then reduces the pairs by the declared metric and
block weights. Network distances (m) are read in validity lengths when normalised.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import STATION_VARIABLES, CalibrationConfig
from hydromodpy.calibration.config_network import MatchingHydrographicNetworkOptions
from hydromodpy.calibration.config_objective import CalibObjectiveBlockDecl as Block
from hydromodpy.calibration.config_outputs import validate_calib_output
from hydromodpy.calibration.config_terms import CalibWindow
from hydromodpy.calibration.metrics import composite, solver_extract
from hydromodpy.calibration.metrics.composite import PRODUCERS, build_metric_extractor
from hydromodpy.calibration.metrics.observable_scoring import (
    VALIDATION_COST,
    ObservableScorer,
    StationBlockScorer,
    _one_record_per_station,
    bound_text,
    dated_series,
    discharge_target,
    network_distance_scales,
    refuse_a_network_state_outside_the_window,
    refuse_window_without_dates,
    select_observable_times,
    slice_time,
)
from hydromodpy.calibration.metrics.series import ObservedSeries, time_grid_boundaries
from hydromodpy.calibration.metrics.trial_series_capture import TrialSeriesSink
from hydromodpy.calibration.optim.objective import ConfigBlockObjective
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners import pipeline_evaluator
from hydromodpy.calibration.runners.recap import scored_samples
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    select_time_indices,
)
from hydromodpy.results.session.descriptor import read_session, scored_samples_text
from tests._helpers.session_documents import session_opening
from tests.unit.calibration._factories_config import messages, preflight_of
from tests.unit.calibration._factories_scoring import (
    FakeAdapter,
    adapter_result,
    boundary_output,
    objective_block,
)

RECORD_DAYS = pd.date_range("1999-12-01", "2000-02-29", freq="D")
OBS_RECORD = pd.Series(np.linspace(10.0, 12.0, len(RECORD_DAYS)), index=RECORD_DAYS).drop(
    pd.Timestamp("2000-01-25")
)

# Daily stamps, each closing the day before it.
DAILY_STAMPS = pd.date_range("2000-01-02", "2000-02-01", freq="D")
DAILY_BOUNDS = (pd.Timestamp("2000-01-01"), *DAILY_STAMPS)

# Three dry periods inside the window, one before it.
DRY_STAMPS = pd.DatetimeIndex(["2000-01-03", "2000-01-11", "2000-01-16", "2000-01-21"])
SCORE_WINDOW = (pd.Timestamp("2000-01-05"), pd.Timestamp("2000-01-31"))


def simulated_series() -> pd.Series:
    values = pd.Series(np.linspace(10.0, 11.0, len(DAILY_STAMPS)), index=DAILY_STAMPS)
    values[DRY_STAMPS] = np.nan
    return values


def head_scorer() -> ObservableScorer:
    outputs = {
        "H": validate_calib_output(
            {"variable": "head", "support": "cell", "row": 0, "col": 0, "layer": 0, "observes": "P"}
        )
    }
    blocks = [objective_block("fit", "rmse", ["H"])]
    return ObservableScorer(
        outputs, blocks, observed_records={"H": OBS_RECORD}, window=SCORE_WINDOW
    )


def head_answer() -> ObservableResult:
    simulated = simulated_series()
    return adapter_result("H", simulated.to_numpy(), "m", times=simulated.index)


def test_nan_count_warned_once(caplog) -> None:
    scorer = head_scorer()

    with caplog.at_level(logging.WARNING):
        _, first = scorer.score({"H": head_answer()}, boundaries=DAILY_BOUNDS)
        _, second = scorer.score({"H": head_answer()}, boundaries=DAILY_BOUNDS)

    assert first["H.n_sim_nan"] == 3.0
    assert second["H.n_sim_nan"] == 3.0
    warned = [r.getMessage() for r in caplog.records if "NaN" in r.getMessage()]
    assert len(warned) == 1 and "H" in warned[0] and "3" in warned[0]


def test_session_keeps_nan_count(tmp_path: Path) -> None:
    _, components = head_scorer().score({"H": head_answer()}, boundaries=DAILY_BOUNDS)
    persistence = CalibrationPersistence(tmp_path / "sessions" / "dry")
    persistence.start_session(**session_opening("dry", cost_name="rmse", bounds={}))
    line = persistence.append_iteration(
        ParamSuggestion(trial_id=1, values={"K": 1.0}),
        EvaluationResult(trial_id=1, sim_id=None, cost=1.0, components=components),
    )
    assert persistence.trials()[0].only_case.components["H.n_sim_nan"] == 3.0

    persistence.finalize_session(
        status="completed",
        best=None,
        scored=scored_samples(line.only_case.components, case_id="dry"),
    )

    samples = read_session(persistence.directory).scored
    assert samples[0].n_sim_nan == 3
    assert "3 lost to a NaN simulated value" in scored_samples_text(samples)


def gap_block(scales: dict[str, list[float]] | None, *, metric: str = "distance_gap"):
    return ConfigBlockObjective(
        name="network",
        metric=metric,
        uses_outputs=["net"],
        observed_by_output={},
        normalize_cost=True,
        distance_scales=scales,
    )


def test_efficiency_not_normalised() -> None:
    with pytest.raises(ValueError, match="already a pure number"):
        objective_block("q", "nse_log", ["q"], normalize_cost=True)


GAP_SCALES = {"net": [150.0, 150.0]}  # validity lengths (m), one per bound

DISTANCE_TOTALS = [
    pytest.param("distance_gap", GAP_SCALES, [420.0, 120.0], 2.0, id="one bound"),
    pytest.param("distance_mean", {"net": [100.0, 100.0]}, [300.0, 100.0], 2.0, id="mean distance"),
    pytest.param(
        "distance_gap",
        {"net": [100.0, 100.0, 200.0, 200.0]},
        [50.0, 150.0, 400.0, 0.0],
        100.0 / 100.0 + 400.0 / 200.0,
        id="two bounds",
    ),
    # A root search reads the sign of the cost, so both orders cost the same.
    pytest.param("distance_gap", GAP_SCALES, [100.0, 400.0], 2.0, id="gap below the scale"),
    pytest.param("distance_gap", GAP_SCALES, [400.0, 100.0], 2.0, id="gap above the scale"),
]


@pytest.mark.parametrize(("metric", "scales", "distances", "total"), DISTANCE_TOTALS)
def test_distances_in_validity_lengths(metric, scales, distances, total) -> None:
    value = gap_block(scales, metric=metric).evaluate({"net": distances})

    assert value.total == pytest.approx(total)


def test_normalised_cost_components() -> None:
    one = gap_block(GAP_SCALES).evaluate({"net": [420.0, 120.0]})
    two = gap_block({"net": [100.0, 100.0, 200.0, 200.0]}).evaluate(
        {"net": [50.0, 150.0, 400.0, 0.0]}
    )

    assert one.components["network.raw_cost"] == pytest.approx(300.0)
    assert one.components["network.normalized_cost"] == pytest.approx(2.0)
    assert one.components["network.reference_scale"] == pytest.approx(150.0)
    assert two.components["network.raw_cost"] == pytest.approx(500.0)


NETWORK_OUTPUT = validate_calib_output({"support": "network", "map": {"complete": "n.gpkg"}})

DISTANCE_SCALES = [
    pytest.param(
        {
            "net.n_bounds_scored": 2.0,
            "net.validity_length_m_minimal": 100.0,
            "net.validity_length_m_maximal": 200.0,
        },
        {"net": [100.0, 100.0, 200.0, 200.0]},
        id="minimal then maximal",
    ),
    pytest.param({}, {}, id="nothing published"),
]


@pytest.mark.parametrize(("diagnostics", "expected"), DISTANCE_SCALES)
def test_network_distance_scales(diagnostics, expected) -> None:
    assert network_distance_scales({"net": NETWORK_OUTPUT}, diagnostics) == expected


def test_zero_length_refused() -> None:
    with pytest.raises(ValueError, match="positive length"):
        gap_block({"net": [0.0, 0.0]}).evaluate({"net": [420.0, 120.0]})


def share_scorer() -> ObservableScorer:
    outputs = {
        "net": validate_calib_output({"support": "network", "map": {"complete": "n.gpkg"}}),
        "q": boundary_output(observed_values=[1.0, 2.0, 3.0, 4.0]),
    }
    blocks = [
        objective_block("network", "distance_gap", ["net"], normalize_cost=True, weight=0.2),
        objective_block("hydrograph", "nse", ["q"], weight=0.8),
    ]
    return ObservableScorer(outputs, blocks)


def test_network_cost_in_validity_lengths() -> None:
    simulated = adapter_result("q", np.array([1.0, 2.0, 3.0, 4.0]), "m3 s-1")
    total, components = share_scorer().score(
        {"q": simulated},
        network_values={"net": [450.0, 150.0]},
        diagnostics={"net.n_bounds_scored": 1.0, "net.validity_length_m": 150.0},
    )
    assert components["network.total"] == pytest.approx(2.0)
    assert components["hydrograph.total"] == pytest.approx(0.0)
    assert total == pytest.approx(0.2 * 2.0)


def test_missing_validity_length_refused() -> None:
    simulated = adapter_result("q", np.array([1.0, 2.0, 3.0, 4.0]), "m3 s-1")
    with pytest.raises(RuntimeError, match="validity length"):
        share_scorer().score({"q": simulated}, network_values={"net": [450.0, 150.0]})


# 1999 is worth 1.0 a day, 2000 is worth 3.0, 2001 is worth 5.0.
STEADY_DAYS = pd.date_range("1999-01-01", "2001-12-31", freq="D")
STEADY_RECORD = pd.Series(
    np.select([STEADY_DAYS.year == 1999, STEADY_DAYS.year == 2000], [1.0, 3.0], default=5.0),
    index=STEADY_DAYS,
)

# One steady period over 2000, stamped at its end.
STEADY_BOUNDS = (pd.Timestamp("2000-01-01"), pd.Timestamp("2001-01-01"))
STEADY_STAMP = pd.DatetimeIndex([STEADY_BOUNDS[1]])


def steady_discharge_scorer() -> StationBlockScorer:
    records = [ObservedSeries("Q", "discharge", STEADY_RECORD)]
    return StationBlockScorer("discharge", "mae", records, gauge="Q")


def steady_answer(value: float) -> ObservableResult:
    return adapter_result("Q", np.asarray([value]), "m3 s-1", times=STEADY_STAMP)


def test_steady_discharge_scored_on_its_year() -> None:
    scorer = steady_discharge_scorer()

    cost, _ = scorer.score({"Q": steady_answer(3.0)}, boundaries=STEADY_BOUNDS)

    # The year 2000 averages 3.0 exactly. The last day before the stamp is
    # also 3.0 here, so the start has to be checked on a stage it changes.
    assert cost == pytest.approx(0.0)


def test_window_start_moves_steady_score() -> None:
    scorer = steady_discharge_scorer()
    spanning = (pd.Timestamp("1999-01-01"), STEADY_BOUNDS[1])

    cost, _ = scorer.score({"Q": steady_answer(3.0)}, boundaries=spanning)

    # Two years, 1999 at 1.0 and 2000 at 3.0: (365 * 1 + 366 * 3) / 731.
    assert cost == pytest.approx(abs(3.0 - (365 * 1.0 + 366 * 3.0) / 731))


def test_weighted_route_start_from_grid() -> None:
    outputs = {"Q": boundary_output(observes="gauge")}
    blocks = [objective_block("flow", "mae", ["Q"])]
    scorer = ObservableScorer(outputs, blocks, observed_records={"Q": STEADY_RECORD})
    grid = SimpleNamespace(
        setup=SimpleNamespace(time_grid=SimpleNamespace(boundaries=STEADY_BOUNDS))
    )

    with_grid, _ = scorer.score({"Q": steady_answer(3.0)}, boundaries=time_grid_boundaries(grid))
    without, _ = scorer.score({"Q": steady_answer(3.0)})

    assert with_grid == pytest.approx(0.0)
    # No grid: the whole record, (365 + 366 * 3 + 365 * 5) / 1096.
    assert without == pytest.approx(abs(3.0 - (365 * 1.0 + 366 * 3.0 + 365 * 5.0) / 1096))


def test_steady_head_read_at_stamp() -> None:
    # A head is the state at the stamp: the grid start does not widen it.
    scorer = StationBlockScorer("head", "mae", [ObservedSeries("P", "head", STEADY_RECORD)])

    cost, _ = scorer.score({"P": steady_answer(5.0)}, boundaries=STEADY_BOUNDS)

    # The reading AT 2001-01-01 is 5.0; the mean of 2000 would be 3.0.
    assert cost == pytest.approx(0.0)


MONTHS = tuple(pd.date_range("2000-01-01", periods=37, freq="MS"))
BLOCKS = [objective_block("network", "distance_gap", ["net"])]


def network_outputs(time: str = "last") -> dict[str, object]:
    return {
        "net": validate_calib_output(
            {"support": "network", "map": {"complete": "n.gpkg"}, "time": time}
        )
    }


@pytest.mark.parametrize(
    ("time", "match"),
    [
        pytest.param("2000-10-15", "stamped 2000-11-01", id="state-before-the-window"),
        pytest.param(
            "2004-01-01",
            "network output 'net' has time = '2004-01-01'",
            id="date-the-run-does-not-hold",
        ),
    ],
)
def test_date_outside_window_refused(time, match) -> None:
    with pytest.raises(ValueError, match=match):
        refuse_window_without_dates(
            network_outputs(time),
            BLOCKS,
            (pd.Timestamp("2001-01-01"), None),
            {},
            boundaries=MONTHS,
        )


PHASE_TOML = """
[calibration]

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"
units = "m/s"

[calibration.outputs.net]
support = "network"
map.complete = "{geometry}"
time = "{time}"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]

[[calibration.phases]]
name = "conductivity"
parameters = ["K"]
method = "grid"
max_trials = 4
regime = "{regime}"
{window}
"""


def window_findings(tmp_path, *, time: str, window: str, regime: str = "transient") -> str:
    geometry = tmp_path / "streams.gpkg"
    geometry.write_bytes(b"map")
    findings = preflight_of(
        tmp_path, PHASE_TOML.format(geometry=geometry, time=time, window=window, regime=regime)
    )
    return messages(item for item in findings if "window" in item.detail or "time =" in item.detail)


FROM_JULY = '[calibration.phases.window]\nstart = "2000-07-01"'
TO_JUNE = '[calibration.phases.window]\nend = "2000-06-30"'

# The steady span is a day count: a unitless timedelta warns under the pinned NumPy.
NO_GENERIC_UNIT = pytest.mark.filterwarnings(
    "error:The 'generic' unit for NumPy timedelta:DeprecationWarning"
)


def test_last_state_in_window_no_finding(tmp_path) -> None:
    assert window_findings(tmp_path, time="last", window=FROM_JULY) == ""


WINDOW_FINDINGS = [
    pytest.param(
        "2000-03-15", FROM_JULY, "transient", ["stamped 2000-03-15"], id="dated state outside"
    ),
    pytest.param(
        "2005-03-15",
        "",
        "transient",
        ["calibration.outputs.net: ", "outside the record"],
        id="date outside record",
    ),
    pytest.param(
        "2000-03-15",
        TO_JUNE,
        "steady",
        ["stamped 2001-01-01"],
        id="steady stamped at window end",
        marks=NO_GENERIC_UNIT,
    ),
]


@pytest.mark.parametrize(("time", "window", "regime", "named"), WINDOW_FINDINGS)
def test_window_findings_named(tmp_path, time, window, regime, named) -> None:
    found = window_findings(tmp_path, time=time, window=window, regime=regime)

    for text in named:
        assert text in found


PROTOCOL_WINDOWS = [
    pytest.param({"window": {"start": "2001-13-01"}}, "is not a date", id="bad date"),
    pytest.param({"steady_window": {"start": "2000-01-01"}}, "missing end", id="steady span"),
    pytest.param({"window": {"begin": "2001-01-01"}}, "begin", id="unknown bound"),
]


@pytest.mark.parametrize(("window", "match"), PROTOCOL_WINDOWS)
def test_protocol_window_must_be_dates(window, match) -> None:
    with pytest.raises(ValueError, match=match):
        MatchingHydrographicNetworkOptions.model_validate(
            {"name": "matching_hydrographic_network", **window}
        )


def observed_stations(*station_ids: str) -> list:
    return [SimpleNamespace(station_id=sid) for sid in station_ids]


DISCHARGE_TARGET_REFUSALS = [
    pytest.param(
        ("NANCON", "UPSTREAM"), None, "per-cell discharge observable", id="several gauges"
    ),
    pytest.param(
        ("NANCON",), "J001401001", "is not among the loaded discharge stations", id="not loaded"
    ),
    pytest.param((), None, "No observed discharge station", id="no station"),
]


@pytest.mark.parametrize(("ids", "gauge", "match"), DISCHARGE_TARGET_REFUSALS)
def test_discharge_target_refusals(ids, gauge, match) -> None:
    with pytest.raises(ValueError, match=match):
        discharge_target(observed_stations(*ids), gauge)


def wire_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    results: Mapping[str, ObservableResult],
    observed: Mapping[str, pd.Series] | None = None,
) -> None:
    class Adapter:
        def observables(
            self,
            solver_run: object,
            requests: Sequence[ObservableRequest],
            *,
            time_index: pd.DatetimeIndex | None = None,
        ) -> dict[str, ObservableResult]:
            served = {}
            for request in requests:
                result = results[request.id]
                selected = select_time_indices(result.values.size, request.times)
                served[request.id] = replace(
                    result,
                    values=result.values[selected],
                    times=result.times[selected] if result.times is not None else None,
                )
            return served

    monkeypatch.setattr(
        solver_extract,
        "resolve_flow_adapter",
        lambda ctx: (Adapter(), SimpleNamespace(solver_run=None)),
    )
    monkeypatch.setattr(solver_extract, "resolve_time_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        composite, "observed_series_for_outputs", lambda outputs, ctx: observed or {}
    )


def test_weighted_outputs_reduction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = {
        "q": validate_calib_output(
            dict(
                variable="discharge",
                support="boundary",
                boundary_id="outlet",
                observed_values=[1.0, 2.0],
            )
        ),
        "stage": validate_calib_output(
            dict(
                variable="stage",
                support="lake",
                lake_id="lake",
                reducer="mean",
                observed_values=[10.0],
            )
        ),
    }
    blocks = [
        objective_block("flow", "rmse", ["q"], weight=1.0),
        objective_block("lake", "mae", ["stage"], weight=3.0),
    ]
    results = {
        "q": ObservableResult("q", np.array([3.0, 4.0]), "m3/s"),
        "stage": ObservableResult("stage", np.array([13.0, 15.0]), "m"),
    }
    wire_pipeline(monkeypatch, results)
    pipeline = composite.build_metric_extractor(
        None, None, object(), outputs=outputs, objective_blocks=blocks
    )
    foreign = ObservableScorer(outputs, blocks)

    total, components = foreign.score(results)

    assert total == pytest.approx(3.5)
    assert components["flow.raw_cost"] == pytest.approx(2.0)
    assert components["lake.raw_cost"] == pytest.approx(4.0)
    assert pipeline(object()) == (total, components)


def test_dated_window_same_for_both_producers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = pd.date_range("2001-01-01", periods=4)
    outputs = {
        "q": validate_calib_output(
            dict(variable="discharge", support="boundary", boundary_id="outlet", observes="gauge")
        )
    }
    blocks = [objective_block("flow", "rmse", ["q"])]
    results = {"q": ObservableResult("q", np.array([101.0, 5.0, 6.0, 7.0]), "m3/s", times)}
    # Each simulated stamp closes the day observed one day before it.
    observed = {
        "q": pd.Series([1.0, 2.0, 3.0, 4.0, 999.0], index=pd.date_range("2000-12-31", periods=5))
    }
    # The window holds the days 2001-01-01 to 2001-01-04: the stamp 2001-01-01
    # closes 2000-12-31, which it leaves out.
    options = dict(window=(times[0], times[-1]), min_samples=3)
    wire_pipeline(monkeypatch, results, observed)
    pipeline = composite.build_metric_extractor(
        None, None, object(), outputs=outputs, objective_blocks=blocks, **options
    )
    foreign = ObservableScorer(outputs, blocks, observed_records=observed, **options)

    total, components = foreign.score(results)

    assert total == pytest.approx(3.0)
    assert components["flow.n_values"] == 3.0
    assert components["q.n_paired"] == 3.0
    # The window leaves out the first stamp: only 2001-01-02 to 2001-01-04 remain.
    assert date.fromordinal(int(components["q.date_start"])) == date(2001, 1, 2)
    assert date.fromordinal(int(components["q.date_end"])) == date(2001, 1, 4)
    assert pipeline(object()) == (total, components)
    with pytest.raises(ValueError, match="fewer than the 4"):
        ObservableScorer(
            outputs, blocks, observed_records=observed, **{**options, "min_samples": 4}
        ).score(results)


def test_network_values_not_a_release_field() -> None:
    outputs = {
        "net": validate_calib_output(dict(support="network", map={"complete": "data.hydrography"}))
    }
    blocks = [objective_block("network", "distance_gap", ["net"])]
    scorer = ObservableScorer(outputs, blocks)

    total, components = scorer.score(
        {}, network_values={"net": [12.0, 20.0]}, diagnostics={"net.r_optim": 0.3}
    )

    assert total == pytest.approx(8.0)
    assert components["network.raw_cost"] == pytest.approx(8.0)
    assert components["net.r_optim"] == pytest.approx(0.3)
    with pytest.raises(ValueError, match="prepared network distances"):
        scorer.score({"net": ObservableResult("net", np.array([12.0, 20.0]), "m3/s")})


def test_observed_output_without_dates() -> None:
    outputs = {
        "q": validate_calib_output(
            dict(variable="discharge", support="boundary", boundary_id="outlet", observes="gauge")
        )
    }
    blocks = [objective_block("flow", "rmse", ["q"])]
    scorer = ObservableScorer(
        outputs,
        blocks,
        observed_records={"q": pd.Series([1.0], index=pd.date_range("2001-01-01", periods=1))},
    )
    with pytest.raises(ValueError, match="produced no series"):
        scorer.score({"q": ObservableResult("q", np.array([1.0]), "m3/s")})


@pytest.mark.parametrize(
    ("selector", "values", "count"),
    [
        pytest.param("first", [1.0, 102.0, 103.0], 1, id="first stamp"),
        pytest.param("last", [101.0, 102.0, 3.0], 1, id="last stamp"),
    ],
)
def test_time_selection_of_one_stamp(
    monkeypatch: pytest.MonkeyPatch, selector: str, values: list[float], count: int
) -> None:
    times = pd.date_range("2001-01-01", periods=3)
    outputs = {
        "q": validate_calib_output(
            dict(
                variable="discharge",
                support="boundary",
                boundary_id="outlet",
                observes="gauge",
                time=selector,
            )
        )
    }
    blocks = [objective_block("flow", "rmse", ["q"])]
    results = {"q": ObservableResult("q", np.asarray(values), "m3/s", times)}
    # The record is stamped at the day each simulated stamp closes.
    observed = {"q": pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2000-12-31", periods=3))}
    wire_pipeline(monkeypatch, results, observed)
    pipeline = composite.build_metric_extractor(
        None,
        None,
        object(),
        outputs=outputs,
        objective_blocks=blocks,
    )
    foreign = ObservableScorer(outputs, blocks, observed_records=observed)
    # A solver that honors the request hands back the one selected stamp, so
    # the start of its period can only come from the run's time grid.
    trial_ctx = SimpleNamespace(
        setup=SimpleNamespace(
            time_grid=SimpleNamespace(boundaries=(times[0] - pd.Timedelta("1D"), *times))
        )
    )

    total, components = foreign.score(results)

    assert total == pytest.approx(0.0)
    assert components["q.n_paired"] == count
    assert pipeline(trial_ctx) == (total, components)


INDEX = pd.date_range("2020-01-01", periods=3, freq="D")

# A discharge is the mean of the period its stamp closes, so a gauge day is
# stamped one day before the simulated stamp that closes it.
DAY_BEFORE_INDEX = pd.date_range("2019-12-31", periods=3, freq="D")


def station_record(station_id: str, values, variable: str = "head") -> ObservedSeries:
    # A head or a lake level is the state AT the stamp, so its record is read
    # at the stamp instants themselves. Shifting it by a day, as a discharge
    # is, would pair each state with the reading of the day before.
    index = DAY_BEFORE_INDEX if variable == "discharge" else INDEX
    return ObservedSeries(
        station_id=station_id,
        variable=variable,
        series=pd.Series(np.asarray(values, dtype=float), index=index[: len(values)]),
    )


def station_answer(station_id: str, values, *, dated: bool = True) -> ObservableResult:
    array = np.asarray(values, dtype=float)
    return adapter_result(station_id, array, "m", times=INDEX[: array.size] if dated else None)


def station_scorer(variable, *ids, metric="rmse", values=None, **options):
    """A scorer over records that all hold `values`, 10 to 12 for a state and 1 for a flow."""
    if values is None:
        values = [1.0, 1.0, 1.0] if variable == "discharge" else [10.0, 11.0, 12.0]
    kind = "discharge" if variable == "discharge" else "head"
    records = [station_record(station, values, kind) for station in ids]
    return StationBlockScorer(variable, metric, records, **options)


def test_producers_match_scored_variables() -> None:
    assert set(PRODUCERS) == set(STATION_VARIABLES)


def test_unobserved_variable_refused() -> None:
    with pytest.raises(NotImplementedError, match="is not supported"):
        station_scorer("salinity", "A", values=[1.0, 2.0, 3.0])


def test_head_answer_scored_alone() -> None:
    scorer = station_scorer("head", "PZ1")

    cost, components = scorer.score({"PZ1": station_answer("PZ1", [10.5, 11.5, 12.5])})

    assert cost == pytest.approx(0.5)
    assert components["rmse@PZ1.raw_cost"] == pytest.approx(0.5)
    assert components["head@PZ1.n_paired"] == 3.0


def test_named_criterion_is_applied() -> None:
    observed = [station_record("PZ1", [10.0, 11.0, 12.0])]
    answer = {"PZ1": station_answer("PZ1", [10.5, 12.5, 12.5])}

    rmse, _ = StationBlockScorer("head", "rmse", observed).score(answer)
    mae, _ = StationBlockScorer("head", "mae", observed).score(answer)

    assert rmse != pytest.approx(mae)


def test_several_heads_averaged() -> None:
    scorer = station_scorer("head", "PZ1", "PZ2")

    cost, components = scorer.score(
        {
            "PZ1": station_answer("PZ1", [10.5, 11.5, 12.5]),
            "PZ2": station_answer("PZ2", [11.5, 12.5, 13.5]),
        }
    )

    assert components["rmse@PZ1.raw_cost"] == pytest.approx(0.5)
    assert components["rmse@PZ2.raw_cost"] == pytest.approx(1.5)
    assert cost == pytest.approx(1.0)


def test_declared_gauge_alone_scored() -> None:
    scorer = StationBlockScorer(
        "discharge",
        "rmse",
        [
            station_record("OUTLET", [1.0, 1.0, 1.0], variable="discharge"),
            station_record("UP", [1.0, 1.0, 1.0], variable="discharge"),
        ],
        gauge="UP",
    )

    cost, components = scorer.score(
        {
            "OUTLET": station_answer("OUTLET", [9.0, 9.0, 9.0]),
            "UP": station_answer("UP", [2.0, 2.0, 2.0]),
        }
    )

    assert cost == pytest.approx(1.0)
    assert [record.station_id for record in scorer.stations] == ["UP"]
    assert not [key for key in components if "OUTLET" in key]


def test_missing_gauge_answer_refused() -> None:
    scorer = StationBlockScorer(
        "discharge",
        "rmse",
        [
            station_record("OUTLET", [1.0, 1.0, 1.0], variable="discharge"),
            station_record("UP", [1.0, 1.0, 1.0], variable="discharge"),
        ],
        gauge="UP",
    )

    with pytest.raises(NotImplementedError, match="'UP'"):
        scorer.score({"OUTLET": station_answer("OUTLET", [9.0, 9.0, 9.0])})


def test_unplaced_gauge_stays_unscored() -> None:
    scorer = station_scorer("head", "PZ1", "NOWHERE")

    cost, components = scorer.score({"PZ1": station_answer("PZ1", [10.5, 11.5, 12.5])})

    assert cost == pytest.approx(0.5)
    assert not [key for key in components if "NOWHERE" in key]


def test_left_out_gauge_warned_once(caplog) -> None:
    scorer = station_scorer("head", "PZ1", "NOWHERE")
    answer = {"PZ1": station_answer("PZ1", [10.5, 11.5, 12.5])}

    with caplog.at_level("WARNING"):
        scorer.score(answer, source="Solver 'modflow6'")
        scorer.score(answer, source="Solver 'modflow6'")

    said = [record for record in caplog.records if "NOWHERE" in record.getMessage()]
    assert len(said) == 1
    assert "head" in said[0].getMessage()


def test_unscorable_answer_refused() -> None:
    scorer = station_scorer("head", "PZ1")

    with pytest.raises(ValueError, match="served no head at any of the stations"):
        scorer.score({})


def test_empty_series_refused() -> None:
    scorer = station_scorer("lake_level", "lac0")

    with pytest.raises(NotImplementedError, match="fake_solver"):
        scorer.score({"lac0": station_answer("lac0", [], dated=False)}, source="fake_solver")


def one_gauge_ctx():
    """A project loading one gauge, and no runoff to add to the budget."""
    frame = pd.DataFrame({"datetime": DAY_BEFORE_INDEX, "value": [1.0, 1.0, 1.0]})
    record = SimpleNamespace(station_id="OUTLET", variable="discharge", data=frame)
    return SimpleNamespace(
        setup=SimpleNamespace(cell_mesh=None, domain=None, geographic=None, time_grid=None),
        loaded_data=SimpleNamespace(
            hydrometry=SimpleNamespace(points=[record]),
            piezometry=None,
            runoff=None,
        ),
    )


def wired(monkeypatch):
    served = {"catchment": station_answer("catchment", [2.0, 2.0, 2.0])}
    monkeypatch.setattr(
        "hydromodpy.calibration.metrics.composite.resolve_flow_adapter",
        lambda ctx: (
            FakeAdapter(served),
            SimpleNamespace(
                run=SimpleNamespace(solver="modflow6"),
                solver_run=SimpleNamespace(solver_model=None),
            ),
        ),
    )
    ctx = one_gauge_ctx()
    return ctx, build_metric_extractor("discharge", "rmse", ctx)


def test_extractor_equals_bare_scorer(monkeypatch) -> None:
    ctx, metric_fn = wired(monkeypatch)

    through_pipeline = metric_fn(ctx, objective="rmse", variable="discharge")
    bare = StationBlockScorer(
        "discharge", "rmse", [station_record("OUTLET", [1.0, 1.0, 1.0], "discharge")]
    ).score({"OUTLET": station_answer("OUTLET", [2.0, 2.0, 2.0])})

    assert through_pipeline == bare
    assert through_pipeline[0] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("call", "match"),
    [
        pytest.param(
            {"objective": "nse", "variable": "discharge"},
            "Build a second extractor",
            id="criterion",
        ),
        pytest.param({"objective": "rmse", "variable": "head"}, "variable='head'", id="variable"),
    ],
)
def test_trial_cannot_rename_its_score(monkeypatch, call, match) -> None:
    ctx, metric_fn = wired(monkeypatch)

    with pytest.raises(ValueError, match=match):
        metric_fn(ctx, **call)


def test_refusal_before_any_read() -> None:
    metric_fn = build_metric_extractor("discharge", "rmse", one_gauge_ctx())

    with pytest.raises(ValueError, match="Build a second extractor"):
        metric_fn(SimpleNamespace(), objective="nse", variable="discharge")


VAL_DAYS = pd.date_range("2000-01-01", periods=6, freq="D")
VAL_RECORD = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0], index=VAL_DAYS)
VAL_FIRST, VAL_LATER = (VAL_DAYS[0], VAL_DAYS[2]), (VAL_DAYS[3], VAL_DAYS[5])
VAL_HEAD = {"variable": "head", "support": "cell", "row": 0, "col": 0, "layer": 0, "observes": "P"}


def val_scorer(metric="rmse", record=VAL_RECORD, **options) -> ObservableScorer:
    return ObservableScorer(
        {"h": validate_calib_output(VAL_HEAD)},
        [objective_block("fit", metric, ["h"])],
        observed_records={"h": record},
        window=VAL_FIRST,
        **options,
    )


def val_answer(first: float = 1.0, later: float = 3.0) -> dict[str, ObservableResult]:
    simulated = VAL_RECORD.to_numpy() + np.array([first] * 3 + [later] * 3)
    return {"h": adapter_result("h", simulated, "m", times=VAL_DAYS)}


def test_validation_never_moves_cost() -> None:
    sink = TrialSeriesSink()
    scorer = val_scorer(validation_window=VAL_LATER, series_sink=sink)

    cost, scored = scorer.score(val_answer())
    worse = scorer.score(val_answer(later=5.0))

    assert [row["simulated"] for row in sink.drain()[:3]] == [11.0, 12.0, 13.0]
    assert (cost, worse[0]) == (1.0, 1.0)
    assert worse[1][VALIDATION_COST] == pytest.approx(5.0)
    assert scored.pop(VALIDATION_COST) == pytest.approx(3.0)
    assert (cost, scored) == val_scorer().score(val_answer())


@pytest.mark.parametrize(
    ("metric", "record", "window", "said"),
    [
        ("rmse", VAL_RECORD, (pd.Timestamp("2001-01-01"), pd.Timestamp("2001-12-31")), 1),
        ("nse", VAL_RECORD.where(VAL_RECORD < 13.0, 13.0), VAL_LATER, 0),
    ],
    ids=["no_pair", "undefined_metric"],
)
def test_unscored_validation_keeps_cost(caplog, metric, record, window, said) -> None:
    scorer = val_scorer(metric, record, validation_window=window)

    with caplog.at_level(logging.WARNING):
        first = scorer.score(val_answer())
        second = scorer.score(val_answer())

    assert first == second == val_scorer(metric, record).score(val_answer())
    start = "A trial has no score on the validation window: output "
    assert sum(r.getMessage().startswith(start) for r in caplog.records) == said


def test_validation_on_dated_blocks_only() -> None:
    outputs = {"h": validate_calib_output(VAL_HEAD), **network_outputs()}
    blocks = [
        objective_block("fit", "rmse", ["h"], weight=1.0),
        objective_block("map", "distance_gap", ["net"], weight=3.0),
    ]
    distances = {"net": [100.0, 100.0]}
    options = {"validation_window": VAL_LATER}
    both = ObservableScorer(outputs, blocks, observed_records={"h": VAL_RECORD}, **options)
    net = ObservableScorer({"net": outputs["net"]}, blocks[1:], **options)

    assert both.score(val_answer(), network_values=distances)[1][VALIDATION_COST] == 3.0
    assert VALIDATION_COST not in net.score({}, network_values=distances)[1]


def test_validation_on_both_routes(monkeypatch) -> None:
    wire_pipeline(monkeypatch, val_answer(), {"h": VAL_RECORD})
    declared = composite.build_metric_extractor(
        None,
        None,
        object(),
        outputs={"h": validate_calib_output(VAL_HEAD)},
        objective_blocks=[objective_block("fit", "rmse", ["h"])],
        window=VAL_FIRST,
        validation_window=VAL_LATER,
    )
    station = station_scorer("head", "P", validation_window=(INDEX[2], INDEX[2]))
    answer = {"P": station_answer("P", [11.0, 12.0, 14.0])}

    assert declared(object())[1][VALIDATION_COST] == pytest.approx(3.0)
    assert station.score(answer)[1][VALIDATION_COST] == pytest.approx(2.0)


def test_evaluator_hands_over_window(monkeypatch) -> None:
    handed = {}
    monkeypatch.setattr(
        pipeline_evaluator, "build_metric_extractor", lambda *_, **kw: handed.update(kw)
    )
    late = CalibWindow(start="2001-01-01", end="2001-12-31")

    pipeline_evaluator._extractor_for(
        CalibrationConfig(window=CalibWindow(end="2000-12-31"), validation_window=late),
        SimpleNamespace(base_cfg=SimpleNamespace(site=None), ctx=None),
    )

    assert handed["validation_window"][0] == pd.Timestamp("2001-01-01")


def two_gauges():
    frame = pd.DataFrame({"datetime": INDEX, "value": [1.0, 1.0, 1.0]})
    points = [
        SimpleNamespace(station_id=sid, variable="discharge", data=frame)
        for sid in ("OUTLET", "UP")
    ]
    return SimpleNamespace(
        setup=SimpleNamespace(time_grid=None),
        loaded_data=SimpleNamespace(hydrometry=SimpleNamespace(points=points)),
    )


def test_two_gauges_refused_at_build() -> None:
    with pytest.raises(ValueError, match="one simulated discharge series"):
        build_metric_extractor("discharge", "rmse", two_gauges())


def test_empty_answer_not_dated() -> None:
    assert slice_time(np.array([]), "all", "mean") == []
    assert dated_series(adapter_result("q", np.array([]), "m", times=pd.DatetimeIndex([]))) is None


@pytest.mark.parametrize("times", [None, pd.date_range("2000-01-01", periods=2)])
def test_mismatched_dates_not_a_series(times) -> None:
    answer = adapter_result("q", np.array([1.0, 2.0, 3.0]), "m", times=times)

    assert dated_series(answer) is None
    if times is not None:
        with pytest.raises(ValueError, match="mismatched timestamps"):
            select_observable_times(answer, "first")


@pytest.mark.parametrize(
    ("window", "boundaries"),
    [
        (None, None),
        ((None, None), None),
        ((pd.Timestamp("2000-01-05"), None), [pd.Timestamp("2000-01-01")]),
    ],
)
def test_unbounded_window_not_checked(window, boundaries) -> None:
    refuse_a_network_state_outside_the_window({}, [], window, boundaries)


@pytest.mark.parametrize(
    ("value", "written"),
    [(None, "open"), ("2000-01-05", "2000-01-05"), ("2000-01-05 06:00", "2000-01-05T06:00:00")],
)
def test_window_bound_text(value, written) -> None:
    assert bound_text(value) == written


def test_station_loaded_twice_kept_once(caplog) -> None:
    records = [
        ObservedSeries("S1", "discharge", pd.Series([1.0])),
        ObservedSeries("S2", "discharge", pd.Series([2.0])),
        ObservedSeries("S1", "discharge", pd.Series([3.0])),
    ]

    with caplog.at_level(logging.WARNING):
        kept = _one_record_per_station(records)

    assert [(record.station_id, record.series.iloc[0]) for record in kept] == [
        ("S1", 1.0),
        ("S2", 2.0),
    ]
    assert "'S1' is loaded twice" in caplog.text


def test_pairing_refusals() -> None:
    scorer = head_scorer()

    for answers in ({}, {"H": adapter_result("H", np.array([1.0]), "m")}):
        with pytest.raises(
            ValueError, match="output 'H' observes a station but produced no series"
        ):
            scorer.pair(answers)
