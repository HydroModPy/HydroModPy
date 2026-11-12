"""The run store scope of a workflow."""

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

# --- test_run_store_scope ---
# The store of a run is a scope, not a field.
#
# ``WorkflowContext`` carries no live handle. What it carries is the directory
# of the run; a step that writes opens the store of that directory and closes
# it before returning. A run that keeps no store is told so by a predicate,
# and a run that asked for one and has no directory yet is a broken run.


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


def test_the_context_carries_no_store_handle() -> None:
    fields = set(WorkflowContext.__dataclass_fields__)
    assert "store" not in fields
    assert {"run_dir", "attempt", "lineage", "calibrated_by"} <= fields


def test_a_persisted_run_without_a_directory_is_a_broken_run(tmp_path: Path) -> None:
    ctx = _ctx(save_catalog=True, lightweight=False, run_dir=None)
    with pytest.raises(PipelineError, match="no directory"), run_store(ctx):
        pass


def test_the_scope_opens_the_store_of_the_run_and_writes_the_facts_back(tmp_path: Path) -> None:
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
