"""One calibration trial: fork the config, write the sampled values, re-run the pipeline.

A trial copies the base configuration, writes each sampled value (K in m/s, Sy and
angles as given) through its dotted path, re-runs the pipeline from the earliest
step that reads those paths and scores the model. The best trial of a session is
then promoted into a saved run.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import numpy as np
import pytest
from pydantic import BaseModel

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.lanes import TrialParents
from hydromodpy.calibration.runners.promotion import promote_session
from hydromodpy.calibration.runners.state import space_from_config
from hydromodpy.calibration.runners.trial import (
    TrialContext,
    _phase_samples_the_recharge,
    _with_the_model_built,
    promote_prepared_trial,
    run_trial_light,
)
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.config_kit.written import written_payload
from hydromodpy.core.exceptions import CalibrationError, ConfigError, StepError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.state.layout import INTERNAL_DIRNAME
from hydromodpy.core.state.run_state import ExecutionRegistry, SlotRequest
from hydromodpy.core.units.physical_bounds import validate_physical_value
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.model import ModelTime, model_from_flow
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import claim_reserved_directory
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME
from hydromodpy.results.storage.kept import level_of
from hydromodpy.results.storage.run_facts import PromotionFacts
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.base.results_config import ResultsConfig
from hydromodpy.solver.modflow6.builders.solver_options import resolve_xt3d_decision
from hydromodpy.solver.modflow6.support.property_mapping import (
    K_TENSOR_NPF_NAMES,
    MODFLOW6_PROPERTIES,
)
from hydromodpy.solver.modflow_common.property_mapping import resolve_flow_property_arrays
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.data import ensure_flow
from hydromodpy.workflow.steps.dependencies import earliest_affected_step
from hydromodpy.workflow.steps.mesh import BuildMeshStep
from hydromodpy.workflow.steps.planning import step_configure_results
from tests._helpers.model_factory import default_options, small_geometry, time_grid
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays
from tests.unit.calibration._factories import Setup
from tests.unit.calibration._factories_runners import FakePipeline, ToyCtx, make_session

needs_pipeline = pytest.mark.usefixtures("ensure_bootstrap")

SOIL_RU = "flow.sinks_sources.recharge.soil.ru"
K_VALUE = "flow.K.value"


class StubStep:
    """A pipeline step that only says which config sections it reads."""

    def __init__(self, sections: tuple[str, ...]) -> None:
        self.config_sections = sections


class CountingStep:
    """A pipeline step that counts its runs and touches no disk."""

    def __init__(self, name: str, sections: tuple[str, ...]) -> None:
        self.name = name
        self.config_sections = sections
        self.calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.calls += 1
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class ActionStep:
    """A pipeline step that runs one function on the state."""

    def __init__(self, name: str, action) -> None:
        self.name = name
        self._action = action

    def run(self, state: PipelineState) -> PipelineState:
        self._action(state)
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


@dataclass
class FakeParam:
    value: float = 1.0


@dataclass
class FakeSoil:
    ru: float = 150.0


@dataclass
class FakeRecharge:
    soil: FakeSoil = field(default_factory=FakeSoil)
    values: float = 0.0


@dataclass
class FakeSinksSources:
    recharge: FakeRecharge = field(default_factory=FakeRecharge)


@dataclass
class FakeSimulation:
    name: str = "toy"


@dataclass
class FakeFlow:
    K: FakeParam = field(default_factory=FakeParam)
    Sy: FakeParam = field(default_factory=FakeParam)
    sinks_sources: FakeSinksSources = field(default_factory=FakeSinksSources)


@dataclass
class FakeCfg:
    flow: FakeFlow = field(default_factory=FakeFlow)
    simulation: FakeSimulation = field(default_factory=FakeSimulation)

    def model_copy(self, *, deep: bool = False) -> FakeCfg:
        return copy.deepcopy(self) if deep else copy.copy(self)


@dataclass
class FakeSetup:
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
class FakeLoadedData:
    hydrometry: Any = None


@dataclass
class FakeCtx:
    cfg: FakeCfg
    config_path: Path
    raw_toml: dict[str, Any]
    bounds: Any = None
    data_plan: Any = None
    setup: FakeSetup = field(default_factory=FakeSetup)
    loaded_data: FakeLoadedData = field(default_factory=FakeLoadedData)
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)
    store: Any = None
    sim_id: Any = None


def counting_steps_context(tmp_path: Path, *, earliest: int) -> tuple[TrialContext, list]:
    """Nine counting steps over a fake config, K sampled on `flow.K.value`."""
    steps = [
        CountingStep("s0", ("workspace", "simulation")),
        CountingStep("s1", ("workspace", "simulation")),
        CountingStep("s2", ("data",)),
        CountingStep("s3", ("geographic", "data.dem")),
        CountingStep("s4", ("domain.supports",)),
        CountingStep("s5", ("domain.depth_model", "flow.ic", "simulation")),
        CountingStep("s6", ("flow", "transport", "solver")),
        CountingStep("s7", ("flow", "transport", "solver")),
        CountingStep("s8", ()),
    ]
    cfg = FakeCfg()
    ctx = FakeCtx(cfg=cfg, config_path=tmp_path / "hydromodpy.toml", raw_toml={})
    trial_ctx = TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=earliest,
        downstream_steps=tuple(steps),
        override_paths={"K": K_VALUE},
        workspace=tmp_path,
        cfg_path=tmp_path / "hydromodpy.toml",
        raw_toml={},
    )
    return trial_ctx, steps


def snapshot_files(root: Path) -> set[str]:
    return {
        str(Path(dirpath, name).relative_to(root))
        for dirpath, _dirnames, filenames in os.walk(root)
        for name in filenames
    }


def solver_crash(_state) -> None:
    raise RuntimeError("solver crashed")


def k_past_ceiling(_state) -> None:
    validate_physical_value(param_id="K", value=1e4, where="zone 'a'")


def sy_past_ceiling(_state) -> None:
    validate_physical_value(param_id="Sy", value=1e4, where="zone 'a'")


# Which step each sampled value is allowed to re-run.
PIPELINE_STEPS = (
    StubStep(("workspace", "simulation")),
    StubStep(("geographic", "data.dem")),
    StubStep(("data",)),
    StubStep(("domain.supports", "mesh")),
    StubStep(("flow", "transport")),
    StubStep(()),
)


def test_unowned_path_refused() -> None:
    # A path no step reads would leave the trial evaluating the previous model.
    with pytest.raises(ConfigError, match="no pipeline step"):
        earliest_affected_step({"flow.param.K.field.value", "nowhere.at.all"}, PIPELINE_STEPS)


def test_mesh_step_reads_the_mesh_section() -> None:
    assert "mesh" in set(BuildMeshStep.config_sections)


FAILURES = [
    pytest.param(solver_crash, "StepError: ", "solver crashed", id="solver crash"),
    # The search moves K: a K past its ceiling is a point it can leave.
    pytest.param(k_past_ceiling, "infeasible: StepError: ", "id='K'", id="sampled K past ceiling"),
    # Sy is fixed: its refusal repeats on every trial, so it is a failure.
    pytest.param(sy_past_ceiling, "StepError: ", "id='Sy'", id="fixed Sy past ceiling"),
]


@needs_pipeline
def test_trial_writes_no_files(tmp_path: Path) -> None:
    trial_ctx, _ = counting_steps_context(tmp_path, earliest=6)
    before = snapshot_files(tmp_path)

    run_trial_light(trial_ctx, {"K": 0.1})

    assert snapshot_files(tmp_path) == before


@needs_pipeline
@pytest.mark.parametrize(("crash", "error_start", "error_holds"), FAILURES)
def test_step_failure_status(tmp_path: Path, crash, error_start, error_holds) -> None:
    trial_ctx, steps = counting_steps_context(tmp_path, earliest=6)
    steps[7].run = crash

    result = run_trial_light(trial_ctx, {"K": 0.1})

    assert result.status == "crashed"
    assert np.isnan(result.primary_metric)
    assert (result.error or "").startswith(error_start)
    assert error_holds in (result.error or "")


@needs_pipeline
def test_candidate_past_ceiling(tmp_path: Path) -> None:
    trial_ctx, _ = counting_steps_context(tmp_path, earliest=6)
    # A scale of 8 on Sy = 1 writes 8, past the physical ceiling.
    trial_ctx.parameter_space = [
        CalibParameter("Sy", 0.5, 8.0, path="flow.Sy.value", mode="scale", units="-")
    ]

    result = run_trial_light(trial_ctx, {"Sy": 8.0})

    assert result.status == "failed"
    assert np.isnan(result.primary_metric)
    assert (result.error or "").startswith("infeasible: fork: ValueError: ")
    assert "candidate 8" in (result.error or "")


@needs_pipeline
def test_default_metric_fails(tmp_path: Path) -> None:
    trial_ctx, _ = counting_steps_context(tmp_path, earliest=6)

    result = run_trial_light(trial_ctx, {"K": 1.0})

    assert result.status == "failed"
    assert np.isnan(result.primary_metric)
    assert result.metrics == {}
    assert result.error == "metric_fn returned a non-finite objective"


@needs_pipeline
def test_custom_metric_is_used(tmp_path: Path) -> None:
    trial_ctx, _ = counting_steps_context(tmp_path, earliest=6)

    def metric(ctx, *, objective, variable):
        return 0.42, {"nse@outlet": 0.58}

    result = run_trial_light(trial_ctx, {"K": 1.0}, metric_fn=metric)

    assert result.primary_metric == pytest.approx(0.42)
    assert result.metrics == {"nse@outlet": 0.58}


# The solver writes its RCHA/EVTA binaries in the shared forcing folder of the
# phase, or in a `_recharge` folder of the trial when the phase samples a value
# the recharge is computed from.


def forcing_context(tmp_path: Path, *, parameter_space: ParameterSpace | None) -> TrialContext:
    cfg = FakeCfg()
    ctx = FakeCtx(cfg=cfg, config_path=tmp_path / "hydromodpy.toml", raw_toml={})
    ctx.setup.workspace = SimpleNamespace(solver_scratch_folder=tmp_path / "scratch")
    # earliest=9 with no downstream steps: run_trial_light skips the pipeline
    # and only forks the config and extracts the metric.
    return TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=9,
        downstream_steps=(),
        override_paths={"K": K_VALUE},
        workspace=tmp_path,
        cfg_path=tmp_path / "hydromodpy.toml",
        raw_toml={},
        parameter_space=parameter_space,
    )


def sampled_space(**paths: str) -> ParameterSpace:
    return ParameterSpace(
        [CalibParameter(name=n, lower=0, upper=1000, path=p) for n, p in paths.items()]
    )


SLOT_REQUESTS = [
    pytest.param(
        {"ru": SOIL_RU},
        {"ru": 120.0},
        1,
        ("toy_trial000001", "toy_trial000001/_recharge"),
        id="sampled soil recharge owns its folder",
    ),
    pytest.param(
        {"K": K_VALUE},
        {"K": 1.0},
        2,
        ("toy_trial000002", "_shared_recharge"),
        id="sampled K shares the recharge",
    ),
    pytest.param({"ru": SOIL_RU}, {"ru": 100.0}, None, None, id="no trial id"),
]


@needs_pipeline
@pytest.mark.parametrize(("sampled", "values", "trial_id", "expected"), SLOT_REQUESTS)
def test_trial_slot_request(tmp_path, sampled, values, trial_id, expected) -> None:
    trial_ctx = forcing_context(tmp_path, parameter_space=sampled_space(**sampled))
    captured: list[SlotRequest | None] = []

    def metric(ctx, *, objective, variable):
        captured.append(ctx.setup.slot_request)
        return 0.0, {}

    run_trial_light(trial_ctx, values, metric_fn=metric, trial_id=trial_id)

    if expected is None:
        assert captured[0] is None
        return
    name, forcing = expected
    assert captured[0] == SlotRequest(name=name, shared_forcing_dir=tmp_path / "scratch" / forcing)


def config_with(tmp_path: Path, **flow: object) -> HydroModPyConfig:
    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        flow=FlowConfig(**flow),
    )


@needs_pipeline
def test_factor_reaches_fork(tmp_path) -> None:
    cfg = config_with(tmp_path, sinks_sources={"recharge": {"values": 2.0}})
    stub, _ = counting_steps_context(tmp_path, earliest=6)
    paths = {"recharge.factor": "flow.sinks_sources.recharge.factor"}
    base = replace(stub, base_cfg=cfg, override_paths=paths)

    forked = base.fork({"recharge.factor": 1.5}).ctx.cfg

    assert cfg.flow.sinks_sources.recharge.factor == 1.0
    frozen = HydroModPyConfig.model_validate(written_payload(forked))
    assert frozen.flow.sinks_sources.recharge.factor == 1.5
    # 2 mm/d x 1.5 = 3 mm/d, in m/s.
    assert Flow(frozen.flow).sinks_sources["recharge"].values == pytest.approx(3e-3 / 86400.0)
    assert _phase_samples_the_recharge(base)


# A K tensor trial: K22 and the angles travel the path K travels, and XT3D reads the
# arrays the build puts on the model.

TENSOR_TOML = """
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
def tensor_cfg(tmp_path_factory) -> HydroModPyConfig:
    path = tmp_path_factory.mktemp("k_tensor_trial") / "project.toml"
    path.write_text(TENSOR_TOML, encoding="utf-8")
    return HydroModPyConfig.from_toml(path)


