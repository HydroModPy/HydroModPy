#!/usr/bin/env python
"""
Generate golden reference signatures for launcher_glob regression tests.

This script:
1. Runs launcher_glob for each example (ex00, ex01, ex03, ex04, ex09, ex12)
2. Collects .npy signatures (modflow, modpath)
3. Saves them to JSON golden reference files for future regression tests

Usage:
    python generate_launcher_glob_golden_references.py
"""

import sys
from pathlib import Path
import tempfile
import json

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from tests.regression.golden_utils import (
    collect_modflow_signatures,
    collect_modpath_signatures,
    resolve_model_workspace,
    write_golden_reference
)

# Define examples to generate golden references for
EXAMPLES = {
    "ex00": {
        "watershed_name": "00S_short",
        "results_folder_name": "results",
        "modflow_outputs": [
            "watertable_elevation",
            "watertable_depth",
            "seepage_areas",
            "outflow_drain",
            "accumulation_flux",
        ],
        "modpath_files": [
            "starting.dbf",
            "starting_weighted.dbf",
            "ending.dbf",
            "ending_weighted.dbf",
        ]
    },
    "ex01": {
        "watershed_name": "01S_short",
        "results_folder_name": "results",
        "modflow_outputs": [
            "watertable_elevation",
            "watertable_depth",
            "seepage_areas",
            "outflow_drain",
            "accumulation_flux",
        ],
        "modpath_files": [
            "starting.dbf",
            "ending.dbf",
        ]
    },
    "ex03": {
        "watershed_name": "03S_short",
        "results_folder_name": "results",
        "modflow_outputs": [
            "watertable_elevation",
            "outflow_drain",
            "groundwater_flux",
            "groundwater_storage",
            "accumulation_flux",
        ],
        "modpath_files": [
            "starting.dbf",
            "ending.dbf",
        ]
    },
    "ex04": {
        "watershed_name": "04S_short",
        "results_folder_name": "results",
        "modflow_outputs": [
            "watertable_elevation",
            "outflow_drain",
            "groundwater_flux",
            "groundwater_storage",
            "accumulation_flux",
        ],
        "modpath_files": [
            "starting.dbf",
            "ending.dbf",
        ]
    },
    "ex09": {
        "watershed_name": "09S_short",
        "results_folder_name": "results",
        "modflow_outputs": [
            "watertable_elevation",
            "outflow_drain",
            "groundwater_flux",
            "groundwater_storage",
            "accumulation_flux",
        ],
        "modpath_files": [
            "starting.dbf",
            "ending.dbf",
        ]
    },
    "ex12": {
        "watershed_name": "example12",
        "results_folder_name": "results_simulations",
        "modflow_outputs": [
            "watertable_elevation",
            "watertable_depth",
            "seepage_areas",
            "outflow_drain",
            "accumulation_flux",
        ],
        "modpath_files": [
            "starting.dbf",
            "ending.dbf",
        ]
    },
}

GOLDEN_REF_DIR = REPO_ROOT / "tests" / "regression" / "reference" / "golden_references"


def generate_golden_reference(example_key: str):
    """Generate and save golden reference for one example via launcher_glob."""
    config = EXAMPLES[example_key]

    # Import run_launcher_glob from Launcher_Glob
    sys.path.insert(0, str(REPO_ROOT / "examples" / "Examples_Launchers"))
    try:
        from Launcher_Glob import run_launcher_glob
    except ImportError as e:
        print(f"  ✗ Could not import run_launcher_glob: {e}")
        return False

    print(f"\n{'='*70}")
    print(f"Generating golden reference for {example_key.upper()}".center(70))
    print(f"{'='*70}")

    # Create temporary directory and run launcher_glob
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        out_path = tmp_path / f"launcher_glob_{example_key}_outputs"

        try:
            print(f"  Running launcher_glob for {example_key}...")
            run_launcher_glob(
                example_key=example_key,
                out_path=out_path,
                display_plots=False
            )
            print(f"  ✓ Execution completed")
        except Exception as e:
            print(f"  ✗ Execution failed: {e}")
            import traceback
            traceback.print_exc()
            return False

        # Resolve output paths
        try:
            _, postprocess_dir, particles_dir = resolve_model_workspace(
                out_path,
                watershed_name=config["watershed_name"],
                results_folder_name=config["results_folder_name"],
            )
            print(f"  ✓ Output paths resolved")
        except Exception as e:
            print(f"  ✗ Could not resolve output paths: {e}")
            import traceback
            traceback.print_exc()
            return False

        # Collect signatures
        try:
            modflow_sig = collect_modflow_signatures(postprocess_dir, config["modflow_outputs"])
            modpath_sig = collect_modpath_signatures(particles_dir, config["modpath_files"])
            print(f"  ✓ Signatures collected")
        except Exception as e:
            print(f"  ✗ Could not collect signatures: {e}")
            import traceback
            traceback.print_exc()
            return False

        # Build golden reference payload
        golden_payload = {
            "modflow_expected": modflow_sig,
            "modpath_expected": modpath_sig,
        }

        # Save to JSON file
        golden_file = GOLDEN_REF_DIR / f"launcher_glob_{example_key}_npy_signatures.json"
        try:
            write_golden_reference(golden_file, golden_payload)
            print(f"  ✓ Saved: {golden_file.relative_to(REPO_ROOT)}")
            return True
        except Exception as e:
            print(f"  ✗ Could not save golden reference: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    """Generate all golden references."""
    print("\n" + "="*70)
    print("GENERATING LAUNCHER_GLOB GOLDEN REFERENCES".center(70))
    print("="*70)

    results = {}
    for example_key in EXAMPLES.keys():
        results[example_key] = generate_golden_reference(example_key)

    # Summary
    print("\n" + "="*70)
    print("SUMMARY".center(70))
    print("="*70)

    for example_key, success in results.items():
        status = "✓" if success else "✗"
        print(f"  {status} {example_key}")

    all_success = all(results.values())
    if all_success:
        print("\n✓ All golden references generated successfully!")
    else:
        print("\n✗ Some golden references failed to generate")

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
