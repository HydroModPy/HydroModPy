"""Report pages built from a fake run: figures, metrics and tables of each page.

The run is two gauged stations over three monthly steps (discharge in m3/s). The
OLD_ sets list what the earlier research and overview pages showed, so a page
that loses one of them fails.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.display import runs as display_runs
from hydromodpy.display.figure_table import FIGURES
from hydromodpy.display.overview.report import PANEL_FILES, REGIONAL_PANEL_FILE
from hydromodpy.display.report import pages
from hydromodpy.display.report.engine import Block, Metric, Picture, Prose, Table
from hydromodpy.display.report.presets import PRESETS, SHEET_FIGURES, ReportTexts
from hydromodpy.results.errors import SeveralCasesError
from hydromodpy.results.metric_rule import MetricScore
from hydromodpy.schema.phrases import keys, phrase

TITLES = {key: phrase("report", key, "en") for key in keys("report")}
TEXTS = ReportTexts(
    method="Run sentence.\n\nLabel sentence. Budget sentence.",
    label="Label sentence.",
    titles=TITLES,
)

OLD_OVERVIEW_FIGURES = frozenset(
    {
        "map_dem",
        "map_regional_context",
        "map_hydrography",
        "station_inventory",
        "timeseries_discharge",
        "timeseries_piezometry",
        "timeseries_intermittency",
        "timeseries_water_quality",
    }
)
OLD_OVERVIEW_METRICS = frozenset(
    {
        "Workflow",
        "Catchment",
        "Period",
        "Workspace",
        "Catchment area",
        "CRS",
        "Catchment definition",
        "Objects",
        "Sources",
        "Hydrometry",
        "Piezometry",
        "Intermittency",
        "Water quality",
        "Mean recharge",
        "Pumping",
        "Wells",
    }
)
OLD_OVERVIEW_TABLES = frozenset(
    {
        "families",
        "hydrography_sources",
        "stations",
        "recharge_sources",
        "wells",
        "artifact_table",
    }
)


@pytest.fixture(autouse=True)
def no_tables(monkeypatch):
    """A fake run stores no table."""
    monkeypatch.setattr(pages, "read_run_table", lambda run, name: pd.DataFrame())


def _fake_run(
    tmp_path: Path, *, stations=("S1", "S2"), licenses=("CC-BY", None)
) -> SimpleNamespace:
    run_dir = tmp_path / "runs" / "r1"
    (run_dir / "figures").mkdir(parents=True)
    idx = pd.date_range("2000-01-31", periods=3, freq="ME")

    def timeseries(variable, *, station=None):
        if station not in stations:
            raise KeyError(station)
        return pd.Series([1.0, 2.0, 3.0], index=idx, name=station)

    def observed(variable, *, station=None):
        if station not in stations:
            raise ValueError(station)
        return pd.DataFrame({"station_id": station, "datetime": idx, "value": [1.5, 2.5, 3.5]})

    metrics = pd.DataFrame(
        [
            {
                "station": s,
                "variable": "discharge",
                "metric": m,
                "window_name": "metrics",
                "value": v,
                "n_samples": 36.0,
            }
            for s, vals in zip(stations, ((0.8, 0.7), (0.6, 0.5)), strict=False)
            for m, v in zip(("nse", "kge"), vals, strict=True)
        ]
    )
    return SimpleNamespace(
        dir=run_dir,
        name="r1",
        n_cells=100,
        n_timesteps=3,
        record=SimpleNamespace(
            site=SimpleNamespace(
                label="Selune",
                name="selune",
                gauge="S1",
                crs="EPSG:2154",
                x_outlet=1.0,
                y_outlet=2.0,
            ),
            period=SimpleNamespace(
                start=datetime(2000, 1, 1), end=datetime(2000, 3, 31), time_unit="month"
            ),
            run=SimpleNamespace(duration_s=12.5),
            score=MetricScore(
                metric="nse",
                value=0.65,
                station="S2",
                variable="discharge",
                window_name="metrics",
                window_start=None,
                window_end=None,
                n_samples=24,
                metric_rule_version="2",
            ),
        ),
        config_snapshot={
            "data": {"recharge": {"sources": [{"station_ids": ["R1"]}]}},
            "geographic": {"river_network": {"threshold_area_km2": 0.5}},
        },
        geographic=_no_geographic,
        parameters=pd.DataFrame(
            {"value": [1e-5, 0.1, 1e-4], "unit": ["m/s", "-", "1/m"]}, index=["K", "Sy", "Ss"]
        ),
        has_table=lambda name: True,
        timeseries=timeseries,
        observed=observed,
        metrics=metrics,
        exports=[],
        inputs=[
            SimpleNamespace(variable=v, provider="hubeau", path=f"in/{v}", license=lic)
            for v, lic in zip(("recharge", "discharge"), licenses, strict=True)
        ],
    )


def _no_geographic(name):
    raise KeyError(name)


def _items(blocks: list[Block], kind: type) -> list:
    return [i for b in blocks for _, i in b.items if isinstance(i, kind)]


def _figures_of(blocks: list[Block]) -> list[Picture]:
    return _items(blocks, Picture)


def bare_overview(directory: Path) -> SimpleNamespace:
    return SimpleNamespace(
        dir=directory,
        name="ov",
        record=SimpleNamespace(site=SimpleNamespace(label="Selune", crs="EPSG:2154")),
        config_snapshot={},
        figures=[],
        inputs=[],
    )


def _metric(blocks: list[Block], label: str) -> Metric:
    return next(m for m in _items(blocks, Metric) if m.label == label)


def test_preset_names_are_registered():
    research = PRESETS["research"]
    named = [n for names in research.figures.values() for n in names]
    assert [n for n in (*named, *SHEET_FIGURES) if n not in FIGURES] == []
    panels = {*PANEL_FILES.values(), REGIONAL_PANEL_FILE}
    assert [p for p in research.panels if f"{p}.png" not in panels] == []


def test_overview_keeps_old_content(tmp_path):
    blocks = pages.overview_blocks(bare_overview(tmp_path / "runs" / "ov"))
    assert OLD_OVERVIEW_FIGURES - {p.id for p in _figures_of(blocks)} == set()
    assert OLD_OVERVIEW_METRICS - {m.label for m in _items(blocks, Metric)} == set()
    assert OLD_OVERVIEW_TABLES - {t.id for t in _items(blocks, Table)} == set()


def test_sealed_config_feeds_metrics(tmp_path):
    blocks = pages.run_blocks(_fake_run(tmp_path), overview=None, texts=TEXTS, station=None)
    assert _metric(blocks, "Forcing origin").value == "custom recharge (R1)"
    assert _metric(blocks, "DEM extraction threshold").value == "0.5"


def test_geology_rows(tmp_path):
    import geopandas as gpd
    from shapely.geometry import box

    run = _fake_run(tmp_path)
    geology = tmp_path / "geology.gpkg"
    gpd.GeoDataFrame(
        {"CODE_LEG": ["2", "10"], "NOTATION": ["b", "a"]},
        geometry=[box(0, 0, 1000, 1000), box(1000, 0, 3000, 1000)],
        crs="EPSG:2154",
    ).to_file(geology)
    run.inputs.append(
        SimpleNamespace(variable="geology", provider="brgm", path=str(geology), license=None)
    )
    rows = pages._geology_rows(run, None)
    assert [(r["code"], r["area_km2"]) for r in rows] == [("2", "1.00"), ("10", "2.00")]


def test_site_metric_names_gauge(tmp_path):
    blocks = pages.run_blocks(_fake_run(tmp_path), overview=None, texts=TEXTS, station=None)
    assert _metric(blocks, "Site").value == "Selune (S1)"


def test_unknown_station_keeps_page(tmp_path):
    blocks = pages.run_blocks(_fake_run(tmp_path), overview=None, texts=TEXTS, station="nope")
    assert _metric(blocks, "Observed discharge points").value == 0


def test_sheet_label_once(tmp_path):
    blocks = pages.sheet_blocks(_fake_run(tmp_path), texts=TEXTS, station=None)
    text = " ".join(p for prose in _items(blocks, Prose) for p in prose.paragraphs)
    assert text.count("Label sentence.") == 1


def test_sheet_headline_score(tmp_path):
    blocks = pages.sheet_blocks(_fake_run(tmp_path), texts=TEXTS, station="S1")
    scores = next(t for t in _items(blocks, Table) if t.id == "scores")
    assert scores.rows == (
        {
            "station": "S2",
            "variable": "discharge",
            "metric": "nse",
            "window": "metrics",
            "value": "0.65",
            "samples": 24,
        },
    )


def test_undetermined_license():
    assert not hasattr(pages, "UNDETERMINED_LICENCE")
    assert pages.UNDETERMINED_LICENSE == "LicenseRef-undetermined"


def test_overview_reads_inventory(tmp_path, monkeypatch):
    inventory = pd.DataFrame(
        [
            {
                "row_kind": "family",
                "family": "hydrometry",
                "source": "hubeau",
                "name": "",
                "records": 9,
            },
            {
                "row_kind": "station",
                "family": "hydrometry",
                "source": "hubeau",
                "name": "S1",
                "records": 9,
            },
            {"row_kind": "well", "family": "pumping", "source": "file", "name": "W1", "records": 1},
        ]
    )
    monkeypatch.setattr(pages, "read_run_table", lambda run, name: inventory)
    blocks = pages.overview_blocks(bare_overview(tmp_path / "ov"))
    tables = {t.id: t for t in _items(blocks, Table)}
    assert [r["family"] for r in tables["families"].rows] == ["hydrometry"]
    assert [r["name"] for r in tables["stations"].rows] == ["S1"]
    assert [r["name"] for r in tables["wells"].rows] == ["W1"]
    assert _metric(blocks, "Stations").value == 1
    assert _metric(blocks, "Hydrometry").value == 1
    assert _metric(blocks, "Wells").value == 1


def test_session_trial_trace_cut():
    trials = pd.DataFrame(
        {
            "trial": range(1, 31),
            "cost": [float(i) for i in range(30)],
            "status": "completed",
            "parameters": [{"K": {"value": 1e-5 * i}} for i in range(30)],
        }
    )
    session = SimpleNamespace(trials=trials, phases=[])
    blocks = pages.session_blocks(session, summary_rows=[("method", "cmaes")], figures=[])
    by_id = {b.id: b for b in blocks}
    assert by_id["trials"].lead == "10 more rows not shown."
    assert by_id["figures"].lead == "No figures rendered."
    short = next(i for _, i in by_id["trials"].items if isinstance(i, Table) and i.id == "trials")
    assert len(short.rows) == 20
    assert '"K": 1e-05' in short.rows[1]["parameters"] or '"K"' in short.rows[1]["parameters"]


class _SeveralCases:
    trials = pd.DataFrame(columns=["trial", "cost", "status", "parameters"])
    phases: list = []

    @property
    def best(self):
        raise SeveralCasesError("session s holds one run per case (a, b): read best_by_case.")


def test_several_cases_session(tmp_path):
    cases = [
        {"case": "a", "site": "A", "best_run": "a.v1", "note": ""},
        {"case": "b", "site": "B", "best_run": "", "note": "best run not opened: broken"},
    ]
    figure = tmp_path / "a_hydrograph_sim_obs.png"
    figure.write_bytes(b"x")
    blocks = pages.session_blocks(
        _SeveralCases(), summary_rows=[], figures=[], cases=cases, best_figures=[figure]
    )
    table = next(t for t in _items(blocks, Table) if t.id == "cases")
    assert [r["case"] for r in table.rows] == ["a", "b"]
    assert table.rows[1]["note"] == "best run not opened: broken"
    assert [p.id for p in _figures_of(blocks)] == ["best_a_hydrograph_sim_obs"]


@pytest.fixture
def draw_spy(monkeypatch):
    calls = []

    def render(run, display, *, output_dir, figure_names):
        calls.append((display, output_dir, figure_names))
        return SimpleNamespace(rendered=tuple(figure_names))

    monkeypatch.setattr(display_runs, "render_figures_for_run", render)
    monkeypatch.setattr(display_runs, "log_render_summary", lambda report, destination: None)
    return calls


def test_draw_only_missing(tmp_path, draw_spy):
    run = SimpleNamespace(dir=tmp_path, config_snapshot=None)
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "seepage_map.png").write_bytes(b"x")
    drawn = pages.draw_named_figures(run, ["seepage_map", "water_budget", "water_budget"])
    assert drawn == ("water_budget",)
    display, output_dir, names = draw_spy[0]
    assert names == ["water_budget"]
    assert output_dir == tmp_path / "figures"
    assert display.enabled
    assert display.save
    assert display.on_error == "warn"


def test_draw_nothing_when_all_exist(tmp_path, draw_spy):
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "seepage_map.png").write_bytes(b"x")
    run = SimpleNamespace(dir=tmp_path, config_snapshot=None)
    assert pages.draw_named_figures(run, ["seepage_map"]) == ()
    assert draw_spy == []


def test_sealed_display_keeps_chosen():
    run = SimpleNamespace(config_snapshot={"display": {"dpi": 220}})
    display = pages._sealed_display(run, ["seepage_map"])
    assert display.dpi == 220
    assert list(display.figures) == ["seepage_map"]
    assert display.on_error == "warn"


def test_sealed_display_falls_back():
    run = SimpleNamespace(config_snapshot={"display": {"dpi": "not a number"}})
    display = pages._sealed_display(run, ["seepage_map"])
    assert list(display.figures) == ["seepage_map"]
