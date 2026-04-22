"""Catalog fixtures for the test suite.

Provides :class:`~hydromodpy.results.catalog.SimulationCatalog` factories
that populate DuckDB with deterministic synthetic simulations for unit,
integration and e2e coverage.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import SimulationCatalog


def seed_three_simulations(catalog: SimulationCatalog) -> list[str]:
    """Register three fake simulations (nwt / mf6 / boussinesq).

    Each simulation writes one timeseries, one metric and one parameter.
    Returns the list of ``sim_id`` (UUID4 strings) in registration order.
    """
    specs = [
        ("sim_nwt", "demo", "modflow_nwt", "steady", 0.85),
        ("sim_mf6", "demo", "modflow6", "steady", 0.75),
        ("sim_bq", "demo", "boussinesq", "transient", 0.65),
    ]
    sim_ids: list[str] = []
    dates = pd.date_range("2020-01-01", periods=5, freq="D")
    for name, project, solver, regime, nse in specs:
        sid = str(uuid4())
        catalog.register_simulation(
            sim_id=sid,
            project=project,
            solver=solver,
            name=name,
            flow_regime=regime,
        )
        catalog.write_parameters(
            sid,
            [{"param_name": "k", "zone_id": "default", "value": 1e-5, "unit": "m/s"}],
        )
        ts = pd.Series(
            np.linspace(10.0, 11.0, len(dates)),
            index=dates,
            name="head",
        )
        catalog.write_timeseries(sid, station_id="P01", variable="head", ts=ts, unit="m")
        catalog.write_metric(sid, station_id="P01", metric_name="nse", value=nse)
        sim_ids.append(sid)
    return sim_ids


@pytest.fixture
def empty_catalog(tmp_path: Path) -> SimulationCatalog:
    """Empty catalog rooted in ``tmp_path/workspace``."""
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


@pytest.fixture
def populated_catalog(tmp_path: Path) -> SimulationCatalog:
    """Catalog with three fake simulations (nwt + mf6 + boussinesq)."""
    cat = SimulationCatalog(tmp_path / "workspace")
    seed_three_simulations(cat)
    yield cat
    cat.close()
