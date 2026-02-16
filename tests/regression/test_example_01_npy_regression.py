"""End-to-end regression test for examples/example_01.py."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    REPO_ROOT,
    assert_modflow_signatures,
    assert_modpath_signatures,
    assert_required_executables,
    collect_modflow_signatures,
    collect_modpath_signatures,
    load_golden_reference,
    write_golden_reference,
)


EXAMPLE_01_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "01_simplified_example_presented_in_the_paper"
    / "example_01.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_01_npy_signatures.json"
)

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "outflow_drain",
    "groundwater_flux",
    "groundwater_storage",
    "accumulation_flux",
]

MODPATH_SNAPSHOT_FILES = [
    "starting.dbf",
    "ending.dbf",
]


def _run_example_01_script(out_path: Path):
    """Run example_01.py without editing it, in headless/non-interactive mode."""
    # NOTE:
    # - example_01 writes to root_dir/examples/results (hardcoded),
    # - and enters interactive plotting at the end.
    # This wrapper:
    # 1) redirects only that specific output path to tmp_path,
    # 2) stops execution right after postprocessing_netcdf() returns.
    wrapper = r"""
import os
import runpy
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

script = Path(sys.argv[1]).resolve()
out_path = Path(sys.argv[2]).resolve()

orig_join = os.path.join

def patched_join(*parts):
    if len(parts) == 3 and parts[1] == "examples" and parts[2] == "results":
        return str(out_path)
    return orig_join(*parts)

os.path.join = patched_join

from hydromodpy.watershed_root import Watershed
orig_postprocessing_netcdf = Watershed.postprocessing_netcdf

def patched_postprocessing_netcdf(self, *args, **kwargs):
    result = orig_postprocessing_netcdf(self, *args, **kwargs)
    raise SystemExit(0)

Watershed.postprocessing_netcdf = patched_postprocessing_netcdf

try:
    runpy.run_path(str(script), run_name="__main__")
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else 0
    if code not in (0, None):
        raise
"""

    env = os.environ.copy()
    env.setdefault("MPLBACKEND", "Agg")

    command = [sys.executable, "-c", wrapper, str(EXAMPLE_01_SCRIPT), str(out_path)]
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=1800,
    )

    assert completed.returncode == 0, (
        "example_01.py failed.\n"
        f"Command: {' '.join(command)}\n"
        f"Stdout:\n{completed.stdout}\n"
        f"Stderr:\n{completed.stderr}"
    )


@pytest.mark.regression
@pytest.mark.slow
def test_example_01_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_01, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_01_outputs"
    _run_example_01_script(out_path)

    model_ws = out_path / "Example_01_Canut" / "results_simulations" / "test_0"
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
        "modpath_expected": collect_modpath_signatures(particles_dir, MODPATH_SNAPSHOT_FILES),
    }

    if update_goldens:
        write_golden_reference(GOLDEN_REFERENCE_FILE, actual)
        return

    expected = load_golden_reference(GOLDEN_REFERENCE_FILE)
    assert_modflow_signatures(actual["modflow_expected"], expected["modflow_expected"])
    assert_modpath_signatures(actual["modpath_expected"], expected["modpath_expected"])

