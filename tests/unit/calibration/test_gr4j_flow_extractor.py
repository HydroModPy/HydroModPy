"""Unit tests for the GR4J flow extractor output adapter."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.lumped import Gr4jFlowExtractor
from tests._helpers.run_stores import open_run_store


@pytest.fixture
def store(tmp_path):
    """The open store of a claimed GR4J run, the object the extractor writes into."""
    with open_run_store(tmp_path / "project", "gr4j", solver="gr4j", create_zarr=False) as opened:
        yield opened


class TestGr4jFlowExtractor:
    def test_discharge_stored(self, store):
        sid = store.sim_id

        idx = pd.date_range("2020-01-01", periods=30, freq="D")
        q = pd.Series(np.random.default_rng(1).random(30), index=idx, name="Q")

        adapter = Gr4jFlowExtractor()
        adapter.extract_from_memory(sid, store, discharge=q)

        result = store.query_timeseries(sid, "outlet", "discharge")
        assert len(result) == 30
        np.testing.assert_array_almost_equal(result.values, q.values)

    def test_extra_series(self, store):
        sid = store.sim_id

        idx = pd.date_range("2020-01-01", periods=10, freq="D")
        adapter = Gr4jFlowExtractor()
        adapter.extract_from_memory(
            sid,
            store,
            extra={"evap": pd.Series(range(10), index=idx, dtype=float)},
            station_id="BV1",
        )

        result = store.query_timeseries(sid, "BV1", "evap")
        assert len(result) == 10
