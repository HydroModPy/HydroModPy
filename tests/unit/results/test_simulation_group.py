from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.layout import catalog_path_for, runs_dir_for
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.run import Run
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.tables import global_parameters
from hydromodpy.results.storage.run_facts import RunFacts
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_builders import populate, runs, score

__all__ = ["runs"]


def _cfg(*, persisted: bool) -> SimpleNamespace:
    """The configuration double of a project: a domain, and whether runs are kept."""
    persistence = SimpleNamespace(save_catalog=persisted)
    return SimpleNamespace(
        domain=object(),
        site=None,
        simulation=SimpleNamespace(
            name=None, if_exists="version", results=SimpleNamespace(persistence=persistence)
        ),
        model_dump=lambda **_kwargs: {},
    )


class TestSimulationGroup:
    def test_count_and_len(self, runs):
        sids = [runs.open().sim_id for _ in range(3)]
        group = RunSet(sids, runs.catalog())
        assert group.count == 3
        assert len(group) == 3

    def test_project_run_handles_survive_later_runs(self, monkeypatch, tmp_path):
        """A run handle keeps reading its run after the project ran another one."""
        from hydromodpy.project.runner import ProjectRunner
        from hydromodpy.workflow.state import PipelineState

        project_root = tmp_path / "project"

        class _Step:
            name = "setup_process"

        class _Pipeline:
            counter = 0

            def __init__(self, steps, *, workspace, run_dir=None):
                self.steps = steps
                self.workspace = workspace

            def run(self, state, *, resume_from=None, parallel=False, **_kwargs):
                _Pipeline.counter += 1
                ctx = state.get("ctx")
                outcome = read_outcome(ctx.run_dir)
                facts = RunFacts(
                    sim_id=outcome.sim_id,
                    name=ctx.run_dir.name,
                    case_id=outcome.case_id,
                    project="project",
                    attempt=outcome.attempt,
                    attempt_id=outcome.attempt_id,
                    created_at=outcome.started_at,
                    started_at=outcome.started_at,
                    solver="modflow6",
                    n_cells=1,
                    n_layers=1,
                )
                store = RunStore.open(ctx.run_dir, facts=facts, workspace=project_root)
                store.write_parameters(
                    facts.sim_id,
                    [{"param_name": "thickness", "value": float(_Pipeline.counter), "unit": "m"}],
                )
                seal_completed(store)
                ctx.sim_id = facts.sim_id
                return PipelineState(
                    run_id=state.run_id,
                    step_index=0,
                    step_name="display",
                    data={**state.data, "ctx": ctx},
                )

        monkeypatch.setattr("hydromodpy.workflow.steps.sequence.standard_steps", lambda: (_Step(),))
        monkeypatch.setattr(
            "hydromodpy.workflow.steps.planning.step_build_plan", lambda *a, **k: None
        )
        monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _Pipeline)
        # The double has no document to freeze and no inputs to resolve: the claim
        # steps of the runner are the subject of its own tests.
        monkeypatch.setattr(
            ProjectRunner,
            "_claim_documents",
            lambda self, handle, request, cfg_run, workspace_path, *, name, skip_identical, window_source=None: (
                "k",
                None,
            ),
        )

        workspace = SimpleNamespace(
            root=tmp_path / "workspace",
            project_root=project_root,
            catalog_path=catalog_path_for(project_root),
            runs_dir=runs_dir_for(project_root),
            solver_scratch_folder=None,
        )
        # The domain of a built model phase names the configuration section it
        # was built from, so a run defined by that same configuration keeps it.
        declared_cfg = _cfg(persisted=True)
        ctx = SimpleNamespace(
            cfg=declared_cfg,
            setup=SimpleNamespace(
                workspace=workspace,
                geographic=object(),
                domain=object(),
                domain_config_source=declared_cfg.domain,
                flow=None,
                run_id=None,
                slot_request=None,
            ),
            raw_toml={},
            sim_id=None,
            run_dir=None,
        )
        project = SimpleNamespace(
            _ctx=ctx,
            _cfg=declared_cfg,
            _config_path=tmp_path / "hydromodpy.toml",
            # The double stands for a project whose model phase is built, which
            # is what the geographic / domain objects on its ctx declare.
            _ensure_model_built=lambda: None,
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
            _run_history=[],
        )

        runner = ProjectRunner(project)
        first = runner.run(name="first")
        second = runner.run(name="second")

        # Each handle reads its own run directory, never an index handle of the project.
        assert second._catalog.run_dir == project_root / "runs" / "second"
        assert first._catalog.run_dir == project_root / "runs" / "first"
        assert global_parameters(first)["thickness"] == pytest.approx(1.0)
        assert global_parameters(second)["thickness"] == pytest.approx(2.0)
        assert first.dir.name == "first"
        assert second.dir.name == "second"

    def testpin_parent_sim_id_overrides_ctx_during_pipeline_run(self, monkeypatch, tmp_path):
        from hydromodpy.project.runner import ProjectRunner, pin_parent_sim_id
        from hydromodpy.workflow.state import PipelineState

        class _Step:
            name = "setup_process"

        observed: list[str | None] = []

        class _Pipeline:
            def __init__(self, steps, *, workspace, run_dir=None):
                self.steps = steps
                self.workspace = workspace

            def run(self, state, *, resume_from=None, parallel=False, **_kwargs):
                ctx = state.get("ctx")
                observed.append(ctx.parent_sim_id)
                ctx.sim_id = None
                return PipelineState(
                    run_id=state.run_id,
                    step_index=0,
                    step_name="display",
                    data={**state.data, "ctx": ctx},
                )

        monkeypatch.setattr("hydromodpy.workflow.steps.sequence.standard_steps", lambda: (_Step(),))
        monkeypatch.setattr(
            "hydromodpy.workflow.steps.planning.step_build_plan", lambda *a, **k: None
        )
        monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _Pipeline)
        monkeypatch.setattr("hydromodpy.project.phases.open_catalog", lambda *_a, **_k: None)

        workspace = SimpleNamespace(
            root=tmp_path / "workspace",
            project_root=tmp_path / "project",
        )
        declared_cfg = _cfg(persisted=False)
        ctx = SimpleNamespace(
            cfg=declared_cfg,
            setup=SimpleNamespace(
                workspace=workspace,
                geographic=object(),
                domain=object(),
                domain_config_source=declared_cfg.domain,
                flow=None,
                run_id=None,
                slot_request=None,
            ),
            raw_toml={},
            store=None,
            sim_id=None,
            parent_sim_id="existing-parent",
        )
        project = SimpleNamespace(
            _ctx=ctx,
            _cfg=declared_cfg,
            _config_path=tmp_path / "hydromodpy.toml",
            # The double stands for a project whose model phase is built, which
            # is what the geographic / domain objects on its ctx declare.
            _ensure_model_built=lambda: None,
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
            _run_history=[],
        )

        with pin_parent_sim_id(ctx, "parent-run"):
            result = ProjectRunner(project).run(name="derived")

        assert result is None
        assert observed == ["parent-run"]
        assert ctx.parent_sim_id == "existing-parent"

    def testpin_parent_sim_id_restores_on_exception(self):
        from hydromodpy.project.runner import pin_parent_sim_id

        ctx = SimpleNamespace(parent_sim_id="initial")

        with pytest.raises(RuntimeError):
            with pin_parent_sim_id(ctx, "transient"):
                assert ctx.parent_sim_id == "transient"
                raise RuntimeError("boom")

        assert ctx.parent_sim_id == "initial"

    def testpin_parent_sim_id_none_is_noop(self):
        from hydromodpy.project.runner import pin_parent_sim_id

        ctx = SimpleNamespace(parent_sim_id="initial")

        with pin_parent_sim_id(ctx, None):
            assert ctx.parent_sim_id == "initial"

        assert ctx.parent_sim_id == "initial"

    def test_iter(self, runs):
        sids = [runs.open().sim_id for _ in range(2)]
        sims = list(RunSet(sids, runs.catalog()))
        assert len(sims) == 2
        assert all(isinstance(s, Run) for s in sims)

    def test_getitem(self, runs):
        sids = [runs.open().sim_id for _ in range(3)]
        sim = RunSet(sids, runs.catalog())[1]
        assert isinstance(sim, Run)
        assert sim.sim_id == sids[1]

    def test_best_worst_follow_the_score_under_the_rule(self, runs):
        low, high = runs.open(), runs.open()
        score(low, 0.6)
        score(high, 0.9)
        group = RunSet([low.sim_id, high.sim_id], runs.catalog())
        assert group.best("nse").sim_id == high.sim_id
        assert group.worst("nse").sim_id == low.sim_id

    def test_sort_by(self, runs):
        stores = [runs.open() for _ in range(3)]
        for store, value in zip(stores, (0.5, 0.9, 0.7), strict=True):
            score(store, value)
        group = RunSet([store.sim_id for store in stores], runs.catalog())
        ordered = group.sort_by("nse", ascending=False)
        assert ordered.sim_ids == [stores[1].sim_id, stores[2].sim_id, stores[0].sim_id]

    def test_compare(self, runs):
        stores = [runs.open() for _ in range(2)]
        for store, value in zip(stores, (0.6, 0.9), strict=True):
            score(store, value)
        df = RunSet([store.sim_id for store in stores], runs.catalog()).compare("nse")
        assert len(df) == 2

    def test_to_dataframe(self, runs):
        first, second = runs.open(), runs.open()
        populate(first)
        populate(second)
        df = RunSet([first.sim_id, second.sim_id], runs.catalog()).to_dataframe()
        assert len(df) == 2
        assert "sim_id" in df.columns

    def test_empty_group(self, runs):
        runs.open()
        group = RunSet([], runs.catalog())
        assert group.count == 0
        assert group.parameters.empty
        assert group.metrics.empty
        assert group.to_dataframe().empty