def two_by_two_mesh() -> SolverMesh:
    return solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=2,
        top=np.full((2, 2), 30.0),
        botm=np.stack([np.full((2, 2), 20.0), np.zeros((2, 2))]),
    )


def forked_trial(cfg: HydroModPyConfig, tmp_path: Path, values: dict[str, float]) -> TrialContext:
    setup = SimpleNamespace(flow=None, transport=None, slot_request=None)
    ctx = SimpleNamespace(
        setup=setup,
        data_plan=None,
        bounds=None,
        loaded_data=SimpleNamespace(),
        execution=ExecutionRegistry(),
    )
    base = TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=0,
        downstream_steps=(),
        override_paths={},
        workspace=tmp_path,
        cfg_path=tmp_path / "project.toml",
        parameter_space=space_from_config(cfg.calibration),
    )
    return base.fork(values)


def built_model(trial: TrialContext, mesh: SolverMesh) -> SimpleNamespace:
    """The model attributes `run_pre_processing` sets before its XT3D decision."""
    ensure_flow(trial.ctx)
    mapped = resolve_flow_property_arrays(
        profiles=trial.ctx.setup.flow.parameters,
        domain=SimpleNamespace(zones={}),
        solver_mesh=mesh,
        required_properties=frozenset({"K"}),
        properties=MODFLOW6_PROPERTIES,
    )
    runtime = SimpleNamespace(mf6_enable_xt3d=None)
    model = SimpleNamespace(modflow_config=SimpleNamespace(runtime=runtime))
    model.hk = mapped["hk"]
    for name in K_TENSOR_NPF_NAMES:
        setattr(model, name, mapped.get(name))
    return model


