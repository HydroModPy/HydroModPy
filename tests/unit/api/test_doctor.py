"""Unit tests for the verb ``doctor``."""

from __future__ import annotations

import pytest

from hydromodpy.project import api
from hydromodpy.project.doctor import DoctorReport

pytestmark = pytest.mark.fast


def test_doctor_returns_a_report_with_the_expected_keys() -> None:
    report = api.doctor()
    assert isinstance(report, DoctorReport)
    assert set(report.to_dict()) == {"python", "hydromodpy", "solvers", "optional"}
