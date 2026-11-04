"""Tests of `metrics.observable_scoring`."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import (
    STATION_VARIABLES,
    CalibAggregateDecl,
    CalibObjectiveBlockDecl,
    CalibOutputPoint,
    CalibrationConfig,
    CalibWindow,
    MatchingHydrographicNetworkOptions,
    validate_calib_output,
)
from hydromodpy.calibration.config import CalibObjectiveBlockDecl as Block
from hydromodpy.calibration.metrics import composite, solver_extract
from hydromodpy.calibration.metrics.composite import PRODUCERS, build_metric_extractor
from hydromodpy.calibration.metrics.observable_scoring import (
    VALIDATION_COST,
    ObservableScorer,
    StationBlockScorer,
    discharge_target,
    network_distance_scales,
    refuse_window_without_dates,
)
from hydromodpy.calibration.metrics.observed_pairing import pair_outputs_with_observations
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
from hydromodpy.core.time.period_aggregation import period_edges
from hydromodpy.results.session.descriptor import read_session, scored_samples_text
from tests._helpers.session_documents import session_opening
from tests.unit.calibration._factories_config import messages, preflight_of
from tests.unit.calibration._factories_scoring import (
    FakeAdapter,
    adapter_result,
    boundary_output,
    objective_block,
)

# From test_a_dry_cell_is_counted_beside_the_cost.py
# A pair dropped because the simulated value is NaN is counted beside the cost.
#
# A dry cell leaves its simulated head NaN, and the pairing drops that period
# from both series. The scored sample then depends on the parameters of the
# trial, and nothing said so. The count of such pairs inside the window now
# travels with the cost: in the components of the trial, so in its journal
# line, and in ``scored`` of ``session.json``. A warning says it the
# first time an output loses pairs that way. A period the record leaves empty is
# not counted: it does not move with the parameters.


_RECORD_DAYS = pd.date_range("1999-12-01", "2000-02-29", freq="D")
_RECORD = pd.Series(np.linspace(10.0, 12.0, len(_RECORD_DAYS)), index=_RECORD_DAYS).drop(
    pd.Timestamp("2000-01-25")
)

# Daily stamps, each closing the day before it.
_STAMPS = pd.date_range("2000-01-02", "2000-02-01", freq="D")
_BOUNDS = (pd.Timestamp("2000-01-01"), *_STAMPS)

# Three dry periods inside the window, one before it.
_DRY = pd.DatetimeIndex(["2000-01-03", "2000-01-11", "2000-01-16", "2000-01-21"])
_WINDOW = (pd.Timestamp("2000-01-05"), pd.Timestamp("2000-01-31"))


def _simulated() -> pd.Series:
    values = pd.Series(np.linspace(10.0, 11.0, len(_STAMPS)), index=_STAMPS)
    values[_DRY] = np.nan
    return values


def _scorer() -> ObservableScorer:
    outputs = {
        "H": validate_calib_output(
            {"variable": "head", "support": "cell", "row": 0, "col": 0, "layer": 0, "observes": "P"}
        )
    }
    blocks = [objective_block("fit", "rmse", ["H"])]
    return ObservableScorer(outputs, blocks, observed_records={"H": _RECORD}, window=_WINDOW)


def _answer() -> ObservableResult:
    simulated = _simulated()
    return adapter_result("H", simulated.to_numpy(), "m", times=simulated.index)


def test_the_pairing_counts_the_dry_periods_of_the_window() -> None:
    paired = pair_outputs_with_observations(
        observed={"H": _RECORD},
        simulated={"H": _simulated()},
        window=_WINDOW,
        time_methods={"H": "point"},
    )

    assert paired.n_simulated_nan == {"H": 3}


def test_the_count_is_a_component_of_the_cost_and_warned_once(caplog) -> None:
    scorer = _scorer()

    with caplog.at_level(logging.WARNING):
        _, first = scorer.score({"H": _answer()}, boundaries=_BOUNDS)
        _, second = scorer.score({"H": _answer()}, boundaries=_BOUNDS)

    assert first["H.n_sim_nan"] == 3.0
    assert second["H.n_sim_nan"] == 3.0
    warned = [r.getMessage() for r in caplog.records if "NaN" in r.getMessage()]
    assert len(warned) == 1 and "H" in warned[0] and "3" in warned[0]


def test_a_wet_trial_writes_zero() -> None:
    simulated = pd.Series(np.linspace(10.0, 11.0, len(_STAMPS)), index=_STAMPS)
    answer = adapter_result("H", simulated.to_numpy(), "m", times=_STAMPS)

    _, components = _scorer().score({"H": answer}, boundaries=_BOUNDS)

    assert components["H.n_sim_nan"] == 0.0


def test_the_journal_and_the_session_keep_the_count(tmp_path: Path) -> None:
    _, components = _scorer().score({"H": _answer()}, boundaries=_BOUNDS)
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


# From test_a_network_distance_is_counted_in_validity_lengths.py
# A normalized network distance is counted in validity lengths.
#
# A network block scores a distance in meters and a hydrograph block an
# efficiency, a pure number. Added raw, a phase share table between the two is an
# exchange rate between meters and an efficiency. ``normalize_cost = true`` on
# ``distance_gap`` or ``distance_mean`` divides each distance by the output's
# validity length (Eq. 4, ``"auto"`` = 2 h_obs), which the trial publishes, so the
# cost is a pure number and a share means a share.


def _gap(scales: dict[str, list[float]] | None, *, metric: str = "distance_gap"):
    return ConfigBlockObjective(
        name="network",
        metric=metric,
        uses_outputs=["net"],
        observed_by_output={},
        normalize_cost=True,
        distance_scales=scales,
    )


class TestTheDeclaration:
    @pytest.mark.parametrize("metric", ["distance_gap", "distance_mean"])
    def test_a_network_distance_may_be_normalised(self, metric: str) -> None:
        block = CalibObjectiveBlockDecl(
            name="network", metric=metric, uses_outputs=["net"], normalize_cost=True
        )
        assert block.normalize_cost is True

    def test_an_efficiency_is_still_refused(self) -> None:
        with pytest.raises(ValueError, match="already a pure number"):
            objective_block("q", "nse_log", ["q"], normalize_cost=True)


class TestTheCost:
    def test_one_bound_is_divided_by_its_validity_length(self) -> None:
        value = _gap({"net": [150.0, 150.0]}).evaluate({"net": [420.0, 120.0]})
        assert value.total == pytest.approx(2.0)
        assert value.components["network.raw_cost"] == pytest.approx(300.0)
        assert value.components["network.normalized_cost"] == pytest.approx(2.0)
        assert value.components["network.reference_scale"] == pytest.approx(150.0)

    def test_the_mean_distance_is_divided_the_same_way(self) -> None:
        value = _gap({"net": [100.0, 100.0]}, metric="distance_mean").evaluate(
            {"net": [300.0, 100.0]}
        )
        assert value.total == pytest.approx(2.0)

    def test_two_bounds_are_each_divided_by_their_own_length(self) -> None:
        scales = {"net": [100.0, 100.0, 200.0, 200.0]}
        value = _gap(scales).evaluate({"net": [50.0, 150.0, 400.0, 0.0]})
        assert value.total == pytest.approx(100.0 / 100.0 + 400.0 / 200.0)
        assert value.components["network.raw_cost"] == pytest.approx(500.0)

    def test_the_sign_a_root_search_reads_is_kept(self) -> None:
        low = _gap({"net": [150.0, 150.0]}).evaluate({"net": [100.0, 400.0]})
        high = _gap({"net": [150.0, 150.0]}).evaluate({"net": [400.0, 100.0]})
        assert low.total == pytest.approx(high.total) == pytest.approx(2.0)

    def test_no_length_published_refuses_the_trial_by_name(self) -> None:
        with pytest.raises(ValueError, match="output 'net' by its validity length"):
            _gap(None).evaluate({"net": [420.0, 120.0]})

    def test_a_length_for_another_count_of_values_is_refused(self) -> None:
        with pytest.raises(ValueError, match="2 for 4 values"):
            _gap({"net": [150.0, 150.0]}).evaluate({"net": [1.0, 2.0, 3.0, 4.0]})

    def test_a_length_that_is_not_positive_is_refused(self) -> None:
        with pytest.raises(ValueError, match="positive length"):
            _gap({"net": [0.0, 0.0]}).evaluate({"net": [420.0, 120.0]})


class TestTheLengthsATrialPublishes:
    NETWORK = validate_calib_output({"support": "network", "map": {"complete": "n.gpkg"}})

    def test_one_bound_reads_its_unsuffixed_length(self) -> None:
        found = network_distance_scales(
            {"net": self.NETWORK},
            {"net.n_bounds_scored": 1.0, "net.validity_length_m": 150.0},
        )
        assert found == {"net": [150.0, 150.0]}

    def test_two_bounds_read_the_minimal_then_the_maximal(self) -> None:
        found = network_distance_scales(
            {"net": self.NETWORK},
            {
                "net.n_bounds_scored": 2.0,
                "net.validity_length_m_minimal": 100.0,
                "net.validity_length_m_maximal": 200.0,
            },
        )
        assert found == {"net": [100.0, 100.0, 200.0, 200.0]}

    def test_an_output_that_published_none_is_left_out(self) -> None:
        assert network_distance_scales({"net": self.NETWORK}, {}) == {}


class TestAShareIsAShare:
    """A phase table between a network block and an efficiency weighs pure numbers."""

    def _scorer(self) -> ObservableScorer:
        outputs = {
            "net": validate_calib_output({"support": "network", "map": {"complete": "n.gpkg"}}),
            "q": boundary_output(observed_values=[1.0, 2.0, 3.0, 4.0]),
        }
        blocks = [
            objective_block("network", "distance_gap", ["net"], normalize_cost=True, weight=0.2),
            objective_block("hydrograph", "nse", ["q"], weight=0.8),
        ]
        return ObservableScorer(outputs, blocks)

    def test_the_network_enters_the_sum_in_validity_lengths(self) -> None:
        simulated = adapter_result("q", np.array([1.0, 2.0, 3.0, 4.0]), "m3 s-1")
        total, components = self._scorer().score(
            {"q": simulated},
            network_values={"net": [450.0, 150.0]},
            diagnostics={"net.n_bounds_scored": 1.0, "net.validity_length_m": 150.0},
        )
        assert components["network.total"] == pytest.approx(2.0)
        assert components["hydrograph.total"] == pytest.approx(0.0)
        assert total == pytest.approx(0.2 * 2.0)

    def test_a_trial_that_published_no_length_is_not_scored(self) -> None:
        simulated = adapter_result("q", np.array([1.0, 2.0, 3.0, 4.0]), "m3 s-1")
        with pytest.raises(RuntimeError, match="validity length"):
            self._scorer().score({"q": simulated}, network_values={"net": [450.0, 150.0]})


class TestTheUnitsOfASum:
    def _config(self, blocks: list[dict[str, object]]) -> dict[str, object]:
        return {
            "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
            "outputs": {
                "net": {"support": "network", "map": {"complete": "n.gpkg"}},
                "head": {
                    "variable": "head",
                    "support": "cell",
                    "row": 0,
                    "col": 0,
                    "observed_values": [1.0, 2.0],
                },
            },
            "objective_blocks": blocks,
        }

    def test_a_raw_distance_beside_a_raw_head_residual_is_refused(self) -> None:
        with pytest.raises(ValueError) as caught:
            CalibrationConfig.model_validate(
                self._config(
                    [
                        {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]},
                        {"name": "heads", "metric": "rmse", "uses_outputs": ["head"]},
                    ]
                )
            )
        message = str(caught.value)
        assert "network distance in m" in message
        assert "validity lengths" in message

    def test_both_normalised_they_add(self) -> None:
        cfg = CalibrationConfig.model_validate(
            self._config(
                [
                    {
                        "name": "network",
                        "metric": "distance_gap",
                        "uses_outputs": ["net"],
                        "normalize_cost": True,
                    },
                    {
                        "name": "heads",
                        "metric": "rmse",
                        "uses_outputs": ["head"],
                        "normalize_cost": True,
                    },
                ]
            )
        )
        assert len(cfg.objective_blocks) == 2


class TestTheIntervalOfANormalisedDistance:
    """A distance counted in validity lengths is no longer read in mesh cells."""

    def _config(self, *, normalise: bool) -> CalibrationConfig:
        return CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
                "outputs": {"net": {"support": "network", "map": {"complete": "n.gpkg"}}},
                "objective_blocks": [
                    {
                        "name": "network",
                        "metric": "distance_gap",
                        "uses_outputs": ["net"],
                        "normalize_cost": normalise,
                    }
                ],
            }
        )

    def test_a_gap_in_metres_is_read_in_mesh_cells(self) -> None:
        width = self._config(normalise=False).interval_width_for()
        assert width.on_distances is True
        assert width.kind == "absolute"

    def test_a_normalised_gap_is_read_as_any_other_cost(self) -> None:
        width = self._config(normalise=True).interval_width_for()
        assert width.on_distances is False
        assert width.kind == "relative"


# From test_a_session_window_open_at_its_end_scores_the_periods_of_the_run.py
# A session window with a start only scores the periods the run scores.
#
# A protocol phase declares ``window = {start = ...}`` without an end.
# The session compared that start with the END stamp of each pair, so it kept
# the period closing on the start day as well: 25 months against the 24 the run
# scores on example 04 (N1 of the audit of 2026-10-20, RAPPORT §1.3). The
# session now reads the window as the run does, whether the cost is written as
# blocks or as ``variable`` + ``objective``.


FIRST_PERIOD = pd.Timestamp("2000-01-01")
STAMPS = pd.date_range("2000-02-01", "2003-01-01", freq="MS")
START_ONLY = (pd.Timestamp("2001-01-01"), None)


def _series() -> tuple[pd.Series, pd.Series]:
    days = pd.date_range(FIRST_PERIOD, STAMPS[-1] - pd.Timedelta(1, unit="D"), freq="D")
    t = np.arange(days.size, dtype=float)
    observed = pd.Series(1.0 + 0.5 * np.cos(2.0 * np.pi * t / 365.25), index=days)
    simulated = pd.Series(1.0 + 0.4 * np.cos(np.arange(STAMPS.size) / 2.0), index=STAMPS)
    return observed, simulated


def test_the_block_route_keeps_the_24_months_of_the_run() -> None:
    observed, simulated = _series()

    paired = pair_outputs_with_observations(
        observed={"hydrograph": observed},
        simulated={"hydrograph": simulated},
        window=START_ONLY,
        time_methods={"hydrograph": "mean"},
        period_starts={"hydrograph": FIRST_PERIOD},
    )

    assert paired.n_paired["hydrograph"] == 24
    # The first period scored is January 2001, which closes on 1 February.
    assert paired.dates["hydrograph"] == (pd.Timestamp("2001-02-01"), pd.Timestamp("2003-01-01"))


def test_variable_and_objective_keep_the_24_months_of_the_run() -> None:
    observed, simulated = _series()
    sink = TrialSeriesSink()
    scorer = StationBlockScorer(
        "discharge",
        "nse",
        [ObservedSeries("NANCON", "discharge", observed)],
        window=START_ONLY,
        series_sink=sink,
    )

    scorer.score(
        {"NANCON": ObservableResult("NANCON", simulated.to_numpy(), "m3/s", STAMPS)},
        boundaries=[FIRST_PERIOD, *STAMPS],
    )

    times = [pd.Timestamp(row["time"]) for row in sink.drain()]
    assert len(times) == 24
    assert times[0] == pd.Timestamp("2001-02-01")


def test_the_pairs_session_json_records_are_those_of_the_run() -> None:
    # session.json -> scored is read from these components.
    observed, simulated = _series()
    outputs = {
        "q": validate_calib_output(
            dict(variable="discharge", support="boundary", boundary_id="outlet", observes="gauge")
        )
    }
    blocks = [objective_block("flow", "nse", ["q"])]
    scorer = ObservableScorer(outputs, blocks, observed_records={"q": observed}, window=START_ONLY)
    boundaries = [FIRST_PERIOD, *STAMPS]

    _, components = scorer.score(
        {"q": ObservableResult("q", simulated.to_numpy(), "m3/s", STAMPS)}, boundaries=boundaries
    )

    assert components["q.n_paired"] == 24.0
    assert date.fromordinal(int(components["q.date_start"])) == date(2001, 2, 1)
    assert date.fromordinal(int(components["q.date_end"])) == date(2003, 1, 1)


# From test_a_steady_stage_is_scored_on_its_window.py
# A steady stage is scored on the window its one stamp closes.
#
# A steady run has one stress period, stamped at its end. That stamp alone does
# not say where the period starts, so the scorer takes the start from the run's
# time grid. Without it the stage was scored against the last day of its
# window, one day standing for a whole steady year.


# 1999 is worth 1.0 a day, 2000 is worth 3.0, 2001 is worth 5.0.
_DAYS = pd.date_range("1999-01-01", "2001-12-31", freq="D")
_RECORD__steady_stage = pd.Series(
    np.select([_DAYS.year == 1999, _DAYS.year == 2000], [1.0, 3.0], default=5.0), index=_DAYS
)

# One steady period over 2000, stamped at its end.
_BOUNDS__steady_stage = (pd.Timestamp("2000-01-01"), pd.Timestamp("2001-01-01"))
_STAMP = pd.DatetimeIndex([_BOUNDS__steady_stage[1]])


def _answer__steady_stage(value: float) -> ObservableResult:
    return adapter_result("Q", np.asarray([value]), "m3 s-1", times=_STAMP)


def test_variable_and_objective_score_a_steady_discharge_on_its_year() -> None:
    scorer = StationBlockScorer(
        "discharge",
        "mae",
        [ObservedSeries("Q", "discharge", _RECORD__steady_stage)],
        gauge="Q",
    )

    cost, _ = scorer.score({"Q": _answer__steady_stage(3.0)}, boundaries=_BOUNDS__steady_stage)

    # The year 2000 averages 3.0 exactly. The last day before the stamp is
    # also 3.0 here, so the start has to be checked on a stage it changes.
    assert cost == pytest.approx(0.0)


def test_the_window_start_moves_the_score_of_a_steady_stage() -> None:
    scorer = StationBlockScorer(
        "discharge",
        "mae",
        [ObservedSeries("Q", "discharge", _RECORD__steady_stage)],
        gauge="Q",
    )
    spanning = (pd.Timestamp("1999-01-01"), _BOUNDS__steady_stage[1])

    cost, _ = scorer.score({"Q": _answer__steady_stage(3.0)}, boundaries=spanning)

    # Two years, 1999 at 1.0 and 2000 at 3.0: (365 * 1 + 366 * 3) / 731.
    assert cost == pytest.approx(abs(3.0 - (365 * 1.0 + 366 * 3.0) / 731))


def test_the_weighted_route_takes_the_same_start_from_the_grid() -> None:
    outputs = {"Q": boundary_output(observes="gauge")}
    blocks = [objective_block("flow", "mae", ["Q"])]
    scorer = ObservableScorer(outputs, blocks, observed_records={"Q": _RECORD__steady_stage})
    grid = SimpleNamespace(
        setup=SimpleNamespace(time_grid=SimpleNamespace(boundaries=_BOUNDS__steady_stage))
    )

    with_grid, _ = scorer.score(
        {"Q": _answer__steady_stage(3.0)}, boundaries=time_grid_boundaries(grid)
    )
    without, _ = scorer.score({"Q": _answer__steady_stage(3.0)})

    assert with_grid == pytest.approx(0.0)
    # No grid: the whole record, (365 + 366 * 3 + 365 * 5) / 1096.
    assert without == pytest.approx(abs(3.0 - (365 * 1.0 + 366 * 3.0 + 365 * 5.0) / 1096))


def test_a_steady_head_is_still_read_at_its_stamp() -> None:
    # A head is the state at the stamp: the grid start does not widen it.
    scorer = StationBlockScorer("head", "mae", [ObservedSeries("P", "head", _RECORD__steady_stage)])

    cost, _ = scorer.score({"P": _answer__steady_stage(5.0)}, boundaries=_BOUNDS__steady_stage)

    # The reading AT 2001-01-01 is 5.0; the mean of 2000 would be 3.0.
    assert cost == pytest.approx(0.0)


# From test_a_window_holds_the_network_state_it_scores.py
# A scoring window beside a network output read in one state.
#
# That output is dated at the stamp of the state it reads, the stamp that closes
# its period. A window that holds the stamp scores it; one that does not is
# refused, naming both, at the first trial and by ``hmp config check``
# before any solve. So ``window.start`` is the one way to leave a spin-up
# out of a composite that scores a hydrograph and a network together.


MONTHS = tuple(pd.date_range("2000-01-01", periods=37, freq="MS"))
BLOCKS = [objective_block("network", "distance_gap", ["net"])]


def _network(time: str = "last") -> dict[str, object]:
    return {
        "net": validate_calib_output(
            {"support": "network", "map": {"complete": "n.gpkg"}, "time": time}
        )
    }


class TestTheRule:
    def test_before_the_grid_is_known_the_state_counts_as_dated(self) -> None:
        refuse_window_without_dates(_network(), BLOCKS, (pd.Timestamp("2001-01-01"), None), {})

    def test_a_window_holding_the_stamp_is_accepted(self) -> None:
        refuse_window_without_dates(
            _network(), BLOCKS, (pd.Timestamp("2001-01-01"), None), {}, boundaries=MONTHS
        )

    def test_a_window_ending_before_the_last_state_is_refused_naming_both(self) -> None:
        window = (pd.Timestamp("2001-01-01"), pd.Timestamp("2002-06-30"))
        with pytest.raises(ValueError) as caught:
            refuse_window_without_dates(_network(), BLOCKS, window, {}, boundaries=MONTHS)
        message = str(caught.value)
        assert "window 2001-01-01 to 2002-06-30" in message
        assert "time = 'last'" in message
        assert "2002-12" in message and "stamped 2003-01-01" in message

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
    def test_a_date_outside_the_window_is_refused(self, time, match) -> None:
        with pytest.raises(ValueError, match=match):
            refuse_window_without_dates(
                _network(time),
                BLOCKS,
                (pd.Timestamp("2001-01-01"), None),
                {},
                boundaries=MONTHS,
            )

    def test_a_typed_vector_still_has_no_date_to_cut(self) -> None:
        outputs = {"q": boundary_output(observed_values=[1.0, 2.0])}
        blocks = [objective_block("flows", "rmse", ["q"])]
        with pytest.raises(ValueError, match="no time axis to cut on"):
            refuse_window_without_dates(outputs, blocks, (pd.Timestamp("2001-01-01"), None), {})


_PHASE = """
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


