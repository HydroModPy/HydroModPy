"""``hmp.run``: one type per workflow, the controls by name, the changes in ``set=``."""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.project.request import RunOutcome
from hydromodpy.workflow.overview import OverviewResult

pytestmark = pytest.mark.fast

WORKFLOW = "hydromodpy.project.dispatch.workflow"
RESULT = OverviewResult(
    name="ov", run_dir=None, catchment_area_km2=1.0, report_paths=(), web_report=None
)


def _toml(tmp_path: Path, mode: str, extra: str = "") -> Path:
    path = tmp_path / f"{mode}.toml"
    path.write_text(f'[workflow]\nmode = "{mode}"\n{extra}', encoding="utf-8")
    return path


def _document(mode: str) -> dict:
    """A document in memory, which reaches the worker against a base."""
    return {"workflow": {"mode": mode}}


def _outcome(**fields) -> RunOutcome:
    """The outcome of a completed run, as the worker gives it back."""
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
    monkeypatch.setattr(f"{WORKFLOW}.completed_run_view", lambda outcome: ("run", outcome.name))
    return asked


def test_an_overview_gives_its_result(monkeypatch, tmp_path: Path) -> None:
    config = _toml(tmp_path, "overview")
    monkeypatch.setattr(
        f"{WORKFLOW}.run_overview", lambda request, *, base, environment=None: RESULT
    )

    assert hmp.run(config) is RESULT
    assert hmp.run(str(config)) is RESULT


@pytest.mark.parametrize("option", [{"name": "x"}, {"set": {"K": 1.0}}, {"until_step": "seal"}])
def test_an_overview_refuses_what_steers_a_simulation(tmp_path: Path, option: dict) -> None:
    with pytest.raises(hmp.ConfigError, match=next(iter(option))):
        hmp.run(_toml(tmp_path, "overview"), **option)


@pytest.mark.parametrize("from_a_file", [True, False])
def test_a_calibration_is_refused_and_points_to_its_verb(tmp_path: Path, from_a_file: bool) -> None:
    with pytest.raises(hmp.ConfigError, match=r"hmp\.calibrate"):
        if from_a_file:
            hmp.run(_toml(tmp_path, "calibration"))
        else:
            hmp.run(_document("calibration"), base=tmp_path)


def test_a_sites_project_is_refused_and_points_to_its_verb(tmp_path: Path) -> None:
    config = _toml(tmp_path, "simulation", '[sites]\ntable = "sites.csv"\n')
    with pytest.raises(hmp.ConfigError, match=r"\.launch\(\)"):
        hmp.run(config)


def test_a_simulation_gives_its_run_and_the_controls_reach_the_worker(
    worker: dict, tmp_path: Path
) -> None:
    config = _toml(tmp_path, "simulation")

    assert hmp.run(config, name="x", force=True, set={"K": 1e-5}) == ("run", "x")
    request = worker["request"]
    assert (request.form, Path(request.source)) == ("toml", config.resolve())
    assert worker["base"] == tmp_path.resolve()
    assert request.set == {"K": 1e-5}
    assert (request.name, request.force) == ("x", True)

    assert hmp.run(_document("simulation"), base=tmp_path, until_step="seal", headless=True) == (
        "run",
        "x",
    )
    request = worker["request"]
    assert (request.form, worker["base"]) == ("dict", tmp_path.resolve())
    assert (request.until_step, request.no_display) == ("seal", True)


def test_a_window_that_keeps_nothing_gives_nothing(worker: dict, tmp_path: Path) -> None:
    worker["outcome"] = None
    assert hmp.run(_toml(tmp_path, "simulation"), until_step="load_data") is None


def test_a_change_is_never_a_loose_keyword(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="K"):
        hmp.run(_toml(tmp_path, "simulation"), K=1e-5)


def test_a_skipped_run_is_returned_and_said(
    worker: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    said: list[tuple] = []
    monkeypatch.setattr("hydromodpy._api._report_identical_run", lambda *a: said.append(a))
    worker["outcome"] = _outcome(identical_to="x")

    assert hmp.run(_toml(tmp_path, "simulation")) == ("run", "x")
    assert said == [("x", "sid")]


@pytest.mark.parametrize("workflow", ["simulation", "overview"])
def test_a_dry_run_gives_a_plan_and_runs_nothing(
    workflow: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: dict = {}

    def fake(source, **kwargs):
        asked.update(source=source, **kwargs)
        return "draft"

    monkeypatch.setattr(f"{WORKFLOW}.draft_of_a_file_or_config", fake)
    config = _toml(tmp_path, workflow)

    assert hmp.run(config, dry_run=True, name="x") == "draft"
    assert asked["workflow"] == workflow
    assert asked["name"] == "x"


def test_a_dry_run_says_the_steps_of_its_window(tmp_path: Path) -> None:
    """One case, no table, the steps of the window and the identity of the run."""
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

    draft = hmp.run(config, dry_run=True, name="x", until_step="load_data")

    assert isinstance(draft, PlanDraft)
    assert draft.steps == ("validate", "resolve", "build_geographic", "load_data")
    assert [(case.case_id, case.kind, case.done) for case in draft.cases] == [
        ("x", "simulation", False)
    ]
    assert draft.cases[0].config_hash
    assert draft.sites_config is None
