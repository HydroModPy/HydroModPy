"""The NSE on log discharge has one name, ``nse_log``, in calibration and in the catalog.

The run panel stored it as ``log_nse`` while a calibration scores ``nse_log``,
so ``@best:nse_log`` found no run. Old rows are renamed by the catalog
migration and by a reindex; the old name is refused with the one to write.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.catalog import Catalog, SimulationNotFoundError
from hydromodpy.results.catalog.constants import (
    OUTLET_STATION,
    UnrankedMetricError,
    metric_rank_sql,
)
from hydromodpy.results.catalog.migrations import MIGRATIONS_DIR
from hydromodpy.results.catalog.reindex import rebuild_index
from hydromodpy.simulation.extraction.derivation.fit_metrics import write_fit_metrics
from tests._helpers.fixtures_catalog import simulation_catalog


def _completed(cat: Catalog, name: str, metrics: dict[str, float]) -> str:
    sid = str(uuid.uuid4())
    cat.register_simulation(sid, project="p", solver="modflow6", name=name)
    for metric, value in metrics.items():
        cat.write_metric(sid, OUTLET_STATION, metric, value, variable="discharge")
    cat.finalize(sid, "completed")
    return sid


def test_the_selector_finds_the_calibration_name(tmp_path: Path) -> None:
    with simulation_catalog(tmp_path / "ws") as cat:
        _completed(cat, "low", {"nse_log": 0.2})
        high = _completed(cat, "high", {"nse_log": 0.8})
        assert cat.resolve("@best:nse_log") == high


def test_the_old_name_is_refused_with_the_new_one(tmp_path: Path) -> None:
    with simulation_catalog(tmp_path / "ws") as cat:
        _completed(cat, "only", {"nse_log": 0.5})
        with pytest.raises(SimulationNotFoundError, match="was renamed: write 'nse_log'"):
            cat.resolve("@best:log_nse")
    with pytest.raises(UnrankedMetricError, match="write 'nse_log'"):
        metric_rank_sql("log_nse", best=True)


def test_the_migration_renames_stored_rows() -> None:
    sql = (MIGRATIONS_DIR / "0005_metric_nse_log.sql").read_text(encoding="utf-8")
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE metrics (sim_id VARCHAR, station_id VARCHAR, variable VARCHAR, "
            "metric_name VARCHAR, value DOUBLE, "
            "PRIMARY KEY (sim_id, station_id, variable, metric_name))"
        )
        conn.execute(
            "INSERT INTO metrics VALUES "
            "('a', 's', 'discharge', 'log_nse', 0.4), "
            "('b', 's', 'discharge', 'log_nse', 0.1), "
            "('b', 's', 'discharge', 'nse_log', 0.2)"
        )
        conn.execute(sql)
        rows = conn.execute(
            "SELECT sim_id, metric_name, value FROM metrics ORDER BY sim_id"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("a", "nse_log", 0.4), ("b", "nse_log", 0.2)]


def test_a_reindex_renames_the_rows_of_an_old_run(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    with Catalog(root) as cat:
        sid = _completed(cat, "old", {"log_nse": 0.7, "nse": 0.5})
    catalog_path_for(root).unlink()

    rebuild_index(root)

    with Catalog(root, read_only=True) as cat:
        names = {
            row[0]
            for row in cat.backend.fetch_all(
                "SELECT metric_name FROM metrics WHERE sim_id = ?", [sid]
            )
        }
    assert names == {"nse_log", "nse"}


def test_the_run_panel_writes_the_calibration_name() -> None:
    class _Connection:
        def __init__(self, frame: pd.DataFrame) -> None:
            self._frame = frame

        def execute(self, _sql: str, _params: list) -> _Connection:
            return self

        def df(self) -> pd.DataFrame:
            return self._frame

    class _Store:
        def __init__(self, frame: pd.DataFrame) -> None:
            self.connection = _Connection(frame)
            self.names: list[str] = []

        def write_metric(self, sim_id, station_id, metric_name, value, **kwargs):
            self.names.append(metric_name)

    days = pd.date_range("2001-01-01", periods=20, freq="D", tz="UTC")
    values = np.linspace(1.0, 3.0, 20)
    rows = [
        {"station_id": "_c", "variable": "discharge", "time": t, "value": v}
        for t, v in zip(days.shift(1, freq="D"), values, strict=True)
    ] + [
        {"station_id": "G", "variable": "discharge_obs", "time": t, "value": v}
        for t, v in zip(days, values, strict=True)
    ]
    store = _Store(pd.DataFrame(rows))
    write_fit_metrics("sim", store)
    assert "nse_log" in store.names
    assert "log_nse" not in store.names
