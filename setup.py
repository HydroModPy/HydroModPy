#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Custom setup.py for HydroModPy to handle FORTRAN extension compilation.

This setup script ensures the HELP3O Fortran module is compiled
during package installation for the target platform and Python version.
"""

import os
import sys
import subprocess
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.develop import develop
from setuptools.command.install import install


class BuildHELP3OCommand:
    """Mixin class to build HELP3O extension."""

    def build_help3o(self):
        """Compile the HELP3O Fortran extension."""
        print("\n" + "=" * 70)
        print("Building HELP3O Fortran extension")
        print("=" * 70)

        # Run the build script
        build_script = Path(__file__).parent / "build_extensions.py"

        try:
            subprocess.check_call([sys.executable, str(build_script)])
            print("HELP3O extension compiled successfully")
        except subprocess.CalledProcessError as e:
            print(f"\nWARNING: Failed to compile HELP3O extension (exit code {e.returncode})")
            print("The package will be installed but pyhelp functionality may be limited.")
            print("You can manually compile later by running: python build_extensions.py")
        except Exception as e:
            print(f"\nWARNING: Unexpected error during HELP3O compilation: {e}")
            print("The package will be installed but pyhelp functionality may be limited.")

        print("=" * 70 + "\n")


class CustomBuildPy(build_py, BuildHELP3OCommand):
    """Custom build_py command that compiles HELP3O."""

    def run(self):
        self.build_help3o()
        super().run()


class CustomDevelop(develop, BuildHELP3OCommand):
    """Custom develop command that compiles HELP3O."""

    def run(self):
        self.build_help3o()
        super().run()


class CustomInstall(install, BuildHELP3OCommand):
    """Custom install command that compiles HELP3O."""

    def run(self):
        self.build_help3o()
        super().run()


# Run setup with custom commands
setup(
    cmdclass={
        'build_py': CustomBuildPy,
        'develop': CustomDevelop,
        'install': CustomInstall,
    },
)
