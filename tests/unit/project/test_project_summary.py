"""``hmp project collect`` writes ``summary/`` of a project from its runs.

Every run here is a sealed directory written by ``RunRecord.write``, every
failure an ``outcome.json``, and the plan a real ``plan/<hash>/``. The collect
refreshes the index itself, then writes the tables by case and by site, the
map, the cohort figures, the exports of ``[[sites.export]]``, a page, a dated
README and an RO-Crate.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from hydromodpy.core.site.row import SITE_ROW_COLUMNS, SiteRow
from hydromodpy.project import summary as summary_module
from hydromodpy.project.summary import (
    CASE_COLUMNS,
    SummaryError,
    UnreadableManifestError,
    collect_project,
    overrides_text,
    rank_rows,
)
from hydromodpy.results.checks import CalibratedBy
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.plan_store import Plan, PlanCase, write_plan
from hydromodpy.results.record import RunRecord
from hydromodpy.results.run.sealed import MixedWindowsError
from hydromodpy.results.storage.contract import TABLES_DIRNAME
from tests._helpers.sealed_runs import WINDOW, seal_run, write_attempt, write_session_dir

OTHER_WINDOW = DateWindow(start=date(2010, 1, 1), end=date(2014, 12, 31))

PROJECT_TOML = """\
[sites]
table = "sites.csv"

[sites.summary]
metrics = ["nse", "kge"]
parameters = ["K"]
columns = ["checks.budget_pct", "metrics.nse"]
{summary_extra}

{exports}

