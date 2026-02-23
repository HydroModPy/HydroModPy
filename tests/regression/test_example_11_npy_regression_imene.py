"""End-to-end regression test for examples/example_11.py."""

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


EXAMPLE_11_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "11_for run from scratch without plots"
    / "example_11.py"
)

GOLDEN_REFERENCE_DIR = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
)

DEM_TEST_CASES = [
    pytest.param(
        "regional dem 2.tif",
        "example_11_npy_signatures.json",
        marks=pytest.mark.fast,
        id="dem_2_fast",
    ),
    pytest.param(
        "regional dem.tif",
        "example_11_regional_dem_npy_signatures.json",
        marks=pytest.mark.slow,
        id="dem_slow",
    ),
]

MODPATH_SNAPSHOT_FILES = [
    "starting.dbf",
    "ending.dbf",
]


@pytest.mark.regression
@pytest.mark.parametrize(
    ("dem_name", "golden_filename"),
    DEM_TEST_CASES,
)
def test_example_11_regression_on_npy_outputs(tmp_path, update_goldens, dem_name, golden_filename):
    """Run example_11, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / f"example_11_outputs_{dem_name.replace(' ', '_').replace('.', '_')}"
    run_example_script(
        script_path=EXAMPLE_11_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_EXAMPLE11_OUT_PATH",
        extra_env={"HYDROMODPY_EXAMPLE11_DEM_NAME": dem_name},
    )
    _, postprocess_dir, particles_dir = resolve_model_workspace(out_path)

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, DEFAULT_MODFLOW_OUTPUT_NAMES),
        "modpath_expected": collect_modpath_signatures(particles_dir, MODPATH_SNAPSHOT_FILES),
    }

    golden_reference_file = GOLDEN_REFERENCE_DIR / golden_filename
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=golden_reference_file,
        update_goldens=update_goldens,
    )

