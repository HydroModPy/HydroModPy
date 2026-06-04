from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.run import Run
from hydromodpy.results.simulation_group import SimulationGroup

from ._test_simulation_api_builders import _populate, _register, catalog

__all__ = ["catalog"]


class TestSimulationGroup:
    def test_count_and_len(self, catalog):
        sids = [_register(catalog) for _ in range(3)]
        group = SimulationGroup(sids, catalog)
        assert group.count == 3
        assert len(group) == 3

    def test_project_sweep_returns_group_bound_to_catalog(self, monkeypatch, catalog):
        from hydromodpy.project.runner import ProjectRunner

        sids = [_register(catalog) for _ in range(2)]

        def fake_run_sweep(project, *, parameters, strategy, name_template, parallel=1):
            assert parameters == {"K": [1.0, 2.0]}
            assert strategy == "enumerate"
            assert name_template == "{param}_{value:.4g}"
            assert parallel == 1
            return sids

        monkeypatch.setattr("hydromodpy.workflow.parallel.run_sweep", fake_run_sweep)
        project = SimpleNamespace(_store=catalog, _ensure_model_built=lambda: None)

        group = ProjectRunner(project).sweep({"K": [1.0, 2.0]})

        assert isinstance(group, SimulationGroup)
        assert group.sim_ids == sids
        assert group[0].sim_id == sids[0]

    def test_project_run_handles_survive_later_runs(self, monkeypatch, tmp_path):
        from hydromodpy.project.runner import ProjectRunner
        from hydromodpy.workflow.internals.state import PipelineState

        class _Step:
            name = "setup_process"

        class _Pipeline:
            counter = 0

            def __init__(self, steps, *, workspace):
                self.steps = steps
                self.workspace = workspace

            def run(self, state, *, resume_from=None, parallel=False):
                _Pipeline.counter += 1
                ctx = state.get("ctx")
                sim_id = str(uuid.uuid4())
                with SimulationCatalog(ctx.setup.workspace.project_root) as run_catalog:
                    reg = run_catalog.register_simulation(
                        sim_id,
                        project="project",
                        solver="modflow6",
                        name=ctx.setup.run_id,
                        n_cells=1,
                        n_layers=1,
                    )
                    if reg.zarr is not None:
                        reg.zarr.close()
                    run_catalog.write_parameters(
                        sim_id,
                        [
                            {
                                "param_name": "thickness",
                                "value": float(_Pipeline.counter),
                                "unit": "m",
                            }
                        ],
                    )
                    run_catalog.finalize(sim_id, "completed")
                ctx.sim_id = sim_id
                ctx.store = None
                return PipelineState(
                    run_id=state.run_id,
                    step_index=0,
                    step_name="display",
                    data={**state.data, "ctx": ctx},
                )

        monkeypatch.setattr("hydromodpy.workflow.orchestrator.standard_steps", lambda: (_Step(),))
        monkeypatch.setattr(
            "hydromodpy.workflow.steps.planning.step_build_plan", lambda *a, **k: None
        )
        monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _Pipeline)

        project_root = tmp_path / "project"
        workspace = SimpleNamespace(
            root=tmp_path / "workspace",
            project_root=project_root,
            catalog_path=project_root / "catalog.duckdb",
            simulations_dir=project_root / "simulations",
        )
        ctx = SimpleNamespace(
            setup=SimpleNamespace(
                workspace=workspace,
                geographic=object(),
                domain=object(),
                run_id=None,
                flow_runtime_overrides=None,
            ),
            raw_toml={},
            store=None,
            sim_id=None,
        )
        project = SimpleNamespace(
            _ctx=ctx,
            _cfg=SimpleNamespace(),
            _config_path=tmp_path / "hydromodpy.toml",
            _spatial_support_registry=None,
            _requested_support_ids=(),
            _requested_domain_supports={},
            _store=None,
            _run_counter=0,
            _solver="modflow6",
            _no_display=True,
            _headless=True,
            _project_name="project",
            _active_runs={},
            _last_wall_seconds={},
            _run_history=[],
        )

        runner = ProjectRunner(project)
        first = runner.run(name="first")
        first_catalog = first._catalog
        second = runner.run(name="second")

        assert first_catalog is not project._store
        assert first._catalog is project._store
        assert second._catalog is project._store
        assert first.params["thickness"] == pytest.approx(1.0)
        assert second.params["thickness"] == pytest.approx(2.0)

    def test_pin_parent_sim_id_overrides_ctx_during_pipeline_run(self, monkeypatch, tmp_path):
        from hydromodpy.project.runner import ProjectRunner, _pin_parent_sim_id
        from hydromodpy.workflow.internals.state import PipelineState

        class _Step:
            name = "setup_process"

        observed: list[str | None] = []

        class _Pipeline:
            def __init__(self, steps, *, workspace):
                self.steps = steps
                self.workspace = workspace

            def run(self, state, *, resume_from=None, parallel=False):
                ctx = state.get("ctx")
                observed.append(ctx.parent_sim_id)
                ctx.sim_id = None
                return PipelineState(
                    run_id=state.run_id,
                    step_index=0,
                    step_name="display",
                    data={**state.data, "ctx": ctx},
                )

        monkeypatch.setattr("hydromodpy.workflow.orchestrator.standard_steps", lambda: (_Step(),))
        monkeypatch.setattr(
            "hydromodpy.workflow.steps.planning.step_build_plan", lambda *a, **k: None
        )
        monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _Pipeline)
        monkeypatch.setattr("hydromodpy.project.phases.open_catalog", lambda *_a, **_k: None)

        workspace = SimpleNamespace(
            root=tmp_path / "workspace",
            project_root=tmp_path / "project",
        )
        ctx = SimpleNamespace(
            setup=SimpleNamespace(
                workspace=workspace,
                geographic=object(),
                domain=object(),
                run_id=None,
                flow_runtime_overrides=None,
            ),
            raw_toml={},
            store=None,
            sim_id=None,
            parent_sim_id="existing-parent",
        )
        project = SimpleNamespace(
            _ctx=ctx,
            _cfg=SimpleNamespace(),
            _config_path=tmp_path / "hydromodpy.toml",
            _spatial_support_registry=None,
            _requested_support_ids=(),
            _requested_domain_supports={},
            _store=None,
            _run_counter=0,
            _solver="modflow6",
            _no_display=True,
            _headless=True,
            _project_name="project",
            _active_runs={},
            _last_wall_seconds={},
            _run_history=[],
        )

        with _pin_parent_sim_id(ctx, "parent-run"):
            result = ProjectRunner(project).run(name="derived")

        assert result is None
        assert observed == ["parent-run"]
        assert ctx.parent_sim_id == "existing-parent"

    def test_pin_parent_sim_id_restores_on_exception(self):
        from hydromodpy.project.runner import _pin_parent_sim_id

        ctx = SimpleNamespace(parent_sim_id="initial")

        with pytest.raises(RuntimeError):
            with _pin_parent_sim_id(ctx, "transient"):
                assert ctx.parent_sim_id == "transient"
                raise RuntimeError("boom")

        assert ctx.parent_sim_id == "initial"

    def test_pin_parent_sim_id_none_is_noop(self):
        from hydromodpy.project.runner import _pin_parent_sim_id

        ctx = SimpleNamespace(parent_sim_id="initial")

        with _pin_parent_sim_id(ctx, None):
            assert ctx.parent_sim_id == "initial"

        assert ctx.parent_sim_id == "initial"

    def test_iter(self, catalog):
        sids = [_register(catalog) for _ in range(2)]
        group = SimulationGroup(sids, catalog)
        sims = list(group)
        assert len(sims) == 2
        assert all(isinstance(s, Run) for s in sims)

    def test_getitem(self, catalog):
        sids = [_register(catalog) for _ in range(3)]
        group = SimulationGroup(sids, catalog)
        sim = group[1]
        assert isinstance(sim, Run)
        assert sim.sim_id == sids[1]

    def test_best_worst(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        catalog.write_metric(s1, "P01", "nse", 0.6)
        catalog.write_metric(s2, "P01", "nse", 0.9)
        catalog.finalize(s1, "completed")
        catalog.finalize(s2, "completed")

        group = SimulationGroup([s1, s2], catalog)
        assert group.best("nse").sim_id == s2
        assert group.worst("nse").sim_id == s1

    def test_sort_by(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        s3 = _register(catalog)
        catalog.write_metric(s1, "P01", "nse", 0.5)
        catalog.write_metric(s2, "P01", "nse", 0.9)
        catalog.write_metric(s3, "P01", "nse", 0.7)

        group = SimulationGroup([s1, s2, s3], catalog)
        sorted_g = group.sort_by("nse", ascending=False)
        assert sorted_g.sim_ids[0] == s2
        assert sorted_g.sim_ids[-1] == s1

    def test_compare(self, catalog):
        s1 = _register(catalog)
        s2 = _register(catalog)
        catalog.write_metric(s1, "P01", "nse", 0.6)
        catalog.write_metric(s2, "P01", "nse", 0.9)

        group = SimulationGroup([s1, s2], catalog)
        df = group.compare("nse")
        assert len(df) == 2

    def test_to_dataframe(self, catalog):
        s1 = _register(catalog)
        _populate(catalog, s1)
        s2 = _register(catalog)
        _populate(catalog, s2)

        group = SimulationGroup([s1, s2], catalog)
        df = group.to_dataframe()
        assert len(df) == 2
        assert "sim_id" in df.columns

    def test_empty_group(self, catalog):
        group = SimulationGroup([], catalog)
        assert group.count == 0
        assert group.parameters.empty
        assert group.metrics.empty
        assert group.to_dataframe().empty
