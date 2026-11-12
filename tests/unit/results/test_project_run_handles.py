"""A project run returns a handle that reads its own run directory.

The runner is played with a pipeline double that seals one run per call, so the
handles of two successive runs can be compared.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.core.state.layout import catalog_path_for, runs_dir_for
from hydromodpy.project.runner import ProjectRunner, pin_parent_sim_id
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.run.tables import global_parameters
from hydromodpy.results.storage.run_facts import RunFacts
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.workflow.state import PipelineState


class SetupStep:
    name = "setup_process"


def config_double(*, persisted: bool) -> SimpleNamespace:
    """The configuration of a project: a domain, and whether runs are kept."""
    persistence = SimpleNamespace(save_catalog=persisted)
    return SimpleNamespace(
        domain=object(),
        site=None,
        simulation=SimpleNamespace(
            name=None, if_exists="version", results=SimpleNamespace(persistence=persistence)
        ),
        model_dump=lambda **_kwargs: {},
    )


def project_double(tmp_path, workspace, *, persisted: bool, **ctx_fields):
    """A project whose model phase is built, with the context the runner reads."""
    declared_cfg = config_double(persisted=persisted)
    # The domain of a built model phase names the configuration section it was
    # built from, so a run defined by that same configuration keeps it.
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
        **ctx_fields,
    )
    project = SimpleNamespace(
        _ctx=ctx,
        _cfg=declared_cfg,
        _config_path=tmp_path / "hydromodpy.toml",
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
    return ctx, project


def play_with(monkeypatch, pipeline_class) -> None:
    monkeypatch.setattr("hydromodpy.workflow.steps.sequence.standard_steps", lambda: (SetupStep(),))
    monkeypatch.setattr("hydromodpy.workflow.steps.planning.step_build_plan", lambda *a, **k: None)
    monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", pipeline_class)


def finished_state(state, ctx) -> PipelineState:
    return PipelineState(
        run_id=state.run_id,
        step_index=0,
        step_name="display",
        data={**state.data, "ctx": ctx},
    )


def test_handles_survive_later_runs(monkeypatch, tmp_path):
    project_root = tmp_path / "project"

    class SealingPipeline:
        counter = 0

        def __init__(self, steps, *, workspace, run_dir=None):
            self.steps = steps
            self.workspace = workspace

        def run(self, state, *, resume_from=None, parallel=False, **_kwargs):
            SealingPipeline.counter += 1
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
            thickness = [
                {"param_name": "thickness", "value": float(SealingPipeline.counter), "unit": "m"}
            ]
            store.write_parameters(facts.sim_id, thickness)
            seal_completed(store)
            ctx.sim_id = facts.sim_id
            return finished_state(state, ctx)

    play_with(monkeypatch, SealingPipeline)
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
    _, project = project_double(tmp_path, workspace, persisted=True, run_dir=None)

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


def test_pinned_parent_overrides_the_context_during_a_run(monkeypatch, tmp_path):
    observed: list[str | None] = []

    class ObservingPipeline:
        def __init__(self, steps, *, workspace, run_dir=None):
            self.steps = steps
            self.workspace = workspace

        def run(self, state, *, resume_from=None, parallel=False, **_kwargs):
            ctx = state.get("ctx")
            observed.append(ctx.parent_sim_id)
            ctx.sim_id = None
            return finished_state(state, ctx)

    play_with(monkeypatch, ObservingPipeline)
    monkeypatch.setattr("hydromodpy.project.phases.open_catalog", lambda *_a, **_k: None)
    workspace = SimpleNamespace(root=tmp_path / "workspace", project_root=tmp_path / "project")
    ctx, project = project_double(
        tmp_path, workspace, persisted=False, store=None, parent_sim_id="existing-parent"
    )

    with pin_parent_sim_id(ctx, "parent-run"):
        result = ProjectRunner(project).run(name="derived")

    assert result is None
    assert observed == ["parent-run"]
    assert ctx.parent_sim_id == "existing-parent"


def test_pinning_no_parent_changes_nothing():
    ctx = SimpleNamespace(parent_sim_id="initial")

    with pin_parent_sim_id(ctx, None):
        assert ctx.parent_sim_id == "initial"

    assert ctx.parent_sim_id == "initial"
