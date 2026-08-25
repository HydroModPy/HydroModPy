from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.workflow.steps import prepare_solver as prepare_solver_module


class _FakeZarr:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _FakeStore:
    def __init__(self, registration) -> None:
        self.registration = registration
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.environment_calls: list[dict[str, object]] = []

    def register_simulation(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.registration

    def write_run_environment(self, *args, **kwargs) -> None:
        self.environment_calls.append({"args": args, "kwargs": kwargs})


def test_step_register_simulation_closes_unused_bootstrap_zarr(monkeypatch) -> None:
    fake_zarr = _FakeZarr()
    registration = SimpleNamespace(name="run_0001", replaced_sim_id=None, zarr=fake_zarr)
    store = _FakeStore(registration)
    ctx = SimpleNamespace(
        parent_sim_id="parent-123",
        store=store,
        cfg=SimpleNamespace(simulation=SimpleNamespace(if_exists="replace")),
        setup=SimpleNamespace(time_grid=None, workspace=SimpleNamespace(project_root=None)),
    )
    plan = SimpleNamespace(runs=[SimpleNamespace(solver="boussinesq", process_type="flow")])

    monkeypatch.setattr(prepare_solver_module, "collect_registration_kwargs", lambda ctx: {})

    final_name = prepare_solver_module.step_register_simulation(
        ctx,
        "sim-123",
        plan=plan,
        project_name="demo_project",
        name="requested_name",
    )

    assert final_name == "run_0001"
    assert store.calls[0][1]["parent_sim_id"] == "parent-123"
    assert fake_zarr.close_calls == 1


def _fake_catalog_class(registration):
    """Return a Catalog stand-in recording what it was asked to register."""

    class FakeCatalog:
        def __init__(self, workspace_root, *, persistence=None) -> None:
            self.workspace_root = workspace_root
            self.persistence = persistence
            self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        @classmethod
        def from_workspace(cls, workspace, *, persistence=None):
            return cls(workspace.project_root, persistence=persistence)

        def register_simulation(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return registration

    return FakeCatalog


def _open_store_ctx(tmp_path: Path, *, reserved_sim_id: str | None = None) -> SimpleNamespace:
    """A context shaped the way ``step_open_store`` expects to find it."""
    return SimpleNamespace(
        parent_sim_id="parent-456",
        store=None,
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
    """Neutralise everything ``step_open_store`` persists besides the id."""
    import hydromodpy.results.catalog as catalog_module

    monkeypatch.setattr(catalog_module, "Catalog", catalog_class)
    monkeypatch.setattr(prepare_solver_module, "collect_registration_kwargs", lambda ctx: {})
    monkeypatch.setattr(prepare_solver_module, "_register_tracked_input_files", lambda ctx: None)
    monkeypatch.setattr(prepare_solver_module, "step_persist_params", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare_solver_module, "step_persist_mesh", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        prepare_solver_module, "step_persist_geographic", lambda *args, **kwargs: None
    )


def test_step_open_store_closes_unused_bootstrap_zarr(monkeypatch, tmp_path: Path) -> None:
    fake_zarr = _FakeZarr()
    registration = SimpleNamespace(name="run_0002", replaced_sim_id=None, zarr=fake_zarr)
    ctx = _open_store_ctx(tmp_path)

    _silence_store_writes(monkeypatch, _fake_catalog_class(registration))

    prepare_solver_module.step_open_store(ctx)

    assert ctx.store is not None
    assert ctx.sim_id is not None
    assert ctx.setup.run_id == "run_0002"
    assert ctx.store.calls[0][1]["parent_sim_id"] == "parent-456"
    assert fake_zarr.close_calls == 1


def test_step_open_store_takes_the_reserved_id_once(monkeypatch, tmp_path: Path) -> None:
    """A reserved id becomes the run id, and is not handed to a second run.

    Calibration promotion reserves the id so it can link the run to its
    session before the pipeline reaches the step that draws the figures. The
    reservation is consumed here: a context replayed for another run must mint
    a fresh id rather than register twice under the same one.
    """
    registration = SimpleNamespace(name="run_0003", replaced_sim_id=None, zarr=None)
    reserved = "0e6a5f5c-6f3c-4a6b-9c2f-2f0f5c1b7a11"
    ctx = _open_store_ctx(tmp_path, reserved_sim_id=reserved)

    _silence_store_writes(monkeypatch, _fake_catalog_class(registration))

    prepare_solver_module.step_open_store(ctx)

    assert ctx.sim_id == reserved
    assert ctx.store.calls[0][0][0] == reserved
    assert ctx.reserved_sim_id is None

    ctx.store = None
    prepare_solver_module.step_open_store(ctx)

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


def test_step_cleanup_scratch_raises_on_cleanup_failure(monkeypatch, tmp_path: Path) -> None:
    from hydromodpy.core.exceptions import ExportError
    from hydromodpy.workflow.steps import export as export_module

    scratch = tmp_path / ".solver_scratch"
    scratch.mkdir()
    ctx = SimpleNamespace(
        setup=SimpleNamespace(
            workspace=SimpleNamespace(solver_scratch_folder=scratch),
        )
    )

    def fail_rmtree(_path: Path) -> None:
        raise OSError("locked")

    monkeypatch.setattr(export_module.shutil, "rmtree", fail_rmtree)

    with pytest.raises(ExportError, match="Could not remove solver scratch directory"):
        export_module.step_cleanup_scratch(ctx)


def test_step_cleanup_scratch_retries_after_releasing_handles(monkeypatch, tmp_path: Path) -> None:
    from hydromodpy.workflow.steps import export as export_module

    scratch = tmp_path / ".solver_scratch"
    scratch.mkdir()
    (scratch / "locked.txt").write_text("temporary", encoding="utf-8")
    ctx = SimpleNamespace(
        setup=SimpleNamespace(
            workspace=SimpleNamespace(solver_scratch_folder=scratch),
        )
    )
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

    export_module.step_cleanup_scratch(ctx)

    assert calls == 2
    assert releases == 2
    assert not scratch.exists()


@dataclass
class _LoadedForcings:
    recharge: object | None = None


def test_step_persist_forcings_closes_zarr_when_no_forcings() -> None:
    from hydromodpy.workflow.steps.prepare_solver.prepare import step_persist_forcings

    fake_zarr = _FakeZarr()
    ctx = SimpleNamespace(
        store=SimpleNamespace(open_zarr=lambda _sim_id: fake_zarr),
        sim_id="sim-123",
        loaded_data=_LoadedForcings(),
    )

    step_persist_forcings(ctx)

    assert fake_zarr.close_calls == 1
