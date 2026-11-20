"""MODFLOW 6 solves the island with a tilted, anisotropic K tensor.

The flow sets K22, Kv, an azimuth and a dip on two layers. The build writes
them to NPF with XT3D, which the dip turns on, and ANGLE3 as zero, since
MODFLOW 6 reads ANGLE2 only with ANGLE3. The steady state converges, and the run
store keeps K33 and the tensor beside K, read back as fields of the run.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import zarr

import hydromodpy as hmp
from tests._helpers.island_project import island_toml, run_island

pytestmark = [
    pytest.mark.integration,
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.slow,
    pytest.mark.allow_subprocess,
]

TENSOR = """
[flow.param.K22.field]
kind = "homogeneous"
value = "1e-6 m/s"

[flow.param.Kv.field]
kind = "homogeneous"
value = "5e-7 m/s"

[flow.param.angle1.field]
kind = "homogeneous"
value = 30.0

[flow.param.angle2.field]
kind = "homogeneous"
value = 20.0
"""


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("tilted")
    toml = island_toml("tilted", keep_solver_files=True)
    toml = toml.replace('param_list = ["K"]', 'param_list = ["K", "K22", "Kv", "angle1", "angle2"]')
    toml = toml.replace("nlay = 1", "nlay = 2")
    config = root / "project.toml"
    config.write_text(toml + TENSOR, encoding="utf-8")
    run_island(config)
    return root / "runs" / "tilted"


def _npf_text(run_dir: Path) -> str:
    (npf,) = sorted((run_dir / "solver").rglob("*.npf"))
    return npf.read_text(encoding="utf-8").upper()


def test_npf_carries_the_tensor_and_xt3d(run_dir: Path) -> None:
    text = _npf_text(run_dir)
    options = text.split("BEGIN OPTIONS")[1].split("END OPTIONS")[0]
    assert "XT3D" in options
    for block in ("K22", "K33", "ANGLE1", "ANGLE2", "ANGLE3"):
        assert f"\n  {block}" in text or f"\n{block}" in text, block


def test_the_steady_state_converges(run_dir: Path) -> None:
    (simulation,) = sorted((run_dir / "solver").rglob("mfsim.lst"))
    assert "Normal termination" in simulation.read_text(encoding="utf-8", errors="replace")
    for listing in (run_dir / "solver").rglob("*.lst"):
        text = listing.read_text(encoding="utf-8", errors="replace")
        assert "FAILED TO MEET SOLVER CONVERGENCE CRITERIA" not in text, listing.name


def test_the_store_keeps_k33_and_the_tensor(run_dir: Path) -> None:
    (store,) = sorted(run_dir.rglob("*.zarr"))
    derived = zarr.open_group(str(store), mode="r")["derived"]
    k = np.asarray(derived["hydraulic_conductivity"][:])
    assert k.shape[0] == 2
    assert np.allclose(np.asarray(derived["hydraulic_conductivity_k22"][:]), 1e-6)
    assert np.allclose(np.asarray(derived["hydraulic_conductivity_k33"][:]), 5e-7)
    assert np.allclose(np.asarray(derived["conductivity_tensor_angle1"][:]), 30.0)
    assert np.allclose(np.asarray(derived["conductivity_tensor_angle2"][:]), 20.0)
    assert np.allclose(np.asarray(derived["conductivity_tensor_angle3"][:]), 0.0)


def test_the_tensor_reads_back_as_fields_of_the_run(run_dir: Path) -> None:
    run = hmp.open(run_dir)
    assert np.allclose(run.field("hydraulic_conductivity_k33"), 5e-7)
    assert np.allclose(run.field("conductivity_tensor_angle2", layer=1), 20.0)
