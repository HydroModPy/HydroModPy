"""Reusable static report block primitives."""

from __future__ import annotations

from hydromodpy.display.report_blocks.html import (
    render_report_page,
    render_report_page_with_block_variants,
    write_report_page,
    write_report_page_with_block_variants,
)
from hydromodpy.display.report_blocks.model import (
    DetailLevel,
    ReportBlock,
    ReportFigure,
    ReportLink,
    ReportMetric,
    ReportTable,
    key_value_table,
)

__all__ = [
    "DetailLevel",
    "ReportBlock",
    "ReportFigure",
    "ReportLink",
    "ReportMetric",
    "ReportTable",
    "key_value_table",
    "render_report_page",
    "render_report_page_with_block_variants",
    "write_report_page",
    "write_report_page_with_block_variants",
]
