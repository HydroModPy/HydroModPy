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


def _prt(monkeypatch, tmp_path, version):
    mf6 = tmp_path / "mf6"
    mf6.touch()
    monkeypatch.setattr(doctor, "locate_mf6", lambda: mf6)
    monkeypatch.setattr(doctor, "mf6_version", lambda _exe: version)
    return {entry["name"]: entry for entry in doctor.prt_checks()}


@pytest.mark.parametrize(
    ("version", "status"),
    [
        (("mf6: 6.6.3", (6, 6, 3)), "OK"),
        (("mf6: 6.5.0", (6, 5, 0)), "OK"),
        (("mf6: 6.4.1", (6, 4, 1)), "KO"),
    ],
)
def test_prt_needs_mf6_6_5_or_newer(monkeypatch, tmp_path, version, status) -> None:
    checks = _prt(monkeypatch, tmp_path, version)

    assert checks["prt:mf6"]["status"] == "OK"
    assert checks["prt:mf6_version"]["status"] == status
    assert checks["prt:flopy"]["status"] == "OK"
    if status == "KO":
        assert "install-binaries" in checks["prt:mf6_version"]["hint"]


def test_prt_warns_on_a_banner_with_no_version(monkeypatch, tmp_path) -> None:
    checks = _prt(monkeypatch, tmp_path, ("", None))

    assert checks["prt:mf6_version"]["status"] == "WARN"
    assert "empty" in checks["prt:mf6_version"]["detail"]


def test_prt_reports_a_missing_mf6(monkeypatch) -> None:
    monkeypatch.setattr(doctor, "locate_mf6", lambda: None)

    checks = doctor.prt_checks()

    assert [entry["status"] for entry in checks] == ["KO"]
    assert checks[0]["name"] == "prt:mf6"


@pytest.mark.parametrize(
    ("banner", "parsed"),
    [("mf6: 6.6.3 07/30/2025", (6, 6, 3)), ("no number here", None)],
)
def test_the_version_is_read_from_the_banner(monkeypatch, tmp_path, banner, parsed) -> None:
    class Done:
        stdout = banner
        stderr = ""

    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: Done())

    assert doctor.mf6_version(tmp_path / "mf6") == (banner, parsed)


def test_the_required_and_the_optional_packages_make_the_packages() -> None:
    assert doctor.PACKAGES == doctor.REQUIRED_PACKAGES + doctor.OPTIONAL_PACKAGES
    assert set(doctor.SOLVER_BINARIES) == set(doctor.SOLVERS) - {"mf2005"}


def test_the_report_of_hmp_doctor_has_a_row_for_each_package_and_solver(monkeypatch) -> None:
    report = doctor.build_report(doctor_report().to_dict(), None, None)
    names = [row["name"] for row in report["checks"]]

    assert [n for n in names if n.startswith("dep:")] == [
        f"dep:{p}" for p in doctor.REQUIRED_PACKAGES
    ]
    assert [n for n in names if n.startswith("opt:")] == [
        f"opt:{p}" for p in doctor.OPTIONAL_PACKAGES
    ]
    assert [n for n in names if n.startswith("solver:") and n.split(":")[1] in doctor.SOLVERS] == [
        f"solver:{s}" for s in doctor.SOLVER_BINARIES
    ]
    assert names[-1] == "workspace"


def test_a_missing_workspace_is_a_warning_that_names_the_way_out() -> None:
    rows = doctor.probe_workspace(None, None)

    assert [(row["name"], row["status"]) for row in rows] == [("workspace", "WARN")]
    assert "-w" in rows[0]["hint"]


def test_a_path_that_is_there_is_ok_and_one_that_is_not_is_a_warning(tmp_path) -> None:
    assert doctor.path_check("data_dir", tmp_path)["status"] == "OK"
    missing = doctor.path_check("data_dir", tmp_path / "absent")
    assert missing["status"] == "WARN"
    assert missing["detail"].endswith("(missing)")


def test_the_checks_that_read_a_workspace_say_so_when_there_is_none() -> None:
    assert doctor.cross_catalog_checks(None)[0]["name"] == "cross_catalog:workspace"
    assert doctor.lifecycle_checks(None)[0]["name"] == "lifecycle:workspace"


def test_a_data_folder_that_is_not_there_is_a_warning(tmp_path) -> None:
    row = doctor.data_cache_check(tmp_path / "data")

    assert (row["name"], row["status"]) == ("data_cache", "WARN")
    assert "missing" in row["detail"]
