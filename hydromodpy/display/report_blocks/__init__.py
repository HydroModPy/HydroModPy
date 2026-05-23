"""Reusable static report block primitives."""

from __future__ import annotations

from hydromodpy.display.report_blocks.html import render_report_page, write_report_page
from hydromodpy.display.report_blocks.model import (
    DetailLevel,
    ReportBlock,
    ReportFigure,
    ReportMetric,
    ReportTable,
)

__all__ = [
    "DetailLevel",
    "ReportBlock",
    "ReportFigure",
    "ReportMetric",
    "ReportTable",
    "render_report_page",
    "write_report_page",
]
