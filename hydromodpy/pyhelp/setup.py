#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Setup script for building the HELP3O Fortran extension module.

This script uses numpy.f2py to compile the FORTRAN source code
into a Python extension module that works across different platforms
and Python versions.
"""

from pathlib import Path
import sys


def build_help3o():
    """Build the HELP3O extension module using f2py."""
    from numpy import f2py

    # Get the directory containing this setup.py file
    pyhelp_dir = Path(__file__).parent
    fortran_source = pyhelp_dir / "HELP3O.FOR"

    if not fortran_source.exists():
        raise FileNotFoundError(f"FORTRAN source not found: {fortran_source}")

    print(f"Building HELP3O extension from {fortran_source}")

    # Prepare f2py arguments
    # The module will be named HELP3O and will be built in-place
    sys.argv = [
        'f2py',
        '-c',  # Compile
        '-m', 'HELP3O',  # Module name
        str(fortran_source),
        '--quiet'
    ]

    # Run f2py compilation
    f2py.main()

    print("HELP3O extension built successfully")


if __name__ == "__main__":
    build_help3o()
