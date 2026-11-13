"""The public verbs of ``hydromodpy.project.api``: ``open``, ``run``, ``doctor`` and ``show(what="report")``.

``open`` hands back what a path stands for. ``run`` takes one workflow type, the
controls by name and the changes in ``set=``. ``show`` of a session reads its
directory alone, never the index. Nothing here runs a solver.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError, NothingThereError
from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.project import api
from hydromodpy.project.accessors import Workspace
from hydromodpy.project.doctor import DoctorReport
from hydromodpy.project.facade import Project
from hydromodpy.project.request import RunOutcome, request_of
from hydromodpy.results.catalog.discovery import SimulationNotFoundError
from hydromodpy.results.errors import RunNotSealedError
from hydromodpy.workflow.overview import OverviewResult
from tests._helpers.sealed_runs import (
    make_project,
    seal_run,
    write_attempt,
    write_session_dir,
)

pytestmark = pytest.mark.fast

WORKFLOW = "hydromodpy.project.dispatch.workflow"
RESULT = OverviewResult(
    name="ov", run_dir=None, catchment_area_km2=1.0, report_paths=(), web_report=None
)


def test_doctor_report_keys() -> None:
    report = api.doctor()
    assert isinstance(report, DoctorReport)
    assert set(report.to_dict()) == {"python", "hydromodpy", "solvers", "optional"}


def test_open_a_project_from_a_file_or_a_folder(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    (project / "configs").mkdir()

    for where in (str(project), project / "project.toml", project / "configs"):
        proj = api.open(where)
        assert isinstance(proj, Project)
        assert proj.root == project.resolve()


def test_open_a_run_that_never_completed(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_attempt(project, "runs/broken", status="failed", error=("SolverError", "diverged"))

    with pytest.raises(RunNotSealedError, match="outcome.json"):
        api.open(project / "runs" / "broken")


def test_open_a_workspace(tmp_path: Path) -> None:
    make_project(tmp_path / "projects" / "demo")

    workspace = api.open(tmp_path)

    assert isinstance(workspace, Workspace)
    assert workspace.projects == ["demo"]
    assert isinstance(workspace["demo"], Project)


def test_workspace_runs_by_site_need_no_index(tmp_path: Path) -> None:
    first = make_project(tmp_path / "projects" / "a")
    second = make_project(tmp_path / "projects" / "b")
    seal_run(first, "one", site="nancon")
    seal_run(second, "two", site="nancon")
    seal_run(second, "three", site="couesnon")

    runs = api.open(tmp_path).runs(site="nancon")

    assert sorted(runs["name"]) == ["one", "two"]
    assert not catalog_path_for(first).exists()
    assert not catalog_path_for(second).exists()


OPEN_REFUSALS = [
    pytest.param("missing", "does not exist", id="no such path"),
    pytest.param("loose", "no project", id="folder without a project"),
]


@pytest.mark.parametrize(("name", "message"), OPEN_REFUSALS)
def test_open_refusals(tmp_path: Path, name: str, message: str) -> None:
    (tmp_path / "loose").mkdir()
    with pytest.raises(FileNotFoundError, match=message):
        api.open(tmp_path / name)


def test_open_a_folder_of_projects_names_them(tmp_path: Path) -> None:
    folder = (tmp_path / "studies").resolve()
    make_project(folder / "demo")
    make_project(folder / "group" / "other")
    with pytest.raises(FileNotFoundError, match="This folder holds projects") as caught:
        api.open(folder)
    message = str(caught.value)
    assert str(folder / "demo") in message
    assert str(folder / "group" / "other") in message


def _capture_render(monkeypatch) -> dict:
    captured: dict = {}

    def fake_render(session_dir: Path, **_options) -> Path:
        captured["session_dir"] = session_dir
        return session_dir / "report" / "index.html"

    monkeypatch.setattr("hydromodpy.project.report.report_session", fake_render)
    return captured


def test_report_name_is_not_read_in_the_cwd_project(monkeypatch, tmp_path: Path) -> None:
    # The library never looks for a project above the working directory.
    project = make_project(tmp_path / "p")
    write_session_dir(project, "new")
    (project / "configs").mkdir()
    monkeypatch.chdir(project / "configs")
    captured = _capture_render(monkeypatch)

    with pytest.raises(NothingThereError, match="workspace="):
        api.show("new", what="report")

    assert captured == {}
    assert api.show(project / "sessions" / "new", what="report").parent.name == "report"


def test_report_of_an_unknown_session(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_session_dir(project, "calibration")
    _capture_render(monkeypatch)

    with pytest.raises(SimulationNotFoundError, match="calibration"):
        api.show("nope", what="report", workspace=project)


WORKFLOW = "hydromodpy.project.dispatch.workflow"
RESULT = OverviewResult(
    name="ov", run_dir=None, catchment_area_km2=1.0, report_paths=(), web_report=None
)


def _toml(tmp_path: Path, mode: str, extra: str = "") -> Path:
    path = tmp_path / f"{mode}.toml"
    path.write_text(f'[workflow]\nmode = "{mode}"\n{extra}', encoding="utf-8")
    return path


def _document(mode: str) -> dict:
    return {"workflow": {"mode": mode}}


def _outcome(**fields) -> RunOutcome:
    given = {
        "name": "x",
        "run_dir": Path("/p/runs/x"),
        "sim_id": "sid",
        "request_id": "r" * 64,
        "status": "completed",
        "identical_to": None,
        "project_root": Path("/p"),
        **fields,
    }
    return RunOutcome(**given)


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stand in for the worker: record the request and the base, name one completed run."""
    asked: dict = {}

    def fake(request, *, base, environment=None, **kwargs):
        asked.update(request=request, base=base, kwargs=kwargs)
        return asked["outcome"] if "outcome" in asked else _outcome()

    monkeypatch.setattr(f"{WORKFLOW}.run_simulation", fake)
    asked["indexed"] = []
    monkeypatch.setattr(
        "hydromodpy.results.catalog.indexer.index_after_run",
        lambda root: asked["indexed"].append(root),
    )
    return asked


