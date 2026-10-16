"""Solver files kept under ``keep_solver_files`` move into ``runs/<run>/solver/``.

The scratch of an attempt is ``<run>/.hmp/scratch/``, and the close of a
sealed attempt removes ``<run>/.hmp/``. A solver folder left there would die
with it, so the export step moves it into the run, an entry the seal never
inventories. Without the flag the folder goes; a run without a directory keeps
its scratch in place; the preprocessing tree and a folder another run owns
stay where they are.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.core.state.paths import PREPROCESSING_DIRNAME
from hydromodpy.results.storage.contract import (
    ALLOWED_RUN_ENTRIES,
    RUN_SOLVER_DIRNAME,
    UNSEALED_RUN_ENTRIES,
)
from hydromodpy.workflow.steps.export import step_cleanup_scratch


def _ctx(run_dir: Path, *, persisted: bool = True) -> SimpleNamespace:
    """A run whose attempt works in ``<run>/.hmp/scratch`` with one model folder."""
    scratch = run_dir / ".hmp" / "scratch"
    (scratch / "model_a").mkdir(parents=True)
    (scratch / "model_a" / "model_a.disv").write_text("disv", encoding="utf-8")
    (scratch / PREPROCESSING_DIRNAME).mkdir()
    results = SimpleNamespace(persistence=SimpleNamespace(save_catalog=persisted))
    return SimpleNamespace(
        run_dir=run_dir,
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results)),
        execution=SimpleNamespace(lightweight=False),
        setup=SimpleNamespace(workspace=SimpleNamespace(solver_scratch_folder=scratch)),
    )


def test_the_solver_entry_is_declared_and_never_inventoried() -> None:
    assert RUN_SOLVER_DIRNAME == "solver"
    assert RUN_SOLVER_DIRNAME in ALLOWED_RUN_ENTRIES
    assert RUN_SOLVER_DIRNAME in UNSEALED_RUN_ENTRIES


def test_kept_solver_folders_move_into_the_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo"
    ctx = _ctx(run_dir)

    step_cleanup_scratch(ctx, keep_solver_files=True)

    kept = run_dir / RUN_SOLVER_DIRNAME / "model_a" / "model_a.disv"
    assert kept.read_text(encoding="utf-8") == "disv"
    assert not (run_dir / ".hmp" / "scratch" / "model_a").exists()
    assert (run_dir / ".hmp" / "scratch" / PREPROCESSING_DIRNAME).is_dir()


def test_a_resumed_run_replaces_the_folder_it_kept_before(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo"
    stale = run_dir / RUN_SOLVER_DIRNAME / "model_a"
    stale.mkdir(parents=True)
    (stale / "old.lst").write_text("old", encoding="utf-8")
    ctx = _ctx(run_dir)

    step_cleanup_scratch(ctx, keep_solver_files=True)

    assert sorted(path.name for path in stale.iterdir()) == ["model_a.disv"]


def test_without_the_flag_the_solver_folders_go(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo"
    ctx = _ctx(run_dir)

    step_cleanup_scratch(ctx, keep_solver_files=False)

    assert not (run_dir / RUN_SOLVER_DIRNAME).exists()
    assert not (run_dir / ".hmp" / "scratch" / "model_a").exists()


def test_a_run_without_a_directory_keeps_its_scratch_in_place(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo"
    ctx = _ctx(run_dir, persisted=False)

    step_cleanup_scratch(ctx, keep_solver_files=True)

    assert (run_dir / ".hmp" / "scratch" / "model_a" / "model_a.disv").is_file()
    assert not (run_dir / RUN_SOLVER_DIRNAME).exists()


def test_a_folder_another_run_owns_stays_in_the_scratch(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo"
    ctx = _ctx(run_dir)
    owned = run_dir / ".hmp" / "scratch" / "model_a"

    step_cleanup_scratch(ctx, keep_solver_files=True, spare=(owned,))

    assert (owned / "model_a.disv").is_file()
    assert not (run_dir / RUN_SOLVER_DIRNAME).exists()
