#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Build script for compiling HELP3O Fortran extension.

This script is called during package installation (via pyproject.toml)
to compile the HELP3O Fortran module for the current platform and Python version.
"""

import os
import sys
import subprocess
from pathlib import Path


def build_help3o_extension():
    """Build the HELP3O Fortran extension using numpy.f2py."""

    # Get paths
    project_root = Path(__file__).parent
    pyhelp_dir = project_root / "hydromodpy" / "pyhelp"
    fortran_source = pyhelp_dir / "HELP3O.FOR"

    if not fortran_source.exists():
        print(f"ERROR: FORTRAN source not found: {fortran_source}")
        return False

    print("=" * 70)
    print("Building HELP3O Fortran extension module")
    print("=" * 70)
    print(f"Source: {fortran_source}")
    print(f"Target directory: {pyhelp_dir}")
    print(f"Python: {sys.version}")
    print(f"Platform: {sys.platform}")

    # Remove old compiled versions
    old_extensions = list(pyhelp_dir.glob("HELP3O*.pyd")) + list(pyhelp_dir.glob("HELP3O*.so"))
    for old_ext in old_extensions:
        print(f"Removing old extension: {old_ext}")
        old_ext.unlink()

    # Build using f2py via command line for better control
    cmd = [
        sys.executable, '-m', 'numpy.f2py',
        '-c',  # Compile
        '-m', 'HELP3O',  # Module name
        str(fortran_source),
    ]

    print(f"\nRunning: {' '.join(cmd)}")
    print("-" * 70)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(pyhelp_dir),
            check=True,
            capture_output=False,
            text=True
        )

        print("-" * 70)
        print("HELP3O extension built successfully!")

        # Verify the extension was created
        extensions = list(pyhelp_dir.glob("HELP3O*.pyd")) + list(pyhelp_dir.glob("HELP3O*.so"))
        if extensions:
            print(f"Created: {extensions[0].name}")
        else:
            print("WARNING: Extension file not found after build")

        print("=" * 70)
        return True

    except subprocess.CalledProcessError as e:
        print("-" * 70)
        print(f"ERROR: Failed to build HELP3O extension")
        print(f"Return code: {e.returncode}")
        print("\nThis is likely because a Fortran compiler is not installed.")
        print("\nTo install gfortran:")
        print("  Linux (Debian/Ubuntu): sudo apt-get install gfortran")
        print("  Linux (RedHat/CentOS): sudo yum install gcc-gfortran")
        print("  macOS: brew install gcc")
        print("  Windows: Install MinGW-w64 or Intel Fortran")
        print("\nAfter installing gfortran, run: python build_extensions.py")
        print("=" * 70)
        return False
    except Exception as e:
        print(f"ERROR: Unexpected error during build: {e}")
        print("\nPlease check that you have:")
        print("  1. A Fortran compiler (gfortran, ifort, etc.) installed")
        print("  2. NumPy installed (pip install numpy)")
        print("  3. Meson build system (pip install meson meson-python ninja)")
        return False


if __name__ == "__main__":
    success = build_help3o_extension()
    sys.exit(0 if success else 1)
