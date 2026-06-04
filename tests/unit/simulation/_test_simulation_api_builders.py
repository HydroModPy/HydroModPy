from __future__ import annotations

import uuid

import numpy as np
import pandas as pd
import pytest

from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


def _sid():
    return str(uuid.uuid4())


def _register(catalog, sim_id=None, **kw):
    sid = sim_id or _sid()
    defaults = dict(project="test", solver="modflow6", n_cells=10, n_layers=2)
    defaults.update(kw)
    reg = catalog.register_simulation(sid, **defaults)
    if reg.zarr is not None:
        reg.zarr.close()
    return sid


def _populate(catalog, sid):
    catalog.write_parameters(
        sid,
        [
            {"param_name": "K", "value": 1.5, "unit": "m/d"},
            {"param_name": "Sy", "value": 0.05, "unit": "-"},
        ],
    )
    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    catalog.write_timeseries(sid, "P01", "head", pd.Series(np.arange(10.0), index=idx))
    catalog.write_budget(sid, 0, "z1", "recharge", 100.0, 0.0)
    catalog.write_mass_balance(sid, 0, 100.0, 95.0, 5.0)
    catalog.write_metric(sid, "P01", "nse", 0.85)
    catalog.write_metric(sid, "P01", "kge", 0.78)
    catalog.finalize(sid, "completed", 42.0)
