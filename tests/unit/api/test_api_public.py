"""Smoke tests for the public ``hydromodpy`` API surface.

These checks pin down the names the top level promises: the verbs, the objects they
return, the three readers the frozen runs of 2.0.0 call and the exception hierarchy. Everything else stays reachable through its module.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.results.catalog import Catalog
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


def test_the_top_level_is_the_verbs_the_objects_and_the_exceptions() -> None:
    errors = {name for name in hmp.__all__ if _is_a_failure(getattr(hmp, name))}
    assert set(hmp.__all__) - errors == VERBS | OBJECTS | KEPT_READERS | {"__version__"}
    assert all(issubclass(getattr(hmp, name), hmp.HydroModPyError) for name in errors)


def _is_a_failure(value: object) -> bool:
    return isinstance(value, type) and issubclass(value, BaseException)


def test_the_categories_of_the_hierarchy_are_at_the_top_level_and_the_leaves_are_not() -> None:
    from hydromodpy.core import exceptions

    top = set(hmp.__all__)
    assert {"HydroModPyError", "ConfigError", "DataError", "SolverError", "PipelineError"} <= top
    # Every exception at the top level lives in core, and every category of an exit code
    # of ``hmp`` is carried by a class at the top level, or caught by one.
    assert all(
        getattr(hmp, name).__module__ == exceptions.__name__
        for name in top - VERBS - OBJECTS - KEPT_READERS - {"__version__"}
    )
    carried = {getattr(hmp, name).category for name in top if _is_a_failure(getattr(hmp, name))}
    from hydromodpy.results.catalog.discovery import AmbiguousReferenceError

    assert set(exceptions.Category) - carried == {exceptions.Category.AMBIGUOUS_REFERENCE}
    assert issubclass(AmbiguousReferenceError, hmp.StorageError)
    # A leaf stays importable from its module, and is refused at the top level with its path.
    assert "SolverDivergedError" in exceptions.__all__ and "SolverDivergedError" not in top
    with pytest.raises(hmp.OldNameError, match=r"core\.exceptions\.SolverDivergedError"):
        hmp.__getattr__("SolverDivergedError")
    # What a verb says it raises can be caught from the top level.
    documented = (getattr(hmp, name).__doc__ or "" for name in VERBS)
    named = {found for doc in documented for found in RAISED_BY_PATH.findall(doc)}
    caught = {
        name
        for name in named
        if any(
            issubclass(_class_of(name), getattr(hmp, top_name))
            for top_name in top
            if _is_a_failure(getattr(hmp, top_name)) and top_name != "HydroModPyError"
        )
    }
    assert named == caught


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
    from hydromodpy.core.workspace import WorkspaceLayout
    from hydromodpy.project.accessors import Workspace

    assert Workspace is not WorkspaceLayout
    with pytest.raises(hmp.OldNameError, match="hydromodpy.project.accessors.Workspace"):
        hmp.Workspace  # noqa: B018


def test_old_simulation_catalog_name_is_not_exposed() -> None:
    # Clean break: the V1 facade is ``Catalog`` / ``RunSet``; the old
    # ``SimulationCatalog`` / ``SimulationGroup`` names are gone (no alias).
    with pytest.raises(AttributeError):
        hmp.SimulationCatalog  # noqa: B018
    with pytest.raises(AttributeError):
        hmp.SimulationGroup  # noqa: B018


def test_removed_batch_api_is_not_exposed() -> None:
    with pytest.raises(AttributeError):
        hmp.batch  # noqa: B018


def _empty_index(tmp_path: Path) -> Path:
    project = make_project(tmp_path / "p")
    rebuild_index(project)
    return project


def test_open_returns_a_project_whose_store_is_the_catalog(tmp_path: Path) -> None:
    proj = hmp.open(_empty_index(tmp_path))
    try:
        assert isinstance(proj, hmp.Project)
        assert isinstance(proj.store, Catalog)
    finally:
        proj.close()


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
    from hydromodpy.results.run import Run

    assert hasattr(Run, "field")
    assert hasattr(Run, "label")
    assert hasattr(Run, "metrics")
    assert hasattr(Run, "_repr_html_")


def test_the_catalog_is_a_reader(tmp_path: Path) -> None:
    """The index is written by the indexer alone: the handle carries no writer."""
    cat = Catalog(_empty_index(tmp_path))
    try:
        for name in ("register_simulation", "export_package", "import_package", "delete"):
            assert not hasattr(cat, name), name
    finally:
        cat.close()


def test_doctor_returns_a_report_whose_dict_holds_the_four_keys() -> None:
    report = hmp.doctor().to_dict()
    assert isinstance(report, dict)
    for key in ("python", "hydromodpy", "solvers", "optional"):
        assert key in report


def test_unknown_attribute_raises() -> None:
    with pytest.raises(AttributeError):
        hmp.NotARealThing  # noqa: B018
