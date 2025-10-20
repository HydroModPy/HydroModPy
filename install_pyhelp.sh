#!/bin/bash
# Installation script for HydroModPy with PyHELP support
# This script ensures all dependencies are installed before building the HELP3O extension

set -e  # Exit on error

echo "=================================================================="
echo "HydroModPy Installation with PyHELP Support"
echo "=================================================================="

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    OS="windows"
else
    OS="unknown"
fi

echo "Detected OS: $OS"

# Check for Fortran compiler
echo ""
echo "Checking for Fortran compiler..."
if command -v gfortran &> /dev/null; then
    echo "✓ gfortran found: $(gfortran --version | head -1)"
else
    echo "✗ gfortran not found!"
    echo ""
    echo "PyHELP requires a Fortran compiler. Please install it:"

    if [[ "$OS" == "linux" ]]; then
        echo ""
        echo "Ubuntu/Debian:"
        echo "  sudo apt-get update"
        echo "  sudo apt-get install gfortran"
        echo ""
        echo "RedHat/CentOS:"
        echo "  sudo yum install gcc-gfortran"
    elif [[ "$OS" == "macos" ]]; then
        echo ""
        echo "macOS (using Homebrew):"
        echo "  brew install gcc"
    elif [[ "$OS" == "windows" ]]; then
        echo ""
        echo "Windows: Install MinGW-w64 from https://www.mingw-w64.org/"
    fi

    echo ""
    read -p "Continue without Fortran compiler? (PyHELP will not work) [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check Python version
echo ""
echo "Checking Python version..."
python_version=$(python --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

required_version="3.11"
if [[ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]]; then
    echo "✗ Python $required_version or higher is required!"
    echo "  Current version: $python_version"
    exit 1
fi
echo "✓ Python version OK"

# Install build dependencies
echo ""
echo "Installing build dependencies..."
pip install --upgrade pip
pip install numpy meson meson-python ninja build wheel setuptools

# Build HELP3O extension
echo ""
echo "Building HELP3O Fortran extension..."
if python build_extensions.py; then
    echo "✓ HELP3O extension built successfully"
else
    echo "✗ Failed to build HELP3O extension"
    echo ""
    echo "The installation will continue, but PyHELP functionality will be limited."
    echo "You can try to compile manually later by running:"
    echo "  python build_extensions.py"
    echo ""
    read -p "Continue anyway? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Install HydroModPy
echo ""
echo "Installing HydroModPy..."
pip install -e .

echo ""
echo "=================================================================="
echo "Installation complete!"
echo "=================================================================="
echo ""
echo "To test the installation, run:"
echo "  python -c 'from hydromodpy.pyhelp import HelpManager; print(\"Success!\")'"
echo ""
