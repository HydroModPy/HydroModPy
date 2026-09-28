"""An overview run ends on the page to open and the figures folder."""

from __future__ import annotations

import pytest

from hydromodpy.cli.commands import run as run_command


@pytest.mark.fast
def test_overview_recap_names_the_page_and_the_figures(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    figures = tmp_path / "share" / "figures" / "overview"
    summary = {
        "mode": "data_overview",
        "name": "Nançon",
        "catchment_area_km2": 64.6325,
        "report_paths": [str(figures / "map_dem.png"), str(figures / "stats_card.png")],
        "web_report": str(tmp_path / "share" / "web" / "index.html"),
    }

    run_command._print_overview_recap(summary)

    assert capsys.readouterr().err.splitlines() == [
        "Overview of Nançon ready (64.6 km²)",
        "  Report:  share/web/index.html",
        "  Figures: share/figures/overview/ (2)",
    ]
