"""The workflow dispatch routes a workflow name to its adapter and gives back sealed identical runs.

A plain ``hmp run`` that is identical to a completed run gives that run back, read from the
manifests under ``runs/`` (no index is opened). The run is told by its solution key, sealed as
``identity.config_hash``: the request, the digest and state of its inputs, the code, the solver
binaries and the numeric packages.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any

import pytest
from pydantic import BaseModel

import hydromodpy.project as project_pkg
from hydromodpy.core.exceptions import CalibrationError, ConfigError
from hydromodpy.core.state.result_dirs import run_dir_rel
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.project.dispatch import workflow as wf
from hydromodpy.project.request import RunRequest
from hydromodpy.results.manifest import ManifestConfig, ManifestRun
from hydromodpy.results.request_identity import request_id, solution_key
from tests._helpers.run_records import make_identity, make_record
from tests._helpers.sealed_runs import write_attempt

EDITION = "2.1"


class _FakeRunner:
    """Stands for ``ProjectRunner``: records what ``run_simulation`` asks of it."""

    def __init__(self, project: _FakeProject) -> None:
        self.project = project

    def execute(self, request: RunRequest, **kwargs: Any) -> Any:
        self.project.executed.append({"request": request, **kwargs})
        return _FakeProject.result


class _FakeProject:
    """Stands for ``Project``: records what ``run_simulation`` asks of it."""

    instances: list[_FakeProject] = []
    result: Any = None

    def __init__(
        self,
        config: Any,
        *,
        base: Any = None,
        document: Any = None,
        source: Any = None,
        no_display: bool = False,
        environment: Any = None,
    ) -> None:
        self.args = {"base": base, "document": document, "source": source}
        self.no_display = no_display
        self.environment = environment
        self._cfg = config
        self._runner = _FakeRunner(self)
        self.executed: list[dict[str, Any]] = []
        _FakeProject.instances.append(self)

    def __enter__(self) -> _FakeProject:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _cfg(root: Path, name: str | None = "case") -> SimpleNamespace:
    return SimpleNamespace(
        simulation=SimpleNamespace(name=name),
        workspace=SimpleNamespace(project_root=str(root)),
    )


def _request(**members: Any) -> RunRequest:
    return RunRequest(config={}, **{"form": "dict", **members})


@pytest.fixture
def fake_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> type[_FakeProject]:
    """A ``Project`` double, a loader that gives ``_cfg(tmp_path)`` and an unchecked environment."""
    _FakeProject.instances = []
    _FakeProject.result = SimpleNamespace(
        name="case",
        sim_id="s" * 32,
        run_dir=Path("/r/case"),
        status="completed",
        identical_to=None,
    )
    monkeypatch.setattr(project_pkg, "Project", _FakeProject)
    monkeypatch.setattr(wf, "_loaded", lambda request, base: _cfg(Path(base)))
    monkeypatch.setattr(wf, "_checked_environment", lambda environment, root: environment)
    return _FakeProject


@pytest.mark.parametrize("workflow", ["simulation", "overview", "calibration"])
def test_dispatch_workflow_routes_by_workflow_name(
    workflow: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, RunRequest, Path, dict[str, Any]]] = []
    for key in wf.DISPATCH:
        monkeypatch.setitem(
            wf.DISPATCH,
            key,
            lambda request, *, base, _key=key, **kw: (
                calls.append((_key, request, base, kw)) or _key
            ),
        )
    request = _request()
    assert wf.dispatch_workflow(workflow, request, base=tmp_path, force=True) == workflow
    assert calls == [(workflow, request, tmp_path, {"force": True})]


def test_dispatch_workflow_refuses_an_unknown_workflow(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="nonsense"):
        wf.dispatch_workflow("nonsense", _request(), base=tmp_path)


def test_the_dispatch_table_names_the_three_adapters() -> None:
    assert wf.DISPATCH == {
        "simulation": wf.run_simulation,
        "overview": wf.run_overview,
        "calibration": wf.run_calibration,
    }


def test_run_simulation_lets_a_plain_run_give_back_an_identical_one(
    fake_project: type[_FakeProject], tmp_path: Path
) -> None:
    """The attempt looks for the identical run once it has claimed: the call says it may."""
    outcome = wf.run_simulation(_request(), base=tmp_path)

    assert outcome is fake_project.result
    sent = fake_project.instances[0].executed[0]
    assert sent["skip_identical"] is True
    assert sent["frozen"] is False


@pytest.mark.parametrize("identical_to", [None, "case"], ids=["computed", "given back"])
def test_run_simulation_hands_on_the_mesh_summary_of_a_run_that_built_its_mesh(
    fake_project: type[_FakeProject],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    identical_to: str | None,
) -> None:
    """The summary lives in process memory only; a run given back computed nothing."""
    from hydromodpy.project.request import RunOutcome

    summary = {"engine": "gmsh", "product_key": "k1"}
    fake_project.result = RunOutcome(
        name="case",
        run_dir=tmp_path / "runs" / "case",
        sim_id="s" * 32,
        request_id="r" * 64,
        status="completed",
        identical_to=identical_to,
        project_root=tmp_path,
    )
    built = SimpleNamespace(
        setup=SimpleNamespace(mesh_summary=summary),
        execution=SimpleNamespace(
            simulation_plan=SimpleNamespace(runs=[SimpleNamespace(process_type="mesh")])
        ),
    )
    monkeypatch.setattr(_FakeProject, "_ctx", built, raising=False)

    outcome = wf.run_simulation(_request(), base=tmp_path)

    assert outcome.mesh_summary == (None if identical_to else summary)


def test_run_simulation_force_runs_despite_an_identical_sealed_run(
    fake_project: type[_FakeProject], tmp_path: Path
) -> None:
    wf.run_simulation(_request(force=True), base=tmp_path)

    sent = fake_project.instances[0].executed[0]
    assert sent["skip_identical"] is False
    assert sent["request"].force is True


@pytest.mark.parametrize(
    "members",
    [{"resume": "r1"}, {"from_step": "extract"}, {"until_step": "run_solver"}],
    ids=["resume", "from_step", "until_step"],
)
def test_run_simulation_partial_runs_never_look_for_an_identical_run(
    members: dict[str, str], fake_project: type[_FakeProject], tmp_path: Path
) -> None:
    wf.run_simulation(_request(**members), base=tmp_path)

    assert fake_project.instances[0].executed[0]["skip_identical"] is False


def test_run_simulation_never_skips_a_run_that_has_no_name(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wf, "_loaded", lambda request, base: _cfg(Path(base), name=None))

    wf.run_simulation(_request(), base=tmp_path)

    assert fake_project.instances[0].executed[0]["skip_identical"] is False


def test_run_simulation_hands_the_request_the_base_and_the_blocks_of_a_promotion(
    fake_project: type[_FakeProject], tmp_path: Path
) -> None:
    request = _request(name="mine", fresh=True, set={"flow.x": 2})
    lineage, calibrated_by = object(), object()

    outcome = wf.run_simulation(
        request, base=tmp_path, lineage=lineage, calibrated_by=calibrated_by
    )

    project = fake_project.instances[0]
    sent = project.executed[0]
    assert sent["request"] is request
    assert (sent["lineage"], sent["calibrated_by"]) == (lineage, calibrated_by)
    assert project.args["base"] == tmp_path.resolve()
    assert outcome.status == "completed"
    assert outcome.run_dir == Path("/r/case")


def test_run_simulation_refuses_a_run_name_that_breaks_the_rule_before_any_project(
    fake_project: type[_FakeProject], tmp_path: Path
) -> None:
    request = RunRequest.model_construct(
        config={}, name="Two Words", resume=None, set={}, overlays=(), form="dict"
    )
    with pytest.raises(ConfigError, match="two_words"):
        wf.run_simulation(request, base=tmp_path)
    assert fake_project.instances == []


def test_run_simulation_names_the_run_after_the_file_the_document_came_from(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A document with no name takes the stem of its file from the loader, and the source reaches it."""
    seen: list[Any] = []
    monkeypatch.setattr(
        wf,
        "_loaded",
        lambda request, base: seen.append(wf._source_path(request, Path(base))) or _cfg(base),
    )

    wf.run_simulation(_request(source="site_a.toml", form="toml"), base=tmp_path)

    assert seen == [tmp_path.resolve() / "site_a.toml"]
    assert fake_project.instances[0].args["source"] == tmp_path.resolve() / "site_a.toml"


