"""The export step, the scratch cleanup, the exports after the seal and the seal step.

The step cleans the scratch of the run. Solver files kept under ``keep_solver_files`` move
into ``runs/<run>/solver/``, an entry the seal never inventories, because the close of a
sealed attempt removes ``<run>/.hmp/``. Data requests and metadata views (STAC, RO-Crate,
PROV) are written after the seal under ``runs/<run>/exports/``. The preprocessing tree is
a rebuildable cache, dropped at the end of whoever owns the session. A replay seals its
values classed against its source run.
"""

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
from hydromodpy.catchment.preprocess.preprocessing_cleanup import cleanup_stable_folder
from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import ConfigError, ExportError
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.core.state.scratch import PREPROCESSING_DIRNAME
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.exporters.export_spec import load_export_requests
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage import scratch as scratch_module
from hydromodpy.results.storage.attempt import claim_run_directory
from hydromodpy.results.storage.contract import (
    ALLOWED_RUN_ENTRIES,
    PUBLICATION_FILENAME,
    RUN_SOLVER_DIRNAME,
    UNSEALED_RUN_ENTRIES,
)
from hydromodpy.results.storage.run_profile import read_profile
from hydromodpy.schema.lineage import Lineage
from hydromodpy.solver.base.plan import ProcessRun, RunSlot, SimulationPlan, SolverRun
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.export import step_cleanup_preprocessing, step_cleanup_scratch
from hydromodpy.workflow.steps.prepare_solver.dispatch import bind_run_directory, initial_facts
from hydromodpy.workflow.steps.prepare_solver.facts import collect_effective_config_snapshot
from tests._helpers.run_records import make_record


def test_uncatalogued_run_cleans_scratch_only(monkeypatch) -> None:
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


def test_step_needs_a_context() -> None:
    with pytest.raises(ConfigError, match="requires 'ctx'"):
        export_module.ExportStep().run(PipelineState(run_id="run-1", data={}))


def test_artifacts_are_existing_project_relative_paths(tmp_path: Path) -> None:
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
        if r.getMessage().startswith(("Run completed", "next: hmp show"))
    ]


def _kept_ctx(run_dir: Path, *, persisted: bool = True) -> SimpleNamespace:
    # The attempt works in <run>/.hmp/scratch with one model folder.
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


def test_solver_entry_is_never_inventoried() -> None:
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


