"""Tests of `runners.trial`."""

from __future__ import annotations

import copy
import copy as _copy
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import numpy as np
import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace, set_by_path
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.promotion import promote_session
from hydromodpy.calibration.runners.state import space_from_config
from hydromodpy.calibration.runners.trial import (
    TrialContext,
    TrialResult,
    _phase_samples_the_recharge,
    promote_prepared_trial,
    run_trial_light,
)
from hydromodpy.calibration.targets import calibration_targets, targets_by_name
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.budget.terms import POLICY_ALL, POLICY_CONSUMERS, BudgetKeep
from hydromodpy.core.config_kit.written import written_payload
from hydromodpy.core.exceptions import ConfigError, StepError
from hydromodpy.core.state.layout import INTERNAL_DIRNAME
from hydromodpy.core.state.run_state import ExecutionRegistry, SlotRequest
from hydromodpy.core.units.physical_bounds import validate_physical_value
from hydromodpy.model.flow import Flow
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import claim_reserved_directory
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME
from hydromodpy.results.storage.run_facts import PromotionFacts
from hydromodpy.solver.base.results_config import ResultsConfig
from hydromodpy.solver.modflow6.builders.solver_options import resolve_xt3d_decision
from hydromodpy.solver.modflow6.support.property_mapping import (
    K_TENSOR_NPF_NAMES,
    resolve_flow_property_arrays,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.workflow.runner import Pipeline
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.step import Step  # noqa: F401
from hydromodpy.workflow.steps.data import ensure_flow
from hydromodpy.workflow.steps.dependencies import earliest_affected_step
from hydromodpy.workflow.steps.export import step_cleanup_preprocessing
from hydromodpy.workflow.steps.mesh import BuildMeshStep
from hydromodpy.workflow.steps.planning import step_configure_results
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays
from tests.unit.calibration._factories import Setup
from tests.unit.calibration._factories_runners import FakePipeline, ToyCtx, make_session
from tests.unit.calibration.test_targets import _config

# From test_a_parameter_must_reach_a_step.py
# A calibrated parameter that re-runs nothing is a search over a constant.
#
# Each trial re-runs the pipeline from the earliest step that consumes the
# parameter's configuration path. A path no step declares matched nothing, and the
# answer was "no step needs to re-run": the trial then evaluated the previous
# model with a new number attached to it. Every trial returned the same cost, the
# search converged on whatever it started from, and the report named a calibrated
# value.
#
# The mesh is the case that made it visible. ``[mesh]`` drives the mesh
# step and the step did not say so, so calibrating a mesh resolution changed the
# number in the record and nothing on disk.


class _Step__parameter_must:
    def __init__(self, sections: tuple[str, ...]) -> None:
        self.config_sections = sections


_STEPS = (
    _Step__parameter_must(("workspace", "simulation")),
    _Step__parameter_must(("geographic", "data.dem")),
    _Step__parameter_must(("data",)),
    _Step__parameter_must(("domain.supports", "mesh")),
    _Step__parameter_must(("flow", "transport")),
    _Step__parameter_must(()),
)


def test_a_path_a_step_owns_selects_that_step() -> None:
    assert earliest_affected_step({"flow.param.K.field.value"}, _STEPS) == 4


def test_a_mesh_path_selects_the_mesh_step() -> None:
    assert earliest_affected_step({"mesh.cell_size"}, _STEPS) == 3


def test_a_path_no_step_owns_is_refused() -> None:
    with pytest.raises(ConfigError, match="no pipeline step"):
        earliest_affected_step({"flow.param.K.field.value", "nowhere.at.all"}, _STEPS)


def test_the_refusal_names_the_path_and_what_a_step_would_have_to_declare() -> None:
    with pytest.raises(ConfigError) as caught:
        earliest_affected_step({"nowhere.at.all"}, _STEPS)

    message = str(caught.value)
    assert "nowhere.at.all" in message
    assert "mesh" in message


def test_the_mesh_step_declares_the_sections_that_drive_it() -> None:
    """The step reads [mesh]; it has to say so."""
    declared = set(BuildMeshStep.config_sections)

    assert {"mesh"} <= declared


# From test_a_phase_that_samples_the_recharge_owns_its_trial_recharge.py
# ``_phase_samples_the_recharge`` reads what THIS phase samples, not what it reruns.
#
# A phase after a frozen recharge phase carries ``soil.ru`` in
# ``override_paths`` (it reruns the value) without carrying it in
# ``parameter_space`` (it does not search over it). Only the second one means
# the phase owns its own recharge folder.


def _trial_context(
    *,
    parameter_space: ParameterSpace | None = None,
    override_paths: dict[str, str] | None = None,
) -> TrialContext:
    return TrialContext(
        base_cfg=None,
        ctx=None,
        earliest=0,
        downstream_steps=(),
        override_paths=override_paths or {},
        workspace=Path("."),
        cfg_path=Path("hydromodpy.toml"),
        parameter_space=parameter_space,
    )


SOIL_RU = "flow.sinks_sources.recharge.soil.ru"
K_VALUE = "flow.K.value"


def _sampled(**paths: str) -> ParameterSpace | None:
    """A space sampling each name on its path, or None when no name is given."""
    specs = [CalibParameter(name=n, lower=0, upper=1000, path=p) for n, p in paths.items()]
    return ParameterSpace(specs) if specs else None


@pytest.mark.parametrize(
    ("sampled", "override_paths", "owns"),
    [
        pytest.param({"ru": SOIL_RU}, None, True, id="a_sampled_soil_ru"),
        pytest.param(
            {"rch": "flow.sinks_sources.recharge.values"}, None, True, id="a_sampled_rate"
        ),
        pytest.param({"K": K_VALUE}, None, False, id="only_k_sampled"),
        # Phase K after phase RU: soil.ru is frozen and reran (override_paths),
        # but this phase's own parameter_space only searches over K.
        pytest.param(
            {"K": K_VALUE}, {"K": K_VALUE, "ru": SOIL_RU}, False, id="a_frozen_soil_ru_reran"
        ),
        # With no parameter space, the override paths decide.
        pytest.param({}, {"ru": SOIL_RU}, True, id="no_space_recharge_path"),
        pytest.param({}, {"K": K_VALUE}, False, id="no_space_other_path"),
    ],
)
def test_a_trial_owns_its_recharge_when_its_phase_samples_what_it_is_computed_from(
    sampled, override_paths, owns
) -> None:
    ctx = _trial_context(parameter_space=_sampled(**sampled), override_paths=override_paths)

    assert _phase_samples_the_recharge(ctx) is owns


# From test_a_promoted_run_closes_its_attempt.py
# A promoted run closes its attempt: completed once sealed, failed when it raises.
#
# A promotion is not launched under ``workflow.record.attempt.run_attempt``: the
# pipeline claims the reserved directory and seals it, and nothing else used to
# close the attempt. The promoted run then kept ``outcome.json = running``,
# ``ended_at = null`` and its ``.hmp/`` beside a completed manifest. The
# pipeline is stubbed down to a claim, a seal and the facts the session hands it.


@dataclass
class _Cfg:
    K: float = 1.0
    simulation: Any = field(default_factory=lambda: SimpleNamespace(name="toy", results=None))

    def model_copy(self, *, deep: bool = False) -> _Cfg:
        return copy.deepcopy(self)


class _Step:
    def __init__(self, name: str, action) -> None:
        self.name = name
        self._action = action

    def run(self, state: PipelineState) -> PipelineState:
        self._action(state)
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


def _claim(state: PipelineState) -> None:
    ctx = state.get("ctx")
    run_dir = state.get("run_dir")
    claim_reserved_directory(
        run_dir, case_id=run_dir.name, project="project", sim_id=ctx.reserved_sim_id
    )
    (run_dir / INTERNAL_DIRNAME / "checkpoints").mkdir(parents=True, exist_ok=True)
    ctx.sim_id = ctx.reserved_sim_id


def _seal(state: PipelineState) -> None:
    (state.get("run_dir") / RUN_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")


def _trial_ctx(tmp_path: Path, steps) -> TrialContext:
    cfg = _Cfg()
    ctx = ToyCtx(cfg=cfg, config_path=tmp_path / "calib.toml", raw_toml={})
    trial_ctx = TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=0,
        downstream_steps=tuple(steps),
        override_paths={"K": "K"},
        workspace=tmp_path,
        cfg_path=tmp_path / "calib.toml",
        raw_toml={},
    )
    trial_ctx.kept_solves = None
    return trial_ctx


@pytest.fixture()
def _pipeline(monkeypatch) -> None:
    monkeypatch.setattr(trial_module, "_PIPELINE", FakePipeline())


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "calage"
    run_dir.mkdir(parents=True)
    return run_dir


@pytest.mark.usefixtures("_pipeline")
def test_a_sealed_promotion_is_completed_and_keeps_no_attempt_state(tmp_path) -> None:
    run_dir = _run_dir(tmp_path)
    trial_ctx = _trial_ctx(tmp_path, [_Step("prepare_solver", _claim), _Step("export", _seal)])

    promote_prepared_trial(trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32, run_dir=run_dir)

    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "completed"
    assert outcome.ended_at is not None
    assert not (run_dir / INTERNAL_DIRNAME).exists()


@pytest.mark.usefixtures("_pipeline")
def test_a_promotion_that_raises_is_failed_and_says_why(tmp_path) -> None:
    run_dir = _run_dir(tmp_path)

    def _boom(state: PipelineState) -> None:
        raise RuntimeError("the solver did not converge")

    trial_ctx = _trial_ctx(tmp_path, [_Step("prepare_solver", _claim), _Step("export", _boom)])

    with pytest.raises(StepError, match="did not converge"):
        promote_prepared_trial(
            trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32, run_dir=run_dir
        )

    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.error is not None and "did not converge" in outcome.error.message
    assert not (run_dir / RUN_MANIFEST_FILENAME).exists()


@pytest.mark.usefixtures("_pipeline")
def test_an_interrupted_promotion_is_aborted(tmp_path) -> None:
    run_dir = _run_dir(tmp_path)

    def _interrupt(state: PipelineState) -> None:
        raise KeyboardInterrupt

    trial_ctx = _trial_ctx(tmp_path, [_Step("prepare_solver", _claim), _Step("export", _interrupt)])

    with pytest.raises(KeyboardInterrupt):
        promote_prepared_trial(
            trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32, run_dir=run_dir
        )

    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "aborted"


@pytest.mark.usefixtures("_pipeline")
def test_the_facts_of_the_session_travel_in_the_state_of_the_run(tmp_path) -> None:
    run_dir = _run_dir(tmp_path)
    seen: list[Any] = []
    trial_ctx = _trial_ctx(
        tmp_path,
        [
            _Step(
                "prepare_solver", lambda state: (seen.append(state.get("promotion")), _claim(state))
            ),
            _Step("export", _seal),
        ],
    )
    promotion = PromotionFacts(converged=True)

    promote_prepared_trial(
        trial_ctx,
        {"K": 2.0},
        name="calage",
        sim_id="a" * 32,
        run_dir=run_dir,
        promotion=promotion,
    )

    assert seen == [promotion]
    assert json.loads((run_dir / "outcome.json").read_text())["status"] == "completed"


# From test_a_saved_trial_run_keeps_only_what_it_reads.py
# The runs a calibration saves: the best keeps the budget, the others keep what they read.
#
# Trials write nothing. ``save_runs`` writes the runs it names: the best one keeps
# ``[simulation.results] keep_per_cell_budget`` as the project file says (the whole
# per-cell budget by default), every other saved run takes the ``consumers`` policy.
# The pipeline is stubbed down to the step that decides the policy
# (``step_configure_results``, the real one) and the step that records it.


@dataclass
class _Cfg__saved_trial:
    K: float = 1.0
    simulation: Any = field(
        default_factory=lambda: SimpleNamespace(name="toy", results=ResultsConfig())
    )
    display: Any = field(default_factory=lambda: SimpleNamespace(enabled=False, figures=()))

    def model_copy(self, *, deep: bool = False) -> _Cfg:
        return copy.deepcopy(self)


@dataclass
class _Ctx__saved_trial:
    cfg: _Cfg__saved_trial
    config_path: Path
    raw_toml: dict[str, Any]
    # The bounds of the call, as WorkflowContext carries them now.
    bounds: Any = None
    data_plan: Any = None
    setup: Setup = field(default_factory=Setup)
    loaded_data: Any = None
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)
    sim_id: Any = None
    reserved_sim_id: Any = None
    budget_terms: BudgetKeep | None = None


