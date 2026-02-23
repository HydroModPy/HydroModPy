"""End-to-end regression tests for launcher.py - validates it produces identical results to example_03_new.py and example_09_new.py."""

from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    DEFAULT_MODFLOW_OUTPUT_NAMES,
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    resolve_first_model_workspace,
    resolve_model_workspace,
    run_legacy_example_script,
    update_or_assert_goldens,
)


# ============================================================================
# LAUNCHER EXAMPLE 03 TEST
# ============================================================================

LAUNCHER_EX03_SCRIPT = (
    REPO_ROOT
    / "tests"
    / "regression"
    / "launcher_ex03_test.py"
)

GOLDEN_REFERENCE_FILE_EX03 = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_03s_short_new_npy_signatures.json"
)


@pytest.mark.regression
@pytest.mark.fast
def test_launcher_ex03_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run launcher with example=ex03, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "launcher_ex03_outputs"
    run_legacy_example_script(
        script_path=LAUNCHER_EX03_SCRIPT,
        out_path=out_path,
        expected_netcdf_calls=3,
    )
    _, postprocess_dir, _ = resolve_first_model_workspace(out_path)

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, DEFAULT_MODFLOW_OUTPUT_NAMES),
    }
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=GOLDEN_REFERENCE_FILE_EX03,
        update_goldens=update_goldens,
    )


# ============================================================================
# LAUNCHER EXAMPLE 09 TEST
# ============================================================================

LAUNCHER_EX09_SCRIPT = (
    REPO_ROOT
    / "tests"
    / "regression"
    / "launcher_ex09_test.py"
)

GOLDEN_REFERENCE_FILE_EX09 = (
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
def test_example_09s_short_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_09S, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "launcher_ex09_test.py"
    run_legacy_example_script(
        script_path=LAUNCHER_EX09_SCRIPT,
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
        golden_reference_file=GOLDEN_REFERENCE_FILE_EX09,
        update_goldens=update_goldens,
    )