def test_signed_angle_space(tensor_cfg) -> None:
    space = space_from_config(tensor_cfg.calibration)

    assert {param.name for param in space} == {"K22", "angle1", "angle2"}


def test_sample_reaches_every_cell(tensor_cfg, tmp_path: Path) -> None:
    trial = forked_trial(tensor_cfg, tmp_path, {"K22": 2e-6, "angle1": 45.0, "angle2": 12.0})

    model = built_model(trial, two_by_two_mesh())

    np.testing.assert_allclose(model.k22, 2e-6)
    np.testing.assert_allclose(model.angle1, 45.0)
    np.testing.assert_allclose(model.angle2, 12.0)
    # The fork left the base configuration alone.
    assert tensor_cfg.flow.param["K22"].field.value == pytest.approx(1e-5)


def test_base_tensor_xt3d_off(tensor_cfg, tmp_path: Path) -> None:
    model = built_model(forked_trial(tensor_cfg, tmp_path, {}), two_by_two_mesh())

    assert resolve_xt3d_decision(model, two_by_two_mesh()).enabled is False


# Promotion: a promoted run closes its attempt, completed once sealed, failed when
# it raises. The pipeline is stubbed down to a claim, a seal and the session facts.


@dataclass
class PromotedCfg:
    K: float = 1.0
    simulation: Any = field(default_factory=lambda: SimpleNamespace(name="toy", results=None))

    def model_copy(self, *, deep: bool = False) -> PromotedCfg:
        return copy.deepcopy(self)


