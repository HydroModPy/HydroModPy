"""The table of ``show`` (``hydromodpy/project/show.py``): one case per line, and ``render``."""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any, get_args

import pandas as pd
import pytest
import xarray as xr

from hydromodpy.core.exceptions import CommandUsageError, NothingThereError
from hydromodpy.project import api, show
from hydromodpy.project.facade import Project
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


# The table and the names made from it


def test_show_what_is_made_from_the_keys_of_the_table() -> None:
    assert get_args(show.ShowWhat) == tuple(show.SHOWN)


def test_the_overloads_of_the_verb_name_each_line_once() -> None:
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
def test_each_line_reads_its_subjects(what: str, subjects: tuple[str, ...]) -> None:
    assert show.SHOWN[what].subjects == subjects


@pytest.mark.parametrize(
    ("cls", "kind"), [(Run, "run"), (Session, "session"), (RunSet, "set"), (Project, "project")]
)
def test_the_kind_of_a_subject(cls: type, kind: str) -> None:
    assert show.kind_of(_bare(cls)) == kind
    assert show.kind_of(3) == "int"


# summary


def test_the_summary_of_a_project_is_read_from_its_directories(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    seal_run(project, "base")
    (project / "extra.toml").write_text("", encoding="utf-8")
    subject = _bare(Project)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Project, "root", property(lambda self: project))
        said = show.shown(subject, "summary", {})

    assert (said["name"], said["n_runs"], said["configs"]) == ("p", 1, ["extra.toml"])
    assert (said["has_index"], said["n_sessions"], said["n_trashed"]) == (False, 0, 0)


def test_the_summary_of_a_run_in_its_project_is_its_facts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_at
) -> None:
    project = make_project(tmp_path / "p")
    seal_run(project, "base")
    calls = _recorder(
        monkeypatch, "hydromodpy.results.catalog.listing.show_simulation", {"name": "base"}
    )
    run = run_at((project / "runs" / "base").resolve(), "abc")

    assert show.shown(run, "summary", {"detail": True}) == {"name": "base"}
    assert calls[0] == (("abc",), {"workspace": project.resolve(), "detail": True})


def test_the_summary_of_a_sealed_run_the_index_has_not_met_is_read(tmp_path: Path, run_at) -> None:
    project = make_project(tmp_path / "p")
    seal_run(project, "base")
    index_new_runs(project)
    sim_id = seal_run(project, "later")
    run = run_at((project / "runs" / "later").resolve(), sim_id)

    said = show.shown(run, "summary", {})

    assert (said["sim_id"], said["name"]) == (sim_id, "later")


def test_the_summary_of_a_run_out_of_any_project_is_read_from_its_folder(
    tmp_path: Path, run_at
) -> None:
    folder = tmp_path / "copy"
    folder.mkdir()
    run = run_at(folder, "abc")

    said = show.shown(run, "summary", {})

    assert (said["sim_id"], said["rel_dir"], said["deliveries"]) == ("abc", None, [])
    assert said["profile"]["present"] is False


def test_the_summary_of_a_session_is_its_summary_with_the_report_as_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dataclasses import dataclass

    @dataclass
    class Summary:
        trials: int
        report: Path | None

    monkeypatch.setattr(
        "hydromodpy.results.session.summary.session_summary",
        lambda session: Summary(trials=4, report=tmp_path / "index.html"),
    )

    said = show.shown(_bare(Session), "summary", {})

    assert said == {"trials": 4, "report": str(tmp_path / "index.html")}


# profile, table, field, series


def test_the_profile_of_a_run_and_of_a_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_at
) -> None:
    calls = _recorder(monkeypatch, "hydromodpy.results.catalog.listing.profile_of_run", {"a": 1})
    frame = pd.DataFrame({"step": ["solve"]})
    monkeypatch.setattr(Session, "profile", lambda self: frame)

    assert show.shown(run_at(tmp_path), "profile", {}) == {"a": 1}
    assert calls[0][0] == (tmp_path,)
    assert show.shown(_bare(Session), "profile", {}) is frame


@pytest.mark.parametrize("what", ["table", "field", "series"])
def test_a_line_that_reads_by_name_needs_the_name(what: str) -> None:
    with pytest.raises(CommandUsageError, match="needs name="):
        show.shown(_bare(Run), what, {})


@pytest.mark.parametrize("cls", [Run, Session, RunSet])
def test_a_table_is_read_by_the_object(monkeypatch: pytest.MonkeyPatch, cls: type) -> None:
    monkeypatch.setattr(cls, "table", lambda self, name: f"table {name}", raising=False)
    assert show.shown(_bare(cls), "table", {"name": "budget"}) == "table budget"


@pytest.mark.parametrize("what", ["field", "series"])
def test_a_field_and_a_series_are_read_by_the_run(monkeypatch: pytest.MonkeyPatch, what) -> None:
    asked: list = []
    monkeypatch.setattr(
        Run, "read", lambda self, name, **kw: asked.append((name, kw)) or "data", raising=False
    )

    options = {"name": "head", "time": -1, "layer": 0, "sel": None, "bbox": None}
    assert show.shown(_bare(Run), what, options) == "data"
    assert asked == [("head", {"time": -1, "layer": 0, "sel": None, "bbox": None})]


# point and rank


def test_a_point_is_read_in_the_project_of_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_at
) -> None:
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


def test_a_point_of_a_run_out_of_any_project_is_refused(tmp_path: Path, run_at) -> None:
    folder = tmp_path / "copy"
    folder.mkdir()
    with pytest.raises(NothingThereError, match="sits in no project"):
        show.shown(run_at(folder), "point", {"name": "head"})


def test_a_rank_reads_the_project_with_its_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _recorder(monkeypatch, "hydromodpy.results.catalog.listing.rank_simulations", "r")
    monkeypatch.setattr(Project, "root", property(lambda self: tmp_path / "p"))

    assert show.shown(_bare(Project), "rank", {}) == "r"
    assert show.shown(_bare(Project), "rank", {"metric": "kge", "limit": 2, "best": False}) == "r"
    assert calls[0] == (
        ("p",),
        {
            "workspace": tmp_path / "p",
            "metric": "nse",
            "station": None,
            "best": True,
            "n": 5,
            "mixed_windows": False,
        },
    )
    assert (calls[1][1]["metric"], calls[1][1]["n"], calls[1][1]["best"]) == ("kge", 2, False)


# figure, report and render


def test_render_draws_a_figure_and_gives_the_file_it_saved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_at
) -> None:
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


def test_a_set_of_runs_stamps_no_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _recorder(monkeypatch, "hydromodpy.display.runs.render_figure", "figure")
    show.render(_bare(RunSet), "scores", {"save": tmp_path / "s.png"})
    assert calls[0][1]["run_dir"] is None


def test_the_report_of_a_run_and_of_a_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_at
) -> None:
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


# What a save writes


def test_a_save_writes_what_was_read_by_its_suffix(tmp_path: Path) -> None:
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


def test_show_with_save_writes_a_table_and_leaves_a_figure_to_render(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Run, "table", lambda self, name: pd.DataFrame({"a": [1]}), raising=False)
    drawn = _recorder(monkeypatch, "hydromodpy.project.show.render", tmp_path / "f.png")

    written = show.shown(_bare(Run), "table", {"name": "budget", "save": tmp_path / "t.csv"})
    figure = show.shown(_bare(Run), "figure", {"name": "head", "save": tmp_path / "f.png"})

    assert written == tmp_path / "t.csv" and written.is_file()
    assert figure == tmp_path / "f.png"
    assert drawn[0][0][2]["save"] == tmp_path / "f.png"
