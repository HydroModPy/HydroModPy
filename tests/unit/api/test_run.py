"""The verb ``run``: one type per workflow, the controls by name, the changes in ``set=``."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.project import api
from hydromodpy.project.request import RunOutcome, request_of
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
    asked["indexed"] = []
    monkeypatch.setattr(
        "hydromodpy.results.catalog.indexer.index_after_run",
        lambda root: asked["indexed"].append(root),
    )
    return asked


def test_an_overview_gives_its_result(monkeypatch, tmp_path: Path) -> None:
    config = _toml(tmp_path, "overview")
    monkeypatch.setattr(
        f"{WORKFLOW}.run_overview", lambda request, *, base, environment=None: RESULT
    )

    assert api.run(config) is RESULT
    assert api.run(str(config)) is RESULT


@pytest.mark.parametrize("option", [{"name": "x"}, {"set": {"K": 1.0}}, {"until_step": "seal"}])
def test_an_overview_refuses_what_steers_a_simulation(tmp_path: Path, option: dict) -> None:
    with pytest.raises(ConfigError, match=next(iter(option))):
        api.run(_toml(tmp_path, "overview"), **option)


@pytest.mark.parametrize("from_a_file", [True, False])
def test_a_calibration_is_refused_and_points_to_its_verb(tmp_path: Path, from_a_file: bool) -> None:
    with pytest.raises(ConfigError, match=r"hmp\.calibrate"):
        if from_a_file:
            api.run(_toml(tmp_path, "calibration"))
        else:
            api.run(_document("calibration"), base=tmp_path)


def test_a_sites_project_is_refused_and_points_to_its_verb(tmp_path: Path) -> None:
    config = _toml(tmp_path, "simulation", '[sites]\ntable = "sites.csv"\n')
    with pytest.raises(ConfigError, match=r"\.launch\(\)"):
        api.run(config)


def test_a_window_that_keeps_nothing_still_gives_its_outcome(worker: dict, tmp_path: Path) -> None:
    """A directory was claimed: its outcome comes back, without an id, and nothing is indexed."""
    worker["outcome"] = _outcome(sim_id=None, status="partial")

    outcome = api.run(_toml(tmp_path, "simulation"), until_step="load_data")

    assert (outcome.sim_id, outcome.status) == (None, "partial")
    assert worker["indexed"] == []


def test_a_request_object_is_a_source_and_needs_a_base(worker: dict, tmp_path: Path) -> None:
    request = request_of(_document("simulation"), name="from_request")

    with pytest.raises(ConfigError, match="base"):
        api.run(request)
    outcome = api.run(request, base=tmp_path, force=True)

    assert outcome.name == "x"
    assert (worker["request"].name, worker["request"].force) == ("from_request", True)
    assert worker["base"] == tmp_path.resolve()


def test_a_change_is_never_a_loose_keyword(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="K"):
        api.run(_toml(tmp_path, "simulation"), K=1e-5)


def test_a_skipped_run_is_returned_and_said(
    worker: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    said: list[tuple] = []
    monkeypatch.setattr("hydromodpy.project.api.report_identical_run", lambda *a: said.append(a))
    worker["outcome"] = _outcome(identical_to="x")

    assert api.run(_toml(tmp_path, "simulation")).identical_to == "x"
    assert said == [("x", "sid")]


def test_a_request_that_asks_a_dry_run_gives_a_plan_with_its_own_options(
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

    draft = api.run(config, dry_run=True, name="x", until_step="load_data")

    assert isinstance(draft, PlanDraft)
    assert draft.steps == ("validate", "resolve", "build_geographic", "load_data")
    assert [(case.case_id, case.kind, case.done) for case in draft.cases] == [
        ("x", "simulation", False)
    ]
    assert draft.cases[0].config_hash
    assert draft.sites_config is None
