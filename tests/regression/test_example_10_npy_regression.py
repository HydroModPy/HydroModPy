"""End-to-end regression test for examples/10.../example_10.py."""

from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    DEFAULT_MODFLOW_OUTPUT_NAMES,
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    resolve_model_workspace,
    run_legacy_example_script,
    update_or_assert_goldens,
)


EXAMPLE_10_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "10_coupling_with_land_surface_model_pyhelp"
    / "example_10.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_10_npy_signatures.json"
)

@pytest.mark.regression
@pytest.mark.slow
def test_example_10_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_10, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    # Ensure optional PYHELP component is importable before running the example.
    pytest.importorskip("hydromodpy.pyhelp.pyhelp_netcdf")

    out_path = tmp_path / "example_10_outputs"
    run_legacy_example_script(
        script_path=EXAMPLE_10_SCRIPT,
        out_path=out_path,
        stop_method="postprocessing_modflow",
        expected_stop_calls=1,
        patch_ipython_inline=True,
        timeout=7200,
    )
    _, postprocess_dir, _ = resolve_model_workspace(
        out_path,
        watershed_name="Example_10_Urse",
        results_folder_name="results_calibration",
    )

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, DEFAULT_MODFLOW_OUTPUT_NAMES),
    }
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=GOLDEN_REFERENCE_FILE,
        update_goldens=update_goldens,
    )
