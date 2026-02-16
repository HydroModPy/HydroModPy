"""End-to-end regression test for examples/example_11.py."""

from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    REPO_ROOT,
    assert_modflow_signatures,
    assert_modpath_signatures,
    assert_required_executables,
    collect_modflow_signatures,
    collect_modpath_signatures,
    load_golden_reference,
    run_example_script,
    write_golden_reference,
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

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "outflow_drain",
    "groundwater_flux",
    "groundwater_storage",
    "accumulation_flux",
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

    watershed_dirs = sorted(p for p in out_path.iterdir() if p.is_dir())
    assert watershed_dirs, f"No watershed folder found in {out_path}"
    watershed_dir = watershed_dirs[0]

    results_simulations_dir = watershed_dir / "results_simulations"
    model_dirs = sorted(
        p for p in results_simulations_dir.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )
    assert model_dirs, f"No model folder found in {results_simulations_dir}"
    model_ws = model_dirs[0]
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
        "modpath_expected": collect_modpath_signatures(particles_dir, MODPATH_SNAPSHOT_FILES),
    }

    golden_reference_file = GOLDEN_REFERENCE_DIR / golden_filename

    if update_goldens:
        write_golden_reference(golden_reference_file, actual)
        return

    expected = load_golden_reference(golden_reference_file)
    assert_modflow_signatures(actual["modflow_expected"], expected["modflow_expected"])
    assert_modpath_signatures(actual["modpath_expected"], expected["modpath_expected"])

