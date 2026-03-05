"""End-to-end regression test for examples/06.../example_06.py."""

from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    DEFAULT_MODFLOW_OUTPUT_NAMES,
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    collect_modpath_signatures,
    resolve_model_workspace,
    run_legacy_example_script,
    update_or_assert_goldens,
)


EXAMPLE_06_SCRIPT = (
    REPO_ROOT
    / "examples_legacy"
    / "06_particle_tracking_and_residence_times"
    / "example_06.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_06_npy_signatures.json"
)

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
    _, postprocess_dir, particles_dir = resolve_model_workspace(
        out_path,
        watershed_name="Example_06_Lasset",
        model_name="default",
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

