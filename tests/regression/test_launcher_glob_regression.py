"""
End-to-end regression tests for launcher_glob.py

OBJECTIVE: Validate that Launcher_Glob produces identical results to individual examples.

CONCEPT:
- Each example (ex00, ex01, ex03, etc.) has a "golden reference" file
- Golden = expected signatures (hashes) of output files when run correctly
- When we run Launcher_Glob with example_key="ex00", it MUST produce the same
  signatures as running example_00.py directly
- If signatures differ → regression detected → test fails

WORKFLOW:
1. Run Launcher_Glob(example_key="exXX")
2. Collect MODFLOW output file signatures (hashes of .npy files)
3. Compare with golden reference file (example_XXs_short_npy_signatures.json)
4. If identical → PASS (no regression)
5. If different → FAIL (regression detected!)
"""

from pathlib import Path

import pytest

from examples.Examples_Launchers.Launcher_Glob import run_launcher_glob
from tests.regression.golden_utils import (
    DEFAULT_MODFLOW_OUTPUT_NAMES,
    assert_required_executables,
    collect_modflow_signatures,
    resolve_model_workspace,
    update_or_assert_goldens,
)


# ============================================================================
# HELPER FUNCTION - Run regression test for any example
# ============================================================================

def run_launcher_glob_regression_test(
    example_key: str,
    watershed_name: str,
    results_folder_name: str,
    golden_reference_file: Path,
    tmp_path,
    update_goldens,
    modflow_output_names=None,
    model_name_prefix: str = "",
):
    """
    Generic regression test helper for any Launcher_Glob example.
    
    Parameters:
    -----------
    example_key : str
        Example identifier (ex00, ex01, ex03, ex04, ex09, ex12, etc.)
    watershed_name : str
        Watershed folder name (00S_short, 01S_short, etc.)
    results_folder_name : str
        Where results are stored (results_simulations or results_calibration)
    golden_reference_file : Path
        Path to golden reference JSON file
    modflow_output_names : list, optional
        List of MODFLOW output file names to verify (default: DEFAULT_MODFLOW_OUTPUT_NAMES)
    model_name_prefix : str, optional
        Prefix added to model name (e.g., "TRANS1_" for ex09, ex12)
    """
    # Ensure required tools are available
    assert_required_executables()
    
    # Use default output names if not specified
    if modflow_output_names is None:
        modflow_output_names = DEFAULT_MODFLOW_OUTPUT_NAMES
    
    # Create output directory for this test
    out_path = tmp_path / f"launcher_glob_{example_key}_outputs"
    
    # STEP 1: Execute Launcher_Glob with this example
    print(f"\n[REGRESSION TEST] Running Launcher_Glob with example_key='{example_key}'")
    run_launcher_glob(
        example_key=example_key,
        out_path=str(out_path),
        display_plots=False
    )
    
    # STEP 2: Locate the MODFLOW postprocessing directory
    _, postprocess_dir, _ = resolve_model_workspace(
        out_path,
        watershed_name=watershed_name,
        results_folder_name=results_folder_name,
        model_name_prefix=model_name_prefix,
    )
    
    # STEP 3: Collect output file signatures (hashes)
    print(f"[REGRESSION TEST] Collecting MODFLOW output signatures from: {postprocess_dir}")
    actual_signatures = collect_modflow_signatures(postprocess_dir, modflow_output_names)
    
    actual = {"modflow_expected": actual_signatures}
    
    # STEP 4: Compare with golden reference file
    print(f"[REGRESSION TEST] Comparing with golden reference: {golden_reference_file}")
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=golden_reference_file,
        update_goldens=update_goldens,
    )
    
    print(f"✓ REGRESSION TEST PASSED for {example_key}")


# ============================================================================
# EXAMPLE 00 - Verify Launcher_Glob(ex00) produces same results as example_00.py
# ============================================================================

GOLDEN_EX00 = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_00s_short_npy_signatures.json"
)


@pytest.mark.regression
@pytest.mark.fast
def test_launcher_glob_ex00_regression(tmp_path, update_goldens):
    """
    Regression test for Example 00 (simple hydrological model).
    
    Verifies: Launcher_Glob(ex00) produces identical MODFLOW outputs to example_00.py
    Expected files: watertable_elevation, watertable_depth, seepage_areas, etc.
    """
    run_launcher_glob_regression_test(
        example_key="ex00",
        watershed_name="00S_short",
        results_folder_name="results_simulations",
        golden_reference_file=GOLDEN_EX00,
        tmp_path=tmp_path,
        update_goldens=update_goldens,
    )


# ============================================================================
# EXAMPLE 01 - Verify Launcher_Glob(ex01) produces same results as example_01.py
# ============================================================================

GOLDEN_EX01 = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_01s_short_npy_signatures.json"
)