@pytest.fixture
def session(tmp_path: Path, monkeypatch):
    """A trial context and the budget each promoted run decided to keep."""
    kept: dict[str, BudgetKeep] = {}
    flags: dict[str, bool] = {}

    def _plan(state: PipelineState) -> None:
        ctx = state.get("ctx")
        ctx.budget_terms = step_configure_results(
            ctx.cfg.simulation.results,
            SimpleNamespace(runs=()),
            ctx.cfg.display,
            display_active=False,
            export_requests=(),
            calibration=None,
            observation=None,
        )

    def _export(state: PipelineState) -> None:
        ctx = state.get("ctx")
        run_dir = state.get("run_dir")
        label = (
            ctx.setup.run_id if run_dir is None or run_dir.parent.name == "runs" else run_dir.name
        )
        kept[label] = ctx.budget_terms
        flags[label] = ctx.cfg.simulation.results.keep_per_cell_budget
        ctx.sim_id = ctx.reserved_sim_id

    monkeypatch.setattr(trial_module, "_PIPELINE", FakePipeline())
    cfg = _Cfg__saved_trial()
    ctx = _Ctx__saved_trial(cfg=cfg, config_path=tmp_path / "calib.toml", raw_toml={})
    trial_ctx = TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=0,
        downstream_steps=(_Step("prepare_solver", _plan), _Step("export", _export)),
        override_paths={"K": "K"},
        workspace=tmp_path,
        cfg_path=tmp_path / "calib.toml",
        raw_toml={},
    )
    trial_ctx.kept_solves = None
    return trial_ctx, kept, flags