def _window_findings(tmp_path, *, time: str, window: str, regime: str = "transient") -> str:
    geometry = tmp_path / "streams.gpkg"
    geometry.write_bytes(b"map")
    findings = preflight_of(
        tmp_path, _PHASE.format(geometry=geometry, time=time, window=window, regime=regime)
    )
    return messages(item for item in findings if "window" in item.detail or "time =" in item.detail)


_FROM_JULY = '[calibration.phases.window]\nstart = "2000-07-01"'
_TO_JUNE = '[calibration.phases.window]\nend = "2000-06-30"'

# The steady span is a day count: a unitless timedelta warns under the pinned NumPy.
_NO_GENERIC_UNIT = pytest.mark.filterwarnings(
    "error:The 'generic' unit for NumPy timedelta:DeprecationWarning"
)


class TestTheCheckBeforeTheRun:
    """The project runs 2000 at a daily step: the last state is stamped 2001-01-01."""

    def test_a_window_holding_the_last_state_is_no_finding(self, tmp_path) -> None:
        assert _window_findings(tmp_path, time="last", window=_FROM_JULY) == ""

    def test_a_window_ending_before_it_is_named_with_its_phase(self, tmp_path) -> None:
        found = _window_findings(tmp_path, time="last", window=_TO_JUNE)
        assert "[[calibration.phases]] 'conductivity'" in found
        assert "window open to 2000-06-30" in found
        assert "stamped 2001-01-01" in found

    def test_a_dated_state_outside_the_window_is_named(self, tmp_path) -> None:
        found = _window_findings(tmp_path, time="2000-03-15", window=_FROM_JULY)
        assert "stamped 2000-03-15" in found

    def test_a_date_the_run_does_not_hold_is_named_without_a_window(self, tmp_path) -> None:
        found = _window_findings(tmp_path, time="2005-03-15", window="")
        assert "[calibration.outputs.net]" in found
        assert "outside the record" in found

    @_NO_GENERIC_UNIT
    def test_a_steady_phase_holds_every_date_of_its_window(self, tmp_path) -> None:
        found = _window_findings(tmp_path, time="2000-03-15", window="", regime="steady")
        assert found == ""

    @_NO_GENERIC_UNIT
    def test_a_steady_state_is_stamped_at_the_end_of_its_window(self, tmp_path) -> None:
        found = _window_findings(tmp_path, time="2000-03-15", window=_TO_JUNE, regime="steady")
        assert "stamped 2001-01-01" in found


