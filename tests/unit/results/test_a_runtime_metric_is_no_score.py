"""The solver's runtime numbers are stored beside the scores but are not scores.

They went in as rows of ``metrics`` (station ``flow_main``, variable ``runtime``)
and came out in ``catalog show``, ``catalog diff``, ``compare_pair`` and
``v_metrics_wide`` next to the NSE. The facts and the seal still carry them, the
way the project summary reads the solve time; the index and the readers of scores
leave them out.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from hydromodpy.analysis.comparison.pairwise import compare_pair
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.metric_rule import METRIC_RULE_VERSION, MetricScore
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.simulation.extraction.post_run import record_run_execution_metrics
from tests._helpers.run_stores import open_run_store

STATION = "J0014010"
RUNTIME = {"flow_solve_time_seconds": 12.5, "water_budget_percent_discrepancy": 0.01}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "p"
    for name, nse in (("a", 0.6), ("b", 0.7)):
        store = open_run_store(root, name, create_zarr=False)
        store.facts.put_metric(
            MetricRow(
                station=STATION,
                variable="discharge",
                metric="nse",
                value=nse,
                nse_window_start=date(2016, 1, 1),
                nse_window_end=date(2020, 12, 31),
                nse_n=10,
                metric_rule_version=METRIC_RULE_VERSION,
            )
        )
        ctx = SimpleNamespace(run=SimpleNamespace(is_solver_backed=True, id="flow_main"))
        record_run_execution_metrics(
            ctx=ctx, sim_id=store.sim_id, store=store, result=SimpleNamespace(metrics=RUNTIME)
        )
        assert {row.metric for row in store.facts.metrics if row.variable == "runtime"} == set(
            RUNTIME
        )
        store.facts.score = MetricScore(
            metric="nse",
            value=nse,
            station=STATION,
            variable="discharge",
            nse_window_start=date(2016, 1, 1),
            nse_window_end=date(2020, 12, 31),
            nse_n=10,
            metric_rule_version=METRIC_RULE_VERSION,
        )
        seal_completed(store)
    rebuild_index(root)
    return root


def test_the_index_holds_no_runtime_row(project) -> None:
    with Catalog(project) as cat:
        names = set(cat.sql("SELECT metric_name FROM metrics")["metric_name"])
        variables = set(cat.sql("SELECT variable FROM metrics")["variable"])
    assert names == {"nse"}
    assert variables == {"discharge"}


def test_the_wide_view_has_no_runtime_row(project) -> None:
    with Catalog(project) as cat:
        wide = cat.sql("SELECT variable FROM v_metrics_wide")
    assert set(wide["variable"]) == {"discharge"}


def test_show_and_diff_and_compare_pair_list_scores_only(project) -> None:
    with Catalog(project) as cat:
        shown = cat["a"].metrics
        delta = cat.diff("a", "b")["metrics"]
    assert set(shown["variable"]) == {"discharge"}
    assert {key[0] for key in delta} == {"nse"}
    assert set(compare_pair("a", "b", workspace=project).reset_index()["metric_name"]) == {"nse"}
