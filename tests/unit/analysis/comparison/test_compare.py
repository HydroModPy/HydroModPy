"""Each test states one thing a hydrogeologist can check by hand."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest

import hydromodpy as hmp
from hydromodpy.analysis.comparison import compare as c
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_VALIDATION
from hydromodpy.cli.main import main as hmp_main
from tests.unit.results._run_record_factory import make_identity, make_record

pytestmark = pytest.mark.fast

D = pd.Timestamp
TWO_CELLS = ((0.0, 0.0), (10.0, 0.0))


def make_run(
    name="a",
    start="2000-01-01",
    freq="D",
    n=4,
    q=1.0,
    site="s",
    mesh="m",
    centers=TWO_CELLS,
    areas=(100.0, 100.0),
    head=(1.0, 2.0),
    params=None,
    gauge="G",
    unit="m3/s",
    networks=(),
    flows=True,
    regime="transient",
    fields=("watertable_elevation", "watertable_depth", "head"),
    has_budget=True,
):
    """A run answering the public Run API, with values chosen to be checked by hand.

    A field grows by 10 per step and a term of the budget is 2 + step, so that a
    wrong step, variable or weight changes the answer.
    """
    stamps = pd.date_range(start, periods=n + 1, freq=freq)[1:]
    q_at = q if callable(q) else lambda _: q
    series = {"discharge": ("_catchment", 0.0), "head": ("P1", 50.0)}
    offsets = {"watertable_elevation": 0.0, "watertable_depth": 100.0, "head": 0.0}
    terms = (("recharge", 2.0, 0.0), ("drain", 0.0, 2.0))
    budget = pd.DataFrame(
        {
            "timestep": t,
            "zone_id": zone,
            "component": term,
            "flux_in": fin and fin + t,
            "flux_out": fout and fout + t,
            "unit": unit,
        }
        for t in range(n if has_budget else 0)
        for zone in ("0", "catchment")
        for term, fin, fout in terms
    )
    columns = ("station", "metric", "value", "window_start", "window_end", "n_samples")
    rows = ((gauge, m, 0.123456, "w0", "w1", n) for m in ("nse", "rmse"))
    metrics = pd.DataFrame(rows, columns=columns) if gauge else pd.DataFrame()
    x, y = np.array(centers).T
    corners = np.column_stack([np.repeat(x, 4), np.repeat(y, 4)]) + [
        [-1, -1],
        [1, -1],
        [1, 1],
        [-1, 1],
    ] * len(x)

    def timeseries(variable, station):
        assert station == series[variable][0]
        values = [q_at(d) + series[variable][1] for d in stamps]
        return pd.Series(values, index=stamps, name=variable)

    def stations(variable):
        return ([gauge] if gauge else []) if variable.endswith("_obs") else [series[variable][0]]

    return NS(
        name=name,
        site=site,
        solver="modflow6",
        params=params or {"K": 1e-5},
        metrics=metrics,
        time_index=None if regime == "steady" else stamps,
        checks=NS(budget_pct=0.1),
        record=NS(
            period=NS(start=f"{start}T00:00:00Z", end=str(stamps[-1])),
            identity=NS(site_fingerprint=site, mesh_hash=mesh),
            run=NS(flow_regime=regime),
        ),
        mesh=NS(
            cell_centers=lambda: np.array(centers),
            cell_areas=lambda: np.array(areas),
            vertices=corners,
            face_node_connectivity=np.arange(len(x) * 4).reshape(-1, 4),
        ),
        stations=stations,
        timeseries=timeseries,
        field=lambda v, timestep: np.asarray(head) + offsets[v] + 10.0 * timestep,
        budget=lambda: budget,
        has_field=lambda v: v in fields or (flows and v == "accumulation_flux"),
        has_hydrographic_network=lambda role: role in networks,
        observed=lambda v: pd.DataFrame({"datetime": stamps, "value": 1.0}),
    )


@pytest.mark.parametrize(
    ("runs", "message"),
    [
        ([make_run()], "A comparison needs at least two runs"),
        ([make_run(), make_run()], "distinct names"),
        ([make_run(), make_run("b", site="other")], "a: s, b: other.*--by site"),
        (
            [make_run(), make_run("b", start="2015-01-01")],
            "a: 2000-01-01 to 2000-01-05, b: 2015-01-01 to 2015-01-05",
        ),
        ([make_run(), make_run("b", start="2000-01-05")], "share no date"),
        ([make_run(regime="steady", n=1), make_run("b")], "Steady and transient"),
        ([make_run(), make_run("b", unit="m3/d")], "b has budget rows in ..m3/d.., not m3/s"),
        ([make_run(), make_run("b", head=[[1.0, 2.0]])], "watertable_elevation is not one value"),
    ],
)
def test_what_cannot_be_compared_is_refused(runs, message) -> None:
    with pytest.raises(c.ComparisonCaseError, match=message):
        c.compare(runs)


def test_two_series_pair_on_their_shared_dates_only() -> None:
    late = make_run("b", start="2000-01-03", q=3.0)  # two days shared with the reference
    rows = c.compare([make_run(), late]).tables["series"].to_dict("records")
    assert rows[0] == {
        "variable": "discharge",
        "station": "_catchment",
        "run": "b",
        "reference": "a",
        "first": "2000-01-04 00:00:00",
        "last": "2000-01-05 00:00:00",
        "n": 2,
        "reference_mean": 1.0,
        "bias": 2.0,
        "mae": 2.0,
        "rmse": 2.0,
    }
    assert (rows[1]["variable"], rows[1]["station"], rows[1]["reference_mean"]) == (
        "head",
        "P1",
        51.0,
    )


def test_a_period_mean_is_weighted_by_duration_and_the_stamp_closes_its_period() -> None:
    dates = pd.to_datetime(["2000-01-01", "2000-01-02", "2000-01-04"])
    series = pd.Series([100.0, 1.0, 4.0], index=dates, name="q")
    means = c.period_means(series, D("2000-01-01"), pd.DatetimeIndex(["2000-01-04"]))
    assert means.to_dict() == {D("2000-01-04"): 3.0}  # (1 x 1 + 4 x 2) / 3
    assert means.name == "q"


def test_a_daily_series_compares_on_the_months_of_a_monthly_one() -> None:
    daily = make_run("d", n=60, q=2.0)
    row = c.compare([daily, make_run("m", freq="MS", n=2, q=1.0)]).tables["series"].iloc[0]
    assert (row["n"], row["bias"], row["last"]) == (2, -1.0, "2000-03-01 00:00:00")


def test_a_period_covered_in_part_is_left_out() -> None:
    daily = make_run("d", start="2000-01-16", n=60, q=2.0)  # to 16 March, so February only
    row = c.compare([daily, make_run("m", freq="MS", n=3, q=1.0)]).tables["series"].iloc[0]
    assert (row["n"], row["bias"], row["first"]) == (1, -1.0, "2000-03-01 00:00:00")


def test_no_whole_period_in_common_gives_no_series() -> None:
    tables = c.compare([make_run(), make_run("m", freq="MS", n=1)]).tables
    assert tables["series"].empty
    assert tables["maps"].empty


def test_steps_that_never_meet_give_series_but_no_map() -> None:
    tables = c.compare([make_run(freq="2D"), make_run("b", start="2000-01-02", freq="2D")]).tables
    assert tables["maps"].empty
    assert tables["series"]["n"].iloc[0] == 3


def test_steady_runs_compare_whatever_date_their_solver_wrote(tmp_path: Path) -> None:
    first = make_run(regime="steady", n=1)
    second = make_run("b", start="2003-06-01", regime="steady", n=1, q=3.0, head=(2.0, 3.0))
    result = c.compare([first, second], ["head"])
    assert result.tables["series"].iloc[0][["first", "n", "bias"]].tolist() == ["steady", 1, 2.0]
    assert result.tables["maps"].iloc[0][["date", "bias"]].tolist() == ["steady", 1.0]
    budget = result.tables["budget"].query("run == 'b' and zone == '0'").set_index("term")["m3_s"]
    assert budget.to_dict() == {"drain": -2.0, "recharge": 2.0, "residual": 0.0}
    text = result.write(tmp_path).read_text()
    assert "Reference a. Steady state." in text
    assert not list(tmp_path.glob("discharge*.png"))


def test_a_map_error_is_weighted_by_surface_at_the_last_shared_date() -> None:
    wide = {"areas": (100.0, 300.0)}
    ahead = make_run("b", start="1999-12-31", n=3, head=(1.0, 1.0), **wide)  # one step ahead
    rows = c.compare([make_run(**wide), ahead], ["head"]).tables["maps"].to_dict("records")
    assert rows == [
        {
            "variable": "head",
            "date": "2000-01-03 00:00:00",
            "run": "b",
            "reference": "a",
            "same_mesh": True,
            "n": 2,
            "reference_mean": 11.75,
            "bias": 9.25,
            "mae": 9.25,
            "rmse": pytest.approx(np.sqrt((100 + 3 * 81) / 4)),
        }
    ]


def test_another_mesh_is_read_at_its_nearest_cell_and_never_too_far() -> None:
    reference = make_run(centers=((0.0, 0.0), (30.0, 0.0)))
    other = make_run("b", mesh="n", centers=((10.0, 0.0), (500.0, 0.0)), head=(4.0, 9.0))
    row = c.compare([reference, other], ["head"]).tables["maps"].iloc[0]
    assert (row["n"], row["bias"], row["same_mesh"]) == (1, 3.0, False)
    apart = make_run("c", mesh="n", centers=((900.0, 0.0), (950.0, 0.0)))
    assert c.compare([reference, apart], ["head"]).tables["maps"]["n"].iloc[0] == 0


def test_a_field_is_mapped_when_every_run_has_it_and_a_named_one_must_be() -> None:
    runs = [make_run(), make_run("b", fields=("watertable_depth",))]
    assert c.compare(runs).tables["maps"]["variable"].tolist() == ["watertable_depth"]
    with pytest.raises(c.ComparisonCaseError, match="'head'.*not fields of every"):
        c.compare(runs, ["head"])


def test_budget_terms_stay_per_zone_and_are_weighted_by_duration_on_the_shared_dates() -> None:
    uneven = make_run(n=4)
    uneven.time_index = pd.to_datetime(["2000-01-02", "2000-01-03", "2000-01-04", "2000-01-07"])
    uneven.record.period.end = "2000-01-07"
    table = c.compare([uneven, make_run("b", start="2000-01-03")]).tables["budget"]
    one = table.query("run == 'a' and zone == 'catchment'").set_index("term")["m3_s"]
    # (4 x 1 + 5 x 3) / 4
    assert one.to_dict() == {"drain": -4.75, "recharge": 4.75, "residual": 0.0}
    assert set(table["zone"]) == {"0", "catchment"}


def test_a_run_without_budget_rows_is_left_out_of_the_budget() -> None:
    table = c.compare([make_run(has_budget=False), make_run("b")]).tables["budget"]
    assert set(table["run"]) == {"b"}


def test_each_mapped_network_gives_one_row_with_overlap_and_distance(monkeypatch) -> None:
    def overlap(run, network_role):
        assert run.name == "a"
        return {"network_role": network_role, "cell_f1_ratio": 0.5, "other": 1}

    def distance(run, network_role):
        assert run.name == "a" and network_role.startswith("reference")
        return {"sim_to_network_distance_median_m": 30.0}

    monkeypatch.setattr(c.views, "cell_field_network_overlap_metrics", overlap)
    monkeypatch.setattr(c.views, "cell_field_network_distance_metrics", distance)
    runs = [
        make_run(networks=("reference", "reference_permanent")),
        make_run("b", networks=("generated",)),
        make_run("c", networks=("reference",), flows=False),
    ]
    table = c.network_table(runs)
    columns = ["run", "network_role", "cell_f1_ratio", "sim_to_network_distance_median_m"]
    assert table[columns].values.tolist() == [
        ["a", "reference", 0.5, 30.0],
        ["a", "reference_permanent", 0.5, 30.0],
    ]
    assert "other" not in table
    assert c.network_table(runs[1:]).empty


def test_the_runs_table_says_what_each_run_is() -> None:
    runs = [make_run(), make_run("b", mesh="0123456789")]
    assert c.compare(runs).tables["runs"].to_dict("records")[1] == {
        "run": "b",
        "solver": "modflow6",
        "start": "2000-01-01T00:00:00Z",
        "end": "2000-01-05 00:00:00",
        "n_steps": 4,
        "budget_pct": 0.1,
        "mesh": "01234567",
    }


def test_only_the_parameters_that_differ_are_listed() -> None:
    first = make_run(params={"K": 1.0, "Sy": 0.1})
    second = make_run("b", params={"K": 2.0, "Sy": 0.1, "Ss": 0.3})
    table = c.compare([first, second]).tables["parameters"].set_index("parameter")
    assert sorted(table.index) == ["K", "Ss"]
    assert table.loc["K"].to_dict() == {"a": 1.0, "b": 2.0}


def test_scores_keep_their_window_and_samples_and_a_run_without_gauge_gives_none() -> None:
    table = c.compare([make_run(), make_run("b", gauge=None)]).tables["scores"]
    assert table.to_dict("records") == [
        {
            "run": "a",
            "station": "G",
            "metric": "nse",
            "value": 0.123456,
            "window_start": "w0",
            "window_end": "w1",
            "n_samples": 4,
        }
    ]
    assert c.scores_table([make_run(gauge=None)]).empty


def test_the_folder_holds_every_table_and_figure_named_in_its_readme(tmp_path: Path) -> None:
    readme = c.compare([make_run(), make_run("b", head=(2.0, 3.0))]).write(tmp_path / "new" / "dir")
    tmp_path = readme.parent
    text = readme.read_text()
    assert readme.name == "README.md"
    assert pd.read_csv(tmp_path / "runs.csv").columns[0] == "run"
    tables = ("runs", "parameters", "scores", "budget", "network", "series", "maps")
    assert {p.name for p in tmp_path.glob("*.csv")} == {f"{t}.csv" for t in tables}
    assert {p.name for p in tmp_path.glob("*.png")} == {
        "discharge_catchment.png",
        "head_P1.png",
        "watertable_elevation.png",
        "watertable_depth.png",
    }
    assert text.startswith("# a vs b\n\nReference a. Dates compared 2000-01-01 to 2000-01-05.\n")
    assert "## parameters\n\nNothing to compare." in text
    assert "| a | G | nse | 0.1235 | w0 | w1 | 4 |" in text
    assert "| --- | --- |" in text
    assert all(f"![{v}]" in text for v in ("discharge", "head", "watertable_depth"))


def _seal(
    project: Path, name: str, *, recipe: str = "r", site: str = "s", version: int = 1
) -> Path:
    """Write one sealed run under ``runs/``, enough to resolve and to refuse."""
    base = make_record()
    run_dir = project / "runs" / name
    run_dir.mkdir(parents=True)
    make_record(
        run=base.run.model_copy(
            update={
                "name": name,
                "recipe": recipe,
                "version": version,
                "case_id": f"{site}-{recipe}",
                "rel_dir": f"runs/{name}",
            }
        ),
        site=base.site.model_copy(update={"name": site, "fingerprint": f"fp_{site}"}),
        identity=make_identity(
            site=site, site_fingerprint=f"fp_{site}", case_id=f"{site}-{recipe}"
        ),
    ).write(run_dir)
    return run_dir


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "bretagne"
    root.mkdir()
    (root / "project.toml").write_text("", encoding="utf-8")
    return root


def test_a_reference_is_a_directory_a_name_or_the_latest_run_of_a_recipe(project: Path) -> None:
    directory = _seal(project, "x-base", recipe="base")
    _seal(project, "y-base", recipe="base", site="y")
    _seal(project, "y-base.v2", recipe="base", site="y", version=2)
    _seal(project, "y-other", recipe="other", site="y")
    named = c.resolve_references([str(directory), "y-other", "base"], project_root=project)
    assert [[run.name for run in runs] for runs in named] == [
        ["x-base"],
        ["y-other"],
        ["x-base", "y-base.v2"],
    ]
    only_a_directory = c.resolve_references([str(directory)], project_root=None)
    assert only_a_directory[0][0].name == "x-base"


@pytest.mark.parametrize("root", ["project", None])
def test_a_reference_that_names_no_sealed_run_is_refused(project: Path, root: str | None) -> None:
    (project / "runs" / "failed").mkdir(parents=True)
    with pytest.raises(c.ComparisonReferenceError, match="'failed' names no sealed run"):
        c.resolve_references(["failed"], project_root=project if root else None)


def test_the_command_gives_typed_exit_codes(project: Path, monkeypatch) -> None:
    _seal(project, "one", site="s1")
    _seal(project, "two", site="s2")
    monkeypatch.chdir(project)
    for refs, code in ((["one", "nowhere"], EXIT_NOT_FOUND), (["one", "two"], EXIT_VALIDATION)):
        with pytest.raises(SystemExit) as refused:
            hmp_main(["report", "compare", *refs])
        assert refused.value.code == code


def test_the_command_writes_in_the_project_or_where_it_is_told(project: Path, monkeypatch) -> None:
    written: list[Path] = []
    comparison = NS(write=lambda folder: written.append(Path(folder)) or Path(folder) / "README.md")
    monkeypatch.setattr(c, "compare_references", lambda refs, **_: comparison)
    monkeypatch.setattr(
        c, "compare_by_site", lambda refs, folder, **_: written.append(Path(folder))
    )
    monkeypatch.chdir(project)
    hmp_main(["report", "compare", "runs/a", "b c", "--variables", "head, ,x"])
    hmp_main(["report", "compare", "a", "b", "--by", "site", "--out", "elsewhere"])
    assert written == [project / "summary/report/compare/a-vs-b_c", Path("elsewhere")]


def test_references_reach_the_comparison_with_their_variables(monkeypatch) -> None:
    monkeypatch.setattr(c, "resolve_references", lambda refs, project_root: [[project_root], refs])
    monkeypatch.setattr(c, "compare", lambda runs, variables: (runs, variables))
    compared = c.compare_references(["a", "b"], project_root="root", variables=["head"])
    assert compared == (["root", "a", "b"], ["head"])


def test_a_folder_needs_a_project_and_a_long_name_becomes_a_hash(project: Path) -> None:
    with pytest.raises(c.ComparisonCaseError, match="pass --out"):
        c.default_folder(["a", "b"], None)
    assert len(c.default_folder(["a" * 100, "b"], project).name) == 12


def test_the_facade_compares_and_writes_only_when_asked(project: Path, monkeypatch) -> None:
    written: list[Path] = []
    comparison = NS(write=written.append)
    monkeypatch.setattr(c, "compare_references", lambda refs, **_: comparison)
    assert hmp.compare(["a", "b"], workspace=project) is comparison
    assert written == []
    hmp.compare(["a", "b"], out=project / "study", workspace=project)
    assert written == [project / "study"]


def test_sites_are_compared_apart_and_their_scores_joined(tmp_path: Path, monkeypatch) -> None:
    first = [make_run("a1", site="x", gauge=None), make_run("a2", site="y")]
    second = [make_run("b1", site="x")]
    monkeypatch.setattr(c, "resolve_references", lambda refs, project_root: project_root and refs)
    path = c.compare_by_site([first, second], tmp_path, project_root=True, variables=["head"])
    assert path == tmp_path / "by_site.csv"
    assert (tmp_path / "x" / "head.png").exists()
    assert not (tmp_path / "y").exists()
    assert pd.read_csv(path)["site"].tolist() == ["x"]
    with pytest.raises(c.ComparisonCaseError, match="No site holds a run in two"):
        c.compare_by_site([first], tmp_path, project_root=True)
    with pytest.raises(c.ComparisonCaseError, match="One reference holds two runs"):
        c.compare_by_site([[make_run("m"), make_run("n")]], tmp_path, project_root=True)
