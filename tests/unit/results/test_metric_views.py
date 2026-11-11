"""Tests of metric views."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from hydromodpy.calibration.criteria.series import METRICS, SeriesCriterion
from hydromodpy.calibration.criteria.series import METRICS as CALIBRATION_METRICS
from hydromodpy.cli.commands.catalog import rank
from hydromodpy.cli.helpers import EXIT_VALIDATION, exit_code_for
from hydromodpy.core.budget.flux import STREAM_CONSTANT_HEAD_BUDGET
from hydromodpy.core.budget.terms import BudgetKeep, budget_terms_for
from hydromodpy.core.exceptions import DataError
from hydromodpy.core.scoring import metrics as core
from hydromodpy.core.scoring.metric_table import METRIC_SENSE, RUN_METRIC_NAMES
from hydromodpy.model.sinks_sources.wells import (
    WELLS_PUMPED_CHECK,
    WELLS_PUMPED_METRIC,
    pumped_percent,
)
from hydromodpy.project.accessors import ProjectRunsAccessor
from hydromodpy.results import field_registry
from hydromodpy.results.catalog import Catalog, SimulationNotFoundError
from hydromodpy.results.catalog.constants import (
    RETIRED_METRIC_NAMES,
    UnrankedMetricError,
    cost_of,
    metric_rank_sql,
    score_of,
)
from hydromodpy.results.catalog.facade import compare_pair
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.catalog.listing import rank_simulations
from hydromodpy.results.derive.config_flags import diagnose_missing, missing_field_explanation
from hydromodpy.results.derive.virtual_fields import (
    VIRTUAL_FIELDS,
    available_virtual_fields,
    field_descriptor,
    read_field_or_virtual,
    read_field_range_or_virtual,
)
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.metric_rule import (
    HEADLINE_WINDOW,
    METRIC_RULE_VERSION,
    DateWindow,
    MetricRule,
)
from hydromodpy.results.record.manifest import MetricRow, ParameterRow
from hydromodpy.results.run import Run, ranking
from hydromodpy.results.run.sealed import MixedWindowsError, metrics_frame
from hydromodpy.results.score import score_metric, score_timeseries
from hydromodpy.results.storage.parquet_schemas import primary_key_for
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter
from hydromodpy.solver.modflow_common.budget_components import (
    CANONICAL_BUDGET_TERMS,
    canonical_budget_component,
)
from hydromodpy.workflow.steps.run_outputs import record_run_execution_metrics
from tests._helpers.metric_rows import headline_row, headline_score
from tests._helpers.run_stores import open_run_store
from tests._helpers.sealed_runs import make_project, seal_run
from validation_cases.calibration.recession_hillslope_aquifer import experiment as case

# The search minimizes a cost; an efficiency is one minus it. That flip was
# written by hand in the criteria, the single-metric route, the scalar
# objective, two cases and the figures, and the figures kept their own list of
# efficiencies. ``cost_of`` and ``score_of`` sit beside ``METRIC_SENSE`` and are
# the one place that says it.
pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "metric", sorted(name for name, sense in METRIC_SENSE.items() if sense in ("max", "min"))
)
def test_a_score_comes_back_from_its_cost(metric: str) -> None:
    assert score_of(metric, cost_of(metric, 0.25)) == pytest.approx(0.25)


def test_an_efficiency_costs_one_minus_its_score_and_an_error_costs_itself() -> None:
    assert cost_of("nse_log", 0.9) == pytest.approx(0.1)
    assert cost_of("rmse", 0.9) == pytest.approx(0.9)
    assert np.allclose(score_of("kge", np.array([0.1, 0.4])), [0.9, 0.6])


@pytest.mark.parametrize("metric", ["bias", "kge_alpha"])
def test_a_metric_best_at_a_target_has_no_cost_form(metric: str) -> None:
    with pytest.raises(UnrankedMetricError, match=metric):
        cost_of(metric, 0.1)


@pytest.mark.parametrize("metric", sorted(set(METRICS) - {"distance_gap", "distance_mean"}))
def test_every_series_criterion_costs_what_the_table_says(metric: str) -> None:
    rng = np.random.default_rng(3)
    obs = 1.0 + rng.random(730)
    sim = obs * (1.0 + 0.1 * rng.standard_normal(730))
    criterion = SeriesCriterion(metric, METRICS[metric])
    result = criterion.score(np.abs(sim), obs)
    assert result.cost == pytest.approx(cost_of(metric, result.diagnostics["score"]))


def test_the_figures_keep_no_list_of_efficiencies_of_their_own() -> None:
    from hydromodpy.display.figures import _calibration_session

    assert not hasattr(_calibration_session, "EFFICIENCIES")
    for metric in _calibration_session.METRIC_LABELS:
        assert metric in METRIC_SENSE


# They pivoted on (metric, station), so the discharge and the level of one station
# merged into one row, and nothing said on which window or how many samples each
# side was scored.
STATION = "J0014010"


def _row(variable: str, value: float, start: date, n: int) -> MetricRow:
    window = DateWindow(start=start, end=date(2020, 12, 31))
    return headline_row(
        "nse", value, station=STATION, variable=variable, window=window, n_samples=n
    )


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "p"
    scores = {
        "a": [
            _row("discharge", 0.6, date(2016, 1, 1), 1827),
            _row("level", 0.2, date(2016, 1, 1), 1827),
        ],
        "b": [
            _row("discharge", 0.7, date(2018, 1, 1), 1096),
            _row("level", 0.9, date(2016, 1, 1), 1827),
        ],
    }
    for name, rows in scores.items():
        store = open_run_store(root, name, create_zarr=False)
        for row in rows:
            store.facts.put_metric(row)
        seal_completed(store)
    rebuild_index(root)
    return root


def test_the_diff_keeps_each_variable_of_a_station(project) -> None:
    with Catalog(project) as cat:
        delta = cat.diff("a", "b")["metrics"]
    assert {key[:3] for key in delta} == {
        ("nse", STATION, "discharge"),
        ("nse", STATION, "level"),
    }


def test_the_diff_shows_the_window_and_the_samples_of_each_side(project) -> None:
    with Catalog(project) as cat:
        delta = cat.diff("a", "b")["metrics"]
    side_a, side_b = delta[("nse", STATION, "discharge")]
    assert (side_a["value"], side_a["n"], side_a["window_start"]) == (0.6, 1827, date(2016, 1, 1))
    assert (side_b["value"], side_b["n"], side_b["window_start"]) == (0.7, 1096, date(2018, 1, 1))


def test_compare_pair_has_one_row_per_variable_with_its_window(project) -> None:
    frame = compare_pair("a", "b", workspace=project).reset_index()
    assert sorted(frame["variable"]) == ["discharge", "level"]
    discharge = frame[frame["variable"] == "discharge"].iloc[0]
    assert (discharge["A"], discharge["B"]) == (0.6, 0.7)
    assert (discharge["A_n"], discharge["B_n"]) == (1827, 1096)
    assert discharge["A_window"] == "2016-01-01/2020-12-31"
    assert discharge["B_window"] == "2018-01-01/2020-12-31"


def test_compare_pair_gives_the_scores_the_diff_gives(project) -> None:
    frame = compare_pair("a", "b", workspace=project)
    with Catalog(project) as cat:
        delta = cat.diff("a", "b")["metrics"]
    for (metric, station, variable), (side_a, side_b) in delta.items():
        row = frame.loc[(metric, station, variable)]
        assert (row["A"], row["B"]) == (side_a["value"], side_b["value"])
        assert (row["A_n"], row["B_n"]) == (side_a["n"], side_b["n"])


def test_compare_pair_needs_a_project(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="is not a project directory"):
        compare_pair("a", "b", workspace=tmp_path)


def _run_diff(project, capsys, fmt: str) -> str:
    import argparse

    from hydromodpy.cli.commands.catalog import diff

    args = argparse.Namespace(
        ref_a="a", ref_b="b", workspace=str(project), format=fmt, verbose=0, quiet=False
    )
    diff.run(args)
    return capsys.readouterr().out


def test_the_cli_prints_each_variable_with_its_window(project, capsys) -> None:
    text = _run_diff(project, capsys, "table")
    assert f"nse@{STATION}/discharge: 0.6 [2016-01-01/2020-12-31, n=1827]" in text
    assert "0.7 [2018-01-01/2020-12-31, n=1096]" in text
    assert f"nse@{STATION}/level" in text


def test_the_cli_json_rows_carry_station_variable_and_windows(project, capsys) -> None:
    import json

    rows = json.loads(_run_diff(project, capsys, "json"))["data"]["metrics"]
    discharge = next(row for row in rows if row["variable"] == "discharge")
    assert discharge["station"] == STATION
    assert discharge["a"]["n"] == 1827
    assert discharge["b"]["window"] == "2018-01-01/2020-12-31"


# A run scored on a head whose cell went dry is scored on fewer periods than
# the window holds, and the rows said only ``n_samples``. Each row now says how
# many periods of the window it lost to a NaN simulated value (``n_sim_nan``),
# in the seal, in ``metrics.parquet`` and in the ``metrics`` table of the index,
# and the scoring warns. A period the record leaves empty is not counted.
PIEZOMETER = "P1"


WINDOW = DateWindow(start=date(2001, 1, 5), end=date(2001, 1, 31))


RULE = MetricRule(station=PIEZOMETER, window=WINDOW)


STAMPS = pd.date_range("2001-01-02", "2001-02-01", freq="D", tz="UTC")


DRY = pd.DatetimeIndex(["2001-01-03", "2001-01-11", "2001-01-16", "2001-01-21"], tz="UTC")


def _frame(dry: pd.DatetimeIndex) -> pd.DataFrame:
    simulated = pd.Series(np.linspace(10.0, 11.0, len(STAMPS)), index=STAMPS)
    simulated[dry] = np.nan
    days = pd.date_range("2000-12-01", "2001-02-28", freq="D", tz="UTC")
    observed = pd.Series(np.linspace(10.0, 12.0, len(days)), index=days).drop(
        pd.Timestamp("2001-01-25", tz="UTC")
    )
    rows = [
        {"station_id": PIEZOMETER, "variable": "head", "source": "simulated", "time": t, "value": v}
        for t, v in simulated.items()
    ] + [
        {"station_id": PIEZOMETER, "variable": "head", "source": "observed", "time": t, "value": v}
        for t, v in observed.items()
    ]
    return pd.DataFrame(rows)


def test_every_row_counts_the_dry_periods_of_the_window(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy.results.score"):
        scores = score_timeseries(_frame(DRY), rule=RULE)

    assert scores.rows
    assert {row.n_sim_nan for row in scores.rows} == {3}
    warned = [r.getMessage() for r in caplog.records]
    assert any("NaN" in message and PIEZOMETER in message for message in warned)


def test_a_wet_run_counts_zero_and_does_not_warn(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy.results.score"):
        scores = score_timeseries(_frame(DRY[:0]), rule=RULE)

    assert {row.n_sim_nan for row in scores.rows} == {0}
    assert not [r for r in caplog.records if "NaN" in r.getMessage()]


def test_the_store_the_seal_and_the_index_keep_n_sim_nan(tmp_path) -> None:
    root = tmp_path / "p"
    store = open_run_store(root, "a", create_zarr=False)
    for metric, value in (("nse", 0.5), ("rmse", 0.1)):
        store.write_metric(
            store.sim_id,
            headline_row(
                metric, value, station=PIEZOMETER, variable="head", window=WINDOW, n_sim_nan=3
            ),
        )
    table = pq.read_table(store.table_path_for(store.sim_id, "metrics")).to_pandas()
    assert table["n_sim_nan"].tolist() == [3, 3]
    record = seal_completed(store)
    assert metrics_frame(record)["n_sim_nan"].tolist() == [3, 3]
    rebuild_index(root)

    with Catalog(root) as cat:
        frame = cat.sql("SELECT metric, n_sim_nan FROM metrics ORDER BY metric")

    assert frame.set_index("metric")["n_sim_nan"].to_dict() == {"nse": 3, "rmse": 3}


# A retired spelling (``log_nse_gt``) or a typo used to join no row and return an
# empty ``RunSet``, which reads as "no run is that good". It is now refused with
# the known names, the retired spelling with the name to write.
@pytest.fixture
def cat(tmp_path):
    project = tmp_path / "p"
    store = open_run_store(project, "a", create_zarr=False)
    for metric, value in {"nse": 0.8, "nse_log": 0.7}.items():
        store.facts.put_metric(headline_row(metric, value))
    store.facts.score = headline_score(0.8)
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog


def test_a_known_metric_filters(cat) -> None:
    assert len(cat.find(nse_gt=0.5)) == 1
    assert len(cat.find(nse_log_gte=0.9)) == 0


def test_a_retired_spelling_is_refused_with_the_name_to_write(cat) -> None:
    with pytest.raises(ValueError, match="write 'nse_log'"):
        cat.find(log_nse_gt=0.5)


def test_a_typo_is_refused_with_the_known_names(cat) -> None:
    with pytest.raises(ValueError, match="nse_lgo") as raised:
        cat.find(nse_lgo_gt=0.5)
    assert "kge_alpha" in str(raised.value)


# A discharge reconstructed below a dam can hold a few negative values. The
# calibration clipped them and counted them, the run score returned ``None``, the
# core kernel raised and the Brutsaert case returned NaN (N10 of the audit of
# 2026-10-20, decision m12). Now the run and the calibration clip alike, and the
# run writes ``n_clipped`` on the row of ``nse_log``: 0 when nothing was clipped,
# ``None`` on a metric that never clips.
WINDOW_2 = DateWindow(start=date(2001, 1, 1), end=date(2001, 1, 10))


RULE_2 = MetricRule(station="S", window=WINDOW_2)


DAYS = pd.date_range("2001-01-01", periods=10, freq="D")


OBSERVED = pd.Series([4.0, 3.5, 3.0, 2.6, 2.2, 1.9, 1.6, 1.4, 1.2, 1.0], index=DAYS)


CLEAN = OBSERVED * np.array([1.1, 0.9, 1.05, 0.95, 1.2, 0.85, 1.1, 0.9, 1.3, 0.8])


BELOW_ZERO = CLEAN.copy()


BELOW_ZERO.iloc[3] = -0.4


BELOW_ZERO.iloc[7] = -0.1


def test_the_core_kernel_clips_instead_of_raising() -> None:
    expected = core.log_nse(np.clip(BELOW_ZERO.to_numpy(), 0.0, None), OBSERVED.to_numpy())

    assert core.log_nse(BELOW_ZERO.to_numpy(), OBSERVED.to_numpy()) == pytest.approx(expected)


def test_the_run_scores_a_negative_value_and_counts_the_clipping() -> None:
    result = score_metric(BELOW_ZERO, OBSERVED, RULE_2, "nse_log")

    assert result.value is not None
    assert np.isfinite(result.value)
    assert result.n_clipped == 2


def test_a_clipping_on_the_observed_side_counts_too() -> None:
    observed = OBSERVED.copy()
    observed.iloc[0] = -2.0

    assert score_metric(CLEAN, observed, RULE_2, "nse_log").n_clipped == 1


def test_a_clean_series_writes_zero_on_nse_log_and_none_elsewhere() -> None:
    assert score_metric(CLEAN, OBSERVED, RULE_2, "nse_log").n_clipped == 0
    assert score_metric(BELOW_ZERO, OBSERVED, RULE_2, "nse").n_clipped is None
    assert score_metric(BELOW_ZERO, OBSERVED, RULE_2, "rmse").n_clipped is None


def test_the_run_score_is_the_calibration_score_on_the_same_pairs() -> None:
    from_run = score_metric(BELOW_ZERO, OBSERVED, RULE_2, "nse_log")
    from_calibration = SeriesCriterion("nse_log", core.log_nse).score(
        BELOW_ZERO.to_numpy(), OBSERVED.to_numpy()
    )

    assert from_run.value == pytest.approx(from_calibration.diagnostics["score"], abs=1e-15)
    assert from_run.n_clipped == int(from_calibration.diagnostics["n_clipped"])


def test_the_row_of_a_run_carries_n_clipped() -> None:
    def rows(values: pd.Series) -> list[dict]:
        sim = [
            {
                "station_id": "S",
                "variable": "discharge",
                "source": "simulated",
                "time": t + pd.Timedelta(1, unit="D"),
                "value": v,
            }
            for t, v in zip(DAYS.tz_localize("UTC"), values, strict=True)
        ]
        obs = [
            {
                "station_id": "S",
                "variable": "discharge",
                "source": "observed",
                "time": t,
                "value": v,
            }
            for t, v in zip(DAYS.tz_localize("UTC"), OBSERVED, strict=True)
        ]
        return sim + obs

    scores = score_timeseries(pd.DataFrame(rows(BELOW_ZERO)), rule=RULE_2)

    by_metric = {row.metric: row for row in scores.rows}
    assert by_metric["nse_log"].n_clipped == 2
    assert by_metric["nse_log"].value is not None
    assert by_metric["nse"].n_clipped is None


def test_the_brutsaert_case_follows_the_same_rule() -> None:
    bundle = case._compute_metrics(OBSERVED.to_numpy(), BELOW_ZERO.to_numpy())

    assert bundle["NSElog"] == pytest.approx(
        core.log_nse(BELOW_ZERO.to_numpy(), OBSERVED.to_numpy())
    )
    assert np.isfinite(bundle["NSElog"])


def test_the_store_the_seal_and_the_index_keep_n_clipped(tmp_path) -> None:
    root = tmp_path / "p"
    store = open_run_store(root, "a", create_zarr=False)
    store.write_metric(
        store.sim_id,
        headline_row("nse_log", 0.5, station="S", window=WINDOW_2, n_clipped=2),
    )
    store.facts.score = headline_score(0.5, station="S", window=WINDOW_2)
    seal_completed(store)
    rebuild_index(root)

    with Catalog(root) as cat:
        frame = cat.sql("SELECT metric, n_clipped FROM metrics")

    assert frame.set_index("metric")["n_clipped"].to_dict() == {"nse_log": 2}


# Under the ``"consumers"`` policy a field is available only when every term it
# reads is declared kept. A term declared with no array is a term the model does
# not produce, which is fine. Under ``"all"`` nothing changes.
N_STEPS = 4


N_CELLS = 3


@pytest.fixture
def project_2(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


@contextmanager
def _sealed(
    project_2: Path, keep: BudgetKeep | None, written: tuple[str, ...]
) -> Iterator[tuple[Catalog, str]]:
    """Seal a run that wrote the *written* terms under *keep*; yield the catalog and its id."""
    store = open_run_store(project_2, "run", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS)
    sid = store.sim_id
    rng = np.random.default_rng(3)
    sz = store.open_zarr(sid)
    try:
        sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 10.0))
        for name in written:
            sz.write_field_stack(
                name, -rng.uniform(0.0, 1e-3, (N_STEPS, 1, N_CELLS)), subgroup="budget"
            )
        if keep is not None:
            sz.write_budget_policy(keep, written)
    finally:
        sz.close()
    seal_completed(store)
    rebuild_index(project_2)
    with Catalog(project_2) as catalog:
        yield catalog, sid


def test_a_consumers_store_with_the_drain_only_refuses_the_release_flux(project_2) -> None:
    keep = BudgetKeep.of_terms({"drain", "drain_to_mover"})
    with _sealed(project_2, keep, ("drain",)) as (catalog, sid):
        sz = catalog.open_zarr(sid)
        try:
            assert "release_flux" not in available_virtual_fields(sz.root)
            assert "outflow_drain" in available_virtual_fields(sz.root)
        finally:
            sz.close()
        run = Run(sid, catalog)
        assert not run.has_field("release_flux")
        assert "release_flux" not in run.array.list_fields()
        with pytest.raises(FieldNotFoundError):
            run.field("release_flux", time=0)
        with pytest.raises(KeyError):
            read_field_or_virtual(catalog, sid, "release_flux", 0)
        with pytest.raises(KeyError):
            read_field_range_or_virtual(catalog, sid, "release_flux", 0, N_STEPS)


def test_the_diagnosis_names_the_release_terms_the_store_lacks(project_2) -> None:
    keep = BudgetKeep.of_terms({"drain", "drain_to_mover"})
    with _sealed(project_2, keep, ("drain",)) as (catalog, sid):
        run = Run(sid, catalog)

        problem = diagnose_missing(["release_flux"], run)
        text = missing_field_explanation(["release_flux"], run)

        assert problem is not None
        assert {"stream", "lake", "recharge"} <= set(problem.terms)
        assert "drain" not in problem.terms
        assert "stream" in text and "lake" in text
        assert "keep_per_cell_budget" in text


def test_a_consumers_store_that_declares_every_release_term_serves_the_field(project_2) -> None:
    keep = BudgetKeep.of_terms(budget_terms_for("release_flux"))
    with _sealed(project_2, keep, ("drain", "recharge")) as (catalog, sid):
        run = Run(sid, catalog)

        assert run.has_field("release_flux")
        rows = read_field_range_or_virtual(catalog, sid, "release_flux", 0, N_STEPS)
        assert rows.shape == (N_STEPS, N_CELLS)
        assert diagnose_missing(["release_flux"], run) is None


def test_the_all_policy_serves_the_field_from_the_drain_alone(project_2) -> None:
    with _sealed(project_2, BudgetKeep.everything(), ("drain",)) as (catalog, sid):
        assert Run(sid, catalog).has_field("release_flux")


def test_a_store_without_attributes_serves_the_field_from_the_drain_alone(project_2) -> None:
    with _sealed(project_2, None, ("drain",)) as (catalog, sid):
        assert Run(sid, catalog).has_field("release_flux")


# A validation period sits beside ``[metrics] window`` in the ``metrics`` table. The
# long view of a run lists both. The wide view, the selectors, ``find``, a set of
# runs and the dataset loader read the period named ``metrics`` alone, so a score
# of another period never makes a run best.
VALIDATION = DateWindow(start=date(2010, 1, 1), end=date(2012, 12, 31))


SCORES = {"low": (0.6, 0.99), "high": (0.7, 0.1)}


@pytest.fixture
def cat_2(tmp_path):
    root = tmp_path / "p"
    ids = {}
    for name, (headline, validation) in SCORES.items():
        store = open_run_store(root, name, create_zarr=False)
        store.facts.put_metric(headline_row("nse", headline))
        store.facts.put_metric(
            headline_row(
                "nse",
                validation,
                window=VALIDATION,
                window_name="validation",
                window_role="validation",
            )
        )
        store.facts.score = headline_score(headline)
        seal_completed(store)
        ids[name] = store.sim_id
    rebuild_index(root)
    with Catalog(root) as catalog:
        yield catalog, ids


def test_the_long_view_of_a_run_lists_every_period(cat_2) -> None:
    catalog, _ids = cat_2
    frame = catalog["low"].metrics
    assert dict(zip(frame["window_name"], frame["value"], strict=True)) == {
        HEADLINE_WINDOW: 0.6,
        "validation": 0.99,
    }
    assert set(frame["window_role"]) == {"evaluation", "validation"}


def test_the_selectors_and_the_filter_rank_on_the_headline_period(cat_2) -> None:
    catalog, ids = cat_2
    assert catalog.resolve("@best:nse") == ids["high"]
    assert catalog.resolve("@worst:nse") == ids["low"]
    assert catalog.find(nse_gt=0.65).sim_ids == [ids["high"]]


def test_the_wide_view_the_set_and_the_loader_read_the_headline_period(cat_2) -> None:
    catalog, ids = cat_2
    wide = catalog.sql("SELECT sim_id, nse FROM v_metrics_wide")
    assert dict(zip(wide["sim_id"].astype(str), wide["nse"], strict=True)) == {
        ids["low"]: 0.6,
        ids["high"]: 0.7,
    }
    frame = catalog.find().metrics.set_index("sim_id")
    assert frame.loc[ids["high"], "nse"] == 0.7
    dataset = catalog.load_dataset()
    assert dict(zip(dataset["sim_id"].values, dataset["metric_nse"].values, strict=True)) == {
        ids["low"]: 0.6,
        ids["high"]: 0.7,
    }


def test_the_loader_and_the_set_stack_parameters_and_fields(tmp_path) -> None:
    root = tmp_path / "p"
    ids = {}
    for index, name in enumerate(("a", "b")):
        store = open_run_store(root, name)
        store.facts.put_parameter(
            ParameterRow(name="K", value=1e-5 * (index + 1), origin="declared", calibrated=False)
        )
        store.facts.put_parameter(
            ParameterRow(name="K", zone="granite", value=2e-6, origin="declared", calibrated=False)
        )
        with store.open_zarr(store.sim_id) as zarr:
            zarr.write_field("head", 0, np.full(4, 10.0 + index), n_timesteps=1)
        seal_completed(store)
        ids[name] = store.sim_id
    rebuild_index(root)
    with Catalog(root) as catalog:
        dataset = catalog.load_dataset(fields=["head", "absent"])
        assert sorted(dataset["sim_id"].values) == sorted(ids.values())
        assert dataset["param_K"].sel(sim_id=ids["b"]).item() == pytest.approx(2e-5)
        assert dataset["param_K_granite"].sel(sim_id=ids["a"]).item() == pytest.approx(2e-6)
        assert "env_python_version" in dataset
        assert "absent" not in dataset
        assert float(dataset["head"].sel(sim_id=ids["b"]).max()) == 11.0
        stacked = catalog.find().to_xarray("head")
        assert stacked.name == "head"
        assert list(stacked["run"].values) == catalog.find().sim_ids
        assert catalog.find().to_xarray("absent").size == 1
        scalars = catalog.load_dataset(include_params=False, include_env=False)
        assert not any(str(name).startswith(("param_", "env_")) for name in scalars.data_vars)


# They went in as rows of ``metrics`` (station ``flow_main``, variable ``runtime``)
# and came out in ``catalog show``, ``catalog diff``, ``compare_pair`` and
# ``v_metrics_wide`` next to the NSE. The facts and the seal still carry them, the
# way the project summary reads the solve time; the index and the readers of scores
# leave them out. A run of 2.0 carries the solve time among them and a new run does not
# (it is in ``profile.json``), so the fixture holds both kinds of row.
RUNTIME = {"flow_solve_time_seconds": 12.5, "water_budget_percent_discrepancy": 0.01}


@pytest.fixture
def project_3(tmp_path):
    root = tmp_path / "p"
    for name, nse in (("a", 0.6), ("b", 0.7)):
        store = open_run_store(root, name, create_zarr=False)
        store.facts.put_metric(headline_row("nse", nse, station=STATION))
        ctx = SimpleNamespace(run=SimpleNamespace(is_solver_backed=True, id="flow_main"))
        record_run_execution_metrics(
            ctx=ctx, sim_id=store.sim_id, store=store, result=SimpleNamespace(metrics=RUNTIME)
        )
        assert {row.metric for row in store.facts.metrics if row.variable == "runtime"} == set(
            RUNTIME
        )
        store.facts.score = headline_score(nse, station=STATION)
        seal_completed(store)
    rebuild_index(root)
    return root


def test_the_index_holds_no_runtime_row(project_3) -> None:
    with Catalog(project_3) as cat:
        names = set(cat.sql("SELECT metric FROM metrics")["metric"])
        variables = set(cat.sql("SELECT variable FROM metrics")["variable"])
    assert names == {"nse"}
    assert variables == {"discharge"}


def test_the_wide_view_has_no_runtime_row(project_3) -> None:
    with Catalog(project_3) as cat:
        wide = cat.sql("SELECT variable FROM v_metrics_wide")
    assert set(wide["variable"]) == {"discharge"}


def test_show_and_diff_and_compare_pair_list_scores_only(project_3) -> None:
    with Catalog(project_3) as cat:
        shown = cat["a"].metrics
        delta = cat.diff("a", "b")["metrics"]
    assert set(shown["variable"]) == {"discharge"}
    assert {key[0] for key in delta} == {"nse"}
    assert set(compare_pair("a", "b", workspace=project_3).reset_index()["metric"]) == {"nse"}


def test_soil_budget_declares_its_primary_key() -> None:
    assert primary_key_for("soil_budget") == ("sim_id", "column_id", "year")


def test_an_undeclared_column_is_refused_by_name(tmp_path: Path) -> None:
    with open_run_store(tmp_path / "project", "run", n_cells=1, n_layers=1) as store:
        with pytest.raises(KeyError, match="not_a_column"):
            store.write_view(
                store.sim_id,
                "soil_budget",
                [{"column_id": "0.0", "year": 2020, "not_a_column": 1.0}],
            )


# The solver adapter hands the pumped share of the wells to the run as a metric.
# The post-run step turns it into a validity of the checks: a non-fatal one, that
# fails below the share a cut is reported at, and passes above it. The seal then
# carries it in ``manifest.json`` and the README.
def _record(tmp_path: Path, metrics: dict[str, float]):
    store = open_run_store(tmp_path / "proj", "demo")
    ctx = SimpleNamespace(run=SimpleNamespace(is_solver_backed=True, id="flow_main"))
    result = SimpleNamespace(metrics=metrics)
    record_run_execution_metrics(ctx=ctx, sim_id=store.sim_id, store=store, result=result)
    return store


def test_the_pumped_share_is_applied_over_requested() -> None:
    requested = {(0, 4): -756000.0, (1, 2): -100.0}
    applied = {(0, 4): -131858.0, (1, 2): -100.0}

    assert pumped_percent(requested, applied) == pytest.approx(
        100.0 * (131858.0 + 100.0) / (756000.0 + 100.0)
    )


def test_a_run_without_a_requested_volume_has_no_pumped_share() -> None:
    assert pumped_percent({}, {}) is None
    assert pumped_percent({(0, 1): 0.0}, {(0, 1): 0.0}) is None


def test_a_cut_well_fails_a_non_fatal_validity(tmp_path: Path) -> None:
    store = _record(tmp_path, {WELLS_PUMPED_METRIC: 17.4})
    try:
        (validity,) = store.facts.validities
        assert validity.name == WELLS_PUMPED_CHECK
        assert validity.passed is False
        assert validity.fatal is False
        assert validity.value == pytest.approx(17.4)
        assert "17 %" in validity.message
        assert store.facts.metrics[0].metric == WELLS_PUMPED_METRIC
    finally:
        store.close()


def test_a_fully_pumped_well_passes(tmp_path: Path) -> None:
    store = _record(tmp_path, {WELLS_PUMPED_METRIC: 99.6})
    try:
        (validity,) = store.facts.validities
        assert validity.passed is True
    finally:
        store.close()


def test_a_run_without_wells_carries_no_such_validity(tmp_path: Path) -> None:
    store = _record(tmp_path, {})
    try:
        assert store.facts.validities == []
    finally:
        store.close()


# It used to take the highest value, so ``@best:rmse`` named the worst run. Best
# is now the highest ``nse``, the lowest ``rmse`` and the ``pbias`` closest to
# zero, for the selector and ``Catalog.best`` alike. ``RunSet.best`` is covered
# by ``test_group.py``.
@pytest.fixture
def scored(tmp_path):
    """Three sealed runs: a, b, c, scored under the rule on nse, rmse and pbias.

    The derive step records one row per metric and the headline NSE in
    ``facts.score``. The rank under the rule reads that headline.
    """
    scores = {
        "a": {"nse": 0.6, "rmse": 2.0, "pbias": -20.0},
        "b": {"nse": 0.9, "rmse": 0.5, "pbias": 5.0},
        "c": {"nse": 0.3, "rmse": 3.0, "pbias": 30.0},
    }
    project = tmp_path / "p"
    ids = {}
    for name, metrics in scores.items():
        store = open_run_store(project, name, create_zarr=False)
        sid = store.sim_id
        for metric, value in {**metrics, "unknown_score": 1.0}.items():
            store.facts.put_metric(headline_row(metric, value, n_samples=1827))
        store.facts.score = headline_score(metrics["nse"], n_samples=1827)
        seal_completed(store)
        ids[name] = sid
    rebuild_index(project)
    with Catalog(project) as cat:
        yield cat, ids


@pytest.mark.parametrize(
    ("metric", "best", "worst"),
    [("nse", "b", "c"), ("rmse", "b", "c"), ("pbias", "b", "c")],
)
def test_the_selector_follows_the_metric(scored, metric, best, worst) -> None:
    cat, ids = scored
    assert cat.resolve(f"@best:{metric}") == ids[best]
    assert cat.resolve(f"@worst:{metric}") == ids[worst]
    assert cat.best("p", metric).sim_id == ids[best]
    assert cat.worst("p", metric).sim_id == ids[worst]


def test_rank_lists_best_first(scored) -> None:
    cat, ids = scored
    assert cat.rank("p", "rmse", n=3).sim_ids == [ids["b"], ids["a"], ids["c"]]
    # The raw order stays reachable for a metric with no direction.
    assert cat.rank("p", "rmse", n=3, ascending=False).sim_ids == [ids["c"], ids["a"], ids["b"]]


def test_a_metric_without_direction_is_refused(scored) -> None:
    cat, _ids = scored
    with pytest.raises(SimulationNotFoundError, match="no declared direction"):
        cat.resolve("@best:unknown_score")
    with pytest.raises(UnrankedMetricError):
        cat.best("p", "unknown_score")


FIVE_YEARS = DateWindow(start=date(2016, 1, 1), end=date(2020, 12, 31))


NINETY_DAYS = DateWindow(start=date(2020, 10, 1), end=date(2020, 12, 29))


@pytest.fixture
def windows(tmp_path):
    """One site, one gauge, two windows: a short good score and a long poor one."""
    root = make_project(tmp_path / "demo")
    ids = {
        "short": seal_run(root, "short", nse=0.97, window=NINETY_DAYS),
        "long": seal_run(root, "long", nse=0.60, window=FIVE_YEARS),
        "long2": seal_run(root, "long2", nse=0.55, window=FIVE_YEARS),
    }
    rebuild_index(root)
    return ids


@pytest.fixture
def stations(tmp_path):
    """Two sites, so two gauges, on the same window."""
    root = make_project(tmp_path / "demo")
    ids = {
        "a1": seal_run(root, "a1", site="J001", nse=0.8, window=FIVE_YEARS),
        "a2": seal_run(root, "a2", site="J001", nse=0.7, window=FIVE_YEARS),
        "b1": seal_run(root, "b1", site="J002", nse=0.9, window=FIVE_YEARS),
    }
    rebuild_index(root)
    return ids


def test_catalog_rank_refuses_two_windows(windows, tmp_path) -> None:
    ids = windows
    root = tmp_path / "demo"
    with pytest.raises(MixedWindowsError, match="--mixed-windows"):
        rank_simulations("demo", workspace=root, metric="nse")
    with pytest.raises(MixedWindowsError):
        rank_simulations("demo", workspace=root, metric="nse", station="J0014010")
    frame = rank_simulations("demo", workspace=root, metric="nse", mixed_windows=True)
    assert frame["sim_id"].astype(str).tolist()[0] == ids["short"]


def test_catalog_rank_of_one_station_ranks_it(stations, tmp_path) -> None:
    ids = stations
    root = tmp_path / "demo"
    with pytest.raises(MixedWindowsError, match="J002"):
        rank_simulations("demo", workspace=root, metric="nse")
    frame = rank_simulations("demo", workspace=root, metric="nse", station="J001")
    assert frame["sim_id"].astype(str).tolist() == [ids["a1"], ids["a2"]]


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="hmp catalog")
    sub = parser.add_subparsers(dest="action")
    rank.register(sub)
    return parser.parse_args([rank.NAME, *argv])


def test_the_command_exits_with_the_validation_code_and_forces(windows, tmp_path, capsys) -> None:
    root = str(tmp_path / "demo")
    args = _parse(["--project", "demo", "-w", root, "--top", "3"])
    with pytest.raises(MixedWindowsError, match="--mixed-windows") as stopped:
        args._handler(args)
    assert exit_code_for(stopped.value) == EXIT_VALIDATION

    args = _parse(["--project", "demo", "-w", root, "--top", "3", "--mixed-windows"])
    args._handler(args)
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("TOP#1: short")
    assert "window=2020-10-01..2020-12-29" in out


# A term without a descriptor is stored but never listed, exported or read: the
# registry is the gate of ``run.array.list_fields``, ``hmp export --list`` and
# ``[[export]] variables = "all"``.
#
# The list of terms is the canonical map, so it cannot see a record that map does
# not name: ``canonical_budget_component`` passes such a record through as its
# lower-cased name, and that term lands in the store without a descriptor. The
# record names the MODFLOW builders emit are listed below and checked against the
# map; an unmapped record a future package emits is not caught here.
VIRTUAL_FIELD_NAMES = (
    "watertable_elevation",
    "watertable_depth",
    "seepage_mask",
    "outflow_drain",
    "release_flux",
    "budget_flux_per_area",
    "drain_accumulation_flux",
    "release_accumulation_flux",
    "concentration_seepage",
    "mass_seepage",
    "mass_seepage_running_sum",
    "simulated_active_network",
)


MODFLOW_6_RECORDS = (
    "DRN",
    "DRN-TO-MVR",
    "RCHA",
    "CHD",
    "WEL",
    "EVTA",
    "STO-SS",
    "STO-SY",
    "SFR",
    "LAK",
)


MODFLOW_NWT_RECORDS = (
    "DRAINS",
    "RECHARGE",
    "ET",
    "WELLS",
    "CONSTANT HEAD",
    "STORAGE",
    "STREAM LEAKAGE",
    "LAKE SEEPAGE",
)


def _boussinesq_terms() -> set[str]:
    """Return the components the Boussinesq extractor writes, given every history."""
    ones = np.ones((2, N_CELLS))
    payload = {
        "recharge_rate_history_m_s": ones,
        "drainage_flux_history_m3_s": ones,
        "well_flux_history_m3_s": ones,
        "saturation_excess_history_m_s": ones,
        "prescribed_head_flux_history_m3_s": ones,
    }
    components = BoussinesqOutputAdapter._budget_components(
        payload, n_timesteps=2, n_cells=N_CELLS, cell_area_m2=np.ones(N_CELLS)
    )
    return set(components)


def _written_terms() -> list[str]:
    terms = {*CANONICAL_BUDGET_TERMS, STREAM_CONSTANT_HEAD_BUDGET, *_boussinesq_terms()}
    return sorted(terms)


def test_the_boussinesq_extractor_writes_five_terms() -> None:
    assert _boussinesq_terms() == {"recharge", "drain", "well", "surface_excess", "constant_head"}


@pytest.mark.parametrize("term", _written_terms())
def test_a_written_budget_term_is_in_the_registry_under_budget(term: str) -> None:
    descriptor = field_registry.get(term)
    assert descriptor.zarr_path == f"budget/{term}"
    assert descriptor.units == "m3 s-1"
    assert descriptor.derived_by == "solver"


@pytest.mark.parametrize("record", [*MODFLOW_6_RECORDS, *MODFLOW_NWT_RECORDS])
def test_a_record_the_builders_emit_maps_to_a_canonical_term(record: str) -> None:
    assert canonical_budget_component(record) in CANONICAL_BUDGET_TERMS


def test_every_unknown_name_of_a_cell_budget_file_stays_out_of_the_registry() -> None:
    assert not field_registry.has("cell_budget")


@pytest.mark.parametrize("name", VIRTUAL_FIELD_NAMES)
def test_a_virtual_field_has_a_descriptor(name: str) -> None:
    descriptor = field_descriptor(name)
    assert descriptor.public_name == name
    assert descriptor.zarr_path == f"derived/{name}"


def test_the_virtual_field_table_names_nothing_outside_the_list() -> None:
    assert set(VIRTUAL_FIELDS) <= set(VIRTUAL_FIELD_NAMES)


# The rule was written twice: ``project/summary.py`` over the columns of the
# index (``score_station``, ``score_variable``) and ``results/run/sealed.py`` over
# those of a headline row, with two exceptions (``MixedWindowsError`` and a bare
# ``ValueError``). The summary left the station out of the rule when no ``by``
# was given, so ``hmp catalog ls --best`` ranked runs scored at different
# stations together.
def _rows(*scored: tuple[str, str, str, float]) -> pd.DataFrame:
    """One row per run: ``(site, station, variable, nse)``, one window and one rule version."""
    return pd.DataFrame(
        [
            {
                "name": f"run{index}",
                "site": site,
                "score_station": station,
                "score_variable": variable,
                "window_start": "2016-01-01",
                "window_end": "2020-12-31",
                "metric_rule_version": "1",
                "nse": nse,
            }
            for index, (site, station, variable, nse) in enumerate(scored)
        ]
    )


def test_the_exception_is_one_class_of_the_data_errors() -> None:
    assert issubclass(MixedWindowsError, DataError)
    assert not hasattr(ranking, "MixedWindowsError")


def test_runs_scored_at_different_stations_are_not_ranked_together() -> None:
    frame = _rows(("a", "J001", "discharge", 0.8), ("b", "J002", "discharge", 0.6))

    with pytest.raises(MixedWindowsError, match="J001") as refused:
        ranking.rank_rows(frame, "nse")
    assert "J002" in str(refused.value)
    assert list(ranking.rank_rows(frame, "nse", mixed_windows=True)["name"]) == ["run0", "run1"]


def test_each_site_keeps_its_own_station_when_ranked_by_site() -> None:
    frame = _rows(
        ("a", "J001", "discharge", 0.8),
        ("a", "J001", "discharge", 0.9),
        ("b", "J002", "discharge", 0.6),
    )

    best = ranking.rank_rows(frame, "nse", by="site")

    assert list(best["name"]) == ["run1", "run2"]


@pytest.mark.parametrize(
    ("second", "said"),
    [
        (("a", "J002", "discharge", 0.9), "site a"),
        (("b", "P002", "groundwater_level", 0.9), "groundwater_level"),
    ],
    ids=["two-stations-inside-one-site", "two-variables-across-the-cohort"],
)
def test_two_rules_in_one_ranking_are_refused(second, said) -> None:
    frame = _rows(("a", "J001", "discharge", 0.8), second)

    with pytest.raises(MixedWindowsError, match=said):
        ranking.rank_rows(frame, "nse", by="site")


def test_the_direction_of_a_metric_is_ranked_by_one_key() -> None:
    from hydromodpy.project.launch import summary
    from hydromodpy.results.run import group

    assert ranking.rank_key is group.rank_key
    assert not hasattr(summary, "rank_key")


# Four lists of the same thing had drifted: the wide view pivoted twenty names, the
# run kernels computed eleven, the direction table held twenty-five and the
# calibration criteria their own ten. ``r2``, ``mse`` and ``kge_delta`` had a
# direction and no producer, and the wide view carried columns nothing filled.
PRODUCERS = {
    "the run kernels": set(RUN_METRIC_NAMES),
    "the calibration criteria": set(CALIBRATION_METRICS),
}


def test_every_name_a_producer_writes_has_a_direction() -> None:
    for producer, names in PRODUCERS.items():
        assert names <= set(METRIC_SENSE), (
            f"{producer} write(s) without a direction: {sorted(names - set(METRIC_SENSE))}"
        )


def test_every_direction_has_a_producer() -> None:
    produced = set().union(*PRODUCERS.values())
    assert set(METRIC_SENSE) <= produced, (
        f"a direction nothing produces: {sorted(set(METRIC_SENSE) - produced)}"
    )


def test_a_retired_name_is_no_known_name() -> None:
    assert not set(RETIRED_METRIC_NAMES) & set(METRIC_SENSE)


@pytest.fixture
def index(tmp_path):
    project = tmp_path / "p"
    store = open_run_store(project, "a", create_zarr=False)
    store.facts.put_metric(
        MetricRow(
            station="J0014010",
            variable="discharge",
            metric="nse",
            value=0.5,
            window_start=date(2016, 1, 1),
            window_end=date(2020, 12, 31),
            n_samples=10,
            metric_rule_version=METRIC_RULE_VERSION,
        )
    )
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as cat:
        yield cat


def test_the_wide_view_pivots_the_names_the_kernels_compute(index) -> None:
    columns = index.sql("SELECT * FROM v_metrics_wide").columns
    pivoted = [c for c in columns if c not in {"sim_id", "station_id", "variable"}]
    assert pivoted == list(RUN_METRIC_NAMES)


# A calibration scores ``nse_log``; the old spelling ``log_nse`` is refused
# with the one to write, in the ranking helper and in the ``@best`` selector.
def test_the_old_name_is_refused_with_the_new_one(tmp_path: Path) -> None:
    from tests._helpers.sealed_runs import make_project, seal_run

    root = make_project(tmp_path / "demo")
    seal_run(root, "only")
    rebuild_index(root)
    with Catalog(root) as catalog:
        with pytest.raises(SimulationNotFoundError, match="was renamed: write 'nse_log'"):
            catalog.resolve("@best:log_nse")
    with pytest.raises(UnrankedMetricError, match="write 'nse_log'"):
        metric_rank_sql("log_nse", best=True)


def test_the_new_name_has_a_direction() -> None:
    assert metric_rank_sql("nse_log", best=True).endswith("DESC")


@pytest.fixture
def windows_2(tmp_path):
    """One site, one gauge, two windows: a short good score and a long poor one."""
    root = make_project(tmp_path / "demo")
    ids = {
        "short": seal_run(root, "short", nse=0.97, window=NINETY_DAYS),
        "long": seal_run(root, "long", nse=0.60, window=FIVE_YEARS),
        "long2": seal_run(root, "long2", nse=0.55, window=FIVE_YEARS),
    }
    rebuild_index(root)
    with Catalog(root) as cat:
        yield cat, ids


def test_each_rule_has_its_own_best_run(windows_2) -> None:
    cat, ids = windows_2
    rows = cat.backend.fetch_all(
        "SELECT CAST(sim_id AS VARCHAR), nse, score_window_start FROM v_best_per_project "
        "ORDER BY score_window_start"
    )
    assert rows == [
        (ids["long"], 0.60, FIVE_YEARS.start),
        (ids["short"], 0.97, NINETY_DAYS.start),
    ]


# A 90-day NSE of 0.97 ranked above a 5-year NSE of 0.60 in ``Catalog.best``,
# ``@best:nse`` and ``find(nse_gt=...)``: each ordered the ``metrics`` rows
# whatever their window, station or variable. They now refuse, naming the rules
# found, unless ``mixed_windows=True``. ``hmp catalog rank`` and the best-per-project
# view have their own files.
@pytest.fixture
def windows_3(tmp_path):
    """One site, one gauge, two windows: a short good score and a long poor one."""
    root = make_project(tmp_path / "demo")
    ids = {
        "short": seal_run(root, "short", nse=0.97, window=NINETY_DAYS),
        "long": seal_run(root, "long", nse=0.60, window=FIVE_YEARS),
        "long2": seal_run(root, "long2", nse=0.55, window=FIVE_YEARS),
    }
    rebuild_index(root)
    with Catalog(root) as cat:
        yield cat, ids


@pytest.fixture
def stations_2(tmp_path):
    """Two sites, so two gauges, on the same window."""
    root = make_project(tmp_path / "demo")
    ids = {
        "a1": seal_run(root, "a1", site="J001", nse=0.8, window=FIVE_YEARS),
        "a2": seal_run(root, "a2", site="J001", nse=0.7, window=FIVE_YEARS),
        "b1": seal_run(root, "b1", site="J002", nse=0.9, window=FIVE_YEARS),
    }
    rebuild_index(root)
    with Catalog(root) as cat:
        yield cat, ids


@pytest.mark.parametrize("call", ["best", "worst", "rank"])
def test_the_methods_refuse_two_windows(windows_3, call) -> None:
    cat, _ids = windows_3
    with pytest.raises(MixedWindowsError, match="--mixed-windows") as refused:
        getattr(cat, call)("demo", "nse")
    assert "2016-01-01 to 2020-12-31" in str(refused.value)
    assert "2020-10-01 to 2020-12-29" in str(refused.value)


def test_mixed_windows_forces_the_ranking(windows_3) -> None:
    cat, ids = windows_3
    assert cat.best("demo", "nse", mixed_windows=True).sim_id == ids["short"]
    assert cat.worst("demo", "nse", mixed_windows=True).sim_id == ids["long2"]
    ranked = cat.rank("demo", "nse", n=3, mixed_windows=True)
    assert ranked.sim_ids == [ids["short"], ids["long"], ids["long2"]]


def test_a_selector_refuses_two_windows(windows_3) -> None:
    cat, ids = windows_3
    with pytest.raises(MixedWindowsError, match="name the run by its directory"):
        cat.resolve("@best:nse")
    with pytest.raises(MixedWindowsError):
        cat.resolve("@worst:nse")
    assert cat.resolve("@best:nse", mixed_windows=True) == ids["short"]


def test_two_stations_are_refused_and_a_named_station_is_not(stations_2) -> None:
    cat, ids = stations_2
    with pytest.raises(MixedWindowsError, match="J001") as refused:
        cat.best("demo", "nse")
    assert "J002" in str(refused.value)
    with pytest.raises(MixedWindowsError):
        cat.resolve("@best:nse")
    assert cat.resolve("@best:nse@J001") == ids["a1"]
    assert cat.resolve("@worst:nse@J001") == ids["a2"]
    assert cat.resolve("@best:nse", mixed_windows=True) == ids["b1"]


def test_a_named_station_still_needs_one_window(windows_3) -> None:
    cat, ids = windows_3
    with pytest.raises(MixedWindowsError):
        cat.resolve("@best:nse@J0014010")
    assert cat.resolve("@best:nse@J0014010", mixed_windows=True) == ids["short"]


def test_a_filter_on_a_metric_refuses_two_windows(windows_3) -> None:
    cat, ids = windows_3
    with pytest.raises(MixedWindowsError, match="--mixed-windows"):
        cat.find(nse_gt=0.5)
    # A filter that names no metric ranks nothing.
    assert len(cat.find(status="completed")) == 3
    assert set(cat.find(nse_gt=0.5, mixed_windows=True).sim_ids) == set(ids.values())


def test_a_filter_on_a_metric_under_one_rule_answers(stations_2) -> None:
    cat, ids = stations_2
    assert set(cat.find(site="J001", nse_gt=0.75).sim_ids) == {ids["a1"]}


def test_the_project_accessor_refuses_two_windows(windows_3) -> None:
    cat, ids = windows_3
    runs = ProjectRunsAccessor(SimpleNamespace(_store=cat, _project_name="demo"))
    with pytest.raises(MixedWindowsError, match="--mixed-windows"):
        runs.best("nse")
    assert runs.best("nse", mixed_windows=True).sim_id == ids["short"]


# It took ``MAX`` over every station and variable of a run, so the discharge and the
# level of one station came out as one row holding the best of both. The index table
# ``metrics`` names the period of each row (``window_name``) and the view keeps the
# headline period only.
def _row_2(station: str, variable: str, metric: str, value: float) -> MetricRow:
    return headline_row(metric, value, station=station, variable=variable, n_samples=1827)


@pytest.fixture
def cat_3(tmp_path):
    project = tmp_path / "p"
    store = open_run_store(project, "a", create_zarr=False)
    for row in (
        _row_2("S1", "discharge", "nse", 0.6),
        _row_2("S1", "discharge", "rmse", 2.0),
        _row_2("S1", "level", "nse", 0.2),
        _row_2("S2", "discharge", "nse", 0.9),
        headline_row("nse", 0.1, station="S1", window_name="validation", window_role="validation"),
    ):
        store.facts.put_metric(row)
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog


def test_one_row_per_station_and_variable(cat_3) -> None:
    wide = cat_3.sql("SELECT station_id, variable, nse, rmse FROM v_metrics_wide")
    rows = {(r.station_id, r.variable): (r.nse, r.rmse) for r in wide.itertuples()}
    assert len(wide) == 3  # the validation period of S1 stays beside the headline
    assert rows[("S1", "discharge")] == (0.6, 2.0)
    assert rows[("S1", "level")][0] == 0.2
    assert rows[("S2", "discharge")][0] == 0.9


def test_the_index_table_names_the_period_of_each_row(cat_3) -> None:
    columns = set(cat_3.sql("SELECT * FROM metrics").columns)
    assert not columns & {"period_start", "period_end", "nse_window_start", "nse_n"}
    assert {"window_name", "window_role", "window_start", "window_end", "n_samples"} <= columns
