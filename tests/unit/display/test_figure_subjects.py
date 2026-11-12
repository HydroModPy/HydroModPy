"""What a figure draws: a run, a calibration session or a set of runs.

A figure declares its subject in ``FigureSpec.subject``. The display layer
resolves it once from the object a caller passed: a session figure asked for
on a run draws the session that promoted the run and receives the run as the
option ``promoted``; a figure given an object it cannot draw is refused with
a sentence that names what to pass.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import hydromodpy.display.figure as display_figure
import hydromodpy.display.runs as display_runs
from hydromodpy.display.figure import PROMOTED_OPTION, SUBJECTS, BaseFigure, FigureSpec
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
PAIR_FIGURES = ("difference_map", "side_by_side", "conditioning_impact_map")


def _expected_subject(name: str) -> str:
    if name in SESSION_FIGURES:
        return "session"
    if name in RUNSET_FIGURES:
        return "runset"
    return "run"


@pytest.mark.parametrize("spec", list_figures(), ids=lambda spec: spec.name)
def test_each_registered_figure_declares_its_subject(spec: FigureSpec) -> None:
    assert spec.subject in SUBJECTS
    assert spec.subject == _expected_subject(spec.name)


@pytest.mark.parametrize("option", ["subject", PROMOTED_OPTION])
def test_what_the_display_layer_fills_is_never_a_user_option(option: str) -> None:
    from hydromodpy.display.figure import option_names_of

    class _TakesAPromotedRun(_Drawn):
        spec = FigureSpec(name="takes_promoted", title="t", subject="session")

        def render(self, subject: Any, ax: Any, *, promoted: Any = None, **_: Any) -> Any:
            return ax

    assert option not in option_names_of(_TakesAPromotedRun)


# --- resolving the subject ---


class _Drawn(BaseFigure):
    """A figure that records what it was handed instead of drawing."""

    spec = FigureSpec(name="drawn", title="Drawn")

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def render(self, subject: Any, ax: Any, **opts: Any) -> Any:
        self.calls.append((subject, opts))
        return ax


class _RunFigure(_Drawn):
    spec = FigureSpec(name="a_run_figure", title="Run")


class _SessionFigure(_Drawn):
    spec = FigureSpec(name="a_session_figure", title="Session", subject="session")


class _RunsetFigure(_Drawn):
    spec = FigureSpec(name="a_runset_figure", title="Runset", subject="runset")


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


def _objects(project: Path, promoted: Any, plain: Any) -> dict[str, Any]:
    return {
        "promoted run": promoted,
        "plain run": plain,
        "session": Session(project / "sessions" / "cheze-calage"),
        "runset": RunSet([], SimpleNamespace()),
    }


SUBJECT_CASES = [
    # figure, object, what render receives, refusal
    (_RunFigure, "plain run", "plain run", None),
    (_RunFigure, "promoted run", "promoted run", None),
    (_RunFigure, "session", None, display_figure.NOT_A_RUN_REASON),
    (_RunFigure, "runset", None, display_figure.NOT_A_RUN_REASON),
    (_SessionFigure, "promoted run", "session", None),
    (_SessionFigure, "session", "session", None),
    (_SessionFigure, "plain run", None, display_figure.NOT_PROMOTED_REASON),
    (_SessionFigure, "runset", None, display_figure.NOT_A_SESSION_REASON),
    (_RunsetFigure, "runset", "runset", None),
    (_RunsetFigure, "plain run", None, display_figure.NOT_A_RUNSET_REASON),
    (_RunsetFigure, "promoted run", None, display_figure.NOT_A_RUNSET_REASON),
    (_RunsetFigure, "session", None, display_figure.NOT_A_RUNSET_REASON),
]


@pytest.mark.parametrize(
    ("figure", "given", "drawn", "reason"),
    SUBJECT_CASES,
    ids=[f"{case[0].spec.subject} figure given a {case[1]}" for case in SUBJECT_CASES],
)
def test_the_subject_is_resolved_once_from_what_the_caller_passed(
    project, promoted, plain, figure, given, drawn, reason
) -> None:
    objects = _objects(project, promoted, plain)

    subject = display_runs._subject_for(figure(), objects[given])

    assert subject.reason == reason
    assert display_runs.unavailable_reason(figure(), objects[given]) == reason
    if drawn is None:
        return
    if drawn == "session":
        assert isinstance(subject.drawn, Session)
        assert subject.drawn.dir == (project / "sessions" / "cheze-calage").resolve()
    else:
        assert subject.drawn is objects[drawn]
    if figure is _SessionFigure and given == "promoted run":
        assert subject.options == {PROMOTED_OPTION: promoted}
        assert subject.run is promoted
    else:
        assert subject.options == {}


def test_the_sentence_of_a_run_no_session_promoted() -> None:
    assert display_figure.NOT_PROMOTED_REASON == (
        "draws the calibration session that promoted a run; this run was not promoted by a session"
    )
    assert display_figure.NOT_A_RUNSET_REASON == "draws the envelope of several runs; pass a RunSet"


def test_a_batch_looks_the_session_of_a_run_up_once(monkeypatch, promoted) -> None:
    asked: list[Any] = []

    def counting(run: Any) -> Session | None:
        asked.append(run)
        return None

    monkeypatch.setattr(Session, "of_run", staticmethod(counting))
    session_of = display_runs._memoised_session_of()
    for _ in range(3):
        display_runs._subject_for(_SessionFigure(), promoted, session_of=session_of)
    assert asked == [promoted]


@pytest.mark.parametrize(
    ("figure", "given", "drawn_type"),
    [
        (_SessionFigure, "promoted run", Session),
        (_RunFigure, "plain run", SimpleNamespace),
    ],
)
def test_render_figure_hands_the_figure_its_subject(
    monkeypatch, tmp_path, project, promoted, plain, figure, given, drawn_type
) -> None:
    instance = figure()
    monkeypatch.setattr(display_runs, "_get_figure", lambda _name: instance)
    obj = _objects(project, promoted, plain)[given]

    display_runs.render_figure(instance.spec.name, obj, save=tmp_path / "out.png")

    ((subject, opts),) = instance.calls
    assert isinstance(subject, drawn_type)
    if figure is _SessionFigure:
        assert opts[PROMOTED_OPTION] is promoted
    else:
        assert PROMOTED_OPTION not in opts
    assert (tmp_path / "out.png").is_file()


@pytest.mark.parametrize(
    ("figure", "given", "reason"),
    [
        (_SessionFigure, "plain run", display_figure.NOT_PROMOTED_REASON),
        (_RunsetFigure, "plain run", display_figure.NOT_A_RUNSET_REASON),
        (_RunFigure, "session", display_figure.NOT_A_RUN_REASON),
    ],
)
def test_render_figure_refuses_a_subject_the_figure_cannot_draw(
    monkeypatch, project, promoted, plain, figure, given, reason
) -> None:
    instance = figure()
    monkeypatch.setattr(display_runs, "_get_figure", lambda _name: instance)
    obj = _objects(project, promoted, plain)[given]

    with pytest.raises(ValueError, match="does not apply") as raised:
        display_runs.render_figure(instance.spec.name, obj)

    assert reason in str(raised.value)
    assert instance.calls == []


def test_a_subject_without_a_run_takes_no_time(project, promoted, plain) -> None:
    # A [display] time reaches every figure that draws one instant; a session
    # drawn alone holds no period to place it in.
    session = _objects(project, promoted, plain)["session"]
    options = {"time": "last"}

    reason = display_runs._time_reason(
        display_runs._subject_for(_SessionFigure(), session), options
    )

    assert reason == "time names an instant of a run, and this figure draws no single run"
    assert "time" not in options


# --- the session of a run ---


def test_a_kept_trial_is_in_its_own_session(project) -> None:
    write_session_dir(project, "cheze-calage")
    trial_dir = project / "sessions" / "cheze-calage" / "trials" / "0001"
    trial_dir.mkdir(parents=True)

    session = Session.of_run(SimpleNamespace(dir=trial_dir, lineage=None))

    assert session is not None
    assert session.name == "cheze-calage"
