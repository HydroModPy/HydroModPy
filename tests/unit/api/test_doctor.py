"""Unit tests for ``hmp.doctor``."""

from __future__ import annotations

import pytest

import hydromodpy as hmp

pytestmark = pytest.mark.fast


def test_doctor_returns_dict() -> None:
    """``hmp.doctor`` returns a dict with the expected top-level keys."""
    report = hmp.doctor()
    assert isinstance(report, dict)
    for key in ("python", "hydromodpy", "solvers", "optional"):
        assert key in report


def test_doctor_records_solvers_lookup() -> None:
    """``solvers`` contains entries for the three MODFLOW executables."""
    report = hmp.doctor()
    solvers = report["solvers"]
    assert isinstance(solvers, dict)
    for exe in ("mf2005", "mfnwt", "mf6"):
        assert exe in solvers


def test_doctor_records_optional_packages() -> None:
    """``optional`` contains entries for known optional dependencies."""
    report = hmp.doctor()
    optional = report["optional"]
    assert isinstance(optional, dict)
    for pkg in ("flopy", "gmsh", "duckdb", "zarr", "pyproj", "rasterio"):
        assert pkg in optional


def test_doctor_python_version_is_string() -> None:
    """``python`` is a string version (e.g. ``3.11.5``)."""
    report = hmp.doctor()
    assert isinstance(report["python"], str)
    assert report["python"].count(".") >= 1


def test_doctor_hydromodpy_version_string() -> None:
    """``hydromodpy`` matches the package version."""
    report = hmp.doctor()
    from hydromodpy.core.version import __version__

    assert report["hydromodpy"] == __version__