@pytest.mark.regression
@pytest.mark.fast
def test_launcher_glob_ex01_regression(tmp_path, update_goldens):
    """
    Regression test for Example 01 (simplified example from paper).
    
    Verifies: Launcher_Glob(ex01) produces identical MODFLOW outputs to example_01.py
    """
    run_launcher_glob_regression_test(
        example_key="ex01",
        watershed_name="01S_short",
        results_folder_name="results_simulations",
        golden_reference_file=GOLDEN_EX01,
        tmp_path=tmp_path,
        update_goldens=update_goldens,
    )


# ============================================================================
# EXAMPLE 03 - Verify Launcher_Glob(ex03) produces same results as example_03.py
# ============================================================================

GOLDEN_EX03 = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_03s_short_new_npy_signatures.json"
)


@pytest.mark.regression
@pytest.mark.fast
def test_launcher_glob_ex03_regression(tmp_path, update_goldens):
    """
    Regression test for Example 03 (hydrographic network).
    
    Verifies: Launcher_Glob(ex03) produces identical MODFLOW outputs to example_03.py
    """
    run_launcher_glob_regression_test(
        example_key="ex03",
        watershed_name="03S_short",
        results_folder_name="results_simulations",
        golden_reference_file=GOLDEN_EX03,
        tmp_path=tmp_path,
        update_goldens=update_goldens,
    )


# ============================================================================
# EXAMPLE 04 - Verify Launcher_Glob(ex04) produces same results as example_04.py
# ============================================================================

GOLDEN_EX04 = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_04s_short_npy_signatures.json"
)

MODFLOW_OUTPUTS_EX04 = [
    "watertable_elevation",
    "watertable_depth",
    "seepage_areas",
    "outflow_drain",
    "accumulation_flux",
]


@pytest.mark.regression
@pytest.mark.fast
def test_launcher_glob_ex04_regression(tmp_path, update_goldens):
    """
    Regression test for Example 04 (streamflow intermittence with porosity loop).
    
    Verifies: Launcher_Glob(ex04) loops over multiple porosity values and produces
              identical MODFLOW outputs to example_04.py for each iteration
    """
    run_launcher_glob_regression_test(
        example_key="ex04",
        watershed_name="04S_short",
        results_folder_name="results_simulations",
        golden_reference_file=GOLDEN_EX04,
        tmp_path=tmp_path,
        update_goldens=update_goldens,
        modflow_output_names=MODFLOW_OUTPUTS_EX04,
    )


# ============================================================================
# EXAMPLE 09 - Verify Launcher_Glob(ex09) produces same results as example_09.py
# ============================================================================

GOLDEN_EX09 = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_09s_short_new_npy_signatures.json"
)

MODFLOW_OUTPUTS_EX09 = [
    "watertable_elevation",
    "watertable_depth",
    "seepage_areas",
    "outflow_drain",
    "accumulation_flux",
]


@pytest.mark.regression
@pytest.mark.fast
def test_launcher_glob_ex09_regression(tmp_path, update_goldens):
    """
    Regression test for Example 09 (transport + calibration).
    
    Verifies: Launcher_Glob(ex09) with calibration setup produces identical
              MODFLOW outputs to example_09.py
    Note: Results stored in "results_calibration" folder with model prefix
    """
    run_launcher_glob_regression_test(
        example_key="ex09",
        watershed_name="09S_short",
        results_folder_name="results_calibration",
        golden_reference_file=GOLDEN_EX09,
        tmp_path=tmp_path,
        update_goldens=update_goldens,
        modflow_output_names=MODFLOW_OUTPUTS_EX09,
        model_name_prefix="TRANS1_",
    )


# ============================================================================
# EXAMPLE 12 - Verify Launcher_Glob(ex12) produces same results as example_12.py
# ============================================================================

GOLDEN_EX12 = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "launcher_glob_ex12_npy_signatures.json"
)

MODFLOW_OUTPUTS_EX12 = [
    "watertable_elevation",
    "watertable_depth",
    "seepage_areas",
    "outflow_drain",
    "accumulation_flux",
]


@pytest.mark.regression
@pytest.mark.fast
def test_launcher_glob_ex12_regression(tmp_path, update_goldens):
    """
    Regression test for Example 12 (complete workflow: MODFLOW + MODPATH + MT3DMS).
    
    Verifies: Launcher_Glob(ex12) with transport and particle tracking produces
              identical MODFLOW outputs to example_12.py
    Note: This is the most comprehensive test, including all post-processing options
    """
    run_launcher_glob_regression_test(
        example_key="ex12",
        watershed_name="example12",
        results_folder_name="results_simulations",
        golden_reference_file=GOLDEN_EX12,
        tmp_path=tmp_path,
        update_goldens=update_goldens,
        modflow_output_names=MODFLOW_OUTPUTS_EX12,
        model_name_prefix="TRANS1_",
    )

