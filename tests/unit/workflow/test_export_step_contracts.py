from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import hydromodpy.workflow.steps.export as export_module
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.state import PipelineState


class _RecordingStore:
    def __init__(self) -> None:
        self.finalize_calls: list[dict[str, object]] = []
        self.close_calls = 0

    def finalize(self, sim_id: str, *, status: str, duration_s: float) -> None:
        self.finalize_calls.append({"sim_id": sim_id, "status": status, "duration_s": duration_s})

    def close(self) -> None:
        self.close_calls += 1


def test_step_finalize_store_finalizes_closes_and_detaches_store() -> None:
    store = _RecordingStore()
    ctx = SimpleNamespace(store=store, sim_id="sim-123")

    export_module.step_finalize_store(ctx, wall_seconds=12.5, status="failed")

    assert store.finalize_calls == [{"sim_id": "sim-123", "status": "failed", "duration_s": 12.5}]
    assert store.close_calls == 1
    assert ctx.store is None


def test_step_finalize_store_still_closes_when_finalize_fails() -> None:
    class FailingStore(_RecordingStore):
        def finalize(self, sim_id: str, *, status: str, duration_s: float) -> None:
            super().finalize(sim_id, status=status, duration_s=duration_s)
            raise RuntimeError("catalog write failed")

    store = FailingStore()
    ctx = SimpleNamespace(store=store, sim_id="sim-123")

    with pytest.raises(RuntimeError, match="catalog write failed"):
        export_module.step_finalize_store(ctx)

    assert store.close_calls == 1
    assert ctx.store is None


def test_export_step_without_store_skips_store_work_but_cleans_scratch(monkeypatch) -> None:
    calls: list[tuple[str, object, bool | None]] = []

    def fail_save(*_args, **_kwargs) -> None:
        raise AssertionError("step_save_run_artifacts should not run without a store")

    def fake_cleanup(ctx, *, keep_solver_files: bool) -> None:
        calls.append(("cleanup", ctx, keep_solver_files))

    monkeypatch.setattr(export_module, "step_save_run_artifacts", fail_save)
    monkeypatch.setattr(export_module, "step_cleanup_scratch", fake_cleanup)
    results_cfg = SimpleNamespace(keep_solver_files=True)
    ctx = SimpleNamespace(
        store=None,
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results_cfg)),
        effective_results_config=None,
    )
    state = PipelineState(run_id="run-1", step_index=7, data={"ctx": ctx})

    advanced = export_module.ExportStep().run(state)

    assert calls == [("cleanup", ctx, True)]
    assert advanced.step_index == 8
    assert advanced.step_name == "export"
    assert advanced.get("ctx") is ctx


def test_export_step_lightweight_store_path_saves_finalizes_and_skips_auto_export(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_save(ctx, wall_seconds: float) -> None:
        calls.append(f"save:{wall_seconds}")

    def fake_finalize(ctx, *, wall_seconds: float = 0.0, status: str = "completed") -> None:
        calls.append(f"finalize:{wall_seconds}:{status}")

    def fake_cleanup(ctx, *, keep_solver_files: bool) -> None:
        calls.append(f"cleanup:{keep_solver_files}")

    monkeypatch.setattr(export_module, "step_save_run_artifacts", fake_save)
    monkeypatch.setattr(export_module, "step_finalize_store", fake_finalize)
    monkeypatch.setattr(export_module, "step_cleanup_scratch", fake_cleanup)
    results_cfg = SimpleNamespace(keep_solver_files=False)
    ctx = SimpleNamespace(
        store=object(),
        sim_id="sim-123",
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results_cfg)),
        effective_results_config=None,
        execution=SimpleNamespace(
            simulation_plan=SimpleNamespace(runs=(SimpleNamespace(is_solver_backed=True),)),
            lightweight=True,
        ),
        setup=SimpleNamespace(run_id="run-1"),
    )
    state = PipelineState(run_id="run-1", step_index=7, data={"ctx": ctx, "wall_seconds": 2.0})

    export_module.ExportStep().run(state)

    assert calls == ["save:2.0", "finalize:2.0:completed", "cleanup:False"]


def test_export_step_requires_context() -> None:
    with pytest.raises(ConfigError, match="requires 'ctx'"):
        export_module.ExportStep().run(PipelineState(run_id="run-1", data={}))


def test_export_artifacts_filters_to_existing_workspace_relative_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    export_path = project_root / "exports" / "head.parquet"
    duplicate = project_root / "exports" / "head.parquet"
    missing = project_root / "exports" / "missing.parquet"
    outside = tmp_path / "outside.parquet"
    export_path.parent.mkdir(parents=True)
    export_path.write_text("head", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    ctx = SimpleNamespace(
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=project_root))
    )
    state = PipelineState(
        run_id="run-1",
        data={
            "ctx": ctx,
            "export_paths": (export_path, str(duplicate), missing, outside, object()),
        },
    )

    assert export_module.ExportStep().artifacts(state) == ("exports/head.parquet",)


class _FakeZarr:
    """Minimal store handle recording which group was dropped."""

    def __init__(self, present: bool) -> None:
        self.present = present
        self.dropped: list[str] = []
        self.closed = 0

    def drop_group(self, name: str) -> int:
        self.dropped.append(name)
        return 12_730_000 if self.present else 0

    def close(self) -> None:
        self.closed += 1


class _ZarrStore(_RecordingStore):
    def __init__(self, handle: _FakeZarr) -> None:
        super().__init__()
        self.handle = handle

    def open_zarr(self, sim_id: str) -> _FakeZarr:
        return self.handle


def test_step_drop_intermediate_budget_removes_a_reconciled_budget() -> None:
    # Computing is not persisting: a budget switched on by the figure ->
    # derived -> budget cascade is an intermediate and leaves no trace.
    handle = _FakeZarr(present=True)
    ctx = SimpleNamespace(
        store=_ZarrStore(handle),
        sim_id="sim-123",
        forced_results_flags=("derived.accumulation_flux", "budget.spatial_fields"),
    )

    export_module.step_drop_intermediate_budget(ctx)

    assert handle.dropped == ["budget"]
    assert handle.closed == 1


def test_step_drop_intermediate_budget_keeps_a_user_requested_budget() -> None:
    handle = _FakeZarr(present=True)
    ctx = SimpleNamespace(
        store=_ZarrStore(handle),
        sim_id="sim-123",
        forced_results_flags=("derived.accumulation_flux",),
    )

    export_module.step_drop_intermediate_budget(ctx)

    assert handle.dropped == []