class TestTheWindowIsWrittenInDates:
    @pytest.mark.parametrize(
        ("window", "match"),
        [
            pytest.param({"window": {"start": "2001-13-01"}}, "is not a date", id="bad-date"),
            pytest.param(
                {"steady_window": {"start": "2000-01-01"}}, "missing end", id="steady-span"
            ),
            pytest.param({"window": {"begin": "2001-01-01"}}, "begin", id="unknown-bound"),
        ],
    )
    def test_a_protocol_window_that_is_not_dates_fails_when_the_file_is_read(
        self, window, match
    ) -> None:
        with pytest.raises(ValueError, match=match):
            MatchingHydrographicNetworkOptions.model_validate(
                {"name": "matching_hydrographic_network", **window}
            )

    def test_a_protocol_window_is_read_as_the_window_of_the_section(self) -> None:
        declared = MatchingHydrographicNetworkOptions.model_validate(
            {"name": "matching_hydrographic_network", "window": {"start": "2001-01-01"}}
        )
        assert declared.window == CalibWindow(start="2001-01-01")


# From test_discharge_target_station.py
# A run has one simulated discharge series, so one station is the target.


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
    assert "[site] gauge" in message
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


# From test_min_samples_holds_on_every_scored_support.py
# ``[calibration.aggregate] min_samples`` holds on every output that is scored against a record.
#
# Since the single route, a point, a cell, a boundary, a lake and the implicit
# output of ``variable`` + ``objective`` are all paired by the same function, so
# the same floor applies to each. An output scored on fewer pairs than the floor
# is refused by name; on as many, it is scored. The default floor stays 1.


