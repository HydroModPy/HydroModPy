"""End-to-end: the cyclic spin-up driver over real MODFLOW 6 runs.

Reuses the config-declared lake fixtures from ``test_lake_project_e2e`` (committed
regional DEM + synthetic lake, structured grid so the mesh is deterministic across
cycles) and drives ``hmp.spinup`` for real. It proves the driver:

* runs several real cycles and converges (this small 30-day model reaches its
  dynamic equilibrium fast);
* actually restarts each cycle from the previous one -- cycle 1's initial head
  equals cycle 0's final head, and that head is a solved, spatially varying field
  (not the flat ``top`` initial condition);
* emits a reusable converged-state Zarr for ``[flow] restart_from``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from tests.e2e.test_lake_project_e2e import (
    _write_lake_abacus_fixture,
    _write_lake_config,
    _write_lake_geometry_fixture,
)
from tests.regression.golden_utils import assert_required_executables


def _read_head_stack(zarr_path: str) -> np.ndarray:
    """Return the (ntime, nlay, ncpl) head stack from a (possibly zipped) Zarr."""
    import zarr

    if zarr_path.endswith(".zip"):
        root = zarr.open(zarr.storage.ZipStore(zarr_path, mode="r"), mode="r")
    else:
        root = zarr.open(zarr_path, mode="r")
    head = np.asarray(root["head"])
    return np.where(np.abs(head) > 1e20, np.nan, head)


@pytest.mark.e2e
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
def test_spinup_e2e_converges_and_restarts_each_cycle(tmp_path: Path) -> None:
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )
    import hydromodpy as hmp

    out = tmp_path / "spinup_run"
    out.mkdir(parents=True, exist_ok=True)
    data_dir = out / "data"
    geom = _write_lake_geometry_fixture(data_dir)
    abac = _write_lake_abacus_fixture(data_dir)
    config_path = out / "run_spinup_e2e.toml"
    _write_lake_config(config_path, geometry_path=geom, abacus_path=abac)
    with config_path.open("a", encoding="utf-8") as fh:
        fh.write("\n[spinup]\nmax_cycles = 4\ntol_head = 0.05\ntol_stage = 0.05\n")

    result = hmp.spinup(config_path)

    # Multiple real cycles ran and the loop converged to a reusable state.
    assert result.n_cycles >= 2, f"expected >= 2 cycles, got {result.n_cycles}"
    assert result.converged, "spin-up did not converge on the equilibrium model"
    assert result.restart_from.endswith(FIELDS_STORE_NAME)
    assert Path(result.restart_from).exists()

    # Restart correctness: cycle 1 starts exactly where cycle 0 ended, and that
    # start field is a solved, spatially varying head (not the flat top IC).
    c0 = _read_head_stack(result.cycles[0].zarr_path)
    c1 = _read_head_stack(result.cycles[1].zarr_path)
    assert c0.shape == c1.shape
    c0_final = c0[-1]
    c1_initial = c1[0]
    finite = np.isfinite(c0_final) & np.isfinite(c1_initial)
    assert np.nanmax(np.abs(c1_initial[finite] - c0_final[finite])) < 1e-3, (
        "cycle 1 did not restart from cycle 0's final head"
    )
    assert np.nanstd(c1_initial[finite]) > 0.1, (
        "cycle 1 initial head is flat; it looks like the top IC, not a restart"
    )
