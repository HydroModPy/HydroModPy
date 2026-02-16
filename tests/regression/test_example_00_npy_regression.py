"""End-to-end regression test for examples/example_00.py."""

from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    DEFAULT_MODFLOW_OUTPUT_NAMES,
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    collect_modpath_signatures,
    resolve_model_workspace,
    run_example_script,
    update_or_assert_goldens,
)


EXAMPLE_00_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "00_quick_test_of_wide_hydromodpy_capabilities"
    / "example_00.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_00_npy_signatures.json"
)

MODPATH_SNAPSHOT_FILES = [
    "starting.dbf",
    "starting_weighted.dbf",
]


@pytest.mark.regression
@pytest.mark.slow
def test_example_00_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_00, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_00_outputs"
    run_example_script(
        script_path=EXAMPLE_00_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_EXAMPLE00_OUT_PATH",
        extra_env={"HYDROMODPY_EXAMPLE00_SKIP_PLOTS": "1"},
    )
    _, postprocess_dir, particles_dir = resolve_model_workspace(
        out_path,
        watershed_name="Example_00_Aber",
        model_name="reg_0",
    )

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, DEFAULT_MODFLOW_OUTPUT_NAMES),
        "modpath_expected": collect_modpath_signatures(particles_dir, MODPATH_SNAPSHOT_FILES),
    }
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=GOLDEN_REFERENCE_FILE,
        update_goldens=update_goldens,
    )