_RECORD_DAYS__min_samples = pd.date_range("2000-01-01", "2000-03-31", freq="D")
_RECORD__min_samples = pd.Series(
    np.linspace(1.0, 2.0, len(_RECORD_DAYS__min_samples)), index=_RECORD_DAYS__min_samples
)
_STAMPS__min_samples = pd.date_range("2000-01-02", periods=6, freq="D")
_BOUNDS__min_samples = (pd.Timestamp("2000-01-01"), *_STAMPS__min_samples)

SUPPORTS: dict[str, dict[str, Any]] = {
    "point": {"variable": "head", "support": "point"},
    "cell": {"variable": "discharge", "support": "cell", "row": 0, "col": 0, "layer": 0},
    "boundary": {"variable": "discharge", "support": "boundary", "boundary_id": "outlet"},
    "lake": {"variable": "stage", "support": "lake", "lake_id": "L1"},
}


def _answer__min_samples(name: str) -> ObservableResult:
    return adapter_result(
        name, np.linspace(1.0, 1.1, len(_STAMPS__min_samples)), "-", times=_STAMPS__min_samples
    )


def _scorer__min_samples(support: str, min_samples: int) -> ObservableScorer:
    outputs = {"Y": validate_calib_output({**SUPPORTS[support], "observes": "G"})}
    blocks = [objective_block("fit", "rmse", ["Y"])]
    return ObservableScorer(
        outputs, blocks, observed_records={"Y": _RECORD__min_samples}, min_samples=min_samples
    )


