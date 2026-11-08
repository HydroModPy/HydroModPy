"""Factories of the runner tests: a fake pipeline, a fake phase runner, sessions, reports, documents."""

from __future__ import annotations

import json
import math
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import params_hash
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import promotion, search, staged_runner
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.core.runtime.interrupts import TerminationRequested
from hydromodpy.core.state.run_state import ExecutionRegistry
from tests._helpers.persisting_simulation import SimulationStub, persisting_simulation
from tests._helpers.session_documents import session_opening
from tests.unit.calibration._factories import Setup
from tests.unit.calibration._factories_search import result_of

K_TOML = 1e-5
SY_TOML = 0.1
K_CALIBRATED = 2.5e-5
SY_CALIBRATED = 0.07


def write_document(tmp_path: Path, text: str, name: str = "calibration.toml") -> Path:
    """Write *text* as a UTF-8 file under *tmp_path* and return its path."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def make_report(**fields: Any) -> CalibrationReport:
    """Return a report of a one-trial grid search, with *fields* set over the defaults."""
    base = {
        "session_id": "abc",
        "method": "grid",
        "n_trials": 1,
        "best_cost": 0.1,
        "duration_s": 0.0,
        "save_runs": "none",
        "promoted": 0,
    }
    return CalibrationReport(**{**base, **fields})


def bare_trial_ctx() -> TrialContext:
    """A trial context that prepared nothing, for code that reads only ``ctx`` and ``kept_solves``."""
    return TrialContext(None, None, 0, (), {}, Path("."), Path("."))


def journal_trial(
    persistence: CalibrationPersistence,
    trial_id: int,
    cost: float = 0.1,
    *,
    k: float = 1e-4,
    phase=None,
    detail: str = "summary",
    values: dict | None = None,
    **fields: Any,
):
    """Append one completed trial on K (or on *values*) to the journal and return its line."""
    suggestion = ParamSuggestion(trial_id=trial_id, values={"K": k} if values is None else values)
    return persistence.append_iteration(
        suggestion,
        result_of(suggestion, cost, **fields),
        phase=phase,
        detail=detail,
    )


def make_session(
    tmp_path: Path, name: str = "calage", *, costs: tuple = (), **opening: Any
) -> CalibrationPersistence:
    """Open a session under ``tmp_path/sessions/<name>`` and journal one trial per cost.

    A cost may be a number or a dict of the keywords of ``journal_trial``, ``cost`` included.
    """
    session_dir = tmp_path / "sessions" / name
    session_dir.mkdir(parents=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(**session_opening(name, **opening))
    for trial_id, cost in enumerate(costs, start=1):
        journal_trial(persistence, trial_id, **(cost if isinstance(cost, dict) else {"cost": cost}))
    return persistence


class _Leaf(BaseModel):
    value: float = 1e-4


class _Field(BaseModel):
    field: _Leaf = _Leaf()


class _Param(BaseModel):
    K: _Field = _Field()


class _Flow(BaseModel):
    param: _Param = _Param()


class _Cfg(BaseModel):
    flow: _Flow = _Flow()
    simulation: SimulationStub = SimulationStub()
    site: None = None


@dataclass
class ToyCtx:
    """The pipeline context of a toy trial: a config, a setup and an execution registry."""

    cfg: Any
    config_path: Path
    raw_toml: dict[str, Any]
    data_plan: Any = None
    setup: Setup = field(default_factory=Setup)
    loaded_data: Any = None
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)
    sim_id: Any = None
    reserved_sim_id: Any = None


class FakeCtx:
    def __init__(self, cfg, config_path: Path, raw_toml: dict, tmp_path: Path) -> None:
        workspace = SimpleNamespace(root=tmp_path / "ws", project_root=tmp_path)
        self.cfg = cfg
        self.config_path = config_path
        self.raw_toml = raw_toml
        self.setup = SimpleNamespace(
            workspace=workspace, flow=None, transport=None, slot_request=None
        )
        self.loaded_data = SimpleNamespace()
        self.data_plan = None
        self.execution = ExecutionRegistry()
        self.store = None


@pytest.fixture
def fake_pipeline(monkeypatch, tmp_path):
    """Fake ``prepare_trials`` and ``promote_prepared_trial`` so a calibration runs in seconds.

    The fixture is the list of the promotions, one dict each. A metric function is injected by
    the test, so the closed-form cost of ``quadratic_metric`` stands for a model run.
    """
    promoted: list[dict] = []

    def prepare(cfg_path, *, override_paths, steps=None, parameter_space=None):
        raw = tomllib.loads(Path(cfg_path).read_text(encoding="utf-8"))
        cfg = _Cfg()
        paths = (
            dict(override_paths)
            if isinstance(override_paths, dict)
            else {p: p for p in override_paths}
        )
        return TrialContext(
            base_cfg=cfg,
            ctx=FakeCtx(cfg, cfg_path, raw, tmp_path),
            earliest=9,  # never run downstream, the metric function ignores the context
            downstream_steps=(),
            override_paths=paths,
            workspace=tmp_path,
            cfg_path=cfg_path,
            raw_toml=raw,
        )

    def promote(trial_ctx, values, *, name=None, sim_id=None, run_dir=None, **kwargs):
        sim_id = sim_id or uuid.uuid4().hex
        promoted.append(
            {
                "sim_id": sim_id,
                "values": dict(values),
                "name": name,
                "run_dir": run_dir,
                "lineage": kwargs.get("lineage"),
                "calibrated_by": kwargs.get("calibrated_by"),
            }
        )
        return sim_id

    monkeypatch.setattr(search, "prepare_trials", prepare)
    monkeypatch.setattr(promotion, "promote_prepared_trial", promote)
    return promoted


@pytest.fixture
def quadratic_metric():
    """Toy metric whose minimum is at K = 1e-4, the log midpoint of [1e-6, 1e-3]."""

    def metric_fn(ctx, *, objective, variable):
        cost = (math.log10(ctx.cfg.flow.param.K.field.value) - math.log10(1e-4)) ** 2
        return cost, {"nse@outlet": cost}

    return metric_fn


class FakeRunner:
    """Stands in for the preparation and the calibration loop of one phase.

    With ``journal`` it writes one trial per phase into the session and carries the search
    verdict in the report, as a search that ran. ``cut_at`` names a phase that is cut by SIGTERM
    after its trial. ``per_phase`` gives the values each phase returns, whatever it lists.
    ``patch`` points the staged and the CLI runners at this object.
    """

    def __init__(self, *, best_cost: float | None = 0.25, journal: bool = False) -> None:
        self.best_cost = best_cost
        self.journal = journal
        self.values = {"K": K_CALIBRATED, "Sy": SY_CALIBRATED}
        self.marker = "v1"
        self.cut_at: str | None = None
        self.per_phase: dict[str, dict[str, float]] | None = None
        self.prepared: list[dict[str, str]] = []
        self.overridden: list[dict[str, object]] = []
        self.calls: list[SimpleNamespace] = []

    @property
    def phases_run(self) -> list[str]:
        return [call.phase.name for call in self.calls]

    def patch(self, monkeypatch, *, marker: str | None = None) -> None:
        """Fake the solver; with *marker*, fake the fingerprint's raw material too."""
        monkeypatch.setattr(staged_runner, "prepare_trials", self.prepare_trials)
        monkeypatch.setattr(search, "run_calibration_core", self.run_calibration_core)
        if marker is not None:
            self.marker = marker
            monkeypatch.setattr(
                staged_runner, "build_cache_context", lambda **kwargs: {"marker": marker}
            )

    def prepare_trials(
        self, cfg_path, *, override_paths, steps=None, parameter_space=None, config_overrides=None
    ) -> TrialContext:
        self.prepared.append(dict(override_paths))
        self.overridden.append(dict(config_overrides or {}))
        baseline = SimpleNamespace(
            simulation=persisting_simulation(),
            flow=SimpleNamespace(
                active_bc=[],
                param=SimpleNamespace(
                    K=SimpleNamespace(field=SimpleNamespace(value=K_TOML)),
                    Sy=SimpleNamespace(field=SimpleNamespace(value=SY_TOML)),
                ),
            ),
        )
        for dotted, value in (config_overrides or {}).items():
            set_by_path(baseline, str(dotted), value)
        return TrialContext(
            base_cfg=baseline,
            ctx=None,
            earliest=0,
            downstream_steps=(),
            override_paths=dict(override_paths),
            workspace=cfg_path.parent,
            cfg_path=cfg_path,
            parameter_space=parameter_space,
        )

    def run_calibration_core(
        self,
        cfg,
        trial_ctx,
        *,
        persistence,
        space,
        project_root,
        cfg_path=None,
        metric_fn=None,
        objective=None,
        phase=None,
        start_at=None,
        interval_width=None,
        pool_for=None,
    ) -> CalibrationReport:
        self.calls.append(
            SimpleNamespace(
                cfg=cfg,
                trial_ctx=trial_ctx,
                baseline=trial_ctx.base_cfg,
                space=space,
                workspace=project_root,
                phase=phase,
                session_id=persistence.descriptor.session_id,
                session_dir=persistence.directory,
                start_at=start_at,
                seed=cfg.seed,
                interval_width=interval_width,
            )
        )
        best = (
            self.per_phase[phase.name]
            if self.per_phase
            else {name: self.values[name] for name in cfg.parameters}
        )
        extra = {
            "search_status": "completed" if self.best_cost is not None else "failed",
            "search": {"stop_state": "rule_met", "converged": True, "stopping_rule": "xatol"},
        }
        best_trial = None
        if self.journal:
            line = journal_trial(
                persistence,
                1,
                self.best_cost,
                values=best,
                phase=phase,
                metadata={"params_hash": params_hash(best, context={"marker": self.marker})},
            )
            if phase is not None and phase.name == self.cut_at:
                raise TerminationRequested("signal 15")
            best_trial = line.trial
        return CalibrationReport(
            session_id=persistence.descriptor.session_id,
            method=cfg.method,
            n_trials=cfg.max_trials,
            best_cost=self.best_cost,
            best_trial=best_trial,
            duration_s=1.0,
            save_runs=cfg.save_runs,
            promoted=0,
            best_parameters=None if self.best_cost is None else best,
            workspace=project_root,
            session_dir=persistence.directory,
            extra=extra,
        )


