"""End-to-end regression test for examples/06.../example_06.py."""

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
    run_legacy_example_script,
    write_golden_reference,
)


EXAMPLE_06_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "06_particle_tracking_and_residence_times"
    / "example_06.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_06_npy_signatures.json"
)

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "outflow_drain",
    "groundwater_flux",
    "groundwater_storage",
    "accumulation_flux",
]

MODPATH_SNAPSHOT_FILES = [
    "starting_weighted.dbf",
    "ending_weighted.dbf",
]


@pytest.mark.regression
@pytest.mark.slow
def test_example_06_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_06, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_06_outputs"
    run_legacy_example_script(
        script_path=EXAMPLE_06_SCRIPT,
        out_path=out_path,
        stop_method="filtprocessing_modpath",
        expected_stop_calls=1,
        timeout=5400,
    )

    model_ws = out_path / "Example_06_Lasset" / "results_simulations" / "default"
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
