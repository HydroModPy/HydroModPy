"""Shared fixtures for the FAIR exports integration tier."""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import SimulationCatalog


@pytest.fixture
def fair_catalog(tmp_path: Path) -> SimulationCatalog:
    """A live :class:`SimulationCatalog` with one finalised simulation row."""
    cat = SimulationCatalog(tmp_path / "ws")
    yield cat
    cat.close()


def populate_simulation(catalog: SimulationCatalog, *, project: str = "test") -> str:
    """Insert one simulation with metrics, timeseries, parameters and provenance."""
    sid = str(uuid.uuid4())
    reg = catalog.register_simulation(
        sid,
        name="fair-sim",
        project=project,
        solver="modflow6",
        n_cells=8,
        n_layers=1,
    )
    if reg.zarr is not None:
        reg.zarr.close()
    catalog.write_parameters(
        sid,
        [
            {"param_name": "K", "value": 1.5, "unit": "m/d"},
            {"param_name": "S", "value": 1e-4, "unit": "1/m"},
        ],
    )
    idx = pd.date_range("2020-01-01", periods=6, freq="D")
    catalog.write_timeseries(sid, "P01", "head", pd.Series(np.ones(6), index=idx))
    catalog.write_metric(sid, "P01", "nse", 0.91)
    catalog.write_metric(sid, "P01", "kge", 0.87)
    catalog.write_provenance(sid, "dem", "https://example.org/dem.tif", np.ones(8))
    # Patch bbox + period + crs columns so STAC + RO-Crate carry real values.
    catalog.connection.execute(
        "UPDATE simulations SET bbox_xmin=?, bbox_ymin=?, bbox_xmax=?, bbox_ymax=?, "
        "crs_wkt=?, crs_epsg=?, period_start=?, period_end=? WHERE sim_id = ?",
        [0.0, 0.0, 1000.0, 1000.0, "EPSG:2154", 2154, "2020-01-01", "2020-01-06", sid],
    )
    catalog.finalize(sid, "completed", 1.0)
    return sid


__all__ = ["fair_catalog", "populate_simulation"]
