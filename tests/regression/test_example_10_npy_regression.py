"""End-to-end regression test for examples/10.../example_10.py."""

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

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "outflow_drain",
    "groundwater_flux",
    "groundwater_storage",
    "accumulation_flux",
]


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

    calibration_dir = out_path / "Example_10_Urse" / "results_calibration"
    model_dirs = sorted(p for p in calibration_dir.iterdir() if p.is_dir())
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