def test_the_default_floor_is_one_pair() -> None:
    assert CalibAggregateDecl().min_samples == 1


@pytest.mark.parametrize("support", sorted(SUPPORTS))
def test_an_output_paired_on_fewer_than_the_floor_is_refused(support: str) -> None:
    scorer = _scorer__min_samples(support, min_samples=len(_STAMPS__min_samples) + 1)

    with pytest.raises(ValueError, match="min_samples"):
        scorer.score({"Y": _answer__min_samples("Y")}, boundaries=_BOUNDS__min_samples)


@pytest.mark.parametrize("support", sorted(SUPPORTS))
def test_an_output_paired_on_the_floor_is_scored(support: str) -> None:
    scorer = _scorer__min_samples(support, min_samples=len(_STAMPS__min_samples))

    cost, components = scorer.score(
        {"Y": _answer__min_samples("Y")}, boundaries=_BOUNDS__min_samples
    )

    assert np.isfinite(cost)
    assert components["Y.n_paired"] == len(_STAMPS__min_samples)


@pytest.mark.parametrize("variable", ["discharge", "head", "lake_level"])
def test_the_implicit_station_output_honours_the_floor(variable: str) -> None:
    record = [ObservedSeries("G", variable, _RECORD__min_samples)]

    refused = StationBlockScorer(
        variable, "rmse", record, gauge="G", min_samples=len(_STAMPS__min_samples) + 1
    )
    with pytest.raises(ValueError, match="min_samples"):
        refused.score({"G": _answer__min_samples("G")}, boundaries=_BOUNDS__min_samples)

    kept = StationBlockScorer(
        variable, "rmse", record, gauge="G", min_samples=len(_STAMPS__min_samples)
    )
    cost, _ = kept.score({"G": _answer__min_samples("G")}, boundaries=_BOUNDS__min_samples)
    assert np.isfinite(cost)


# From test_observable_scoring.py
# The pipeline and a foreign model share composite scoring.


def _wire_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    results: Mapping[str, ObservableResult],
    observed: Mapping[str, pd.Series] | None = None,
) -> None:
    class Adapter:
        def extract_observables(
            self,
            ctx: object,
            store: object,
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

    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda ctx: (Adapter(), None))
    monkeypatch.setattr(solver_extract, "resolve_time_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        composite, "observed_series_for_outputs", lambda outputs, ctx: observed or {}
    )


