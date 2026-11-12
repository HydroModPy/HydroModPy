"""What is public and held: surfaces, registers, tolerances, variables, exceptions.

The public surfaces are compared with their snapshots, the facade holds its
fifteen verbs, the register of changes has a reader for every row, the
tolerance table has one source, every ``HMP_*`` name has a row, and a scoped
layer raises typed exceptions only. A CI step that runs tests in parallel
leaves out the Whitebox tests, and the active tree names no legacy
vocabulary.
"""

from __future__ import annotations

import ast
import builtins
import collections.abc
import json
import os
import pathlib
import re
import types
import typing
from collections.abc import Callable
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pandas as pd
import pytest
import yaml
from packaging.version import Version

import hydromodpy as hmp
from hydromodpy import _lazy
from hydromodpy._lazy import OLD_NAMES, OldName
from hydromodpy.cli import conventions
from hydromodpy.config.config_migration import RULES as CONFIG_RULES
from hydromodpy.core.runtime.env import ENV_SCOPES, ENV_VARS, env_var
from hydromodpy.core.version import __version__
from hydromodpy.project import api
from hydromodpy.results.record.forms import RULES as RUN_SEAL_RULES
from hydromodpy.schema import changes
from hydromodpy.schema.changes import REGISTER, REGISTER_FILENAME, migrations_of, outlived, read
from hydromodpy.schema.job.seal import JOB_SEAL_RULES
from tests._helpers.tolerances import TOLERANCES, tol
from tests.conftest import _WHITEBOX_XDIST_GROUP_TEST_FILES
from tests.unit.architecture import _scan
from tests.unit.architecture._scan import PKG_ROOT, REPO_ROOT, Rule, offences, parse
from tools import surface_snapshot as surface
from tools.docs.contribute_data import env_var_references

pytestmark = pytest.mark.fast

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


# ---------------------------------------------------------------------------
# Public surfaces cannot change without someone saying so
# ---------------------------------------------------------------------------


ROW_ONE = "a.b\tint\t1\tstable"


def test_the_frozen_step_names_are_the_steps_of_the_pipeline() -> None:
    from hydromodpy.core.pipeline_steps import STEP_NAMES
    from hydromodpy.workflow.steps.sequence import standard_steps

    assert tuple(step.name for step in standard_steps()) == STEP_NAMES


@pytest.mark.parametrize("name", sorted(surface.SURFACES))
def test_a_surface_equals_its_snapshot(name: str) -> None:
    difference = surface.compare(
        surface.read_rows(surface.SNAPSHOT_DIR / name), surface.rows_of(name)
    )
    assert not difference, (
        f"tests/unit/architecture/surface/{name} no longer matches this build:\n"
        f"{difference.describe()}\n"
        f"If this is on purpose, run `{surface.REGENERATE}` and commit the files. A removed "
        "public name goes in the changelog with its replacement, and a removed TOML key needs "
        "its [[migration]] row in hydromodpy/schema/changes.toml first. From the first stable "
        "version on, a removed Python name or hmp flag needs its entry in hydromodpy/_lazy.py "
        "or hydromodpy/cli/conventions.py first."
    )


def _without_their_entry(rows: list[str], entry_of: Callable[[str], Any]) -> list[str]:
    """Return the names of a ledger whose delay runs and that nothing keeps working."""
    return [
        row.split("\t")[0]
        for row in rows
        if entry_of(row.split("\t")[0]) is None and not outlived(row.split("\t")[1], __version__)
    ]


def test_a_removed_toml_key_keeps_its_migration_until_its_delay_ends() -> None:
    """A row of the register or a line of ``prerelease_forms.txt`` keeps each key answered."""
    ledger = surface.read_rows(surface.SNAPSHOT_DIR / surface.REMOVED_TOML_KEYS)
    missing = _without_their_entry(ledger, surface.toml_entry_for)
    assert missing == [], (
        f"{missing} left the grammar and hydromodpy/schema/changes.toml has no row for them."
    )


def test_a_removed_name_keeps_its_entry_until_its_delay_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = surface.read_rows(surface.SNAPSHOT_DIR / surface.REMOVED_NAMES)
    missing = _without_their_entry(ledger, surface.entry_for)
    assert missing == [], f"{missing} left the surface and no table keeps them working."

    assert _without_their_entry(["gone\t2.0.0"], surface.entry_for) == ["gone"]
    monkeypatch.setitem(OLD_NAMES, "gone", OldName("run", "2.0.0"))
    assert _without_their_entry(["gone\t2.0.0"], surface.entry_for) == []


def test_an_entry_that_outlives_its_delay_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_lazy, "OLD_NAMES", {"gone": OldName("run", "2.0.0")})
    form = conventions.OldCliForm("hmp old", "hmp new", "2.0.0")
    monkeypatch.setattr(conventions, "OLD_CLI_FORMS", (form,))

    assert surface.outlived_interface_forms("2.1.9") == ()
    late = surface.outlived_interface_forms("2.2.0a1")
    assert [entry.old for entry in late] == ["gone", "hmp old"]


