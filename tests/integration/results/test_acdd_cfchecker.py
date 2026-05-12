"""Integration test: export a Zarr to NetCDF and validate with cfchecker.

Skipped unless ``cfchecker`` is installed in the current environment. Install
manually with ``pip install cfchecker`` to run this test.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from hydromodpy.results.zarr_store import SimulationZarr

HAS_CFCHECKER = (
    shutil.which("cfchecker") is not None or importlib.util.find_spec("cfchecker") is not None
)


@pytest.mark.skipif(
    not HAS_CFCHECKER,
    reason="cfchecker not installed, install via 'pip install cfchecker'",
)
def test_acdd_zarr_passes_cfchecker(tmp_path: Path) -> None:
    sz = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=4, n_layers=1)
    try:
        sz.write_time(np.array([0, 86400, 172800], dtype="int64"))
        sz.write_crs(crs_wkt="EPSG:4326", grid_mapping_name="latitude_longitude")
        sz.write_mesh(
            vertices=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]),
            face_node_connectivity=np.array([[0, 1, 2, 3]], dtype="int32"),
            z_interfaces=np.array([0.0, -10.0]),
            topography=np.array([5.0]),
        )
        sz.write_field("head", 0, np.array([1.0, 2.0, 3.0, 4.0]), n_timesteps=3)
        sz.write_field("head", 1, np.array([1.5, 2.5, 3.5, 4.5]))
        sz.write_field("head", 2, np.array([2.0, 3.0, 4.0, 5.0]))
        sz.write_acdd_root_attrs(
            sim_row={
                "sim_id": "abc",
                "name": "compliance",
                "project": "p",
                "solver": "modflow6",
                "period_start": "2020-01-01",
                "period_end": "2020-01-03",
                "time_unit": "day",
                "contact_email": "x@y.z",
            },
            runs_env={"user_name": "u", "hydromodpy_version": "2.0.0", "rng_seed": 0},
        )
        ds = sz.to_xarray()
    finally:
        sz.close()

    nc_path = tmp_path / "compliance.nc"
    ds.to_netcdf(nc_path)
    result = subprocess.run(
        ["cfchecker", "-a", str(nc_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    # cfchecker exits 0 if no errors; warnings are accepted (>0 only when
    # the file has hard CF errors).
    assert result.returncode == 0, (
        f"cfchecker failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
