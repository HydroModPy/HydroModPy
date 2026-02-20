"""End-to-end regression test for examples/example12/example12.py."""

from pathlib import Path

import pytest
from examples.example12.example12 import run_example12
from tests.regression.golden_utils import (
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    collect_modpath_signatures,
    resolve_model_workspace,
    run_legacy_example_script,
    update_or_assert_goldens,
)

EXAMPLE12_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "example12"
    / "example12.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example12_npy_signatures.json"
)

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "watertable_depth",
    "seepage_areas",
    "outflow_drain",
    "accumulation_flux",
]

MODPATH_SNAPSHOT_FILES = [
    "starting.dbf",
    "ending.dbf",
]

@pytest.mark.regression
@pytest.mark.slow
def test_example12_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example12, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example12_outputs"
    # run_legacy_example_script(
    #     script_path=EXAMPLE12_SCRIPT,
    #     out_path=out_path,
    #     stop_method="postprocessing_modflow",
    #     expected_stop_calls=1,
    #     mirror_example_data_dir=True,
    #     timeout=7200,
    # )
    run_example12(out_path=out_path, display_plots=False)
    
    _, postprocess_dir,  particles_dir  = resolve_model_workspace(
        out_path,
        watershed_name="example12",
        results_folder_name="results_simulations",
    )

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
        "modpath_expected": collect_modpath_signatures(particles_dir, MODPATH_SNAPSHOT_FILES),
    }
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=GOLDEN_REFERENCE_FILE,
        update_goldens=update_goldens,
    )
