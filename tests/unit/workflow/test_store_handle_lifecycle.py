from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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

    def register_simulation(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.registration


def test_step_register_simulation_closes_unused_bootstrap_zarr(monkeypatch) -> None:
    fake_zarr = _FakeZarr()
    registration = SimpleNamespace(name="run_0001", replaced_sim_id=None, zarr=fake_zarr)
    store = _FakeStore(registration)
    ctx = SimpleNamespace(
        parent_sim_id=None,
        store=store,
        cfg=SimpleNamespace(simulation=SimpleNamespace(on_collision="replace")),
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
