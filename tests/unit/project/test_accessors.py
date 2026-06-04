"""Tests for the helper accessors in :mod:`hydromodpy.project.accessors`.

The accessors are thin wrappers that pre-filter catalog queries by the current
project name and apply small selection rules. We drive them through a single
seam: a tiny fake store that records the filters it receives and returns
deterministic rows. This keeps the test focused on the accessor's own behavior
(project scoping, latest/best/find/delete dispatch, missing-variable diff)
without standing up a real DuckDB catalog.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from hydromodpy.project.accessors import ProjectDataAccessor, ProjectRunsAccessor

pytestmark = pytest.mark.fast


class _FakeStore:
    """Minimal stand-in for SimulationCatalog implementing only the seams
    that ProjectRunsAccessor touches."""

    def __init__(self, rows: pd.DataFrame) -> None:
        self._rows = rows
        self.list_calls: list[dict[str, Any]] = []
        self.find_calls: list[dict[str, Any]] = []
        self.best_calls: list[tuple[str, str]] = []
        self.delete_calls: list[tuple[str, bool]] = []
        self.getitem_calls: list[str] = []

    def list_simulations(self, **filters: Any) -> pd.DataFrame:
        self.list_calls.append(filters)
        return self._rows

    def find(self, **filters: Any) -> list[str]:
        self.find_calls.append(filters)
        return [f"run-{filters.get('solver', 'any')}"]

    def best(self, project: str, metric: str) -> str:
        self.best_calls.append((project, metric))
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


# --- ProjectRunsAccessor.list -------------------------------------------------


def test_list_scopes_query_to_project_name() -> None:
    store = _FakeStore(_rows("a", "b"))
    accessor = ProjectRunsAccessor(_fake_project(store, project_name="naizin"))

    df = accessor.list()

    assert store.list_calls == [{"project": "naizin"}]
    assert list(df["sim_id"]) == ["a", "b"]


def test_list_returns_empty_frame_when_store_is_none() -> None:
    accessor = ProjectRunsAccessor(_fake_project(None))

    df = accessor.list()

    assert isinstance(df, pd.DataFrame)
    assert df.empty


# --- ProjectRunsAccessor.find -------------------------------------------------


def test_find_injects_project_and_forwards_filters() -> None:
    store = _FakeStore(_rows())
    accessor = ProjectRunsAccessor(_fake_project(store, project_name="flume"))

    result = accessor.find(solver="modflow6", status="completed")

    assert store.find_calls == [{"project": "flume", "solver": "modflow6", "status": "completed"}]
    assert result == ["run-modflow6"]


def test_find_returns_empty_list_when_store_is_none() -> None:
    accessor = ProjectRunsAccessor(_fake_project(None))

    assert accessor.find(solver="modflow6") == []


# --- ProjectRunsAccessor.latest ----------------------------------------------


def test_latest_selects_last_row_and_resolves_run() -> None:
    store = _FakeStore(_rows("first", "second", "third"))
    accessor = ProjectRunsAccessor(_fake_project(store))

    run = accessor.latest()

    # latest() must pick the bottom row of the listing, then look it up.
    assert store.getitem_calls == ["third"]
    assert run == "run-object-third"


def test_latest_returns_none_when_no_runs() -> None:
    store = _FakeStore(_rows())
    accessor = ProjectRunsAccessor(_fake_project(store))

    assert accessor.latest() is None
    assert store.getitem_calls == []


def test_latest_returns_none_when_store_is_none() -> None:
    accessor = ProjectRunsAccessor(_fake_project(None))

    assert accessor.latest() is None


# --- ProjectRunsAccessor.best ------------------------------------------------


def test_best_delegates_to_store_with_project_and_metric() -> None:
    store = _FakeStore(_rows("x"))
    accessor = ProjectRunsAccessor(_fake_project(store, project_name="nancon"))

    run = accessor.best("nse")

    assert store.best_calls == [("nancon", "nse")]
    assert run == "best-nse"


def test_best_returns_none_when_store_is_none() -> None:
    accessor = ProjectRunsAccessor(_fake_project(None))

    assert accessor.best("nse") is None


# --- ProjectRunsAccessor.delete ----------------------------------------------


def test_delete_forwards_sim_id_and_remove_storage_flag() -> None:
    store = _FakeStore(_rows("a"))
    accessor = ProjectRunsAccessor(_fake_project(store))

    accessor.delete("sim-42", remove_storage=False)

    assert store.delete_calls == [("sim-42", False)]


def test_delete_defaults_remove_storage_to_true() -> None:
    store = _FakeStore(_rows("a"))
    accessor = ProjectRunsAccessor(_fake_project(store))

    accessor.delete("sim-7")

    assert store.delete_calls == [("sim-7", True)]


def test_delete_is_noop_when_store_is_none() -> None:
    accessor = ProjectRunsAccessor(_fake_project(None))

    # Must not raise even though there is no store to delegate to.
    accessor.delete("sim-1")


# --- ProjectDataAccessor.missing ---------------------------------------------


def _data_project(plan_types: Any, loaded: set[str]) -> SimpleNamespace:
    ctx = SimpleNamespace(data_plan=SimpleNamespace(types=plan_types))
    return SimpleNamespace(_ctx=ctx, data_loaded=loaded)


def test_missing_returns_planned_types_not_yet_loaded() -> None:
    project = _data_project(
        plan_types=("precipitation", "temperature", "et0"),
        loaded={"precipitation"},
    )
    accessor = ProjectDataAccessor(project)

    assert accessor.missing() == ["temperature", "et0"]


def test_missing_preserves_plan_order() -> None:
    project = _data_project(
        plan_types=("c", "a", "b"),
        loaded=set(),
    )
    accessor = ProjectDataAccessor(project)

    assert accessor.missing() == ["c", "a", "b"]


def test_missing_returns_empty_when_all_loaded() -> None:
    project = _data_project(
        plan_types=("precipitation", "temperature"),
        loaded={"precipitation", "temperature", "extra"},
    )
    accessor = ProjectDataAccessor(project)

    assert accessor.missing() == []


def test_missing_handles_none_plan_types() -> None:
    project = _data_project(plan_types=None, loaded={"precipitation"})
    accessor = ProjectDataAccessor(project)

    # The accessor coerces a falsy ``types`` to an empty tuple.
    assert accessor.missing() == []


# --- ProjectDataAccessor.list ------------------------------------------------


def test_data_list_returns_sorted_loaded_variables() -> None:
    project = _data_project(plan_types=(), loaded={"temperature", "precipitation", "et0"})
    accessor = ProjectDataAccessor(project)

    df = accessor.list()

    assert list(df["variable"]) == ["et0", "precipitation", "temperature"]


def test_data_list_filters_to_requested_variable() -> None:
    project = _data_project(plan_types=(), loaded={"temperature", "precipitation"})
    accessor = ProjectDataAccessor(project)

    df = accessor.list(variable="temperature")

    assert list(df["variable"]) == ["temperature"]


def test_data_list_unknown_variable_yields_empty_frame() -> None:
    project = _data_project(plan_types=(), loaded={"temperature"})
    accessor = ProjectDataAccessor(project)

    df = accessor.list(variable="nope")

    assert list(df["variable"]) == []
