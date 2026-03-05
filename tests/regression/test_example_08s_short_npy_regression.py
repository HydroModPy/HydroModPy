"""End-to-end regression test for examples/08S_short/example_08.py."""

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


EXAMPLE_08S_SCRIPT = (
    REPO_ROOT
    / "examples_legacy"
    / "08S_short"
    / "example_08.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_08s_short_npy_signatures.json"
)

MODPATH_SNAPSHOT_FILES = [
    "starting_weighted.dbf",
    "ending_weighted.dbf",
]


@pytest.mark.regression
@pytest.mark.fast
def test_example_08s_short_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_08S, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_08s_short_outputs"
    run_legacy_example_script(
        script_path=EXAMPLE_08S_SCRIPT,
        out_path=out_path,
        stop_method="filtprocessing_modpath",
        expected_stop_calls=1,
        timeout=5400,
    )
    _, postprocess_dir, particles_dir = resolve_model_workspace(
        out_path,
        watershed_name="08S_short",
        model_name="test_v1",
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