def _persistence(project: Path, rows: int, costs: dict[int, float]) -> CalibrationPersistence:
    """A journaled session of ``rows`` trials, trial ``n`` at parameter ``K = n``."""
    costs = [{"cost": costs[index], "k": float(index)} for index in range(1, rows + 1)]
    return make_session(project, "best", costs=costs, project=project.name, bounds={})


def _promote(trial_ctx, *, cfg: CalibrationConfig, rows: int, best_trial: int):
    project = trial_ctx.workspace / "project"
    costs = {index: float(index) for index in range(1, rows + 1)}
    costs[best_trial] = 0.0
    outcome = promote_session(
        cfg=cfg,
        trial_ctx=trial_ctx,
        persistence=_persistence(project, rows, costs),
        project_root=project,
        phase="main",
        session_status="completed",
        override_paths={"K": "K"},
    )
    return outcome.count, outcome.failures, outcome.best_sim_id


@pytest.mark.parametrize(
    "declared",
    [
        {"save_runs": "best_n", "save_best_n": 3},
        {"save_runs": "all"},
    ],
)
def test_the_best_run_keeps_everything_and_the_others_keep_what_they_read(
    session, declared
) -> None:
    trial_ctx, kept, flags = session

    count, failures, best_sim_id = _promote(
        trial_ctx, cfg=CalibrationConfig(**declared), rows=3, best_trial=2
    )

    assert (count, failures) == (3, [])
    assert best_sim_id is not None
    # Every promoted run is named after the case; the best one keeps everything,
    # the two kept trials take the consumers policy, in the order they were promoted.
    assert kept["best"] == BudgetKeep.everything()
    assert kept["best"].policy == POLICY_ALL
    assert flags["best"] is True
    assert [policy.policy for policy in kept.values()][1:] == [POLICY_CONSUMERS, POLICY_CONSUMERS]
    assert list(flags.values())[1:] == [False, False]


def test_the_best_run_follows_the_project_file(session) -> None:
    trial_ctx, kept, flags = session
    trial_ctx.base_cfg.simulation.results = ResultsConfig(keep_per_cell_budget=False)

    _promote(
        trial_ctx,
        cfg=CalibrationConfig(save_runs="best_n", save_best_n=2),
        rows=2,
        best_trial=1,
    )

    assert flags["best"] is False
    assert kept["best"].policy == POLICY_CONSUMERS


def test_a_saved_run_never_changes_the_shared_configuration(session) -> None:
    trial_ctx, _, _ = session

    _promote(
        trial_ctx,
        cfg=CalibrationConfig(save_runs="all"),
        rows=3,
        best_trial=1,
    )

    assert trial_ctx.base_cfg.simulation.results.keep_per_cell_budget is True
    assert trial_ctx.ctx.cfg.simulation.results.keep_per_cell_budget is True