def test_a_bare_resume_continues_the_run_the_request_names(
    fake_project: type[_FakeProject], tmp_path: Path
) -> None:
    """The name comes from ``[simulation] name``, which a file folds from its stem."""
    wf.run_simulation(_request(resume=""), base=tmp_path)

    (project,) = fake_project.instances
    (executed,) = project.executed
    assert executed["request"].resume == "case"


def test_a_bare_resume_of_a_request_that_names_no_run_is_refused(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wf, "_loaded", lambda request, base: _cfg(Path(base), name=None))

    with pytest.raises(ConfigError, match="names none"):
        wf.run_simulation(_request(resume=""), base=tmp_path)
    assert fake_project.instances == []


def test_run_simulation_returns_nothing_when_no_run_was_made(
    fake_project: type[_FakeProject], tmp_path: Path
) -> None:
    fake_project.result = None
    assert wf.run_simulation(_request(), base=tmp_path) is None


def test_run_simulation_checks_then_warns_about_a_replayed_run(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.workflow.replay_checks as rc

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        rc, "check_replay", lambda cfg, src, *, project_root, inputs_checked: seen.update(c=src)
    )
    monkeypatch.setattr(rc, "warn_replay_differences", lambda src, run: seen.update(w=(src, run)))
    published = tmp_path / "copy"

    wf.run_simulation(_request(), base=tmp_path, replay_of=published)

    assert seen["c"] == published
    assert seen["w"] == (published, Path("/r/case"))
    sent = fake_project.instances[0].executed[0]
    assert sent["frozen"] is False
    assert sent["skip_identical"] is False


