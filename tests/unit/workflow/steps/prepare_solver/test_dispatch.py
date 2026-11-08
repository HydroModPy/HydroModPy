"""Binding the pipeline to its run directory and the restart source."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.project.launch import plan_project
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.lineage import Lineage
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import claim_run_directory
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.solver.modflow_common.binaries import SolverEngine
from hydromodpy.workflow.steps.prepare_solver import dispatch as dispatch_module
from hydromodpy.workflow.steps.prepare_solver.dispatch import (
    bind_restart_source,
    bind_run_directory,
    initial_facts,
    planned_recipe,
)
from hydromodpy.workflow.steps.prepare_solver.facts import collect_effective_config_snapshot
from hydromodpy.workflow.steps.prepare_solver.restart import resolve_restart_source
from tests._helpers.run_stores import open_run_store
from tests._helpers.sealed_runs import make_project, seal_run
from tests.unit.project.launch._launch_fakes import write_project
from tests.unit.workflow.steps.prepare_solver._helpers import sealed_run

# --- test_a_planned_run_carries_its_recipe ---
# A run of a planned case seals its recipe, read from the plan.
#
# ``hmp report compare k_mid k_low k_high`` and ``--by site`` read the recipe of
# each run from ``manifest.run.recipe`` and the index: a worker of the plan
# must write it. The case id names the recipe for the life of the project, so
# the current plan answers; a run outside any plan has none.


def test_a_planned_case_reads_its_recipe_from_the_plan(tmp_path: Path) -> None:
    project = write_project(tmp_path)
    plan_project(project)

    assert planned_recipe(project, "alpha-k2e_5") == "k2e_5"
    assert planned_recipe(project, "beta-base") == "base"
    assert planned_recipe(project, "a_free_run") is None


def test_a_project_without_a_plan_gives_no_recipe(tmp_path: Path) -> None:
    assert planned_recipe(tmp_path, "alpha-base") is None


# --- test_run_environment_engine ---
# Registration must record the engine the run selected, not a default guess.


def _solver_section(runner: str) -> SimpleNamespace:
    """A ``[solver]`` section whose only settings table is the one of MODFLOW 6."""

    def options_of(name: str) -> SimpleNamespace:
        assert name == "modflow6"
        return SimpleNamespace(runtime=SimpleNamespace(mf6_runner=runner))

    return SimpleNamespace(options_of=options_of)


def _ctx(
    *,
    runner: str = "subprocess",
    captured: dict | None = None,
    built_model: object | None = None,
    solver: str = "modflow6",
) -> SimpleNamespace:
    sink = {} if captured is None else captured
    run = SimpleNamespace(id="flow_main", process_type="flow", solver=solver)
    return SimpleNamespace(
        cfg=SimpleNamespace(
            solver=_solver_section(runner),
            simulation=SimpleNamespace(rng_seed=7),
        ),
        setup=SimpleNamespace(
            workspace=SimpleNamespace(project_root=Path("/tmp/project"), bin_path="/tmp/bin")
        ),
        sim_id="sim-1",
        execution=SimpleNamespace(
            simulation_plan=SimpleNamespace(runs=(run,)),
            models_by_run_id={} if built_model is None else {"flow_main": built_model},
        ),
    )


def _store(captured: dict) -> SimpleNamespace:
    """A store that records the one row the registration writes."""
    return SimpleNamespace(
        write_run_environment=lambda sim_id, **kwargs: captured.update({"sim_id": sim_id, **kwargs})
    )


def _marnage_model() -> SimpleNamespace:
    """A built MODFLOW 6 model whose exposed-band coupling forces the library."""
    return SimpleNamespace(
        required_runner=lambda: "api",
        modflow_config=SimpleNamespace(runtime=SimpleNamespace(mf6_runner="subprocess")),
    )


def test_execution_mode_follows_the_declared_runner() -> None:
    assert dispatch_module._execution_mode(_ctx(runner="api"), "modflow6") == "api"
    assert dispatch_module._execution_mode(_ctx(runner="subprocess"), "modflow6") == "subprocess"


def test_only_modflow6_can_be_driven_through_the_library() -> None:
    ctx = _ctx(runner="api")

    assert dispatch_module._execution_mode(ctx, "modflow_nwt") == "subprocess"
    assert dispatch_module._execution_mode(ctx, "boussinesq") == "subprocess"
    assert dispatch_module._execution_mode(ctx, None) == "subprocess"


def test_api_registration_records_the_library_engine(monkeypatch) -> None:
    captured: dict = {}
    ctx = _ctx(runner="api", captured=captured)
    engine = SolverEngine(
        solver="modflow6",
        kind="library",
        execution_mode="api",
        path=Path("/tmp/bin/libmf6.so"),
        version="6.6.3",
    )
    monkeypatch.setattr(dispatch_module, "_resolve_solver_engine", lambda *_a, **_k: engine)

    dispatch_module._write_run_environment(ctx, "sim-1", "modflow6", store=_store(captured))

    assert captured["solver_engine"] == "library"
    assert captured["solver_execution_mode"] == "api"
    assert captured["solver_binary_path"] == Path("/tmp/bin/libmf6.so")
    assert captured["solver_version_text"] == "6.6.3"
    assert captured["rng_seed"] == 7


def test_the_built_model_overrides_the_declared_runner() -> None:
    """A lake with exposed-band runoff solves through libmf6 whatever the TOML says."""
    ctx = _ctx(runner="subprocess", built_model=_marnage_model())

    assert dispatch_module._execution_mode(ctx, "modflow6") == "api"


def test_a_plain_built_model_keeps_the_declared_runner() -> None:
    plain = SimpleNamespace(
        modflow_config=SimpleNamespace(runtime=SimpleNamespace(mf6_runner="subprocess"))
    )

    assert dispatch_module._execution_mode(_ctx(built_model=plain), "modflow6") == "subprocess"


def test_refresh_rewrites_the_engine_once_the_model_exists(monkeypatch) -> None:
    """The post-solve pass records the library, not the executable registration guessed."""
    captured: dict = {}
    ctx = _ctx(runner="subprocess", captured=captured, built_model=_marnage_model())
    library = SolverEngine(
        solver="modflow6",
        kind="library",
        execution_mode="api",
        path=Path("/tmp/bin/libmf6.so"),
        version="6.6.3",
    )
    monkeypatch.setattr(dispatch_module, "_resolve_solver_engine", lambda *_a, **_k: library)
    monkeypatch.setattr(
        dispatch_module, "primary_run_for_simulation", lambda _plan: ("flow", "modflow6")
    )

    dispatch_module.refresh_run_environment(ctx, store=_store(captured))

    assert captured["solver_execution_mode"] == "api"
    assert captured["solver_engine"] == "library"
    assert captured["solver_binary_path"] == Path("/tmp/bin/libmf6.so")


def test_refresh_is_a_no_op_before_the_run_is_registered() -> None:
    """No sim_id yet means no row to rewrite, whatever handle it was given."""
    captured: dict = {}
    ctx = _ctx()
    ctx.sim_id = None

    dispatch_module.refresh_run_environment(ctx, store=_store(captured))

    assert captured == {}


def test_a_solver_without_an_engine_still_records_its_mode(monkeypatch) -> None:
    """Boussinesq has no binary; the environment row must still be written."""
    captured: dict = {}
    ctx = _ctx(captured=captured)
    monkeypatch.setattr(dispatch_module, "_resolve_solver_engine", lambda *_a, **_k: None)

    dispatch_module._write_run_environment(ctx, "sim-2", "boussinesq", store=_store(captured))

    assert captured["solver_name"] == "boussinesq"
    assert captured["solver_engine"] is None
    assert captured["solver_binary_path"] is None
    assert captured["solver_execution_mode"] == "subprocess"


# --- test_store_handle_lifecycle ---
# The run directory is bound once, by the step that opens the run.
#
# ``bind_run_directory`` reads the identity of the attempt off the outcome of
# the directory it is handed, or claims the directory of the case when it is
# handed none; the facts of the attempt are built from the context, written by
# the store that opens on them, and no handle survives the step.


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "demo_project"
    root.mkdir()
    (root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return root


def _bind_ctx(project: Path, *, reserved_sim_id: str | None = None) -> SimpleNamespace:
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
            model_dump=lambda mode="json", exclude_defaults=False: {"flow": {"k": 1e-5}},
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
    ctx = _bind_ctx(project)

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
    ctx = _bind_ctx(project, reserved_sim_id=reserved)
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
    ctx = _bind_ctx(project)

    bind_run_directory(
        ctx, run_dir=claim.run_dir, lineage=None, calibrated_by=None, run_overrides=None
    )

    assert ctx.sim_id == claim.sim_id
    assert ctx.attempt == claim.attempt
    assert read_outcome(claim.run_dir).attempt == 1


def test_the_initial_facts_name_the_run_its_solver_and_its_hash(tmp_path: Path) -> None:
    project = _project(tmp_path)
    ctx = _bind_ctx(project)
    bind_run_directory(
        ctx, run_dir=None, lineage=None, calibrated_by=None, run_overrides={"K": 1e-5}
    )

    facts = initial_facts(ctx)

    assert facts.sim_id == ctx.sim_id
    assert facts.name == "requested_name"
    assert facts.case_id == "requested_name"
    assert facts.project == "demo_project"
    assert facts.solver == "boussinesq"
    assert facts.solver_category == "integrated"
    assert facts.config_hash
    assert facts.config_source == "requested_name.toml"
    assert facts.lineage.kind == "rerun"


# --- test_a_restart_reference_is_resolved_to_a_run ---
# ``[flow] restart_from`` names a run; the step resolves it to a store and links by id.
#
# A run name, with or without its version, a ``sim_id`` or a path: each resolves
# to the field store the solver reads, and to the ``sim_id`` of the sealed run
# that holds it. The step binds the resolved path on the flow configuration,
# so the frozen ``config.toml`` writes it relative to the project, and the
# lineage of the run names its source by id.


def test_the_step_binds_the_resolved_path_and_links_the_lineage_by_id(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    sid = sealed_run(project, "spinup")
    store = open_run_store(project, "production", n_cells=4)
    flow = SimpleNamespace(restart_from="spinup")
    ctx = SimpleNamespace(cfg=SimpleNamespace(flow=flow), lineage=None)

    bind_restart_source(ctx, store=store)

    assert flow.restart_from == str(project / "runs" / "spinup" / FIELDS_STORE_NAME)
    assert store.facts.lineage.parent_sim_id == sid
    assert store.facts.lineage.parent_hint == "runs/spinup"
    assert ctx.lineage == store.facts.lineage
    store.close()


def test_without_a_reference_the_step_touches_nothing(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    store = open_run_store(project, "production", n_cells=4)
    flow = SimpleNamespace(restart_from=None)
    ctx = SimpleNamespace(cfg=SimpleNamespace(flow=flow), lineage=None)

    bind_restart_source(ctx, store=store)

    assert flow.restart_from is None
    assert store.facts.lineage.parent_sim_id is None
    store.close()


def test_the_step_returns_the_sim_id_the_frozen_config_writes(tmp_path: Path) -> None:
    from hydromodpy.model.flow_config import RestartReference

    project = make_project(tmp_path / "demo")
    sid = sealed_run(project, "spinup")
    store = open_run_store(project, "production", n_cells=4)
    flow = SimpleNamespace(restart_from=RestartReference(sim_id=sid))
    ctx = SimpleNamespace(cfg=SimpleNamespace(flow=flow), lineage=None)

    returned = bind_restart_source(ctx, store=store)

    assert returned == sid
    assert flow.restart_from == str(project / "runs" / "spinup" / FIELDS_STORE_NAME)
    store.close()
