"""The report pages: figures named by the presets, two stations, drawn figures, overview, sheet, session."""

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

OLD_RESEARCH_FIGURES = frozenset(
    {
        # The figures the research report of 6dddbdc21 showed, by the file they read.
        # forcing_window, baseline_discharge_comparison and the simulated hydrograph
        # are hydrograph_sim_obs; observed_discharge_full is timeseries_discharge.
        "stats_card",
        "station_inventory",
        "map_regional_context",
        "map_dem",
        "map_geology",
        "map_hydrography",
        "hydrographic_network_generated",
        "hydrographic_network_comparison",
        "hydrographic_network_reference_missing_only",
        "hydrographic_network_generated_extra_only",
        "simulated_active_network_reference_overlay",
        "seepage_map",
        "timeseries_discharge",
        "climatic_summary",
        "hydrograph_sim_obs",
        "piezometric_map",
        "water_budget",
    }
)
OLD_RESEARCH_METRICS = frozenset(
    {
        # "BD Topage segments" reads "Reference segments", "Solver time" reads
        # "Run time", "Mean simulated discharge of the reference run" reads
        # "Mean simulated discharge", "Sᵧ" reads "Sy".
        "Site",
        "CRS",
        "Outlet X",
        "Outlet Y",
        "Window",
        "Run cells",
        "K",
        "Sy",
        "Ss",
        "Reference segments",
        "DEM extraction threshold",
        "Source figures folder",
        "Forcing origin",
        "Mean observed discharge",
        "Observed discharge points",
        "Simulation",
        "Timesteps",
        "Run time",
        "Mean simulated discharge",
    }
)
OLD_RESEARCH_TABLES = frozenset(
    {"configuration", "parameters", "geology_units", "flux_stats", "scores", "inputs"}
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


def _figures_of(blocks: list[Block]) -> list[Picture]:
    return [i for b in blocks for _, i in b.items if isinstance(i, Picture)]


def _metric(blocks: list[Block], label: str) -> Metric:
    return next(i for b in blocks for _, i in b.items if isinstance(i, Metric) and i.label == label)


def test_named_figures_and_panels_are_registered():
    research = PRESETS["research"]
    named = [n for names in research.figures.values() for n in names]
    assert [n for n in (*named, *SHEET_FIGURES) if n not in FIGURES] == []
    panels = {*PANEL_FILES.values(), REGIONAL_PANEL_FILE}
    assert [p for p in research.panels if f"{p}.png" not in panels] == []


def test_run_blocks_use_every_figure_the_preset_names(tmp_path):
    blocks = pages.run_blocks(_fake_run(tmp_path), overview=None, texts=TEXTS, station=None)
    used = {p.id for p in _figures_of(blocks)}
    named = {n for names in PRESETS["research"].figures.values() for n in names}
    assert named <= used


def test_run_blocks_start_with_the_method(tmp_path):
    blocks = pages.run_blocks(_fake_run(tmp_path), overview=None, texts=TEXTS, station=None)
    first = blocks[0]
    assert first.id == "method"
    prose = next(i for _, i in first.items if isinstance(i, Prose))
    assert prose.paragraphs == ("Run sentence.", "Label sentence. Budget sentence.")


def _items(blocks: list[Block], kind: type) -> list:
    return [i for b in blocks for _, i in b.items if isinstance(i, kind)]


def test_the_research_report_keeps_every_figure_metric_and_table_of_the_old_one(tmp_path):
    blocks = pages.run_blocks(_fake_run(tmp_path), overview=None, texts=TEXTS, station=None)
    figures = {p.id for p in _figures_of(blocks)}
    assert OLD_RESEARCH_FIGURES - figures == set()
    assert OLD_RESEARCH_FIGURES - set(PRESETS["research"].panels) <= {
        n for names in PRESETS["research"].figures.values() for n in names
    }
    assert OLD_RESEARCH_METRICS - {m.label for m in _items(blocks, Metric)} == set()
    assert OLD_RESEARCH_TABLES - {t.id for t in _items(blocks, Table)} == set()


def test_the_overview_page_keeps_every_figure_metric_and_table_of_the_old_one(tmp_path):
    overview = SimpleNamespace(
        dir=tmp_path / "runs" / "ov",
        name="ov",
        record=SimpleNamespace(site=SimpleNamespace(label="Selune", crs="EPSG:2154")),
        config_snapshot={},
        figures=[],
        inputs=[],
    )
    blocks = pages.overview_blocks(overview)
    assert OLD_OVERVIEW_FIGURES - {p.id for p in _figures_of(blocks)} == set()
    assert OLD_OVERVIEW_METRICS - {m.label for m in _items(blocks, Metric)} == set()
    assert OLD_OVERVIEW_TABLES - {t.id for t in _items(blocks, Table)} == set()


def test_the_forcing_origin_and_the_configuration_read_the_sealed_config(tmp_path):
    blocks = pages.run_blocks(_fake_run(tmp_path), overview=None, texts=TEXTS, station=None)
    assert _metric(blocks, "Forcing origin").value == "custom recharge (R1)"
    assert _metric(blocks, "DEM extraction threshold").value == "0.5"


def test_the_geology_table_lists_the_codes_of_the_catchment(tmp_path):
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


@pytest.mark.parametrize(("station", "mean"), [(None, "2"), ("S1", "2"), ("S2", "2")])
def test_series_follow_the_station(tmp_path, station, mean):
    blocks = pages.run_blocks(_fake_run(tmp_path), overview=None, texts=TEXTS, station=station)
    assert _metric(blocks, "Mean simulated discharge").value == mean


def test_gauge_names_the_site(tmp_path):
    blocks = pages.run_blocks(_fake_run(tmp_path), overview=None, texts=TEXTS, station=None)
    assert _metric(blocks, "Site").value == "Selune (S1)"


def test_unknown_station_gives_no_series_but_still_a_page(tmp_path):
    blocks = pages.run_blocks(_fake_run(tmp_path), overview=None, texts=TEXTS, station="nope")
    assert _metric(blocks, "Observed discharge points").value == 0


def test_scores_list_every_station(tmp_path):
    blocks = pages.run_blocks(_fake_run(tmp_path), overview=None, texts=TEXTS, station="S1")
    table = next(i for b in blocks for _, i in b.items if isinstance(i, Table) and i.id == "scores")
    assert {r["station"] for r in table.rows} == {"S1", "S2"}
    assert len(table.rows) == 4
    assert ("window_name", "Window") in table.columns
    assert {r["n_samples"] for r in table.rows} == {"36"}


def test_figures_are_required_and_missing_ones_stay_empty(tmp_path):
    run = _fake_run(tmp_path)
    (run.dir / "figures" / "seepage_map.png").write_bytes(b"x")
    blocks = pages.run_blocks(run, overview=None, texts=TEXTS, station=None)
    by_id = {p.id: p for p in _figures_of(blocks)}
    assert by_id["seepage_map"].ok
    assert not by_id["water_budget"].ok
    assert by_id["water_budget"].required


def test_overview_panels_are_required_only_with_an_overview(tmp_path):
    run = _fake_run(tmp_path)
    without = pages.run_blocks(run, overview=None, texts=TEXTS, station=None)
    assert not any(p.required for p in _figures_of(without) if p.id == "map_dem")
    overview = SimpleNamespace(dir=tmp_path / "runs" / "ov", inputs=[])
    (overview.dir / "figures").mkdir(parents=True)
    (overview.dir / "figures" / "map_dem.png").write_bytes(b"x")
    with_ov = pages.run_blocks(run, overview=overview, texts=TEXTS, station=None)
    dem = next(p for p in _figures_of(with_ov) if p.id == "map_dem")
    assert dem.ok
    assert dem.required


def test_sheet_in_two_languages_with_licence_warning(tmp_path):
    run = _fake_run(tmp_path)
    fr = ReportTexts(
        "Methode.",
        "Etiquette valide.",
        {key: phrase("report", key, "fr") for key in keys("report")},
    )
    for texts, label in ((TEXTS, "Label sentence."), (fr, "Etiquette valide.")):
        blocks = pages.sheet_blocks(run, texts=texts, station=None)
        assert [b.id for b in blocks] == ["label", "method", "figures", "scores", "inputs"]
        prose = next(i for _, i in blocks[0].items if isinstance(i, Prose))
        assert prose.paragraphs == (label,)
        warnings = [i for b in blocks for _, i in b.items if isinstance(i, str)]
        assert warnings == [f"discharge: {texts.titles['licence_unknown']}"]
    assert [p.id for p in _figures_of(blocks)] == list(SHEET_FIGURES)
    assert [p.title for p in _figures_of(blocks)] == [
        phrase("report", f"figure_{n}", "fr") for n in SHEET_FIGURES
    ]
    headings = {h for t in _items(blocks, Table) for _, h in t.columns}
    assert {"Critère", "Fenêtre", "Échantillons", "Fournisseur", "Chemin"} <= headings


def test_sheet_names_its_label_once(tmp_path):
    blocks = pages.sheet_blocks(_fake_run(tmp_path), texts=TEXTS, station=None)
    text = " ".join(p for prose in _items(blocks, Prose) for p in prose.paragraphs)
    assert text.count("Label sentence.") == 1


def test_sheet_headline_is_the_score_of_the_seal(tmp_path):
    blocks = pages.sheet_blocks(_fake_run(tmp_path), texts=TEXTS, station="S1")
    scores = next(
        i for b in blocks for _, i in b.items if isinstance(i, Table) and i.id == "scores"
    )
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


def test_the_undetermined_licence_is_the_one_of_core():
    assert not hasattr(pages, "UNDETERMINED_LICENCE")
    assert pages.UNDETERMINED_LICENSE == "LicenseRef-undetermined"


def test_overview_blocks_read_the_sealed_inventory(tmp_path, monkeypatch):
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
    overview = SimpleNamespace(
        dir=tmp_path / "ov",
        name="ov",
        record=SimpleNamespace(site=SimpleNamespace(label="Selune", crs="EPSG:2154")),
        config_snapshot={},
        figures=[],
        inputs=[],
    )
    blocks = pages.overview_blocks(overview)
    tables = {i.id: i for b in blocks for _, i in b.items if isinstance(i, Table)}
    assert [r["family"] for r in tables["families"].rows] == ["hydrometry"]
    assert [r["name"] for r in tables["stations"].rows] == ["S1"]
    assert [r["name"] for r in tables["wells"].rows] == ["W1"]
    assert _metric(blocks, "Stations").value == 1
    assert _metric(blocks, "Hydrometry").value == 1
    assert _metric(blocks, "Wells").value == 1


def test_session_blocks_cut_the_trial_trace():
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


def test_a_session_of_several_cases_has_its_page_with_a_row_per_case(tmp_path):
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


def test_draw_named_figures_draws_only_the_missing(tmp_path, draw_spy):
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


def test_draw_named_figures_does_nothing_when_all_exist(tmp_path, draw_spy):
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "seepage_map.png").write_bytes(b"x")
    run = SimpleNamespace(dir=tmp_path, config_snapshot=None)
    assert pages.draw_named_figures(run, ["seepage_map"]) == ()
    assert draw_spy == []


def test_sealed_display_keeps_only_values_the_run_chose():
    run = SimpleNamespace(config_snapshot={"display": {"dpi": 220}})
    display = pages._sealed_display(run, ["seepage_map"])
    assert display.dpi == 220
    assert list(display.figures) == ["seepage_map"]
    assert display.on_error == "warn"


def test_sealed_display_falls_back_to_the_defaults():
    run = SimpleNamespace(config_snapshot={"display": {"dpi": "not a number"}})
    display = pages._sealed_display(run, ["seepage_map"])
    assert list(display.figures) == ["seepage_map"]
