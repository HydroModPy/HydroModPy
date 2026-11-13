"""The table of ``show``: what each line reads, how it is saved, and ``render``."""

from __future__ import annotations

import json
import typing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.exceptions import CommandUsageError, NothingThereError
from hydromodpy.project import api, show
from hydromodpy.project.facade import Project
from hydromodpy.results.catalog.discovery import SimulationNotFoundError
from hydromodpy.results.catalog.indexer import index_new_runs
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.view import REPORT, Run
from hydromodpy.results.session.view import Session
from tests._helpers.sealed_runs import make_project, seal_run

pytestmark = pytest.mark.fast


def _bare(cls: type) -> Any:
    return object.__new__(cls)


@pytest.fixture
def run_at(monkeypatch: pytest.MonkeyPatch):
    """Give a bare run a directory and an id, the two things a line reads of it."""

    def place(directory: Path, sim_id: str = "s" * 32) -> Run:
        monkeypatch.setattr(Run, "dir", property(lambda self: directory))
        monkeypatch.setattr(Run, "sim_id", property(lambda self: sim_id))
        return _bare(Run)

    return place


def _recorder(monkeypatch: pytest.MonkeyPatch, target: str, value: Any = None) -> list:
    calls: list = []

    def fake(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return value

    monkeypatch.setattr(target, fake, raising=False)
    return calls


def test_show_what_keys() -> None:
    assert get_args(show.ShowWhat) == tuple(show.SHOWN)


def test_overloads_name_each_line() -> None:
    named: list[str] = []
    for overload in typing.get_overloads(api.show):
        hints = typing.get_type_hints(
            overload, globalns={**vars(api), "pd": pd, "xr": xr, "Figure": object}
        )
        named.extend(get_args(hints["what"]))
    assert sorted(named) == sorted(show.SHOWN)


@pytest.mark.parametrize(
    ("what", "subjects"),
    [
        ("summary", ("run", "session", "project")),
        ("profile", ("run", "session")),
        ("table", ("run", "session", "set")),
        ("field", ("run",)),
        ("series", ("run",)),
        ("point", ("run",)),
        ("rank", ("project",)),
        ("figure", ("run", "session", "set")),
        ("report", ("run", "session")),
    ],
)
def test_subjects_of_a_line(what: str, subjects: tuple[str, ...]) -> None:
    assert show.SHOWN[what].subjects == subjects


@pytest.mark.parametrize(
    ("cls", "kind"), [(Run, "run"), (Session, "session"), (RunSet, "set"), (Project, "project")]
)
def test_kind_of_a_subject(cls: type, kind: str) -> None:
    assert show.kind_of(_bare(cls)) == kind
    assert show.kind_of(3) == "int"


def test_summary_of_an_unindexed_run(tmp_path: Path, run_at) -> None:
    project = make_project(tmp_path / "p")
    seal_run(project, "base")
    index_new_runs(project)
    sim_id = seal_run(project, "later")
    run = run_at((project / "runs" / "later").resolve(), sim_id)

    said = show.shown(run, "summary", {})

    assert (said["sim_id"], said["name"]) == (sim_id, "later")


def test_summary_of_a_loose_run(tmp_path: Path, run_at) -> None:
    folder = tmp_path / "copy"
    folder.mkdir()
    run = run_at(folder, "abc")

    said = show.shown(run, "summary", {})

    assert (said["sim_id"], said["rel_dir"], said["deliveries"]) == ("abc", None, [])
    assert said["profile"]["present"] is False


def test_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_at) -> None:
    calls = _recorder(monkeypatch, "hydromodpy.results.catalog.listing.profile_of_run", {"a": 1})
    frame = pd.DataFrame({"step": ["solve"]})
    monkeypatch.setattr(Session, "profile", lambda self: frame)

    assert show.shown(run_at(tmp_path), "profile", {}) == {"a": 1}
    assert calls[0][0] == (tmp_path,)
    assert show.shown(_bare(Session), "profile", {}) is frame


@pytest.mark.parametrize("what", ["table", "field", "series"])
def test_name_is_needed(what: str) -> None:
    with pytest.raises(CommandUsageError, match="needs name="):
        show.shown(_bare(Run), what, {})


@pytest.mark.parametrize("cls", [Run, Session, RunSet])
def test_table_read_by_object(monkeypatch: pytest.MonkeyPatch, cls: type) -> None:
    monkeypatch.setattr(cls, "table", lambda self, name: f"table {name}", raising=False)
    assert show.shown(_bare(cls), "table", {"name": "budget"}) == "table budget"


@pytest.mark.parametrize("what", ["field", "series"])
def test_field_and_series(monkeypatch: pytest.MonkeyPatch, what) -> None:
    asked: list = []
    monkeypatch.setattr(
        Run, "read", lambda self, name, **kw: asked.append((name, kw)) or "data", raising=False
    )

    options = {"name": "head", "time": -1, "layer": 0, "sel": None, "bbox": None}
    assert show.shown(_bare(Run), what, options) == "data"
    assert asked == [("head", {"time": -1, "layer": 0, "sel": None, "bbox": None})]


