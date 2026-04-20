"""Unit tests for calibration devkit helpers."""

from __future__ import annotations

import pytest

pytest.skip(
    "legacy analysis/calibration superseded by P09 hydromodpy/calibration",
    allow_module_level=True,
)


from pathlib import Path

from hydromodpy.analysis.calibration.devkit.check_case import check_case
from hydromodpy.analysis.calibration.devkit.config_reference import (
    build_config_reference_markdown,
    write_config_reference_markdown,
)
from hydromodpy.analysis.calibration.devkit.doctor import format_doctor_report, run_doctor
from hydromodpy.analysis.calibration.devkit.new_case import scaffold_case


def test_scaffold_case_creates_expected_files(tmp_path: Path):
    case_dir = tmp_path / "demo_case"
    report = scaffold_case("demo_case", destination=case_dir)

    assert report["case_name"] == "demo_case"
    assert Path(report["case_dir"]) == case_dir

    required = (
        "__init__.py",
        "README.md",
        "case_config.py",
        "workflow.py",
        "case_implementation.py",
        "run_calibration.py",
        "config_calibration.toml",
    )
    for name in required:
        assert (case_dir / name).exists()

    content = (case_dir / "case_implementation.py").read_text(encoding="utf-8")
    assert "class DemoCaseCalibrationCase" in content
    assert 'CASE_NAME = "demo_case"' in content


def test_scaffold_case_rejects_invalid_name():
    try:
        scaffold_case("Bad-Case")
    except ValueError as exc:
        assert "case_name must match pattern" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid case name")


def test_check_case_reports_existing_reservoir_case_ok():
    report = check_case("reservoir")
    assert report["ok"]
    assert report["checks"]["required_files"]["ok"]
    assert report["checks"]["implementation"]["ok"]
    assert report["checks"]["implementation"]["canonical_case_name"] == "reservoir"


def test_check_case_reports_missing_files(tmp_path: Path):
    cases_root = tmp_path / "cases"
    broken_dir = cases_root / "broken_case"
    broken_dir.mkdir(parents=True, exist_ok=True)
    (broken_dir / "__init__.py").write_text("", encoding="utf-8")

    report = check_case("broken_case", cases_root=cases_root)
    assert not report["ok"]
    assert report["checks"]["required_files"]["ok"] is False
    assert "case_config.py" in report["checks"]["required_files"]["missing"]


def test_run_doctor_returns_structured_report():
    report = run_doctor()
    assert "python" in report
    assert "modules" in report
    assert "methods" in report
    assert "cases" in report
    assert "simplex" in report["methods"]

    text = format_doctor_report(report)
    assert "Calibration doctor report" in text
    assert "Core modules:" in text


def test_config_reference_markdown_generation(tmp_path: Path):
    markdown = build_config_reference_markdown()
    assert "# Calibration Config Reference" in markdown
    assert "## Built-in Method Kwargs" in markdown
    assert "[calibration_method.simplex]" in markdown

    output = write_config_reference_markdown(tmp_path / "config_reference.md")
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "Case Chronicle Schemas" in content

