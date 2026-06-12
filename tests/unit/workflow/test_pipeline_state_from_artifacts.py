"""End-to-end resume relies on ``rebuild_state`` only.

Builds a pipeline mixing in-memory steps with persistent steps that
declare ``artifacts()`` and ``rebuild_state``. On resume, the runner must
re-execute the in-memory steps and rebuild from disk the persistent ones,
never touching the deleted pickle layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.journal import WorkflowJournal
from hydromodpy.workflow.runner import Pipeline


class _Memory:
    """In-memory step: re-executed at resume."""

    config_sections: ClassVar[tuple[str, ...]] = ()

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.calls += 1
        history = list(state.data.get("history", ()))
        history.append(("memory", self.name))
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            history=tuple(history),
        )


class _Persistent:
    """Persistent step: declares artefacts and supports rebuild_state."""

    config_sections: ClassVar[tuple[str, ...]] = ()

    def __init__(self, name: str, fail: bool = False) -> None:
        self.name = name
        self._fail = fail
        self.run_calls = 0
        self.rebuild_calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        if self._fail:
            raise RuntimeError(f"{self.name} crashed")
        self.run_calls += 1
        workspace = Path(state.get("workspace"))
        target = workspace / "artefacts" / f"{self.name}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.name, encoding="utf-8")
        history = list(state.data.get("history", ()))
        history.append(("persistent", self.name))
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            history=tuple(history),
        )

    def artifacts(self, state: PipelineState) -> tuple[str, ...]:
        return (f"artefacts/{self.name}.txt",)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        self.rebuild_calls += 1
        history = list(prior_state.data.get("history", ()))
        history.append(("rebuilt", self.name))
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            history=tuple(history),
        )


def _initial_state(tmp_path: Path, run_id: str) -> PipelineState:
    return PipelineState(
        run_id=run_id,
        data={"workspace": str(tmp_path), "history": ()},
    )


def test_full_run_writes_artefacts_and_journal(tmp_path: Path) -> None:
    blueprint = (
        _Memory("mem0"),
        _Memory("mem1"),
        _Persistent("p2"),
        _Persistent("p3"),
        _Persistent("p4"),
    )
    pipeline = Pipeline(blueprint, workspace=tmp_path)
    final = pipeline.run(_initial_state(tmp_path, "run-A"))

    assert final.step_name == "p4"
    for name in ("p2", "p3", "p4"):
        assert (tmp_path / "artefacts" / f"{name}.txt").is_file()

    catalog = Catalog(tmp_path)
    try:
        journal = WorkflowJournal(catalog)
        rows = journal.list_steps("run-A")
        assert [r.step_name for r in rows] == ["mem0", "mem1", "p2", "p3", "p4"]
        assert all(r.status == "completed" for r in rows)
    finally:
        catalog.close()


def test_resume_rebuilds_persistent_and_reexec_memory(tmp_path: Path) -> None:
    blueprint = (
        _Memory("mem0"),
        _Memory("mem1"),
        _Persistent("p2"),
        _Persistent("p3"),
        _Persistent("p4"),
    )
    pipeline = Pipeline(blueprint, workspace=tmp_path)
    pipeline.run(_initial_state(tmp_path, "run-B"))

    # second pipeline objects (fresh counters) to observe rebuild vs re-exec
    recovery = (
        _Memory("mem0"),
        _Memory("mem1"),
        _Persistent("p2"),
        _Persistent("p3"),
        _Persistent("p4"),
    )
    pipeline = Pipeline(recovery, workspace=tmp_path)
    final = pipeline.run(_initial_state(tmp_path, "run-B"), resume_from=3)

    mem0, mem1, p2, p3, p4 = recovery
    assert mem0.calls == 1
    assert mem1.calls == 1
    assert p2.rebuild_calls == 1
    assert p2.run_calls == 0
    assert p3.run_calls == 1
    assert p4.run_calls == 1
    assert ("rebuilt", "p2") in final.data["history"]
    assert ("persistent", "p3") in final.data["history"]


def test_no_pickle_files_anywhere(tmp_path: Path) -> None:
    blueprint = (_Memory("mem0"), _Persistent("p1"), _Persistent("p2"))
    pipeline = Pipeline(blueprint, workspace=tmp_path)
    pipeline.run(_initial_state(tmp_path, "run-C"))

    checkpoint_root = tmp_path / ".hmp" / "checkpoints"
    if checkpoint_root.exists():
        for entry in checkpoint_root.rglob("*"):
            assert entry.suffix not in (".pkl", ".pkl.zst", ".pickle")


def test_checkpoint_store_module_was_removed() -> None:
    with pytest.raises(ImportError):
        import hydromodpy.workflow.internals.checkpoint  # noqa: F401


def test_signed_pickle_module_was_removed() -> None:
    with pytest.raises(ImportError):
        import hydromodpy.core.io.signed_pickle  # noqa: F401
