"""The export step, the scratch cleanup and the seal."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

import hydromodpy.results.exporters.request as request_module
import hydromodpy.workflow.steps.export as export_module
import hydromodpy.workflow.steps.run_outputs as post_run_module
from hydromodpy.calibration.runners.session_scope import release_session_scratch
from hydromodpy.catchment.preprocess import preprocessing_cleanup
from hydromodpy.catchment.preprocess.preprocessing_cleanup import cleanup_stable_folder
from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.core.state.scratch import PREPROCESSING_DIRNAME
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.exporters.export_spec import load_export_requests
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.lineage import Lineage
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import claim_run_directory
from hydromodpy.results.storage.contract import (
    ALLOWED_RUN_ENTRIES,
    RUN_SOLVER_DIRNAME,
    UNSEALED_RUN_ENTRIES,
)
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.export import step_cleanup_preprocessing, step_cleanup_scratch
from hydromodpy.workflow.steps.prepare_solver.dispatch import bind_run_directory, initial_facts
from hydromodpy.workflow.steps.prepare_solver.facts import collect_effective_config_snapshot
from tests._helpers.run_records import make_record


@pytest.fixture
def sealed(tmp_path):
    """Return a factory of contexts naming a sealed run directory."""
    from tests._helpers.run_records import make_record

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


def _refuse_the_store(_contract_ctx):
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
    from hydromodpy.core.console import progress

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


# --- test_cleanup_pipeline ---
# What ``[geographic] write_intermediates`` keeps, and what ``keep`` means.
#
# The preprocessing tree is a rebuildable cache, dropped at the end of whoever
# owns the session. Two different reasons keep it: the user asked for the
# rasters on disk, or a multi-run session is still reading them.


@pytest.fixture
def cleanup_calls(monkeypatch):
    """Record the ``keep`` each call asks for, without touching the disk."""
    kept: list[bool] = []
    monkeypatch.setattr(
        preprocessing_cleanup,
        "cleanup_stable_folder",
        lambda geo, *, keep=False: kept.append(keep) or 0,
    )
    return kept


def _ctx(geographic: object, *, write_intermediates: bool) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(geographic=SimpleNamespace(write_intermediates=write_intermediates)),
        setup=SimpleNamespace(workspace=None, geographic=geographic),
    )


@pytest.mark.parametrize("write_intermediates", [True, False])
def test_the_option_that_asked_for_the_rasters_keeps_the_tree(
    cleanup_calls, write_intermediates: bool
) -> None:
    step_cleanup_preprocessing(
        _ctx(SimpleNamespace(stable_folder=None), write_intermediates=write_intermediates)
    )

    assert cleanup_calls == [write_intermediates]


def test_a_session_that_owns_the_tree_keeps_it_whatever_the_option_says(cleanup_calls) -> None:
    """``keep=True`` is a lifetime statement, independent of the option."""
    step_cleanup_preprocessing(
        _ctx(SimpleNamespace(stable_folder=None), write_intermediates=False), keep=True
    )

    assert cleanup_calls == [True]


def test_a_run_without_a_geographic_runtime_cleans_nothing(cleanup_calls) -> None:
    assert step_cleanup_preprocessing(_ctx(None, write_intermediates=True)) == 0
    assert cleanup_calls == []


# --- test_kept_solver_files_outlive_the_seal ---
# Solver files kept under ``keep_solver_files`` move into ``runs/<run>/solver/``.
#
# The scratch of an attempt is ``<run>/.hmp/scratch/``, and the close of a
# sealed attempt removes ``<run>/.hmp/``. A solver folder left there would die
# with it, so the export step moves it into the run, an entry the seal never
# inventories. Without the flag the folder goes; a run without a directory keeps
# its scratch in place; the preprocessing tree and a folder another run owns
# stay where they are.


def _kept_ctx(run_dir: Path, *, persisted: bool = True) -> SimpleNamespace:
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
    ctx = _kept_ctx(run_dir)

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
    ctx = _kept_ctx(run_dir)

    step_cleanup_scratch(ctx, keep_solver_files=True)

    assert sorted(path.name for path in stale.iterdir()) == ["model_a.disv"]


def test_without_the_flag_the_solver_folders_go(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo"
    ctx = _kept_ctx(run_dir)

    step_cleanup_scratch(ctx, keep_solver_files=False)

    assert not (run_dir / RUN_SOLVER_DIRNAME).exists()
    assert not (run_dir / ".hmp" / "scratch" / "model_a").exists()


def test_a_run_without_a_directory_keeps_its_scratch_in_place(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo"
    ctx = _kept_ctx(run_dir, persisted=False)

    step_cleanup_scratch(ctx, keep_solver_files=True)

    assert (run_dir / ".hmp" / "scratch" / "model_a" / "model_a.disv").is_file()
    assert not (run_dir / RUN_SOLVER_DIRNAME).exists()


def test_a_folder_another_run_owns_stays_in_the_scratch(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo"
    ctx = _kept_ctx(run_dir)
    owned = run_dir / ".hmp" / "scratch" / "model_a"

    step_cleanup_scratch(ctx, keep_solver_files=True, spare=(owned,))

    assert (owned / "model_a.disv").is_file()
    assert not (run_dir / RUN_SOLVER_DIRNAME).exists()


# --- test_the_export_step_runs_requests_around_the_seal ---
# The data requests are written before the seal and the metadata views after it.
#
# A data request (a field, a series, a layer) reads the fields of the run, so
# the export step writes it. A metadata view (STAC, RO-Crate, PROV) renders the
# seal, so :func:`step_after_seal` writes it once the run is sealed, from the
# directory alone. Every file lands under ``runs/<run>/exports/`` and the
# console says how many files were written and where.


def _requests_ctx(run_dir: Path, requests) -> SimpleNamespace:
    results_cfg = SimpleNamespace(
        keep_solver_files=True, persistence=SimpleNamespace(save_catalog=True)
    )
    return SimpleNamespace(
        sim_id="0123456789abcdef",
        run_dir=run_dir,
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results_cfg), export=requests),
        execution=SimpleNamespace(simulation_plan=SimpleNamespace(runs=()), lightweight=False),
        setup=SimpleNamespace(run_id="run-1", workspace=None),
        budget_terms=BudgetKeep.everything(),
    )


def test_the_export_step_writes_the_data_requests_only(monkeypatch, tmp_path: Path) -> None:
    seen: list = []
    requests = load_export_requests(
        [{"variables": "head", "time": "last"}, {"variables": "all", "format": "rocrate"}]
    )

    @contextmanager
    def fake_store(_requests_ctx):
        yield SimpleNamespace()

    def fake_results(_store, _sim_id, requests):
        seen.append(requests)
        return [tmp_path / "runs" / "run-1" / "exports" / "head_last.tif"]

    monkeypatch.setattr(export_module, "run_store", fake_store)
    monkeypatch.setattr(export_module, "step_cleanup_scratch", lambda *_a, **_k: None)
    monkeypatch.setattr(export_module, "step_cleanup_preprocessing", lambda *_a, **_k: 0)
    monkeypatch.setattr(export_module, "step_drop_empty_scratch", lambda *_a, **_k: None)
    monkeypatch.setattr(request_module, "export_data_requests", fake_results)
    monkeypatch.setattr(post_run_module, "cleanup_solver_outputs", lambda **_k: None)

    export_module.ExportStep().run(
        PipelineState(run_id="run-1", step_index=7, data={"ctx": _requests_ctx(tmp_path, requests)})
    )

    assert seen == [requests]


@pytest.mark.parametrize("keep", [False, True])
def test_the_export_step_cleans_each_solver_run_under_the_retention_of_the_run(
    monkeypatch, tmp_path: Path, keep: bool
) -> None:
    from hydromodpy.solver.base.plan import ProcessRun, RunSlot, SimulationPlan, SolverRun

    mesh = ProcessRun(id="mesh::c", process_id="mesh", process_type="mesh", solver="c")
    flow = ProcessRun(id="flow::m", process_id="flow", process_type="flow", solver="m")
    solved = SolverRun(slot=RunSlot(tmp_path, "island"), output_dir=tmp_path / "island")
    cleaned: list[tuple] = []

    @contextmanager
    def fake_store(_ctx):
        yield SimpleNamespace()

    monkeypatch.setattr(export_module, "run_store", fake_store)
    monkeypatch.setattr(export_module, "step_cleanup_scratch", lambda *_a, **_k: None)
    monkeypatch.setattr(export_module, "step_cleanup_preprocessing", lambda *_a, **_k: 0)
    monkeypatch.setattr(export_module, "step_drop_empty_scratch", lambda *_a, **_k: None)
    monkeypatch.setattr(request_module, "export_data_requests", lambda *_a: [])
    monkeypatch.setattr(
        post_run_module,
        "cleanup_solver_outputs",
        lambda *, ctx, retention: cleaned.append((ctx.run.id, ctx.solver_run, retention)),
    )
    ctx = _requests_ctx(tmp_path, [])
    ctx.cfg.simulation.results.keep_solver_files = keep
    ctx.execution = SimpleNamespace(
        simulation_plan=SimulationPlan(name="run", description="run", runs=(mesh, flow)),
        solver_runs={flow.id: solved},
        lightweight=False,
    )
    ctx.budget_terms = BudgetKeep.of_terms(("drain",))

    export_module.ExportStep().run(PipelineState(run_id="run-1", step_index=7, data={"ctx": ctx}))

    assert [(run_id, run) for run_id, run, _ in cleaned] == [(flow.id, solved)]
    retention = cleaned[0][2]
    assert retention.solver_files is keep
    assert retention.budget == BudgetKeep.of_terms(("drain",))


def test_the_views_are_written_after_the_seal_from_the_directory(tmp_path: Path, caplog) -> None:
    record = make_record()
    run_dir = tmp_path / record.run.rel_dir
    run_dir.mkdir(parents=True)
    record.write(run_dir)
    requests = load_export_requests(
        [
            {"variables": "head", "time": "last"},
            {"variables": "all", "format": "rocrate", "folder": "crate"},
        ]
    )
    caplog.set_level(logging.INFO, logger=export_module.logger.name)

    written = export_module.step_after_seal(_requests_ctx(run_dir, requests))

    crate = run_dir / "exports" / "crate" / "ro-crate-metadata.json"
    assert written == [crate]
    assert read_identity_from(crate).sim_id == record.run.sim_id
    assert [entry.file for entry in Ledger.read(run_dir / "exports").entries] == [
        "crate/ro-crate-metadata.json"
    ]
    announced = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Exported")]
    assert announced == [announced[0]]
    assert announced[0].startswith("Exported 1 file(s) -> ")


# --- test_preprocessing_scratch_lifecycle ---
# Lifetime of ``.hmp/scratch/_preprocessing``.
#
# The tree holds the corrected DEM and the flow rasters: hundreds of MB, written
# once and then ingested into the project store. Every trial of a calibration
# session reads it, so no trial may delete it; but only a *promoted* run reaches
# the export step that normally does, so a session that promotes nothing used to
# leave the whole tree behind.


@pytest.fixture
def preprocessing_tree(tmp_path):
    """A populated ``_preprocessing`` tree and the geographic object naming it."""
    stable = tmp_path / ".hmp" / "scratch" / "_preprocessing"
    (stable / "geographic").mkdir(parents=True)
    (stable / "demcorrecflow").mkdir(parents=True)
    (stable / "geographic" / "watershed.tif").write_bytes(b"x" * 4096)
    (stable / "demcorrecflow" / "dem_breach.tif").write_bytes(b"y" * 8192)
    return stable, SimpleNamespace(stable_folder=str(stable))


def _preprocessing_ctx(geographic: object, *, write_intermediates: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        setup=SimpleNamespace(geographic=geographic, workspace=None),
        cfg=SimpleNamespace(
            geographic=SimpleNamespace(write_intermediates=write_intermediates),
            simulation=SimpleNamespace(
                results=SimpleNamespace(
                    keep_solver_files=False,
                    persistence=SimpleNamespace(save_catalog=False),
                )
            ),
        ),
        execution=SimpleNamespace(lightweight=False),
    )


def _trial_ctx(geographic: object, *, write_intermediates: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        ctx=SimpleNamespace(setup=SimpleNamespace(geographic=geographic)),
        base_cfg=SimpleNamespace(
            geographic=SimpleNamespace(write_intermediates=write_intermediates)
        ),
    )


def test_cleanup_reports_the_bytes_it_frees(preprocessing_tree) -> None:
    stable, geographic = preprocessing_tree

    freed = cleanup_stable_folder(geographic)

    assert freed == 4096 + 8192
    assert not stable.exists()


def test_keeping_the_intermediates_keeps_the_tree(preprocessing_tree) -> None:
    stable, geographic = preprocessing_tree

    assert cleanup_stable_folder(geographic, keep=True) == 0
    assert stable.is_dir()


def test_cleanup_is_idempotent(preprocessing_tree) -> None:
    _, geographic = preprocessing_tree
    cleanup_stable_folder(geographic)

    assert cleanup_stable_folder(geographic) == 0


def test_export_step_drops_the_tree(preprocessing_tree) -> None:
    """The solver scratch can be redirected elsewhere; this tree cannot."""
    stable, geographic = preprocessing_tree

    freed = step_cleanup_preprocessing(_preprocessing_ctx(geographic))

    assert freed > 0
    assert not stable.exists()


def test_export_step_honours_write_intermediates(preprocessing_tree) -> None:
    stable, geographic = preprocessing_tree

    assert step_cleanup_preprocessing(_preprocessing_ctx(geographic, write_intermediates=True)) == 0
    assert stable.is_dir()


def test_export_step_without_geographic_does_nothing() -> None:
    assert step_cleanup_preprocessing(_preprocessing_ctx(None)) == 0


def test_export_step_keeps_the_tree_for_a_multi_run_session(preprocessing_tree) -> None:
    """A Project builds the tree once and runs many times off it."""
    stable, geographic = preprocessing_tree

    assert step_cleanup_preprocessing(_preprocessing_ctx(geographic), keep=True) == 0
    assert stable.is_dir()


def test_the_export_step_reads_keep_preprocessing_from_the_state(preprocessing_tree) -> None:
    """``Project.simulate`` sets the flag; the run must not drop what it borrows."""
    from hydromodpy.workflow.state import PipelineState
    from hydromodpy.workflow.steps.export import ExportStep

    stable, geographic = preprocessing_tree
    ctx = _preprocessing_ctx(geographic)

    ExportStep().run(PipelineState(run_id="sweep", data={"ctx": ctx, "keep_preprocessing": True}))
    assert stable.is_dir()

    ExportStep().run(PipelineState(run_id="single", data={"ctx": ctx}))
    assert not stable.exists()


def test_a_session_that_promotes_nothing_still_drops_the_tree(preprocessing_tree) -> None:
    stable, geographic = preprocessing_tree

    release_session_scratch(_trial_ctx(geographic))

    assert not stable.exists()


def test_a_session_keeps_the_tree_on_request(monkeypatch, preprocessing_tree) -> None:
    stable, geographic = preprocessing_tree
    monkeypatch.setenv("HMP_KEEP_TRIAL_SCRATCH", "1")

    release_session_scratch(_trial_ctx(geographic))

    assert stable.is_dir()


def test_a_session_cleanup_failure_never_propagates(monkeypatch, preprocessing_tree) -> None:
    """It runs in a ``finally``: raising there would mask the real error."""
    _, geographic = preprocessing_tree

    def boom(*_args, **_kwargs):
        raise OSError("device busy")

    monkeypatch.setattr(
        "hydromodpy.catchment.preprocess.preprocessing_cleanup.cleanup_stable_folder", boom
    )
    release_session_scratch(_trial_ctx(geographic))


def test_a_session_without_geographic_does_nothing() -> None:
    release_session_scratch(_trial_ctx(None))


def test_the_tree_outlives_a_single_trial(preprocessing_tree) -> None:
    """Trials share it: only the end of the session may drop it."""
    from hydromodpy.calibration.runners.sandbox import TrialSandbox

    stable, _ = preprocessing_tree
    scratch = stable.parent
    with TrialSandbox("run", 1, scratch_root=scratch) as sandbox:
        trial_dir = Path(scratch) / sandbox.model_name
        trial_dir.mkdir(parents=True)
        (trial_dir / "mfsim.nam").write_text("x")

    assert not trial_dir.exists()
    assert stable.is_dir()


# --- test_store_handle_lifecycle ---
# The run directory is bound once, by the step that opens the run.
#
# ``bind_run_directory`` reads the identity of the attempt off the outcome of
# the directory it is handed, or claims the directory of the case when it is
# handed none; the facts of the attempt are built from the context, written by
# the store that opens on them, and no handle survives the step.


def _scratch_ctx(scratch: Path) -> SimpleNamespace:
    return SimpleNamespace(
        setup=SimpleNamespace(
            workspace=SimpleNamespace(solver_scratch_folder=scratch),
        )
    )


def test_step_cleanup_scratch_raises_on_cleanup_failure(monkeypatch, tmp_path: Path) -> None:
    from hydromodpy.core.exceptions import ExportError
    from hydromodpy.results.storage import scratch as scratch_module
    from hydromodpy.workflow.steps import export as export_module

    scratch = tmp_path / ".solver_scratch"
    (scratch / "sim-0001").mkdir(parents=True)

    def fail_rmtree(_path: Path) -> None:
        raise OSError("locked")

    monkeypatch.setattr(scratch_module.shutil, "rmtree", fail_rmtree)

    with pytest.raises(ExportError, match="Could not remove solver scratch directory"):
        export_module.step_cleanup_scratch(_scratch_ctx(scratch))


def test_step_cleanup_scratch_retries_after_releasing_handles(monkeypatch, tmp_path: Path) -> None:
    from hydromodpy.results.storage import scratch as scratch_module
    from hydromodpy.workflow.steps import export as export_module

    scratch = tmp_path / ".solver_scratch"
    run_dir = scratch / "sim-0001"
    run_dir.mkdir(parents=True)
    (run_dir / "locked.txt").write_text("temporary", encoding="utf-8")
    real_rmtree = scratch_module.shutil.rmtree
    calls = 0
    releases = 0

    def fake_release() -> None:
        nonlocal releases
        releases += 1

    def flaky_rmtree(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("locked")
        real_rmtree(path)

    monkeypatch.setattr(scratch_module, "_SCRATCH_CLEANUP_RETRY_DELAYS", (0.01,))
    monkeypatch.setattr(scratch_module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(scratch_module, "release_cleanup_handles", fake_release)
    monkeypatch.setattr(scratch_module.shutil, "rmtree", flaky_rmtree)

    export_module.step_cleanup_scratch(_scratch_ctx(scratch))

    assert calls == 2
    assert releases == 2
    assert not run_dir.exists()


def test_step_cleanup_scratch_spares_the_preprocessing_tree(tmp_path: Path) -> None:
    """A run owns its solver folder, not the tree the whole session reads."""
    from hydromodpy.workflow.steps import export as export_module

    scratch = tmp_path / ".solver_scratch"
    run_dir = scratch / "sim-0001"
    run_dir.mkdir(parents=True)
    preprocessing = scratch / "_preprocessing" / "geographic"
    preprocessing.mkdir(parents=True)

    export_module.step_cleanup_scratch(_scratch_ctx(scratch))

    assert not run_dir.exists()
    assert preprocessing.is_dir()


def test_step_cleanup_scratch_spares_the_folders_another_promotion_owns(tmp_path: Path) -> None:
    """A calibration keeps trial solver folders for their own promotion."""
    from hydromodpy.workflow.steps import export as export_module

    scratch = tmp_path / ".solver_scratch"
    promoted = scratch / "run_trial000001"
    kept = scratch / "run_trial000002"
    shared = scratch / "_shared_recharge"
    for folder in (promoted, kept, shared):
        folder.mkdir(parents=True)

    export_module.step_cleanup_scratch(_scratch_ctx(scratch), spare=(str(kept),))

    assert kept.is_dir()
    assert not promoted.exists()
    assert not shared.exists()


def test_step_drop_empty_scratch_only_removes_an_empty_folder(tmp_path: Path) -> None:
    from hydromodpy.workflow.steps import export as export_module

    scratch = tmp_path / ".solver_scratch"
    kept = scratch / "_preprocessing"
    kept.mkdir(parents=True)

    export_module.step_drop_empty_scratch(_scratch_ctx(scratch))
    assert scratch.is_dir()

    kept.rmdir()
    export_module.step_drop_empty_scratch(_scratch_ctx(scratch))
    assert not scratch.exists()
