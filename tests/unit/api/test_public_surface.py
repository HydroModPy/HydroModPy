"""Public surface snapshot for the functional facade (interface refactor).

Locks which symbols ``hydromodpy`` exposes at the top level so a removed
verb cannot silently reappear and a new one is a deliberate edit here. A name
that left the top level before the first stable version is refused with its new path,
through ``OLD_NAMES``. From that version on a name that moves keeps working for its delay,
through the same table.
"""

from __future__ import annotations

import importlib
import inspect
import re

import pytest

import hydromodpy as hmp
from hydromodpy._lazy import OLD_NAMES, OldName
from hydromodpy.core.old_members import OLD_MEMBERS

pytestmark = [pytest.mark.fast]

# Verbs that must stay reachable as ``hmp.<name>``.
PRESENT = (
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
)

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

# Verbs removed by the interface refactor, before the first stable version:
# merged into ``hmp.open`` / ``hmp.run`` dispatch. They must not come back.
REMOVED = ("open_catalog", "overview", "mesh", "testbed")

# Removed verbs whose name is now a subpackage. Once that package is imported,
# Python binds it on ``hydromodpy``, so ``hmp.<name>`` is the module, never the verb.
SUBPACKAGES = ("mesh",)


@pytest.mark.parametrize("name", PRESENT)
def test_present_symbol(name: str) -> None:
    assert hasattr(hmp, name), f"hmp.{name} missing"
    assert name in hmp.__all__


@pytest.mark.parametrize("name", REMOVED)
def test_a_name_removed_before_the_tag_has_no_entry_and_is_gone(name: str) -> None:
    assert name not in hmp.__all__, f"hmp.{name} must not be in __all__"
    assert name not in OLD_NAMES
    if name in SUBPACKAGES:
        package = importlib.import_module(f"hydromodpy.{name}")
        assert getattr(hmp, name) is package
        assert inspect.ismodule(package) and not callable(package)
        return
    with pytest.raises(AttributeError):
        getattr(hmp, name)


@pytest.mark.parametrize(
    ("old", "new"), [("old_run", "run"), ("OldProject", "Project"), ("old_session", "Session")]
)
def test_a_name_that_moved_after_the_tag_warns_and_forwards(
    old: str, new: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(OLD_NAMES, old, OldName(new, "2.3.0"))

    with pytest.warns(FutureWarning, match=rf"hydromodpy\.{old} is now hydromodpy\.{new}.*2\.3\.0"):
        assert getattr(hmp, old) is getattr(hmp, new)
    assert old not in hmp.__all__


def _resolves(path: str) -> bool:
    """Say whether a dotted path, or the call it starts, names a module or an attribute."""
    path = path.partition("(")[0]
    module, _, attribute = path.rpartition(".")
    try:
        importlib.import_module(path)
    except ModuleNotFoundError:
        return hasattr(importlib.import_module(module), attribute)
    return True


TOP_LEVEL_NAMES = sorted(name for name in OLD_NAMES if "." not in name)


@pytest.mark.parametrize("old", TOP_LEVEL_NAMES)
def test_a_name_that_left_is_refused_with_a_path_that_answers(old: str) -> None:
    entry = OLD_NAMES[old]
    assert entry.refused and old not in hmp.__all__
    with pytest.raises(hmp.OldNameError, match=re.escape(entry.new)):
        getattr(hmp, old)
    assert not hasattr(hmp, old)
    assert _resolves(entry.new), entry.new


@pytest.mark.parametrize("old", sorted(LEFT_IN_2_0_0))
def test_a_name_that_left_in_2_0_0_is_refused_with_the_call_that_replaces_it(old: str) -> None:
    entry = OLD_NAMES[old]
    assert (entry.new, entry.since, entry.refused) == (LEFT_IN_2_0_0[old], "2.0.0", True)
    with pytest.raises(hmp.OldNameError, match=re.escape(f"Use {entry.new}.")):
        getattr(hmp, old)


@pytest.mark.parametrize(
    ("owner", "old", "new"),
    [(hmp.Project, "run", "launch"), (hmp.Project, "best", "best_runs")],
)
def test_a_member_that_left_is_refused_with_its_new_name(owner: type, old: str, new: str) -> None:
    instance = object.__new__(owner)
    object.__setattr__(instance, "_state", None)
    with pytest.raises(hmp.OldNameError, match=new):
        getattr(instance, old)
    assert hasattr(owner, new)
    assert f"{owner.__name__}.{old}" in OLD_NAMES


def test_a_renamed_run_member_is_refused_too() -> None:
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
def test_a_control_is_named_never_positional(name: str) -> None:
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
def test_a_word_that_left_a_signature_is_not_swallowed(function, gone: str, taken: str) -> None:
    parameters = inspect.signature(function).parameters
    assert gone not in parameters and taken in parameters
    assert not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())


def test_the_configuration_of_a_project_is_a_copy_that_refuses_a_change() -> None:
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


def test_the_launch_verb_is_public_and_the_worker_verb_is_not() -> None:
    assert callable(hmp.Project.launch) and callable(hmp.Project._execute)
    assert "Project.workflow_context" in OLD_NAMES or "Project.workflow_context" in OLD_MEMBERS
    assert not hasattr(hmp.Project, "workflow_context")


def test_the_modules_a_plugin_imports_are_listed_and_exist() -> None:
    """The list of ``contracts.rst`` names modules that all import."""
    from pathlib import Path

    page = Path(__file__).parents[3] / "docs/source/contribute/architecture/contracts.rst"
    listed = page.read_text(encoding="utf-8").split(".. public-modules-start")[1]
    modules = re.findall(
        r"^- ``(hydromodpy[\w.]*)``", listed.split(".. public-modules-end")[0], re.M
    )
    assert len(modules) >= 30
    for module in modules:
        importlib.import_module(module)
