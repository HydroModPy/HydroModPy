"""
End-to-end regression test for `example_00.py`.

What this test verifies
-----------------------
This test executes the full "quick wide capabilities" example and checks that
key MODFLOW and MODPATH outputs still match committed golden references.

Why this matters
----------------
`example_00` is a broad integration scenario. If this test fails, it usually
means a functional regression was introduced in workflow orchestration,
post-processing, or particle tracking outputs.
"""

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


# Absolute path to the example script executed by the test.
EXAMPLE_00_SCRIPT = (
    REPO_ROOT
    / "examples_legacy"
    / "00_quick_test_of_wide_hydromodpy_capabilities"
    / "example_00.py"
)

# Golden JSON storing expected signatures for this scenario.
GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_00_npy_signatures.json"
)

# MODPATH DBF snapshots used for particle-tracking regression checks.
MODPATH_SNAPSHOT_FILES = [
    "starting.dbf",
    "starting_weighted.dbf",
]


@pytest.mark.regression
@pytest.mark.slow
def test_example_00_regression_on_npy_outputs(tmp_path, update_goldens):
    """
    Execute `example_00` and compare generated signatures to golden references.

    High-level flow:
    1. guard against missing MODFLOW/MODPATH binaries,
    2. run the example in an isolated temporary output folder,
    3. locate generated post-process folders,
    4. compute compact signatures from selected files,
    5. compare with goldens or refresh them with `--update-goldens`.
    """
    # Skip gracefully if required numerical executables are not available.
    assert_required_executables()

    # Keep every test run isolated to avoid cross-test interference.
    out_path = tmp_path / "example_00_outputs"
    run_example_script(
        script_path=EXAMPLE_00_SCRIPT,
        out_path=out_path,
        # example_00 supports output redirection through this env variable.
        out_env_var="HYDROMODPY_EXAMPLE00_OUT_PATH",
        # Disable plotting for deterministic, headless test execution.
        extra_env={"HYDROMODPY_EXAMPLE00_SKIP_PLOTS": "1"},
    )

    # Resolve the exact model workspace produced by this example.
    _, postprocess_dir, particles_dir = resolve_model_workspace(
        out_path,
        watershed_name="Example_00_Aber",
        model_name="reg_0",
    )

    # Build compact runtime signatures from MODFLOW `.npy` and MODPATH `.dbf`.
    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, DEFAULT_MODFLOW_OUTPUT_NAMES),
        "modpath_expected": collect_modpath_signatures(particles_dir, MODPATH_SNAPSHOT_FILES),
    }

    # In normal mode: assert equality with committed goldens.
    # In update mode: rewrite goldens with current signatures.
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=GOLDEN_REFERENCE_FILE,
        update_goldens=update_goldens,
    )


