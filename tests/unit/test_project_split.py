"""Public surface of :class:`hydromodpy.project.Project` after the interface refactor.

The run-phase verb is :meth:`Project.simulate` (ex-``run``); cheap construction
replaces ``Project.lazy``; the removed ``session()`` / prepared-run primitives
and the ``from_*`` factories are gone. ``Project`` stays focused on model-phase
verbs, ``simulate`` / ``calibrate``, and lifecycle.
"""

from __future__ import annotations

from hydromodpy.project import Project

MAX_PROJECT_METHODS = 15


def test_project_instance_methods_below_limit() -> None:
    """Project keeps a small public method surface."""
    methods = [
        name
        for name, value in vars(Project).items()
        if callable(value) and not name.startswith("_") and not isinstance(value, classmethod)
    ]
    assert len(methods) <= MAX_PROJECT_METHODS, (
        f"Project has {len(methods)} instance methods (max {MAX_PROJECT_METHODS}): {methods}"
    )


def test_project_drops_removed_surface() -> None:
    """The removed run/session/factory surface is gone."""
    for name in (
        "run",
        "lazy",
        "session",
        "from_toml",
        "from_json",
        "from_dict",
        "execute",
        "ingest",
        "render",
        "cleanup",
    ):
        assert not hasattr(Project, name), f"Project still exposes removed {name!r}"


def test_project_keeps_canonical_run_phase_verbs() -> None:
    """``Project`` keeps the high-level run-phase verbs."""
    for name in ("simulate", "calibrate", "prepare", "rerun"):
        assert hasattr(Project, name), f"Project lost canonical verb {name!r}"


def test_project_config_is_a_property() -> None:
    """``cfg`` is replaced by the read-only ``config`` property."""
    assert isinstance(Project.config, property)
    assert not hasattr(Project, "cfg")


def test_project_drops_toml_only_workflow_verbs() -> None:
    """TOML-only workflows live on ``hmp._api``, not on ``Project``."""
    for name in ("overview", "compare", "mesh", "report"):
        assert not hasattr(Project, name), (
            f"Project still exposes {name!r}; the canonical entry point is hmp.{name}()"
        )


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
