"""Smoke tests for the public ``hydromodpy`` API surface.

These checks pin down the names the top level promises: the verbs, the objects they
return and the exception hierarchy. Everything else stays reachable through its module.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project

VERBS = {
    "calibrate",
    "calibration_phases",
    "compare",
    "compare_pair",
    "doctor",
    "example_add",
    "example_list",
    "example_show",
    "export",
    "figure",
    "index",
    "open",
    "read",
    "report",
    "run",
    "spinup",
}
RAISED_BY_PATH = re.compile(r"^\s*hydromodpy\.[\w.]*\.(\w+Error)$", re.M)
OBJECTS = {"Catalog", "HydroModPyConfig", "Project", "Run", "RunSet", "Session", "Workspace"}


def test_the_top_level_is_the_verbs_the_objects_and_the_exceptions() -> None:
    errors = {name for name in hmp.__all__ if _is_a_failure(getattr(hmp, name))}
    assert set(hmp.__all__) - errors == VERBS | OBJECTS | {"__version__"}
    assert all(issubclass(getattr(hmp, name), hmp.HydroModPyError) for name in errors)


def _is_a_failure(value: object) -> bool:
    return isinstance(value, type) and issubclass(value, BaseException)


def test_the_categories_of_the_hierarchy_are_at_the_top_level_and_the_leaves_are_not() -> None:
    import inspect

    from hydromodpy.cli import helpers
    from hydromodpy.core import exceptions

    top = set(hmp.__all__)
    assert {"HydroModPyError", "ConfigError", "DataError", "SolverError", "PipelineError"} <= top
    # Every class that sets an exit code of ``hmp`` is a category.
    source = inspect.getsource(helpers.exit_code_for)
    mapped = {name for name in exceptions.__all__ if re.search(rf"\({name}, EXIT_", source)}
    assert mapped and mapped <= top
    # A leaf stays importable from its module, and is refused at the top level with its path.
    assert "SolverDivergedError" in exceptions.__all__ and "SolverDivergedError" not in top
    with pytest.raises(hmp.OldNameError, match=r"core\.exceptions\.SolverDivergedError"):
        hmp.__getattr__("SolverDivergedError")
    # What a verb says it raises can be caught from the top level.
    documented = (getattr(hmp, name).__doc__ or "" for name in VERBS)
    named = {found for doc in documented for found in RAISED_BY_PATH.findall(doc)}
    assert named and named <= set(hmp.__all__)


def test_the_two_workspaces_have_two_names() -> None:
    from hydromodpy.core.workspace import WorkspaceLayout
    from hydromodpy.project.accessors import Workspace

    assert hmp.Workspace is Workspace
    assert hmp.Workspace is not WorkspaceLayout


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
        assert isinstance(proj.store, hmp.Catalog)
    finally:
        proj.close()


def test_simulation_catalog_repr_html(tmp_path: Path) -> None:
    cat = hmp.Catalog(_empty_index(tmp_path))
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
    cat = hmp.Catalog(_empty_index(tmp_path))
    try:
        for name in ("register_simulation", "export_package", "import_package", "delete"):
            assert not hasattr(cat, name), name
    finally:
        cat.close()


def test_doctor_returns_dict() -> None:
    report = hmp.doctor()
    assert isinstance(report, dict)
    for key in ("python", "hydromodpy", "solvers", "optional"):
        assert key in report


def test_unknown_attribute_raises() -> None:
    with pytest.raises(AttributeError):
        hmp.NotARealThing  # noqa: B018
