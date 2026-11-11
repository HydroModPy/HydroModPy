"""Unit tests for the verb ``doctor``."""

from __future__ import annotations

import pytest

from hydromodpy.core.version import __version__
from hydromodpy.project import api
from hydromodpy.project.doctor import DoctorReport

pytestmark = pytest.mark.fast


def test_doctor_returns_a_report_with_the_expected_keys() -> None:
    report = api.doctor()
    assert isinstance(report, DoctorReport)
    assert set(report.to_dict()) == {"python", "hydromodpy", "solvers", "optional"}


@pytest.mark.parametrize(
    ("section", "names"),
    [
        ("solvers", ("mf2005", "mfnwt", "mf6")),
        ("optional", ("flopy", "gmsh", "duckdb", "zarr", "pyproj", "rasterio")),
    ],
)
def test_doctor_records_each_lookup(section, names) -> None:
    held = api.doctor().to_dict()[section]
    assert isinstance(held, dict)
    for name in names:
        assert name in held


def test_doctor_python_and_hydromodpy_versions() -> None:
    report = api.doctor()
    assert report.python.count(".") >= 1
    assert report.hydromodpy == __version__
