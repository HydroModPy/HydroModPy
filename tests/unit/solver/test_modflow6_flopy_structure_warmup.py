"""FloPy MF6 DFN-structure warm-up: concurrent builds on a cold process.

``MFStructure`` publishes its singleton before loading it, so threads that
construct an ``MFSimulation`` at the same time on a cold interpreter race and
all but one raise ``AttributeError: 'NoneType' object has no attribute
'blocks'``. Parallel calibration hits exactly that. The check has to run in a
fresh interpreter, because any earlier test in the session would have already
loaded the singleton and made the race unobservable.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

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