def test_the_delay_of_the_interface_tables_is_the_one_of_the_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``schema.changes`` writes the delay once, and the surface gate reads no other."""
    monkeypatch.setattr(_lazy, "OLD_NAMES", {"gone": OldName("run", "2.0.0")})
    monkeypatch.setattr(
        conventions, "OLD_CLI_FORMS", (conventions.OldCliForm("hmp old", "hmp new", "2.1.0"),)
    )

    assert [entry.old for entry in surface.outlived_interface_forms("2.2.0")] == ["gone"]
    assert [entry.old for entry in surface.outlived_interface_forms("2.3.0")] == ["gone", "hmp old"]

    monkeypatch.setattr(changes, "DELAY_MINORS", changes.DELAY_MINORS + 1)

    assert surface.outlived_interface_forms("2.2.0") == ()
    assert [entry.old for entry in surface.outlived_interface_forms("2.3.0")] == ["gone"]


def test_an_old_form_of_hmp_is_not_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    before = surface.rows_of(surface.CLI_SURFACE)
    forms = (
        conventions.OldCliForm("hmp ls --old", "hmp ls --format", "2.3.0"),
        conventions.OldCliForm("hmp status", "hmp ls", "2.3.0"),
    )
    monkeypatch.setattr(conventions, "OLD_CLI_FORMS", forms)

    assert surface.rows_of(surface.CLI_SURFACE) == before


def test_a_change_is_named_by_kind() -> None:
    difference = surface.compare(
        [ROW_ONE, "gone\tint\t1\tstable"], ["a.b\tint\t2\tstable", "new\tint\t1\tstable"]
    )
    assert difference.removed == ("gone",)
    assert difference.added == ("new",)
    assert difference.changed == (("a.b", (ROW_ONE,), ("a.b\tint\t2\tstable",)),)
    assert "removed: gone" in difference.describe()
    assert not surface.compare([ROW_ONE], [ROW_ONE])


def test_an_experimental_key_can_leave_and_a_stable_one_is_counted() -> None:
    before = ["a\tint\t1\tstable", f"b\tint\t1\t{surface.EXPERIMENTAL}", ROW_ONE]
    assert surface.stable_removals(before, [ROW_ONE]) == ["a"]
    assert surface.stable_removals(before, [ROW_ONE], demoted=["b"]) == ["a", "b"]


def _snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, keys: list[str]) -> Path:
    """Stand in for the real surfaces with one fake TOML surface and the snapshot of it."""
    monkeypatch.setattr(surface, "SURFACES", {surface.TOML_SURFACE: lambda: list(keys)})
    (tmp_path / surface.TOML_SURFACE).write_text(
        "modflow6.hclose\tfloat\t1.0\tstable\nnever.migrated\tint\t1\tstable\nkept\tint\t1\tstable\n",
        encoding="utf-8",
    )
    return tmp_path


def test_regenerating_refuses_a_stable_key_without_a_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _snapshots(
        tmp_path, monkeypatch, keys=["modflow6.hclose\tfloat\t1.0\tstable", "kept\tint\t1\tstable"]
    )
    before = (directory / surface.TOML_SURFACE).read_text(encoding="utf-8")

    refused = surface.regenerate(directory)

    assert len(refused) == 1
    assert "never.migrated" in refused[0] and "hydromodpy/schema/changes.toml" in refused[0]
    assert (directory / surface.TOML_SURFACE).read_text(encoding="utf-8") == before


def test_regenerating_records_a_key_that_has_its_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _snapshots(
        tmp_path, monkeypatch, keys=["never.migrated\tint\t1\tstable", "kept\tint\t1\tstable"]
    )

    assert surface.regenerate(directory) == []

    ledger = surface.read_rows(directory / surface.REMOVED_TOML_KEYS)
    assert ledger == [f"modflow6.hclose\t{surface.installed_release()}"]
    assert surface.read_rows(directory / surface.TOML_SURFACE) == [
        "kept\tint\t1\tstable",
        "never.migrated\tint\t1\tstable",
    ]


def _fake_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, before: dict[str, Any], after: dict[str, Any]
) -> Path:
    """Stand in for the real surfaces: write the snapshots *before*, build gives *after*."""
    monkeypatch.setattr(
        surface,
        "SURFACES",
        {name: (lambda rows=rows: list(rows)) for name, rows in after.items()},
    )
    for name, rows in before.items():
        (tmp_path / name).write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")
    return tmp_path


def _at_the_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(surface, "before_the_tag", lambda: False)


NAMES_THAT_LEAVE = (
    (surface.FACADE_SURFACE, ["gone\tfunction\t()", "kept\tfunction\t()"], "gone"),
    (surface.CLI_SURFACE, ["hmp a\tcommand", "hmp a --gone,-g\t"], "hmp a --gone"),
    (surface.CLI_SURFACE, ["hmp a\tcommand", "hmp a --gone,-g\t"], "hmp a -g"),
    (surface.CLI_SURFACE, ["hmp a\tcommand", "hmp gone\tcommand", "hmp gone --x\t"], "hmp gone"),
)


"""A surface, its rows before, and one name that leaves when only the first command stays."""


def _kept(rows: list[str]) -> list[str]:
    return [row for row in rows if "gone" not in row]


def _entries_for(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if name.startswith("hmp "):
        forms = tuple(
            conventions.OldCliForm(old, "hmp a", "2.3.0")
            for old in ("hmp a --gone", "hmp a -g", "hmp gone")
        )
        monkeypatch.setattr(conventions, "OLD_CLI_FORMS", forms)
    else:
        monkeypatch.setitem(OLD_NAMES, name, OldName("kept", "2.3.0"))


@pytest.mark.parametrize(("name", "rows", "gone"), NAMES_THAT_LEAVE)
def test_before_the_tag_a_name_leaves_with_no_entry(
    name: str, rows: list[str], gone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(surface, "before_the_tag", lambda: True)
    directory = _fake_surfaces(
        tmp_path,
        monkeypatch,
        {name: rows},
        {name: _kept(rows), surface.TOML_SURFACE: []},
    )

    assert surface.regenerate(directory) == []
    assert surface.read_rows(directory / surface.REMOVED_NAMES) == []


@pytest.mark.parametrize(("name", "rows", "gone"), NAMES_THAT_LEAVE)
def test_from_the_tag_a_name_needs_its_entry_to_leave(
    name: str, rows: list[str], gone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _at_the_tag(monkeypatch)
    directory = _fake_surfaces(
        tmp_path,
        monkeypatch,
        {name: rows},
        {name: _kept(rows), surface.TOML_SURFACE: []},
    )

    refused = surface.regenerate(directory)
    assert any(line.startswith(f"{gone}: ") for line in refused)
    assert surface.read_rows(directory / name) == rows

    _entries_for(gone, monkeypatch)
    assert surface.regenerate(directory) == []
    ledger = surface.read_rows(directory / surface.REMOVED_NAMES)
    assert f"{gone}\t{surface.installed_release()}" in ledger
    assert surface.read_rows(directory / name) == _kept(rows)


def test_a_positional_may_leave_with_no_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _at_the_tag(monkeypatch)
    rows = ["hmp a\tcommand", "hmp a <gone>\t"]
    directory = _fake_surfaces(
        tmp_path,
        monkeypatch,
        {surface.CLI_SURFACE: rows},
        {surface.CLI_SURFACE: rows[:1], surface.TOML_SURFACE: []},
    )

    assert surface.regenerate(directory) == []


def test_a_stable_key_marked_experimental_still_needs_its_migration_to_leave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(surface, "before_the_tag", lambda: True)
    stable, marked = (
        "never.migrated\tint\t1\tstable",
        f"never.migrated\tint\t1\t{surface.EXPERIMENTAL}",
    )
    directory = _fake_surfaces(
        tmp_path, monkeypatch, {surface.TOML_SURFACE: [stable]}, {surface.TOML_SURFACE: [marked]}
    )
    assert surface.regenerate(directory) == []
    assert surface.read_rows(directory / surface.DEMOTED_TOML_KEYS) == ["never.migrated"]

    _fake_surfaces(tmp_path, monkeypatch, {}, {surface.TOML_SURFACE: []})
    refused = surface.regenerate(directory)

    assert len(refused) == 1 and refused[0].startswith("never.migrated: ")


def test_from_the_tag_a_stable_key_cannot_be_marked_experimental(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _at_the_tag(monkeypatch)
    stable, marked = "a.b\tint\t1\tstable", f"a.b\tint\t1\t{surface.EXPERIMENTAL}"
    directory = _fake_surfaces(
        tmp_path, monkeypatch, {surface.TOML_SURFACE: [stable]}, {surface.TOML_SURFACE: [marked]}
    )

    refused = surface.regenerate(directory)

    assert len(refused) == 1 and "marked experimental" in refused[0]
    assert surface.read_rows(directory / surface.TOML_SURFACE) == [stable]


def test_a_form_the_loader_only_refuses_is_no_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A line of ``prerelease_forms.txt`` holds a key of the ledger, never a key that leaves now."""
    directory = _fake_surfaces(
        tmp_path,
        monkeypatch,
        {surface.TOML_SURFACE: ["data.project_crs\tstr\t'a'\tstable"]},
        {surface.TOML_SURFACE: []},
    )

    refused = surface.regenerate(directory)

    assert len(refused) == 1 and refused[0].startswith("data.project_crs: ")


_RETIRE_ROWS = (
    'schema = "hydromodpy.changes.v1"\n'
    '[[migration]]\ndocument = "config"\nold = "table.left"\n'
    'instead = "Write table.right."\nsince = "2.1.0"\n'
    '[[migration]]\ndocument = "config"\nold = "table.moved_by_a_rule"\n'
    'instead = "Write table.right."\nsince = "2.1.0"\nrule = "a_rule"\n'
    '[[migration]]\ndocument = "sidecar"\nold = "sidecar_key"\nnew = "sidecar_new"\n'
    'since = "2.1.0"\n'
)


