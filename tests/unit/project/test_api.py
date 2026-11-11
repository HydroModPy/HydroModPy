"""The fifteen verbs of ``hydromodpy/project/api.py``: what each resolves, calls and returns.

``open``, ``run`` and ``check`` have files of their own (``tests/unit/api/test_open.py``,
``tests/unit/api/test_run.py``, ``tests/unit/project/test_check_source.py``); the
lines of ``show`` are in ``tests/unit/project/test_show.py``. The work each verb
hands over is stood in for here, so a case reads what the verb itself decides.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.exceptions import (
    CalibrationError,
    CommandUsageError,
    ConfigError,
    ExportError,
    NothingThereError,
)
from hydromodpy.project import api, request
from hydromodpy.project.facade import Project
from hydromodpy.project.request import RunOutcome
from hydromodpy.results.outcome import DEFAULT_STALE_AFTER_S
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.view import Session
from tests._helpers.sealed_runs import make_project, seal_run, write_attempt, write_session_dir

pytestmark = pytest.mark.fast

FIFTEEN = [
    "open",
    "run",
    "check",
    "calibrate",
    "spinup",
    "replay",
    "stop",
    "status",
    "trash",
    "compare",
    "show",
    "export",
    "publish",
    "example",
    "doctor",
]


def _bare(cls: type) -> Any:
    """An instance that only answers ``isinstance``: nothing is read from it."""
    return object.__new__(cls)


def _recorder(monkeypatch: pytest.MonkeyPatch, target: str, value: Any = None) -> list:
    """Stand in for *target*: record each call and return *value*."""
    calls: list = []

    def fake(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return value

    monkeypatch.setattr(target, fake, raising=False)
    return calls


def test_the_module_holds_the_fifteen_verbs_in_their_order() -> None:
    assert api.__all__ == FIFTEEN
    for name in FIFTEEN:
        assert getattr(api, name).__module__ == api.__name__


def test_the_five_objects_are_read_at_the_top_of_the_module() -> None:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    assert (api.Project, api.Run, api.RunSet, api.Session, api.HydroModPyConfig) == (
        Project,
        Run,
        RunSet,
        Session,
        HydroModPyConfig,
    )


# open gives the objects the function that draws


def test_open_gives_a_run_and_a_session_the_render_of_show(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hydromodpy.project.show import render

    project = make_project(tmp_path / "p")
    seal_run(project, "base")
    write_session_dir(project, "calage")
    runs = _recorder(monkeypatch, "hydromodpy.results.run.view.open_run_dir", "a run")
    sessions = _recorder(monkeypatch, "hydromodpy.project.api.Session", "a session")

    assert api.open(project / "runs" / "base") == "a run"
    assert api.open(project / "sessions" / "calage") == "a session"
    assert runs[0][1]["render"] is render
    assert sessions[0][1]["render"] is render


# check


@pytest.mark.parametrize("source", [3, None, b"run.toml"])
def test_check_refuses_what_is_neither_a_path_nor_a_mapping(source: object) -> None:
    with pytest.raises(TypeError, match="path or a mapping"):
        api.check(source)  # type: ignore[arg-type]


# calibrate


def _calibration_file(tmp_path: Path) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")
    return path


def test_calibrate_gives_a_file_its_options_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _recorder(monkeypatch, "hydromodpy.project.calibrate.calibrate_a_file", "report")
    path = _calibration_file(tmp_path)

    assert api.calibrate(path, phase="steady", resume=True, report=False) == "report"
    (args, kwargs) = calls[0]
    assert args == (path,)
    assert (kwargs["phase"], kwargs["resume"], kwargs["report"], kwargs["force"]) == (
        "steady",
        True,
        False,
        False,
    )


@pytest.mark.parametrize("option", ["case", "method", "max_trials", "seed", "save_runs"])
def test_calibrate_refuses_for_a_file_what_steers_a_calibration_in_memory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, option: str
) -> None:
    _recorder(monkeypatch, "hydromodpy.project.calibrate.calibrate_a_file")
    value = 3 if option in ("max_trials", "seed") else "x"
    with pytest.raises(ConfigError, match=option):
        api.calibrate(_calibration_file(tmp_path), **{option: value})


def test_a_dry_calibration_gives_its_plan_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = SimpleNamespace(phases=[{"name": "steady"}, {"name": "transient"}])
    calls = _recorder(monkeypatch, "hydromodpy.project.calibrate.calibration_plan", plan)
    ran = _recorder(monkeypatch, "hydromodpy.project.calibrate.calibrate_a_file")
    path = _calibration_file(tmp_path)

    assert api.calibrate(path, dry_run=True, workspace=tmp_path, preflight=False) is plan
    assert api.calibrate(path, dry_run=True, phase="steady") is plan
    assert calls[0] == ((path.resolve(),), {"workspace": tmp_path.resolve(), "check": False})
    assert calls[1][1] == {"workspace": None, "check": True}
    assert ran == []
    with pytest.raises(CalibrationError, match="unknown phase 'other'"):
        api.calibrate(path, dry_run=True, phase="other")


def test_a_calibration_in_memory_runs_in_a_project_with_its_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict = {}

    class FakeProject:
        def __init__(self, config: Any, **kwargs: Any) -> None:
            asked.update(config=config, opened=kwargs)

        def __enter__(self) -> FakeProject:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def calibrate(self, **options: Any) -> str:
            asked["options"] = options
            return "report"

    monkeypatch.setattr(api, "Project", FakeProject)
    config = SimpleNamespace(calibration=SimpleNamespace(phases=None))

    assert api.calibrate(config, case="calage", max_trials=4, force=True) == "report"
    assert asked["config"] is config
    assert asked["options"] == {"case": "calage", "max_trials": 4, "force": True}
    assert asked["opened"]["headless"] is True
    with pytest.raises(CalibrationError, match="no phase 'p1'"):
        api.calibrate(config, phase="p1")


# spinup


def test_spinup_reads_its_settings_from_a_mapping_and_writes_the_project_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hydromodpy.model.initial_config import SpinupConfig

    seen: dict = {}

    class FakeProject:
        def __init__(self, config: Any, **kwargs: Any) -> None:
            seen["config"] = config
            self.root = tmp_path

        def __enter__(self) -> FakeProject:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def fake_spinup(project: Any, *, spinup: Any, name_prefix: str) -> Any:
        seen.update(spinup=spinup, prefix=name_prefix)
        return SimpleNamespace(restart_from=None)

    monkeypatch.setattr(api, "Project", FakeProject)
    monkeypatch.setattr("hydromodpy.project.spinup.run_spinup", fake_spinup)
    config = object()

    api.spinup(config, spinup={}, name_prefix="warm")

    assert seen["config"] is config
    assert isinstance(seen["spinup"], SpinupConfig)
    assert seen["prefix"] == "warm"
    assert (tmp_path / ".hmp" / "logs" / "hydromodpy_debug.log").is_file()


# replay and stop


def test_replay_gives_the_outcome_of_the_directory_it_wrote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "p")
    seal_run(project, "base")
    seal_run(project, "base.v2")
    played = SimpleNamespace(dir=(project / "runs" / "base.v2").resolve())
    calls = _recorder(monkeypatch, "hydromodpy.project.replay.replay", played)

    outcome = api.replay("base", workspace=project, strict=True)

    assert isinstance(outcome, RunOutcome)
    assert (outcome.name, outcome.project_root) == ("base.v2", project.resolve())
    (args, kwargs) = calls[0]
    assert args[0] == (project / "runs" / "base.v2").resolve()
    assert (kwargs["strict"], kwargs["base"]) == (True, project.resolve())


def test_stop_reads_a_name_in_the_project_named_and_a_path_as_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "p")
    write_attempt(project, "runs/base")
    calls = _recorder(monkeypatch, "hydromodpy.results.storage.attempt.request_stop", "flag")

    assert api.stop("base", workspace=project) == "flag"
    assert api.stop(project / "runs" / "base") == "flag"
    assert [args[0] for args, _ in calls] == [
        (project / "runs" / "base").resolve(),
        (project / "runs" / "base").resolve(),
    ]
    with pytest.raises(NothingThereError, match="nothing to stop"):
        api.stop("ghost", workspace=project)


def test_a_name_without_workspace_is_never_read_in_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "p")
    write_attempt(project, "runs/base")
    monkeypatch.chdir(project)

    with pytest.raises(NothingThereError, match="workspace="):
        api.stop("ghost")


# status


def test_status_needs_a_project(tmp_path: Path) -> None:
    with pytest.raises(CommandUsageError, match="workspace="):
        api.status()
    with pytest.raises(CommandUsageError, match="no directory"):
        api.status(_bare(RunSet))


def test_status_lists_the_directories_of_a_project_and_reads_one(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_attempt(project, "runs/base", status="completed")
    write_session_dir(project, "calage")

    listed = api.status(workspace=project)
    one = api.status(project / "sessions" / "calage")
    same = api.status("calage", workspace=project)

    assert [(each.name, each.kind) for each in listed] == [("base", "run"), ("calage", "session")]
    assert api.status(".", workspace=project) == listed
    assert (one.name, one.kind, one.project_root) == ("calage", "session", project.resolve())
    assert same == one
    json.dumps([each.to_dict() for each in listed])


def test_status_of_the_plan_reads_the_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    calls = _recorder(monkeypatch, "hydromodpy.project.launch.project_status", "report")

    assert api.status(workspace=project, plan=True) == "report"
    assert calls[0][0] == (project.resolve(),)
    assert calls[0][1] == {}


def test_status_of_the_plan_passes_the_stale_age(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "p")
    calls = _recorder(monkeypatch, "hydromodpy.project.launch.project_status", "report")

    assert api.status(workspace=project, plan=True, stale_after_s=90.0) == "report"
    assert calls[0][1] == {"stale_after_s": 90.0}


def test_status_of_the_directories_passes_the_stale_age(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "p")
    write_attempt(project, "runs/base", status="completed")
    seen: list[float] = []
    real = request.effective_status

    def spy(path: Path, **kwargs: Any) -> Any:
        seen.append(kwargs["stale_after_s"])
        return real(path, **kwargs)

    monkeypatch.setattr(request, "effective_status", spy)

    api.status(workspace=project)
    api.status(workspace=project, stale_after_s=90.0)
    api.status(project / "runs" / "base", stale_after_s=45.0)

    assert seen == [DEFAULT_STALE_AFTER_S, 90.0, 45.0]


# show


def test_show_reads_the_session_of_a_name_a_run_also_carries(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    seal_run(project, "calage")
    write_session_dir(project, "calage")

    assert api._subject("calage", project, session_first=True).__class__ is Session
    assert api._subject("calage", project).__class__ is Run
    assert api._subject("runs/calage", project, session_first=True).__class__ is Run


# trash


def test_trash_moves_a_run_named_in_the_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "p")
    seal_run(project, "base")
    moved = project / "trash" / "runs__base"
    calls = _recorder(monkeypatch, "hydromodpy.results.trash.trash_run", moved)
    indexed = _recorder(monkeypatch, "hydromodpy.results.catalog.indexer.reindex_if_indexed")

    assert api.trash("base", workspace=project, force=True) == [moved]
    (args, kwargs) = calls[0]
    assert args == (project.resolve(), "runs/base")
    assert kwargs["force"] is True
    assert indexed == [((project.resolve(),), {})]


def test_trash_restores_an_entry_of_the_project_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "p")
    entry = SimpleNamespace(name="runs__base@20261110T000000")
    _recorder(monkeypatch, "hydromodpy.results.catalog.discovery.resolve_trashed", entry)
    calls = _recorder(monkeypatch, "hydromodpy.results.trash.restore", project / "runs" / "base")
    _recorder(monkeypatch, "hydromodpy.results.catalog.indexer.reindex_if_indexed")

    with pytest.raises(CommandUsageError, match="workspace="):
        api.trash("base", restore=True)
    assert api.trash("base", workspace=project, restore=True) == [project / "runs" / "base"]
    assert calls[0][0] == (project.resolve(), entry.name)


# compare


def test_compare_reads_the_references_in_the_project_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "p")
    comparison = SimpleNamespace(written=[], write=lambda out: comparison.written.append(out))
    calls = _recorder(monkeypatch, "hydromodpy.project.compare.compare_references", comparison)
    run = _bare(Run)
    monkeypatch.setattr(Run, "dir", property(lambda self: project / "runs" / "b"))

    assert api.compare(["a", run], workspace=project, out=tmp_path / "out") is comparison
    (args, kwargs) = calls[0]
    assert args == (["a", str(project / "runs" / "b")],)
    assert kwargs["project_root"] == project.resolve()
    assert comparison.written == [tmp_path / "out"]
    api.compare(["a"])
    assert calls[1][1]["project_root"] is None


def test_compare_by_site_writes_a_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _recorder(monkeypatch, "hydromodpy.project.compare.compare_by_site", tmp_path / "out")

    with pytest.raises(CommandUsageError, match="out="):
        api.compare(["a", "b"], by="site")
    assert api.compare(["a", "b"], by="site", out=tmp_path / "out") == tmp_path / "out"
    assert calls[0][0] == (["a", "b"], tmp_path / "out")


# show


def test_show_hands_every_word_to_the_line_of_its_what(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _recorder(monkeypatch, "hydromodpy.project.api.shown", "value")
    run = _bare(Run)

    assert api.show(run, what="field", name="head", time=-1, sel={"x": 1}, bbox=[0, 0, 1, 1]) == (
        "value"
    )
    (args, _) = calls[0]
    assert args[0] is run
    assert args[1] == "field"
    assert (args[2]["name"], args[2]["time"], args[2]["sel"], args[2]["bbox"]) == (
        "head",
        -1,
        {"x": 1},
        (0, 0, 1, 1),
    )


@pytest.mark.parametrize(
    ("subject", "what", "allowed"),
    [
        (Run, "rank", "summary, profile, table, field, series, point, figure, report"),
        (Session, "field", "summary, profile, table, figure, report"),
        (RunSet, "summary", "table, figure"),
        (Project, "figure", "summary, rank"),
    ],
)
def test_show_refuses_a_what_its_subject_has_not(subject: type, what: str, allowed: str) -> None:
    with pytest.raises(CommandUsageError) as caught:
        api.show(_bare(subject), what=what)  # type: ignore[call-overload]
    assert caught.value.category == "usage"
    assert allowed in str(caught.value)


def test_show_refuses_a_what_no_line_has() -> None:
    with pytest.raises(CommandUsageError, match="is not one of summary"):
        api.show(_bare(Run), what="everything")  # type: ignore[call-overload]


# export


def test_export_reads_a_run_and_refuses_anything_else(monkeypatch: pytest.MonkeyPatch) -> None:
    exported: list = []
    run = _bare(Run)
    monkeypatch.setattr(
        Run, "export", lambda self, variables, **kw: exported.append(variables) or []
    )

    with pytest.raises(TypeError, match="export reads a run"):
        api.export(_bare(Session), "head")
    with pytest.raises(ExportError, match="variables is missing"):
        api.export(run)
    with pytest.raises(ExportError, match="no other word"):
        api.export(run, "head", deliver=True)  # type: ignore[call-overload]
    assert api.export(run, ["head"]) == []
    assert exported == [["head"]]


# publish


def test_publish_copies_a_project_whole_and_a_run_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = make_project(tmp_path / "p")
    seal_run(project, "base")
    _recorder(monkeypatch, "hydromodpy.project.exchange.share.inputs_of", "inputs")
    whole = _recorder(monkeypatch, "hydromodpy.results.export.publish.publish_project", "all")
    one = _recorder(monkeypatch, "hydromodpy.results.export.publish.publish", tmp_path / "copy")

    assert api.publish(".", to=tmp_path / "out", workspace=project) == "all"
    assert api.publish(project, to=tmp_path / "out", with_=["results"]) == "all"
    assert api.publish("base", to=tmp_path / "copy", workspace=project) == tmp_path / "copy"
    assert whole[0][0][0] == project.resolve()
    assert whole[1][1]["with_"] == ("results",)
    (args, kwargs) = one[0]
    assert args[0] == (project / "runs" / "base").resolve()
    assert (kwargs["project_root"], kwargs["inputs"]) == (project.resolve(), "inputs")
    with pytest.raises(FileNotFoundError, match="summary"):
        api.publish("summary", to=tmp_path / "s", workspace=project)


# example and doctor


def test_example_lists_shows_and_installs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _recorder(monkeypatch, "hydromodpy.project.examples.manifest.load_catalog", ("a", "b"))
    _recorder(monkeypatch, "hydromodpy.project.examples.manifest.find_entry", "entry")
    _recorder(monkeypatch, "hydromodpy.project.examples.blobs.resolve_source", "source")
    installs = _recorder(
        monkeypatch, "hydromodpy.project.examples.install.install_example", "report"
    )

    assert api.example() == ("a", "b")
    assert api.example("04") == "entry"
    assert api.example("04", add=True, workspace=tmp_path, force=True) == "report"
    assert installs[0] == (
        ("entry",),
        {"workspace": tmp_path.resolve(), "source": "source", "force": True},
    )
    with pytest.raises(CommandUsageError, match="name it"):
        api.example(add=True)


def test_doctor_gives_the_report_of_the_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    _recorder(monkeypatch, "hydromodpy.project.doctor.doctor_report", "report")
    assert api.doctor() == "report"