[publication]
license = "CC-BY-4.0"
creators = ["A. Hydrogeologist"]
"""


def _project(tmp_path: Path, *, summary_extra: str = "", exports: str = "") -> Path:
    root = tmp_path / "bretagne_k"
    root.mkdir()
    (root / "project.toml").write_text(
        PROJECT_TOML.format(summary_extra=summary_extra, exports=exports), encoding="utf-8"
    )
    return root


def _plan(root: Path, case_ids: list[str]) -> None:
    cases = [
        PlanCase(
            case_id=case_id,
            site=case_id.split("-")[0],
            recipe=case_id.split("-")[1],
            config_hash="c0ffee",
            config_path=f"{case_id}.toml",
        )
        for case_id in case_ids
    ]
    plan = Plan(
        plan_hash="a3f9c2e1",
        hydromodpy_version="2.0.0a5",
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
        n_cases=len(cases),
    )
    sites = pa.table({"site": sorted({case.site for case in cases})})
    write_plan(root, plan, sites, cases, {case.case_id: "[flow]\n" for case in cases})


def _seal(
    root: Path,
    site: str,
    recipe: str,
    *,
    nse: float,
    kge: float | None = None,
    k: float = 1e-5,
    calibrated: bool = False,
    window: DateWindow = WINDOW,
    version: int = 1,
    objective: float | None = None,
    overrides: dict | None = None,
    x_outlet: float = 350000.0,
) -> Path:
    """Seal ``runs/<site>-<recipe>[.vN]`` and return its directory."""
    case_id = f"{site}-{recipe}"
    name = case_id if version == 1 else f"{case_id}.v{version}"
    seal_run(
        root,
        name,
        project=root.name,
        site=site,
        recipe=recipe,
        nse=nse,
        window=window,
        parameters={"K": k},
        calibrated_by=(
            CalibratedBy(
                session_id=f"s_{case_id}", phase="steady_k", trial=4, session_status="completed"
            )
            if calibrated
            else None
        ),
    )
    run_dir = root / "runs" / name
    record = RunRecord.read(run_dir)
    metrics = list(record.metrics)
    if kge is not None:
        base = metrics[0]
        metrics.append(base.model_copy(update={"metric": "kge", "value": kge}))
        metrics.append(MetricRow(station="elsewhere", variable="discharge", metric="kge", value=-9))
    update: dict = {
        "metrics": metrics,
        "lineage": record.lineage.model_copy(update={"overrides": overrides or {}}),
        "site": record.site.model_copy(update={"x_outlet": x_outlet}),
    }
    if objective is not None:
        update.update(objective_name="nse_log", objective_value=objective, objective_window=window)
    record.model_copy(update=update).write(run_dir)
    return run_dir


def _timeseries(run_dir: Path, sim_id: str) -> None:
    times = pd.date_range("2016-01-01", periods=3, freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "sim_id": sim_id,
            "station_id": "J0014010",
            "variable": ["discharge"] * 3 + ["discharge_obs"] * 3,
            "timestep": [0, 1, 2] * 2,
            "time": list(times) * 2,
            "value": [1.0, 2.0, 3.0, 1.1, 2.1, 3.1],
            "unit": "m3/s",
        }
    )
    frame.to_parquet(run_dir / TABLES_DIRNAME / "timeseries.parquet")


@pytest.fixture
def campaign(tmp_path: Path) -> Path:
    """Two sites, a base and a calibration recipe each, one failure, one case not run."""
    root = _project(tmp_path)
    _plan(
        root,
        ["J0014010-base", "J0014010-calage", "J0170000-base", "J0170000-calage", "J0200000-base"],
    )
    _seal(root, "J0014010", "base", nse=0.81, kge=0.70, k=2e-5)
    _seal(root, "J0014010", "calage", nse=0.62, kge=0.60, k=6.1e-6, calibrated=True, objective=0.7)
    _seal(root, "J0170000", "calage", nse=0.55, kge=0.50, k=3e-6, calibrated=True, objective=0.6)
    write_attempt(
        root, "runs/J0170000-base", status="failed", case_id="J0170000-base", site="J0170000"
    )
    return root


def test_collect_writes_every_file_of_the_summary(campaign: Path) -> None:
    paths = collect_project(campaign)

    summary = campaign / "summary"
    for name in (
        "by_case.parquet",
        "by_case.csv",
        "by_site.parquet",
        "by_site.csv",
        "by_site.gpkg",
        "figures/index.json",
        "exports/index.json",
        "report/index.html",
        "README.md",
        "ro-crate-metadata.json",
    ):
        assert (summary / name).is_file(), name
    assert paths.by_case == summary / "by_case.parquet"
    assert paths.by_site == summary / "by_site.parquet"
    assert paths.catalog is None
    assert not (summary / "catalog.csv").exists()
    assert paths.readme == summary / "README.md"
    assert paths.rocrate == summary / "ro-crate-metadata.json"
    assert paths.report == summary / "report" / "index.html"


def test_by_case_holds_every_planned_case_with_its_status(campaign: Path) -> None:
    collect_project(campaign)

    by_case = pd.read_parquet(campaign / "summary" / "by_case.parquet").set_index("case_id")
    assert list(by_case.index) == [
        "J0014010-base",
        "J0014010-calage",
        "J0170000-base",
        "J0170000-calage",
        "J0200000-base",
    ]
    assert list(by_case.columns[: len(CASE_COLUMNS) - 1]) == list(CASE_COLUMNS[1:])
    assert by_case.loc["J0014010-base", "status"] == "completed"
    assert by_case.loc["J0170000-base", "status"] == "failed"
    assert by_case.loc["J0170000-base", "error_type"] == "SolverError"
    assert by_case.loc["J0200000-base", "status"] == "planned"
    assert by_case.loc["J0014010-calage", "label"] == "calibrated"
    assert by_case.loc["J0014010-base", "label"] == "exploratory"
    assert by_case.loc["J0014010-base", "K"] == pytest.approx(2e-5)
    assert by_case.loc["J0014010-base", "kge"] == pytest.approx(0.70)
    assert by_case.loc["J0014010-base", "nse_window_start"] == "2016-01-01"
    assert by_case.loc["J0014010-base", "checks.budget_pct"] == pytest.approx(0.8)
    assert by_case.loc["J0014010-base", "metrics.nse"] == pytest.approx(0.81)
    csv_rows = pd.read_csv(campaign / "summary" / "by_case.csv")
    assert len(csv_rows) == 5


def test_by_site_keeps_the_best_calibrated_case(campaign: Path) -> None:
    collect_project(campaign)

    by_site = pd.read_parquet(campaign / "summary" / "by_site.parquet").set_index("site")
    # The base case scores higher but is not calibrated: best = "calibrated" skips it.
    assert by_site.loc["J0014010", "best_case"] == "J0014010-calage"
    assert by_site.loc["J0014010", "K"] == pytest.approx(6.1e-6)
    assert by_site.loc["J0014010", "n_cases"] == 2
    assert by_site.loc["J0014010", "n_completed"] == 2
    assert by_site.loc["J0170000", "best_case"] == "J0170000-calage"
    assert pd.isna(by_site.loc["J0200000", "best_case"])
    assert by_site.loc["J0014010", "area_km2"] == pytest.approx(65.2)
    assert by_site.loc["J0014010", "crs"] == "EPSG:2154"


def test_best_any_takes_the_best_case_whatever_its_label(tmp_path: Path) -> None:
    root = _project(tmp_path, summary_extra='best = "any"')
    _seal(root, "J0014010", "base", nse=0.81)
    _seal(root, "J0014010", "calage", nse=0.62, calibrated=True)

    paths = collect_project(root)

    by_site = pd.read_parquet(root / "summary" / "by_site.parquet").set_index("site")
    assert by_site.loc["J0014010", "best_case"] == "J0014010-base"
    readme = paths.readme.read_text(encoding="utf-8")
    assert 'the best case whatever its label (best = "any")' in readme


def test_the_objective_of_the_session_sits_beside_the_nse(campaign: Path) -> None:
    collect_project(campaign)

    by_site = pd.read_parquet(campaign / "summary" / "by_site.parquet").set_index("site")
    row = by_site.loc["J0014010"]
    assert row["objective_name"] == "nse_log"
    assert row["objective_value"] == pytest.approx(0.7)
    assert row["nse"] == pytest.approx(0.62)
    assert row["nse_window_start"] == "2016-01-01"
    assert row["objective_window_start"] == "2016-01-01"


def test_the_latest_version_of_a_case_is_the_one_collected(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _seal(root, "J0014010", "base", nse=0.40)
    _seal(
        root,
        "J0014010",
        "base",
        nse=0.75,
        version=2,
        overrides={"flow.param.K.field.value": 2e-5},
    )

    collect_project(root)

    by_case = pd.read_parquet(root / "summary" / "by_case.parquet")
    assert len(by_case) == 1
    row = by_case.iloc[0]
    assert row["rel_dir"] == "runs/J0014010-base.v2"
    assert row["version"] == 2
    assert row["nse"] == pytest.approx(0.75)
    assert row["overrides"] == "flow.param.K.field.value=2e-05"


def test_scores_on_two_windows_are_not_ranked_without_the_flag(tmp_path: Path) -> None:
    root = _project(tmp_path, summary_extra='best = "any"')
    _seal(root, "J0014010", "base", nse=0.81)
    _seal(root, "J0170000", "base", nse=0.55, window=OTHER_WINDOW)

    with pytest.raises(MixedWindowsError, match="--mixed-windows") as refused:
        collect_project(root)
    assert "2010-01-01" in str(refused.value)
    assert "J0170000-base" in str(refused.value)
    assert not (root / "summary" / "by_site.parquet").exists()

    collect_project(root, mixed_windows=True)

    by_site = pd.read_parquet(root / "summary" / "by_site.parquet").set_index("site")
    assert by_site.loc["J0170000", "nse_window_start"] == "2010-01-01"
    assert by_site.loc["J0014010", "nse_window_start"] == "2016-01-01"


def test_a_column_no_manifest_has_is_refused_with_its_neighbours(tmp_path: Path) -> None:
    root = _project(tmp_path)
    toml = (root / "project.toml").read_text(encoding="utf-8")
    (root / "project.toml").write_text(
        toml.replace('"metrics.nse"]', '"checks.budget_pc"]'), encoding="utf-8"
    )
    _seal(root, "J0014010", "base", nse=0.81)

    with pytest.raises(SummaryError, match="checks.budget_pc"):
        collect_project(root)


def test_write_sites_writes_the_sites_as_a_site_table(campaign: Path) -> None:
    paths = collect_project(campaign, write_sites=True)

    assert paths.catalog == campaign / "summary" / "catalog.csv"
    with paths.catalog.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == SITE_ROW_COLUMNS
        rows = [SiteRow.from_mapping(record) for record in reader]
    assert [row.site for row in rows] == ["J0014010", "J0170000", "J0200000"]
    assert rows[0].gauge == "J0014010"
    assert rows[0].x_outlet == pytest.approx(350000.0)
    assert rows[0].crs == "EPSG:2154"
    assert rows[2].x_outlet is None


def test_sites_export_speaks_the_words_of_export(tmp_path: Path) -> None:
    exports = """\
