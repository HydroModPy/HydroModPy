"""The facade holds fifteen typed verbs and five objects, and each command calls its verb.

``hydromodpy.__all__`` is the fifteen verbs of ``hydromodpy.project.api``, the five
objects they take and return, the three kept readers, the categories of the exception
hierarchy and ``__version__``. A verb takes text, numbers, booleans, paths, literals, mappings
or sequences of those, plus a few named Python conveniences, and returns a value
with ``to_dict()`` that ``json.dumps`` writes, a path, a list of paths or a list
of diagnostics. A server can then call every verb and send what it returns.
"""

from __future__ import annotations

import ast
import collections.abc
import json
import os
import types
import typing
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pandas as pd
import pytest

import hydromodpy as hmp
from hydromodpy.project import api

REPO = Path(__file__).resolve().parents[3]
PACKAGE = REPO / "hydromodpy"

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
"""The three readers kept beside the verbs, because the frozen runs of 2.0.0 call them."""

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
    from hydromodpy.results.catalog import Catalog

    frozen = (REPO / "tests" / "regression" / "frozen_runs" / "test_frozen_runs.py").read_text(
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
    path = PACKAGE / "cli" / "commands" / command
    assert _calls_its_verb(path, COMMANDS[command]), (
        f"hmp {command} must call hydromodpy.project.api.{COMMANDS[command]}"
    )


def test_the_api_module_reads_in_one_place() -> None:
    lines = (PACKAGE / "project" / "api.py").read_text(encoding="utf-8").count("\n")
    assert lines < MAX_API_LINES, f"project/api.py holds {lines} lines"
