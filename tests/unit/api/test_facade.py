"""``Project`` of a ``[sites]`` campaign, read from the disk with the words of the CLI.

``hmp.open(project)`` reads the plan, the runs and the sessions: ``cases`` (the plan
joined to the outcomes), ``sites``, ``best_runs``, ``runs(site=)``, ``sessions[...]``
and ``proj[ref]``. It launches with ``plan``, ``launch``, ``status``, ``collect`` and
``publish``. The runs are sealed the way a run seals itself.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import pytest

from hydromodpy.project import api
from hydromodpy.project.launch.status import CASE_COLUMNS
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.record.checks import CalibratedBy
from hydromodpy.results.run.sealed import MixedWindowsError
from tests._helpers.sealed_runs import (
    WINDOW,
    make_project,
    seal_run,
    write_attempt,
    write_session_dir,
)
from tests._helpers.session_documents import calibration_window

pytestmark = pytest.mark.fast

_PROJECT = """\
[workspace]
data_dir = "data"

[workflow]
mode = "simulation"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
snap_dist = "150 m"
buff_area = "10%"

[data]
types = ["dem"]

[[data.dem.sources]]
source = "file"
path = "dem.tif"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-03-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.bc.drainage]

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
        windows=calibration_window(WINDOW.start, WINDOW.end),
    )


def _launched(project: Path) -> dict[str, str]:
    """Plan the campaign, seal two cases of nancon, fail one of couesnon."""
    proj = api.open(project)
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


