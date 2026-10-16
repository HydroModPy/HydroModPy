"""A [sites] campaign read from Python with the words of the CLI (D6, D9).

``hmp.open(project)`` gives a ``Project`` that reads its plan, its runs and
its sessions from the disk: ``cases`` (the plan joined to the outcomes),
``sites``, ``best(metric, by="site")``, ``runs(site=)``, ``sessions[...]``,
``proj[ref]``; it launches with ``plan``, ``run``, ``status``, ``collect`` and
``publish``. ``hmp.index().runs(site=)`` reads across the projects of a
workspace. The runs here are sealed the way a run seals itself; the plan is
written by ``Project.plan``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import pytest

import hydromodpy as hmp
from hydromodpy.results.checks import CalibratedBy
from hydromodpy.results.metric_rule import DateWindow
from tests._helpers.sealed_runs import WINDOW, seal_run, write_attempt, write_session_dir

pytestmark = pytest.mark.fast

_PROJECT = """\
[workspace]
data_dir = "data"

[workflow]
mode = "simulation"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "dem.tif"
snap_dist = "150 m"
buff_area = "10%"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-03-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "steady"
param_list = ["K"]
active_bc = ["drainage"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[sites]
table = "sites.csv"

[sites.recipes]
base = "project.toml"
k2e_5 = { file = "project.toml", set = { "flow.param.K.field.value" = 2e-5 } }

[sites.bind]
"site.name" = "site"
"site.gauge" = "gauge"
"geographic.catchment.x_outlet" = "x_outlet"
"geographic.catchment.y_outlet" = "y_outlet"
"""

PLAN_CASES = {"nancon-base", "nancon-k2e_5", "couesnon-base", "couesnon-k2e_5"}


def _campaign(tmp_path: Path) -> Path:
    """Write a two-site, two-recipe project under a workspace and return its root."""
    project = tmp_path / "ws" / "projects" / "bretagne"
    (project / "data").mkdir(parents=True)
    (project / "dem.tif").write_bytes(b"not a raster, never read by the plan")
    (project / "project.toml").write_text(_PROJECT, encoding="utf-8")
    (project / "sites.csv").write_text(
        "site,gauge,x_outlet,y_outlet\n"
        "nancon,J0014010,389285.910,6816518.749\n"
        "couesnon,J0121510,377120.0,6831410.0\n",
        encoding="utf-8",
    )
    return project


def _calibrated(session_id: str) -> CalibratedBy:
    return CalibratedBy(
        session_id=session_id,
        phase="steady_k",
        trial=2,
        session_status="completed",
        window=WINDOW,
    )


def _launched(project: Path) -> dict[str, str]:
    """Plan the campaign, seal two cases of nancon, fail one of couesnon."""
    proj = hmp.open(project)
    draft = proj.plan()
    assert {case.case_id for case in draft.cases} == PLAN_CASES
    sim_ids = {
        "base": seal_run(
            project, "nancon-base", site="nancon", recipe="base", nse=0.52, parameters={"K": 5e-5}
        ),
        "k2e_5": seal_run(
            project,
            "nancon-k2e_5",
            site="nancon",
            recipe="k2e_5",
            nse=0.81,
            parameters={"K": 2e-5},
            calibrated_by=_calibrated("s-nancon"),
        ),
    }
    write_attempt(
        project,
        "runs/couesnon-base",
        status="failed",
        case_id="couesnon-base",
        site="couesnon",
        error=("SolverError", "diverged"),
    )
    write_session_dir(
        project,
        "nancon-k2e_5",
        session_id="s-nancon",
        case_id="nancon-k2e_5",
        site="nancon",
        trials=3,
        best_trial=2,
        best_sim_id=sim_ids["k2e_5"],
        best_rel_dir="runs/nancon-k2e_5",
    )
    proj.close()
    return sim_ids


def test_cases_join_the_plan_to_the_outcomes(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    _launched(project)

    with hmp.open(project) as proj:
        cases = proj.cases.set_index("case_id")

    assert set(cases.index) == PLAN_CASES
    assert cases.loc["nancon-base", "status"] == "completed"
    assert cases.loc["nancon-k2e_5", "status"] == "completed"
    assert cases.loc["couesnon-base", "status"] == "failed"
    assert cases.loc["couesnon-k2e_5", "status"] == "planned"
    assert cases.loc["nancon-base", "label"] == "exploratory"
    assert cases.loc["nancon-k2e_5", "label"] == "calibrated"
    assert cases.loc["nancon-k2e_5", "nse"] == pytest.approx(0.81)
    assert cases.loc["nancon-k2e_5", "K"] == pytest.approx(2e-5)
    assert cases.loc["nancon-k2e_5", "rel_dir"] == "runs/nancon-k2e_5"
    assert cases.loc["nancon-k2e_5", "site"] == "nancon"
    assert cases.loc["nancon-k2e_5", "recipe"] == "k2e_5"


def test_sites_are_the_sites_of_the_plan_with_their_outlet(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    _launched(project)

    with hmp.open(project) as proj:
        sites = proj.sites

    assert isinstance(sites, gpd.GeoDataFrame)
    assert list(sites["site"]) == ["nancon", "couesnon"]
    assert sites.crs.to_epsg() == 2154
    assert sites.geometry.iloc[0].x == pytest.approx(389285.910)


def test_best_by_site_ranks_the_calibrated_runs_under_their_rule(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    sim_ids = _launched(project)

    with hmp.open(project) as proj:
        best = proj.best("nse", by="site")
        every = proj.best("nse", by="site", label=None)

    assert list(best["site"]) == ["nancon"]
    row = best.iloc[0]
    assert row["case_id"] == "nancon-k2e_5"
    assert row["sim_id"] == sim_ids["k2e_5"]
    assert row["K"] == pytest.approx(2e-5)
    assert row["nse"] == pytest.approx(0.81)
    assert row["nse_window_start"] == WINDOW.start
    assert row["nse_window_end"] == WINDOW.end
    assert list(every["case_id"]) == ["nancon-k2e_5"]


def test_best_refuses_two_windows_inside_one_site(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    _launched(project)
    other = DateWindow(start=date(2010, 1, 1), end=date(2014, 12, 31))
    seal_run(project, "nancon-base.v2", site="nancon", recipe="base", nse=0.9, window=other)

    with hmp.open(project) as proj:
        with pytest.raises(ValueError, match="different rules"):
            proj.best("nse", by="site", label=None)
        assert len(proj.best("nse", by="site", label=None, mixed_windows=True)) == 1


def test_runs_of_a_site_carry_their_metrics_without_suffix(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    sim_ids = _launched(project)

    with hmp.open(project) as proj:
        runs = proj.runs(site="nancon")
        metrics = runs.metrics.set_index("sim_id")
        named = proj["nancon-base"]

    assert set(runs.sim_ids) == set(sim_ids.values())
    assert metrics.loc[sim_ids["k2e_5"], "nse"] == pytest.approx(0.81)
    assert metrics.loc[sim_ids["k2e_5"], "nse_window_start"] == WINDOW.start
    assert named.sim_id == sim_ids["base"]
    assert named.site == "nancon"
    assert named.checks.budget_pct == pytest.approx(0.8)


def test_a_session_reads_its_trials_phases_config_and_best(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    sim_ids = _launched(project)

    with hmp.open(project) as proj:
        assert list(proj.sessions) == ["nancon-k2e_5"]
        session = proj.sessions["nancon-k2e_5"]

    assert session.status == "completed"
    assert list(session.trials["iteration"]) == [1, 2, 3]
    assert [phase.name for phase in session.phases] == ["steady_k"]
    assert session.config == {}
    assert session.best is not None
    assert session.best.sim_id == sim_ids["k2e_5"]
    assert session.best.label().label == "calibrated"


def test_the_workspace_index_reads_runs_across_projects_by_site(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    sim_ids = _launched(project)

    runs = hmp.index(tmp_path / "ws").runs(site="nancon")

    assert set(runs["sim_id"]) == set(sim_ids.values())


def test_the_launch_verbs_speak_the_words_of_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run``, ``status`` and ``collect`` call the launcher and the summary with the CLI words."""
    import hydromodpy.project.launch as launch
    import hydromodpy.project.summary as summary

    project = _campaign(tmp_path)
    calls: dict[str, Any] = {}

    def run_plan(root: Path, **kwargs: Any) -> str:
        calls["run"] = (root, kwargs)
        return "launched"

    def collect_project(root: Path, **kwargs: Any) -> str:
        calls["collect"] = (root, kwargs)
        return "collected"

    monkeypatch.setattr(launch, "run_plan", run_plan)
    monkeypatch.setattr(summary, "collect_project", collect_project)

    with hmp.open(project) as proj:
        assert proj.run(parallel=8, only="failed", site="nancon") == "launched"
        assert proj.collect(write_sites=True) == "collected"
        proj.plan()
        status = proj.status()

    root, kwargs = calls["run"]
    assert root == project.resolve()
    assert kwargs["parallel"] == 8
    assert kwargs["only"] == ("failed",)
    assert kwargs["site"] == "nancon"
    assert calls["collect"] == (project.resolve(), {"write_sites": True, "mixed_windows": False})
    assert {row.case_id for row in status.rows} == PLAN_CASES
    assert {row.status for row in status.rows} == {"planned"}


def test_publish_copies_the_summary_once_it_is_collected(tmp_path: Path) -> None:
    project = _campaign(tmp_path)

    with hmp.open(project) as proj:
        with pytest.raises(FileNotFoundError, match="collect"):
            proj.publish(tmp_path / "out")
        (project / "summary").mkdir()
        (project / "summary" / "README.md").write_text("# Summary\n", encoding="utf-8")
        copy = proj.publish(tmp_path / "out")

    assert (copy / "README.md").read_text(encoding="utf-8") == "# Summary\n"


def test_a_sites_project_is_never_configured_as_one_model(tmp_path: Path) -> None:
    from hydromodpy.config.sites.expansion import SitesProjectError

    project = _campaign(tmp_path)

    with hmp.open(project) as proj:
        with pytest.raises(SitesProjectError, match="proj.run"):
            proj.config  # noqa: B018
