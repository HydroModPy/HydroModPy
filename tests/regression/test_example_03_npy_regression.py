"""End-to-end regression test for examples/03.../example_03.py."""

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


EXAMPLE_03_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "03_hydrographic_network_in_steady_state"
    / "example_03.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_03_npy_signatures.json"
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
def test_example_03_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_03, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_03_outputs"
    run_legacy_example_script(
        script_path=EXAMPLE_03_SCRIPT,
        out_path=out_path,
        expected_netcdf_calls=10,
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

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
    }

    if update_goldens:
        write_golden_reference(GOLDEN_REFERENCE_FILE, actual)
        return

    expected = load_golden_reference(GOLDEN_REFERENCE_FILE)
    assert_modflow_signatures(actual["modflow_expected"], expected["modflow_expected"])
