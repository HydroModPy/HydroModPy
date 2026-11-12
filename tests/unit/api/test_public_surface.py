"""Names ``hydromodpy`` exposes at the top level, and how a name that left is refused.

A name that left before the first stable version is refused with its new path, through
``OLD_NAMES``. From that version on a name that moves keeps working for its delay,
through the same table. Signatures keep their controls named, never positional.
"""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy._lazy import OLD_NAMES, OldName
from hydromodpy.core.old_members import OLD_MEMBERS
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.run.group import RunSet
from tests._helpers.sealed_runs import make_project

pytestmark = [pytest.mark.fast]

# The names that left the top level in 2.0.0, with the call that replaces each.
LEFT_IN_2_0_0 = {
    "figure": "hydromodpy.show(ref, what='figure', name=...)",
    "report": "hydromodpy.show(ref, what='report')",
    "calibration_phases": "hydromodpy.calibrate(source, dry_run=True)",
    "compare_pair": "hydromodpy.compare([a, b]).table",
    "example_list": "hydromodpy.example()",
    "example_show": "hydromodpy.example(name)",
    "example_add": "hydromodpy.example(name, add=True)",
    "Workspace": "hydromodpy.project.accessors.Workspace",
    "AmbiguousReferenceError": "hydromodpy.results.catalog.discovery.AmbiguousReferenceError",
    "SimulationNotFoundError": "hydromodpy.results.catalog.discovery.SimulationNotFoundError",
    "CatalogError": "hydromodpy.core.exceptions.CatalogError",
    "RunNotSealedError": "hydromodpy.results.errors.RunNotSealedError",
    "FieldNotFoundError": "hydromodpy.results.errors.FieldNotFoundError",
    "ComparisonCaseError": "hydromodpy.project.compare.ComparisonCaseError",
    "ComparisonReferenceError": "hydromodpy.project.compare.ComparisonReferenceError",
}


@pytest.mark.parametrize(
    ("old", "new"), [("old_run", "run"), ("OldProject", "Project"), ("old_session", "Session")]
)
def test_moved_name_warns_and_forwards(old: str, new: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(OLD_NAMES, old, OldName(new, "2.3.0"))

    with pytest.warns(FutureWarning, match=rf"hydromodpy\.{old} is now hydromodpy\.{new}.*2\.3\.0"):
        assert getattr(hmp, old) is getattr(hmp, new)
    assert old not in hmp.__all__


@pytest.mark.parametrize("old", sorted(LEFT_IN_2_0_0))
def test_left_name_is_refused(old: str) -> None:
    entry = OLD_NAMES[old]
    assert (entry.new, entry.since, entry.refused) == (LEFT_IN_2_0_0[old], "2.0.0", True)
    with pytest.raises(hmp.OldNameError, match=re.escape(f"Use {entry.new}.")):
        getattr(hmp, old)


@pytest.mark.parametrize(
    ("owner", "old", "new"),
    [(hmp.Project, "run", "launch"), (hmp.Project, "best", "best_runs")],
)
def test_left_member_is_refused(owner: type, old: str, new: str) -> None:
    instance = object.__new__(owner)
    object.__setattr__(instance, "_state", None)
    with pytest.raises(hmp.OldNameError, match=new):
        getattr(instance, old)
    assert hasattr(owner, new)
    assert f"{owner.__name__}.{old}" in OLD_NAMES


def test_renamed_run_member() -> None:
    with pytest.raises(hmp.OldNameError, match="Run.parameters"):
        object.__new__(hmp.Run).params  # noqa: B018


# What each verb takes by position. Every parameter after them is named.
POSITIONAL = {
    "hmp.run": (hmp.run, 1),
    "Run.read": (hmp.Run.read, 2),
    "Project.simulate": (hmp.Project.simulate, 1),
    "Project.launch": (hmp.Project.launch, 1),
    "Project.rerun": (hmp.Project.rerun, 1),
    "Run.field": (hmp.Run.field, 2),
    "Run.budget": (hmp.Run.budget, 2),
    "Run.timeseries": (hmp.Run.timeseries, 2),
}


@pytest.mark.parametrize("name", POSITIONAL)
def test_controls_are_keyword_only(name: str) -> None:
    function, count = POSITIONAL[name]
    parameters = list(inspect.signature(function).parameters.values())
    kinds = {p.name: p.kind for p in parameters[count:]}
    assert all(kind is inspect.Parameter.KEYWORD_ONLY for kind in kinds.values()), kinds


@pytest.mark.parametrize(
    ("function", "gone", "taken"),
    [
        (hmp.run, "parallel", "set"),
        (hmp.Project.simulate, "parallel", "set"),
        (hmp.Project.rerun, "overrides", "set"),
        (hmp.Run.field, "timestep", "time"),
    ],
)
def test_gone_word_not_swallowed(function, gone: str, taken: str) -> None:
    parameters = inspect.signature(function).parameters
    assert gone not in parameters and taken in parameters
    assert not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())


def test_project_config_is_a_frozen_copy() -> None:
    from hydromodpy.core.config_kit.base import HydroModelBase
    from hydromodpy.core.exceptions import FrozenConfigError

    class Section(HydroModelBase):
        value: int = 1

    project = object.__new__(hmp.Project)
    project._cfg = Section()
    first, second = project.config, project.config

    assert first is not second and first is not project._cfg
    with pytest.raises(FrozenConfigError):
        first.value = 2
    assert project._cfg.value == 1


def test_launch_public_worker_private() -> None:
    assert callable(hmp.Project.launch) and callable(hmp.Project._execute)
    assert "Project.workflow_context" in OLD_NAMES or "Project.workflow_context" in OLD_MEMBERS
    assert not hasattr(hmp.Project, "workflow_context")


def test_plugin_modules_exist() -> None:
    page = Path(__file__).parents[3] / "docs/source/contribute/architecture/contracts.rst"
    listed = page.read_text(encoding="utf-8").split(".. public-modules-start")[1]
    modules = re.findall(
        r"^- ``(hydromodpy[\w.]*)``", listed.split(".. public-modules-end")[0], re.M
    )
    assert len(modules) >= 30
    for module in modules:
        importlib.import_module(module)


def test_two_workspaces_have_two_names() -> None:
    from hydromodpy.core.workspace.workspace import WorkspaceLayout
    from hydromodpy.project.accessors import Workspace

    assert Workspace is not WorkspaceLayout


def test_catalog_repr_html(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    rebuild_index(project)
    cat = Catalog(project)
    try:
        html = cat._repr_html_()
        assert "<b>Catalog</b>" in html
        assert "<table" in html
    finally:
        cat.close()


FLUENT_MEMBERS = [
    pytest.param(RunSet, ("filter", "to_dataframe", "_repr_html_"), id="run set"),
    pytest.param(hmp.Run, ("field", "label", "metrics", "_repr_html_"), id="run"),
]


@pytest.mark.parametrize(("owner", "members"), FLUENT_MEMBERS)
def test_fluent_members(owner: type, members: tuple[str, ...]) -> None:
    assert all(hasattr(owner, name) for name in members)
