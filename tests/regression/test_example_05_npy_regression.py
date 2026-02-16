"""End-to-end regression test for examples/05.../example_05.py."""

from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    REPO_ROOT,
    assert_modflow_signatures,
    assert_required_executables,
    collect_modflow_signatures,
    load_golden_reference,
    run_legacy_example_script,
    write_golden_reference,
)


EXAMPLE_05_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "05_piezometry_in_a_heterogeneous_coastal_aquifer"
    / "example_05.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_05_npy_signatures.json"
)

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "outflow_drain",
    "groundwater_flux",
    "groundwater_storage",
]


@pytest.mark.regression
@pytest.mark.slow
def test_example_05_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_05, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_05_outputs"
    run_legacy_example_script(
        script_path=EXAMPLE_05_SCRIPT,
        out_path=out_path,
        stop_method="postprocessing_netcdf",
        expected_stop_calls=1,
        timeout=5400,
    )

    model_ws = out_path / "Example_05_Gouville" / "results_simulations" / "default"
    postprocess_dir = model_ws / "_postprocess"

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
    }

    if update_goldens:
        write_golden_reference(GOLDEN_REFERENCE_FILE, actual)
        return

    expected = load_golden_reference(GOLDEN_REFERENCE_FILE)
    assert_modflow_signatures(actual["modflow_expected"], expected["modflow_expected"])
