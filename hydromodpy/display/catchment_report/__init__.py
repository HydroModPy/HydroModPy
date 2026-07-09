"""Catchment-scale report assembly helpers."""

from hydromodpy.display.catchment_report.build_options import CatchmentReportBuildOptions
from hydromodpy.display.catchment_report.builder import (
    CatchmentReportConfig,
    build_catchment_report,
)
from hydromodpy.display.catchment_report.context import build_context_from_report_config
from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
from hydromodpy.display.catchment_report.pipeline import run_catchment_report_pipeline
from hydromodpy.display.catchment_report.presets import (
    GENERIC_REPORT_PRESET,
    CatchmentReportPreset,
    preset_from_name,
)
from hydromodpy.display.catchment_report.settings import CatchmentReportSettings

__all__ = [
    "CatchmentReportConfig",
    "CatchmentReportBuildOptions",
    "CatchmentReportInputs",
    "CatchmentReportSettings",
    "CatchmentReportPreset",
    "GENERIC_REPORT_PRESET",
    "build_context_from_report_config",
    "build_catchment_report",
    "preset_from_name",
    "run_catchment_report_pipeline",
]