def test_the_override_is_set_on_a_copy_of_the_results_section(session) -> None:
    trial_ctx, kept, flags = session
    shared = trial_ctx.base_cfg.simulation.results

    promote_prepared_trial(
        trial_ctx, {"K": 2.0}, name="lean", sim_id="a" * 32, keep_per_cell_budget=False
    )
    promote_prepared_trial(trial_ctx, {"K": 3.0}, name="whole", sim_id="b" * 32)

    assert kept["lean"].policy == POLICY_CONSUMERS and flags["lean"] is False
    assert kept["whole"] == BudgetKeep.everything() and flags["whole"] is True
    assert trial_ctx.base_cfg.simulation.results is shared
    assert shared.keep_per_cell_budget is True


def test_the_default_promotes_the_best_alone_with_the_whole_budget(session) -> None:
    trial_ctx, kept, _ = session

    count, failures, _ = _promote(trial_ctx, cfg=CalibrationConfig(), rows=3, best_trial=2)

    assert (count, failures) == (1, [])
    assert list(kept) == ["best"]
    assert kept["best"] == BudgetKeep.everything()


# From test_a_trial_moves_the_k_tensor.py
# A calibration trial that moves K22 or an angle reaches the NPF arrays and XT3D.
#
# A trial writes its sample into a copy of the configuration
# (``TrialContext.fork``), and the flow of the trial is built again from it. So
# K22 and the angles travel the path K travels: the catalog offers them, the
# sample lands in ``flow.param``, the shared mapping puts it on every cell, and
# the XT3D rule reads the arrays the build sets on the model. A trial that turns
# the tensor off the grid axes gets XT3D, a trial that keeps it on them does not.
#
# An angle is signed, so the catalog searches it as written. It used to inherit
# the log search every field parameter declares for K, and a range such as
# [-30, 30] was refused at load.


PROJECT_TOML = """
[workflow]
mode = "calibration"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[solver]
backend = "modflow6"

[flow]
param_list = ["K", "K22", "angle1", "angle2"]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"

[flow.param.K22.field]
kind = "homogeneous"
value = "1e-5 m/s"

[flow.param.angle1.field]
kind = "homogeneous"
value = 30.0

[flow.param.angle2.field]
kind = "homogeneous"
value = 0.0

[calibration]
variable = "head"
objective = "rmse"

[calibration.parameters.K22]
bounds = [1e-7, 1e-4]

[calibration.parameters.angle1]
bounds = [-90.0, 90.0]

[calibration.parameters.angle2]
bounds = [-30.0, 30.0]
"""


@pytest.fixture(scope="module")
def cfg__trial_moves(tmp_path_factory) -> HydroModPyConfig:
    path = tmp_path_factory.mktemp("k_tensor_trial") / "project.toml"
    path.write_text(PROJECT_TOML, encoding="utf-8")
    return HydroModPyConfig.from_toml(path)


def _mesh() -> SolverMesh:
    return solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=2,
        top=np.full((2, 2), 30.0),
        botm=np.stack([np.full((2, 2), 20.0), np.zeros((2, 2))]),
    )


def _trial(
    cfg__trial_moves: HydroModPyConfig, tmp_path: Path, values: dict[str, float]
) -> TrialContext:
    setup = SimpleNamespace(flow=None, transport=None, slot_request=None)
    ctx = SimpleNamespace(
        setup=setup,
        data_plan=None,
        # The bounds of the call, as WorkflowContext carries them now.
        bounds=None,
        loaded_data=SimpleNamespace(),
        execution=ExecutionRegistry(),
    )
    base = TrialContext(
        base_cfg=cfg__trial_moves,
        ctx=ctx,
        earliest=0,
        downstream_steps=(),
        override_paths={},
        workspace=tmp_path,
        cfg_path=tmp_path / "project.toml",
        parameter_space=space_from_config(cfg__trial_moves.calibration),
    )
    return base.fork(values)


def _built_model(trial: TrialContext, mesh: SolverMesh) -> SimpleNamespace:
    """The model attributes ``run_pre_processing`` sets before its XT3D decision."""
    ensure_flow(trial.ctx)
    mapped = resolve_flow_property_arrays(
        profiles=trial.ctx.setup.flow.parameters,
        domain=SimpleNamespace(zones={}),
        solver_mesh=mesh,
        required_properties=frozenset({"K"}),
    )
    runtime = SimpleNamespace(mf6_enable_xt3d=None)
    model = SimpleNamespace(modflow_config=SimpleNamespace(runtime=runtime))
    model.hk = mesh.flatten_from_grid(mapped["hk"])
    for name in K_TENSOR_NPF_NAMES:
        values = mapped.get(name)
        setattr(model, name, None if values is None else mesh.flatten_from_grid(values))
    return model


@pytest.mark.parametrize("name", ["angle1", "angle2"])
def test_the_catalogue_searches_an_angle_as_written(cfg__trial_moves, name: str) -> None:
    target = targets_by_name(calibration_targets(cfg__trial_moves))[name]
    assert target.calibrable is not None
    assert (target.calibrable.search_space, target.calibrable.sampling) == ("identity", "uniform")
    assert (
        cfg__trial_moves.calibration.parameters[name].search_space,
        cfg__trial_moves.calibration.parameters[name].sampling,
    ) == (
        "identity",
        "uniform",
    )


def test_k22_is_still_searched_in_log_space(cfg__trial_moves) -> None:
    assert cfg__trial_moves.calibration.parameters["K22"].search_space == "log"


def test_a_signed_angle_range_builds_a_parameter_space(cfg__trial_moves) -> None:
    space = space_from_config(cfg__trial_moves.calibration)
    assert {param.name for param in space} == {"K22", "angle1", "angle2"}


