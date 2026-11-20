"""Metric scores of sealed runs, as the catalog, the selectors, the CLI and the index serve them.

A cost is one minus an efficiency, or the error itself. Ranking, filtering and ``@best``
refuse runs scored under two rules (window, station, variable). Windows are dates,
discharge is in m3 s-1 and heads in m.
"""

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
from hydromodpy.cli.exit_codes import EXIT_VALIDATION, exit_code_for
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
from hydromodpy.project.compare import headline_table
from hydromodpy.results import field_registry
from hydromodpy.results.catalog.constants import (
    RETIRED_METRIC_NAMES,
    UnrankedMetricError,
    cost_of,
    metric_rank_sql,
    score_of,
)
from hydromodpy.results.catalog.discovery import SimulationNotFoundError
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.catalog.listing import rank_simulations
from hydromodpy.results.derive.config_flags import diagnose_missing
from hydromodpy.results.derive.virtual_fields import (
    VIRTUAL_FIELDS,
    available_virtual_fields,
    read_field_or_virtual,
    read_field_range_or_virtual,
)
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.metric_rule import METRIC_RULE_VERSION, DateWindow, MetricRule
from hydromodpy.results.record.manifest import MetricRow, ParameterRow
from hydromodpy.results.run import ranking
from hydromodpy.results.run.sealed import MixedWindowsError, metrics_frame
from hydromodpy.results.run.view import Run
from hydromodpy.results.score import score_metric, score_timeseries
from hydromodpy.results.storage.parquet_schemas import primary_key_for
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter
from hydromodpy.solver.modflow_common.budget_components import CANONICAL_BUDGET_TERMS
from hydromodpy.workflow.steps.run_outputs import record_run_execution_metrics
from tests._helpers.metric_rows import headline_row, headline_score
from tests._helpers.run_stores import open_run_store
from tests._helpers.sealed_runs import make_project, seal_run
from validation_cases.calibration.recession_hillslope_aquifer import experiment as case

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "metric", sorted(name for name, sense in METRIC_SENSE.items() if sense in ("max", "min"))
)
def test_score_from_cost(metric: str) -> None:
    assert score_of(metric, cost_of(metric, 0.25)) == pytest.approx(0.25)


def test_cost_of_a_score() -> None:
    assert cost_of("nse_log", 0.9) == pytest.approx(0.1)
    assert cost_of("rmse", 0.9) == pytest.approx(0.9)
    assert np.allclose(score_of("kge", np.array([0.1, 0.4])), [0.9, 0.6])


@pytest.mark.parametrize("metric", ["bias", "kge_alpha"])
def test_no_cost_for_target_metric(metric: str) -> None:
    with pytest.raises(UnrankedMetricError, match=metric):
        cost_of(metric, 0.1)


@pytest.mark.parametrize("metric", sorted(set(METRICS) - {"distance_gap", "distance_mean"}))
def test_series_criterion_cost(metric: str) -> None:
    rng = np.random.default_rng(3)
    obs = 1.0 + rng.random(730)
    sim = obs * (1.0 + 0.1 * rng.standard_normal(730))
    criterion = SeriesCriterion(metric, METRICS[metric])
    result = criterion.score(np.abs(sim), obs)
    assert result.cost == pytest.approx(cost_of(metric, result.diagnostics["score"]))


# Two stations or two variables of one run stay in separate rows, each with its window and n.
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


def test_comparison_needs_a_project(tmp_path) -> None:
    from hydromodpy.project import api
    from hydromodpy.project.compare import ComparisonReferenceError

    with pytest.raises(ComparisonReferenceError, match="names no sealed run"):
        api.compare(["a", "b"], workspace=tmp_path)


def _run_diff(project, capsys, fmt: str) -> str:
    from hydromodpy.cli.main import _build_parser

    args = _build_parser().parse_args(["diff", "a", "b", "-w", str(project), "--format", fmt])
    args._handler(args)
    return capsys.readouterr().out


def test_cli_prints_window_of_each_variable(project, capsys) -> None:
    text = _run_diff(project, capsys, "table")
    assert f"nse@{STATION}/discharge: 0.6 [2016-01-01/2020-12-31, n=1827]" in text
    assert "0.7 [2018-01-01/2020-12-31, n=1096]" in text
    assert f"nse@{STATION}/level" in text


