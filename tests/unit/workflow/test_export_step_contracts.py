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

    def finalize(self, sim_id: str, *, status: str) -> None:
        self.finalize_calls.append({"sim_id": sim_id, "status": status})

    def close(self) -> None:
        self.close_calls += 1


def test_step_seal_store_finalizes_through_the_handle_it_was_given() -> None:
    store = _RecordingStore()
    ctx = SimpleNamespace(sim_id="sim-123")

    export_module.step_seal_store(ctx, store=store, wall_seconds=12.5, status="failed")

    assert store.finalize_calls == [{"sim_id": "sim-123", "status": "failed"}]
    # Sealing does not close: the scope that opened the handle owns its end.
    assert store.close_calls == 0


def test_an_uncatalogued_run_skips_store_work_but_cleans_scratch(monkeypatch) -> None:
    calls: list[tuple[str, object, bool | None]] = []

    def fail_save(*_args, **_kwargs) -> None:
        raise AssertionError("step_save_run_artifacts should not run without an index")

    def fake_cleanup(ctx, *, keep_solver_files: bool) -> None:
        calls.append(("cleanup", ctx, keep_solver_files))

    monkeypatch.setattr(export_module, "step_save_run_artifacts", fail_save)
    monkeypatch.setattr(export_module, "step_cleanup_scratch", fake_cleanup)
    results_cfg = SimpleNamespace(
        keep_solver_files=True, persistence=SimpleNamespace(save_catalog=False)
    )
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results_cfg)),
        effective_results_config=None,
        execution=SimpleNamespace(lightweight=False),
        setup=SimpleNamespace(workspace=None),
    )
    state = PipelineState(run_id="run-1", step_index=7, data={"ctx": ctx})

    advanced = export_module.ExportStep().run(state)

    assert calls == [("cleanup", ctx, True)]
    assert advanced.step_index == 8
    assert advanced.step_name == "export"
    assert advanced.get("ctx") is ctx


def test_a_lightweight_run_never_opens_the_index(monkeypatch) -> None:
    calls: list[str] = []

    def fail_open(_ctx):
        raise AssertionError("a lightweight run must not open the index")

    def fake_cleanup(ctx, *, keep_solver_files: bool) -> None:
        calls.append(f"cleanup:{keep_solver_files}")

    monkeypatch.setattr(export_module, "run_catalog", fail_open)
    monkeypatch.setattr(export_module, "step_cleanup_scratch", fake_cleanup)
    results_cfg = SimpleNamespace(
        keep_solver_files=False, persistence=SimpleNamespace(save_catalog=True)
    )
    ctx = SimpleNamespace(
        sim_id="sim-123",
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results_cfg)),
        effective_results_config=None,
        execution=SimpleNamespace(
            simulation_plan=SimpleNamespace(runs=(SimpleNamespace(is_solver_backed=True),)),
            lightweight=True,
        ),
        setup=SimpleNamespace(
            run_id="run-1",
            workspace=SimpleNamespace(solver_scratch_folder=Path("/nonexistent/scratch")),
        ),
    )
    state = PipelineState(run_id="run-1", step_index=7, data={"ctx": ctx, "wall_seconds": 2.0})

    export_module.ExportStep().run(state)

    assert calls == ["cleanup:False"]


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
        sim_id="sim-123",
        forced_results_flags=("derived.accumulation_flux", "budget.spatial_fields"),
    )

    export_module.step_drop_intermediate_budget(ctx, store=_ZarrStore(handle))

    assert handle.dropped == ["budget"]
    assert handle.closed == 1


def test_step_drop_intermediate_budget_keeps_a_user_requested_budget() -> None:
    handle = _FakeZarr(present=True)
    ctx = SimpleNamespace(
        sim_id="sim-123",
        forced_results_flags=("derived.accumulation_flux",),
    )

    export_module.step_drop_intermediate_budget(ctx, store=_ZarrStore(handle))

    assert handle.dropped == []
