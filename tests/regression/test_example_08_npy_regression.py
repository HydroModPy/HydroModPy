"""End-to-end regression test for examples/08.../example_08.py."""

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


EXAMPLE_08_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "08_exponential_distribution_of_residence_times"
    / "example_08.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_08_npy_signatures.json"
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
def test_example_08_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_08, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_08_outputs"
    run_legacy_example_script(
        script_path=EXAMPLE_08_SCRIPT,
        out_path=out_path,
        stop_method="filtprocessing_modpath",
        expected_stop_calls=1,
        timeout=5400,
    )

    model_ws = out_path / "Example_08_Synthetic" / "results_simulations" / "test_v1"
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