def test_a_replay_that_was_given_back_as_identical_is_not_compared_to_its_source(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.workflow.replay_checks as rc

    monkeypatch.setattr(rc, "check_replay", lambda *a, **k: None)
    monkeypatch.setattr(
        rc, "warn_replay_differences", lambda *a: pytest.fail("nothing ran, nothing differs")
    )
    fake_project.result = SimpleNamespace(
        name="case", sim_id="s", run_dir=Path("/r/case"), status="completed", identical_to="case"
    )

    wf.run_simulation(_request(), base=tmp_path, replay_of=tmp_path / "copy")


def test_a_frozen_replay_of_a_completed_run_is_never_skipped_as_identical(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.workflow.replay_checks as rc

    sealed = tmp_path / "runs" / "case"
    monkeypatch.setattr(rc, "sealed_run_of", lambda path: sealed)
    monkeypatch.setattr(rc, "check_replay", lambda cfg, src, *, project_root, inputs_checked: None)
    monkeypatch.setattr(rc, "warn_replay_differences", lambda src, run: None)

    wf.run_simulation(
        _request(frozen=True, source="runs/case/config.toml", form="toml"), base=tmp_path
    )

    sent = fake_project.instances[0].executed[0]
    assert (sent["frozen"], sent["skip_identical"], sent["request"].force) == (False, False, False)


def test_a_frozen_run_with_no_record_to_replay_may_still_be_given_back_as_identical(
    fake_project: type[_FakeProject], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.workflow.replay_checks as rc

    monkeypatch.setattr(rc, "sealed_run_of", lambda path: None)

    wf.run_simulation(_request(frozen=True, source="case.toml", form="toml"), base=tmp_path)

    sent = fake_project.instances[0].executed[0]
    assert (sent["frozen"], sent["skip_identical"]) == (True, True)


def test_checked_replay_source_is_none_without_a_sealed_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.workflow.replay_checks as rc

    monkeypatch.setattr(rc, "sealed_run_of", lambda path: None)
    assert wf.checked_replay_source(object(), tmp_path / "a.toml", None, tmp_path) is None
    assert wf.checked_replay_source(object(), None, None, tmp_path) is None


def test_mesh_summary_is_given_only_when_the_plan_runs_a_mesh_process() -> None:
    def project(process_types: list[str], summary: Any) -> SimpleNamespace:
        runs = [SimpleNamespace(process_type=p) for p in process_types]
        ctx = SimpleNamespace(
            setup=SimpleNamespace(mesh_summary=summary),
            execution=SimpleNamespace(simulation_plan=SimpleNamespace(runs=runs)),
        )
        return SimpleNamespace(_ctx=ctx)

    assert wf.mesh_summary_of(project(["mesh", "flow"], {"cells": 4})) == {"cells": 4}
    assert wf.mesh_summary_of(project(["flow"], {"cells": 4})) == {}
    assert wf.mesh_summary_of(project(["mesh"], "not a mapping")) == {}
    assert wf.mesh_summary_of(SimpleNamespace()) == {}


def test_identical_run_message_falls_back_to_the_short_id() -> None:
    assert wf.identical_run_message("base", "abcdef123456") == (
        "Config identical to completed run 'base' [abcdef12]; nothing to do."
    )
    assert "'abcdef12' [abcdef12]" in wf.identical_run_message(None, "abcdef123456")


def test_completed_identical_run_is_none_without_a_runs_directory(tmp_path: Path) -> None:
    assert wf.completed_identical_run(tmp_path, "case", "K") is None


def test_completed_identical_run_is_none_without_a_key(tmp_path: Path) -> None:
    (tmp_path / "runs" / "case").mkdir(parents=True)
    assert wf.completed_identical_run(tmp_path, "case", None) is None


def test_completed_run_view_indexes_then_reads_the_run_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.project.runner as runner
    import hydromodpy.results.catalog.indexer as indexer

    order: list[Any] = []
    monkeypatch.setattr(indexer, "index_new_runs", lambda root: order.append(("index", root)))
    monkeypatch.setattr(
        runner,
        "run_view_of",
        lambda run_dir, *, project_root, sim_id: order.append(("view", run_dir, sim_id)) or "V",
    )
    outcome = SimpleNamespace(
        project_root=tmp_path, run_dir=tmp_path / "runs" / "case", sim_id="sid"
    )
    assert wf.completed_run_view(outcome) == "V"
    assert order[0] == ("index", tmp_path)
    assert order[1][0] == "view"
    assert order[1][1].name == "case"
    assert order[1][2] == "sid"


def _phases_loader(monkeypatch: pytest.MonkeyPatch, names: list[str] | Exception) -> None:
    import hydromodpy.calibration.runners.document as document

    def load(path: Path) -> tuple[Any, dict]:
        if isinstance(names, Exception):
            raise names
        return SimpleNamespace(phases=[SimpleNamespace(name=n) for n in names]), {}

    monkeypatch.setattr(document, "load_toml_calibration", load)


def test_declared_phases_are_listed_and_an_unreadable_file_declares_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _phases_loader(monkeypatch, ["warm", "fine"])
    assert wf.declared_calibration_phases("c.toml") == ["warm", "fine"]
    _phases_loader(monkeypatch, ValueError("bad"))
    assert wf.declared_calibration_phases("c.toml") == []


def test_calibration_phases_or_raise_reports_an_unreadable_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _phases_loader(monkeypatch, ["warm"])
    assert wf.calibration_phases_or_raise("c.toml") == ["warm"]
    _phases_loader(monkeypatch, ValueError("bad"))
    with pytest.raises(ConfigError, match="cannot be read: bad"):
        wf.calibration_phases_or_raise("c.toml")


def test_no_such_phase_names_the_source_and_the_phase() -> None:
    message = wf.no_such_phase("c.toml", "fine")
    assert "c.toml" in message
    assert "'fine'" in message


@pytest.fixture
def calibration_runners(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import hydromodpy.calibration.preflight as preflight
    import hydromodpy.calibration.runners.cli_runner as cli
    import hydromodpy.calibration.runners.staged_runner as staged

    called: list[str] = []
    monkeypatch.setattr(preflight, "preflight_launch", lambda target: called.append("preflight"))
    monkeypatch.setattr(
        staged,
        "run_staged_calibration",
        lambda target, *, phase, bounds, **kw: (
            called.append(f"staged:{phase}") or SimpleNamespace(to_dict=lambda: {"kind": "staged"})
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_calibration_cli",
        lambda target, *, bounds, **kw: (
            called.append("flat") or SimpleNamespace(to_dict=lambda: {"kind": "flat"})
        ),
    )
    monkeypatch.setattr(
        wf, "_checked_environment", lambda environment, root: SimpleNamespace(bounds=None)
    )
    monkeypatch.setattr(wf, "_completed_session", lambda target: None)
    return called


def _file_request(**members: Any) -> RunRequest:
    return RunRequest(config={}, form="toml", source="c.toml", **members)


def test_run_calibration_routes_a_phased_file_to_the_staged_runner(
    monkeypatch: pytest.MonkeyPatch, calibration_runners: list[str], tmp_path: Path
) -> None:
    _phases_loader(monkeypatch, ["warm"])
    assert wf.run_calibration(_file_request(phase="warm"), base=tmp_path) == {"kind": "staged"}
    assert calibration_runners == ["preflight", "staged:warm"]


def test_run_calibration_routes_a_flat_file_to_the_single_runner(
    monkeypatch: pytest.MonkeyPatch, calibration_runners: list[str], tmp_path: Path
) -> None:
    _phases_loader(monkeypatch, [])
    assert wf.run_calibration(_file_request(), base=tmp_path) == {"kind": "flat"}
    assert calibration_runners == ["preflight", "flat"]


def test_run_calibration_refuses_a_phase_a_flat_file_does_not_declare(
    monkeypatch: pytest.MonkeyPatch, calibration_runners: list[str], tmp_path: Path
) -> None:
    _phases_loader(monkeypatch, [])
    with pytest.raises(CalibrationError, match="no phase 'warm'"):
        wf.run_calibration(_file_request(phase="warm"), base=tmp_path)


def test_run_calibration_gives_back_the_completed_session_of_the_same_key(
    monkeypatch: pytest.MonkeyPatch, calibration_runners: list[str], tmp_path: Path
) -> None:
    _phases_loader(monkeypatch, [])
    answer = {"skipped": True, "name": "c", "sim_id": "sid"}
    monkeypatch.setattr(wf, "_completed_session", lambda target: answer)

    assert wf.run_calibration(_file_request(), base=tmp_path) == answer
    assert calibration_runners == ["preflight"]


@pytest.mark.parametrize(
    "members",
    [{"force": True}, {"resume": ""}, {"phase": "warm"}],
    ids=["force", "resume", "one-phase"],
)
def test_run_calibration_searches_again_when_it_is_forced_resumed_or_partial(
    members: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    calibration_runners: list[str],
    tmp_path: Path,
) -> None:
    _phases_loader(monkeypatch, ["warm"])
    monkeypatch.setattr(wf, "_completed_session", lambda target: {"skipped": True})

    result = wf.run_calibration(_file_request(**members), base=tmp_path)

    assert result == {"kind": "staged"}


def test_a_calibration_whose_request_names_its_case_runs_held_in_memory(
    monkeypatch: pytest.MonkeyPatch, calibration_runners: list[str], tmp_path: Path
) -> None:
    """``--case`` alone names the session, as it did through a copy named by the case."""
    named: list[str | None] = []
    monkeypatch.setattr(
        wf,
        "_calibrate_in_memory",
        lambda request, base, environment: named.append(request.name) or {"kind": "memory"},
    )

    assert wf.run_calibration(_file_request(name="other"), base=tmp_path) == {"kind": "memory"}
    assert named == ["other"]
    assert calibration_runners == []


def test_a_calibration_held_in_memory_names_its_case_and_forwards_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.project as project_package

    asked: dict[str, Any] = {}

    class _Project:
        def __init__(self, cfg, **kwargs) -> None:
            asked["source"] = kwargs["source"]

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

        def calibrate(self, **options):
            asked["options"] = options
            return SimpleNamespace(to_dict=lambda: {"kind": "memory"})

    monkeypatch.setattr(
        wf,
        "_loaded",
        lambda request, base: SimpleNamespace(workspace=SimpleNamespace(project_root=str(base))),
    )
    monkeypatch.setattr(
        "hydromodpy.project.run_overrides.override_changes", lambda cfg, changes: {}
    )
    monkeypatch.setattr(project_package, "Project", _Project)
    request = _file_request(name="other", force=True)

    assert wf._calibrate_in_memory(request, tmp_path, None) == {"kind": "memory"}
    assert asked["source"] is None, "a case the request names runs without its file"
    assert asked["options"] == {
        "phase": None,
        "resume": False,
        "workspace": tmp_path,
        "force": True,
        "case": "other",
    }


_PHASED_CALIBRATION = """\
[workflow]
mode = "calibration"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[geographic]
source_mode = "synthetic"

[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/s"
value = 6.4e-5

[calibration]
method = "grid"
max_trials = 4
method_options = { points_per_dim = 4 }

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
path = "flow.param.K.field.value"

[[calibration.phases]]
name = "warm"
parameters = ["K"]
"""


@pytest.fixture
def staged_session(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The staged runner a held calibration reaches, recording the document it is handed."""
    import hydromodpy.calibration.preflight as preflight
    import hydromodpy.calibration.runners.staged_runner as staged

    seen: dict[str, Any] = {}

    def run_staged(document: Path, **options: Any) -> SimpleNamespace:
        seen["document"] = Path(document)
        seen["options"] = options
        return SimpleNamespace(to_dict=lambda: {"kind": "staged"})

    monkeypatch.setattr(preflight, "preflight_launch", lambda *args, **kwargs: None)
    monkeypatch.setattr(staged, "run_staged_calibration", run_staged)
    return seen


def test_a_phased_file_with_changes_hands_its_session_the_changed_document(
    tmp_path: Path, staged_session: dict[str, Any]
) -> None:
    """The session freezes the value of ``--set``, under the case of the file, in its project."""
    import tomllib

    from hydromodpy.project.request import request_of

    (tmp_path / "project.toml").write_text("", encoding="utf-8")
    source = tmp_path / "Calib File.toml"
    source.write_text(_PHASED_CALIBRATION, encoding="utf-8")
    request = request_of(source, base=tmp_path, set={"flow.param.K.field.value": 3e-5})

    assert wf.run_calibration(request, base=tmp_path) == {"kind": "staged"}

    document = staged_session["document"]
    frozen = tomllib.loads(document.read_text(encoding="utf-8"))
    assert frozen["flow"]["param"]["K"]["field"]["value"] == 3e-5
    assert document == tmp_path.resolve() / "sessions" / "calib_file.toml"


def test_a_calibration_request_in_json_never_reads_its_file_as_toml(
    tmp_path: Path, staged_session: dict[str, Any]
) -> None:
    """``hmp run calib.json --base .`` runs the document the request carries."""
    import json
    import tomllib

    from hydromodpy.project.request import REQUEST_SCHEMA, request_of

    (tmp_path / "project.toml").write_text("", encoding="utf-8")
    source = tmp_path / "calib.json"
    document = tomllib.loads(_PHASED_CALIBRATION)
    source.write_text(json.dumps({"schema": REQUEST_SCHEMA, "config": document}), "utf-8")
    request = request_of(source, base=tmp_path)

    assert wf.run_calibration(request, base=tmp_path) == {"kind": "staged"}
    assert staged_session["document"].parent == tmp_path.resolve() / "sessions"


def test_a_calibration_with_changes_runs_as_a_project_held_in_memory(
    monkeypatch: pytest.MonkeyPatch, calibration_runners: list[str], tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        wf,
        "_calibrate_in_memory",
        lambda request, base, environment: (
            seen.update(set=request.set, base=base) or {"kind": "memory"}
        ),
    )

    assert wf.run_calibration(_file_request(set={"flow.x": 1}), base=tmp_path) == {"kind": "memory"}
    assert seen == {"set": {"flow.x": 1}, "base": tmp_path.resolve()}
    assert calibration_runners == []


def _draft_collaborators(monkeypatch: pytest.MonkeyPatch, *, is_sites: bool) -> list[Any]:
    import hydromodpy.config.sites as sites
    import hydromodpy.project.launch.sites.expansion as expansion
    import hydromodpy.workflow.dispatch as wdispatch

    seen: list[Any] = []
    monkeypatch.setattr(wdispatch, "load_raw_toml", lambda path: {"raw": str(path)})
    monkeypatch.setattr(sites, "is_sites_project", lambda raw: is_sites)
    monkeypatch.setattr(
        expansion,
        "expand_plan",
        lambda root, path, *, set_overrides: seen.append(("plan", path, set_overrides)) or "PLAN",
    )
    monkeypatch.setattr(
        expansion,
        "single_case_draft",
        lambda cfg, **kw: seen.append(("single", cfg, kw)) or "ONE",
    )
    return seen


def test_a_sites_file_drafts_every_case_of_its_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _draft_collaborators(monkeypatch, is_sites=True)
    path = tmp_path / "sites.toml"
    draft = wf.draft_of_a_file_or_config(
        path, workflow="simulation", set_changes={"flow.recharge": 2}
    )
    assert draft == "PLAN"
    assert seen == [("plan", path, {"flow": {"recharge": 2}})]


def test_an_overview_configuration_drafts_one_case_without_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hydromodpy.display.overview as display_overview

    seen = _draft_collaborators(monkeypatch, is_sites=False)
    monkeypatch.setattr(display_overview, "overview_name", lambda site, name: f"{site}/{name}")
    cfg = SimpleNamespace(site=SimpleNamespace(name="alpha"), overview=SimpleNamespace(name="ov"))
    assert wf.draft_of_a_file_or_config(cfg, workflow="overview") == "ONE"
    _kind, got_cfg, kwargs = seen[0]
    assert got_cfg is cfg
    assert kwargs == {
        "name": "alpha/ov",
        "config_path": None,
        "steps": (),
        "kind": "overview",
    }


def test_run_overview_hands_the_bounds_of_the_call_to_its_launcher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``run_overview`` builds its launcher once, with the bounds and the base of the call."""
    from hydromodpy.core.runtime.bounds import Bounds
    from hydromodpy.project.environment import Environment
    from hydromodpy.workflow import overview as overview_module

    seen: dict[str, Any] = {}

    class _Spy:
        def __init__(self, cfg: Any, *, base: Any, source: Any = None, bounds: Any = None) -> None:
            seen.update(cfg=cfg, base=base, source=source, bounds=bounds)
            raise ConfigError("captured")

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(overview_module, "DataOverviewLauncher", _Spy)
    monkeypatch.setattr(wf, "_loaded", lambda request, base: cfg)
    monkeypatch.setattr(wf, "_checked_environment", lambda environment, root: environment)
    environment = Environment(bounds=Bounds(allowed_hosts=frozenset({"data.geopf.fr"})))

    with pytest.raises(ConfigError):
        wf.run_overview(
            _request(source="overview.toml", form="toml"), base=tmp_path, environment=environment
        )

    assert seen["cfg"] is cfg
    assert seen["base"] == tmp_path.resolve()
    assert seen["source"] == tmp_path.resolve() / "overview.toml"
    assert seen["bounds"] == environment.bounds


_OVERVIEW = """\
[site]
name = "nancon"

[workflow]
mode = "overview"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[overview]
name = "identity card"
"""


def test_run_overview_applies_the_set_of_its_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``hmp run overview.toml --set overview.name=...`` reaches the overview."""
    from hydromodpy.project.request import request_of
    from hydromodpy.workflow import overview as overview_module

    seen: dict[str, Any] = {}

    class _Spy:
        def __init__(self, cfg: Any, **kwargs: Any) -> None:
            seen["name"] = cfg.overview.name
            raise ConfigError("captured")

    (tmp_path / "project.toml").write_text("", encoding="utf-8")
    source = tmp_path / "overview.toml"
    source.write_text(_OVERVIEW, encoding="utf-8")
    monkeypatch.setattr(overview_module, "DataOverviewLauncher", _Spy)
    request = request_of(source, base=tmp_path, set={"overview.name": "winter card"})

    with pytest.raises(ConfigError, match="captured"):
        wf.run_overview(request, base=tmp_path)

    assert seen["name"] == "winter card"


def test_a_simulation_configuration_drafts_through_a_dry_run_of_the_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _draft_collaborators(monkeypatch, is_sites=False)
    seen: dict[str, Any] = {}

    class _Dry(_FakeProject):
        def simulate(self, **kwargs: Any) -> str:
            seen.update(kwargs)
            return "DRY"

    monkeypatch.setattr(project_pkg, "Project", _Dry)
    cfg = SimpleNamespace()
    draft = wf.draft_of_a_file_or_config(
        cfg, workflow="simulation", set_changes={"a": 1}, name="n", from_step="extract"
    )
    assert _Dry.instances[-1].args["base"] is None
    assert draft == "DRY"
    assert seen == {
        "dry_run": True,
        "set": {"a": 1},
        "name": "n",
        "resume": None,
        "from_step": "extract",
        "until_step": None,
    }


def test_completed_identical_run_answers_with_the_newest_sealed_version_of_the_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hydromodpy.results.storage.sealing as sealing
    import hydromodpy.workflow.replay_checks as replay_checks

    runs = tmp_path / "runs"
    for name in ("case", "case.v2", "case.v3", "other"):
        (runs / name).mkdir(parents=True)
    (runs / "stray.txt").write_text("x", encoding="utf-8")
    sealed = {"case": "H", "case.v2": "H", "case.v3": "unsealed-or-other", "other": "H"}
    monkeypatch.setattr(sealing, "sealed_config_hash", lambda run_dir: sealed[run_dir.name])
    monkeypatch.setattr(replay_checks, "api_inputs_intact", lambda run_dir, root: True)

    assert wf.completed_identical_run(tmp_path, "case", "H") == runs / "case.v2"
    sealed["case.v2"] = sealed["case"] = "different"
    assert wf.completed_identical_run(tmp_path, "case", "H") is None
    assert wf.completed_identical_run(tmp_path, "case", None) is None


def test_a_run_whose_api_file_left_the_cache_is_not_given_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The request holds the declaration of such a file, so the guard reads its bytes."""
    import hydromodpy.results.storage.sealing as sealing
    import hydromodpy.workflow.replay_checks as replay_checks

    (tmp_path / "runs" / "case").mkdir(parents=True)
    monkeypatch.setattr(sealing, "sealed_config_hash", lambda run_dir: "K")
    monkeypatch.setattr(replay_checks, "api_inputs_intact", lambda run_dir, root: False)

    assert wf.completed_identical_run(tmp_path, "case", "K") is None


def _key(config: dict, **resolved: list[str | None]) -> str:
    """The solution key of a document whose inputs are *resolved*, with the code held still."""
    request = request_id(config, resolved, edition=EDITION)
    return solution_key(
        request,
        mesh_engine={"engine": "triangle", "version": "1"},
        binaries={},
        code={},
        packages={},
    )


def _seal(root: Path, key: str, *, name: str = "demo") -> str:
    """Seal a run under ``runs/<name>`` with the solution key *key*, and return its ``sim_id``."""
    sid = str(uuid.uuid4())
    stem = name.split(".v")[0]
    version = int(name.rsplit(".v", 1)[1]) if ".v" in name else 1
    base = make_record()
    record = base.model_copy(
        update={
            "run": ManifestRun(
                sim_id=sid,
                name=name,
                name_stem=stem,
                version=version,
                status="completed",
                project="p",
                case_id=stem,
                rel_dir=run_dir_rel(name),
                attempt=1,
                attempt_id="a" * 32,
                solver="modflow6",
                created_at=base.run.created_at,
            ),
            "site": None,
            "config": ManifestConfig(file="config.toml", hash=key, source="project.toml"),
            "identity": make_identity(
                site=None,
                site_fingerprint=None,
                case_id=stem,
                sim_id=sid,
                attempt_id="a" * 32,
                config_hash=key,
                mesh_hash=None,
            ),
            "geometry": base.geometry.model_copy(update={"mesh_hash": None}),
            "provenance": base.provenance.model_copy(update={"sim_id": sid}),
            "inputs": [],
        }
    )
    run_dir = root / "runs" / name
    run_dir.mkdir(parents=True)
    (run_dir / "config.toml").write_text("[flow]\n", encoding="utf-8")
    record.write(run_dir)
    return sid


def _config(sy: float = 0.001, scratch: str = "/p/.hmp/scratch/demo.p111") -> dict:
    return {
        "flow": {"sy": sy},
        "simulation": {"name": "demo"},
        "workspace": {"project_root": "/p", "solver_scratch_folder": scratch},
    }


def test_identical_request_matches_and_change_discriminates(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seal(root, _key(_config()))

    assert wf.completed_identical_run(root, "demo", _key(_config())) == root / "runs" / "demo"

    # Any changed parameter flips the key, so the run is not a duplicate.
    assert wf.completed_identical_run(root, "demo", _key(_config(sy=0.01))) is None


def test_the_scratch_folder_of_the_process_does_not_count(tmp_path: Path) -> None:
    """Two processes name two scratch folders; the run is the same run."""
    root = tmp_path / "ws"
    _seal(root, _key(_config(scratch="/p/.hmp/scratch/demo.p111")))

    other_process = _config(scratch="/p/.hmp/scratch")
    assert wf.completed_identical_run(root, "demo", _key(other_process)) is not None


def test_a_version_of_the_name_answers_too(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seal(root, _key(_config(sy=0.5)), name="demo")
    _seal(root, _key(_config()), name="demo.v2")

    assert wf.completed_identical_run(root, "demo", _key(_config())) == root / "runs" / "demo.v2"


def test_another_name_is_another_run(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seal(root, _key(_config()))
    assert wf.completed_identical_run(root, "other", _key(_config())) is None


def test_an_unsealed_directory_never_matches(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    write_attempt(root, "runs/demo", status="failed")
    write_attempt(root, "runs/demo.v2", status="running")
    assert wf.completed_identical_run(root, "demo", _key(_config())) is None


def test_an_unreadable_manifest_never_matches_and_never_blocks(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    broken = root / "runs" / "demo"
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    assert wf.completed_identical_run(root, "demo", _key(_config())) is None


def test_the_newest_version_answers_first(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    _seal(root, _key(_config()), name="demo")
    _seal(root, _key(_config()), name="demo.v3")
    _seal(root, _key(_config(sy=0.5)), name="demo.v2")

    assert wf.completed_identical_run(root, "demo", _key(_config())) == root / "runs" / "demo.v3"


def test_a_project_without_runs_matches_nothing(tmp_path: Path) -> None:
    assert wf.completed_identical_run(tmp_path / "absent", "demo", _key(_config())) is None


def test_the_request_id_does_not_read_the_name() -> None:
    import copy

    config = _config()
    base = request_id(config, {}, edition=EDITION)
    assert base == request_id(copy.deepcopy(config), {}, edition=EDITION)
    # The name lives in its own column, so a rename does not leave it stale.
    renamed = copy.deepcopy(config)
    renamed["simulation"]["name"] = "demo_k"
    assert base == request_id(renamed, {}, edition=EDITION)
    # The caller's dict is not touched.
    assert config["workspace"]["solver_scratch_folder"].endswith("demo.p111")
    assert config["simulation"]["name"] == "demo"


def test_the_code_that_computes_enters_the_key_and_the_release_does_not(monkeypatch) -> None:
    request = request_id(_config(), {}, edition=EDITION)
    engine = {"engine": "triangle", "version": "1"}

    def key() -> str:
        return solution_key(request, mesh_engine=engine, binaries={}, packages={})

    base = key()
    monkeypatch.setattr("hydromodpy.core.version.__version__", "0.0.0+other")
    assert key() == base
    monkeypatch.setattr(
        "hydromodpy.core.code_fingerprint.code_fingerprint", lambda _layers: {"solver": "edited"}
    )
    assert key() != base


def test_a_key_written_at_its_default_is_another_request(tmp_path: Path) -> None:
    """A validator can tell the two apart, so the request does (``surface_offset`` of an ETP)."""
    from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.workspace.config import WorkspaceConfig
    from hydromodpy.data.loading.inputs import ResolvedInputs
    from hydromodpy.workflow.solution_key import request_id_of

    def config(**solver: float) -> HydroModPyConfig:
        return HydroModPyConfig(
            workflow={"mode": "simulation"},
            workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
            geographic=GeographicConfig(source_mode="synthetic"),
            solver=solver,
        )

    def asked(cfg: HydroModPyConfig) -> str:
        return request_id_of(cfg, ResolvedInputs(), search=False)

    silent = asked(config())
    assert asked(config()) == silent
    assert asked(config(drain_bed_thickness_m=1.0)) != silent
    assert asked(config(drain_bed_thickness_m=2.0)) != silent


class _Workspace(BaseModel):
    project_root: str


class _ForcedConfig(BaseModel):
    """The smallest configuration that names a forcing file."""

    workspace: _Workspace
    simulation: dict
    recharge: Annotated[Path | None, InputFile(role="recharge", category="data")] = None


def _forced_project(tmp_path: Path) -> _ForcedConfig:
    root = tmp_path / "ws"
    forcing = root / "data" / "recharge.csv"
    forcing.parent.mkdir(parents=True)
    forcing.write_text("date,value\n2020-01-01,1.0\n")
    return _ForcedConfig(
        workspace=_Workspace(project_root=str(root)),
        simulation={"name": "demo"},
        recharge=Path("data/recharge.csv"),
    )


def _forced_key(config: BaseModel) -> str:
    """The key the pipeline records for *config*, the files it names read as they are."""
    from hydromodpy.data.loading.inputs import ResolvedInputs
    from hydromodpy.workflow.solution_key import input_digests

    document = config.model_dump(mode="json")
    digests = input_digests(config, ResolvedInputs())
    request = request_id(document, digests, edition=EDITION)
    return solution_key(
        request,
        mesh_engine={"engine": "triangle", "version": "1"},
        binaries={},
        code={},
        packages={},
    )


def _seal_as_a_run(config: _ForcedConfig, *, name: str = "demo") -> str:
    """Seal a run with the key the pipeline records, inputs included."""
    return _seal(Path(config.workspace.project_root), _forced_key(config), name=name)


def test_an_edited_forcing_file_is_another_run(tmp_path: Path) -> None:
    config = _forced_project(tmp_path)
    _seal_as_a_run(config)
    root = Path(config.workspace.project_root)
    assert wf.completed_identical_run(root, "demo", _forced_key(config)) == root / "runs" / "demo"

    forcing = root / "data" / "recharge.csv"
    forcing.write_text("date,value\n2020-01-01,2.0\n")
    assert wf.completed_identical_run(root, "demo", _forced_key(config)) is None


def test_a_renamed_run_no_longer_answers_to_its_old_name(tmp_path: Path) -> None:
    config = _forced_project(tmp_path)
    _seal_as_a_run(config, name="baseline")
    root = Path(config.workspace.project_root)
    key = _forced_key(config)
    assert wf.completed_identical_run(root, "baseline", key) == root / "runs" / "baseline"

    (root / "runs" / "baseline").rename(root / "runs" / "renamed")
    assert wf.completed_identical_run(root, "baseline", key) is None
    assert wf.completed_identical_run(root, "renamed", key) == root / "runs" / "renamed"


class _Workflow(BaseModel):
    mode: str = "simulation"


class _FolderConfig(BaseModel):
    """A configuration that names a folder of station files, as ``[data.recharge]`` does."""

    workspace: _Workspace
    workflow: _Workflow = _Workflow()
    simulation: dict
    recharge: Annotated[Path | None, InputFile(role="recharge", category="data")] = None


def test_the_sidecar_of_a_station_file_leaves_the_key_as_it_was(tmp_path: Path) -> None:
    """The first run writes the sidecar of a station file it read: the second still matches."""
    root = tmp_path / "ws"
    station = root / "data" / "recharge" / "recharge_custom_NANCON_20000101_20021231_M.csv"
    station.parent.mkdir(parents=True)
    station.write_text("datetime,value\n2000-01-31,1.0\n", encoding="utf-8")
    config = _FolderConfig(
        workspace=_Workspace(project_root=str(root)),
        simulation={"name": "demo"},
        recharge=Path("data/recharge"),
    )
    sid = _seal_as_a_run(config)  # keyed before the run, as the run does
    station.with_name(station.name + ".json").write_text('{"source": "file"}', encoding="utf-8")

    found = wf.completed_identical_run(root, "demo", _forced_key(config))
    assert found == root / "runs" / "demo"
    assert sid


# --- The guard of a run read from an API whose extent came from the catchment ---


def _run_that_read(tmp_path: Path, *entries: dict[str, Any]) -> Path:
    """A run directory whose ``inputs.json`` lists *entries*, under a project with no workspace."""
    from hydromodpy.results.manifest import InputEntry
    from hydromodpy.results.record import InputsDocument

    run_dir = tmp_path / "runs" / "demo"
    run_dir.mkdir(parents=True)
    document = InputsDocument(sim_id="s", inputs=[InputEntry(**entry) for entry in entries])
    (run_dir / "inputs.json").write_text(document.model_dump_json(by_alias=True), encoding="utf-8")
    return run_dir


def _digest(path: Path) -> str:
    from hydromodpy.results.storage.digests import sha256_streaming

    return sha256_streaming(path)


@pytest.mark.parametrize(
    ("change", "intact"),
    [
        ("none", True),
        ("edited", False),
        ("deleted", False),
        ("user-file-edited", True),
        ("no-inputs-file", False),
        ("a-folder", True),
    ],
)
def test_a_run_that_read_an_api_file_is_given_back_only_while_the_file_is_as_it_was(
    tmp_path: Path, change: str, intact: bool
) -> None:
    from hydromodpy.workflow.replay_checks import api_inputs_intact

    api = tmp_path / "data" / "climate" / "safran.nc"
    own = tmp_path / "inputs" / "k.csv"
    api.parent.mkdir(parents=True)
    own.parent.mkdir(parents=True)
    api.write_bytes(b"as the provider gave it")
    own.write_text("1", encoding="utf-8")
    entries = [
        {
            "variable": "climate",
            "provider": "safran",
            "path": "data/climate/safran.nc",
            "sha256": _digest(api),
        },
        {"variable": "k", "provider": "file", "path": "inputs/k.csv", "sha256": _digest(own)},
    ]
    if change == "a-folder":
        (tmp_path / "data" / "folder").mkdir()
        entries.append(
            {"variable": "x", "provider": "safran", "path": "data/folder", "sha256": "z"}
        )
    run_dir = _run_that_read(tmp_path, *entries)
    if change == "edited":
        api.write_bytes(b"refreshed by the provider")
    elif change == "deleted":
        api.unlink()
    elif change == "user-file-edited":
        own.write_text("2", encoding="utf-8")
    elif change == "no-inputs-file":
        (run_dir / "inputs.json").unlink()

    assert api_inputs_intact(run_dir, tmp_path) is intact
