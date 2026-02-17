"""End-to-end regression test for examples/10.../example_10.py."""

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


def _short_out_path_for_example_10() -> Path:
    """
    Build a short output path to avoid Windows path-length issues.

    Example 10 creates deeply nested calibration folders with long model names.
    Under pytest-xdist, default `tmp_path` can become too long on Windows.
    """
    root = Path(tempfile.gettempdir()) / "hmpy_reg"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"e10_{uuid.uuid4().hex[:8]}"


@pytest.mark.regression
@pytest.mark.slow
def test_example_10_regression_on_npy_outputs(update_goldens):
    """Run example_10, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    # Ensure optional PYHELP component is importable before running the example.
    pytest.importorskip("hydromodpy.pyhelp.pyhelp_netcdf")

    # Intentionally avoid `tmp_path` here to keep absolute paths short.
    out_path = _short_out_path_for_example_10()
    run_legacy_example_script(
        script_path=EXAMPLE_10_SCRIPT,
        out_path=out_path,
        stop_method="postprocessing_modflow",
        expected_stop_calls=1,
        patch_ipython_inline=True,
        mirror_example_data_dir=True,
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
