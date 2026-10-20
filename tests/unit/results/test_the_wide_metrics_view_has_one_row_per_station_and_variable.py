"""``v_metrics_wide`` gives one row per (run, station, variable), not one per run.

It took ``MAX`` over every station and variable of a run, so the discharge and the
level of one station came out as one row holding the best of both. The index table
``metrics`` also carried ``n_samples`` (a copy of ``nse_n``) and ``period_start`` /
``period_end``, which nothing filled.
"""

from __future__ import annotations

from datetime import date

import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.metric_rule import METRIC_RULE_VERSION
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store


def _row(station: str, variable: str, metric: str, value: float) -> MetricRow:
    return MetricRow(
        station=station,
        variable=variable,
        metric=metric,
        value=value,
        nse_window_start=date(2016, 1, 1),
        nse_window_end=date(2020, 12, 31),
        nse_n=1827,
        metric_rule_version=METRIC_RULE_VERSION,
    )


@pytest.fixture
def cat(tmp_path):
    project = tmp_path / "p"
    store = open_run_store(project, "a", create_zarr=False)
    for row in (
        _row("S1", "discharge", "nse", 0.6),
        _row("S1", "discharge", "rmse", 2.0),
        _row("S1", "level", "nse", 0.2),
        _row("S2", "discharge", "nse", 0.9),
    ):
        store.facts.put_metric(row)
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog


def test_one_row_per_station_and_variable(cat) -> None:
    wide = cat.sql("SELECT station_id, variable, nse, rmse FROM v_metrics_wide")
    rows = {(r.station_id, r.variable): (r.nse, r.rmse) for r in wide.itertuples()}
    assert len(wide) == 3
    assert rows[("S1", "discharge")] == (0.6, 2.0)
    assert rows[("S1", "level")][0] == 0.2
    assert rows[("S2", "discharge")][0] == 0.9


def test_the_index_table_drops_the_columns_nothing_filled(cat) -> None:
    columns = set(cat.sql("SELECT * FROM metrics").columns)
    assert not columns & {"n_samples", "period_start", "period_end"}
    assert {"nse_n", "nse_window_start", "nse_window_end"} <= columns