def test_weighted_positional_outputs_keep_reduction_and_components(
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
    _wire_pipeline(monkeypatch, results)
    pipeline = composite.build_metric_extractor(
        None, None, object(), outputs=outputs, objective_blocks=blocks
    )
    foreign = ObservableScorer(outputs, blocks)

    total, components = foreign.score(results)

    assert total == pytest.approx(3.5)
    assert components["flow.raw_cost"] == pytest.approx(2.0)
    assert components["lake.raw_cost"] == pytest.approx(4.0)
    assert pipeline(object()) == (total, components)


def test_a_dates_window_is_identical_for_both_producers(
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
    _wire_pipeline(monkeypatch, results, observed)
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


def test_network_distances_and_diagnostics_do_not_masquerade_as_a_release_field() -> None:
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


def test_observed_output_without_dates_keeps_the_existing_refusal() -> None:
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
        ("first", [1.0, 102.0, 103.0], 1),
        ("last", [101.0, 102.0, 3.0], 1),
    ],
)
def test_time_selection_matches_a_solver_that_honors_requests(
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
    _wire_pipeline(monkeypatch, results, observed)
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


# From test_station_block_scorer.py
# ``variable`` + ``objective`` is scored without a trial context, by blocks.
#
# The one-line form used to be one function that resolved the flow adapter,
# placed every gauge on the mesh, read its series and scored it. The second half
# is :class:`StationBlockScorer`: one implicit output and one implicit block per
# scored station, handed to the block route. These hold what that is worth: the
# same observables score to the same cost whoever produced them, a model that is
# not the pipeline included.


_INDEX = pd.date_range("2020-01-01", periods=3, freq="D")

# A discharge is the mean of the period its stamp closes, so a gauge day is
# stamped one day before the simulated stamp that closes it.
_DAY_BEFORE_INDEX = pd.date_range("2019-12-31", periods=3, freq="D")


def _observed__station_block(station_id: str, values, variable: str = "head") -> ObservedSeries:
    # A head or a lake level is the state AT the stamp, so its record is read
    # at the stamp instants themselves. Shifting it by a day, as a discharge
    # is, would pair each state with the reading of the day before.
    index = _DAY_BEFORE_INDEX if variable == "discharge" else _INDEX
    return ObservedSeries(
        station_id=station_id,
        variable=variable,
        series=pd.Series(np.asarray(values, dtype=float), index=index[: len(values)]),
    )


def _answer__station_block(station_id: str, values, *, dated: bool = True) -> ObservableResult:
    array = np.asarray(values, dtype=float)
    return adapter_result(station_id, array, "m", times=_INDEX[: array.size] if dated else None)


def _scorer__station_block(variable, *ids, metric="rmse", values=None, **options):
    """A scorer over records that all hold `values`, 10 to 12 for a state and 1 for a flow."""
    if values is None:
        values = [1.0, 1.0, 1.0] if variable == "discharge" else [10.0, 11.0, 12.0]
    kind = "discharge" if variable == "discharge" else "head"
    records = [_observed__station_block(station, values, kind) for station in ids]
    return StationBlockScorer(variable, metric, records, **options)


class TestTheProducersAndTheScorerNameTheSameVariables:
    def test_every_produced_variable_is_a_scored_one(self) -> None:
        """A route one half serves and the other does not is a KeyError at trial time."""
        assert set(PRODUCERS) == set(STATION_VARIABLES)

    def test_a_variable_nothing_observes_is_refused_at_construction(self) -> None:
        with pytest.raises(NotImplementedError, match="is not supported"):
            _scorer__station_block("salinity", "A", values=[1.0, 2.0, 3.0])


class TestScoringWithoutAContext:
    def test_a_head_answer_is_scored_with_no_trial_context_in_sight(self) -> None:
        scorer = _scorer__station_block("head", "PZ1")

        cost, components = scorer.score({"PZ1": _answer__station_block("PZ1", [10.5, 11.5, 12.5])})

        assert cost == pytest.approx(0.5)
        assert components["rmse@PZ1.raw_cost"] == pytest.approx(0.5)
        assert components["head@PZ1.n_paired"] == 3.0

    def test_the_criterion_named_by_the_document_is_the_one_applied(self) -> None:
        """Changing the metric alone moves the number; the answer is untouched."""
        observed = [_observed__station_block("PZ1", [10.0, 11.0, 12.0])]
        answer = {"PZ1": _answer__station_block("PZ1", [10.5, 12.5, 12.5])}

        rmse, _ = StationBlockScorer("head", "rmse", observed).score(answer)
        mae, _ = StationBlockScorer("head", "mae", observed).score(answer)

        assert rmse != pytest.approx(mae)

    def test_several_heads_are_averaged(self) -> None:
        scorer = _scorer__station_block("head", "PZ1", "PZ2")

        cost, components = scorer.score(
            {
                "PZ1": _answer__station_block("PZ1", [10.5, 11.5, 12.5]),
                "PZ2": _answer__station_block("PZ2", [11.5, 12.5, 13.5]),
            }
        )

        assert components["rmse@PZ1.raw_cost"] == pytest.approx(0.5)
        assert components["rmse@PZ2.raw_cost"] == pytest.approx(1.5)
        assert cost == pytest.approx(1.0)


class TestWhichStationDrivesTheSearch:
    def test_the_declared_gauge_alone_is_scored(self) -> None:
        scorer = StationBlockScorer(
            "discharge",
            "rmse",
            [
                _observed__station_block("OUTLET", [1.0, 1.0, 1.0], variable="discharge"),
                _observed__station_block("UP", [1.0, 1.0, 1.0], variable="discharge"),
            ],
            gauge="UP",
        )

        cost, components = scorer.score(
            {
                "OUTLET": _answer__station_block("OUTLET", [9.0, 9.0, 9.0]),
                "UP": _answer__station_block("UP", [2.0, 2.0, 2.0]),
            }
        )

        assert cost == pytest.approx(1.0)
        assert [record.station_id for record in scorer.stations] == ["UP"]
        assert not [key for key in components if "OUTLET" in key]

    def test_a_missing_answer_for_the_followed_gauge_is_refused_by_name(self) -> None:
        scorer = StationBlockScorer(
            "discharge",
            "rmse",
            [
                _observed__station_block("OUTLET", [1.0, 1.0, 1.0], variable="discharge"),
                _observed__station_block("UP", [1.0, 1.0, 1.0], variable="discharge"),
            ],
            gauge="UP",
        )

        with pytest.raises(NotImplementedError, match="'UP'"):
            scorer.score({"OUTLET": _answer__station_block("OUTLET", [9.0, 9.0, 9.0])})

    def test_a_gauge_the_producer_could_not_place_stays_unscored(self) -> None:
        """A piezometer outside the mesh has no counterpart; it is not invented."""
        scorer = _scorer__station_block("head", "PZ1", "NOWHERE")

        cost, components = scorer.score({"PZ1": _answer__station_block("PZ1", [10.5, 11.5, 12.5])})

        assert cost == pytest.approx(0.5)
        assert not [key for key in components if "NOWHERE" in key]

    def test_a_gauge_left_out_is_said_out_loud_once(self, caplog) -> None:
        """A station that vanishes from a report has to leave a line somewhere."""
        scorer = _scorer__station_block("head", "PZ1", "NOWHERE")
        answer = {"PZ1": _answer__station_block("PZ1", [10.5, 11.5, 12.5])}

        with caplog.at_level("WARNING"):
            scorer.score(answer, source="Solver 'modflow6'")
            scorer.score(answer, source="Solver 'modflow6'")

        said = [record for record in caplog.records if "NOWHERE" in record.getMessage()]
        assert len(said) == 1
        assert "head" in said[0].getMessage()

    def test_an_answer_nobody_could_score_says_so(self) -> None:
        scorer = _scorer__station_block("head", "PZ1")

        with pytest.raises(ValueError, match="served no head at any of the stations"):
            scorer.score({})

    def test_an_empty_series_is_refused_and_names_its_source(self) -> None:
        scorer = _scorer__station_block("lake_level", "lac0")

        with pytest.raises(NotImplementedError, match="fake_solver"):
            scorer.score(
                {"lac0": _answer__station_block("lac0", [], dated=False)}, source="fake_solver"
            )


class TestThePipelineTakesTheSameRoute:
    """The extractor scores through the scorer, not beside it."""

    @staticmethod
    def _ctx():
        """A project loading one gauge, and no runoff to add to the budget."""
        frame = pd.DataFrame({"datetime": _DAY_BEFORE_INDEX, "value": [1.0, 1.0, 1.0]})
        record = SimpleNamespace(station_id="OUTLET", variable="discharge", data=frame)
        return SimpleNamespace(
            setup=SimpleNamespace(cell_mesh=None, domain=None, geographic=None, time_grid=None),
            loaded_data=SimpleNamespace(
                hydrometry=SimpleNamespace(points=[record]),
                piezometry=None,
                runoff=None,
            ),
        )

    def _wired(self, monkeypatch):
        served = {"catchment": _answer__station_block("catchment", [2.0, 2.0, 2.0])}
        monkeypatch.setattr(
            "hydromodpy.calibration.metrics.composite.resolve_flow_adapter",
            lambda ctx: (
                FakeAdapter(served),
                SimpleNamespace(run=SimpleNamespace(solver="modflow6"), model=None),
            ),
        )
        ctx = self._ctx()
        return ctx, build_metric_extractor("discharge", "rmse", ctx)

    def test_the_extractor_reports_what_a_bare_scorer_reports(self, monkeypatch) -> None:
        """The discharge route is the one whose producer rewrites its values."""
        ctx, metric_fn = self._wired(monkeypatch)

        through_pipeline = metric_fn(ctx, objective="rmse", variable="discharge")
        bare = StationBlockScorer(
            "discharge", "rmse", [_observed__station_block("OUTLET", [1.0, 1.0, 1.0], "discharge")]
        ).score({"OUTLET": _answer__station_block("OUTLET", [2.0, 2.0, 2.0])})

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
            pytest.param(
                {"objective": "rmse", "variable": "head"}, "variable='head'", id="variable"
            ),
        ],
    )
    def test_a_trial_may_not_rename_what_it_is_scored_on(self, monkeypatch, call, match) -> None:
        """The records, the producer and the followed gauge were all chosen here."""
        ctx, metric_fn = self._wired(monkeypatch)

        with pytest.raises(ValueError, match=match):
            metric_fn(ctx, **call)

    def test_the_refusal_comes_before_anything_is_read(self) -> None:
        """A call naming another route is wrong whatever state the run is in."""
        metric_fn = build_metric_extractor("discharge", "rmse", self._ctx())

        with pytest.raises(ValueError, match="Build a second extractor"):
            metric_fn(SimpleNamespace(), objective="nse", variable="discharge")


