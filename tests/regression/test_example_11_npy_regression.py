"""End-to-end regression test for examples/example_11.py."""

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
    run_example_script,
    write_golden_reference,
)


EXAMPLE_11_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "11_for run from scratch without plots"
    / "example_11.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_11_npy_signatures.json"
)

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "watertable_depth",
    "seepage_areas",
    "outflow_drain",
    "groundwater_flux",
    "groundwater_storage",
    "accumulation_flux",
]

MODPATH_SNAPSHOT_FILES = [
    "modpath_postprocessing_snapshot.npy",
]


@pytest.mark.regression
@pytest.mark.slow
def test_example_11_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_11, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_11_outputs"
    run_example_script(
        script_path=EXAMPLE_11_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_EXAMPLE11_OUT_PATH",
    )

    model_ws = out_path / "Example_11_Galaxy" / "results_simulations" / "Test_Galaxy_v0"
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

