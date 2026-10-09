from __future__ import annotations

from pathlib import Path

from hydromodpy.display.report_blocks import (
    ReportBlock,
    ReportFigure,
    ReportLink,
    ReportMetric,
    ReportTable,
    key_value_table,
    write_report_page,
    write_report_page_with_block_variants,
)


def test_write_report_page_renders_metrics_tables_and_figures(tmp_path: Path) -> None:
    figure_path = tmp_path / "figures" / "map.png"
    figure_path.parent.mkdir()
    figure_path.write_bytes(b"fake-png")

    output_path = tmp_path / "web" / "index.html"
    result = write_report_page(
        output_path=output_path,
        title="Block report",
        blocks=[
            ReportBlock(
                block_id="spatial_context",
                title="Location",
                metrics=(ReportMetric("Area", "12.3", "km2"),),
                figures=(
                    ReportFigure("map", "Map", figure_path, embed=True),
                    ReportFigure("missing", "Missing figure", tmp_path / "missing.png"),
                    ReportFigure(
                        "optional_missing",
                        "Missing optional figure",
                        tmp_path / "optional.png",
                        required=False,
                    ),
                ),
                tables=(
                    ReportTable(
                        "data",
                        "Data",
                        columns=(("name", "Name"),),
                        rows=({"name": "hydrography"},),
                    ),
                    key_value_table(
                        "metadata",
                        "Metadata",
                        (("Mode", "audit"),),
                    ),
                ),
                links=(ReportLink("Source", figure_path, "figure"),),
                status="partial",
            )
        ],
    )

    html = output_path.read_text(encoding="utf-8")
    assert result == output_path
    assert 'id="spatial-context"' in html
    assert "Partial" in html
    assert "Location" in html
    assert "../figures/map.png" in html
    assert 'src="data:image/png;base64,' in html
    assert "Required figure missing" in html
    assert "Missing figure" in html
    assert "Missing optional figure" not in html
    assert "hydrography" in html
    assert "Metadata" in html
    assert "Source" in html
    assert "figure" in html
    assert all(line == line.rstrip() for line in html.splitlines())


def test_write_report_page_with_block_variants_renders_per_block_controls(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "web" / "by_block" / "index.html"
    compact = ReportBlock(
        block_id="flow_context",
        title="Flux",
        level="compact",
        metrics=(ReportMetric("Observed discharge", "1.2", "m3/s"),),
    )
    standard = ReportBlock(
        block_id="flow_context",
        title="Flux",
        level="standard",
        metrics=(
            ReportMetric("Observed discharge", "1.2", "m3/s"),
            ReportMetric("Simulated discharge", "1.1", "m3/s"),
        ),
    )

    write_report_page_with_block_variants(
        output_path=output_path,
        title="Block levels",
        block_variants={"flow_context": {"compact": compact, "standard": standard}},
        default_level="compact",
    )

    html = output_path.read_text(encoding="utf-8")
    assert 'data-block-group="flow-context"' in html
    assert 'data-target-level="compact"' in html
    assert 'data-target-level="standard"' in html
    assert 'id="flow-context-compact"' in html
    assert 'id="flow-context-standard"' in html
    assert "hydromodpy:block-level:" in html
    assert "Observed discharge" in html
    assert "Simulated discharge" in html
    assert all(line == line.rstrip() for line in html.splitlines())
