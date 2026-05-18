"""Split of :class:`hydromodpy.project.Project` into model and run phases.

P8 caps :class:`Project` at <= 15 instance methods (model-phase verbs +
lifecycle). Run-phase orchestration primitives move to
:class:`hydromodpy.project.session.ProjectSession` returned by
:meth:`Project.session`.
"""

from __future__ import annotations

from hydromodpy.project import Project
from hydromodpy.project.session import ProjectSession

MAX_PROJECT_METHODS = 15


def test_project_instance_methods_below_limit() -> None:
    """Project exposes at most 15 instance methods after the P8 split."""
    methods = [
        name
        for name, value in vars(Project).items()
        if callable(value) and not name.startswith("_") and not isinstance(value, classmethod)
    ]
    assert len(methods) <= MAX_PROJECT_METHODS, (
        f"Project has {len(methods)} instance methods (max {MAX_PROJECT_METHODS}): {methods}"
    )


def test_project_session_factory_returns_session() -> None:
    """``Project.session`` is the canonical entry to the run-phase facade."""
    assert hasattr(Project, "session")


def test_project_session_owns_prepared_run_primitives() -> None:
    """Prepared-run primitives are on :class:`ProjectSession`, not Project."""
    for name in ("prepare", "execute", "ingest", "render", "cleanup", "simulate", "sweep"):
        assert hasattr(ProjectSession, name), f"ProjectSession is missing {name!r}"


def test_project_no_longer_exposes_prepared_run_primitives() -> None:
    """``Project`` does not duplicate the prepared-run primitives."""
    for name in ("prepare", "execute", "ingest", "render", "cleanup", "simulate", "sweep"):
        assert not hasattr(Project, name), (
            f"Project still exposes {name!r}; move it to ProjectSession."
        )


def test_project_keeps_canonical_run_phase_verbs() -> None:
    """``Project`` keeps the high-level run-phase verbs used by the CLI."""
    for name in ("run", "calibrate", "mesh", "report", "overview", "compare"):
        assert hasattr(Project, name), f"Project lost canonical verb {name!r}"


def test_project_keeps_model_phase_verbs() -> None:
    """``Project`` keeps the model-phase verbs that mutate the context."""
    for name in (
        "setup_workspace",
        "build_geographic",
        "load_data",
        "reload_data",
        "rebuild_geographic",
        "build_mesh",
    ):
        assert hasattr(Project, name), f"Project lost model-phase verb {name!r}"


def test_project_session_repr() -> None:
    """Smoke-check :class:`ProjectSession` repr (no Project init required)."""

    class _FakeProject:
        def __init__(self) -> None:
            self._runner = object()

        def __repr__(self) -> str:
            return "FakeProject()"

    sess = ProjectSession(_FakeProject())
    assert "ProjectSession" in repr(sess)
