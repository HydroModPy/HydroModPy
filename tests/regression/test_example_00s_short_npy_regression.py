"""End-to-end regression test for examples/00S_short/example_00.py."""

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


EXAMPLE_00S_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "00S_short"
    / "example_00.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_00s_short_npy_signatures.json"
)

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "outflow_drain",
    "groundwater_flux",
    "groundwater_storage",
    "accumulation_flux",
]

MODPATH_SNAPSHOT_FILES = [
    "starting.dbf",
    "starting_weighted.dbf",
    "ending.dbf",
    "ending_weighted.dbf",
]


@pytest.mark.regression
@pytest.mark.fast
def test_example_00s_short_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_00S, then compare (or refresh) its golden signatures."""
    assert_required_executables()

    out_path = tmp_path / "example_00s_short_outputs"
    run_example_script(
        script_path=EXAMPLE_00S_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_EXAMPLE00_OUT_PATH",
        extra_env={"HYDROMODPY_EXAMPLE00_SKIP_PLOTS": "1"},
    )

    model_ws = out_path / "00S_short" / "results_simulations" / "reg_0"
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
        "modpath_expected": collect_modpath_signatures(particles_dir, MODPATH_SNAPSHOT_FILES),
    }

    if update_goldens:
        write_golden_reference(GOLDEN_REFERENCE_FILE, actual)
        return

    expected = load_golden_reference(GOLDEN_REFERENCE_FILE)
    assert_modflow_signatures(actual["modflow_expected"], expected["modflow_expected"])
    assert_modpath_signatures(actual["modpath_expected"], expected["modpath_expected"])