class TestTheValidationWindow:
    """A score beside the cost, on the answer of the trial, and the cost never reads it."""

    DAYS = pd.date_range("2000-01-01", periods=6, freq="D")
    RECORD = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0], index=DAYS)
    FIRST, LATER = (DAYS[0], DAYS[2]), (DAYS[3], DAYS[5])
    HEAD = {"variable": "head", "support": "cell", "row": 0, "col": 0, "layer": 0, "observes": "P"}

    def _scorer(self, metric="rmse", record=RECORD, **options) -> ObservableScorer:
        return ObservableScorer(
            {"h": validate_calib_output(self.HEAD)},
            [objective_block("fit", metric, ["h"])],
            observed_records={"h": record},
            window=self.FIRST,
            **options,
        )

    def _answer(self, first: float = 1.0, later: float = 3.0) -> dict[str, ObservableResult]:
        simulated = self.RECORD.to_numpy() + np.array([first] * 3 + [later] * 3)
        return {"h": adapter_result("h", simulated, "m", times=self.DAYS)}

    def test_the_cost_stays_bit_identical_and_never_reads_it(self) -> None:
        sink = TrialSeriesSink()
        scorer = self._scorer(validation_window=self.LATER, series_sink=sink)

        cost, scored = scorer.score(self._answer())
        worse = scorer.score(self._answer(later=5.0))

        assert [row["simulated"] for row in sink.drain()[:3]] == [11.0, 12.0, 13.0]
        assert (cost, worse[0]) == (1.0, 1.0)
        assert worse[1][VALIDATION_COST] == pytest.approx(5.0)
        assert scored.pop(VALIDATION_COST) == pytest.approx(3.0)
        assert (cost, scored) == self._scorer().score(self._answer())

    @pytest.mark.parametrize(
        ("metric", "record", "window", "said"),
        [
            ("rmse", RECORD, (pd.Timestamp("2001-01-01"), pd.Timestamp("2001-12-31")), 1),
            ("nse", RECORD.where(RECORD < 13.0, 13.0), LATER, 0),
        ],
        ids=["no_pair", "undefined_metric"],
    )
    def test_a_trial_with_no_score_on_it_keeps_its_cost(
        self, caplog, metric, record, window, said
    ) -> None:
        scorer = self._scorer(metric, record, validation_window=window)

        with caplog.at_level(logging.WARNING):
            first = scorer.score(self._answer())
            second = scorer.score(self._answer())

        assert first == second == self._scorer(metric, record).score(self._answer())
        assert sum("validation window" in r.getMessage() for r in caplog.records) == said

    def test_only_the_blocks_on_a_dated_record_are_scored_on_it(self) -> None:
        outputs = {"h": validate_calib_output(self.HEAD), **_network()}
        blocks = [
            objective_block("fit", "rmse", ["h"], weight=1.0),
            objective_block("map", "distance_gap", ["net"], weight=3.0),
        ]
        distances = {"net": [100.0, 100.0]}
        options = {"validation_window": self.LATER}
        both = ObservableScorer(outputs, blocks, observed_records={"h": self.RECORD}, **options)
        net = ObservableScorer({"net": outputs["net"]}, blocks[1:], **options)

        assert both.score(self._answer(), network_values=distances)[1][VALIDATION_COST] == 3.0
        assert VALIDATION_COST not in net.score({}, network_values=distances)[1]

    def test_both_routes_of_the_extractor_score_it(self, monkeypatch) -> None:
        _wire_pipeline(monkeypatch, self._answer(), {"h": self.RECORD})
        declared = composite.build_metric_extractor(
            None,
            None,
            object(),
            outputs={"h": validate_calib_output(self.HEAD)},
            objective_blocks=[objective_block("fit", "rmse", ["h"])],
            window=self.FIRST,
            validation_window=self.LATER,
        )
        station = _scorer__station_block("head", "P", validation_window=(_INDEX[2], _INDEX[2]))
        answer = {"P": _answer__station_block("P", [11.0, 12.0, 14.0])}

        assert declared(object())[1][VALIDATION_COST] == pytest.approx(3.0)
        assert station.score(answer)[1][VALIDATION_COST] == pytest.approx(2.0)

    def test_the_evaluator_hands_over_the_window_of_the_document(self, monkeypatch) -> None:
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