def test_the_trial_sample_reaches_every_cell_of_the_tensor(
    cfg__trial_moves, tmp_path: Path
) -> None:
    trial = _trial(cfg__trial_moves, tmp_path, {"K22": 2e-6, "angle1": 45.0, "angle2": 12.0})
    model = _built_model(trial, _mesh())
    assert np.all(model.k22 == pytest.approx(2e-6))
    assert np.all(model.angle1 == 45.0)
    assert np.all(model.angle2 == 12.0)
    assert cfg__trial_moves.flow.param["K22"].field.value == pytest.approx(1e-5)


def test_the_base_tensor_keeps_xt3d_off(cfg__trial_moves, tmp_path: Path) -> None:
    model = _built_model(_trial(cfg__trial_moves, tmp_path, {}), _mesh())
    assert resolve_xt3d_decision(model, _mesh()).enabled is False


def test_a_trial_that_turns_k22_off_axis_gets_xt3d(cfg__trial_moves, tmp_path: Path) -> None:
    model = _built_model(_trial(cfg__trial_moves, tmp_path, {"K22": 1e-6}), _mesh())
    with pytest.warns(RuntimeWarning, match="K22 differs from K"):
        decision = resolve_xt3d_decision(model, _mesh())
    assert (decision.enabled, decision.source) == (True, "auto_on")


def test_a_trial_that_tilts_the_tensor_gets_xt3d(cfg__trial_moves, tmp_path: Path) -> None:
    model = _built_model(_trial(cfg__trial_moves, tmp_path, {"angle2": -8.0}), _mesh())
    with pytest.warns(RuntimeWarning, match="tilted"):
        assert resolve_xt3d_decision(model, _mesh()).enabled


def test_a_trial_that_brings_k22_back_on_axis_keeps_xt3d_off(
    cfg__trial_moves, tmp_path: Path
) -> None:
    model = _built_model(_trial(cfg__trial_moves, tmp_path, {"K22": 1e-6, "angle1": 90.0}), _mesh())
    assert resolve_xt3d_decision(model, _mesh()).enabled is False


# From test_a_trial_tells_the_solver_when_its_recharge_is_its_own.py
# ``run_trial_light`` marks the sandbox only when the phase owns its recharge.
#
# A trial always gets a private run name in its ``SlotRequest``. Its
# ``shared_forcing_dir`` is a ``_recharge`` folder inside the trial folder when
# its phase samples a value the recharge is computed from
# (:func:`_phase_samples_the_recharge`), and otherwise the ``_shared_recharge``
# folder every trial of the phase shares. MODFLOW 6 writes its RCHA/EVTA
# binaries into that folder.


@dataclass
class _FakeParam:
    value: float = 1.0


@dataclass
class _FakeSoil:
    ru: float = 150.0


@dataclass
class _FakeRecharge:
    soil: _FakeSoil = field(default_factory=_FakeSoil)
    values: float = 0.0


@dataclass
class _FakeSinksSources:
    recharge: _FakeRecharge = field(default_factory=_FakeRecharge)


@dataclass
class _FakeSimulation:
    name: str = "toy"


@dataclass
class _FakeFlow:
    K: _FakeParam = field(default_factory=_FakeParam)
    Sy: _FakeParam = field(default_factory=_FakeParam)
    sinks_sources: _FakeSinksSources = field(default_factory=_FakeSinksSources)


@dataclass
class _FakeCfg:
    flow: _FakeFlow = field(default_factory=_FakeFlow)
    simulation: _FakeSimulation = field(default_factory=_FakeSimulation)

    def model_copy(self, *, deep: bool = False) -> _FakeCfg:
        return _copy.deepcopy(self) if deep else _copy.copy(self)


@dataclass
class _FakeSetup:
    workspace: Any = None
    geographic: Any = None
    cell_mesh: Any = None
    domain: Any = None
    flow: Any = None
    transport: Any = None
    slot_request: Any = None
    run_id: str = "toy"
    time_grid: Any = None


@dataclass
class _FakeLoadedData:
    hydrometry: Any = None


@dataclass
class _FakeCtx:
    cfg: _FakeCfg
    config_path: Path
    raw_toml: dict[str, Any]
    # The bounds of the call, as WorkflowContext carries them now.
    bounds: Any = None
    data_plan: Any = None
    setup: _FakeSetup = field(default_factory=_FakeSetup)
    loaded_data: _FakeLoadedData = field(default_factory=_FakeLoadedData)
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)
    store: Any = None
    sim_id: Any = None


def _trial_context__trial_tells(
    tmp_path: Path, *, parameter_space: ParameterSpace | None
) -> TrialContext:
    cfg = _FakeCfg()
    ctx = _FakeCtx(cfg=cfg, config_path=tmp_path / "hydromodpy.toml", raw_toml={})
    ctx.setup.workspace = SimpleNamespace(solver_scratch_folder=tmp_path / "scratch")
    # earliest=9 with no downstream steps: run_trial_light skips the pipeline
    # slice entirely and only exercises fork() + the metric extractor, which is
    # all this contract needs.
    return TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=9,
        downstream_steps=(),
        override_paths={"K": "flow.K.value"},
        workspace=tmp_path,
        cfg_path=tmp_path / "hydromodpy.toml",
        raw_toml={},
        parameter_space=parameter_space,
    )


def _run_and_capture_request(
    trial_ctx: TrialContext, values: dict[str, float], *, trial_id: int | None
) -> SlotRequest | None:
    captured: list[SlotRequest | None] = []

    def _metric(ctx, *, objective, variable):
        captured.append(ctx.setup.slot_request)
        return 0.0, {}

    run_trial_light(trial_ctx, values, metric_fn=_metric, trial_id=trial_id)
    return captured[0]