def test_cases(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    _launched(project)

    with api.open(project) as proj:
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


def test_sites(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    _launched(project)

    with api.open(project) as proj:
        sites = proj.sites

    assert isinstance(sites, gpd.GeoDataFrame)
    assert list(sites["site"]) == ["nancon", "couesnon"]
    assert sites.crs.to_epsg() == 2154
    assert sites.geometry.iloc[0].x == pytest.approx(389285.910)


def test_best_by_site(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    sim_ids = _launched(project)

    with api.open(project) as proj:
        best = proj.best_runs("nse", by="site")
        every = proj.best_runs("nse", by="site", label=None)

    assert list(best["site"]) == ["nancon"]
    row = best.iloc[0]
    assert row["case_id"] == "nancon-k2e_5"
    assert row["sim_id"] == sim_ids["k2e_5"]
    assert row["K"] == pytest.approx(2e-5)
    assert row["nse"] == pytest.approx(0.81)
    assert row["window_start"] == WINDOW.start
    assert row["window_end"] == WINDOW.end
    assert list(every["case_id"]) == ["nancon-k2e_5"]


def test_best_run_with_no_site(tmp_path: Path, caplog) -> None:
    project = make_project(tmp_path / "plain")
    seal_run(project, "alone", site=None, nse=0.6)

    with api.open(project) as proj:
        only = proj.best_runs("nse", label=None)
        with caplog.at_level(logging.WARNING):
            calibrated = proj.best_runs("nse")
        seal_run(project, "placed", nse=0.7)
        rebuild_index(project)
        both = proj.best_runs("nse", label=None)

    assert list(only["case_id"]) == ["alone"] and only["site"].isna().all()
    assert calibrated.empty and "no site" in caplog.text
    assert list(both["case_id"]) == ["placed", "alone"]
    assert both["nse"].tolist() == pytest.approx([0.7, 0.6])


def test_best_names_skipped_sites(tmp_path: Path, caplog) -> None:
    project = _campaign(tmp_path)
    api.open(project).plan()
    seal_run(project, "nancon-base", site="nancon", recipe="base", nse=None, window=None)
    seal_run(project, "couesnon-base", site="couesnon", recipe="base", nse=0.6)

    with api.open(project) as proj, caplog.at_level(logging.WARNING):
        every = proj.best_runs("nse", by="site", label=None)
        calibrated = proj.best_runs("nse", by="site")

    assert list(every["site"]) == ["couesnon"]
    assert calibrated.empty
    assert "no sealed run of nancon is scored: declare [metrics] window" in caplog.text
    assert (
        "no calibrated or evaluated run of couesnon is scored; label=None ranks every"
        in caplog.text
    )


def test_best_mixed_windows(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    _launched(project)
    other = DateWindow(start=date(2010, 1, 1), end=date(2014, 12, 31))
    seal_run(project, "nancon-base.v2", site="nancon", recipe="base", nse=0.9, window=other)

    with api.open(project) as proj:
        with pytest.raises(MixedWindowsError, match="different rules"):
            proj.best_runs("nse", by="site", label=None)
        assert len(proj.best_runs("nse", by="site", label=None, mixed_windows=True)) == 1


def test_runs_of_a_site(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    sim_ids = _launched(project)

    with api.open(project) as proj:
        runs = proj.runs(site="nancon")
        metrics = runs.metrics.set_index("sim_id")
        named = proj["nancon-base"]

    assert set(runs.sim_ids) == set(sim_ids.values())
    assert metrics.loc[sim_ids["k2e_5"], "nse"] == pytest.approx(0.81)
    assert metrics.loc[sim_ids["k2e_5"], "window_start"] == WINDOW.start
    assert named.sim_id == sim_ids["base"]
    assert named.site == "nancon"
    assert named.checks.budget_pct == pytest.approx(0.8)


def test_session(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    sim_ids = _launched(project)

    with api.open(project) as proj:
        assert list(proj.sessions) == ["nancon-k2e_5"]
        session = proj.sessions["nancon-k2e_5"]

    assert session.status == "completed"
    assert list(session.trials["trial"]) == [1, 2, 3]
    assert [phase.name for phase in session.phases] == ["steady_k"]
    assert session.config == {}
    assert session.best is not None
    assert session.best.sim_id == sim_ids["k2e_5"]
    assert session.best.label().label == "calibrated"


def test_workspace_runs_by_site(tmp_path: Path) -> None:
    project = _campaign(tmp_path)
    sim_ids = _launched(project)

    runs = api.open(tmp_path / "ws").runs(site="nancon")

    assert set(runs["sim_id"]) == set(sim_ids.values())


def test_launch_verbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hydromodpy.project.launch.local as launch
    import hydromodpy.project.launch.summary as summary

    project = _campaign(tmp_path)
    calls: dict[str, Any] = {}

    def run_plan(
        root: Path,
        *,
        parallel: int | None = None,
        prepare_parallel: int | None = None,
        only: tuple[str, ...] = (),
        site: str | None = None,
        until: str | None = None,
        fresh: bool = False,
        force: bool = False,
        resume: bool = False,
        environment_flags: tuple[str, ...] = (),
    ) -> str:
        # The signature is the real one, so a drift of the launcher's words fails here.
        calls["run"] = (
            root,
            {
                "parallel": parallel,
                "prepare_parallel": prepare_parallel,
                "only": only,
                "site": site,
                "until": until,
                "fresh": fresh,
                "force": force,
                "resume": resume,
                "environment_flags": environment_flags,
            },
        )
        return "launched"

    def collect_project(root: Path, **kwargs: Any) -> str:
        calls["collect"] = (root, kwargs)
        return "collected"

    monkeypatch.setattr(launch, "run_plan", run_plan)
    monkeypatch.setattr(summary, "collect_project", collect_project)

    with api.open(project) as proj:
        assert proj.launch(parallel=8, only="failed", site="nancon") == "launched"
        assert proj.collect(write_sites=True) == "collected"
        proj.plan()
        status = proj.status()

    root, kwargs = calls["run"]
    assert root == project.resolve()
    assert kwargs["parallel"] == 8
    assert kwargs["only"] == ("failed",)
    assert kwargs["site"] == "nancon"
    # No allowed host, no ceiling away from its default and no credentials file
    # beyond the default one: a case line stays what it was.
    assert kwargs["environment_flags"] == ()
    assert calls["collect"] == (project.resolve(), {"write_sites": True, "mixed_windows": False})
    assert {row.case_id for row in status.rows} == PLAN_CASES
    assert {row.status for row in status.rows} == {"planned"}
    document = json.loads(json.dumps(status.to_dict()))
    assert list(document) == ["plan_hash", "plan_stale", "counts", "cases"]
    assert document["counts"] == {"planned": len(PLAN_CASES)}
    assert {case["case_id"] for case in document["cases"]} == PLAN_CASES
    assert set(document["cases"][0]) == set(CASE_COLUMNS)
    assert document["cases"][0]["started_at"] == ""


def test_publish(tmp_path: Path) -> None:
    project = _campaign(tmp_path)

    with api.open(project) as proj:
        with pytest.raises(FileNotFoundError, match="collect"):
            proj.publish(tmp_path / "out")
        (project / "summary").mkdir()
        (project / "summary" / "README.md").write_text("# Summary\n", encoding="utf-8")
        copy = proj.publish(tmp_path / "out")

    assert (copy / "README.md").read_text(encoding="utf-8") == "# Summary\n"


def test_sites_project_has_no_config(tmp_path: Path) -> None:
    from hydromodpy.project.launch.plan import SitesProjectError

    project = _campaign(tmp_path)

    with api.open(project) as proj:
        with pytest.raises(SitesProjectError, match="proj.launch"):
            proj.config  # noqa: B018