@pytest.mark.parametrize(
    ("path", "covered"),
    [
        pytest.param("table.left", False, id="a key that left with nothing to write"),
        pytest.param("table.moved_by_a_rule", True, id="a key a rule writes elsewhere"),
        pytest.param("table.moved_by_a_rule.sub", True, id="a key under it"),
        pytest.param("sidecar_key", False, id="a row of another document"),
    ],
)
def test_only_a_row_that_rewrites_counts_as_a_migration(
    path: str, covered: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = changes.read(_RETIRE_ROWS)
    monkeypatch.setattr(
        surface, "migrations_of", lambda document: changes.migrations_of(document, fixture)
    )

    assert (surface.migration_for(path) is not None) is covered


@pytest.mark.parametrize(
    ("path", "row", "line"),
    [
        # A pre-release key is a line of the list, never a row of the register.
        ("data.project_crs", False, True),
        ("calibration.max_iter", False, True),
        ("calibration.phases.max_iter", False, True),
        ("calibration.parameters.transform", False, True),
        ("flow.active_bc", False, True),
        ("workspace.catalog_path", False, True),
        # A line holds what lies below it, as a row does.
        ("calibration.outputs.extent.weights", False, True),
        # Covered by the move of the whole [modflow6] table to [solver.modflow6].
        ("modflow6.process_specific.vka", True, False),
        ("modflow6.sgrid", True, False),
        # The row and the line both hold a table that a pre-release wrote under [modflow6].
        ("modflow6.sgrid.vertical.nlay", True, True),
        # Retired with a rule that writes the key elsewhere.
        ("geographic.catchment.dem_init_path", True, False),
        # Written by hmp init of a pre-release, so it has a row of 2.0.0 and no line.
        ("simulation.process.type", True, False),
        # The parent of a moved table is not moved with it.
        ("flow", False, False),
        ("calibration.max_trials", False, False),
        # A line of one value covers no key: the key stays with its other values.
        ("simulation.if_exists", False, False),
        ("display.figures", False, False),
        ("geographic.catchment.buff_area", False, False),
        # A line of the tables under a key covers what lies below it, not the key.
        ("export.variables", False, False),
        ("export.variables.head", False, True),
    ],
)
def test_a_path_finds_the_row_or_the_line_that_covers_it(path: str, row: bool, line: bool) -> None:
    assert (surface.migration_for(path) is not None) is row
    assert (surface.prerelease_form_for(path) is not None) is line
    assert (surface.toml_entry_for(path) is not None) is (row or line)


# ---------------------------------------------------------------------------
# The facade holds fifteen typed verbs and five objects
# ---------------------------------------------------------------------------


VERBS = (
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


"""The fifteen verbs, in the order of the architecture."""


HOMES = {
    "Project": "hydromodpy.project.facade",
    "Run": "hydromodpy.results.run.view",
    "RunSet": "hydromodpy.results.run.group",
    "Session": "hydromodpy.results.session.view",
    "HydroModPyConfig": "hydromodpy.config.hydromodpy_config",
}


"""Where each of the five objects is defined."""


KEPT_READERS = ("read", "index", "Catalog")


"""The three readers kept beside the verbs, because the frozen runs of a pre-release of 2.0 call them."""


COMMANDS = {
    "run.py": "run",
    "check.py": "check",
    "calibrate.py": "calibrate",
    "spinup.py": "spinup",
    "replay.py": "replay",
    "stop.py": "stop",
    "export.py": "export",
    "publish.py": "publish",
    "doctor.py": "doctor",
    "ls.py": "status",
    "show.py": "show",
    "diff.py": "compare",
    "example/list_cmd.py": "example",
    "example/show.py": "example",
    "example/add.py": "example",
    "catalog/trash.py": "trash",
    "catalog/restore.py": "trash",
}


"""Each command of ``hmp`` that stands for a verb, under ``hydromodpy/cli/commands``."""


EXEMPT_RETURNS = frozenset({"open", "show"})


"""``open`` returns the Python objects, and ``show`` the data itself unless ``save`` is given."""


MAX_API_LINES = 1500


def _namespace() -> dict[str, Any]:
    """The names ``project/api.py`` keeps under ``TYPE_CHECKING``, for its hints."""
    import xarray as xr
    from matplotlib.figure import Figure

    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.model.initial_config import SpinupConfig
    from hydromodpy.project.accessors import Workspace
    from hydromodpy.project.calibrate import CalibrationPlan
    from hydromodpy.project.compare import Comparison
    from hydromodpy.project.doctor import DoctorReport
    from hydromodpy.project.examples.install import InstallReport
    from hydromodpy.project.examples.manifest import ExampleEntry
    from hydromodpy.project.launch.status import StatusReport
    from hydromodpy.project.spinup import SpinupResult
    from hydromodpy.results.export.publish import PublishedProject
    from hydromodpy.results.publication import PublishedLine
    from hydromodpy.workflow.overview import OverviewResult

    names = {
        "pd": pd,
        "xr": xr,
        "Figure": Figure,
        "CalibrationReport": CalibrationReport,
        "SpinupConfig": SpinupConfig,
        "Workspace": Workspace,
        "CalibrationPlan": CalibrationPlan,
        "Comparison": Comparison,
        "DoctorReport": DoctorReport,
        "InstallReport": InstallReport,
        "ExampleEntry": ExampleEntry,
        "StatusReport": StatusReport,
        "SpinupResult": SpinupResult,
        "PublishedProject": PublishedProject,
        "PublishedLine": PublishedLine,
        "OverviewResult": OverviewResult,
    }
    return {**vars(api), **names}


def _hints(name: str) -> dict[str, Any]:
    return typing.get_type_hints(getattr(api, name), globalns=_namespace())


def _conveniences() -> tuple[type, ...]:
    """The Python objects a parameter may take besides plain data."""
    from hydromodpy.model.initial_config import SpinupConfig
    from hydromodpy.project.environment import Environment
    from hydromodpy.project.request import RunRequest

    return (
        hmp.HydroModPyConfig,
        RunRequest,
        hmp.Run,
        hmp.Session,
        hmp.RunSet,
        hmp.Project,
        Environment,
        SpinupConfig,
    )


PLAIN = (str, int, float, bool, type(None), Path, os.PathLike)


def _serializable_parameter(hint: Any) -> bool:
    if hint is Any:
        return False
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin in (typing.Union, types.UnionType):
        return all(_serializable_parameter(arg) for arg in args)
    if origin is Literal:
        return True
    if origin is os.PathLike:
        return args == (str,)
    if origin in (collections.abc.Mapping, dict):
        return args[0] is str
    if origin in (collections.abc.Sequence, list, tuple):
        return all(arg is Ellipsis or _serializable_parameter(arg) for arg in args)
    return isinstance(hint, type) and issubclass(hint, PLAIN + _conveniences())


def _serializable_return(hint: Any) -> bool:
    from hydromodpy.core.diagnostic import Diagnostic
    from hydromodpy.results.publication import PublishedLine

    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin in (typing.Union, types.UnionType):
        return all(_serializable_return(arg) for arg in args)
    if hint is type(None) or hint is Path:
        return True
    if origin is list:
        return args[0] in (Path, Diagnostic) or callable(getattr(args[0], "to_dict", None))
    if origin is tuple:
        return args[1] is Ellipsis and (
            args[0] is PublishedLine or callable(getattr(args[0], "to_dict", None))
        )
    return isinstance(hint, type) and callable(getattr(hint, "to_dict", None))


def test_the_top_level_is_the_verbs_the_objects_the_categories_and_the_version() -> None:
    names = [name for name in hmp.__all__ if name != "__version__"]
    failures = [name for name in names if isinstance(getattr(hmp, name), type)]
    failures = [name for name in failures if issubclass(getattr(hmp, name), BaseException)]
    assert [name for name in names if name not in failures] == [*VERBS, *HOMES, *KEPT_READERS]
    assert all(getattr(hmp, name).__module__ == "hydromodpy.core.exceptions" for name in failures)


def test_the_api_holds_the_fifteen_verbs_and_defines_each() -> None:
    assert api.__all__ == list(VERBS)
    for name in VERBS:
        assert getattr(api, name).__module__ == "hydromodpy.project.api", name
        assert getattr(hmp, name) is getattr(api, name), name


def test_the_kept_readers_are_the_ones_the_frozen_runs_call() -> None:
    """``tests/regression/frozen_runs`` reads its runs through ``hmp.read``,
    ``hmp.index`` and ``hmp.Catalog``, so they stay at the top level beside the verbs."""
    from hydromodpy.project import kept_readers
    from hydromodpy.results.catalog.facade import Catalog

    frozen = (REPO_ROOT / "tests" / "regression" / "frozen_runs" / "test_frozen_runs.py").read_text(
        encoding="utf-8"
    )
    assert all(f"hmp.{name}(" in frozen for name in KEPT_READERS)
    assert kept_readers.__all__ == list(KEPT_READERS)
    assert not set(KEPT_READERS) & set(api.__all__)
    assert hmp.Catalog is Catalog
    assert hmp.read is kept_readers.read and hmp.index is kept_readers.index


@pytest.mark.parametrize("name", sorted(HOMES))
def test_each_object_is_the_class_of_its_home(name: str) -> None:
    import importlib

    assert getattr(hmp, name) is getattr(importlib.import_module(HOMES[name]), name)
    assert getattr(api, name) is getattr(hmp, name)


@pytest.mark.parametrize("name", VERBS)
def test_every_parameter_of_a_verb_is_serializable(name: str) -> None:
    hints = _hints(name)
    hints.pop("return")
    wrong = {key: hint for key, hint in hints.items() if not _serializable_parameter(hint)}
    assert not wrong, f"hmp.{name} takes what a server cannot send: {wrong}"


@pytest.mark.parametrize("name", sorted(set(VERBS) - EXEMPT_RETURNS))
def test_every_verb_returns_what_a_server_can_send(name: str) -> None:
    hint = _hints(name)["return"]
    assert _serializable_return(hint), f"hmp.{name} returns {hint}"


def _instances() -> list[Any]:
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.project.calibrate import CalibrationPlan
    from hydromodpy.project.compare import Comparison
    from hydromodpy.project.doctor import DoctorReport
    from hydromodpy.project.examples.install import InstallReport
    from hydromodpy.project.examples.manifest import ExampleEntry
    from hydromodpy.project.launch.status import StatusReport, StatusRow
    from hydromodpy.project.request import RunOutcome
    from hydromodpy.project.spinup import SpinupCycle, SpinupResult
    from hydromodpy.results.export.publish import PublishedProject
    from hydromodpy.results.publication import PublishedLine
    from hydromodpy.workflow.overview import OverviewResult

    here = Path("project")
    start, end = pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31")
    return [
        RunOutcome("a", here / "runs/a", "abc", "req", "completed", None, here),
        OverviewResult(None, None, None, (), None),
        CalibrationReport("s1", "nelder_mead", 3, 0.5, 1.0, "best", 1),
        CalibrationPlan([{"name": "one"}], {"method": "nelder_mead"}, None, None),
        SpinupResult(True, [SpinupCycle(0, "a", "a.zarr", None, None)], "a.zarr"),
        StatusReport(here, "hash", False, (StatusRow("nancon-base", "nancon", "base", "planned"),)),
        Comparison(
            [SimpleNamespace(name="a"), SimpleNamespace(name="b")],
            start,
            end,
            {"scores": pd.DataFrame({"a": [0.5], "b": [0.6]})},
            {},
            {},
        ),
        PublishedProject([here / "copy"], [("runs/b", "not sealed")]),
        PublishedLine(
            kind="copy",
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            to="/srv/copy",
            format="dir",
            publication_sha256="0" * 64,
        ),
        ExampleEntry("04", "04_x", "Title", "Summary", "1 min", "project.toml", (), ()),
        InstallReport("04", here, here / "04", "bundled"),
        DoctorReport("3.12", "2.1.0", {"mf6": None}, {"dask": "2024.1"}),
    ]


def test_each_type_a_verb_returns_writes_json() -> None:
    for instance in _instances():
        text = json.dumps(instance.to_dict())
        assert isinstance(json.loads(text), dict), type(instance).__name__


def test_a_plan_draft_writes_json(tmp_path: Path) -> None:
    from hydromodpy.project.launch.plan import expand_plan
    from tests.unit.project.launch.test_plan import write_sites_project

    project = write_sites_project(tmp_path)
    draft = expand_plan(project, project / "project.toml")
    assert isinstance(json.loads(json.dumps(draft.to_dict())), dict)


def _calls_its_verb(path: Path, verb: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bound = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "hydromodpy.project.api"
        for alias in node.names
        if alias.name == verb
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    return bool(bound & called)


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_each_command_imports_the_api_and_calls_its_verb(command: str) -> None:
    path = PKG_ROOT / "cli" / "commands" / command
    assert _calls_its_verb(path, COMMANDS[command]), (
        f"hmp {command} must call hydromodpy.project.api.{COMMANDS[command]}"
    )


def test_the_api_module_reads_in_one_place() -> None:
    lines = (PKG_ROOT / "project" / "api.py").read_text(encoding="utf-8").count("\n")
    assert lines < MAX_API_LINES, f"project/api.py holds {lines} lines"


# ---------------------------------------------------------------------------
# The register of changes is read and nothing moves without a row
# ---------------------------------------------------------------------------


SNAPSHOT_2_0_0 = REPO_ROOT / "tools" / "docs" / "snapshots" / "fields-2.0.0.json"


# Each document a row may name, with the module that reads its rows and the
# functions a row of that document may name by ``rule``.
READERS: dict[str, tuple[str, dict[str, Callable[..., Any]]]] = {
    "config": ("hydromodpy.config.config_migration", CONFIG_RULES),
    "sidecar": ("hydromodpy.data.provenance.sidecars", {}),
    "fields": ("hydromodpy.results.zarr_store.zarr_reader", {}),
    "manifest": ("hydromodpy.results.record.forms", RUN_SEAL_RULES),
    "identity": ("hydromodpy.results.record.forms", {}),
    "job.manifest": ("hydromodpy.schema.job.seal", JOB_SEAL_RULES),
}


def test_the_register_reads_and_counts_its_rows() -> None:
    text = (REPO_ROOT / "hydromodpy" / "schema" / REGISTER_FILENAME).read_text(encoding="utf-8")

    assert read(text) == REGISTER
    counts = {
        "bug": len(REGISTER.bugs),
        "default": len(REGISTER.defaults),
        "recipe": len(REGISTER.recipes),
        "migration": len(REGISTER.migrations),
    }
    print("\nrows of the register:", ", ".join(f"{k} {v}" for k, v in counts.items()))
    for document in sorted({row.document for row in REGISTER.migrations}):
        print(f"  migration of {document}: {len(migrations_of(document))}")
    assert sum(counts.values()) > 0


def test_each_document_has_a_reader() -> None:
    documents = {row.document for row in REGISTER.migrations}

    assert documents <= set(READERS), f"no reader for {sorted(documents - set(READERS))}"


def test_each_rule_is_a_function_of_the_reader_of_its_document() -> None:
    unknown = [
        f"{row.document}: {row.rule}"
        for row in REGISTER.migrations
        if row.rule is not None and row.rule not in READERS[row.document][1]
    ]

    assert unknown == []


def test_each_function_of_a_reader_is_named_by_a_row() -> None:
    named = {(row.document, row.rule) for row in REGISTER.migrations if row.rule}
    unnamed = [
        f"{document}: {rule}"
        for document, (_module, rules) in READERS.items()
        for rule in rules
        if (document, rule) not in named
    ]

    assert unnamed == []


def test_the_sidecar_reader_reads_its_rows() -> None:
    source = (REPO_ROOT / "hydromodpy" / "data" / "provenance" / "sidecars.py").read_text()

    assert 'migrations_of("sidecar")' in source


def test_no_row_is_dated_past_the_next_minor_version() -> None:
    current = Version(__version__)
    ceiling = Version(f"{current.major}.{current.minor + 1}.0")
    rows = [*REGISTER.bugs, *REGISTER.defaults, *REGISTER.recipes, *REGISTER.migrations]
    late = [f"{row.since}: {row}" for row in rows if Version(row.since) > ceiling]

    assert late == []


def _value(rendered: str | None) -> Any:
    """Read a default as the registry of fields renders it."""
    if rendered is None:
        return None
    try:
        return json.loads(rendered)
    except json.JSONDecodeError:
        return rendered


def _registry_path(path: str) -> str:
    """Write a path of the register as the registry of fields writes it, ``*`` for a name."""
    return path.replace("[*]", "").replace("{*}", "*")


def _explained(path: str, old: Any, new: Any) -> bool:
    """Whether a row of the register says this default moved."""
    for row in REGISTER.defaults:
        if fnmatchcase(path, _registry_path(row.key)) and (row.old, row.new) == (old, new):
            return True
    return any(
        row.shape == "value"
        and fnmatchcase(path, _registry_path(str(row.key)))
        and (row.old_value, row.new_value) == (old, new)
        for row in migrations_of("config")
    )


@pytest.fixture(scope="module")
def fields_since_2_0_0() -> dict[str, Any]:
    from tools.docs.field_registry import build_payload
    from tools.docs.legacy_keys import moved_tables
    from tools.docs.toml_changelog import diff

    payload, _gates = build_payload("tree")
    released = json.loads(SNAPSHOT_2_0_0.read_text(encoding="utf-8"))
    return {"diff": diff(released, payload, moved_tables()), "nodes": payload["nodes"]}


def test_each_default_that_moved_since_2_0_0_has_its_row(fields_since_2_0_0: dict) -> None:
    moved = [
        (change["path"], *change["changes"]["default"])
        for change in fields_since_2_0_0["diff"]["changed"]
        if "default" in change["changes"]
    ]
    missing = [
        f"{path}: {old} -> {new}"
        for path, old, new in moved
        if not _explained(path, _value(old), _value(new))
    ]

    assert missing == [], (
        "A default moved without its row. Write a [[default]] row in "
        "hydromodpy/schema/changes.toml whose old value keeps the computation of a pre-release."
    )


_UNSET = "not set"


# Each field new since the baseline, by the path the registry of fields writes, with the
# default it has and why that default keeps the computation of a file of edition 2.0. The
# replay of a sealed run reads a key its frozen config does not write at this default, so a
# new field that would move a number needs a [[default]] row instead of a line here.
# The baseline is the tree prepared for the 2.0.0 tag, so the table is empty until a field
# is added after the tag.
NEW_FIELDS: dict[str, tuple[Any, str]] = {}


def _reviewed(path: str) -> tuple[Any, str] | None:
    """Return the reviewed default of a new field, ``None`` when it has no line."""
    for pattern, line in NEW_FIELDS.items():
        if fnmatchcase(path, pattern):
            return line
    return None


def test_each_field_new_since_2_0_0_keeps_the_numbers_of_2_0_at_its_default(
    fields_since_2_0_0: dict,
) -> None:
    """A new field must keep the numbers of a file of edition 2.0 at its default."""
    nodes = fields_since_2_0_0["nodes"]
    added = fields_since_2_0_0["diff"]["added"]
    print(f"\nfields new since 2.0.0: {len(added)}")
    faults = []
    for path in added:
        default = _value(nodes[path].get("default"))
        print(f"  {path} ({nodes[path].get('kind')}): {default!r}")
        reviewed = _reviewed(path)
        if reviewed is None:
            faults.append(f"{path}: no line in NEW_FIELDS")
        elif default != reviewed[0] and not (default is None and reviewed[0] == _UNSET):
            faults.append(f"{path}: default {default!r}, reviewed {reviewed[0]!r}")
    unused = [pattern for pattern in NEW_FIELDS if not any(fnmatchcase(p, pattern) for p in added)]

    assert faults == [], (
        "A field new since 2.0.0 has no reviewed default. Add its line to NEW_FIELDS with "
        "the reason its default keeps the numbers of a pre-release of 2.0, or write a [[default]] row in "
        "hydromodpy/schema/changes.toml."
    )
    assert unused == [], f"{unused} match no field new since 2.0.0: remove their lines."


def test_no_bug_touches_the_version_of_this_tree() -> None:
    """The tree that holds the fix of a bug must not seal its runs inside the bug's range."""
    hit = [bug.id for bug in REGISTER.bugs if bug.hits(__version__, bug.quantities)]

    assert hit == [], f"HydroModPy {__version__} falls inside the versions of {hit}."


def test_the_numbers_block_of_the_changelog_is_the_one_the_register_writes() -> None:
    from tools.changes_changelog import CHANGELOG, rewrite

    text = CHANGELOG.read_text(encoding="utf-8")

    assert rewrite(text) == text, "Run python -m tools.changes_changelog --write."


# ---------------------------------------------------------------------------
# One source of numerical tolerances
# ---------------------------------------------------------------------------


_TESTS_ROOT = REPO_ROOT / "tests"


# These two files exercise the tol() machinery itself (including negative-path
# arguments such as a deliberately-unknown key), so their tol() calls are not
# real tolerance references and must be skipped when scanning the suite.
_SCAN_EXCLUDE: frozenset[str] = frozenset(
    {
        "test_tolerances_helper.py",
        "test_surfaces.py",
        "tolerances.py",
    }
)


# INLINE: literal replaced by tol(); must be referenced by >= 1 tol() call.
INLINE_ROWS: frozenset[str] = frozenset(
    {
        "theis_confined_pumping_2d__nse_vs_analytical_9_probes",
        "theis_confined_pumping_2d__max_pointwise_relative_drawdown_error",
        "direct_solver_outputs__rtol",
        "the_linear_reservoir_on_the_one_cell_mesh_discharge_depth_series_and_released_volume__state_max_abs_error",
        "reservoir_calibration_validation__recovered_log10_k_and_n_drift_from_truth",
        "regression_goldens_arrays__rtol",
        "regression_goldens_arrays__atol",
        "signature_stats_post_v0_5__rtol",
        "signature_stats_post_v0_5__atol",
        "mf6_prt_uniform_velocity_streamline__max_relative_position_error_x_x_exp_x_exp_x0",
        "mf6_gwt_first_order_decay_0d__max_relative_concentration_error_vs_c0_exp_k_t",
        # Stress-period sub-stepping and the ATS bounds, asserted in
        # tests/validation/analytical/transient/test_stress_period_substepping.py.
        "stress_period_sub_stepping_mf6__rmse_ratio_between_nstp_1_and_nstp_10",
        "stress_period_sub_stepping_mf6__rmse_difference_between_tsmult_r_and_1_r",
        "adaptive_time_stepping_mf6__rmse_relative_difference_ats_on_against_ats_off",
        "one_step_per_stress_period_mf6__monthly_discharge_drift_against_a_refined_run",
        "stress_period_sub_stepping_boussinesq__rmse_ratio_between_nstp_1_and_nstp_10",
        # Grid-convergence order bands of the triangle, Voronoi and Boussinesq legs.
        "grid_convergence_dupuit_fixed_head_1d_boussinesq_petsc_and_local_engine__observed_order_of_the_head_rmse_on_16_32_64_columns_p_2",
        "grid_convergence_dupuit_fixed_head_1d_modflow_6_triangles_voronoi_dual__observed_order_of_the_head_rmse_on_16_32_64_columns_p_2_without_newton_and_p_1_under_newton",
        # Twin closure at the truth and the NWT recharge read-back.
        "twin_calibration_closure_noise_free_search_started_at_the_truth_piecewise_k_transient_k_sy_modflow_nwt_modflow_6_modflow_6_triangles_modflow_6_voronoi__best_normalized_cost_and_p_p_true_p_true_of_every_parameter_after_3_evaluations_of_nelder_mead",
        "twin_stream_network_calibration_modflow_nwt__recharge_read_back_from_the_solver_files_rel_against_the_input",
        # SFR standalone budget closure + SFR->LAK MVR reciprocity, asserted in
        # tests/integration/solver/test_sfr_standalone.py and test_sfr_lak_mvr.py.
        "sfr_standalone_budget_closure_mf6__gwf_listing_percent_discrepancy",
        "sfr_lak_mvr_reciprocity_mf6__terminal_reach_to_mvr_vs_lake_from_mvr",
        # V-valley support bench and the D4/D8 length ratio, asserted in
        # tests/unit/catchment/drainage/test_distance.py.
        "v_valley_support_bench_case_a__root_relative_gap_between_raw_and_closed_observed_network",
        "v_valley_support_bench_case_b__root_drift_under_a_rasterization_hole",
        # Terrain port conformance suite, tests/ports/test_terrain.py.
        "terrain_engine_conformance__cross_engine_catchment_area",
        "terrain_engine_conformance__ln_transform_identity",
        "downslope_operator_d4_vs_d8__length_ratio_on_a_pure_diagonal_descent",
        # Golden comparison against whitebox D-infinity, asserted in
        # tests/unit/catchment/drainage/test_downslope_whitebox_golden.py.
        "downslope_operator_vs_whitebox_d_infinity__spearman_rank_correlation_on_a_real_dem",
        "downslope_operator_vs_whitebox_d_infinity__median_relative_gap",
        # Bands of the double-execution comparator, read at import time by
        # tests/characterization/comparator.py.
        "double_execution_comparator_float_arrays__rtol",
        "double_execution_comparator_float_arrays__atol",
        "double_execution_comparator_signature_fallback__rtol",
        "double_execution_comparator_manifest_scalars__rtol",
        # Twin stream-network calibration on MODFLOW 6, asserted in
        # tests/validation/calibration/test_twin_matching_stream_network_modflow6.py.
        # Row 77 is not loadable: its band is the run's own cell spacing.
        "twin_stream_network_calibration_mf6_planar_hillslope_400_cells_of_2_m__"
        "k_k_true_k_true_at_the_returned_trial_and_the_same_on_k_over_r_against_k_true_r",
        "twin_stream_network_calibration_mf6__d_sat_m_at_the_returned_trial_against_the_truth_run",
        "twin_stream_network_calibration_under_heads_mf6_comb_basin_5600_cells_of_20_m_six_heads__"
        "k_k_true_k_true_at_the_returned_trial",
        "twin_stream_network_calibration_under_heads_mf6__d_optim_at_the_returned_trial",
        "twin_stream_network_calibration_under_heads_mf6__d_sat_m_of_the_returned_trial_over_the_truth_run",
        "twin_k_and_sy_on_two_maps_mf6_comb_basin_monthly_recharge_truth_k_6e_6_and_sy_0_05__"
        "j_on_each_map_at_the_true_k_for_sy_from_0_025_to_0_1",
        "twin_stream_network_calibration_mf6__k_optim_m_s_k_over_r_t_over_r_m_t_optim_m2_s_"
        "against_k_r_mean_m_s_and_d_sat_m_of_the_returned_trial",
        # Soil reservoir kernel, asserted in tests/unit/model/soil/.
        "soil_reservoir_kernel_balance_float64__per_column_sum_t_residual_sum_t_p_and_per_day_"
        "max_residual_max_p",
        "soil_transit_store_impulse__max_absolute_error_against_q_0_50_1_k_a_q_t_1_50_k_a_2_exp_"
        "t_1_k_mm",
        "soil_transit_store_impulse_volume__sum_t_q_50_over_60_k_days_mm",
        "soil_spin_up_settling__largest_change_mm_of_the_end_of_year_soil_or_transit_storage_"
        "between_the_last_two_repetitions",
        "soil_curve_number_runoff_balance_with_routing__per_day_max_residual_max_p_per_column_"
        "year_max_residual_p",
        # Soil recharge and unmet ETP reaching MODFLOW 6, asserted in
        # tests/integration/test_soil_recharge_mf6.py,
        # which also gives the global water-budget closure row its first test.
        "soil_recharge_into_mf6_rcha__per_period_sum_q_rch_sum_pe_a_sum_pe_a",
        "soil_unmet_etp_into_mf6_evta__per_cell_and_period_q_evt_etpres_a_etpres_a",
        "global_water_budget_closure__relative_error_in_out_in",
        # Routed impulse through the full soil orchestrator, asserted in
        # tests/validation/analytical/transient/test_a_routed_impulse_matches_the_exponential_reservoir.py.
        "routed_impulse_validation_case__t95_against_k_ln_0_05_days",
        # Mesh characterization net, asserted in tests/regression/mesh/mesh_net/
        # through mesh_net_helpers.py. The cell-count row is exact equality (n/a),
        # so it is not loadable.
        "mesh_characterization_net__geometry_quantiles_relative_band",
        "mesh_characterization_net__cell_areas_and_their_sum_relative",
        "mesh_characterization_net__heads_share_of_the_golden_head_range",
        "mesh_characterization_net__center_offset_over_side_absolute_floor",
        "mesh_characterization_net__non_orthogonality_absolute_floor",
        "mesh_characterization_net__neighbor_size_ratio_absolute_floor",
        "mesh_characterization_net__probe_cell_center_offset_absolute_floor",
        # Mesh engine conformance suite, tests/ports/test_mesh.py.
        # Session cost against the score of its run (decision m01), asserted in
        # tests/unit/calibration/test_criteria_series.py.
        "session_cost_against_run_score__gap_of_1_cost_to_the_run_nse",
        "mesh_engine_conformance__sum_of_the_cell_areas_against_the_area_to_cover_relative",
        "mesh_engine_conformance__exact_faces_to_their_source_lines_hausdorff_distance_as_a_share_of_the_extent",
        "mesh_engine_conformance__wall_clock_time_of_one_build_on_a_closed_case",
        "mesh_engine_conformance__cell_count_at_a_uniform_cell_size_against_the_area_over_the_size_squared_relative",
        "scaffolded_demo__mound_against_the_dupuit_integral",
        # One cell mesh acceptance, tests/integration/test_one_cell_mesh.py.
        "one_cell_mesh_acceptance__recharge_against_the_hand_reference_relative",
        "one_cell_mesh_acceptance__zone_means_against_the_exact_areas_relative",
    }
)


# CASE_TOML: enforced via comparison.tolerances from validation_cases/**/*.toml
# (or, for the twin K recovery, via a case-config tolerance object). These keep
# the case store as the runtime authority; tol() is intentionally not used.
CASE_TOML_ROWS: frozenset[str] = frozenset(
    {
        # Dupuit fixed-head head RMSE, the tolerances.toml head_profile.rmse that
        # NWT and MF6 share.
        "dupuit_fixed_head_1d_nwt__head_rmse",
        "dupuit_fixed_head_1d_mf6__head_rmse",
        # Brutsaert recessions, tolerances.toml blocks [recession] and
        # [uniformity] of the thin and deep cases.
        "brutsaert_thin_1d_mf6_mf6_triangles_nwt__relative_error_of_the_fitted_a_of_dq_dt_a_q_3_2_days_16_to_128",
        "brutsaert_thin_1d__b_3_2_fitted_exponent_of_dq_dt_a_q_b",
        "brutsaert_thin_1d__rmse_of_q_q_ref_1_days_16_to_128_q_ref_on_the_analytical_a_with_a_fitted_origin",
        "brutsaert_thin_1d__cross_row_head_spread",
        "brutsaert_deep_1d__relative_error_of_the_fitted_decay_rate_days_30_to_90",
        "brutsaert_deep_1d__b_1_fitted_exponent",
        "brutsaert_deep_1d__rmse_of_q_q_ref_1_days_30_to_90_both_period_means",
        # Stream depletion, tolerances.toml bound on the well-cell drawdown over
        # the saturated thickness, shared by every variant.
        "stream_depletion_2d_all_variants__well_cell_drawdown_over_saturated_thickness",
        # Dupuit seepage limit, tolerances.toml blocks [seepage_limit], [invariance]
        # and [control]; asserted in
        # tests/validation/analytical/steady/test_dupuit_seepage_limit_1d.py.
        "dupuit_seepage_limit_1d_mf6__seepage_limit_position_error",
        "dupuit_seepage_limit_1d_mf6__head_profile_max_abs_error_vs_the_closed_form",
        "dupuit_seepage_limit_1d_k_r_invariance__water_table_max_abs_difference_across_the_k_r_sweep",
        "dupuit_seepage_limit_1d_k_only_control__total_drain_outflow_relative_drift",
        # Linearized transient cross-row spread, *_modflow6_irregular_tri.toml
        # space_time.row_spread (values match the doc exactly: 1e-9).
        "linearized_transient_recharge_step_1d_mf6_irregular_tri__cross_row_spread",
        "linearized_transient_recharge_periodic_1d_mf6_irregular_tri__cross_row_spread",
        "linearized_transient_boundary_piecewise_1d_mf6_irregular_tri__cross_row_spread",
        "linearized_transient_boundary_step_1d_mf6_irregular_tri__cross_row_spread",
        "linearized_transient_recharge_step_deep_1d_mf6_irregular_tri__cross_row_spread",
        # Twin K recovery. The benchmark enforces an ABSOLUTE K_global tolerance
        # (~2.0e-5) in validation_cases/calibration/.../experiment.py
        # parameter_abs_tolerances (case config, out of scope for tests/). The
        # documented row 19 is a RELATIVE 0.05 SNR envelope and is a different
        # metric than what is enforced; see the disagreement test below.
        "twin_calibration_k_recovery__k_k_true_k_true",
    }
)


# UNUSED: documented but not enforced by any test today.
UNUSED_ROWS: frozenset[str] = frozenset(
    {
        # No test asserts the absolute NSE drift vs a calibration baseline.
        "calibration_nse_vs_baseline__absolute_nse_drift",
        # No test references the Marcais 2017 recession-slope benchmark.
        "boussinesq_vs_mar_ais_2017__recession_slope_error",
        # No test enforces a bootstrap CI rtol on metrics.
        "bootstrap_ci_on_metrics__bootstrap_rtol",
    }
)


def _collect_tol_arguments() -> dict[str, list[str]]:
    """Return ``{slug: [file:line, ...]}`` for every ``tol("...")`` string arg."""
    found: dict[str, list[str]] = {}
    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        if path.name in _SCAN_EXCLUDE:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_tol = (isinstance(func, ast.Name) and func.id == "tol") or (
                isinstance(func, ast.Attribute) and func.attr == "tol"
            )
            if not is_tol or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.setdefault(first.value, []).append(f"{path}:{node.lineno}")
    return found


def _resolve(slug: str) -> str:
    """Resolve a tol() argument to its canonical key with tol()'s own logic."""
    table = TOLERANCES
    if slug in table:
        return slug
    candidates = [key for key in table if slug in key]
    assert len(candidates) == 1, (
        f"tol({slug!r}) does not resolve to exactly one loadable row: {sorted(candidates)}"
    )
    return candidates[0]


@pytest.mark.fast
def test_classification_partitions_all_loadable_rows() -> None:
    """INLINE, CASE_TOML and UNUSED partition exactly the loadable rows."""
    classified = INLINE_ROWS | CASE_TOML_ROWS | UNUSED_ROWS
    loadable = set(TOLERANCES)
    assert len(loadable) == 87, sorted(loadable)
    missing = loadable - classified
    extra = classified - loadable
    assert not missing, f"loadable rows with no classification: {sorted(missing)}"
    assert not extra, f"classified keys that are not loadable rows: {sorted(extra)}"
    # The three classes must not overlap.
    assert not (INLINE_ROWS & CASE_TOML_ROWS)
    assert not (INLINE_ROWS & UNUSED_ROWS)
    assert not (CASE_TOML_ROWS & UNUSED_ROWS)


@pytest.mark.fast
def test_every_tol_call_resolves_to_one_real_row() -> None:
    """No dangling / typo / ambiguous tol() argument anywhere in tests/."""
    calls = _collect_tol_arguments()
    assert calls, "expected at least one tol() call across the test suite"
    for slug, sites in calls.items():
        try:
            _resolve(slug)
        except (AssertionError, KeyError) as exc:
            raise AssertionError(f"tol({slug!r}) used at {sites} is invalid: {exc}") from exc


@pytest.mark.fast
def test_referenced_rows_are_subset_of_loadable_keys() -> None:
    """Every row reached through tol() is one of the loadable keys."""
    referenced = {_resolve(slug) for slug in _collect_tol_arguments()}
    assert referenced <= set(TOLERANCES), sorted(referenced - set(TOLERANCES))


@pytest.mark.fast
def test_every_inline_row_is_referenced_by_a_tol_call() -> None:
    """No INLINE row can drift: each must be anchored by >= 1 tol() call."""
    referenced = {_resolve(slug) for slug in _collect_tol_arguments()}
    missing = INLINE_ROWS - referenced
    assert not missing, f"INLINE rows not referenced by any tol() call: {sorted(missing)}"


@pytest.mark.fast
def test_dupuit_fixed_head_doc_agrees_with_case_toml() -> None:
    """The Dupuit fixed-head head-RMSE doc rows match their enforced case-TOML."""
    doc_mf6 = tol("dupuit_fixed_head_1d_mf6__head_rmse")
    doc_nwt = tol("dupuit_fixed_head_1d_nwt__head_rmse")
    assert doc_mf6 == pytest.approx(0.011)
    assert doc_nwt == pytest.approx(0.011)

    case_root = (
        _TESTS_ROOT.parent / "validation_cases" / "analytical" / "steady" / "dupuit_fixed_head_1d"
    )
    # NWT and MF6 share one file since the heads are posed at the boundary-cell centers.
    assert not (case_root / "tolerances_modflow6.toml").exists()
    shared_toml = (case_root / "tolerances.toml").read_text(encoding="utf-8")
    assert "rmse = 0.011" in shared_toml, "dupuit case-TOML rmse changed; revisit rows 11 and 12"


def test_documented_tolerance_count_matches_the_table() -> None:
    """The header count must equal the number of numbered rows, so it never drifts."""
    import re

    text = (_TESTS_ROOT / "TOLERANCES.md").read_text(encoding="utf-8")
    header = re.search(r"records the (\d+) tolerances", text)
    assert header is not None, "TOLERANCES.md header count line is missing"
    documented = int(header.group(1))
    rows = len(re.findall(r"^\| [0-9]", text, flags=re.MULTILINE))
    assert documented == rows, f"header says {documented} tolerances but the table has {rows} rows"


# ---------------------------------------------------------------------------
# Every HMP_* variable the code names has a row
# ---------------------------------------------------------------------------


NOT_ENVIRONMENT: dict[str, str] = {
    "HMP_NO_SUCH_VARIABLE": "a name that tests/unit/core/runtime/test_env.py refuses on purpose",
    "HMP_PERIOD": "GeoTIFF tag written by results/exporters/geotiff.py",
    "HMP_SIM_ID": "GeoTIFF tag written by results/exporters/geotiff.py",
    "HMP_TIMESTAMP": "GeoTIFF tag written by results/exporters/geotiff.py",
    "HMP_EXPORTED_AT": "GeoTIFF tag written by results/exporters/geotiff.py",
    "HMP_UNITS": "GeoTIFF tag written by results/exporters/geotiff.py",
    "HMP_VARIABLE": "GeoTIFF tag written by results/exporters/geotiff.py",
    "HMP_RUN_SCRATCH": "the retired run scratch variable, which the tests check no run writes",
}


def _registered(name: str) -> bool:
    try:
        env_var(name)
    except KeyError:
        return False
    return True


def test_every_variable_the_code_names_has_a_row() -> None:
    names = set(env_var_references()) - set(NOT_ENVIRONMENT)
    missing = sorted(name for name in names if not _registered(name))
    assert missing == [], (
        "These HMP_* names appear in the code without a row in hydromodpy/core/runtime/env.py. "
        "Add a row (name, default, scope, description), or add the name to NOT_ENVIRONMENT "
        f"in this file when it is not an environment variable: {missing}"
    )


def test_every_row_names_a_variable_the_code_reads() -> None:
    names = set(env_var_references())
    stale = sorted(
        var.name
        for var in ENV_VARS
        if not any(n == var.name or (var.prefix and n.startswith(var.name)) for n in names)
    )
    assert stale == [], f"hydromodpy/core/runtime/env.py lists variables nothing reads: {stale}"


def test_every_exclusion_is_still_written_somewhere() -> None:
    names = set(env_var_references())
    stale = sorted(set(NOT_ENVIRONMENT) - names)
    assert stale == [], f"NOT_ENVIRONMENT lists names the code no longer writes: {stale}"


def test_a_row_is_complete_and_unique() -> None:
    seen: set[str] = set()
    for var in ENV_VARS:
        assert var.name.startswith("HMP_"), var.name
        assert var.name not in seen, f"{var.name} has two rows"
        seen.add(var.name)
        assert var.scope in ENV_SCOPES, f"{var.name}: unknown scope {var.scope!r}"
        assert var.default.strip(), f"{var.name}: say what happens when it is unset"
        assert len(var.description.split()) >= 6, f"{var.name}: the description is too short"


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


"""Files and folders, relative to the package, that raise typed exceptions only. Each must exist."""


"""Files inside a scoped folder that keep their vanilla raises for now.

Each entry says why and names the lot that lifts it, like ``known_stale`` in
``dotted_paths.yaml``. An entry whose file no longer raises a vanilla exception
fails the gate, so it leaves as soon as it is lifted. The list is empty.
"""


BANNED: frozenset[str] = frozenset({"ValueError", "RuntimeError"})


NOT_FAILURES: frozenset[str] = frozenset(
    {"ConfigKeyRenamedWarning", "StopRequested", "TerminationRequested"}
)


"""A warning is no failure. A signal, and a stop asked through the flag of a run, must
stay out of reach of ``except Exception``."""


ROOT = "HydroModPyError"


def _classes_with_bases() -> dict[str, set[str]]:
    """Return the base names of every class the package defines, by class name."""
    bases: dict[str, set[str]] = {}
    for file in PKG_ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                names = {
                    base.id if isinstance(base, ast.Name) else base.attr
                    for base in node.bases
                    if isinstance(base, ast.Name | ast.Attribute)
                }
                bases.setdefault(node.name, set()).update(names)
    return bases


def test_a_public_exception_derives_from_the_root() -> None:
    """A leading underscore keeps a control-flow exception inside its module."""
    bases = _classes_with_bases()

    def reaches(name: str, target: set[str]) -> bool:
        return name in target or any(reaches(base, target) for base in bases.get(name, ()))

    builtin = {name for name, value in vars(builtins).items() if isinstance(value, type)}
    failures = {name for name in builtin if issubclass(getattr(builtins, name), BaseException)}
    outside = sorted(
        name
        for name in bases
        if not name.startswith("_")
        and name not in NOT_FAILURES
        and reaches(name, failures)
        and not reaches(name, {ROOT})
    )
    assert outside == [], f"{outside} do not derive from {ROOT}: add a family of core.exceptions."


# ---------------------------------------------------------------------------
# Whitebox tests run serially in CI
# ---------------------------------------------------------------------------


_PARALLEL_RE = re.compile(r"-n\s+(auto|\d+)")
_MARKER_RE = re.compile(r"""(?:^|\s)-m\s+(?:"([^"]*)"|'([^']*)'|(\S+))""")


def _whitebox_test_paths() -> list[Path]:
    """Locate every file the conftest puts in the Whitebox xdist group."""
    found: list[Path] = []
    for name in sorted(_WHITEBOX_XDIST_GROUP_TEST_FILES):
        matches = sorted((REPO_ROOT / "tests").rglob(name))
        assert matches, (
            f"{name} is listed in the Whitebox xdist group but no such test file "
            "exists; the entry protects nothing and the test that replaced it is "
            "running unguarded"
        )
        found.extend(matches)
    return found


def _pytest_commands(workflow: Path) -> list[str]:
    """Every pytest invocation in a workflow, line continuations folded in."""
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    commands: list[str] = []
    for job in (document.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            script = step.get("run")
            if not script:
                continue
            folded = script.replace("\\\n", " ")
            commands.extend(
                " ".join(line.split()) for line in folded.splitlines() if "pytest" in line
            )
    return commands


def _collects(command: str, path: Path) -> bool:
    """Whether a pytest command walks a tree that contains ``path``."""
    relative = path.relative_to(REPO_ROOT).as_posix()
    for token in command.split():
        if not token.startswith("tests/"):
            continue
        if relative == token or relative.startswith(token.rstrip("/") + "/"):
            return True
    return False


def _leaves_out_whitebox(command: str) -> bool:
    """Whether a ``-m`` expression of a command leaves out the ``whitebox`` marker.

    ``python -m pytest`` also matches, and its ``pytest`` never says ``not whitebox``.
    """
    expressions = ("".join(match.groups(default="")) for match in _MARKER_RE.finditer(command))
    return any(re.search(r"\bnot\s+whitebox\b", text) for text in expressions)


def _ignored(command: str, path: Path) -> bool:
    """Whether a command leaves ``path`` out, by ``--ignore`` or by ``-m "not whitebox"``."""
    if _leaves_out_whitebox(command):
        return True
    relative = path.relative_to(REPO_ROOT).as_posix()
    for token in command.split():
        if not token.startswith("--ignore="):
            continue
        ignored = token.split("=", 1)[1]
        if relative == ignored or relative.startswith(ignored.rstrip("/") + "/"):
            return True
    return False


def test_every_whitebox_group_file_still_exists() -> None:
    """A deleted or renamed file drops out of the group and back into a parallel run."""
    assert len(_whitebox_test_paths()) == len(_WHITEBOX_XDIST_GROUP_TEST_FILES)


@pytest.mark.parametrize(
    "workflow",
    [pytest.param(path, id=path.name) for path in sorted(WORKFLOW_DIR.glob("*.yml"))],
)
def test_no_parallel_step_collects_a_whitebox_test(workflow: Path) -> None:
    offenders: list[str] = []
    for command in _pytest_commands(workflow):
        if not _PARALLEL_RE.search(command):
            continue
        for path in _whitebox_test_paths():
            if _collects(command, path) and not _ignored(command, path):
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()} in: {command}")

    assert not offenders, (
        f"{workflow.name} runs Whitebox tests inside an xdist worker, which kills it:\n  "
        + "\n  ".join(offenders)
        + '\nAdd -m "not whitebox" to that step and a serial step with -m whitebox.'
    )


@pytest.mark.parametrize(
    "workflow",
    [pytest.param(path, id=path.name) for path in sorted(WORKFLOW_DIR.glob("*.yml"))],
)
def test_what_a_parallel_step_ignores_is_run_somewhere_serially(workflow: Path) -> None:
    """Excluding a Whitebox test everywhere without running it would lose coverage."""
    commands = _pytest_commands(workflow)
    serial = [command for command in commands if not _PARALLEL_RE.search(command)]

    missing: list[str] = []
    for path in _whitebox_test_paths():
        excluded = any(
            _PARALLEL_RE.search(command) and _collects(command, path) and _ignored(command, path)
            for command in commands
        )
        if excluded and not any(
            _collects(command, path) and not _ignored(command, path) for command in serial
        ):
            missing.append(path.relative_to(REPO_ROOT).as_posix())

    assert not missing, f"{workflow.name} excludes these but never runs them serially: {missing}"


# ---------------------------------------------------------------------------
# Legacy vocabulary stays out of the active surface
# ---------------------------------------------------------------------------


_SCAN_ROOTS = (
    "docs/source",
    "examples",
    "hydromodpy",
    "tests",
    "tools",
    "validation_cases",
)


_SKIP_DIRS = {
    ".mypy_cache",
    ".pytest_cache",
    ".pytest-tmp",
    ".ruff_cache",
    "__pycache__",
    "pytest_tmp_codex",
}


_BINARY_SUFFIXES = {
    ".7z",
    ".db",
    ".gif",
    ".gz",
    ".ico",
    ".jpg",
    ".jpeg",
    ".npy",
    ".npz",
    ".parquet",
    ".pdf",
    ".png",
    ".pyc",
    ".tif",
    ".tiff",
    ".webp",
    ".zip",
}


def _is_skipped_dir(path: Path) -> bool:
    name = path.name
    return (
        name in _SKIP_DIRS
        or name.startswith("hydromodpy_tests")
        or name.startswith("results")
        or name in {"outputs", "workspace"}
    )


def _iter_candidate_files(repo_root: Path):
    for root_name in _SCAN_ROOTS:
        scan_root = repo_root / root_name
        if not scan_root.exists():
            continue
        for root, dirs, files in os.walk(scan_root):
            root_path = Path(root)
            dirs[:] = [name for name in dirs if not _is_skipped_dir(root_path / name)]
            for filename in files:
                path = root_path / filename
                if path.suffix.lower() in _BINARY_SUFFIXES:
                    continue
                yield path


def test_legacy_regression_vocabulary_stays_out_of_active_surface() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    legacy_name = "_".join(("launcher", "simulation"))
    offenders: list[str] = []

    for path in _iter_candidate_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if legacy_name in text:
            offenders.append(path.relative_to(repo_root).as_posix())

    assert offenders == []


# ---------------------------------------------------------------------------
# Scoped layers raise typed exceptions only
# ---------------------------------------------------------------------------
#
# A public exception derives from ``HydroModPyError``, so ``except
# hmp.HydroModPyError`` means what it says. Ruff has no rule for the names
# ``ValueError`` and ``RuntimeError``, so the scoped layers are held by a rule
# of the syntax tree. A new module that should be locked down adds itself to
# ``SCOPE``, and ``hydromodpy/`` outside it keeps its historical raises.

SCOPE: tuple[str, ...] = (
    "hydromodpy/project/facade.py",
    "hydromodpy/workflow/",
    "hydromodpy/solver/base/runner.py",
    "hydromodpy/solver/base/rerun.py",
    "hydromodpy/solver/modflow_common/flow_run.py",
    "hydromodpy/solver/modflow_common/mt3dms_extractor_base.py",
    "hydromodpy/solver/modflow6/adapter.py",
    "hydromodpy/solver/modflow6/rerun.py",
    "hydromodpy/solver/modflow6/transport.py",
    "hydromodpy/solver/modflow6/prt.py",
    "hydromodpy/solver/modflow_nwt/adapter.py",
    "hydromodpy/solver/modflow_nwt/mt3dms/mt3dms.py",
    "hydromodpy/solver/modflow_nwt/modpath/modpath.py",
    "hydromodpy/solver/boussinesq/adapter.py",
)
"""Files and folders that raise typed exceptions only. Each must exist."""

EXEMPT: dict[str, dict[str, str]] = {
    "hydromodpy/solver/modflow6/transport.py": {
        "why": "legacy engine class Modflow6Gwt raises RuntimeError before solve",
        "lifted_by": "4.16",
    },
    "hydromodpy/solver/modflow6/prt.py": {
        "why": "legacy engine class Modflow6Prt raises ValueError/RuntimeError",
        "lifted_by": "4.16",
    },
    "hydromodpy/solver/modflow_nwt/mt3dms/mt3dms.py": {
        "why": "legacy engine class Mt3dms raises ValueError/RuntimeError",
        "lifted_by": "4.16",
    },
    "hydromodpy/solver/modflow_nwt/modpath/modpath.py": {
        "why": "legacy engine class Modpath raises ValueError",
        "lifted_by": "4.16",
    },
}
"""Scoped files that keep their vanilla raises for now, each with why and the lot that lifts it.

An entry whose file no longer raises a vanilla exception fails the gate, so it leaves as soon as it is lifted."""


def vanilla_raises(t: ast.Module) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(t):
        if isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(target, ast.Name) and target.id in BANNED:
                found.append((node.lineno, target.id))
    return found


def _untyped_raises(t: ast.Module, path: str) -> list[str]:
    if path in EXEMPT:
        return []
    return [
        f"{line} raise {name}: use a typed exception of core.exceptions"
        for line, name in vanilla_raises(t)
    ]


TYPED_RULE = Rule(
    "a_scoped_layer_raises_typed_exceptions_only",
    SCOPE,
    _untyped_raises,
    "def f():\n    raise ValueError('x')\n",
    "hydromodpy/workflow/x.py",
)


def test_a_scoped_layer_raises_typed_exceptions_only() -> None:
    assert offences(TYPED_RULE) == []


def test_the_typed_rule_flags_its_bad_example() -> None:
    assert TYPED_RULE.judge(parse(TYPED_RULE.bad), TYPED_RULE.bad_at)


def test_every_exemption_is_dated_and_still_needed() -> None:
    """One test over the whole table, so an empty table passes rather than skips."""
    for entry, exemption in EXEMPT.items():
        assert exemption.get("why") and exemption.get("lifted_by"), entry
        path = REPO_ROOT / entry
        assert path.is_file(), f"{entry} is gone: drop its exemption"
        assert vanilla_raises(_scan.tree(path)), f"{entry} raises no vanilla exception: drop it"


@pytest.mark.parametrize("entry", SCOPE)
def test_every_scoped_entry_exists(entry: str) -> None:
    """A moved file would leave the scope in silence."""
    assert (REPO_ROOT / entry).exists(), f"{entry} is not in the package: update SCOPE"
