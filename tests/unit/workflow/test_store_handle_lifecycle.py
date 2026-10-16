"""The run directory is bound once, by the step that opens the run.

``bind_run_directory`` reads the identity of the attempt off the outcome of
the directory it is handed, or claims the directory of the case when it is
handed none; the facts of the attempt are built from the context, written by
the store that opens on them, and no handle survives the step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.lineage import Lineage
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import claim_run_directory
from hydromodpy.workflow.steps import prepare_solver as prepare_solver_module
from hydromodpy.workflow.steps.prepare_solver.dispatch import bind_run_directory, initial_facts


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "demo_project"
    root.mkdir()
    (root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return root


def _ctx(project: Path, *, reserved_sim_id: str | None = None) -> SimpleNamespace:
    """A context shaped the way ``bind_run_directory`` and ``initial_facts`` read it."""
    return SimpleNamespace(
        parent_sim_id="parent-456",
        sim_id=None,
        run_dir=None,
        attempt=1,
        attempt_id=None,
        lineage=None,
        calibrated_by=None,
        reserved_sim_id=reserved_sim_id,
        config_path=project / "requested_name.toml",
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(
                results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=True)),
                description="",
                scientific_objective=None,
                contact_email=None,
                doi=None,
                time=None,
                rng_seed=None,
            ),
            flow=SimpleNamespace(flow_regime="steady"),
            geographic=SimpleNamespace(crs_project="EPSG:2154"),
            site=None,
            domain=None,
            model_dump=lambda mode="json": {"flow": {"k": 1e-5}},
        ),
        setup=SimpleNamespace(
            workspace=SimpleNamespace(root=project.parent, project_root=project),
            run_id="requested_name",
            flow=None,
            cell_mesh=None,
            domain=None,
            time_grid=None,
        ),
        execution=SimpleNamespace(
            simulation_plan=SimpleNamespace(
                runs=[SimpleNamespace(solver="boussinesq", process_type="flow")]
            )
        ),
    )


def test_without_a_directory_the_step_claims_the_case_of_the_context(tmp_path: Path) -> None:
    project = _project(tmp_path)
    ctx = _ctx(project)

    run_dir = bind_run_directory(
        ctx, run_dir=None, lineage=None, calibrated_by=None, run_overrides=None
    )

    assert run_dir == project / "runs" / "requested_name"
    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "running" and outcome.attempt == 1
    assert ctx.run_dir == run_dir
    assert ctx.sim_id == outcome.sim_id
    assert ctx.attempt == outcome.attempt
    assert ctx.lineage == Lineage(parent_sim_id="parent-456", kind="rerun")
    assert not hasattr(ctx, "store")


def test_a_reserved_directory_takes_the_reserved_id_once(tmp_path: Path) -> None:
    """A promotion reserves the directory and the id; the step writes the first outcome.

    The reservation is consumed here: a context replayed for another run must
    mint a fresh id rather than open twice under the same one.
    """
    project = _project(tmp_path)
    reserved = "0e6a5f5c-6f3c-4a6b-9c2f-2f0f5c1b7a11"
    ctx = _ctx(project, reserved_sim_id=reserved)
    run_dir = reserve_version_dirname(project, "run", "promoted")

    bound = bind_run_directory(
        ctx,
        run_dir=run_dir,
        lineage=Lineage(kind="promoted"),
        calibrated_by=None,
        run_overrides=None,
    )

    assert bound == run_dir
    assert ctx.sim_id == reserved
    assert ctx.reserved_sim_id is None
    assert ctx.lineage == Lineage(kind="promoted")
    assert read_outcome(run_dir).sim_id == reserved

    ctx.run_dir = None
    ctx.setup.run_id = "second"
    bind_run_directory(ctx, run_dir=None, lineage=None, calibrated_by=None, run_overrides=None)
    assert ctx.sim_id != reserved


def test_a_directory_claimed_before_the_pipeline_is_read_not_claimed_again(tmp_path: Path) -> None:
    project = _project(tmp_path)
    claim = claim_run_directory(project, "requested_name", case_id="requested_name", project="demo")
    ctx = _ctx(project)

    bind_run_directory(
        ctx, run_dir=claim.run_dir, lineage=None, calibrated_by=None, run_overrides=None
    )

    assert ctx.sim_id == claim.sim_id
    assert ctx.attempt == claim.attempt
    assert read_outcome(claim.run_dir).attempt == 1


def test_the_initial_facts_name_the_run_its_solver_and_its_hash(tmp_path: Path) -> None:
    project = _project(tmp_path)
    ctx = _ctx(project)
    bind_run_directory(
        ctx, run_dir=None, lineage=None, calibrated_by=None, run_overrides={"K": 1e-5}
    )

    facts = initial_facts(ctx, run_overrides={"K": 1e-5})

    assert facts.sim_id == ctx.sim_id
    assert facts.name == "requested_name"
    assert facts.case_id == "requested_name"
    assert facts.project == "demo_project"
    assert facts.solver == "boussinesq"
    assert facts.config_hash
    assert facts.config_source == "requested_name.toml"
    assert facts.lineage.kind == "rerun"


class _Dumpable:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def model_dump(self, **_kwargs) -> dict:
        return dict(self.payload)


def test_effective_config_snapshot_is_the_run_config_with_the_runtime_domain() -> None:
    """Nothing is forced at planning: the results section is the one written."""
    declared = {
        "workflow": {"mode": "simulation"},
        "domain": {"depth_model": {"kind": "constant_thickness", "thickness": 10.0}},
        "simulation": {"results": {"keep_solver_files": False}},
    }
    effective_domain = {
        "depth_model": {"kind": "constant_thickness", "thickness": 25.0},
    }
    ctx = SimpleNamespace(
        cfg=_Dumpable(declared),
        setup=SimpleNamespace(domain=SimpleNamespace(config=_Dumpable(effective_domain))),
    )

    snapshot = prepare_solver_module.collect_effective_config_snapshot(ctx)

    assert snapshot["domain"] == effective_domain
    assert snapshot["simulation"] == declared["simulation"]
    assert snapshot["workflow"] == declared["workflow"]


def _scratch_ctx(scratch: Path) -> SimpleNamespace:
    return SimpleNamespace(
        setup=SimpleNamespace(
            workspace=SimpleNamespace(solver_scratch_folder=scratch),
        )
    )


def test_step_cleanup_scratch_raises_on_cleanup_failure(monkeypatch, tmp_path: Path) -> None:
    from hydromodpy.core.exceptions import ExportError
    from hydromodpy.workflow.steps import export as export_module

    scratch = tmp_path / ".solver_scratch"
    (scratch / "sim-0001").mkdir(parents=True)

    def fail_rmtree(_path: Path) -> None:
        raise OSError("locked")

    monkeypatch.setattr(export_module.shutil, "rmtree", fail_rmtree)

    with pytest.raises(ExportError, match="Could not remove solver scratch directory"):
        export_module.step_cleanup_scratch(_scratch_ctx(scratch))


def test_step_cleanup_scratch_retries_after_releasing_handles(monkeypatch, tmp_path: Path) -> None:
    from hydromodpy.workflow.steps import export as export_module

    scratch = tmp_path / ".solver_scratch"
    run_dir = scratch / "sim-0001"
    run_dir.mkdir(parents=True)
    (run_dir / "locked.txt").write_text("temporary", encoding="utf-8")
    real_rmtree = export_module.shutil.rmtree
    calls = 0
    releases = 0

    def fake_release(_ctx) -> None:
        nonlocal releases
        releases += 1

    def flaky_rmtree(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("locked")
        real_rmtree(path)

    monkeypatch.setattr(export_module, "_SCRATCH_CLEANUP_RETRY_DELAYS", (0.01,))
    monkeypatch.setattr(export_module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(export_module, "_release_cleanup_handles", fake_release)
    monkeypatch.setattr(export_module.shutil, "rmtree", flaky_rmtree)

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


@dataclass
class _LoadedForcings:
    recharge: object | None = None


class _FakeZarr:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_step_persist_forcings_closes_zarr_when_no_forcings() -> None:
    from hydromodpy.workflow.steps.prepare_solver.prepare import step_persist_forcings

    fake_zarr = _FakeZarr()
    ctx = SimpleNamespace(sim_id="sim-123", loaded_data=_LoadedForcings())

    step_persist_forcings(ctx, store=SimpleNamespace(open_zarr=lambda _sim_id: fake_zarr))

    assert fake_zarr.close_calls == 1
