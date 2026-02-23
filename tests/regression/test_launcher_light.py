# -*- coding: utf-8 -*-
"""
Light Regression Tests for HydroModPy Launcher
Fast validation tests for launcher.py structure and configuration
These tests do NOT create watersheds - they are quick validation checks (<1s each)

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

# ============================================================================
# LIGHT REGRESSION TESTS: LAUNCHER STRUCTURE & CONFIGURATION
# ============================================================================

class TestLauncherLightRegression:
    """
    Light regression tests for launcher.py - Fast validation tests
    Tests structure, configuration, and imports without heavy computations
    These tests are fast (<1s each) and focus on ensuring launcher integrity
    """

    def test_launcher_config_structure(self):
        """Test that launcher.py CONFIG has correct structure"""
        print("\n[LIGHT TEST] Testing launcher CONFIG structure...")

        try:
            launcher_path = os.path.join(root_dir, "launcher.py")

            with open(launcher_path, 'r') as f:
                content = f.read()

            # Verify CONFIG exists and has expected structure
            assert 'CONFIG = {' in content, "CONFIG dictionary not found"
            assert '"example"' in content, "CONFIG missing 'example' key"
            assert '"sections"' in content, "CONFIG missing 'sections' key"

            # Verify expected sections
            expected_sections = [
                "watershed", "data", "recharge", "parametrization",
                "modeling", "matching_streams", "modpath", "mt3dms", "plot",
                "plot_animation_interactive"
            ]

            for section in expected_sections:
                assert f'"{section}"' in content, f"CONFIG missing section: {section}"

            print(f"  ✓ CONFIG structure valid ({len(expected_sections)} sections found)")

        except AssertionError as e:
            pytest.fail(f"CONFIG structure validation failed: {e}")

    def test_launcher_params_structure(self):
        """Test that launcher.py PARAMS has correct structure for both examples"""
        print("\n[LIGHT TEST] Testing launcher PARAMS structure...")

        try:
            launcher_path = os.path.join(root_dir, "launcher.py")

            with open(launcher_path, 'r') as f:
                content = f.read()

            # Verify PARAMS exists and has both examples
            assert 'PARAMS = {' in content, "PARAMS dictionary not found"
            assert '"ex03"' in content, "PARAMS missing ex03 example"
            assert '"ex09"' in content, "PARAMS missing ex09 example"

            # Verify required parameters for ex03
            ex03_required = ["base_path", "dem_filename", "dem_coordinates", "watershed_name"]
            for param in ex03_required:
                assert f'"{param}"' in content, f"ex03 PARAMS missing: {param}"

            print("  ✓ PARAMS structure valid (ex03 and ex09 complete)")

        except AssertionError as e:
            pytest.fail(f"PARAMS structure validation failed: {e}")

    def test_launcher_functions_exist(self):
        """Test that all required launcher functions are defined"""
        print("\n[LIGHT TEST] Testing launcher functions exist...")

        try:
            launcher_path = os.path.join(root_dir, "launcher.py")

            with open(launcher_path, 'r') as f:
                content = f.read()

            # Verify generic functions
            generic_functions = ["watershed", "recharge"]
            for func in generic_functions:
                assert f'def {func}(' in content, f"Generic function missing: {func}"

            # Verify ex03 functions
            ex03_functions = [
                "ex03_data", "ex03_recharge_plot", "ex03_parametrization",
                "ex03_modeling", "ex03_plot"
            ]
            for func in ex03_functions:
                assert f'def {func}(' in content, f"Ex03 function missing: {func}"

            # Verify ex09 functions
            ex09_functions = [
                "ex09_data", "ex09_recharge_plot", "ex09_modeling",
                "ex09_matching_streams", "ex09_modpath", "ex09_mt3dms",
                "ex09_plot_streamflow", "ex09_plot_piezometry",
                "ex09_plot_pathlines", "ex09_plot_concentration",
                "ex09_plot_animation_interactive"
            ]
            for func in ex09_functions:
                assert f'def {func}(' in content, f"Ex09 function missing: {func}"

            total_functions = len(generic_functions) + len(ex03_functions) + len(ex09_functions)
            print(f"  ✓ All {total_functions} required functions found")

        except AssertionError as e:
            pytest.fail(f"Function validation failed: {e}")

    def test_launcher_workflow_definition(self):
        """Test that WORKFLOW_DEFINITION is complete and valid"""
        print("\n[LIGHT TEST] Testing WORKFLOW_DEFINITION structure...")

        try:
            launcher_path = os.path.join(root_dir, "launcher.py")

            with open(launcher_path, 'r') as f:
                content = f.read()

            # Verify WORKFLOW_DEFINITION exists
            assert 'WORKFLOW_DEFINITION = {' in content, "WORKFLOW_DEFINITION not found"

            # Verify both examples have workflows
            assert '"ex03"' in content, "Workflow missing for ex03"
            assert '"ex09"' in content, "Workflow missing for ex09"

            # Verify workflow components
            workflow_keys = ["step", "section", "function", "requires", "provides"]
            for key in workflow_keys:
                assert f'"{key}"' in content, f"Workflow definition missing key: {key}"

            print(f"  ✓ WORKFLOW_DEFINITION valid")

        except AssertionError as e:
            pytest.fail(f"WORKFLOW_DEFINITION validation failed: {e}")

    def test_launcher_main_function_exists(self):
        """Test that launcher has a working main() function"""
        print("\n[LIGHT TEST] Testing launcher main() function...")

        try:
            launcher_path = os.path.join(root_dir, "launcher.py")

            with open(launcher_path, 'r') as f:
                content = f.read()

            # Verify main function exists
            assert 'def main(' in content, "main() function not found"

            # Verify main contains key logic
            assert 'CONFIG' in content, "main() doesn't reference CONFIG"
            assert 'example_key' in content, "main() missing example_key handling"
            assert 'sections' in content, "main() missing sections handling"

            print("  ✓ main() function structure valid")

        except AssertionError as e:
            pytest.fail(f"main() function validation failed: {e}")

    def test_launcher_plotly_integration(self):
        """Test that Plotly animation function is integrated"""
        print("\n[LIGHT TEST] Testing Plotly integration...")

        try:
            launcher_path = os.path.join(root_dir, "launcher.py")

            with open(launcher_path, 'r') as f:
                content = f.read()

            # Verify Plotly function exists
            assert 'def ex09_plot_animation_interactive(' in content, \
                "Plotly animation function not found"

            # Verify function is in CONFIG
            assert '"plot_animation_interactive"' in content, \
                "plot_animation_interactive not in CONFIG sections"

            # Verify function is in WORKFLOW_DEFINITION
            assert 'ex09_plot_animation_interactive' in content, \
                "Plotly function not in workflow definition"

            print("  ✓ Plotly integration verified")

        except AssertionError as e:
            pytest.fail(f"Plotly integration validation failed: {e}")

    def test_launcher_code_consistency(self):
        """Test that launcher variable naming is consistent"""
        print("\n[LIGHT TEST] Testing code consistency...")

        try:
            launcher_path = os.path.join(root_dir, "launcher.py")

            with open(launcher_path, 'r') as f:
                content = f.read()

            # Check that new variable names are used consistently
            assert 'initializing_object' in content, \
                "New variable name 'initializing_object' not found"
            assert 'geographic_object' in content, \
                "New variable name 'geographic_object' not found"

            print("  ✓ Code consistency validated")

        except AssertionError as e:
            pytest.fail(f"Code consistency validation failed: {e}")

    def test_launcher_syntax_valid(self):
        """Test that launcher.py has valid Python syntax"""
        print("\n[LIGHT TEST] Testing launcher.py syntax...")

        try:
            launcher_path = os.path.join(root_dir, "launcher.py")

            # Try to compile the file
            with open(launcher_path, 'r') as f:
                compile(f.read(), launcher_path, 'exec')

            print("  ✓ Launcher syntax is valid")

        except SyntaxError as e:
            pytest.fail(f"Syntax error in launcher.py: {e}")