def claim(state: PipelineState) -> None:
    ctx = state.get("ctx")
    run_dir = state.get("run_dir")
    claim_reserved_directory(
        run_dir, case_id=run_dir.name, project="project", sim_id=ctx.reserved_sim_id
    )
    (run_dir / INTERNAL_DIRNAME / "checkpoints").mkdir(parents=True, exist_ok=True)
    ctx.sim_id = ctx.reserved_sim_id


def seal(state: PipelineState) -> None:
    (state.get("run_dir") / RUN_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")


def solver_not_converging(state: PipelineState) -> None:
    raise RuntimeError("the solver did not converge")


def interrupt(state: PipelineState) -> None:
    raise KeyboardInterrupt


def promotion_context(tmp_path: Path, steps) -> TrialContext:
    cfg = PromotedCfg()
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
def fake_pipeline_installed(monkeypatch) -> None:
    monkeypatch.setattr(trial_module, "_PIPELINE", FakePipeline())


def make_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "calage"
    run_dir.mkdir(parents=True)
    return run_dir


@pytest.mark.usefixtures("fake_pipeline_installed")
def test_sealed_promotion(tmp_path) -> None:
    run_dir = make_run_dir(tmp_path)
    trial_ctx = promotion_context(
        tmp_path, [ActionStep("prepare_solver", claim), ActionStep("export", seal)]
    )

    promote_prepared_trial(trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32, run_dir=run_dir)

    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "completed"
    assert outcome.ended_at is not None
    assert not (run_dir / INTERNAL_DIRNAME).exists()


@pytest.mark.usefixtures("fake_pipeline_installed")
def test_raising_promotion(tmp_path) -> None:
    run_dir = make_run_dir(tmp_path)
    trial_ctx = promotion_context(
        tmp_path, [ActionStep("prepare_solver", claim), ActionStep("export", solver_not_converging)]
    )

    with pytest.raises(StepError, match="did not converge"):
        promote_prepared_trial(
            trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32, run_dir=run_dir
        )

    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.error is not None and "did not converge" in outcome.error.message
    assert not (run_dir / RUN_MANIFEST_FILENAME).exists()


@pytest.mark.usefixtures("fake_pipeline_installed")
def test_interrupted_promotion(tmp_path) -> None:
    run_dir = make_run_dir(tmp_path)
    trial_ctx = promotion_context(
        tmp_path, [ActionStep("prepare_solver", claim), ActionStep("export", interrupt)]
    )

    with pytest.raises(KeyboardInterrupt):
        promote_prepared_trial(
            trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32, run_dir=run_dir
        )

    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == "aborted"


@pytest.mark.usefixtures("fake_pipeline_installed")
def test_session_facts_in_state(tmp_path) -> None:
    run_dir = make_run_dir(tmp_path)
    seen: list[Any] = []
    trial_ctx = promotion_context(
        tmp_path,
        [
            ActionStep(
                "prepare_solver", lambda state: (seen.append(state.get("promotion")), claim(state))
            ),
            ActionStep("export", seal),
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


@pytest.mark.usefixtures("fake_pipeline_installed")
def test_other_sim_id_refused(tmp_path) -> None:
    def other_id(state: PipelineState) -> None:
        state.get("ctx").sim_id = "b" * 32

    trial_ctx = promotion_context(tmp_path, [ActionStep("export", other_id)])

    with pytest.raises(RuntimeError, match=f"took the id {'b' * 32} instead of the reserved"):
        promote_prepared_trial(trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32)


@pytest.mark.usefixtures("fake_pipeline_installed")
def test_unclosable_attempt_keeps_error(tmp_path, monkeypatch, caplog) -> None:
    def cannot_write(run_dir, **kwargs) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(trial_module, "finish_attempt", cannot_write)
    trial_ctx = promotion_context(
        tmp_path, [ActionStep("prepare_solver", claim), ActionStep("export", solver_not_converging)]
    )

    with pytest.raises(StepError, match="did not converge"):
        promote_prepared_trial(
            trial_ctx, {"K": 2.0}, name="calage", sim_id="a" * 32, run_dir=make_run_dir(tmp_path)
        )

    assert "Could not write the outcome of" in caplog.text


# Saved runs of a calibration: trials write nothing, `promote_session` writes the runs
# it names. The best one keeps the budget the project file asks for (all of it by
# default), the pipeline is stubbed to the real `step_configure_results` and a recorder.


@dataclass
class SavedCfg:
    K: float = 1.0
    simulation: Any = field(
        default_factory=lambda: SimpleNamespace(name="toy", results=ResultsConfig())
    )
    display: Any = field(default_factory=lambda: SimpleNamespace(enabled=False, figures=()))

    def model_copy(self, *, deep: bool = False) -> SavedCfg:
        return copy.deepcopy(self)


@dataclass
class SavedCtx:
    cfg: SavedCfg
    config_path: Path
    raw_toml: dict[str, Any]
    bounds: Any = None
    data_plan: Any = None
    setup: Setup = field(default_factory=Setup)
    loaded_data: Any = None
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)
    sim_id: Any = None
    reserved_sim_id: Any = None
    budget_terms: BudgetKeep | None = None


@pytest.fixture
def saved_session(tmp_path: Path, monkeypatch):
    """A trial context and the budget each promoted run decided to keep."""
    kept: dict[str, BudgetKeep] = {}

    def plan(state: PipelineState) -> None:
        ctx = state.get("ctx")
        ctx.budget_terms = step_configure_results(
            ctx.cfg.simulation.results,
            SimpleNamespace(runs=()),
            ctx.cfg.display,
            display_active=False,
            export_requests=(),
            calibration=None,
            observation=None,
            level=level_of(state.get("lineage")),
        )

    def export(state: PipelineState) -> None:
        ctx = state.get("ctx")
        run_dir = state.get("run_dir")
        label = (
            ctx.setup.run_id if run_dir is None or run_dir.parent.name == "runs" else run_dir.name
        )
        kept[label] = ctx.budget_terms
        ctx.sim_id = ctx.reserved_sim_id

    monkeypatch.setattr(trial_module, "_PIPELINE", FakePipeline())
    cfg = SavedCfg()
    ctx = SavedCtx(cfg=cfg, config_path=tmp_path / "calib.toml", raw_toml={})
    trial_ctx = TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=0,
        downstream_steps=(ActionStep("prepare_solver", plan), ActionStep("export", export)),
        override_paths={"K": "K"},
        workspace=tmp_path,
        cfg_path=tmp_path / "calib.toml",
        raw_toml={},
    )
    trial_ctx.kept_solves = None
    return trial_ctx, kept


def journaled_session(project: Path, rows: int, costs: dict[int, float]) -> CalibrationPersistence:
    """A journaled session of `rows` trials, trial `n` at parameter K = n."""
    journal = [{"cost": costs[index], "k": float(index)} for index in range(1, rows + 1)]
    return make_session(project, "best", costs=journal, project=project.name, bounds={})


def test_best_promoted_whole_budget(saved_session) -> None:
    trial_ctx, kept = saved_session
    project = trial_ctx.workspace / "project"
    rows, best_trial = 3, 2
    costs = {index: float(index) for index in range(1, rows + 1)}
    costs[best_trial] = 0.0

    outcome = promote_session(
        cfg=CalibrationConfig(),
        trial_ctx=trial_ctx,
        persistence=journaled_session(project, rows, costs),
        project_root=project,
        phase="main",
        session_status="completed",
        override_paths={"K": "K"},
    )

    assert (outcome.count, outcome.failures) == (1, [])
    assert list(kept) == ["best"]
    assert kept["best"] == BudgetKeep.everything()


# The trial pipeline is installed once by the project package, never by an import.


def test_pipeline_refused_until_installed(monkeypatch) -> None:
    monkeypatch.setattr(trial_module, "_PIPELINE", None)

    with pytest.raises(CalibrationError, match="fill_trial_pipeline"):
        trial_module.trial_pipeline()


def test_second_pipeline_refused(monkeypatch) -> None:
    # A run already reading the pipeline must never see it change (rule 15).
    monkeypatch.setattr(trial_module, "_PIPELINE", SimpleNamespace(name="first"))
    monkeypatch.setattr(trial_module, "_INITIALIZER", "mod:first")

    with pytest.raises(CalibrationError, match="different TrialPipeline"):
        trial_module.install_trial_pipeline(
            SimpleNamespace(name="second"), initializer="mod:second"
        )


def test_initializer_returned(monkeypatch) -> None:
    monkeypatch.setattr(trial_module, "_PIPELINE", None)
    monkeypatch.setattr(trial_module, "_INITIALIZER", None)

    trial_module.install_trial_pipeline(SimpleNamespace(), initializer="hydromodpy.mod:fill")

    assert trial_module.trial_pipeline_initializer() == "hydromodpy.mod:fill"


# A light trial moves property profiles only: it derives its Model from the prepared one
# and reruns its lane. Its steps stand in for prepare_solver and run_solver.

GEOMETRY = small_geometry()
TIME = ModelTime(grid=time_grid(10.0), regime="steady", first_period_steady=True)
OPTIONS = default_options()
K_PATH = "flow.param.K.field.value"


class _Cfg(BaseModel):
    flow: FlowConfig


def _base_cfg() -> _Cfg:
    return _Cfg(
        flow=FlowConfig.model_validate(
            {
                "param_list": ["K", "Sy"],
                "param": {
                    "K": {"field": {"id": "K", "kind": "homogeneous", "value": "1e-5 m/s"}},
                    "Sy": {"field": {"id": "Sy", "kind": "homogeneous", "value": "0.1 -"}},
                },
            }
        )
    )


class _Counted:
    """A step that counts its calls and runs ``action`` on the context."""

    def __init__(self, name: str, action: Any = None) -> None:
        self.name = name
        self.action = action
        self.calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.calls += 1
        if self.action is not None:
            self.action(state.get("ctx"))
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


def _build_model(ctx: Any) -> None:
    """What ``prepare_solver`` leaves on a light run: the plan, the budget policy, the Model."""
    ctx.execution.simulation_plan = SimpleNamespace(runs=(SimpleNamespace(id="flow"),))
    ctx.budget_terms = "kept terms"
    ctx.setup.model = model_from_flow(ctx.setup.flow, geometry=GEOMETRY, time=TIME, options=OPTIONS)


class _Launching(_Counted):
    """Stands in for ``RunSolverStep``: runs the plan through the launcher it is given."""

    def __init__(self, launcher: Any = None) -> None:
        super().__init__("run_solver")
        self.launcher = launcher

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if self.launcher is not None:
            self.launcher.execute(ctx.execution.simulation_plan, ctx)
        return super().run(state)


class _Pipeline(FakePipeline):
    """Counts the forcing bindings, builds the Flow they bind, and hands the launcher on."""

    def __init__(self) -> None:
        self.bindings = 0

    def apply_structural_updates_from_data(self, ctx) -> None:
        self.bindings += 1
        ctx.setup.flow = Flow(ctx.cfg.flow)

    def with_solver_launcher(self, steps, launcher):
        return tuple(_Launching(launcher) if step.name == "run_solver" else step for step in steps)


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> _Pipeline:
    installed = _Pipeline()
    monkeypatch.setattr(trial_module, "_PIPELINE", installed)
    return installed


def _steps() -> tuple[_Counted, ...]:
    return (
        _Counted("setup_process"),
        _Counted("prepare_solver", _build_model),
        _Launching(),
        _Counted("extract"),
    )


def _prepared(tmp_path: Path, *, paths: dict[str, str], earliest: int = 1) -> TrialContext:
    cfg = _base_cfg()
    setup = SimpleNamespace(
        run_id="calage",
        workspace=SimpleNamespace(solver_scratch_folder=tmp_path / "scratch"),
        domain=object(),
        flow=Flow(cfg.flow),
        model=None,
        slot_request=None,
    )
    ctx = SimpleNamespace(
        cfg=cfg,
        setup=setup,
        loaded_data=SimpleNamespace(recharge=None),
        data_plan=None,
        execution=SimpleNamespace(rng=None, simulation_plan=None),
        bounds=Bounds(),
        budget_terms=None,
    )
    return TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=earliest,
        downstream_steps=_steps(),
        override_paths=paths,
        workspace=tmp_path,
        cfg_path=tmp_path / "calib.toml",
    )