def make_config(**sections: Any) -> CalibrationConfig:
    """Return a calibration of K on its field path, with *sections* set over the defaults."""
    parameters = {"K": {"bounds": [1e-8, 1e-2], "path": "flow.param.K.field.value"}}
    return CalibrationConfig.model_validate({"parameters": parameters} | sections)


def toml_value(value: Any) -> str:
    """Write a string, a number, a boolean, a list or an inline table as TOML."""
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{key} = {toml_value(item)}" for key, item in value.items()) + " }"
    return json.dumps(value)


def phases_toml(*phases: dict[str, Any]) -> str:
    """Write the ``[[calibration.phases]]`` tables, one per dict. A key set to None is left out."""
    return "".join(
        "\n[[calibration.phases]]\n"
        + "".join(
            f"{key} = {toml_value(item)}\n" for key, item in phase.items() if item is not None
        )
        for phase in phases
    )


Q_OUTPUT = """
[calibration.outputs.q]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observed_values = [1.0, 2.0]
"""

Q_BLOCK = """
[[calibration.objective_blocks]]
name = "q_block"
metric = "rmse"
uses_outputs = ["q"]
"""


def calibration_head(
    top: str = 'method = "grid"\nmax_trials = 4',
    *,
    log_k: bool = True,
    outputs: str = Q_OUTPUT + Q_BLOCK,
) -> str:
    """Write ``[calibration]``, the parameters K and Sy, then *outputs* (the q output and its block).

    The tests append their ``[[calibration.phases]]`` tables, see :func:`phases_toml`.
    """
    k_space = 'search_space = "log"\n' if log_k else ""
    return (
        f"\n[calibration]\n{top}\n"
        f"\n[calibration.parameters.K]\nbounds = [1e-9, 1e-3]\n{k_space}"
        'target = "flow.param.K.field.value"\n'
        '\n[calibration.parameters.Sy]\nbounds = [0.001, 0.3]\ntarget = "flow.param.Sy.field.value"\n'
        + outputs
    )


