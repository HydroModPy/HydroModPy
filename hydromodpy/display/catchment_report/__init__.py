"""Catchment-scale report assembly helpers."""

from hydromodpy.display.catchment_report.builder import (
    GENERIC_REPORT_PRESET,
    CatchmentReportConfig,
    CatchmentReportPreset,
    build_catchment_report,
    preset_from_name,
)
from hydromodpy.display.catchment_report.context import build_context_from_report_config
from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
from hydromodpy.display.catchment_report.pipeline import run_catchment_report_pipeline
from hydromodpy.display.catchment_report.settings import CatchmentReportSettings, ReportConfig

__all__ = [
    "CatchmentReportConfig",
    "CatchmentReportInputs",
    "CatchmentReportSettings",
    "CatchmentReportPreset",
    "GENERIC_REPORT_PRESET",
    "ReportConfig",
    "build_context_from_report_config",
    "build_catchment_report",
    "preset_from_name",
    "run_catchment_report_pipeline",
]
