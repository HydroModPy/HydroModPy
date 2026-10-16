"""Unit tests for static comparison-report helpers."""

from __future__ import annotations

import os
from pathlib import Path

from hydromodpy.reporting.comparison.figures import (
    categorize_figures,
    configuration_figures,
    include_in_comparison_report,
)
from hydromodpy.reporting.comparison.html_utils import (
    link_relative,
    relative,
    render_links,
    render_table,
    safe,
    short,
)


def test_html_helpers_escape_tables_and_empty_state() -> None:
    html = render_table(
        [
            {"name": "<script>x</script>", "value": "a & b"},
            {"name": None, "value": "safe"},
        ],
        [("name", "<Name>"), ("value", "Value")],
        empty="nothing <left>",
    )

    assert "<script>x</script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "a &amp; b" in html
    assert "&lt;Name&gt;" in html
    assert safe(None) == ""
    assert short("abcdef", limit=4) == "abc..."
    assert render_table([], [("name", "Name")], empty="nothing <left>") == (
        '<p class="muted">nothing &lt;left&gt;</p>'
    )


def test_html_links_are_relative_posix_and_skip_missing_files(tmp_path) -> None:
    root = tmp_path / "comparison"
    web_dir = root / "web"
    metrics = root / "comparison_metrics.csv"
    missing = root / "missing.csv"
    web_dir.mkdir(parents=True)
    metrics.write_text("metric,value\nnse,0.8\n", encoding="utf-8")

    assert relative(root, metrics) == "comparison_metrics.csv"
    assert link_relative(web_dir, metrics) == "../comparison_metrics.csv"

    html = render_links(root=root, web_dir=web_dir, links=[metrics, missing])

    assert '../comparison_metrics.csv"' in html
    assert "comparison_metrics.csv" in html
    assert "missing.csv" not in html


def test_categorize_figures_filters_and_orders_report_figures(tmp_path) -> None:
    figures = [
        {"path": str(tmp_path / "native_solver_detail.png"), "kind": "native"},
        {
            "path": str(tmp_path / "head_b__timeseries.png"),
            "kind": "timeseries",
            "observable": "head_domain_high_series",
        },
        {"path": str(tmp_path / "case_configuration.png"), "kind": "setup"},
        {"path": str(tmp_path / "storage_comparison_dashboard.png"), "kind": "dashboard"},
        {
            "path": str(tmp_path / "head_map.png"),
            "kind": "fine_raster_map_comparison",
            "observable": "head_map_wet_year1",
        },
    ]

    categories = categorize_figures(figures)

    assert [category.category_id for category in categories] == [
        "configuration",
        "heads",
        "water_balance",
    ]
    assert [Path(item["path"]).name for item in categories[1].figures] == [
        "head_b__timeseries.png",
        "head_map.png",
    ]
    assert [Path(item["path"]).name for item in configuration_figures(figures)] == [
        "case_configuration.png"
    ]
    assert include_in_comparison_report({"path": "native_solver_detail.png"}) is False
