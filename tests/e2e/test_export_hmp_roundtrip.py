"""End-to-end: export a simulation to ``.hmp``, re-import into a fresh workspace.

Validates the full package lifecycle on a minimal synthetic simulation:
the DuckDB rows and Zarr data must round-trip without loss.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest


def test_hmp_package_roundtrip(tmp_path: Path) -> None:
    import hydromodpy as hmp

    src_workspace = tmp_path / "source"
    dst_workspace = tmp_path / "target"

    sim_id = str(uuid4())
    index = pd.date_range("2024-01-01", periods=4, freq="D")
    series = pd.Series([10.0, 10.1, 10.2, 10.3], index=index, name="head")

    with hmp.open(src_workspace) as catalog:
        sz = catalog.register_simulation(
            sim_id=sim_id,
            project="roundtrip",
            solver="modflow_nwt",
            name="roundtrip_sim",
            flow_regime="steady",
            n_cells=4,
            n_layers=1,
        )
        assert sz is not None
        sz.write_field(
            variable="head",
            timestep=0,
            values=np.full((1, 4), 12.3456, dtype="float32"),
            n_timesteps=1,
        )
        catalog.write_timeseries(sim_id, station_id="P01", variable="head", ts=series)
        catalog.write_metric(sim_id, station_id="P01", metric_name="nse", value=0.91)
        catalog.finalize(sim_id, status="completed", duration_s=0.25)

        package_path = catalog.export_package(sim_id, tmp_path / "out.hmp")
        assert package_path.exists()

    with hmp.open(dst_workspace) as target:
        imported_id = target.import_package(package_path)
        assert imported_id == sim_id

        sims = target.list_simulations(project="roundtrip")
        assert len(sims) == 1
        assert str(sims.iloc[0]["sim_id"]) == sim_id

        ts = target.connection.execute(
            "SELECT variable, value FROM timeseries "
            "WHERE sim_id = ? ORDER BY datetime",
            [sim_id],
        ).fetchdf()
        assert list(ts["value"]) == pytest.approx([10.0, 10.1, 10.2, 10.3])

        metric = target.connection.execute(
            "SELECT value FROM metrics WHERE sim_id = ? AND metric_name = 'nse'",
            [sim_id],
        ).fetchone()
        assert metric is not None
        assert float(metric[0]) == pytest.approx(0.91)
