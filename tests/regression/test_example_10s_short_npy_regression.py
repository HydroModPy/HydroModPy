"""End-to-end regression test for examples/10S_short/example_10.py."""

import tempfile
import uuid
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


EXAMPLE_10S_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "10S_short"
    / "example_10.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_10s_short_npy_signatures.json"
)


def _short_out_path_for_example_10s() -> Path:
    """Build a short output path to avoid Windows path-length issues."""
    root = Path(tempfile.gettempdir()) / "hmpy_reg"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"e10s_{uuid.uuid4().hex[:8]}"


@pytest.mark.regression
@pytest.mark.fast
def test_example_10s_short_regression_on_npy_outputs(update_goldens):
    """Run example_10S, then compare (or refresh) its golden signatures."""
    assert_required_executables()
    pytest.importorskip("hydromodpy.pyhelp.pyhelp_netcdf")

    out_path = _short_out_path_for_example_10s()
    run_legacy_example_script(
        script_path=EXAMPLE_10S_SCRIPT,
        out_path=out_path,
        stop_method="postprocessing_modflow",
        expected_stop_calls=1,
        patch_ipython_inline=True,
        timeout=7200,
    )
    _, postprocess_dir, _ = resolve_model_workspace(
        out_path,
        watershed_name="10S_short",
        results_folder_name="results_calibration",
        model_name_prefix="DICHOT2_",
    )

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, DEFAULT_MODFLOW_OUTPUT_NAMES),
    }
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=GOLDEN_REFERENCE_FILE,
        update_goldens=update_goldens,
    )