@pytest.mark.usefixtures("ensure_bootstrap")
class TestTheTrialForcingFolder:
    @pytest.mark.parametrize(
        ("sampled", "values", "trial_id", "expected"),
        [
            pytest.param(
                {"ru": SOIL_RU},
                {"ru": 120.0},
                1,
                ("toy_trial000001", "toy_trial000001/_recharge"),
                id="a_sampled_soil_recharge_marks_its_own_folder",
            ),
            pytest.param(
                {"K": K_VALUE},
                {"K": 1.0},
                2,
                ("toy_trial000002", "_shared_recharge"),
                id="a_phase_that_samples_only_k_shares_the_recharge",
            ),
            pytest.param(
                {"ru": SOIL_RU}, {"ru": 100.0}, None, None, id="a_trial_without_an_id_gets_none"
            ),
        ],
    )
    def test_the_trial_slot_request(self, tmp_path, sampled, values, trial_id, expected) -> None:
        trial_ctx = _trial_context__trial_tells(tmp_path, parameter_space=_sampled(**sampled))

        request = _run_and_capture_request(trial_ctx, values, trial_id=trial_id)
        if expected is None:
            assert request is None
            return
        name, forcing = expected
        assert request == SlotRequest(name=name, shared_forcing_dir=tmp_path / "scratch" / forcing)


# From test_trial_primitive.py
# Unit tests for :mod:`hydromodpy.calibration.runners.trial`.
#
# Phase 1 introduces the lightweight trial primitive that the
# calibration loop forks from. The surface tested here is intentionally
# narrow:
#
# - :class:`TrialContext.fork` deep-copies the config, injects values
#   through the declared dotted paths, shares the expensive setup
#   objects by reference, and resets ``setup.flow`` and ``setup.model``
#   so the downstream steps rebuild them from the trial's config.
# - :func:`run_trial_light` never creates disk artifacts in the CWD and
#   returns a ``TrialResult`` even when the default metric extractor
#   is used (Phase 2 swaps the extractor in).
#
# The tests exercise the primitive through toy steps rather than the
# real MODFLOW pipeline so they run under a second.


# ---------------------------------------------------------------------------
# Toy pipeline steps that record their invocations without touching disk
# ---------------------------------------------------------------------------
class _CallCounterStep:
    def __init__(self, name: str, sections: tuple[str, ...]) -> None:
        self.name = name
        self.config_sections: ClassVar[tuple[str, ...]] = sections  # type: ignore[misc]
        self.config_sections = sections  # runtime attr for dependency matcher
        self.calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.calls += 1
        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
        )


def _make_trial_context(tmp_path: Path, *, earliest: int) -> tuple[TrialContext, list]:
    """Build a TrialContext populated with stub steps + ctx.

    Returns the ``TrialContext`` and the list of toy steps so individual
    tests can inspect call counts.
    """
    steps = [
        _CallCounterStep("s0", ("workspace", "simulation")),
        _CallCounterStep("s1", ("workspace", "simulation")),
        _CallCounterStep("s2", ("data",)),
        _CallCounterStep("s3", ("geographic", "data.dem")),
        _CallCounterStep("s4", ("domain.supports",)),
        _CallCounterStep("s5", ("domain.depth_model", "flow.ic", "simulation")),
        _CallCounterStep("s6", ("flow", "transport", "solver")),
        _CallCounterStep("s7", ("flow", "transport", "solver")),
        _CallCounterStep("s8", ()),
    ]
    cfg = _FakeCfg()
    ctx = _FakeCtx(cfg=cfg, config_path=tmp_path / "hydromodpy.toml", raw_toml={})

    trial_ctx = TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=earliest,
        downstream_steps=tuple(steps),
        override_paths={"K": "flow.K.value"},
        workspace=tmp_path,
        cfg_path=tmp_path / "hydromodpy.toml",
        raw_toml={},
    )
    return trial_ctx, steps


