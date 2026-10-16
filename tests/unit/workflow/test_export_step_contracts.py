from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import hydromodpy.workflow.steps.export as export_module
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.workflow.internals.state import PipelineState


@pytest.fixture
def sealed(tmp_path):
    """Return a factory of contexts naming a sealed run directory."""
    from tests.unit.results._run_record_factory import make_record

    def make(*, duration_s: float | None = 42.0, nse: float | None = 0.4567) -> SimpleNamespace:
        record = make_record()
        run = record.run.model_copy(update={"name": "nancon_step1", "duration_s": duration_s})
        score = None if nse is None else record.score.model_copy(update={"value": nse})
        run_dir = tmp_path / "runs" / "nancon_step1"
        run_dir.mkdir(parents=True, exist_ok=True)
        make_record(run=run, score=score).write(run_dir)
        return SimpleNamespace(
            sim_id="0123456789abcdef", run_dir=run_dir, cfg=SimpleNamespace(export=[])
        )

    return make


def test_an_uncatalogued_run_skips_store_work_but_cleans_scratch(monkeypatch) -> None:
    calls: list[tuple[str, object, bool | None]] = []

    def fake_cleanup(ctx, *, keep_solver_files: bool, spare=()) -> None:
        del spare
        calls.append(("cleanup", ctx, keep_solver_files))

    monkeypatch.setattr(export_module, "run_store", _refuse_the_store)
    monkeypatch.setattr(export_module, "step_cleanup_scratch", fake_cleanup)
    results_cfg = SimpleNamespace(
        keep_solver_files=True, persistence=SimpleNamespace(save_catalog=False)
    )
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results_cfg)),
        execution=SimpleNamespace(lightweight=False),
        setup=SimpleNamespace(workspace=None),
    )
    state = PipelineState(run_id="run-1", step_index=7, data={"ctx": ctx})

    advanced = export_module.ExportStep().run(state)

    assert calls == [("cleanup", ctx, True)]
    assert advanced.step_index == 8
    assert advanced.step_name == "export"
    assert advanced.get("ctx") is ctx


def _refuse_the_store(_ctx):
    raise AssertionError("this run must not open its store")


def test_a_lightweight_run_never_opens_its_store(monkeypatch) -> None:
    calls: list[str] = []

    def fake_cleanup(ctx, *, keep_solver_files: bool, spare=()) -> None:
        del spare
        calls.append(f"cleanup:{keep_solver_files}")

    monkeypatch.setattr(export_module, "run_store", _refuse_the_store)
    monkeypatch.setattr(export_module, "step_cleanup_scratch", fake_cleanup)
    results_cfg = SimpleNamespace(
        keep_solver_files=False, persistence=SimpleNamespace(save_catalog=True)
    )
    ctx = SimpleNamespace(
        sim_id="sim-123",
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results_cfg)),
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


def _recap_lines(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith(("Run completed", "next: hmp catalog"))
    ]


def test_the_run_recap_waits_for_the_export_phase_to_close(caplog, sealed) -> None:
    """The views and the cleanup run after the seal: the recap comes after them."""
    from hydromodpy.core import progress

    caplog.set_level(logging.INFO, logger="hydromodpy")
    ctx = sealed()
    with progress.phase("seal"):
        export_module.step_after_seal(ctx, wall_seconds=42.0)
        assert _recap_lines(caplog) == []
        get_logger("hydromodpy.test").info("views written")
    lines = _recap_lines(caplog)
    assert lines == [
        "Run completed: nancon_step1 [01234567] 42s nse=0.46",
        "next: hmp catalog show nancon_step1 | hmp publish nancon_step1 --to <folder> "
        "| hmp export nancon_step1 --list",
    ]
    messages = [r.getMessage() for r in caplog.records]
    assert messages.index("views written") < messages.index(lines[0])


def test_the_run_recap_prints_at_once_outside_a_phase(caplog, sealed) -> None:
    caplog.set_level(logging.INFO, logger="hydromodpy")
    export_module.step_after_seal(sealed(duration_s=None))
    assert _recap_lines(caplog)[0] == "Run completed: nancon_step1 [01234567] nse=0.46"


def test_the_recap_duration_is_the_seals_wall_time_not_the_solver_step_time(caplog, sealed) -> None:
    """wall_seconds only times run_solver and undercounts the run.

    The seal carries ``duration_s`` from ``started_at``/``ended_at``, the
    figure the catalog reports; the recap prints that, not the solver timer.
    """
    caplog.set_level(logging.INFO, logger="hydromodpy")
    export_module.step_after_seal(sealed(duration_s=26.0), wall_seconds=6.0)
    assert _recap_lines(caplog)[0] == "Run completed: nancon_step1 [01234567] 26s nse=0.46"


def test_a_run_without_a_score_says_no_nse(caplog, sealed) -> None:
    caplog.set_level(logging.INFO, logger="hydromodpy")
    export_module.step_after_seal(sealed(nse=None), wall_seconds=3.0)
    assert _recap_lines(caplog)[0] == "Run completed: nancon_step1 [01234567] 42s"
