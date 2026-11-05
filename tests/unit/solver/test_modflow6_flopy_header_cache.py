"""FloPy MF6 block-header transient-key cache: patch correctness.

The patch (``hydromodpy.solver.modflow6.support.flopy_header_cache``) reaches into
flopy private internals on purpose; these tests double as a canary that
breaks loudly if a flopy upgrade changes them.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import flopy
import numpy as np
import pytest
from flopy.mf6.mfpackage import MFBlockHeader

from hydromodpy.solver.modflow6.support.flopy_header_cache import install_flopy_header_cache

NPER = 40


NROW = NCOL = 3


def _build_sim(ws: Path) -> tuple[flopy.mf6.MFSimulation, flopy.mf6.ModflowGwfrcha]:
    sim = flopy.mf6.MFSimulation(sim_name="cache", sim_ws=str(ws))
    flopy.mf6.ModflowTdis(sim, nper=NPER, perioddata=[(1.0, 1, 1.0)] * NPER)
    flopy.mf6.ModflowIms(sim)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="m")
    flopy.mf6.ModflowGwfdis(gwf, nlay=1, nrow=NROW, ncol=NCOL)
    flopy.mf6.ModflowGwfic(gwf)
    flopy.mf6.ModflowGwfnpf(gwf)
    recharge = {kper: np.full((NROW, NCOL), 1e-9 * (kper + 1)) for kper in range(NPER)}
    rcha = flopy.mf6.ModflowGwfrcha(gwf, recharge=recharge)
    return sim, rcha


def test_install_is_idempotent() -> None:
    install_flopy_header_cache()
    patched = MFBlockHeader.get_transient_key
    install_flopy_header_cache()
    assert MFBlockHeader.get_transient_key is patched


def test_written_period_blocks_are_complete_and_unique(tmp_path: Path) -> None:
    install_flopy_header_cache()
    sim, _ = _build_sim(tmp_path)
    sim.write_simulation(silent=True)
    text = (tmp_path / "m.rcha").read_text().lower()
    keys = [int(match) for match in re.findall(r"begin period\s+(\d+)", text)]
    assert sorted(keys) == list(range(1, NPER + 1))


def test_period_data_roundtrip(tmp_path: Path) -> None:
    install_flopy_header_cache()
    sim, _ = _build_sim(tmp_path)
    sim.write_simulation(silent=True)
    loaded = flopy.mf6.MFSimulation.load(sim_ws=str(tmp_path), verbosity_level=0)
    rcha = loaded.get_model("m").get_package("rcha")
    for kper in (0, 17, NPER - 1):
        np.testing.assert_allclose(
            rcha.recharge.get_data(kper),
            np.full((NROW, NCOL), 1e-9 * (kper + 1)),
        )


def test_header_exists_uses_cached_integer_keys(tmp_path: Path) -> None:
    install_flopy_header_cache()
    _, rcha = _build_sim(tmp_path)
    block = rcha.blocks["period"]
    assert block.header_exists(NPER - 1)
    assert not block.header_exists(NPER + 5)
    cached = sorted(
        header._hydromodpy_transient_key
        for header in block.block_headers
        if hasattr(header, "_hydromodpy_transient_key")
    )
    assert cached == list(range(NPER))


def test_data_path_recursion_guard_preserved(tmp_path: Path) -> None:
    install_flopy_header_cache()
    _, rcha = _build_sim(tmp_path)
    header = rcha.blocks["period"].block_headers[3]
    item_path = header.data_items[0].path
    assert header.get_transient_key(data_path=item_path) is True


def test_build_header_variables_drops_stale_cache(tmp_path: Path) -> None:
    install_flopy_header_cache()
    _, rcha = _build_sim(tmp_path)
    block = rcha.blocks["period"]
    header = block.block_headers[4]
    assert header.get_transient_key() == 4
    # Rebind the header key the way _build_repeating_header does; the cached
    # value from the read above must not survive the rebind.
    header.build_header_variables(
        block._simulation_data,
        block.structure.block_header_structure,
        header.data_items[0].path[:-1],
        [99],
        block._dimensions,
    )
    assert header.get_transient_key() == 99


# FloPy MF6 DFN-structure warm-up: concurrent builds on a cold process.
#
# ``MFStructure`` publishes its singleton before loading it, so threads that
# construct an ``MFSimulation`` at the same time on a cold interpreter race and
# all but one raise ``AttributeError: 'NoneType' object has no attribute
# 'blocks'``. Parallel calibration hits exactly that. The check has to run in a
# fresh interpreter, because any earlier test in the session would have already
# loaded the singleton and made the race unobservable.

_CHILD = """
import sys, tempfile
from concurrent.futures import ThreadPoolExecutor

from hydromodpy.solver.modflow6.support.flopy_structure_warmup import warm_flopy_structure


def build(index):
    import flopy

    warm_flopy_structure()
    try:
        flopy.mf6.MFSimulation(sim_name=f"s{index}", sim_ws=tempfile.mkdtemp())
    except Exception as exc:
        return repr(exc)
    return None


with ThreadPoolExecutor(max_workers=4) as pool:
    failures = [item for item in pool.map(build, range(4)) if item]
print(failures)
sys.exit(1 if failures else 0)
"""


@pytest.mark.allow_subprocess
def test_concurrent_cold_simulation_builds_succeed() -> None:
    """Four threads build an MFSimulation at once without losing any."""
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