[[sites.export]]
table = "by_site"
format = "csv"

[[sites.export]]
table = "by_case"
format = "parquet"

[[sites.export]]
runs = "best"
variables = ["discharge"]
format = "csv"
"""
    root = _project(tmp_path, exports=exports)
    run_dir = _seal(root, "J0014010", "calage", nse=0.62, calibrated=True)
    _timeseries(run_dir, RunRecord.read(run_dir).run.sim_id)

    collect_project(root)

    exports_dir = root / "summary" / "exports"
    assert (exports_dir / "by_site.csv").read_bytes() == (
        root / "summary" / "by_site.csv"
    ).read_bytes()
    assert pd.read_parquet(exports_dir / "by_case.parquet")["case_id"].tolist() == [
        "J0014010-calage"
    ]
    series = pd.read_csv(exports_dir / "best" / "J0014010_discharge.csv")
    assert series["variable"].unique().tolist() == ["discharge"]
    assert series["case_id"].unique().tolist() == ["J0014010-calage"]
    identity = read_identity_from(exports_dir / "best" / "J0014010_discharge.csv")
    assert identity is not None and identity.case_id == "J0014010-calage"
    assert identity.label == "calibrated"
    ledger = Ledger.read(exports_dir)
    assert sorted(entry.file for entry in ledger.entries) == [
        "best/J0014010_discharge.csv",
        "by_case.parquet",
        "by_site.csv",
    ]
    by_file = {entry.file: entry for entry in ledger.entries}
    assert by_file["best/J0014010_discharge.csv"].identity.case_id == "J0014010-calage"
    assert by_file["by_site.csv"].identity is None
    assert by_file["by_site.csv"].options == {"table": "by_site"}


def test_a_format_a_table_cannot_take_is_refused(tmp_path: Path) -> None:
    root = _project(tmp_path, exports='[[sites.export]]\ntable = "by_case"\nformat = "gpkg"\n')
    _seal(root, "J0014010", "base", nse=0.81)

    with pytest.raises(SummaryError, match="gpkg"):
        collect_project(root)
    assert not (root / "summary").exists()


def test_the_cohort_figures_are_drawn_and_recorded(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        summary_extra=('best = "any"\nfigures = ["map", "distribution"]\nvariables = ["K", "nse"]'),
    )
    _seal(root, "J0014010", "base", nse=0.81, k=2e-5)
    _seal(root, "J0170000", "base", nse=0.55, k=3e-6, x_outlet=360000.0)

    paths = collect_project(root)

    names = sorted(path.name for path in paths.figures.glob("*.png"))
    assert names == [
        "distribution_K.png",
        "distribution_nse.png",
        "map_K.png",
        "map_nse.png",
    ]
    ledger = Ledger.read(paths.figures)
    entry = ledger.entry_for("map_K.png")
    assert entry is not None
    assert entry.producer == "display.figures.map"
    assert entry.options == {"variable": "K"}
    page = paths.report.read_text(encoding="utf-8")
    assert "../figures/map_K.png" in page


def test_a_figure_of_a_run_is_refused_in_the_summary(tmp_path: Path) -> None:
    root = _project(tmp_path, summary_extra='figures = ["piezometric_map"]')
    _seal(root, "J0014010", "base", nse=0.81)

    with pytest.raises(SummaryError, match="distribution, map"):
        collect_project(root)
    assert not (root / "summary").exists()


def test_the_readme_is_dated_with_the_versions_and_the_counts(campaign: Path) -> None:
    collect_project(campaign)

    readme = (campaign / "summary" / "README.md").read_text(encoding="utf-8")
    today = datetime.now(UTC).date().isoformat()
    assert f"Collected {today}" in readme
    assert "3 completed of 5 planned cases" in readme
    assert "HydroModPy versions met: 2.0.0a5" in readme
    assert "2016-01-01 to 2020-12-31" in readme
    assert "sha256(by_site.parquet) = " in readme
    assert "the best calibrated case" in readme
    assert "catalog.csv" not in readme
    collect_project(campaign, write_sites=True)
    readme = (campaign / "summary" / "README.md").read_text(encoding="utf-8")
    assert "- `catalog.csv`: the sites as a table" in readme


def test_the_crate_lists_every_file_and_the_runs_it_reads(campaign: Path) -> None:
    collect_project(campaign)

    crate = json.loads((campaign / "summary" / "ro-crate-metadata.json").read_text("utf-8"))
    graph = {node["@id"]: node for node in crate["@graph"]}
    root = graph["./"]
    parts = {part["@id"] for part in root["hasPart"]}
    assert {"by_case.parquet", "by_site.gpkg", "README.md", "report/index.html"} <= parts
    assert {"#runs/J0014010-calage", "#runs/J0170000-calage"} <= {
        ref["@id"] for ref in root["isBasedOn"]
    }
    assert root["license"] == "CC-BY-4.0"
    assert graph["by_case.parquet"]["sha256"]
    text = json.dumps(crate)
    assert str(campaign) not in text


def test_a_second_collect_keeps_the_comparisons(campaign: Path) -> None:
    compare = campaign / "summary" / "report" / "compare" / "a-vs-b"
    compare.mkdir(parents=True)
    (compare / "README.md").write_text("# a vs b\n", encoding="utf-8")

    collect_project(campaign)
    collect_project(campaign)

    assert (compare / "README.md").is_file()
    assert "compare/a-vs-b/README.md" in (
        campaign / "summary" / "report" / "index.html"
    ).read_text(encoding="utf-8")


def test_a_project_without_sites_is_collected_with_the_defaults(tmp_path: Path) -> None:
    root = tmp_path / "nancon"
    root.mkdir()
    (root / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    seal_run(root, "nancon_monthly", project="nancon", site="nancon", nse=0.7)

    paths = collect_project(root)

    by_case = pd.read_parquet(paths.by_case)
    assert by_case["case_id"].tolist() == ["nancon_monthly"]
    assert "kge" not in by_case.columns
    by_site = pd.read_parquet(paths.by_site)
    # Not calibrated: the default best = "calibrated" leaves the site without a best case.
    assert by_site["site"].tolist() == ["nancon"]
    assert pd.isna(by_site.loc[0, "best_case"])


def test_rank_rows_follows_the_direction_of_the_metric() -> None:
    frame = pd.DataFrame(
        {
            "case_id": ["a-x", "b-x", "a-y"],
            "site": ["a", "b", "a"],
            "rmse": [0.3, 0.1, 0.2],
            "nse_window_start": ["2016-01-01"] * 3,
        }
    )

    assert rank_rows(frame, "rmse")["case_id"].tolist() == ["b-x", "a-y", "a-x"]
    assert rank_rows(frame, "rmse", by="site")["case_id"].tolist() == ["a-y", "b-x"]


def test_overrides_read_as_dotted_paths_and_values() -> None:
    assert overrides_text({"b.k": 2e-5, "a.n": 3}) == "a.n=3, b.k=2e-05"
    assert overrides_text({}) == ""


def test_a_case_outside_the_plan_is_listed_but_not_counted(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _plan(root, ["J0014010-base", "J0170000-base"])
    _seal(root, "J0014010", "base", nse=0.81)
    _seal(root, "J0014010", "old", nse=0.70)

    collect_project(root)

    by_case = pd.read_parquet(root / "summary" / "by_case.parquet")
    assert by_case["case_id"].tolist() == ["J0014010-base", "J0170000-base", "J0014010-old"]
    readme = (root / "summary" / "README.md").read_text(encoding="utf-8")
    assert "1 completed of 2 planned cases" in readme


def test_an_unknown_figure_is_refused_with_the_cohort_ones(tmp_path: Path) -> None:
    root = _project(tmp_path, summary_extra='figures = ["histogram"]')
    _seal(root, "J0014010", "base", nse=0.81)

    with pytest.raises(SummaryError, match="histogram"):
        collect_project(root)


def test_a_manifest_this_version_cannot_read_stops_the_collect_by_name(tmp_path: Path) -> None:
    root = _project(tmp_path)
    run_dir = _seal(root, "J0014010", "base", nse=0.81)
    collect_project(root)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["run"]["solver"] = {"not": "a solver name"}
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(UnreadableManifestError, match="J0014010-base") as refused:
        collect_project(root)
    assert "do not read under HydroModPy" in str(refused.value)


def test_a_figure_the_cohort_cannot_give_is_named_and_the_others_drawn(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        summary_extra='best = "any"\nfigures = ["distribution"]\nvariables = ["K", "kge"]',
    )
    _seal(root, "J0014010", "base", nse=0.81, k=2e-5)

    paths = collect_project(root)

    assert sorted(path.name for path in paths.figures.glob("*.png")) == ["distribution_K.png"]
    (skipped,) = paths.skipped
    assert skipped.startswith("distribution of kge: ")
    assert "distribution of kge" in paths.report.read_text(encoding="utf-8")


def test_a_collect_that_stops_keeps_the_figures_of_the_last_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(
        tmp_path, summary_extra='best = "any"\nfigures = ["distribution"]\nvariables = ["K"]'
    )
    _seal(root, "J0014010", "base", nse=0.81, k=2e-5)
    first = collect_project(root)
    drawn = (first.figures / "distribution_K.png").read_bytes()

    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(summary_module, "_write_exports", broken)
    with pytest.raises(OSError, match="disk full"):
        collect_project(root)

    assert (first.figures / "distribution_K.png").read_bytes() == drawn
    assert Ledger.read(first.figures).entry_for("distribution_K.png") is not None
    assert [path.name for path in (root / "summary").iterdir() if path.name.startswith(".")] == []


def test_the_mesh_the_solve_time_and_the_place_are_read_from_the_seal(tmp_path: Path) -> None:
    root = _project(tmp_path, summary_extra='best = "any"')
    run_dir = _seal(root, "J0014010", "base", nse=0.81)
    record = RunRecord.read(run_dir)
    catchment = {
        "catch_area": "64.62",
        "dem_res": "75.0",
        "x_outlet_snapped": "389175.0",
        "y_outlet_snapped": "6816450.0",
    }
    solve = MetricRow(
        station="flow_main::modflow6",
        variable="runtime",
        metric="flow_solve_time_seconds",
        value=26.3,
    )
    record.model_copy(
        update={
            "site": record.site.model_copy(update={"area_km2": None, "dem_resolution_m": None}),
            "geometry": record.geometry.model_copy(
                update={"mesh_engine": "voronoi", "catchment": catchment}
            ),
            "metrics": [*record.metrics, solve],
        }
    ).write(run_dir)

    paths = collect_project(root)

    case = pd.read_parquet(paths.by_case).iloc[0]
    assert case["mesh_engine"] == "voronoi"
    assert case["flow_solve_time_s"] == pytest.approx(26.3)
    site = pd.read_parquet(paths.by_site).iloc[0]
    assert site["area_km2"] == pytest.approx(64.62)
    assert site["dem_resolution_m"] == pytest.approx(75.0)
    assert (site["snapped_x"], site["snapped_y"]) == (389175.0, 6816450.0)


def test_a_calibration_row_takes_the_time_of_its_session(tmp_path: Path) -> None:
    root = _project(tmp_path, summary_extra='best = "any"')
    _seal(root, "J0014010", "calage", nse=0.62, calibrated=True)
    started = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    write_session_dir(
        root, "J0014010-calage", case_id="J0014010-calage", site="J0014010", started_at=started
    )

    paths = collect_project(root)

    row = pd.read_parquet(paths.by_case).set_index("case_id").loc["J0014010-calage"]
    assert row["kind"] == "calibration"
    assert row["session_rel_dir"] == "sessions/J0014010-calage"
    assert pd.Timestamp(row["started_at"]) == pd.Timestamp(started)
    assert pd.Timestamp(row["ended_at"]) == pd.Timestamp("2026-10-01T09:00:00Z")
    assert row["duration_s"] == pytest.approx(3600.0)


def test_a_failed_case_names_its_paths_from_the_project_root(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _plan(root, ["J0014010-base"])
    write_attempt(
        root,
        "runs/J0014010-base",
        status="failed",
        case_id="J0014010-base",
        site="J0014010",
        error=(
            "SolverError",
            f"See {root}/runs/J0014010-base/.hmp/scratch/mfsim.lst and /mnt/lab/dem.tif",
        ),
    )

    collect_project(root)

    expected = "See runs/J0014010-base/.hmp/scratch/mfsim.lst and <absolute path>"
    by_case = pd.read_parquet(root / "summary" / "by_case.parquet").set_index("case_id")
    assert by_case.loc["J0014010-base", "error_message"] == expected
    csv_rows = pd.read_csv(root / "summary" / "by_case.csv").set_index("case_id")
    assert csv_rows.loc["J0014010-base", "error_message"] == expected


RECIPES_TOML = """\
[sites]
table = "sites.csv"

