"""SFR series land in a REAL run store and survive the seal and the index.

The shared standalone model runs real MF6, the production
``Modflow6OutputAdapter`` extracts into the real store of a claimed run
(Zarr/Parquet), the run is SEALED and the project INDEXED, and the per-reach
series are queried back through the index reader under
``station_id = <network>:<reach>`` and compared to the values read directly
from the obs CSV.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter
from hydromodpy.solver.modflow6.extractors.sfr import sfr_station_id
from tests._helpers.run_stores import open_run_store
from tests.integration.solver._sfr_models import (
    NETWORK_ID,
    run_standalone_sfr_model,
)
from tests.unit.solver.modflow_common.solver_runs import keep_all, solved_run


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_sfr_series_roundtrip_through_reopened_store(tmp_path: Path) -> None:
    model_ws = tmp_path / "model"
    model_ws.mkdir()
    network, obs = run_standalone_sfr_model(model_ws, connected=True)
    terminal = max(reach.ifno for reach in network.reaches)

    catalog_ws = tmp_path / "catalog_ws"
    store = open_run_store(catalog_ws, "sfr_roundtrip", create_zarr=False)
    sim_id = store.sim_id
    try:
        Modflow6OutputAdapter().extract(solved_run(model_ws), store, keep_all)
    except BaseException:
        store.close()
        raise
    seal_completed(store)
    rebuild_index(catalog_ws)

    # The store value must come from the sealed run read through the index, not memory.
    reopened = Catalog(catalog_ws)
    try:
        flow = reopened.query_timeseries(
            sim_id, sfr_station_id(NETWORK_ID, terminal), "ext_outflow"
        )
        assert not flow.empty
        # Stored positive (stream POV), m3/s; the CSV reports the outflow negative.
        assert np.allclose(flow.iloc[-1], -obs[f"R{terminal}_EXT_OUTFLOW"], rtol=1e-12)

        dsflow = reopened.query_timeseries(sim_id, sfr_station_id(NETWORK_ID, 0), "downstream_flow")
        assert not dsflow.empty
        assert np.allclose(dsflow.iloc[-1], -obs["R0_DOWNSTREAM_FLOW"], rtol=1e-12)

        # gw_exchange is negated to the stream POV: a losing reach reads negative.
        exchange = reopened.query_timeseries(sim_id, sfr_station_id(NETWORK_ID, 0), "gw_exchange")
        assert not exchange.empty
        assert np.allclose(exchange.iloc[-1], -obs["R0_GW_EXCHANGE"], rtol=1e-12)

        # Every reach has its stage series (states stay in meters, no scaling).
        for reach in network.reaches:
            stage = reopened.query_timeseries(
                sim_id, sfr_station_id(NETWORK_ID, reach.ifno), "stage"
            )
            assert len(stage) > 0
            assert np.isfinite(stage.iloc[-1])
    finally:
        reopened.close()
