@echo off
REM Installation script for HydroModPy with PyHELP support (Windows)
REM This script ensures all dependencies are installed before building the HELP3O extension

echo ==================================================================
echo HydroModPy Installation with PyHELP Support (Windows)
echo ==================================================================

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3.11 or higher.
    pause
    exit /b 1
)

echo.
echo Python found:
python --version

REM Check for gfortran
echo.
echo Checking for Fortran compiler...
gfortran --version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] gfortran not found!
    echo.
    echo PyHELP requires a Fortran compiler. Please install MinGW-w64:
    echo   https://www.mingw-w64.org/
    echo.
    echo Or use conda with fortran compiler:
    echo   conda install -c conda-forge m2w64-toolchain
    echo.
    set /p continue="Continue without Fortran compiler? (PyHELP will not work) [y/N]: "
    if /i not "%continue%"=="y" exit /b 1
) else (
    echo Fortran compiler found:
    gfortran --version | findstr /C:"GCC"
)

REM Install build dependencies
echo.
echo Installing build dependencies...
python -m pip install --upgrade pip
python -m pip install numpy meson meson-python ninja build wheel setuptools

REM Build HELP3O extension
echo.
echo Building HELP3O Fortran extension...
python build_extensions.py
if errorlevel 1 (
    echo [WARNING] Failed to build HELP3O extension
    echo.
    echo The installation will continue, but PyHELP functionality will be limited.
    echo You can try to compile manually later by running:
    echo   python build_extensions.py
    echo.
    set /p continue="Continue anyway? [y/N]: "
    if /i not "%continue%"=="y" exit /b 1
) else (
    echo HELP3O extension built successfully
)

REM Install HydroModPy
echo.
echo Installing HydroModPy...
pip install -e .

echo.
echo ==================================================================
echo Installation complete!
echo ==================================================================
echo.
echo To test the installation, run:
echo   python -c "from hydromodpy.pyhelp import HelpManager; print('Success!')"
echo.
pause