def test_resume_replaces_the_kept_folder(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo"
    stale = run_dir / RUN_SOLVER_DIRNAME / "model_a"
    stale.mkdir(parents=True)
    (stale / "old.lst").write_text("old", encoding="utf-8")
    ctx = _kept_ctx(run_dir)

    step_cleanup_scratch(ctx, keep_solver_files=True)

    assert sorted(path.name for path in stale.iterdir()) == ["model_a.disv"]


def test_run_without_a_directory_keeps_its_scratch(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo"
    ctx = _kept_ctx(run_dir, persisted=False)

    step_cleanup_scratch(ctx, keep_solver_files=True)

    assert (run_dir / ".hmp" / "scratch" / "model_a" / "model_a.disv").is_file()
    assert not (run_dir / RUN_SOLVER_DIRNAME).exists()


def test_spared_folder_stays_in_the_scratch(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo"
    ctx = _kept_ctx(run_dir)
    owned = run_dir / ".hmp" / "scratch" / "model_a"

    step_cleanup_scratch(ctx, keep_solver_files=True, spare=(owned,))

    assert (owned / "model_a.disv").is_file()
    assert not (run_dir / RUN_SOLVER_DIRNAME).exists()


def _requests_ctx(run_dir: Path, requests) -> SimpleNamespace:
    results_cfg = SimpleNamespace(
        keep_solver_files=True,
        keep_face_flows=False,
        persistence=SimpleNamespace(save_catalog=True),
    )
    return SimpleNamespace(
        sim_id="0123456789abcdef",
        run_dir=run_dir,
        attempt=1,
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results_cfg), export=requests),
        execution=SimpleNamespace(simulation_plan=SimpleNamespace(runs=()), lightweight=False),
        setup=SimpleNamespace(run_id="run-1", workspace=None),
        budget_terms=BudgetKeep.everything(),
    )


@pytest.mark.parametrize("keep", [False, True])
def test_cleanup_per_solver_run_under_the_retention(
    monkeypatch, tmp_path: Path, keep: bool
) -> None:
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


def _sealed_run_dir(tmp_path: Path) -> tuple[Path, object]:
    record = make_record()
    run_dir = tmp_path / record.run.rel_dir
    run_dir.mkdir(parents=True)
    record.write(run_dir)
    return run_dir, record


_HEAD_AND_CRATE = [
    {"variables": "head", "time": "last"},
    {"variables": "all", "format": "rocrate", "folder": "crate"},
]


def _fake_sealed_store(monkeypatch, opened: list) -> None:
    @contextmanager
    def fake_store(ctx):
        opened.append(Path(ctx.run_dir))
        yield SimpleNamespace()

    monkeypatch.setattr(export_module, "sealed_run_store", fake_store)


def test_exports_are_written_after_the_seal(monkeypatch, tmp_path: Path, caplog) -> None:
    run_dir, record = _sealed_run_dir(tmp_path)
    requests = load_export_requests(_HEAD_AND_CRATE)
    opened: list[Path] = []
    seen: list = []
    _fake_sealed_store(monkeypatch, opened)
    head = run_dir / "exports" / "head_last.tif"

    def fake_data(_store, sim_id, data_requests):
        seen.append((sim_id, list(data_requests)))
        return [head]

    monkeypatch.setattr(request_module, "export_data_requests", fake_data)
    caplog.set_level(logging.INFO, logger=export_module.logger.name)

    written = export_module.step_after_seal(_requests_ctx(run_dir, requests))

    crate = run_dir / "exports" / "crate" / "ro-crate-metadata.json"
    assert written == [head, crate]
    assert opened == [run_dir]
    assert seen == [("0123456789abcdef", [requests[0]])]
    assert read_identity_from(crate).sim_id == record.run.sim_id
    assert [entry.file for entry in Ledger.read(run_dir / "exports").entries] == [
        "crate/ro-crate-metadata.json"
    ]
    assert [(line.kind, line.name) for line in read_profile(run_dir).lines] == [
        ("export", "data"),
        ("export", "views"),
    ]
    announced = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Exported")]
    assert announced == [announced[0]]
    assert announced[0].startswith("Exported 2 file(s) -> ")


@pytest.mark.parametrize(
    ("requests", "level", "opens_the_store"),
    [
        pytest.param([_HEAD_AND_CRATE[1]], None, False, id="views only open no store"),
        pytest.param(_HEAD_AND_CRATE, "research", False, id="a research run writes no data"),
        pytest.param(_HEAD_AND_CRATE, "result", True, id="a result run writes its data"),
    ],
)
def test_store_opens_only_for_data_of_a_rendering_run(
    monkeypatch, tmp_path: Path, requests, level, opens_the_store
) -> None:
    run_dir, _record = _sealed_run_dir(tmp_path)
    opened: list[Path] = []
    _fake_sealed_store(monkeypatch, opened)
    monkeypatch.setattr(request_module, "export_data_requests", lambda *_a: [])
    ctx = _requests_ctx(run_dir, load_export_requests(requests))
    ctx.level = level

    export_module.step_after_seal(ctx)

    assert bool(opened) is opens_the_store


def test_failed_export_names_hmp_export(monkeypatch, tmp_path: Path, caplog) -> None:
    run_dir, record = _sealed_run_dir(tmp_path)
    requests = load_export_requests(_HEAD_AND_CRATE)
    _fake_sealed_store(monkeypatch, [])

    def failing(*_a):
        raise ExportError("Export failed for run x: no field head")

    monkeypatch.setattr(request_module, "export_data_requests", failing)
    caplog.set_level(logging.INFO, logger="hydromodpy")

    with pytest.raises(ExportError) as raised:
        export_module.step_after_seal(_requests_ctx(run_dir, requests))

    name = record.run.name
    assert str(raised.value).startswith(
        f"run {name} is sealed; write the exports again with hmp export {name}: "
    )
    assert "no field head" in str(raised.value)
    # The views still had their turn, and the recap of a completed run waits.
    assert (run_dir / "exports" / "crate" / "ro-crate-metadata.json").is_file()
    assert (run_dir / "manifest.json").is_file()
    assert _recap_lines(caplog) == []


@pytest.fixture
def preprocessing_tree(tmp_path):
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


def test_preprocessing_cleanup_is_idempotent(preprocessing_tree) -> None:
    _, geographic = preprocessing_tree
    cleanup_stable_folder(geographic)

    assert cleanup_stable_folder(geographic) == 0


def test_no_geographic_no_preprocessing_cleanup() -> None:
    assert step_cleanup_preprocessing(_preprocessing_ctx(None)) == 0


def test_keep_preprocessing_flag(preprocessing_tree) -> None:
    # Project.simulate sets the flag; the run must not drop what it borrows.
    stable, geographic = preprocessing_tree
    ctx = _preprocessing_ctx(geographic)

    export_module.ExportStep().run(
        PipelineState(run_id="sweep", data={"ctx": ctx, "keep_preprocessing": True})
    )
    assert stable.is_dir()

    export_module.ExportStep().run(PipelineState(run_id="single", data={"ctx": ctx}))
    assert not stable.exists()


def test_session_without_promotion_drops_the_tree(preprocessing_tree) -> None:
    stable, geographic = preprocessing_tree

    release_session_scratch(_trial_ctx(geographic))

    assert not stable.exists()


def test_session_cleanup_failure_is_silent(monkeypatch, preprocessing_tree) -> None:
    # It runs in a finally: raising there would mask the real error.
    _, geographic = preprocessing_tree

    def boom(*_args, **_kwargs):
        raise OSError("device busy")

    monkeypatch.setattr(
        "hydromodpy.catchment.preprocess.preprocessing_cleanup.cleanup_stable_folder", boom
    )
    release_session_scratch(_trial_ctx(geographic))


def _scratch_ctx(scratch: Path) -> SimpleNamespace:
    return SimpleNamespace(
        setup=SimpleNamespace(
            workspace=SimpleNamespace(solver_scratch_folder=scratch),
        )
    )


def test_scratch_cleanup_failure_is_raised(monkeypatch, tmp_path: Path) -> None:
    scratch = tmp_path / ".solver_scratch"
    (scratch / "sim-0001").mkdir(parents=True)

    def fail_rmtree(_path: Path) -> None:
        raise OSError("locked")

    monkeypatch.setattr(scratch_module.shutil, "rmtree", fail_rmtree)

    with pytest.raises(ExportError, match="Could not remove solver scratch directory"):
        export_module.step_cleanup_scratch(_scratch_ctx(scratch))


def test_scratch_cleanup_retries_after_releasing_handles(monkeypatch, tmp_path: Path) -> None:
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


def test_scratch_cleanup_spares_promoted_folders(tmp_path: Path) -> None:
    # A calibration keeps trial solver folders for their own promotion.
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


def test_empty_scratch_only_is_dropped(tmp_path: Path) -> None:
    scratch = tmp_path / ".solver_scratch"
    kept = scratch / "_preprocessing"
    kept.mkdir(parents=True)

    export_module.step_drop_empty_scratch(_scratch_ctx(scratch))
    assert scratch.is_dir()

    kept.rmdir()
    export_module.step_drop_empty_scratch(_scratch_ctx(scratch))
    assert not scratch.exists()


@contextmanager
def _store_context(store: object):
    yield store


def _seal_ctx(tmp_path: Path, *, strict: bool | None, replay_of: Path | None) -> PipelineState:
    ctx = SimpleNamespace(sim_id="0123456789abcdef", run_dir=tmp_path / "runs" / "probe.v2")
    data = {"ctx": ctx, "cfg": object()}
    if replay_of is not None:
        data["replay_of"] = replay_of
    if strict is not None:
        data["strict"] = strict
    return PipelineState(run_id="r", step_index=13, step_name="seal", data=data)


@pytest.mark.parametrize(
    ("strict", "expected"),
    [
        (True, True),
        (False, False),
        (None, False),
    ],
)
def test_replay_seal_classes_the_values(
    tmp_path: Path, monkeypatch, strict: bool | None, expected: bool
) -> None:
    store, seen = object(), {}
    monkeypatch.setattr(export_module, "run_is_persisted", lambda ctx: True)
    monkeypatch.setattr(export_module, "run_store", lambda ctx: _store_context(store))
    monkeypatch.setattr(export_module, "step_after_seal", lambda ctx: [])

    def fake_seal(target, cfg, replay_of, *, strict: bool):
        seen.update(store=target, cfg=cfg, replay_of=replay_of, strict=strict)
        return SimpleNamespace(run=SimpleNamespace(name="probe.v2"))

    monkeypatch.setattr(export_module, "_seal_replay", fake_seal)
    source = tmp_path / "runs" / "probe"
    state = _seal_ctx(tmp_path, strict=strict, replay_of=source)

    advanced = export_module.SealStep().run(state)

    assert seen == {
        "store": store,
        "cfg": state.get("cfg"),
        "replay_of": source,
        "strict": expected,
    }
    assert advanced.step_index == 14


def test_source_kind_of_a_copy_and_of_a_run(
    tmp_path: Path,
) -> None:
    copy = tmp_path / "copies" / "probe"
    copy.mkdir(parents=True)
    (copy / PUBLICATION_FILENAME).write_text("{}", encoding="utf-8")
    run = tmp_path / "runs" / "probe.v2"
    run.mkdir(parents=True)
    # ``published`` is the word of a publication; replay.source tells the two apart.
    assert export_module._source_kind(copy) == "replay"
    assert export_module._source_kind(run) == "replay"
