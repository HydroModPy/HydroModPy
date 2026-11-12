"""What a figure draws: a run, a calibration session or a set of runs.

A figure declares its subject in ``FigureSpec.subject``. The display layer
resolves it once from the object a caller passed. A session figure asked for
on a run draws the session that promoted the run and receives the run as the
option ``promoted``. A figure given an object it cannot draw is refused with
a sentence that names what to pass.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import hydromodpy.display.figure as display_figure
import hydromodpy.display.runs as display_runs
from hydromodpy.display.figure import (
    PROMOTED_OPTION,
    SUBJECTS,
    BaseFigure,
    FigureSpec,
    option_names_of,
)
from hydromodpy.display.figure_registry import list_figures
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.session.view import Session
from tests._helpers.sealed_runs import make_project, write_session_dir

SESSION_FIGURES = frozenset(
    {
        "calibration_convergence",
        "calibration_trace",
        "calibration_landscape",
        "calibration_pairplot",
        "calibration_trial_distribution",
        "calibration_objective_surface",
        "calibration_progress",
        "bisection_bracket_trace",
        "parameter_cost_profile",
        "downslope_distance_crossing",
        "matching_hydrographic_network_card",
    }
)
RUNSET_FIGURES = frozenset({"ensemble_band"})


def expected_subject(name: str) -> str:
    if name in SESSION_FIGURES:
        return "session"
    if name in RUNSET_FIGURES:
        return "runset"
    return "run"


class Drawn(BaseFigure):
    """A figure that records what it was handed instead of drawing."""

    spec = FigureSpec(name="drawn", title="Drawn")

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def render(self, subject: Any, ax: Any, **opts: Any) -> Any:
        self.calls.append((subject, opts))
        return ax


class RunFigure(Drawn):
    spec = FigureSpec(name="a_run_figure", title="Run")


class SessionFigure(Drawn):
    spec = FigureSpec(name="a_session_figure", title="Session", subject="session")


class RunsetFigure(Drawn):
    spec = FigureSpec(name="a_runset_figure", title="Runset", subject="runset")


class TakesAPromotedRun(Drawn):
    spec = FigureSpec(name="takes_promoted", title="t", subject="session")

    def render(self, subject: Any, ax: Any, *, promoted: Any = None, **_: Any) -> Any:
        return ax


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return make_project(tmp_path / "demo")


@pytest.fixture
def promoted(project: Path) -> SimpleNamespace:
    """A run whose lineage names the session that promoted it."""
    session_id = write_session_dir(project, "cheze-calage")
    run_dir = project / "runs" / "cheze-calage-best"
    run_dir.mkdir(parents=True)
    return SimpleNamespace(
        dir=run_dir, lineage=SimpleNamespace(session_id=session_id), name="cheze-calage-best"
    )


@pytest.fixture
def plain(project: Path) -> SimpleNamespace:
    """A run no session promoted."""
    run_dir = project / "runs" / "baseline"
    run_dir.mkdir(parents=True)
    return SimpleNamespace(dir=run_dir, lineage=SimpleNamespace(session_id=None), name="baseline")


def objects_of(project: Path, promoted: Any, plain: Any) -> dict[str, Any]:
    return {
        "promoted run": promoted,
        "plain run": plain,
        "session": Session(project / "sessions" / "cheze-calage"),
        "runset": RunSet([], SimpleNamespace()),
    }


# figure, object given, why it is refused (None when it is drawn)
SUBJECT_REASONS = [
    (RunFigure, "plain run", None),
    (RunFigure, "promoted run", None),
    (RunFigure, "session", display_figure.NOT_A_RUN_REASON),
    (RunFigure, "runset", display_figure.NOT_A_RUN_REASON),
    (SessionFigure, "promoted run", None),
    (SessionFigure, "session", None),
    (SessionFigure, "plain run", display_figure.NOT_PROMOTED_REASON),
    (SessionFigure, "runset", display_figure.NOT_A_SESSION_REASON),
    (RunsetFigure, "runset", None),
    (RunsetFigure, "plain run", display_figure.NOT_A_RUNSET_REASON),
    (RunsetFigure, "promoted run", display_figure.NOT_A_RUNSET_REASON),
    (RunsetFigure, "session", display_figure.NOT_A_RUNSET_REASON),
]

# figure, object given: the figure draws that very object
DRAWN_AS_GIVEN = [
    (RunFigure, "plain run"),
    (RunFigure, "promoted run"),
    (RunsetFigure, "runset"),
]


@pytest.mark.parametrize("spec", list_figures(), ids=lambda spec: spec.name)
def test_each_figure_declares_its_subject(spec: FigureSpec) -> None:
    assert spec.subject in SUBJECTS
    assert spec.subject == expected_subject(spec.name)


@pytest.mark.parametrize("option", ["subject", PROMOTED_OPTION])
def test_layer_options_are_hidden(option: str) -> None:
    assert option not in option_names_of(TakesAPromotedRun)


@pytest.mark.parametrize(
    ("figure", "given", "reason"),
    SUBJECT_REASONS,
    ids=[f"{case[0].spec.subject} figure given a {case[1]}" for case in SUBJECT_REASONS],
)
def test_subject_reasons(project, promoted, plain, figure, given, reason) -> None:
    obj = objects_of(project, promoted, plain)[given]

    assert display_runs._subject_for(figure(), obj).reason == reason
    assert display_runs.unavailable_reason(figure(), obj) == reason


@pytest.mark.parametrize(("figure", "given"), DRAWN_AS_GIVEN)
def test_subject_drawn_as_given(project, promoted, plain, figure, given) -> None:
    obj = objects_of(project, promoted, plain)[given]

    subject = display_runs._subject_for(figure(), obj)

    assert subject.drawn is obj
    assert subject.options == {}


def test_session_figure_given_a_session(project, promoted, plain) -> None:
    session = objects_of(project, promoted, plain)["session"]

    subject = display_runs._subject_for(SessionFigure(), session)

    assert subject.drawn.dir == (project / "sessions" / "cheze-calage").resolve()
    assert subject.options == {}


def test_session_figure_given_a_promoted_run(project, promoted) -> None:
    subject = display_runs._subject_for(SessionFigure(), promoted)

    assert isinstance(subject.drawn, Session)
    assert subject.drawn.dir == (project / "sessions" / "cheze-calage").resolve()
    assert subject.options == {PROMOTED_OPTION: promoted}
    assert subject.run is promoted


def test_reason_sentences() -> None:
    assert display_figure.NOT_PROMOTED_REASON == (
        "draws the calibration session that promoted a run; this run was not promoted by a session"
    )
    assert display_figure.NOT_A_RUNSET_REASON == "draws the envelope of several runs; pass a RunSet"


def test_session_lookup_is_memoised(monkeypatch, promoted) -> None:
    asked: list[Any] = []

    def counting(run: Any) -> Session | None:
        asked.append(run)
        return None

    monkeypatch.setattr(Session, "of_run", staticmethod(counting))
    session_of = display_runs._memoised_session_of()
    for _ in range(3):
        display_runs._subject_for(SessionFigure(), promoted, session_of=session_of)
    assert asked == [promoted]


def test_render_hands_over_a_session(monkeypatch, tmp_path, project, promoted) -> None:
    instance = SessionFigure()
    monkeypatch.setattr(display_runs, "_get_figure", lambda _name: instance)

    display_runs.render_figure(instance.spec.name, promoted, save=tmp_path / "out.png")

    ((subject, opts),) = instance.calls
    assert isinstance(subject, Session)
    assert opts[PROMOTED_OPTION] is promoted
    assert (tmp_path / "out.png").is_file()


def test_render_hands_over_a_run(monkeypatch, tmp_path, plain) -> None:
    instance = RunFigure()
    monkeypatch.setattr(display_runs, "_get_figure", lambda _name: instance)

    display_runs.render_figure(instance.spec.name, plain, save=tmp_path / "out.png")

    ((subject, opts),) = instance.calls
    assert subject is plain
    assert PROMOTED_OPTION not in opts
    assert (tmp_path / "out.png").is_file()


def test_time_needs_a_run(project, promoted, plain) -> None:
    # A [display] time reaches every figure that draws one instant. A session
    # drawn alone holds no period to place it in.
    session = objects_of(project, promoted, plain)["session"]
    options = {"time": "last"}

    reason = display_runs._time_reason(display_runs._subject_for(SessionFigure(), session), options)

    assert reason == "time names an instant of a run, and this figure draws no single run"
    assert "time" not in options


def test_trial_finds_its_session(project) -> None:
    write_session_dir(project, "cheze-calage")
    trial_dir = project / "sessions" / "cheze-calage" / "trials" / "0001"
    trial_dir.mkdir(parents=True)

    session = Session.of_run(SimpleNamespace(dir=trial_dir, lineage=None))

    assert session is not None
    assert session.name == "cheze-calage"


REFUSALS = [
    (SessionFigure, "plain run", display_figure.NOT_PROMOTED_REASON),
    (RunsetFigure, "plain run", display_figure.NOT_A_RUNSET_REASON),
    (RunFigure, "session", display_figure.NOT_A_RUN_REASON),
]


@pytest.mark.parametrize(("figure", "given", "reason"), REFUSALS)
def test_refusals(monkeypatch, project, promoted, plain, figure, given, reason) -> None:
    instance = figure()
    monkeypatch.setattr(display_runs, "_get_figure", lambda _name: instance)
    obj = objects_of(project, promoted, plain)[given]

    with pytest.raises(ValueError, match="does not apply") as raised:
        display_runs.render_figure(instance.spec.name, obj)

    assert reason in str(raised.value)
    assert instance.calls == []