def _contents(model: Any) -> dict[str, Any]:
    return {name: profile.as_dict() for name, profile in model.properties.profiles.items()}


def test_fork_derives_the_model(tmp_path: Path, pipeline: _Pipeline) -> None:
    prepared = _with_the_model_built(_prepared(tmp_path, paths={"K": K_PATH}), pipeline)
    model = prepared.ctx.setup.model
    bindings = pipeline.bindings

    forks = [prepared.fork({"K": value}, derive_model=True) for value in (2e-5, 3e-5)]

    assert pipeline.bindings == bindings, "no forcing is bound again"
    assert prepared.downstream_steps[1].calls == 1, "prepare_solver is not played again"
    for fork, value in zip(forks, (2e-5, 3e-5), strict=True):
        derived = fork.ctx.setup.model
        built = model_from_flow(
            Flow(fork.ctx.cfg.flow), geometry=GEOMETRY, time=TIME, options=OPTIONS
        )
        assert _contents(derived) == _contents(built)
        assert derived.properties.profiles["K"].value == pytest.approx(value)
        assert derived.properties.profiles["Sy"] is model.properties.profiles["Sy"]
        assert derived.geometry is model.geometry and derived.time is model.time
        assert fork.ctx.setup.flow is None
        assert fork.ctx.execution.simulation_plan is prepared.ctx.execution.simulation_plan
        assert fork.ctx.budget_terms == "kept terms"
        assert fork.model_from_profiles and fork.parents is None