[sites.recipes]
k_low = { file = "project.toml", set = { "flow.param.K.field.value" = 1e-5 } }
k_mid = "project.toml"
"""


def test_by_case_names_every_parameter_and_the_set_of_its_recipe(tmp_path: Path) -> None:
    root = tmp_path / "comparison"
    root.mkdir()
    (root / "project.toml").write_text(RECIPES_TOML, encoding="utf-8")
    _plan(root, ["nancon-k_low", "nancon-k_mid"])
    for recipe, k in (("k_low", 1e-5), ("k_mid", 5e-5)):
        seal_run(
            root,
            f"nancon-{recipe}",
            project=root.name,
            site="nancon",
            recipe=recipe,
            nse=None,
            window=None,
            parameters={"K": k, "Sy": 0.05, "thickness": 30.0},
        )

    collect_project(root)

    by_case = pd.read_csv(root / "summary" / "by_case.csv").set_index("case_id")
    # Not listed under [sites.summary] parameters: every global parameter is a column.
    assert by_case.loc["nancon-k_low", "K"] == pytest.approx(1e-5)
    assert by_case.loc["nancon-k_mid", "K"] == pytest.approx(5e-5)
    assert by_case.loc["nancon-k_mid", "Sy"] == pytest.approx(0.05)
    assert by_case.loc["nancon-k_low", "thickness"] == pytest.approx(30.0)
    assert by_case.loc["nancon-k_low", "overrides"] == "flow.param.K.field.value=1e-05"
    assert pd.isna(by_case.loc["nancon-k_mid", "overrides"])


def test_a_site_without_a_scored_run_says_why_it_has_no_best_case(tmp_path: Path) -> None:
    root = _project(tmp_path, summary_extra='best = "any"')
    seal_run(root, "J0014010-base", project=root.name, site="J0014010", recipe="base", nse=None)
    _seal(root, "J0170000", "base", nse=0.81)

    collect_project(root)

    by_site = pd.read_csv(root / "summary" / "by_site.csv").set_index("site")
    assert pd.isna(by_site.loc["J0014010", "best_case"])
    assert by_site.loc["J0014010", "best_reason"] == (
        "no sealed run of J0014010 is scored: declare [metrics] window"
    )
    assert by_site.loc["J0170000", "best_case"] == "J0170000-base"
    assert pd.isna(by_site.loc["J0170000", "best_reason"])


def test_a_scored_site_without_a_calibrated_case_says_so(campaign: Path) -> None:
    _seal(campaign, "J0200000", "base", nse=0.5)

    collect_project(campaign)

    by_site = pd.read_parquet(campaign / "summary" / "by_site.parquet").set_index("site")
    assert by_site.loc["J0200000", "best_reason"] == (
        'no calibrated case of J0200000 is scored; best = "any" ranks every case'
    )
