"""The scope in which a step opens the store of its run.

The context holds the run directory, never a live handle. A step opens the store of that
directory, writes, and closes it before it returns.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import PipelineError
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.results.storage.run_facts import facts_path
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.workflow.record.run_store import run_store
from tests._helpers.run_stores import open_run_store


def _ctx(*, save_catalog: bool, lightweight: bool, run_dir: Path | None) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(
                results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=save_catalog))
            )
        ),
        execution=SimpleNamespace(lightweight=lightweight),
        setup=SimpleNamespace(workspace=None),
        run_dir=run_dir,
    )


def test_context_has_no_store_field() -> None:
    fields = set(WorkflowContext.__dataclass_fields__)
    assert "store" not in fields
    assert {"run_dir", "attempt", "lineage", "calibrated_by"} <= fields


def test_persisted_run_needs_a_directory() -> None:
    ctx = _ctx(save_catalog=True, lightweight=False, run_dir=None)
    with pytest.raises(PipelineError, match="no directory"), run_store(ctx):
        pass


def test_scope_writes_the_facts_back(tmp_path: Path) -> None:
    opened = open_run_store(tmp_path / "p", "case")
    opened.close()
    ctx = _ctx(save_catalog=True, lightweight=False, run_dir=opened.run_dir)
    ctx.cfg.simulation.results.persistence = RunStore.open(opened.run_dir).persistence

    with run_store(ctx) as store:
        assert isinstance(store, RunStore)
        assert store.sim_id == opened.sim_id
        store.write_parameters(store.sim_id, [{"param_name": "K", "value": 2e-5}])

    assert store._closed
    assert facts_path(opened.run_dir).is_file()
    with RunStore.open(opened.run_dir) as again:
        assert [p.value for p in again.facts.parameters] == [2e-5]
