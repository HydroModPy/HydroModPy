"""What ``hydromodpy/project/accessors.py`` selects: the runs and the data of one project.

The accessors filter catalog queries by project name. A small fake store records the
filters it receives and returns fixed rows, so no DuckDB catalog is needed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from hydromodpy.project.accessors import ProjectDataAccessor, ProjectRunsAccessor

pytestmark = pytest.mark.fast


class _FakeStore:
    """Minimal stand-in for Catalog implementing only the seams
    that ProjectRunsAccessor touches."""

    def __init__(self, rows: pd.DataFrame) -> None:
        self._rows = rows
        self.list_calls: list[dict[str, Any]] = []
        self.find_calls: list[dict[str, Any]] = []
        self.best_calls: list[tuple[str, str, bool]] = []
        self.delete_calls: list[tuple[str, bool]] = []
        self.getitem_calls: list[str] = []

    def list_simulations(self, **filters: Any) -> pd.DataFrame:
        self.list_calls.append(filters)
        return self._rows

    def find(self, **filters: Any) -> list[str]:
        self.find_calls.append(filters)
        return [f"run-{filters.get('solver', 'any')}"]

    def best(self, project: str, metric: str, mixed_windows: bool = False) -> str:
        self.best_calls.append((project, metric, mixed_windows))
        return f"best-{metric}"

    def delete(self, sim_id: str, *, remove_storage: bool = True) -> None:
        self.delete_calls.append((sim_id, remove_storage))

    def __getitem__(self, sim_id: str) -> str:
        self.getitem_calls.append(sim_id)
        return f"run-object-{sim_id}"


def _fake_project(store: Any, *, project_name: str = "demo") -> SimpleNamespace:
    """A Project-shaped object exposing only the attributes the runs accessor reads."""
    return SimpleNamespace(_store=store, _project_name=project_name)


def _rows(*sim_ids: str) -> pd.DataFrame:
    return pd.DataFrame({"sim_id": list(sim_ids)})


def test_find_adds_project() -> None:
    store = _FakeStore(_rows())
    accessor = ProjectRunsAccessor(_fake_project(store, project_name="flume"))

    result = accessor.find(solver="modflow6", status="completed")

    assert store.find_calls == [{"project": "flume", "solver": "modflow6", "status": "completed"}]
    assert result == ["run-modflow6"]


def test_latest_is_last_row() -> None:
    store = _FakeStore(_rows("first", "second", "third"))
    accessor = ProjectRunsAccessor(_fake_project(store))

    run = accessor.latest()

    # latest() must pick the bottom row of the listing, then look it up.
    assert store.getitem_calls == ["third"]
    assert run == "run-object-third"


def test_latest_without_runs() -> None:
    store = _FakeStore(_rows())
    accessor = ProjectRunsAccessor(_fake_project(store))

    assert accessor.latest() is None
    assert store.getitem_calls == []


def test_best_mixed_windows() -> None:
    store = _FakeStore(_rows("x"))
    accessor = ProjectRunsAccessor(_fake_project(store, project_name="nancon"))

    accessor.best("nse", mixed_windows=True)

    assert store.best_calls == [("nancon", "nse", True)]


def test_list_without_store() -> None:
    assert ProjectRunsAccessor(_fake_project(None)).list().empty


WITHOUT_STORE = [
    pytest.param("find", {"solver": "modflow6"}, [], id="find"),
    pytest.param("latest", {}, None, id="latest"),
    pytest.param("best", {"metric": "nse"}, None, id="best"),
    # Must not raise even though there is no store to delegate to.
    pytest.param("delete", {"sim_id": "sim-1"}, None, id="delete"),
]


@pytest.mark.parametrize(("method", "kwargs", "expected"), WITHOUT_STORE)
def test_runs_without_store(method: str, kwargs: dict, expected: object) -> None:
    accessor = ProjectRunsAccessor(_fake_project(None))

    assert getattr(accessor, method)(**kwargs) == expected


@pytest.mark.parametrize(
    ("sim_id", "kwargs", "remove_storage"),
    [
        pytest.param("sim-42", {"remove_storage": False}, False, id="forwards-the-flag"),
        pytest.param("sim-7", {}, True, id="defaults-remove-storage-to-true"),
    ],
)
def test_delete_flag(sim_id: str, kwargs: dict, remove_storage: bool) -> None:
    store = _FakeStore(_rows("a"))
    accessor = ProjectRunsAccessor(_fake_project(store))

    accessor.delete(sim_id, **kwargs)

    assert store.delete_calls == [(sim_id, remove_storage)]


def _data_project(plan_types: Any, loaded: set[str]) -> SimpleNamespace:
    ctx = SimpleNamespace(data_plan=SimpleNamespace(types=plan_types))
    return SimpleNamespace(_ctx=ctx, data_loaded=loaded)


MISSING = [
    pytest.param(
        ("precipitation", "temperature", "et0"),
        {"precipitation"},
        ["temperature", "et0"],
        id="planned and not loaded",
    ),
    pytest.param(
        ("precipitation", "temperature"),
        {"precipitation", "temperature", "extra"},
        [],
        id="all loaded",
    ),
]


@pytest.mark.parametrize(("plan_types", "loaded", "expected"), MISSING)
def test_missing_types(plan_types: tuple, loaded: set[str], expected: list[str]) -> None:
    accessor = ProjectDataAccessor(_data_project(plan_types, loaded))

    assert accessor.missing() == expected


DATA_LISTS = [
    pytest.param(
        {"temperature", "precipitation", "et0"},
        None,
        ["et0", "precipitation", "temperature"],
        id="sorted",
    ),
    pytest.param(
        {"temperature", "precipitation"}, "temperature", ["temperature"], id="one variable"
    ),
    pytest.param({"temperature"}, "nope", [], id="unknown variable"),
]


@pytest.mark.parametrize(("loaded", "variable", "expected"), DATA_LISTS)
def test_data_list(loaded: set[str], variable: str | None, expected: list[str]) -> None:
    accessor = ProjectDataAccessor(_data_project(plan_types=(), loaded=loaded))

    df = accessor.list() if variable is None else accessor.list(variable=variable)

    assert list(df["variable"]) == expected


@pytest.mark.parametrize("name", ["calage", "calage.v2"])
def test_session_by_name(monkeypatch: pytest.MonkeyPatch, tmp_path, name: str) -> None:
    import hydromodpy.project.accessors as accessors
    from hydromodpy.project.facade import read_sealed_config
    from hydromodpy.project.show import render

    monkeypatch.setattr(
        accessors, "list_session_dirs", lambda root: [tmp_path / "sessions" / "calage.v2"]
    )
    monkeypatch.setattr(
        accessors, "Session", lambda directory, **kwargs: SimpleNamespace(dir=directory, **kwargs)
    )
    session = accessors.ProjectSessions(tmp_path)[name]
    assert session.dir == tmp_path / "sessions" / "calage.v2"
    assert (session.read_config, session.render) == (read_sealed_config, render)
