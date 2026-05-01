from __future__ import annotations

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
        parent_sim_id=None,
        store=store,
        cfg=SimpleNamespace(simulation=SimpleNamespace(on_collision="replace")),
        setup=SimpleNamespace(time_grid=None, workspace=SimpleNamespace(project_root=None)),
    )
    plan = SimpleNamespace(runs=[SimpleNamespace(solver="boussinesq")])

    monkeypatch.setattr(prepare_solver_module, "collect_registration_kwargs", lambda ctx: {})

    final_name = prepare_solver_module.step_register_simulation(
        ctx,
        "sim-123",
        plan=plan,
        project_name="demo_project",
        name="requested_name",
    )

    assert final_name == "run_0001"
    assert fake_zarr.close_calls == 1


def test_step_open_store_closes_unused_bootstrap_zarr(monkeypatch, tmp_path: Path) -> None:
    fake_zarr = _FakeZarr()
    registration = SimpleNamespace(name="run_0002", replaced_sim_id=None, zarr=fake_zarr)

    class FakeCatalog:
        def __init__(self, workspace_root, *, persistence=None) -> None:
            self.workspace_root = workspace_root
            self.persistence = persistence

        def register_simulation(self, *args, **kwargs):
            return registration

    ctx = SimpleNamespace(
        parent_sim_id=None,
        store=None,
        sim_id=None,
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(
                results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=True)),
                on_collision="replace",
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
            simulation_plan=SimpleNamespace(runs=[SimpleNamespace(solver="boussinesq")])
        ),
    )

    import hydromodpy.results.catalog as catalog_module

    monkeypatch.setattr(catalog_module, "SimulationCatalog", FakeCatalog)
    monkeypatch.setattr(prepare_solver_module, "collect_registration_kwargs", lambda ctx: {})
    monkeypatch.setattr(prepare_solver_module, "_register_tracked_input_files", lambda ctx: None)
    monkeypatch.setattr(prepare_solver_module, "step_persist_params", lambda *args, **kwargs: None)
    monkeypatch.setattr(prepare_solver_module, "step_persist_mesh", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        prepare_solver_module, "step_persist_geographic", lambda *args, **kwargs: None
    )

    prepare_solver_module.step_open_store(ctx)

    assert ctx.store is not None
    assert ctx.sim_id is not None
    assert ctx.setup.run_id == "run_0002"
    assert fake_zarr.close_calls == 1


class _Dumpable:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def model_dump(self, **_kwargs) -> dict:
        return dict(self.payload)


def test_effective_config_snapshot_uses_runtime_domain_and_results() -> None:
    declared = {
        "workflow": "simulation",
        "domain": {"depth_model": {"type": "constant_thickness", "thickness": 10.0}},
        "simulation": {"results": {"keep_solver_files": False}},
    }
    effective_domain = {
        "depth_model": {"type": "constant_thickness", "thickness": 25.0},
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

    with pytest.raises(RuntimeError, match="Could not remove solver scratch directory"):
        export_module.step_cleanup_scratch(ctx)
