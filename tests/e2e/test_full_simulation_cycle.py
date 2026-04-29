"""End-to-end: open a workspace, register a sim, query it back, tear down.

The goal is not to exercise MODFLOW but to validate that the public
catalog API stays composable across the lifecycle: create workspace →
register simulation → write outputs → query by project → close.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest


def test_open_register_query_roundtrip(e2e_workspace: Path) -> None:
    import hydromodpy as hmp

    with hmp.open(e2e_workspace) as catalog:
        sim_id = str(uuid4())
        catalog.register_simulation(
            sim_id=sim_id,
            project="e2e_demo",
            solver="modflow_nwt",
            name="toy_sim",
            flow_regime="steady",
        )
        catalog.write_parameters(
            sim_id,
            [{"param_name": "k", "zone_id": "default", "value": 1e-4, "unit": "m/s"}],
        )
        index = pd.date_range("2024-01-01", periods=5, freq="D")
        series = pd.Series(np.linspace(10.0, 10.2, 5), index=index, name="head")
        catalog.write_timeseries(sim_id, station_id="P01", variable="head", ts=series)
        catalog.write_metric(sim_id, station_id="P01", metric_name="nse", value=0.82)
        catalog.finalize(sim_id, status="completed", duration_s=0.1)

    # Re-open the workspace and verify every write is durable.
    with hmp.open(e2e_workspace) as catalog2:
        sims = catalog2.list_simulations(project="e2e_demo")
        assert len(sims) == 1
        assert sims.iloc[0]["solver"] == "modflow_nwt"

        metrics = catalog2._connection.execute(
            "SELECT metric_name, value FROM metrics WHERE sim_id = ?",
            [sim_id],
        ).fetchdf()
        assert list(metrics["metric_name"]) == ["nse"]
        assert float(metrics["value"].iloc[0]) == pytest.approx(0.82)

        params = catalog2._connection.execute(
            "SELECT param_name, value FROM parameters WHERE sim_id = ?",
            [sim_id],
        ).fetchdf()
        assert list(params["param_name"]) == ["k"]
        assert float(params["value"].iloc[0]) == pytest.approx(1e-4)
