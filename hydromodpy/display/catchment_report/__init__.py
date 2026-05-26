"""Catchment-scale report assembly helpers."""

from hydromodpy.display.catchment_report.builder import (
    CatchmentReportConfig,
    build_catchment_report,
)
from hydromodpy.display.catchment_report.context import build_context_from_report_config
from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
from hydromodpy.display.catchment_report.nancon_compat import main as nancon_reference_main
from hydromodpy.display.catchment_report.paths import (
    NANCON_REPORT_CONFIG,
    NANCON_REPORT_INPUTS,
)
from hydromodpy.display.catchment_report.pipeline import run_catchment_report_pipeline
from hydromodpy.display.catchment_report.presets import (
    GENERIC_REPORT_PRESET,
    NANCON_REPORT_PRESET,
    CatchmentReportPreset,
)

__all__ = [
    "CatchmentReportConfig",
    "CatchmentReportInputs",
    "CatchmentReportPreset",
    "GENERIC_REPORT_PRESET",
    "NANCON_REPORT_CONFIG",
    "NANCON_REPORT_INPUTS",
    "NANCON_REPORT_PRESET",
    "build_context_from_report_config",
    "build_catchment_report",
    "nancon_reference_main",
    "run_catchment_report_pipeline",
]