# ---------------------------------------------------------------------------
# Fork isolation
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("ensure_bootstrap")
class TestFork:
    def test_value_is_injected_via_dotted_path(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        forked = trial_ctx.fork({"K": 2.5})
        assert forked.ctx.cfg.flow.K.value == 2.5

    def test_fork_does_not_mutate_base_cfg(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        assert trial_ctx.base_cfg.flow.K.value == 1.0
        forked = trial_ctx.fork({"K": 7.0})
        assert forked.ctx.cfg.flow.K.value == 7.0
        # Base must stay at its initial value so subsequent forks start
        # from the same baseline.
        assert trial_ctx.base_cfg.flow.K.value == 1.0
        assert trial_ctx.ctx.cfg.flow.K.value == 1.0

    def test_fork_produces_independent_setup_but_shares_big_refs(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        trial_ctx.ctx.setup.geographic = object()
        trial_ctx.ctx.setup.cell_mesh = object()
        trial_ctx.ctx.setup.flow = "should_be_reset"

        forked = trial_ctx.fork({"K": 3.0})

        # setup instance is new (so mutation inside the trial does not
        # leak back to base), but geographic / cell_mesh are shared
        # references because those are expensive to rebuild.
        assert forked.ctx.setup is not trial_ctx.ctx.setup
        assert forked.ctx.setup.geographic is trial_ctx.ctx.setup.geographic
        assert forked.ctx.setup.cell_mesh is trial_ctx.ctx.setup.cell_mesh
        # flow is reset so step 05 / SimulationRunner will rebuild it from
        # the trial's cfg.flow.
        assert forked.ctx.setup.flow is None
        assert forked.ctx.setup.slot_request is None

    def test_fork_is_lightweight(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        forked = trial_ctx.fork({"K": 0.01})
        assert forked.ctx.execution.lightweight is True
        # Fresh execution registry: no residual plan / models carried
        # over from another trial or from the base.
        assert forked.ctx.execution.solver_runs == {}
        # A lightweight trial has no index to write to, and the context it
        # forks carries no handle to one.
        assert not hasattr(forked.ctx, "store")

    def test_loaded_data_is_shared_by_reference(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        hydro = object()
        trial_ctx.ctx.loaded_data.hydrometry = hydro
        forked = trial_ctx.fork({"K": 0.01})
        assert forked.ctx.loaded_data is trial_ctx.ctx.loaded_data
        assert forked.ctx.loaded_data.hydrometry is hydro

    def test_a_slot_request_seeds_the_forked_setup(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        request = SlotRequest(name="toy_trial000001")
        forked = trial_ctx.fork({"K": 1.0}, slot_request=request)
        assert forked.ctx.setup.slot_request == request
        # The base setup keeps no request of a trial.
        assert getattr(trial_ctx.ctx.setup, "slot_request", None) is None
        # Without a request the forked setup has none.
        plain = trial_ctx.fork({"K": 1.0})
        assert plain.ctx.setup.slot_request is None


# ---------------------------------------------------------------------------
# run_trial_light - scheduling + no-disk-I/O
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("ensure_bootstrap")
class TestRunTrialLight:
    def test_runs_only_downstream_slice(self, tmp_path: Path) -> None:
        trial_ctx, steps = _make_trial_context(tmp_path, earliest=6)
        # First trial
        result = run_trial_light(
            trial_ctx,
            {"K": 1.0},
            metric_fn=lambda ctx, *, objective, variable: (0.0, {}),
        )
        assert isinstance(result, TrialResult)
        assert result.status == "completed"
        # steps[0..5] must NOT have been called (they are the shared prep)
        for step in steps[:6]:
            assert step.calls == 0, f"step {step.name} re-ran unexpectedly"
        # steps[6..8] must have run exactly once
        for step in steps[6:9]:
            assert step.calls == 1, f"step {step.name} did not run"

    def test_trial_runs_with_rendering_off(self, tmp_path: Path) -> None:
        # A trial draws nothing, so it must carry the same switch as
        # `hmp run --no-display`: no figure gets to turn a derived flag on,
        # and no derivation forces the per-cell budget no trial step drops.
        trial_ctx, steps = _make_trial_context(tmp_path, earliest=6)
        seen: list[object] = []
        original = steps[6].run

        def _capture(state: PipelineState) -> PipelineState:
            seen.append(state.get("skip_display"))
            return original(state)

        steps[6].run = _capture

        run_trial_light(
            trial_ctx,
            {"K": 1.0},
            metric_fn=lambda ctx, *, objective, variable: (0.0, {}),
        )

        assert seen == [True]

    def test_trial_writes_no_files(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        before = _snapshot_files(tmp_path)
        run_trial_light(trial_ctx, {"K": 0.1})
        after = _snapshot_files(tmp_path)
        assert before == after, "run_trial_light created disk artefacts"

    @pytest.mark.parametrize(
        ("stage", "status", "error_start", "error_holds"),
        [
            ("solver", "crashed", "StepError: ", "solver crashed"),
            # The search moves K: a K past its ceiling is a point it can leave.
            ("moved", "crashed", "infeasible: StepError: ", "id='K'"),
            # Sy is fixed: its refusal repeats on every trial, so it is a failure.
            ("fixed", "crashed", "StepError: ", "id='Sy'"),
            ("candidate", "failed", "infeasible: fork: ValueError: ", "candidate 8"),
        ],
    )
    def test_a_failure_is_captured_as_status(
        self, tmp_path: Path, stage: str, status: str, error_start: str, error_holds: str
    ) -> None:
        trial_ctx, steps = _make_trial_context(tmp_path, earliest=6)
        values = {"K": 0.1}
        if stage == "candidate":
            # A scale of 8 on Sy = 1 writes 8, past the physical ceiling.
            trial_ctx.parameter_space = [
                CalibParameter("Sy", 0.5, 8.0, path="flow.Sy.value", mode="scale", units="-")
            ]
            values = {"Sy": 8.0}
        else:

            def boom(_state):
                if stage == "solver":
                    raise RuntimeError("solver crashed")
                validate_physical_value(
                    param_id="K" if stage == "moved" else "Sy", value=1e4, where="zone 'a'"
                )

            steps[7].run = boom  # type: ignore[assignment]

        result = run_trial_light(trial_ctx, values)
        assert result.status == status
        assert result.primary_metric != result.primary_metric  # NaN
        assert (result.error or "").startswith(error_start)
        assert error_holds in (result.error or "")

    def test_default_metric_returns_failed_result(self, tmp_path: Path) -> None:
        """The stub metric extractor fails the trial with a non-finite objective.

        The real extractor is swapped in by the calibration CLI in Phase 2.
        """
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        result = run_trial_light(trial_ctx, {"K": 1.0})
        assert result.status == "failed"
        assert result.primary_metric != result.primary_metric  # NaN
        assert result.metrics == {}
        assert result.error == "metric_fn returned a non-finite objective"

    def test_custom_metric_fn_is_used_when_supplied(self, tmp_path: Path) -> None:
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)

        def _metric(ctx, *, objective, variable):
            return 0.42, {"nse@outlet": 0.58}

        result = run_trial_light(trial_ctx, {"K": 1.0}, metric_fn=_metric)
        assert result.primary_metric == pytest.approx(0.42)
        assert result.metrics == {"nse@outlet": 0.58}

    def test_trials_get_isolated_model_identity_and_cleanup(self, tmp_path: Path) -> None:
        """Each trial gets a unique run name and its outputs are cleaned."""
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)
        trial_ctx.ctx.setup.run_id = "toy"

        seen: list[str] = []
        created: list[Path] = []

        def _capture(ctx, *, objective, variable):
            name = ctx.setup.slot_request.name
            seen.append(name)
            # Simulate the solver having written an output folder for this run.
            out = tmp_path / name
            out.mkdir(parents=True, exist_ok=True)
            ctx.execution.solver_runs["run"] = SimpleNamespace(output_dir=out)
            created.append(out)
            return 0.0, {}

        r1 = run_trial_light(trial_ctx, {"K": 1.0}, metric_fn=_capture, trial_id=1)
        r2 = run_trial_light(trial_ctx, {"K": 2.0}, metric_fn=_capture, trial_id=2)

        assert r1.status == "completed" and r2.status == "completed"
        # Distinct, deterministic per-trial model identities.
        assert seen == ["toy_trial000001", "toy_trial000002"]
        # Ephemeral: each trial's solver output is removed on exit.
        assert all(not d.exists() for d in created)

    def test_trial_without_id_has_no_slot_request(self, tmp_path: Path) -> None:
        """trial_id=None keeps the path without a sandbox: no slot request."""
        trial_ctx, _ = _make_trial_context(tmp_path, earliest=6)

        captured: dict[str, object] = {}

        def _capture(ctx, *, objective, variable):
            captured["request"] = ctx.setup.slot_request
            return 0.0, {}

        run_trial_light(trial_ctx, {"K": 1.0}, metric_fn=_capture)
        assert captured["request"] is None


@pytest.mark.usefixtures("ensure_bootstrap")
class TestPromotion:
    def test_a_promotion_leaves_the_preprocessing_tree_to_the_next_one(
        self, tmp_path: Path
    ) -> None:
        """Every kept trial is promoted from one shared preprocessing tree.

        The export step of the first promotion used to drop it, so the next
        promoted runs found no watershed to ingest and summed their catchment
        series over the whole domain.
        """

        stable = tmp_path / ".hmp" / "scratch" / "_preprocessing"
        (stable / "geographic").mkdir(parents=True)
        (stable / "geographic" / "watershed.shp").write_bytes(b"x" * 64)

        trial_ctx, steps = _make_trial_context(tmp_path, earliest=6)
        trial_ctx.ctx.setup.geographic = SimpleNamespace(stable_folder=str(stable))
        seen: list[bool] = []

        def _export(state: PipelineState) -> PipelineState:
            ctx = state.get("ctx")
            seen.append((stable / "geographic" / "watershed.shp").is_file())
            step_cleanup_preprocessing(ctx, keep=bool(state.get("keep_preprocessing")))
            ctx.sim_id = ctx.reserved_sim_id
            return state.advance(step_index=state.step_index + 1, step_name="export")

        steps[8].run = _export  # type: ignore[assignment]

        promote_prepared_trial(trial_ctx, {"K": 1.0}, name="best", sim_id="a" * 32)
        promote_prepared_trial(trial_ctx, {"K": 2.0}, name="best_trial_0002", sim_id="b" * 32)

        assert seen == [True, True]
        assert stable.is_dir()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("ensure_bootstrap")
class TestSetByPath:
    def test_sets_nested_leaf(self) -> None:
        cfg = _FakeCfg()
        set_by_path(cfg, "flow.K.value", 5.5)
        assert cfg.flow.K.value == 5.5

    def test_deep_copy_isolates_mutation(self) -> None:
        base = _FakeCfg()
        forked = base.model_copy(deep=True)
        set_by_path(forked, "flow.K.value", 9.0)
        assert forked.flow.K.value == 9.0
        assert base.flow.K.value == 1.0


def _snapshot_files(root: Path) -> set[str]:
    """Recursively list every file under ``root`` relative to ``root``."""
    out: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            out.add(str(Path(dirpath, name).relative_to(root)))
    return out


@pytest.mark.usefixtures("ensure_bootstrap")
def test_a_calibrated_factor_reaches_the_fork_the_frozen_file_and_the_replay(tmp_path) -> None:
    cfg = _config(tmp_path, sinks_sources={"recharge": {"values": 2.0}})
    stub, _ = _make_trial_context(tmp_path, earliest=6)
    paths = {"recharge.factor": "flow.sinks_sources.recharge.factor"}
    base = replace(stub, base_cfg=cfg, override_paths=paths)

    forked = base.fork({"recharge.factor": 1.5}).ctx.cfg

    assert cfg.flow.sinks_sources.recharge.factor == 1.0
    frozen = HydroModPyConfig.model_validate(written_payload(forked))
    assert frozen.flow.sinks_sources.recharge.factor == 1.5
    assert Flow(frozen.flow).sinks_sources["recharge"].values == pytest.approx(3e-3 / 86400.0)
    assert _phase_samples_the_recharge(base)


@pytest.mark.usefixtures("_pipeline")
def test_a_promotion_that_takes_another_id_than_the_reserved_one_is_refused(tmp_path) -> None:
    def _other_id(state: PipelineState) -> None:
        state.get("ctx").sim_id = "b" * 32

    trial_ctx = _trial_ctx(tmp_path, [_Step("export", _other_id)])

    with pytest.raises(RuntimeError, match=f"took the id {'b' * 32} instead of the reserved"):
        promote_prepared_trial(trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32)


@pytest.mark.usefixtures("_pipeline")
def test_an_attempt_that_cannot_be_closed_still_raises_the_error_of_the_pipeline(
    tmp_path, monkeypatch, caplog
) -> None:
    def _boom(state: PipelineState) -> None:
        raise RuntimeError("the solver did not converge")

    def _cannot_write(run_dir, **kwargs) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(trial_module, "finish_attempt", _cannot_write)
    trial_ctx = _trial_ctx(tmp_path, [_Step("prepare_solver", _claim), _Step("export", _boom)])

    with pytest.raises(StepError, match="did not converge"):
        promote_prepared_trial(
            trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32, run_dir=_run_dir(tmp_path)
        )

    assert "Could not write the outcome of" in caplog.text