def test_promotion_fork_rebuilds_flow(tmp_path: Path, pipeline: _Pipeline) -> None:
    prepared = _with_the_model_built(_prepared(tmp_path, paths={"K": K_PATH}), pipeline)
    bindings = pipeline.bindings

    fork = prepared.fork({"K": 2e-5})

    assert pipeline.bindings == bindings + 1
    assert fork.ctx.setup.model is None
    assert fork.ctx.setup.flow.parameters["K"].value == pytest.approx(2e-5)


LIGHT_KEPT = [
    pytest.param({"f": "flow.sinks_sources.recharge.factor"}, 1, id="a recharge factor"),
    pytest.param(
        {"K": K_PATH, "f": "flow.sinks_sources.recharge.f"}, 1, id="a profile and a recharge factor"
    ),
    pytest.param({"Ss": "flow.param.Ss.field.value"}, 1, id="an id param_list does not declare"),
    pytest.param({"K": K_PATH}, 0, id="an earliest step before prepare_solver"),
]


@pytest.mark.parametrize(("paths", "earliest"), LIGHT_KEPT)
def test_other_paths_keep_full_fork(
    tmp_path: Path, pipeline: _Pipeline, paths: dict[str, str], earliest: int
) -> None:
    context = _prepared(tmp_path, paths=paths, earliest=earliest)
    prepared = _with_the_model_built(context, pipeline)

    assert prepared is context
    assert prepared.model_from_profiles is False
    assert prepared.downstream_steps[1].calls == 0
    fork = prepared.fork({}, derive_model=True)
    assert fork.ctx.setup.model is None
    assert pipeline.bindings == 1


