"""End-to-end regression test for examples/03S_short/example_03.py."""

from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    DEFAULT_MODFLOW_OUTPUT_NAMES,
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    resolve_first_model_workspace,
    run_legacy_example_script,
    update_or_assert_goldens,
)


EXAMPLE_03S_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "03S_short"
    / "example_03.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_03s_short_npy_signatures.json"
)

@pytest.mark.regression
@pytest.mark.fast
def test_example_03s_short_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_03S, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_03s_short_outputs"
    run_legacy_example_script(
        script_path=EXAMPLE_03S_SCRIPT,
        out_path=out_path,
        expected_netcdf_calls=3,
    )
    _, postprocess_dir, _ = resolve_first_model_workspace(out_path)

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, DEFAULT_MODFLOW_OUTPUT_NAMES),
    }
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=GOLDEN_REFERENCE_FILE,
        update_goldens=update_goldens,
    )
