"""The metric rows of a run count the periods a NaN simulated value took out of the window.

A run scored on a head whose cell went dry is scored on fewer periods than
the window holds, and the rows said only ``nse_n``. Each row now says how
many periods of the window it lost to a NaN simulated value (``n_sim_nan``),
in the seal, in ``metrics.parquet`` and in the ``metrics`` table of the index,
and the scoring warns. A period the record leaves empty is not counted.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.fit_metrics import score_timeseries
from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.metric_rule import DateWindow, MetricRule
from hydromodpy.results.run.sealed import metrics_frame
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store

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
        {"station_id": PIEZOMETER, "variable": "head", "time": t, "value": v}
        for t, v in simulated.items()
    ] + [
        {"station_id": PIEZOMETER, "variable": "head_obs", "time": t, "value": v}
        for t, v in observed.items()
    ]
    return pd.DataFrame(rows)


def test_every_row_counts_the_dry_periods_of_the_window(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy.results.fit_metrics"):
        scores = score_timeseries(_frame(DRY), rule=RULE)

    assert scores.rows
    assert {row.n_sim_nan for row in scores.rows} == {3}
    warned = [r.getMessage() for r in caplog.records]
    assert any("NaN" in message and PIEZOMETER in message for message in warned)


def test_a_wet_run_counts_zero_and_does_not_warn(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy.results.fit_metrics"):
        scores = score_timeseries(_frame(DRY[:0]), rule=RULE)

    assert {row.n_sim_nan for row in scores.rows} == {0}
    assert not [r for r in caplog.records if "NaN" in r.getMessage()]


def test_the_store_the_seal_and_the_index_keep_n_sim_nan(tmp_path) -> None:
    root = tmp_path / "p"
    store = open_run_store(root, "a", create_zarr=False)
    store.facts.put_metric(
        MetricRow(
            station=PIEZOMETER,
            variable="head",
            metric="nse",
            value=0.5,
            nse_window_start=WINDOW.start,
            nse_window_end=WINDOW.end,
            nse_n=20,
            n_sim_nan=3,
            metric_rule_version="2",
        )
    )
    store.write_metric(store.sim_id, PIEZOMETER, "rmse", 0.1, variable="head", n_sim_nan=3)
    table = pq.read_table(store.table_path_for(store.sim_id, "metrics")).to_pandas()
    assert table["n_sim_nan"].tolist() == [3]
    record = seal_completed(store)
    assert metrics_frame(record)["n_sim_nan"].tolist() == [3, 3]
    rebuild_index(root)

    with Catalog(root) as cat:
        frame = cat.sql("SELECT metric_name, n_sim_nan FROM metrics ORDER BY metric_name")

    assert frame.set_index("metric_name")["n_sim_nan"].to_dict() == {"nse": 3, "rmse": 3}
