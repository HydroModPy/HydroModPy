"""End-to-end regression test for examples/09S_short/example_09_new.py (NEW API)."""

from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    resolve_model_workspace,
    run_legacy_example_script,
    update_or_assert_goldens,
)


EXAMPLE_09S_NEW_SCRIPT = (
    REPO_ROOT
    / "examples_legacy"
    / "09S_short"
    / "example_09_new.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_09s_short_new_npy_signatures.json"
)

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "watertable_depth",
    "seepage_areas",
    "outflow_drain",
    "accumulation_flux",
]


@pytest.mark.regression
@pytest.mark.fast
def test_example_09s_short_new_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_09S_new, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_09s_short_new_outputs"
    run_legacy_example_script(
        script_path=EXAMPLE_09S_NEW_SCRIPT,
        out_path=out_path,
        stop_method="postprocessing_timeseries",
        expected_stop_calls=1,
        timeout=7200,
    )

    _, postprocess_dir, _ = resolve_model_workspace(
        out_path,
        watershed_name="09S_short",
        results_folder_name="results_calibration",
        model_name_prefix="TRANS1_",
    )

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
    }
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=GOLDEN_REFERENCE_FILE,
        update_goldens=update_goldens,
    )

