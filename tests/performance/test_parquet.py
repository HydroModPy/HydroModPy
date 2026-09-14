"""Timeseries write/query baseline benchmarks (Catalog Parquet backend).

Guards the thin HydroModPy tabular wrapper (``write_timeseries`` /
``query_timeseries``) backed by Parquet that the calibration and extraction
layers call. A regression in the Parquet timeseries round-trip shows up here
as a pairwise-ratio drift in ``perf.yml``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests._helpers.fixtures_catalog import simulation_catalog

pytestmark = pytest.mark.performance

N_STEPS = 8_760  # one year of hourly steps
SID = "00000000-0000-0000-0000-0000000000b2"


@pytest.fixture(scope="function")
def series() -> pd.Series:
    """Return an 8_760-step hourly discharge series."""
    idx = pd.date_range("2020-01-01", periods=N_STEPS, freq="h")
    val = np.random.default_rng(seed=42).random(N_STEPS)
    return pd.Series(val, index=idx, name="discharge")


@pytest.fixture(scope="function")
def timeseries_catalog(tmp_path: Path, series: pd.Series):
    """Catalog holding one simulation with the discharge series written."""
    with simulation_catalog(tmp_path / "workspace") as cat:
        reg = cat.register_simulation(SID, project="perf", solver="gr4j")
        if reg.zarr is not None:
            reg.zarr.close()
        cat.write_timeseries(SID, "outlet", "discharge", series, unit="m3/s")
        yield cat


@pytest.mark.benchmark(group="parquet")
def test_parquet_write_timeseries(benchmark, tmp_path: Path, series: pd.Series) -> None:
    """Write an 8_760-step timeseries through the catalog Parquet wrapper."""
    with simulation_catalog(tmp_path / "ws_write") as cat:
        reg = cat.register_simulation(SID, project="perf", solver="gr4j")
        if reg.zarr is not None:
            reg.zarr.close()

        def _write() -> None:
            cat.write_timeseries(SID, "outlet", "discharge", series, unit="m3/s")

        benchmark(_write)


@pytest.mark.benchmark(group="parquet")
def test_parquet_query_timeseries(benchmark, timeseries_catalog) -> None:
    """Query an 8_760-step timeseries through the catalog Parquet wrapper."""

    def _query() -> int:
        return len(timeseries_catalog.query_timeseries(SID, "outlet", "discharge"))

    benchmark(_query)
