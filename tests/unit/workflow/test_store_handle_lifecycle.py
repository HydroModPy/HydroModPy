from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.workflow.run_catalog import run_catalog
from hydromodpy.workflow.steps import prepare_solver as prepare_solver_module


class _FakeZarr:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def _fake_catalog_class(registration, opened: list):
    """Return a Catalog stand-in recording what it was asked to register."""

    class FakeCatalog:
        def __init__(self, workspace_root, *, persistence=None) -> None:
            self.workspace_root = workspace_root
            self.persistence = persistence
            self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
            self.closed = 0
            opened.append(self)

        @classmethod
        def from_workspace(cls, workspace, *, persistence=None):
            return cls(workspace.project_root, persistence=persistence)

        def register_simulation(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return registration

        def close(self) -> None:
            self.closed += 1

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            self.close()

    return FakeCatalog


def _open_store_ctx(tmp_path: Path, *, reserved_sim_id: str | None = None) -> SimpleNamespace:
    """A context shaped the way ``step_register_run`` expects to find it."""
    return SimpleNamespace(
        parent_sim_id="parent-456",
        sim_id=None,
        reserved_sim_id=reserved_sim_id,
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(
                results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=True)),
                if_exists="replace",
            ),
            domain=None,
        ),
        setup=SimpleNamespace(
            workspace=SimpleNamespace(
                root=tmp_path / "workspace",
                project_root=tmp_path / "demo_project",
            ),
            run_id="requested_name",
            flow=None,
        ),
        execution=SimpleNamespace(
            simulation_plan=SimpleNamespace(
                runs=[SimpleNamespace(solver="boussinesq", process_type="flow")]
            )
        ),
    )


def _silence_store_writes(monkeypatch, catalog_class) -> None:
    """Neutralise everything ``step_register_run`` persists besides the id."""
    import hydromodpy.results.catalog as catalog_module

    monkeypatch.setattr(catalog_module, "Catalog", catalog_class)
    monkeypatch.setattr(prepare_solver_module, "collect_registration_kwargs", lambda ctx: {})
    monkeypatch.setattr(
        prepare_solver_module, "_register_tracked_input_files", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(prepare_solver_module, "step_persist_params", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare_solver_module, "step_persist_mesh", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        prepare_solver_module, "step_persist_geographic", lambda *args, **kwargs: None
    )


def test_step_register_run_closes_unused_bootstrap_zarr(monkeypatch, tmp_path: Path) -> None:
    fake_zarr = _FakeZarr()
    registration = SimpleNamespace(name="run_0002", replaced_sim_id=None, zarr=fake_zarr)
    ctx = _open_store_ctx(tmp_path)
    opened: list = []

    _silence_store_writes(monkeypatch, _fake_catalog_class(registration, opened))

    with run_catalog(ctx) as store:
        prepare_solver_module.step_register_run(ctx, store=store)

    assert ctx.sim_id is not None
    assert ctx.setup.run_id == "run_0002"
    assert opened[0].calls[0][1]["parent_sim_id"] == "parent-456"
    assert fake_zarr.close_calls == 1
    # The scope that opened the handle is the one that closed it.
    assert opened[0].closed == 1
    assert not hasattr(ctx, "store")


def test_step_register_run_takes_the_reserved_id_once(monkeypatch, tmp_path: Path) -> None:
    """A reserved id becomes the run id, and is not handed to a second run.

    Calibration promotion reserves the id so it can link the run to its
    session before the pipeline reaches the step that draws the figures. The
    reservation is consumed here: a context replayed for another run must mint
    a fresh id rather than register twice under the same one.
    """
    registration = SimpleNamespace(name="run_0003", replaced_sim_id=None, zarr=None)
    reserved = "0e6a5f5c-6f3c-4a6b-9c2f-2f0f5c1b7a11"
    ctx = _open_store_ctx(tmp_path, reserved_sim_id=reserved)
    opened: list = []

    _silence_store_writes(monkeypatch, _fake_catalog_class(registration, opened))

    with run_catalog(ctx) as store:
        prepare_solver_module.step_register_run(ctx, store=store)

    assert ctx.sim_id == reserved
    assert opened[0].calls[0][0][0] == reserved
    assert ctx.reserved_sim_id is None

    with run_catalog(ctx) as store:
        prepare_solver_module.step_register_run(ctx, store=store)

    assert ctx.sim_id != reserved


class _Dumpable:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def model_dump(self, **_kwargs) -> dict:
        return dict(self.payload)


def test_effective_config_snapshot_uses_runtime_domain_and_results() -> None:
    declared = {
        "workflow": {"mode": "simulation"},
        "domain": {"depth_model": {"kind": "constant_thickness", "thickness": 10.0}},
        "simulation": {"results": {"keep_solver_files": False}},
    }
    effective_domain = {
        "depth_model": {"kind": "constant_thickness", "thickness": 25.0},
    }
    effective_results = {
        "keep_solver_files": True,
        "persistence": {"save_catalog": True},
    }
    ctx = SimpleNamespace(
        cfg=_Dumpable(declared),
        setup=SimpleNamespace(domain=SimpleNamespace(config=_Dumpable(effective_domain))),
        effective_results_config=_Dumpable(effective_results),
    )

    snapshot = prepare_solver_module.collect_effective_config_snapshot(ctx)

    assert snapshot["domain"] == effective_domain
    assert snapshot["simulation"]["results"] == effective_results


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


def test_step_persist_forcings_closes_zarr_when_no_forcings() -> None:
    from hydromodpy.workflow.steps.prepare_solver.prepare import step_persist_forcings

    fake_zarr = _FakeZarr()
    ctx = SimpleNamespace(sim_id="sim-123", loaded_data=_LoadedForcings())

    step_persist_forcings(ctx, store=SimpleNamespace(open_zarr=lambda _sim_id: fake_zarr))

    assert fake_zarr.close_calls == 1