class TestWhenTheRefusalHappens:
    """A document no sample can score is refused before a session exists."""

    @staticmethod
    def _two_gauges():
        frame = pd.DataFrame({"datetime": _INDEX, "value": [1.0, 1.0, 1.0]})
        points = [
            SimpleNamespace(station_id=sid, variable="discharge", data=frame)
            for sid in ("OUTLET", "UP")
        ]
        return SimpleNamespace(
            setup=SimpleNamespace(time_grid=None),
            loaded_data=SimpleNamespace(hydrometry=SimpleNamespace(points=points)),
        )

    def test_two_gauges_without_a_declaration_are_refused_at_build_time(self) -> None:
        """Every trial used to fail instead, after a session row had been written."""
        with pytest.raises(ValueError, match="one simulated discharge series"):
            build_metric_extractor("discharge", "rmse", self._two_gauges())

    def test_naming_the_one_that_drives_the_search_builds(self) -> None:
        extractor = build_metric_extractor("discharge", "rmse", self._two_gauges(), gauge="UP")

        assert callable(extractor)


# From test_the_protocol_s_block_route_matches_the_single_metric_one.py
# B11: the protocol's block costs what ``variable`` + ``objective`` costs.
#
# Before B11 the transient stage of ``matching_hydrographic_network`` wrote its
# cost as ``variable`` + ``objective``. After B11 it writes a ``point`` output
# that ``observes`` the gauge and a block. Since m10 the one-line form is itself
# read as an implicit output and block (:class:`StationBlockScorer`), so both
# reach the same :class:`ObservableScorer`, the same alignment and the same
# registered criterion: the same simulated series against the same observed
# record has to cost the same either way.
#
# Measured on a real Nancon run before this test was written: bit-identical,
# 0.07916512462058523 both ways (example 04, session
# 20260923-142058-scipy_nelder_mead-42cbb8b8, trial 4, K and Sy frozen at its
# values). This pins the same property on a synthetic series, deterministically
# and without a solver.


STATION = "NANCON"
TIMES = pd.date_range("2001-01-31", periods=24, freq="ME")
BOUNDARIES = period_edges(TIMES, start=pd.Timestamp("2000-12-31"))
OBSERVED = pd.Series(np.linspace(0.2, 5.0, 24), index=TIMES, name=STATION)
SIMULATED = (OBSERVED * 0.8 + 0.1).to_numpy()


def test_the_block_route_and_the_single_metric_route_cost_the_same() -> None:
    single = StationBlockScorer(
        "discharge",
        "nse_log",
        [ObservedSeries(station_id=STATION, variable="discharge", series=OBSERVED)],
    )
    single_cost, single_components = single.score(
        {STATION: adapter_result(STATION, SIMULATED, "m3 s-1", times=TIMES)},
        boundaries=BOUNDARIES,
    )

    output = CalibOutputPoint.model_validate(
        {"variable": "discharge", "support": "point", "observes": STATION}
    )
    block = objective_block("hydrograph", "nse_log", ["gauge"])
    composite = ObservableScorer({"gauge": output}, [block], observed_records={"gauge": OBSERVED})
    block_cost, block_components = composite.score(
        {"gauge": adapter_result("gauge", SIMULATED, "m3 s-1", times=TIMES)},
        boundaries=BOUNDARIES,
    )

    assert block_cost == single_cost
    assert single_components[f"nse_log@{STATION}.raw_cost"] == single_cost
    assert block_components["hydrograph.raw_cost"] == single_cost
    # One edge sample does not close a period on this boundary set; both
    # routes read the same alignment function and agree on how many do.
    assert block_components["gauge.n_paired"] == 23.0
