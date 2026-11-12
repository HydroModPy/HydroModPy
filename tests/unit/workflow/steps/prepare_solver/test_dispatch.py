"""Opening a run: its recipe, its solver environment, its directory, its restart source and its binaries."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.model.flow_config import RestartReference
from hydromodpy.project.launch.local import plan_project
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import claim_run_directory
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.schema.lineage import Lineage
from hydromodpy.solver.base import planner
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.modflow_common import binaries
from hydromodpy.solver.modflow_common.binaries import SolverEngine, exe_filename
from hydromodpy.workflow.steps.prepare_solver import dispatch as dispatch_module
from hydromodpy.workflow.steps.prepare_solver.dispatch import (
    bind_restart_source,
    bind_run_directory,
    initial_facts,
    planned_recipe,
    solver_binaries,
)
from tests._helpers.run_stores import open_run_store
from tests._helpers.sealed_runs import make_project
from tests.unit.project.launch._launch_fakes import write_project
from tests.unit.workflow.steps.prepare_solver._helpers import sealed_run

# A run of a planned case seals its recipe, read from the plan: ``hmp diff`` reads it from the
# manifest. A run outside any plan has none.


def test_recipe_of_a_planned_case(tmp_path: Path) -> None:
    project = write_project(tmp_path)
    plan_project(project)

    assert planned_recipe(project, "alpha-k2e_5") == "k2e_5"
    assert planned_recipe(project, "beta-base") == "base"
    assert planned_recipe(project, "a_free_run") is None


def test_no_plan_no_recipe(tmp_path: Path) -> None:
    assert planned_recipe(tmp_path, "alpha-base") is None


# Registration records the engine the run selected, not a default guess.


def _solver_section(runner: str) -> SimpleNamespace:
    def options_of(name: str) -> SimpleNamespace | None:
        if name != "modflow6":
            return None
        return SimpleNamespace(runner=runner)

    return SimpleNamespace(options_of=options_of)


def _ctx(
    *,
    runner: str = "subprocess",
    built_model: object | None = None,
    solver: str = "modflow6",
) -> SimpleNamespace:
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
            solver_runs={}
            if built_model is None
            else {
                "flow_main": SolverRun(
                    slot=RunSlot(Path("/tmp/scratch"), "flow_main"), solver_model=built_model
                )
            },
        ),
    )


def _store(captured: dict) -> SimpleNamespace:
    return SimpleNamespace(
        write_run_environment=lambda sim_id, **kwargs: captured.update({"sim_id": sim_id, **kwargs})
    )


def _plain_model() -> SimpleNamespace:
    return SimpleNamespace(
        modflow_config=SimpleNamespace(runtime=SimpleNamespace(mf6_runner="subprocess"))
    )


def _marnage_model() -> SimpleNamespace:
    # A built MODFLOW 6 model whose exposed-band coupling forces the library.
    return SimpleNamespace(
        required_runner=lambda: "api",
        modflow_config=SimpleNamespace(runtime=SimpleNamespace(mf6_runner="subprocess")),
    )


EXECUTION_MODES = [
    pytest.param({"runner": "api"}, "modflow6", "api", id="declared api"),
    pytest.param({"runner": "subprocess"}, "modflow6", "subprocess", id="declared subprocess"),
    pytest.param({"runner": "api"}, "modflow_nwt", "subprocess", id="nwt has no library"),
    pytest.param({"runner": "api"}, "boussinesq", "subprocess", id="boussinesq has no library"),
    pytest.param({"runner": "api"}, None, "subprocess", id="no solver"),
    pytest.param({"built_model": _marnage_model()}, "modflow6", "api", id="built model needs api"),
    pytest.param({"built_model": _plain_model()}, "modflow6", "subprocess", id="plain built model"),
]


@pytest.mark.parametrize(("kwargs", "solver", "mode"), EXECUTION_MODES)
def test_execution_mode(kwargs, solver, mode) -> None:
    # A lake with exposed-band runoff solves through libmf6 whatever the TOML says.
    assert dispatch_module._execution_mode(_ctx(**kwargs), solver) == mode


def test_api_registration_records_library(monkeypatch) -> None:
    captured: dict = {}
    ctx = _ctx(runner="api")
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


def test_refresh_rewrites_engine(monkeypatch) -> None:
    # The post-solve pass records the library, not the executable registration guessed.
    captured: dict = {}
    ctx = _ctx(runner="subprocess", built_model=_marnage_model())
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


def test_refresh_before_registration() -> None:
    # No sim_id yet means no row to rewrite.
    captured: dict = {}
    ctx = _ctx()
    ctx.sim_id = None

    dispatch_module.refresh_run_environment(ctx, store=_store(captured))

    assert captured == {}


def test_solver_without_engine_records_mode(monkeypatch) -> None:
    # Boussinesq has no binary; the environment row must still be written.
    captured: dict = {}
    ctx = _ctx()
    monkeypatch.setattr(dispatch_module, "_resolve_solver_engine", lambda *_a, **_k: None)

    dispatch_module._write_run_environment(ctx, "sim-2", "boussinesq", store=_store(captured))

    assert captured["solver_name"] == "boussinesq"
    assert captured["solver_engine"] is None
    assert captured["solver_binary_path"] is None
    assert captured["solver_execution_mode"] == "subprocess"


# ``bind_run_directory`` reads the identity of the attempt off the outcome of the directory it is
# handed, or claims the directory of the case when it is handed none.


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "demo_project"
    root.mkdir()
    (root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return root


def _bind_ctx(project: Path, *, reserved_sim_id: str | None = None) -> SimpleNamespace:
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


def test_claims_the_case_without_a_directory(tmp_path: Path) -> None:
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


def test_reserved_id_taken_once(tmp_path: Path) -> None:
    # A promotion reserves the directory and the id. The reservation is consumed here: a context
    # replayed for another run must mint a fresh id rather than open twice under the same one.
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


def test_prior_claim_is_read_not_repeated(tmp_path: Path) -> None:
    project = _project(tmp_path)
    claim = claim_run_directory(project, "requested_name", case_id="requested_name", project="demo")
    ctx = _bind_ctx(project)

    bind_run_directory(
        ctx, run_dir=claim.run_dir, lineage=None, calibrated_by=None, run_overrides=None
    )

    assert ctx.sim_id == claim.sim_id
    assert ctx.attempt == claim.attempt
    assert read_outcome(claim.run_dir).attempt == 1


def test_initial_facts(tmp_path: Path) -> None:
    project = _project(tmp_path)
    ctx = _bind_ctx(project)
    bind_run_directory(
        ctx, run_dir=None, lineage=None, calibrated_by=None, run_overrides={"K": 1e-5}
    )

    facts = initial_facts(ctx, solution_key="k" * 64)

    assert facts.sim_id == ctx.sim_id
    assert facts.name == "requested_name"
    assert facts.case_id == "requested_name"
    assert facts.project == "demo_project"
    assert facts.solver == "boussinesq"
    assert facts.solver_category == "integrated"
    assert facts.solution_key == "k" * 64
    assert facts.config_source == "requested_name.toml"
    assert facts.lineage.kind == "rerun"


def test_no_solution_key_seals_none(tmp_path: Path) -> None:
    # No later run is told identical to a run that no runner keyed.
    project = _project(tmp_path)
    ctx = _bind_ctx(project)
    bind_run_directory(
        ctx, run_dir=None, lineage=None, calibrated_by=None, run_overrides={"K": 1e-5}
    )

    assert initial_facts(ctx).solution_key is None


# ``[flow] restart_from`` names a run: the step resolves it to a store and links the lineage by id.


def test_restart_binds_path_and_lineage(tmp_path: Path) -> None:
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


def test_no_restart_reference(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    store = open_run_store(project, "production", n_cells=4)
    flow = SimpleNamespace(restart_from=None)
    ctx = SimpleNamespace(cfg=SimpleNamespace(flow=flow), lineage=None)

    bind_restart_source(ctx, store=store)

    assert flow.restart_from is None
    assert store.facts.lineage.parent_sim_id is None
    store.close()


def test_restart_returns_the_sim_id(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    sid = sealed_run(project, "spinup")
    store = open_run_store(project, "production", n_cells=4)
    flow = SimpleNamespace(restart_from=RestartReference(sim_id=sid))
    ctx = SimpleNamespace(cfg=SimpleNamespace(flow=flow), lineage=None)

    returned = bind_restart_source(ctx, store=store)

    assert returned == sid
    assert flow.restart_from == str(project / "runs" / "spinup" / FIELDS_STORE_NAME)
    store.close()


# The binary each solver of a run calls, which its solution key reads.


def _plan_of(monkeypatch: pytest.MonkeyPatch, *runs: tuple[str, str]) -> None:
    plan = SimpleNamespace(
        runs=[SimpleNamespace(process_type=kind, solver=solver) for kind, solver in runs]
    )
    monkeypatch.setattr(planner.SimulationPlanner, "build", lambda self, simulation: plan)


def _cfg_with_runner(runner: str | None) -> SimpleNamespace:
    def options_of(solver: str) -> SimpleNamespace:
        if solver == "unknown":
            raise ValueError(solver)
        return SimpleNamespace(runner=runner)

    return SimpleNamespace(simulation=object(), solver=SimpleNamespace(options_of=options_of))


@pytest.mark.parametrize(
    ("runner", "wanted"),
    [(None, "mf6"), ("subprocess", "mf6"), ("api", "libmf6")],
    ids=["default", "subprocess", "api"],
)
def test_modflow6_binary_or_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: str | None, wanted: str
) -> None:
    for name in ("mf6", "libmf6"):
        (tmp_path / exe_filename(name)).write_bytes(b"binary")
    _plan_of(monkeypatch, ("mesh", "catchment"), ("flow", "modflow6"), ("transport", "modflow6"))

    found = solver_binaries(_cfg_with_runner(runner), bin_path=tmp_path, fetch=False)

    assert found == {"modflow6": tmp_path / exe_filename(wanted)}, "a mesh step has no binary"


def test_plan_looks_but_does_not_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _plan_of(monkeypatch, ("flow", "boussinesq"), ("flow", "modflow6"))

    found = solver_binaries(_cfg_with_runner(None), bin_path=tmp_path, fetch=False)

    assert found == {"boussinesq": None, "modflow6": None}
    assert list(tmp_path.iterdir()) == [], "a plan only looks"


def test_no_simulation_no_binary() -> None:
    assert solver_binaries(SimpleNamespace(simulation=None)) == {}


def test_run_fetches_managed_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _plan_of(monkeypatch, ("flow", "modflow6"))
    asked: list[str] = []
    monkeypatch.setattr(
        binaries,
        "ensure_solver_binary",
        lambda name, bin_path=None: asked.append(name) or tmp_path / name,
    )

    found = solver_binaries(_cfg_with_runner(None), bin_path=tmp_path)

    assert asked == ["mf6"]
    assert found == {"modflow6": tmp_path / "mf6"}


def test_missing_binary_left_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _plan_of(monkeypatch, ("flow", "modflow6"))

    def refuse(name: str, bin_path=None):
        raise FileNotFoundError(name)

    monkeypatch.setattr(binaries, "ensure_solver_binary", refuse)

    assert solver_binaries(_cfg_with_runner(None), bin_path=tmp_path) == {"modflow6": None}