def test_point_of_a_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_at) -> None:
    project = make_project(tmp_path / "p")
    seal_run(project, "base")
    calls = _recorder(monkeypatch, "hydromodpy.results.catalog.listing.point_simulations", "f")
    run = run_at((project / "runs" / "base").resolve(), "abc")

    options = {"name": "head", "point": {"x": 1.0, "y": 2.0}, "layer": 0, "time": -1}
    assert show.shown(run, "point", options) == "f"
    (args, kwargs) = calls[0]
    assert args == (["abc"],)
    assert (kwargs["workspace"], kwargs["variables"], kwargs["x"], kwargs["timestep"]) == (
        project.resolve(),
        ["head"],
        1.0,
        -1,
    )
    with pytest.raises(CommandUsageError, match="not z"):
        show.shown(run, "point", {"name": "head", "point": {"z": 1.0}})


def test_point_needs_a_project(tmp_path: Path, run_at) -> None:
    folder = tmp_path / "copy"
    folder.mkdir()
    with pytest.raises(NothingThereError, match="sits in no project"):
        show.shown(run_at(folder), "point", {"name": "head"})


def test_render(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_at) -> None:
    calls = _recorder(monkeypatch, "hydromodpy.display.runs.render_figure", "figure")
    run = run_at(tmp_path / "runs" / "base")

    assert show.render(run, "head_map", {"dpi": None, "time": "last"}) == "figure"
    assert show.render(run, "head_map", {"save": tmp_path}) == tmp_path / "head_map.png"
    assert show.render(run, "head_map", {"save": tmp_path / "x.png"}) == tmp_path / "x.png"
    assert calls[0] == (
        ("head_map", run),
        {"save": None, "dpi": None, "run_dir": None, "time": "last"},
    )
    assert calls[1][1]["run_dir"] == tmp_path / "runs" / "base"
    assert show.shown(run, "figure", {"name": "head_map", "options": {"cmap": "x"}}) == "figure"
    assert calls[3][1]["cmap"] == "x"


def test_against_names_a_run_of_the_same_project(monkeypatch, tmp_path: Path, run_at) -> None:
    other = SimpleNamespace(name="other", dir=tmp_path / "runs" / "other")
    project = SimpleNamespace(runs=lambda: [other])
    monkeypatch.setattr("hydromodpy.project.facade.open_project", lambda root: project)
    drawn = _recorder(monkeypatch, "hydromodpy.display.render.render", {})
    run = run_at(tmp_path / "runs" / "base")

    show.render(run, "head", {"against": "other", "data": True})
    assert drawn[0][1]["runs"] == {"other": other}
    with pytest.raises(CommandUsageError, match="no run of the project. Runs: other"):
        show.render(run, "head", {"against": "nope", "data": True})


def test_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_at) -> None:
    runs = _recorder(monkeypatch, "hydromodpy.project.report.report_run", tmp_path / "r.html")
    sessions = _recorder(
        monkeypatch, "hydromodpy.project.report.report_session", tmp_path / "s.html"
    )
    monkeypatch.setattr(Session, "dir", property(lambda self: tmp_path / "sessions" / "c"))
    run = run_at(tmp_path / "runs" / "base")

    options = {"preset": "management", "lang": "fr", "save": tmp_path / "ignored", "name": None}
    assert show.shown(run, "report", options) == tmp_path / "r.html"
    assert show.shown(_bare(Session), "report", {}) == tmp_path / "s.html"
    assert runs[0] == ((tmp_path / "runs" / "base",), {"preset": "management", "lang": "fr"})
    assert sessions[0][0] == (tmp_path / "sessions" / "c",)
    with pytest.raises(CommandUsageError, match="run or a session"):
        show.render(_bare(RunSet), REPORT, {})


def test_write_shown_by_suffix(tmp_path: Path) -> None:
    frame = pd.DataFrame({"a": [1, 2]})
    field = xr.DataArray([1.0, 2.0], dims=["x"], name="head")

    assert json.loads(show.write_shown({"a": 1}, tmp_path / "s.json").read_text()) == {"a": 1}
    assert pd.read_csv(show.write_shown(frame, tmp_path / "t.csv")).equals(frame)
    assert pd.read_parquet(show.write_shown(frame, tmp_path / "t.parquet")).equals(frame)
    assert list(pd.read_csv(show.write_shown(frame["a"], tmp_path / "s.csv"))["a"]) == [1, 2]
    assert show.write_shown(field, tmp_path / "f.nc").is_file()
    assert "head" in pd.read_csv(show.write_shown(field, tmp_path / "f.csv")).columns
    with pytest.raises(CommandUsageError, match="cannot hold a DataFrame"):
        show.write_shown(frame, tmp_path / "t.png")


def test_show_with_save(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Run, "table", lambda self, name: pd.DataFrame({"a": [1]}), raising=False)
    drawn = _recorder(monkeypatch, "hydromodpy.project.show.render", tmp_path / "f.png")

    written = show.shown(_bare(Run), "table", {"name": "budget", "save": tmp_path / "t.csv"})
    figure = show.shown(_bare(Run), "figure", {"name": "head", "save": tmp_path / "f.png"})

    assert written == tmp_path / "t.csv" and written.is_file()
    assert figure == tmp_path / "f.png"
    assert drawn[0][0][2]["save"] == tmp_path / "f.png"


def test_show_target(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "data").mkdir(parents=True)
    (workspace / "workspace.toml").write_text("[workspace]\n", encoding="utf-8")
    demo = make_project(workspace / "projects" / "demo")
    seal_run(demo, "baseline")

    assert show.show_target("demo", demo, str(workspace)) == show.Target(
        workspace / "projects" / "demo", "project"
    )
    with pytest.raises(SimulationNotFoundError):
        show.show_target("absent", demo, str(workspace))
    with pytest.raises(SimulationNotFoundError):
        show.show_target("absent/with/slash", demo, str(workspace))
