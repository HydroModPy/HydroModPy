"""End-to-end regression test for examples/05S_short/example_05.py."""

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


EXAMPLE_05S_SCRIPT = (
    REPO_ROOT
    / "examples_legacy"
    / "05S_short"
    / "example_05.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_05s_short_npy_signatures.json"
)

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "outflow_drain",
    "groundwater_flux",
    "groundwater_storage",
]


@pytest.mark.regression
@pytest.mark.fast
def test_example_05s_short_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_05S, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_05s_short_outputs"
    run_legacy_example_script(
        script_path=EXAMPLE_05S_SCRIPT,
        out_path=out_path,
        stop_method="postprocessing_modflow",
        expected_stop_calls=1,
        timeout=3600,
    )
    _, postprocess_dir, _ = resolve_model_workspace(
        out_path,
        watershed_name="05S_short",
        model_name="default",
    )

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
    }
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=GOLDEN_REFERENCE_FILE,
        update_goldens=update_goldens,
    )

