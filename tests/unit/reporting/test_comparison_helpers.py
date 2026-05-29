"""Unit tests for static comparison-report helpers."""

from __future__ import annotations

import os
from pathlib import Path

from hydromodpy.reporting.comparison.compact_network.io import (
    SimulationMeta,
    SimulationRecord,
    resolve_recorded_path,
)
from hydromodpy.reporting.comparison.compact_network.network import gmsh_physical_lines
from hydromodpy.reporting.comparison.compact_network.sections import (
    configuration_cell,
    figure_preview,
    metric_bar,
    metric_grid,
    solver_summary,
)
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


def test_resolve_recorded_path_normalizes_windows_and_relative_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    windows_path = resolve_recorded_path(r"C:\tmp\run_a")
    relative_path = resolve_recorded_path("outputs/run_b")

    if os.name == "nt":
        assert windows_path == Path(r"C:\tmp\run_a").resolve()
    else:
        assert windows_path.as_posix() == "/mnt/c/tmp/run_a"
    assert relative_path == (tmp_path / "outputs" / "run_b").resolve()


def test_gmsh_physical_lines_extracts_only_named_line_elements(tmp_path) -> None:
    mesh = tmp_path / "mesh_2d.msh"
    mesh.write_text(
        "\n".join(
            [
                "$MeshFormat",
                "2.2 0 8",
                "$EndMeshFormat",
                "$PhysicalNames",
                "2",
                '1 7 "river::trace"',
                '1 8 "other"',
                "$EndPhysicalNames",
                "$Nodes",
                "3",
                "1 0.0 0.0 0.0",
                "2 1.0 0.0 0.0",
                "3 2.0 0.5 0.0",
                "$EndNodes",
                "$Elements",
                "2",
                "1 1 2 7 0 1 2",
                "2 1 2 8 0 2 3",
                "$EndElements",
            ]
        ),
        encoding="utf-8",
    )

    lines = gmsh_physical_lines(mesh, physical_name="river::trace")
    missing = gmsh_physical_lines(mesh, physical_name="missing")

    assert lines == [[(0.0, 0.0), (1.0, 0.0)]]
    assert missing == []


def test_compact_network_sections_escape_labels_and_render_missing_figures(tmp_path) -> None:
    page = tmp_path / "web" / "compact.html"
    figure_root = tmp_path / "field_figures"
    figure = figure_root / "sim-a" / "release_flux_log_intensity.png"
    figure.parent.mkdir(parents=True)
    figure.write_bytes(b"png")
    record = SimulationRecord(
        meta=SimulationMeta(
            simulation_id="sim-a",
            label="<MF6 & ref>",
            group="regular",
            mesh_summary="regular_grid",
        ),
        solver="modflow6",
        release_distance={"catchment_cell_count": "1234"},
    )

    html = figure_preview(page, figure_root, record, "release_flux", "<Release & flux>")
    missing = figure_preview(page, figure_root, record, "missing", "Missing")
    config = configuration_cell(record)

    assert "field_figures/sim-a/release_flux_log_intensity.png" in html
    assert "data-lightbox-src" in html
    assert "&lt;MF6 &amp; ref&gt; - &lt;Release &amp; flux&gt;" in html
    assert missing == '<div class="figure-missing">figure non disponible</div>'
    assert "&lt;MF6 &amp; ref&gt;" in config
    assert "regular grid" in config
    assert "1 234 cellules" in config
    assert solver_summary(record) == "MODFLOW 6"


def test_compact_network_metric_bars_clamp_and_format_values() -> None:
    row = {
        "sim_to_network_distance_mean_m": "1234",
        "network_to_sim_distance_mean_m": "9",
        "planar_distance_ratio": "1.234",
        "bidirectional_distance_mean_m": "200",
    }

    assert metric_bar({"bidirectional_distance_mean_m": "1"}, max_distance=100.0) == (
        '<div class="bar" style="width:4.0%"></div>'
    )
    assert metric_bar({"bidirectional_distance_mean_m": "200"}, max_distance=100.0) == (
        '<div class="bar" style="width:100.0%"></div>'
    )
    assert metric_bar({"bidirectional_distance_mean_m": "bad"}, max_distance=100.0) == (
        '<div class="bar" style="width:0.0%"></div>'
    )

    html = metric_grid(row, max_distance=100.0)
    assert "1 234 m" in html
    assert "1.23" in html
    assert "width:100.0%" in html
