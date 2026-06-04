"""Unit tests for the GR4J flow extractor output adapter."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.lumped import Gr4jFlowExtractor
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


class TestGr4jFlowExtractor:
    def test_discharge_stored(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")

        idx = pd.date_range("2020-01-01", periods=30, freq="D")
        q = pd.Series(np.random.default_rng(1).random(30), index=idx, name="Q")

        adapter = Gr4jFlowExtractor()
        adapter.extract_from_memory(sid, catalog, discharge=q)

        result = catalog.query_timeseries(sid, "outlet", "discharge")
        assert len(result) == 30
        np.testing.assert_array_almost_equal(result.values, q.values)

    def test_extra_series(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")

        idx = pd.date_range("2020-01-01", periods=10, freq="D")
        adapter = Gr4jFlowExtractor()
        adapter.extract_from_memory(
            sid,
            catalog,
            extra={"evap": pd.Series(range(10), index=idx, dtype=float)},
            station_id="BV1",
        )

        result = catalog.query_timeseries(sid, "BV1", "evap")
        assert len(result) == 10

    def test_derive_noop(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")
        adapter = Gr4jFlowExtractor()
        adapter.derive(sid, catalog)  # should not raise
