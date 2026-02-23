# -*- coding: utf-8 -*-
"""
Output Regression Tests for HydroModPy Launcher
Verifies launcher.py generates correct output files and signatures for ex03 and ex09
Compares output signatures (NPY, CSV) with golden references

Author: HydroModPy Team
Date: 2026-02-20
"""

import os
import sys
import pytest
from pathlib import Path

# Add root to path
root_dir = str(Path(__file__).parent.parent.parent)
sys.path.append(root_dir)

from tests.regression.golden_utils import (
    DEFAULT_MODFLOW_OUTPUT_NAMES,
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    collect_modpath_signatures,
    resolve_model_workspace,
    run_legacy_example_script,
    update_or_assert_goldens,
)

# ============================================================================
# CONFIGURATION & GOLDEN REFERENCES
# ============================================================================

LAUNCHER_SCRIPT = Path(root_dir) / "launcher.py"
GOLDEN_REFERENCES_DIR = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
)

MODPATH_SNAPSHOT_FILES = [
    "starting.dbf",
    "ending.dbf",
]

# Example configurations: watershed_name, example_key, golden_reference_filename
EXAMPLE_CONFIGS = {
    "ex03": {
        "example_key": "ex03",
        "watershed_name": "Somme",
        "model_name": "Model_Modflow_Test",
        "golden_file": GOLDEN_REFERENCES_DIR / "launcher_ex03_output_signatures.json",
        "timeout": 7200,
    },
    "ex09": {
        "example_key": "ex09",
        "watershed_name": "Guidh",
        "model_name": "Model_Modflow_Test",
        "golden_file": GOLDEN_REFERENCES_DIR / "launcher_ex09_output_signatures.json",
        "timeout": 7200,
    },
}


# ============================================================================
# LAUNCHER OUTPUT TESTS - PARAMETRIZED FOR EX03 & EX09
# ============================================================================

@pytest.mark.regression
@pytest.mark.slow
@pytest.mark.parametrize("example_key,config", [
    ("ex03", EXAMPLE_CONFIGS["ex03"]),
    ("ex09", EXAMPLE_CONFIGS["ex09"]),
])
def test_launcher_output_signatures(example_key, config, tmp_path, update_goldens):
    """
    Parametrized test: Run launcher.py for each example and compare output signatures.

    This single test function is automatically run once for each example configuration
    (ex03, ex09) thanks to pytest.mark.parametrize. This eliminates code duplication.

    For each example:
    1. Executes launcher.py with the example parameter
    2. Collects MODFLOW/MODPATH output signatures
    3. Compares with golden references (or updates them if --update-goldens flag is used)

    Args:
        example_key: Example identifier (ex03, ex09)
        config: Configuration dict with watershed_name, golden_file, timeout, etc.
        tmp_path: Pytest temporary directory
        update_goldens: Fixture to update golden references
    """
    print("\n" + "="*70)
    print(f"TEST: Launcher {example_key.upper()} Output Signatures")
    print("="*70)

    assert_required_executables()

    out_path = tmp_path / f"launcher_{example_key}_outputs"

    # ========================================================================
    # STEP 1: Run launcher
    # ========================================================================
    try:
        print(f"\n[STEP 1] Running launcher.py for example {example_key.upper()}...")
        run_legacy_example_script(
            script_path=LAUNCHER_SCRIPT,
            out_path=out_path,
            stop_method="postprocessing_netcdf",
            expected_stop_calls=1,
            timeout=config["timeout"],
            script_args={"example": config["example_key"]}
        )
        print("  ✓ Launcher execution completed")

    except Exception as e:
        pytest.fail(f"Failed to run launcher for {example_key}: {e}")

    # ========================================================================
    # STEP 2: Resolve model workspace
    # ========================================================================
    try:
        print("\n[STEP 2] Resolving model workspace...")
        _, postprocess_dir, particles_dir = resolve_model_workspace(
            out_path,
            watershed_name=config["watershed_name"],
            model_name=config["model_name"],
        )
        print(f"  ✓ Postprocess dir: {postprocess_dir}")
        print(f"  ✓ Particles dir: {particles_dir}")

    except Exception as e:
        pytest.fail(f"Failed to resolve workspace for {example_key}: {e}")

    # ========================================================================
    # STEP 3: Collect output signatures
    # ========================================================================
    try:
        print("\n[STEP 3] Collecting output signatures...")
        actual = {
            "modflow_expected": collect_modflow_signatures(
                postprocess_dir,
                DEFAULT_MODFLOW_OUTPUT_NAMES
            ),
            "modpath_expected": collect_modpath_signatures(
                particles_dir,
                MODPATH_SNAPSHOT_FILES
            ),
        }
        print(f"  ✓ MODFLOW signatures collected")
        print(f"  ✓ MODPATH signatures collected")
        if example_key == "ex09":
            print(f"  ⓘ MT3DMS transport model signatures included in MODFLOW set")

    except Exception as e:
        pytest.fail(f"Failed to collect signatures for {example_key}: {e}")

    # ========================================================================
    # STEP 4: Compare with golden references
    # ========================================================================
    try:
        print("\n[STEP 4] Comparing with golden references...")
        update_or_assert_goldens(
            actual=actual,
            golden_reference_file=config["golden_file"],
            update_goldens=update_goldens,
        )
        print("  ✓ Output signatures match golden reference")

    except AssertionError as e:
        pytest.fail(f"Output signature mismatch for {example_key}: {e}")

    print("\n" + "="*70)
    print(f" TEST PASSED: Launcher {example_key.upper()} outputs are correct")
    print("="*70)
