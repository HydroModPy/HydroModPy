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
                title="Localisation",
                metrics=(ReportMetric("Surface", "12.3", "km2"),),
                figures=(
                    ReportFigure("map", "Carte", figure_path, embed=True),
                    ReportFigure("missing", "Figure manquante", tmp_path / "missing.png"),
                    ReportFigure(
                        "optional_missing",
                        "Figure optionnelle manquante",
                        tmp_path / "optional.png",
                        required=False,
                    ),
                ),
                tables=(
                    ReportTable(
                        "data",
                        "Donnees",
                        columns=(("name", "Name"),),
                        rows=({"name": "hydrography"},),
                    ),
                    key_value_table(
                        "metadata",
                        "Metadonnees",
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
    assert "Partiel" in html
    assert "Localisation" in html
    assert "../figures/map.png" in html
    assert 'src="data:image/png;base64,' in html
    assert "Figure requise manquante" in html
    assert "Figure manquante" in html
    assert "Figure optionnelle manquante" not in html
    assert "hydrography" in html
    assert "Metadonnees" in html
    assert "Source" in html
    assert "figure" in html


def test_write_report_page_with_block_variants_renders_per_block_controls(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "web" / "by_block" / "index.html"
    compact = ReportBlock(
        block_id="flow_context",
        title="Flux",
        level="compact",
        metrics=(ReportMetric("Debit observe", "1.2", "m3/s"),),
    )
    standard = ReportBlock(
        block_id="flow_context",
        title="Flux",
        level="standard",
        metrics=(
            ReportMetric("Debit observe", "1.2", "m3/s"),
            ReportMetric("Debit simule", "1.1", "m3/s"),
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
    assert "Debit observe" in html
    assert "Debit simule" in html
