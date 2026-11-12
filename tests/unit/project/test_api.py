"""The fifteen verbs of ``hydromodpy/project/api.py``: what each resolves, calls and returns.

``open``, ``run`` and ``check`` have files of their own (``tests/unit/api/test_api.py``,
``tests/unit/project/test_check_source.py``); the
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
from hydromodpy.project import api
from hydromodpy.project.facade import Project
from hydromodpy.project.request import RunOutcome
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


def test_fifteen_verbs() -> None:
    assert api.__all__ == FIFTEEN
    for name in FIFTEEN:
        assert getattr(api, name).__module__ == api.__name__


def test_five_objects() -> None:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    assert (api.Project, api.Run, api.RunSet, api.Session, api.HydroModPyConfig) == (
        Project,
        Run,
        RunSet,
        Session,
        HydroModPyConfig,
    )


def _calibration_file(tmp_path: Path) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")
    return path


@pytest.mark.parametrize("option", ["case", "method", "max_trials", "seed", "save_runs"])
def test_calibrate_file_refuses_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, option: str
) -> None:
    _recorder(monkeypatch, "hydromodpy.project.calibrate.calibrate_a_file")
    value = 3 if option in ("max_trials", "seed") else "x"
    with pytest.raises(ConfigError, match=option):
        api.calibrate(_calibration_file(tmp_path), **{option: value})


def test_dry_calibration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


def test_calibration_in_memory(
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


def test_spinup_from_mapping(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


def test_replay_outcome(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


def test_stop_name_or_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


def test_name_needs_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_attempt(project, "runs/base")
    monkeypatch.chdir(project)

    with pytest.raises(NothingThereError, match="workspace="):
        api.stop("ghost")


def test_status_needs_project(tmp_path: Path) -> None:
    with pytest.raises(CommandUsageError, match="workspace="):
        api.status()
    with pytest.raises(CommandUsageError, match="no directory"):
        api.status(_bare(RunSet))


def test_status_listing(tmp_path: Path) -> None:
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


def test_status_plan_stale_age(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    calls = _recorder(monkeypatch, "hydromodpy.project.launch.status.project_status", "report")

    assert api.status(workspace=project, plan=True, stale_after_s=90.0) == "report"
    assert calls[0][1] == {"stale_after_s": 90.0}


def test_trash_a_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


def test_trash_restore(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    entry = SimpleNamespace(name="runs__base@20261110T000000")
    _recorder(monkeypatch, "hydromodpy.results.catalog.discovery.resolve_trashed", entry)
    calls = _recorder(monkeypatch, "hydromodpy.results.trash.restore", project / "runs" / "base")
    _recorder(monkeypatch, "hydromodpy.results.catalog.indexer.reindex_if_indexed")

    with pytest.raises(CommandUsageError, match="workspace="):
        api.trash("base", restore=True)
    assert api.trash("base", workspace=project, restore=True) == [project / "runs" / "base"]
    assert calls[0][0] == (project.resolve(), entry.name)


def test_compare_references(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


def test_compare_by_site(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _recorder(monkeypatch, "hydromodpy.project.compare.compare_by_site", tmp_path / "out")

    with pytest.raises(CommandUsageError, match="out="):
        api.compare(["a", "b"], by="site")
    assert api.compare(["a", "b"], by="site", out=tmp_path / "out") == tmp_path / "out"
    assert calls[0][0] == (["a", "b"], tmp_path / "out")


@pytest.mark.parametrize(
    ("subject", "what", "allowed"),
    [
        (Run, "rank", "summary, profile, table, field, series, point, figure, report"),
        (Session, "field", "summary, profile, table, figure, report"),
        (RunSet, "summary", "table, figure"),
        (Project, "figure", "summary, rank"),
    ],
)
def test_show_refuses_what(subject: type, what: str, allowed: str) -> None:
    with pytest.raises(CommandUsageError) as caught:
        api.show(_bare(subject), what=what)  # type: ignore[call-overload]
    assert caught.value.category == "usage"
    assert allowed in str(caught.value)


def test_show_refuses_unknown_what() -> None:
    with pytest.raises(CommandUsageError, match="is not one of summary"):
        api.show(_bare(Run), what="everything")  # type: ignore[call-overload]


def test_export_a_run(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_publish_project_or_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


def test_example_verb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