def test_overview_result(monkeypatch, tmp_path: Path) -> None:
    config = _toml(tmp_path, "overview")
    monkeypatch.setattr(
        f"{WORKFLOW}.run_overview", lambda request, *, base, environment=None: RESULT
    )

    assert api.run(config) is RESULT
    assert api.run(str(config)) is RESULT


@pytest.mark.parametrize("option", [{"name": "x"}, {"set": {"K": 1.0}}, {"until_step": "seal"}])
def test_overview_refusals(tmp_path: Path, option: dict) -> None:
    with pytest.raises(ConfigError, match=next(iter(option))):
        api.run(_toml(tmp_path, "overview"), **option)


@pytest.mark.parametrize("from_a_file", [True, False])
def test_calibration_points_to_its_verb(tmp_path: Path, from_a_file: bool) -> None:
    with pytest.raises(ConfigError, match=r"hmp\.calibrate"):
        if from_a_file:
            api.run(_toml(tmp_path, "calibration"))
        else:
            api.run(_document("calibration"), base=tmp_path)


def test_sites_project_points_to_launch(tmp_path: Path) -> None:
    config = _toml(tmp_path, "simulation", '[sites]\ntable = "sites.csv"\n')
    with pytest.raises(ConfigError, match=r"\.launch\(\)"):
        api.run(config)


def test_window_keeping_nothing(worker: dict, tmp_path: Path) -> None:
    # A directory was claimed: the outcome has no id and nothing is indexed.
    worker["outcome"] = _outcome(sim_id=None, status="partial")

    outcome = api.run(_toml(tmp_path, "simulation"), until_step="load_data")

    assert (outcome.sim_id, outcome.status) == (None, "partial")
    assert worker["indexed"] == []


