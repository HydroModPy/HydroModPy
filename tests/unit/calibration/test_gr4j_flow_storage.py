"""Cover the GR4J flow extractor branches not exercised elsewhere.

``test_gr4j_flow_extractor.py`` already covers discharge and the ``extra``
mapping. This file targets the remaining dark lines: the ``storage`` write
branch (line 65) and the binary-path ``extract`` no-op (line 33). Both run
the real extractor against the real store of a run and assert the stored
series round-trips intact and non-negative.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.lumped import Gr4jFlowExtractor
from tests._helpers.run_stores import open_run_store
from tests._helpers.tolerances import tol

ATOL = tol("regression_goldens_arrays__atol")


@pytest.fixture
def store(tmp_path):
    """The open store of a claimed GR4J run, the object the extractor writes into."""
    with open_run_store(tmp_path / "project", "gr4j", solver="gr4j", create_zarr=False) as opened:
        yield opened


def _storage_series(n: int = 25) -> pd.Series:
    """Non-negative, monotone-bounded storage from a draining reservoir."""
    idx = pd.date_range("2022-03-01", periods=n, freq="D")
    s = 80.0 * np.exp(-0.05 * np.arange(n))  # always > 0, physical recession
    return pd.Series(s, index=idx, name="storage")


class TestStorageBranch:
    def test_storage_written_and_round_trips(self, store):
        sid = store.sim_id
        storage = _storage_series()

        Gr4jFlowExtractor().extract_from_memory(sid, store, storage=storage)

        result = store.query_timeseries(sid, "outlet", "storage")
        assert len(result) == len(storage)
        np.testing.assert_allclose(
            np.sort(result.to_numpy()), np.sort(storage.to_numpy()), atol=ATOL
        )

    def test_stored_storage_is_non_negative(self, store):
        sid = store.sim_id
        storage = _storage_series()

        Gr4jFlowExtractor().extract_from_memory(sid, store, storage=storage)
        result = store.query_timeseries(sid, "outlet", "storage")
        assert (result.to_numpy() > 0).all()

    def test_discharge_and_storage_together(self, store):
        sid = store.sim_id
        idx = pd.date_range("2022-03-01", periods=25, freq="D")
        discharge = pd.Series(np.abs(np.sin(np.arange(25) / 3.0)), index=idx, name="discharge")
        storage = _storage_series()

        Gr4jFlowExtractor().extract_from_memory(
            sid, store, discharge=discharge, storage=storage, station_id="gauge"
        )

        q = store.query_timeseries(sid, "gauge", "discharge")
        s = store.query_timeseries(sid, "gauge", "storage")
        assert len(q) == 25
        assert len(s) == 25
        np.testing.assert_allclose(np.sort(s.to_numpy()), np.sort(storage.to_numpy()), atol=ATOL)


class TestNoOpBranches:
    def test_extract_binary_path_is_noop(self, store, tmp_path):
        sid = store.sim_id
        # The file-based extract() writes nothing for a lumped model.
        Gr4jFlowExtractor().extract(sid, tmp_path, store)
        with pytest.raises(KeyError):
            store.query_timeseries(sid, "outlet", "storage")

    def test_extract_from_memory_with_nothing_writes_nothing(self, store):
        sid = store.sim_id
        # All series None: no write, no raise.
        Gr4jFlowExtractor().extract_from_memory(sid, store)
        with pytest.raises(KeyError):
            store.query_timeseries(sid, "outlet", "discharge")
