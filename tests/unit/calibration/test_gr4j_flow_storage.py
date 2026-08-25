"""Cover the GR4J flow extractor branches not exercised elsewhere.

``test_gr4j_flow_extractor.py`` already covers discharge and the ``extra``
mapping. This file targets the remaining dark lines: the ``storage`` write
branch (line 65) and the binary-path ``extract`` no-op (line 33). Both run
the real extractor against a real Catalog and assert the stored
series round-trips intact and non-negative.
"""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.lumped import Gr4jFlowExtractor
from tests._helpers.fixtures_catalog import simulation_catalog
from tests._helpers.tolerances import tol

ATOL = tol("regression_goldens_arrays__atol")


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


def _storage_series(n: int = 25) -> pd.Series:
    """Non-negative, monotone-bounded storage from a draining reservoir."""
    idx = pd.date_range("2022-03-01", periods=n, freq="D")
    s = 80.0 * np.exp(-0.05 * np.arange(n))  # always > 0, physical recession
    return pd.Series(s, index=idx, name="storage")


class TestStorageBranch:
    def test_storage_written_and_round_trips(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")
        storage = _storage_series()

        Gr4jFlowExtractor().extract_from_memory(sid, catalog, storage=storage)

        result = catalog.query_timeseries(sid, "outlet", "storage")
        assert len(result) == len(storage)
        np.testing.assert_allclose(
            np.sort(result.to_numpy()), np.sort(storage.to_numpy()), atol=ATOL
        )

    def test_stored_storage_is_non_negative(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")
        storage = _storage_series()

        Gr4jFlowExtractor().extract_from_memory(sid, catalog, storage=storage)
        result = catalog.query_timeseries(sid, "outlet", "storage")
        assert (result.to_numpy() > 0).all()

    def test_discharge_and_storage_together(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")
        idx = pd.date_range("2022-03-01", periods=25, freq="D")
        discharge = pd.Series(np.abs(np.sin(np.arange(25) / 3.0)), index=idx, name="discharge")
        storage = _storage_series()

        Gr4jFlowExtractor().extract_from_memory(
            sid, catalog, discharge=discharge, storage=storage, station_id="gauge"
        )

        q = catalog.query_timeseries(sid, "gauge", "discharge")
        s = catalog.query_timeseries(sid, "gauge", "storage")
        assert len(q) == 25
        assert len(s) == 25
        np.testing.assert_allclose(np.sort(s.to_numpy()), np.sort(storage.to_numpy()), atol=ATOL)


class TestNoOpBranches:
    def test_extract_binary_path_is_noop(self, catalog, tmp_path):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")
        # The file-based extract() writes nothing for a lumped model.
        Gr4jFlowExtractor().extract(sid, tmp_path, catalog)
        with pytest.raises(KeyError):
            catalog.query_timeseries(sid, "outlet", "storage")

    def test_extract_from_memory_with_nothing_writes_nothing(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")
        # All series None: no write, no raise.
        Gr4jFlowExtractor().extract_from_memory(sid, catalog)
        with pytest.raises(KeyError):
            catalog.query_timeseries(sid, "outlet", "discharge")
