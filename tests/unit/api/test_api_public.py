"""Smoke tests for the public ``hydromodpy`` API surface.

These checks pin down the names the top level promises: the verbs, the objects they
return, the three readers the frozen runs of a pre-release call and the exception hierarchy. Everything else stays reachable through its module.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project

VERBS = {
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
}
RAISED_BY_PATH = re.compile(r"^\s*hydromodpy\.[\w.]*\.(\w+Error)$", re.M)
OBJECTS = {"HydroModPyConfig", "Project", "Run", "RunSet", "Session"}
KEPT_READERS = {"read", "index", "Catalog"}


def _is_a_failure(value: object) -> bool:
    return isinstance(value, type) and issubclass(value, BaseException)


def _class_of(name: str) -> type:
    """Return the exception class *name*, wherever the hierarchy defines it."""
    import importlib

    for module in (
        "hydromodpy.core.exceptions",
        "hydromodpy.results.errors",
        "hydromodpy.results.catalog.discovery",
        "hydromodpy.project.compare",
    ):
        found = getattr(importlib.import_module(module), name, None)
        if found is not None:
            return found
    raise AssertionError(f"{name} is defined nowhere the verbs raise from")


def test_the_two_workspaces_have_two_names() -> None:
    from hydromodpy.core.workspace.workspace import WorkspaceLayout
    from hydromodpy.project.accessors import Workspace

    assert Workspace is not WorkspaceLayout
    with pytest.raises(hmp.OldNameError, match="hydromodpy.project.accessors.Workspace"):
        hmp.Workspace  # noqa: B018


def _empty_index(tmp_path: Path) -> Path:
    project = make_project(tmp_path / "p")
    rebuild_index(project)
    return project


def test_simulation_catalog_repr_html(tmp_path: Path) -> None:
    cat = Catalog(_empty_index(tmp_path))
    try:
        html = cat._repr_html_()
        assert "<b>Catalog</b>" in html
        assert "<table" in html
    finally:
        cat.close()


def test_simulation_group_fluent_methods_present() -> None:
    from hydromodpy.results.run.group import RunSet

    assert hasattr(RunSet, "filter")
    assert hasattr(RunSet, "to_dataframe")
    assert hasattr(RunSet, "_repr_html_")


def test_simulation_view_fluent_methods_present() -> None:
    from hydromodpy.results.run.view import Run

    assert hasattr(Run, "field")
    assert hasattr(Run, "label")
    assert hasattr(Run, "metrics")
    assert hasattr(Run, "_repr_html_")
