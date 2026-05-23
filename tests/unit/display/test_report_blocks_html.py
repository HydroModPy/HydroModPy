from __future__ import annotations

from pathlib import Path

from hydromodpy.display.report_blocks import (
    ReportBlock,
    ReportFigure,
    ReportMetric,
    ReportTable,
    write_report_page,
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
                title="Localisation",
                metrics=(ReportMetric("Surface", "12.3", "km2"),),
                figures=(
                    ReportFigure("map", "Carte", figure_path),
                    ReportFigure("missing", "Figure manquante", tmp_path / "missing.png"),
                ),
                tables=(
                    ReportTable(
                        "data",
                        "Donnees",
                        columns=(("name", "Name"),),
                        rows=({"name": "hydrography"},),
                    ),
                ),
            )
        ],
    )

    html = output_path.read_text(encoding="utf-8")
    assert result == output_path
    assert "Localisation" in html
    assert "../figures/map.png" in html
    assert "Figure manquante" not in html
    assert "hydrography" in html