STEADY_K = {
    "name": "steady_k",
    "method": "bisection",
    "max_trials": 12,
    "parameters": ["K"],
    "objective_blocks": ["q_block"],
}
TRANSIENT_SY = {
    "name": "transient_sy",
    "method": "grid",
    "max_trials": 30,
    "parameters": ["Sy"],
    "objective_blocks": ["q_block"],
    "depends_on": "steady_k",
}

STAGED_OUTPUTS = """
[calibration.outputs.q]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observes = "Q_STATION"

[calibration.outputs.h]
variable = "head"
support = "point"
x = 100.0
y = 0.0
observes = "H_STATION"

# One cost in m3/s and one in meters: both are normalized, because a sum of
# two units would let their magnitudes set the weighting.
[[calibration.objective_blocks]]
name = "q_block"
metric = "rmse"
uses_outputs = ["q"]
normalize_cost = true

[[calibration.objective_blocks]]
name = "h_block"
metric = "rmse"
uses_outputs = ["h"]
normalize_cost = true
"""
STAGED_HEAD = calibration_head(outputs=STAGED_OUTPUTS)

H_SY = {**TRANSIENT_SY, "objective_blocks": ["h_block"]}
TWO_PHASES = phases_toml({**STEADY_K, "outputs": ["q"]}, H_SY)