class _Runner:
    """Stands in for ``SimulationRunner``: writes the input files and remembers its parents."""

    given: ClassVar[list[Any]] = []

    def execute(self, plan, state, *, callbacks=None, previous=None):
        del callbacks
        self.given.append(None if previous is None else dict(previous))
        slot = state.setup.slot_request
        folder = Path(state.setup.workspace.solver_scratch_folder) / slot.name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "model.npf").write_text("npf", encoding="utf-8")
        sim = SimpleNamespace(sim_path=os.fspath(folder))
        sim.set_sim_path = lambda path: setattr(sim, "sim_path", path)
        run = SolverRun(
            slot=RunSlot(folder.parent, folder.name),
            model=state.setup.model,
            solver_model=SimpleNamespace(sim=sim),
            output_dir=folder,
            input_files=("model.npf",),
            written=True,
            solved=True,
            solve_s=0.01,
            reran=previous is not None,
        )
        executed = []
        for planned in plan.runs:
            state.execution.solver_runs[planned.id] = run
            executed.append((planned, run))
        return tuple(executed)


def _cost(ctx, *, objective, variable):
    del objective, variable
    return float(ctx.setup.model.properties.profiles["K"].value) * 1e5, {}


def test_lane_parent_to_runner(
    tmp_path: Path, pipeline: _Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hydromodpy.solver.base.runner.SimulationRunner", _Runner)
    _Runner.given.clear()
    prepared = _with_the_model_built(_prepared(tmp_path, paths={"K": K_PATH}), pipeline)
    prepared.parents = TrialParents.of(prepared)

    first = run_trial_light(prepared, {"K": 2e-5}, metric_fn=_cost, trial_id=1)
    second = run_trial_light(prepared, {"K": 3e-5}, metric_fn=_cost, trial_id=2)

    assert (first.status, second.status) == ("completed", "completed")
    assert second.primary_metric == pytest.approx(3.0)
    assert _Runner.given[0] is None
    (parent,) = _Runner.given[1].values()
    lane = tmp_path / "scratch" / "calage_lane1" / "flow"
    assert parent.output_dir == lane
    assert (lane / "model.npf").is_file()
    assert not (tmp_path / "scratch" / "calage_trial000001").exists()
    assert [line.name for line in first.profile if line.kind == "step"] == ["run_solver", "extract"]


def test_failed_trial_empties_lane(
    tmp_path: Path, pipeline: _Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hydromodpy.solver.base.runner.SimulationRunner", _Runner)
    _Runner.given.clear()
    prepared = _with_the_model_built(_prepared(tmp_path, paths={"K": K_PATH}), pipeline)
    prepared.parents = TrialParents.of(prepared)

    def fails(ctx, *, objective, variable):
        raise RuntimeError("no record")

    run_trial_light(prepared, {"K": 2e-5}, metric_fn=_cost, trial_id=1)
    failed = run_trial_light(prepared, {"K": 3e-5}, metric_fn=fails, trial_id=2)
    run_trial_light(prepared, {"K": 4e-5}, metric_fn=_cost, trial_id=3)

    assert failed.status == "failed"
    assert _Runner.given[1] is not None
    assert _Runner.given[2] is None, "the parent of the failed trial was consumed"
