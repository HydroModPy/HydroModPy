from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from hydromodpy.core.contracts.overview import DataOverviewState
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.display.overview.web import (
    build_overview_blocks,
    write_overview_review_web_reports,
    write_overview_web_report,
)


def test_overview_web_report_uses_canonical_blocks(tmp_path: Path) -> None:
    figure = tmp_path / "figures" / "overview" / "map_dem_context.png"
    figure.parent.mkdir(parents=True)
    figure.write_bytes(b"fake-png")

    state = _overview_state(tmp_path)
    output = write_overview_web_report(state, figure_paths=[figure])

    html = output.read_text(encoding="utf-8")
    assert output == tmp_path / "web" / "index.html"
    assert "Localisation" in html
    assert "Inventaire des donnees" in html
    assert "Recharge et pompages" in html
    assert "map_dem_context.png" in html
    assert "report-level" not in html
    assert "workflow_header" not in html
    assert "Maillage" not in html
    assert "Solveur" not in html
    assert "365.25 mm/year" in html
    assert "8640 m3/day" in html


def test_overview_blocks_skip_absent_sections(tmp_path: Path) -> None:
    blocks = build_overview_blocks(_overview_state(tmp_path), figure_paths=[])
    by_id = {block.block_id: block for block in blocks}

    assert "mesh_context" not in by_id
    assert "solver_context" not in by_id
    assert "observation_inventory" not in by_id
    assert "hydrographic_network" not in by_id
    assert by_id["forcing_context"].level == "standard"


def test_overview_has_explicit_hydrographic_network_block(tmp_path: Path) -> None:
    figure = tmp_path / "figures" / "overview" / "map_hydrography_data.png"
    figure.parent.mkdir(parents=True)
    figure.write_bytes(b"fake-png")
    state = _overview_state(tmp_path)
    state.loaded_data.hydrography = LoadResult(fields=[SimpleNamespace(metadata={})])
    state.cfg.data.types = ["hydrography", "recharge"]
    state.cfg.data.hydrography = SimpleNamespace(
        date_start="",
        date_end="",
        sources=[SimpleNamespace(source="bdtopage", path="hydro.gpkg")],
    )

    blocks = build_overview_blocks(state, figure_paths=[figure])
    by_id = {block.block_id: block for block in blocks}

    assert by_id["hydrographic_network"].title == "Reseau hydrographique"
    assert by_id["hydrographic_network"].figures[0].figure_id == "map_hydrography_data"


def test_overview_review_pages_write_three_levels(tmp_path: Path) -> None:
    state = _overview_state(tmp_path)
    paths = write_overview_review_web_reports(state, figure_paths=[])

    assert paths == [
        tmp_path / "web_review" / "compact" / "index.html",
        tmp_path / "web_review" / "standard" / "index.html",
        tmp_path / "web_review" / "audit" / "index.html",
    ]
    for level, path in zip(("compact", "standard", "audit"), paths, strict=True):
        html = path.read_text(encoding="utf-8")
        assert f"niveau {level}" in html
        assert "report-level" in html


def _overview_state(tmp_path: Path) -> DataOverviewState:
    recharge_record = PointRecord(
        station_id="synthetic",
        variable="recharge",
        source="synthetic",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame(
            {
                "datetime": pd.date_range("2020-01-01", periods=2, freq="D"),
                "value": [1.0, 1.0],
            }
        ),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 2),
    )
    loaded_data = SimpleNamespace(
        dem=None,
        geology=None,
        hydrography=None,
        hydrometry=None,
        piezometry=None,
        intermittency=None,
        water_quality=None,
        recharge=LoadResult(points=[recharge_record]),
    )
    cfg = SimpleNamespace(
        overview=SimpleNamespace(
            name="Test basin",
            date_start="2020-01-01",
            date_end="2020-01-02",
        ),
        geographic=SimpleNamespace(catch_def="from_outlet_coord", dem_correc_type="breach"),
        data=SimpleNamespace(
            types=["recharge"],
            recharge=SimpleNamespace(
                date_start="2020-01-01",
                date_end="2020-01-02",
                sources=[SimpleNamespace(source="synthetic", path="")],
            ),
        ),
        flow=SimpleNamespace(
            sinks_sources=SimpleNamespace(
                wells={
                    "well_a": SimpleNamespace(
                        location=SimpleNamespace(kind="absolute_xy", x=1.0, y=2.0),
                        flux=-0.1,
                        units="m3/s",
                    )
                }
            )
        ),
    )
    workspace = SimpleNamespace(
        project_root=tmp_path,
        paths=SimpleNamespace(figures_folder=tmp_path / "figures"),
    )
    domain_geographic = SimpleNamespace(
        catchment_area_km2=12.3,
        x_outlet=1.0,
        y_outlet=2.0,
        crs="EPSG:2154",
    )
    return DataOverviewState(
        cfg=cfg,
        workspace=workspace,
        domain_geographic=domain_geographic,
        loaded_data=loaded_data,
    )
