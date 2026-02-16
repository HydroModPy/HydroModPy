"""End-to-end regression test for examples/09.../example_09.py."""

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


EXAMPLE_09_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "09_transport_model_for_an_agricultural_catchment"
    / "example_09.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_09_npy_signatures.json"
)

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "watertable_depth",
    "seepage_areas",
    "outflow_drain",
    "accumulation_flux",
]


@pytest.mark.regression
@pytest.mark.slow
def test_example_09_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_09, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_09_outputs"
    run_legacy_example_script(
        script_path=EXAMPLE_09_SCRIPT,
        out_path=out_path,
        stop_method="postprocessing_timeseries",
        expected_stop_calls=1,
        timeout=5400,
    )

    calibration_dir = out_path / "Example_09_Naizin" / "results_calibration"
    model_dirs = sorted(p for p in calibration_dir.iterdir() if p.is_dir() and p.name.startswith("TRANS1_"))
    assert model_dirs, f"No calibration model folder found in {calibration_dir}"
    model_ws = model_dirs[0]
    postprocess_dir = model_ws / "_postprocess"

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
    }

    if update_goldens:
        write_golden_reference(GOLDEN_REFERENCE_FILE, actual)
        return

    expected = load_golden_reference(GOLDEN_REFERENCE_FILE)
    assert_modflow_signatures(actual["modflow_expected"], expected["modflow_expected"])
