"""
Public devkit API for calibration2 onboarding and maintenance.

How to read this module
-----------------------
This file is a small facade: it re-exports the most useful helpers so users
can import from one stable location:
`hydromodpy.calibration.devkit`.

Who uses it
-----------
- New contributors creating a calibration case,
- maintainers validating case integrity after refactors,
- developers generating schema documentation for config review.

Exposed helpers:
- `scaffold_case`: create a new case skeleton from templates.
- `check_case`: validate structure/interface/config and optional smoke run.
- `run_doctor` / `format_doctor_report`: environment and integration health.
- `build_config_reference_markdown` / `write_config_reference_markdown`:
  schema-driven config documentation.
"""

from hydromodpy.calibration.devkit.check_case import check_case
from hydromodpy.calibration.devkit.config_reference import (
    build_config_reference_markdown,
    write_config_reference_markdown,
)
from hydromodpy.calibration.devkit.doctor import format_doctor_report, run_doctor
from hydromodpy.calibration.devkit.new_case import scaffold_case

__all__ = (
    "scaffold_case",
    "check_case",
    "build_config_reference_markdown",
    "write_config_reference_markdown",
    "run_doctor",
    "format_doctor_report",
)

