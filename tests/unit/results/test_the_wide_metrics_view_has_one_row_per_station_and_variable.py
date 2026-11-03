"""``v_metrics_wide`` gives one row per (run, station, variable), not one per run.

It took ``MAX`` over every station and variable of a run, so the discharge and the
level of one station came out as one row holding the best of both. The index table
``metrics`` names the period of each row (``window_name``) and the view keeps the
headline period only.
"""

from __future__ import annotations

import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.metric_rows import headline_row
from tests._helpers.run_stores import open_run_store


def _row(station: str, variable: str, metric: str, value: float) -> MetricRow:
    return headline_row(metric, value, station=station, variable=variable, n_samples=1827)


@pytest.fixture
def cat(tmp_path):
    project = tmp_path / "p"
    store = open_run_store(project, "a", create_zarr=False)
    for row in (
        _row("S1", "discharge", "nse", 0.6),
        _row("S1", "discharge", "rmse", 2.0),
        _row("S1", "level", "nse", 0.2),
        _row("S2", "discharge", "nse", 0.9),
        headline_row("nse", 0.1, station="S1", window_name="validation", window_role="validation"),
    ):
        store.facts.put_metric(row)
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog


def test_one_row_per_station_and_variable(cat) -> None:
    wide = cat.sql("SELECT station_id, variable, nse, rmse FROM v_metrics_wide")
    rows = {(r.station_id, r.variable): (r.nse, r.rmse) for r in wide.itertuples()}
    assert len(wide) == 3  # the validation period of S1 stays beside the headline
    assert rows[("S1", "discharge")] == (0.6, 2.0)
    assert rows[("S1", "level")][0] == 0.2
    assert rows[("S2", "discharge")][0] == 0.9


def test_the_index_table_names_the_period_of_each_row(cat) -> None:
    columns = set(cat.sql("SELECT * FROM metrics").columns)
    assert not columns & {"period_start", "period_end", "nse_window_start", "nse_n"}
    assert {"window_name", "window_role", "window_start", "window_end", "n_samples"} <= columns
