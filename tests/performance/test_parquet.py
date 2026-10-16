"""Timeseries write/query baseline benchmarks (run store Parquet backend).

Guards the thin HydroModPy tabular wrapper (``write_timeseries`` /
``query_timeseries``) of the run store, backed by Parquet, that the
calibration and extraction layers call. A regression in the Parquet
timeseries round-trip shows up here as a pairwise-ratio drift in ``perf.yml``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests._helpers.run_stores import open_run_store

pytestmark = pytest.mark.performance

N_STEPS = 8_760  # one year of hourly steps


@pytest.fixture(scope="function")
def series() -> pd.Series:
    """Return an 8_760-step hourly discharge series."""
    idx = pd.date_range("2020-01-01", periods=N_STEPS, freq="h")
    val = np.random.default_rng(seed=42).random(N_STEPS)
    return pd.Series(val, index=idx, name="discharge")


@pytest.fixture(scope="function")
def timeseries_store(tmp_path: Path, series: pd.Series):
    """Store of one run with the discharge series written."""
    with open_run_store(tmp_path / "project", "perf", solver="gr4j", create_zarr=False) as store:
        store.write_timeseries(store.sim_id, "outlet", "discharge", series, unit="m3/s")
        yield store


@pytest.mark.benchmark(group="parquet")
def test_parquet_write_timeseries(benchmark, tmp_path: Path, series: pd.Series) -> None:
    """Write an 8_760-step timeseries through the run store Parquet wrapper."""
    with open_run_store(tmp_path / "ws_write", "perf", solver="gr4j", create_zarr=False) as store:

        def _write() -> None:
            store.write_timeseries(store.sim_id, "outlet", "discharge", series, unit="m3/s")

        benchmark(_write)


@pytest.mark.benchmark(group="parquet")
def test_parquet_query_timeseries(benchmark, timeseries_store) -> None:
    """Query an 8_760-step timeseries through the run store Parquet wrapper."""

    def _query() -> int:
        sim_id = timeseries_store.sim_id
        return len(timeseries_store.query_timeseries(sim_id, "outlet", "discharge"))

    benchmark(_query)
