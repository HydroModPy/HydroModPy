"""The doctor report (``hydromodpy/project/doctor.py``): its members and its JSON form."""

from __future__ import annotations

import json

import pytest

from hydromodpy.core.version import __version__
from hydromodpy.project import doctor
from hydromodpy.project.doctor import DoctorReport, doctor_report

pytestmark = pytest.mark.fast


def _report() -> DoctorReport:
    return DoctorReport(
        python="3.12.1",
        hydromodpy="9.9",
        solvers={"mf6": "/bin/mf6", "mfnwt": None},
        optional={"numpy": "2.0", "gmsh": None},
    )


def test_to_dict_keeps_the_keys_and_their_order_of_the_old_dict() -> None:
    assert list(_report().to_dict()) == ["python", "hydromodpy", "solvers", "optional"]


def test_to_dict_is_json_and_carries_every_member() -> None:
    document = json.loads(json.dumps(_report().to_dict()))
    assert document == {
        "python": "3.12.1",
        "hydromodpy": "9.9",
        "solvers": {"mf6": "/bin/mf6", "mfnwt": None},
        "optional": {"numpy": "2.0", "gmsh": None},
    }


def test_the_report_of_this_machine_names_every_solver_and_package() -> None:
    report = doctor_report()
    assert report.hydromodpy == __version__
    assert report.python.count(".") >= 1
    assert tuple(report.solvers) == doctor.SOLVERS
    assert tuple(report.optional) == doctor.PACKAGES


@pytest.mark.parametrize(
    ("found", "expected"),
    [("/usr/bin/mf6", "/usr/bin/mf6"), (None, None)],
)
def test_a_solver_is_its_path_or_none(monkeypatch, found, expected) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: found)
    assert set(doctor_report().solvers.values()) == {expected}


def test_a_package_that_fails_to_import_is_none(monkeypatch) -> None:
    real = doctor.importlib.import_module

    def import_module(name: str):
        if name == "gmsh":
            raise ImportError(name)
        return real(name)

    monkeypatch.setattr(doctor.importlib, "import_module", import_module)
    optional = doctor_report().optional
    assert optional["gmsh"] is None
    assert optional["numpy"] not in (None, "")