def test_cli_json_rows(project, capsys) -> None:
    import json

    rows = json.loads(_run_diff(project, capsys, "json"))["data"]["metrics"]
    discharge = next(row for row in rows if row["variable"] == "discharge")
    assert discharge["station"] == STATION
    assert discharge["a"]["n"] == 1827
    assert discharge["b"]["window"] == "2018-01-01/2020-12-31"


# A cell gone dry gives a NaN head. Each row counts the periods of the window it lost to NaN.
PIEZOMETER = "P1"
DRY_WINDOW = DateWindow(start=date(2001, 1, 5), end=date(2001, 1, 31))
DRY_RULE = MetricRule(station=PIEZOMETER, window=DRY_WINDOW)
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


def test_rows_count_dry_periods(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy.results.score"):
        scores = score_timeseries(_frame(DRY), rule=DRY_RULE)

    assert scores.rows
    assert {row.n_sim_nan for row in scores.rows} == {3}
    warned = [r.getMessage() for r in caplog.records]
    assert any("NaN" in message and PIEZOMETER in message for message in warned)


def test_n_sim_nan_is_kept(tmp_path) -> None:
    root = tmp_path / "p"
    store = open_run_store(root, "a", create_zarr=False)
    for metric, value in (("nse", 0.5), ("rmse", 0.1)):
        store.write_metric(
            store.sim_id,
            headline_row(
                metric, value, station=PIEZOMETER, variable="head", window=DRY_WINDOW, n_sim_nan=3
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


# A retired spelling or a typo in a filter is refused, with the known names.
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


def test_known_metric_filters(cat) -> None:
    assert len(cat.find(nse_gt=0.5)) == 1
    assert len(cat.find(nse_log_gte=0.9)) == 0


FILTER_REFUSALS = [
    pytest.param({"log_nse_gt": 0.5}, "write 'nse_log'", id="retired spelling"),
    pytest.param({"nse_lgo_gt": 0.5}, r"(?s)nse_lgo.*kge_alpha", id="typo, known names listed"),
]


@pytest.mark.parametrize(("filters", "match"), FILTER_REFUSALS)
def test_filter_refusals(cat, filters, match) -> None:
    with pytest.raises(ValueError, match=match):
        cat.find(**filters)


# A discharge below a dam can hold negative values. Run and calibration clip them alike.
CLIP_WINDOW = DateWindow(start=date(2001, 1, 1), end=date(2001, 1, 10))
CLIP_RULE = MetricRule(station="S", window=CLIP_WINDOW)
DAYS = pd.date_range("2001-01-01", periods=10, freq="D")
OBSERVED = pd.Series([4.0, 3.5, 3.0, 2.6, 2.2, 1.9, 1.6, 1.4, 1.2, 1.0], index=DAYS)
CLEAN = OBSERVED * np.array([1.1, 0.9, 1.05, 0.95, 1.2, 0.85, 1.1, 0.9, 1.3, 0.8])
BELOW_ZERO = CLEAN.copy()
BELOW_ZERO.iloc[3] = -0.4
BELOW_ZERO.iloc[7] = -0.1


def test_kernel_clips_negatives() -> None:
    expected = core.log_nse(np.clip(BELOW_ZERO.to_numpy(), 0.0, None), OBSERVED.to_numpy())

    assert core.log_nse(BELOW_ZERO.to_numpy(), OBSERVED.to_numpy()) == pytest.approx(expected)


def test_run_score_equals_calibration() -> None:
    from_run = score_metric(BELOW_ZERO, OBSERVED, CLIP_RULE, "nse_log")
    from_calibration = SeriesCriterion("nse_log", core.log_nse).score(
        BELOW_ZERO.to_numpy(), OBSERVED.to_numpy()
    )

    assert from_run.value == pytest.approx(from_calibration.diagnostics["score"], abs=1e-15)
    assert from_run.n_clipped == int(from_calibration.diagnostics["n_clipped"])


def test_brutsaert_case_clips() -> None:
    bundle = case._compute_metrics(OBSERVED.to_numpy(), BELOW_ZERO.to_numpy())

    assert bundle["NSElog"] == pytest.approx(
        core.log_nse(BELOW_ZERO.to_numpy(), OBSERVED.to_numpy())
    )
    assert np.isfinite(bundle["NSElog"])


# Under the consumers policy a field is served only when every term it reads is kept.
N_STEPS = 4
N_CELLS = 3


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


@contextmanager
def _sealed(
    workspace: Path, keep: BudgetKeep | None, written: tuple[str, ...]
) -> Iterator[tuple[Catalog, str]]:
    """Seal a run that wrote the *written* terms under *keep*; yield the catalog and its id."""
    store = open_run_store(workspace, "run", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS)
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
    rebuild_index(workspace)
    with Catalog(workspace) as catalog:
        yield catalog, sid


def test_drain_only_store_refuses_release(workspace) -> None:
    keep = BudgetKeep.of_terms({"drain", "drain_to_mover"})
    with _sealed(workspace, keep, ("drain",)) as (catalog, sid):
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


def test_store_serves_release_flux(workspace) -> None:
    keep = BudgetKeep.of_terms(budget_terms_for("release_flux"))
    with _sealed(workspace, keep, ("drain", "recharge")) as (catalog, sid):
        run = Run(sid, catalog)

        assert run.has_field("release_flux")
        rows = read_field_range_or_virtual(catalog, sid, "release_flux", 0, N_STEPS)
        assert rows.shape == (N_STEPS, N_CELLS)
        assert diagnose_missing(["release_flux"], run) is None


# A validation period sits beside the headline period. Wide views read the headline alone.
VALIDATION = DateWindow(start=date(2010, 1, 1), end=date(2012, 12, 31))
PERIOD_SCORES = {"low": (0.6, 0.99), "high": (0.7, 0.1)}


@pytest.fixture
def two_period_catalog(tmp_path):
    root = tmp_path / "p"
    ids = {}
    for name, (headline, validation) in PERIOD_SCORES.items():
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


def test_headline_period_is_read(two_period_catalog) -> None:
    catalog, ids = two_period_catalog
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


def test_loader_stacks_parameters_and_fields(tmp_path) -> None:
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


# Solver run times are facts of the seal but never rows of the wide view or of the CLI.
RUNTIME = {"flow_solve_time_seconds": 12.5, "water_budget_percent_discrepancy": 0.01}


@pytest.fixture
def runtime_project(tmp_path):
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


def test_no_runtime_row(runtime_project) -> None:
    with Catalog(runtime_project) as cat:
        wide = cat.sql("SELECT variable FROM v_metrics_wide")
    assert set(wide["variable"]) == {"discharge"}


def test_soil_budget_primary_key() -> None:
    assert primary_key_for("soil_budget") == ("sim_id", "column_id", "year")


def test_undeclared_column_refused(tmp_path: Path) -> None:
    with open_run_store(tmp_path / "project", "run", n_cells=1, n_layers=1) as store:
        with pytest.raises(KeyError, match="not_a_column"):
            store.write_view(
                store.sim_id,
                "soil_budget",
                [{"column_id": "0.0", "year": 2020, "not_a_column": 1.0}],
            )


# A pumped share of the wells below the cut makes a non-fatal validity fail.
def _record(tmp_path: Path, metrics: dict[str, float]):
    store = open_run_store(tmp_path / "proj", "demo")
    ctx = SimpleNamespace(run=SimpleNamespace(is_solver_backed=True, id="flow_main"))
    result = SimpleNamespace(metrics=metrics)
    record_run_execution_metrics(ctx=ctx, sim_id=store.sim_id, store=store, result=result)
    return store


def test_pumped_share() -> None:
    requested = {(0, 4): -756000.0, (1, 2): -100.0}
    applied = {(0, 4): -131858.0, (1, 2): -100.0}

    assert pumped_percent(requested, applied) == pytest.approx(
        100.0 * (131858.0 + 100.0) / (756000.0 + 100.0)
    )


def test_no_requested_volume() -> None:
    assert pumped_percent({}, {}) is None
    assert pumped_percent({(0, 1): 0.0}, {(0, 1): 0.0}) is None


def test_cut_well_fails_validity(tmp_path: Path) -> None:
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


def test_pumped_well_passes(tmp_path: Path) -> None:
    store = _record(tmp_path, {WELLS_PUMPED_METRIC: 99.6})
    try:
        (validity,) = store.facts.validities
        assert validity.passed is True
    finally:
        store.close()


# Best is the highest nse, the lowest rmse and the pbias closest to zero.
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
def test_selector_follows_the_metric(scored, metric, best, worst) -> None:
    cat, ids = scored
    assert cat.resolve(f"@best:{metric}") == ids[best]
    assert cat.resolve(f"@worst:{metric}") == ids[worst]
    assert cat.best("p", metric).sim_id == ids[best]
    assert cat.worst("p", metric).sim_id == ids[worst]


def test_rank_best_first(scored) -> None:
    cat, ids = scored
    assert cat.rank("p", "rmse", n=3).sim_ids == [ids["b"], ids["a"], ids["c"]]
    # The raw order stays reachable for a metric with no direction.
    assert cat.rank("p", "rmse", n=3, ascending=False).sim_ids == [ids["c"], ids["a"], ids["b"]]


def test_metric_without_direction(scored) -> None:
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


def test_rank_refuses_two_windows(windows, tmp_path) -> None:
    ids = windows
    root = tmp_path / "demo"
    with pytest.raises(MixedWindowsError, match="--mixed-windows"):
        rank_simulations("demo", workspace=root, metric="nse")
    with pytest.raises(MixedWindowsError):
        rank_simulations("demo", workspace=root, metric="nse", station="J0014010")
    frame = rank_simulations("demo", workspace=root, metric="nse", mixed_windows=True)
    assert frame["sim_id"].astype(str).tolist()[0] == ids["short"]


def test_rank_one_station(stations, tmp_path) -> None:
    ids = stations
    root = tmp_path / "demo"
    with pytest.raises(MixedWindowsError, match="J002"):
        rank_simulations("demo", workspace=root, metric="nse")
    frame = rank_simulations("demo", workspace=root, metric="nse", station="J001")
    assert frame["sim_id"].astype(str).tolist() == [ids["a1"], ids["a2"]]


def _parse(argv: list[str]) -> argparse.Namespace:
    from hydromodpy.cli.main import _build_parser

    return _build_parser().parse_args(["show", ".", "--rank", "nse", *argv])


def test_command_refuses_then_forces(windows, tmp_path, capsys) -> None:
    root = str(tmp_path / "demo")
    args = _parse(["-w", root, "-n", "3"])
    with pytest.raises(MixedWindowsError, match="--mixed-windows") as stopped:
        args._handler(args)
    assert exit_code_for(stopped.value) == EXIT_VALIDATION

    args = _parse(["-w", root, "-n", "3", "--mixed-windows"])
    args._handler(args)
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("TOP#1: short")
    assert "window=2020-10-01..2020-12-29" in out


# Every budget term a solver writes has a descriptor in the field registry.
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


@pytest.mark.parametrize("term", _written_terms())
def test_budget_term_in_registry(term: str) -> None:
    descriptor = field_registry.get(term)
    assert descriptor.zarr_path == f"budget/{term}"
    assert descriptor.units == "m3 s-1"
    assert descriptor.derived_by == "solver"


def test_cell_budget_not_in_registry() -> None:
    assert not field_registry.has("cell_budget")


def test_virtual_field_names() -> None:
    assert set(VIRTUAL_FIELDS) <= set(VIRTUAL_FIELD_NAMES)


# Runs ranked together share one rule: station, variable, window and version.
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


def test_mixed_windows_is_a_data_error() -> None:
    assert issubclass(MixedWindowsError, DataError)
    assert not hasattr(ranking, "MixedWindowsError")


@pytest.mark.parametrize(
    ("second", "said"),
    [
        (("a", "J002", "discharge", 0.9), "site a"),
        (("b", "P002", "groundwater_level", 0.9), "groundwater_level"),
    ],
    ids=["two-stations-inside-one-site", "two-variables-across-the-cohort"],
)
def test_two_rules_refused(second, said) -> None:
    frame = _rows(("a", "J001", "discharge", 0.8), second)

    with pytest.raises(MixedWindowsError, match=said):
        ranking.rank_rows(frame, "nse", by="site")


def test_one_rank_key() -> None:
    from hydromodpy.project.launch import summary
    from hydromodpy.results.run import group

    assert ranking.rank_key is group.rank_key
    assert not hasattr(summary, "rank_key")


# The direction table, the run kernels and the calibration criteria name the same metrics.
PRODUCERS = {
    "the run kernels": set(RUN_METRIC_NAMES),
    "the calibration criteria": set(CALIBRATION_METRICS),
}


def test_every_produced_name_has_direction() -> None:
    for producer, names in PRODUCERS.items():
        assert names <= set(METRIC_SENSE), (
            f"{producer} write(s) without a direction: {sorted(names - set(METRIC_SENSE))}"
        )


def test_every_direction_is_produced() -> None:
    produced = set().union(*PRODUCERS.values())
    assert set(METRIC_SENSE) <= produced, (
        f"a direction nothing produces: {sorted(set(METRIC_SENSE) - produced)}"
    )


def test_retired_name_not_known() -> None:
    assert not set(RETIRED_METRIC_NAMES) & set(METRIC_SENSE)


# The old spelling log_nse is refused with the name to write.
def test_old_name_refused(tmp_path: Path) -> None:
    root = make_project(tmp_path / "demo")
    seal_run(root, "only")
    rebuild_index(root)
    with Catalog(root) as catalog:
        with pytest.raises(SimulationNotFoundError, match="was renamed: write 'nse_log'"):
            catalog.resolve("@best:log_nse")
    with pytest.raises(UnrankedMetricError, match="write 'nse_log'"):
        metric_rank_sql("log_nse", best=True)


# A 90-day nse of 0.97 never ranks above a 5-year nse of 0.60 unless mixed_windows is set.
@pytest.fixture
def windows_catalog(windows, tmp_path):
    with Catalog(tmp_path / "demo") as cat:
        yield cat, windows


@pytest.fixture
def stations_catalog(stations, tmp_path):
    with Catalog(tmp_path / "demo") as cat:
        yield cat, stations


@pytest.mark.parametrize("call", ["best", "worst", "rank"])
def test_methods_refuse_two_windows(windows_catalog, call) -> None:
    cat, _ids = windows_catalog
    with pytest.raises(MixedWindowsError, match="--mixed-windows") as refused:
        getattr(cat, call)("demo", "nse")
    assert "2016-01-01 to 2020-12-31" in str(refused.value)
    assert "2020-10-01 to 2020-12-29" in str(refused.value)


def test_mixed_windows_forces(windows_catalog) -> None:
    cat, ids = windows_catalog
    assert cat.best("demo", "nse", mixed_windows=True).sim_id == ids["short"]
    assert cat.worst("demo", "nse", mixed_windows=True).sim_id == ids["long2"]
    ranked = cat.rank("demo", "nse", n=3, mixed_windows=True)
    assert ranked.sim_ids == [ids["short"], ids["long"], ids["long2"]]


def test_named_station_needs_one_window(windows_catalog) -> None:
    cat, ids = windows_catalog
    with pytest.raises(MixedWindowsError):
        cat.resolve("@best:nse@J0014010")
    assert cat.resolve("@best:nse@J0014010", mixed_windows=True) == ids["short"]


def test_filter_refuses_two_windows(windows_catalog) -> None:
    cat, ids = windows_catalog
    with pytest.raises(MixedWindowsError, match="--mixed-windows"):
        cat.find(nse_gt=0.5)
    # A filter that names no metric ranks nothing.
    assert len(cat.find(status="completed")) == 3
    assert set(cat.find(nse_gt=0.5, mixed_windows=True).sim_ids) == set(ids.values())


def test_filter_under_one_rule(stations_catalog) -> None:
    cat, ids = stations_catalog
    assert set(cat.find(site="J001", nse_gt=0.75).sim_ids) == {ids["a1"]}


def test_accessor_refuses_two_windows(windows_catalog) -> None:
    cat, ids = windows_catalog
    runs = ProjectRunsAccessor(SimpleNamespace(_store=cat, _project_name="demo"))
    with pytest.raises(MixedWindowsError, match="--mixed-windows"):
        runs.best("nse")
    assert runs.best("nse", mixed_windows=True).sim_id == ids["short"]