def test_request_object_needs_a_base(worker: dict, tmp_path: Path) -> None:
    request = request_of(_document("simulation"), name="from_request")

    with pytest.raises(ConfigError, match="base"):
        api.run(request)
    outcome = api.run(request, base=tmp_path, force=True)

    assert outcome.name == "x"
    assert (worker["request"].name, worker["request"].force) == ("from_request", True)
    assert worker["base"] == tmp_path.resolve()


def test_change_is_never_a_keyword(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="K"):
        api.run(_toml(tmp_path, "simulation"), K=1e-5)


def test_skipped_run_is_said(worker: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    said: list[tuple] = []
    monkeypatch.setattr("hydromodpy.project.api.report_identical_run", lambda *a: said.append(a))
    worker["outcome"] = _outcome(identical_to="x")

    assert api.run(_toml(tmp_path, "simulation")).identical_to == "x"
    assert said == [("x", "sid")]


def test_dry_run_request_keeps_its_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker: dict
) -> None:
    asked: dict = {}

    def fake(source, **kwargs):
        asked.update(source=source, **kwargs)
        return "draft"

    monkeypatch.setattr(f"{WORKFLOW}.draft_of_a_file_or_config", fake)
    held = request_of(
        _document("simulation"),
        name="held",
        resume="case_w2",
        until_step="load_data",
        dry_run=True,
    )

    assert api.run(held, base=tmp_path) == "draft"
    assert (asked["name"], asked["resume"], asked["until_step"]) == (
        "held",
        "case_w2",
        "load_data",
    )
    path = tmp_path / "request.json"
    path.write_text(held.model_dump_json(by_alias=True), encoding="utf-8")
    assert api.run(path) == "draft"
    assert asked["source"] == path
    assert "request" not in worker


def test_dry_run_plan_of_a_window(tmp_path: Path) -> None:
    from hydromodpy.project.launch.plan import PlanDraft

    root = tmp_path / "p"
    root.mkdir()
    config = root / "project.toml"
    config.write_text(
        "[geographic]\n"
        'source_mode = "synthetic"\n'
        "[domain.depth_model]\n"
        'kind = "constant_thickness"\n'
        "thickness = 50.0\n"
        "[simulation.time]\n"
        'start_datetime = "2000-01-01"\n'
        'end_datetime = "2000-03-31"\n'
        'step_value = "1 month"\n'
        "[[simulation.process]]\n"
        'id = "flow_main"\n'
        'kind = "flow"\n'
        'solvers = ["modflow6"]\n',
        encoding="utf-8",
    )

    draft = api.run(config, dry_run=True, name="x", until_step="load_data")

    assert isinstance(draft, PlanDraft)
    assert draft.steps == ("validate", "resolve", "build_geographic", "load_data")
    assert [(case.case_id, case.kind, case.done) for case in draft.cases] == [
        ("x", "simulation", False)
    ]
    assert draft.cases[0].config_hash
    assert draft.sites_config is None
    assert draft.to_dict() == {"lines": [], "warnings": [], "errors": []}


def test_calibrate_reads_a_request_as_its_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}

    def held(source, base):
        seen["source"] = source
        return "config"

    def plan(target, **kwargs):
        seen["target"] = target
        return SimpleNamespace(phases=[{"name": "steady_k"}])

    monkeypatch.setattr(api, "held", held)
    monkeypatch.setattr("hydromodpy.project.calibrate.calibration_plan", plan)
    document = {"workflow": {"mode": "calibration"}, "simulation": {"name": "a"}}
    request = request_of(document, set={"simulation.name": "b"}, phase="steady_k", dry_run=True)

    assert api.calibrate(request, base=tmp_path).phases == [{"name": "steady_k"}]
    assert seen["source"]["simulation"] == {"name": "b"}
    assert seen["target"] == "config"
