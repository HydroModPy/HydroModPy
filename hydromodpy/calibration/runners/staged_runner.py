"""Calibration run in phases: each stage calibrates, then freezes.

A staged calibration runs the phases of ``[[calibration.phases]]`` in
declaration order. Each phase is an ordinary mono-phase calibration: it gets
its own configuration, its own optimizer, its own session, and goes through
:func:`hydromodpy.calibration.runners.cli_runner.run_calibration_core` like
any other. What staging adds is what happens between two phases.

Freezing
--------
A phase that declares ``freeze_on_success`` and converges hands the
parameters it calibrated to the phases after it, as fixed values. A frozen
parameter leaves the search: it is written once into the baseline
configuration every trial of the next phase forks from, and its declaration
is dropped from that phase's parameter space. Keeping it in the space with
equal bounds would make a grid sampler spend points on a degenerate axis and
would break the one-dimensional guard of the bisection adapter.

Chaining
--------
The phases write one session each. Phase 0 is the root of the chain and has
no parent; every later phase records the previous one as its parent and phase
0 as its root. The four values travel through :class:`SessionChain` into
``session.json``, so ``hmp catalog reindex`` gives the chain back.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from hydromodpy.calibration.config import CalibPhaseDecl, CalibrationConfig
from hydromodpy.calibration.optim.optimizer import FAILED_EVAL_COST
from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    ParameterSpace,
    apply_parameter_to_config,
)
from hydromodpy.calibration.runners.cli_runner import (
    load_toml_calibration,
    run_calibration_core,
)
from hydromodpy.calibration.runners.state import (
    CalibrationStoreFactory,
    SessionChain,
    space_from_config,
)
from hydromodpy.calibration.runners.state import (
    override_paths as resolve_override_paths,
)
from hydromodpy.calibration.runners.trial import TrialMetricFn, prepare_trials
from hydromodpy.core.exceptions import CalibrationError, ConfigValidationError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.calibration.runners.trial import TrialContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrozenParameter:
    """One parameter a phase calibrated and held fixed for the phases after it.

    The declaration is the one the parent configuration carries, so the dotted
    path and the mode (``replace`` / ``scale``) are honoured exactly as during
    the phase that calibrated the value.
    """

    parameter: CalibParameter
    value: float
    phase: str

    @property
    def name(self) -> str:
        """Calibration name of the frozen parameter."""
        return self.parameter.name

    @property
    def path(self) -> str | None:
        """Dotted path in the configuration the value is written to."""
        return self.parameter.effective_path

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly view of the frozen value."""
        return {
            "name": self.name,
            "path": self.path,
            "value": float(self.value),
            "mode": self.parameter.mode,
            "phase": self.phase,
        }


@dataclass(frozen=True, slots=True)
class PhaseRun:
    """One phase of a staged calibration: its session, its report, its freeze."""

    name: str
    index: int
    session_id: str
    root_session_id: str
    parent_session_id: str | None
    report: CalibrationReport
    frozen: tuple[FrozenParameter, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly view of the phase, report included."""
        return {
            "phase": self.name,
            "index": self.index,
            "session_id": self.session_id,
            "root_session_id": self.root_session_id,
            "parent_session_id": self.parent_session_id,
            "frozen": [item.to_dict() for item in self.frozen],
            "report": self.report.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class StagedCalibrationReport:
    """Outcome of a calibration run in phases.

    ``phases`` keeps the runs in the order they ran and ``frozen`` gathers,
    in the same order, every value a converged phase declared frozen, with
    the path it is written to.
    """

    phases: tuple[PhaseRun, ...]
    frozen: tuple[FrozenParameter, ...]
    root_session_id: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly summary for the CLI."""
        return {
            "root_session_id": self.root_session_id,
            "phases": [phase.to_dict() for phase in self.phases],
            "frozen": [item.to_dict() for item in self.frozen],
        }


# ---------------------------------------------------------------------------
# Phase configuration
# ---------------------------------------------------------------------------


def _phase_config(cfg: CalibrationConfig, decl: CalibPhaseDecl) -> CalibrationConfig:
    """Return the mono-phase configuration one phase runs under.

    The phase carries its own search (method, budget, parameters) and selects
    by name from what the calibration declares. An empty selection of outputs
    or of objective blocks means every declared one. A phase declaring its own
    ``variable`` or ``objective`` takes the single-metric route instead, and
    inherits neither. ``phases`` is cleared so the sub-run is an ordinary
    calibration.
    """
    payload = cfg.model_dump()
    payload["method"] = decl.method
    payload["max_iter"] = decl.max_iter
    payload["batch_size"] = decl.batch_size
    payload["parallel"] = decl.parallel
    payload["optimizer_kwargs"] = dict(decl.optimizer_kwargs)
    if decl.variable is not None:
        payload["variable"] = decl.variable
    if decl.objective is not None:
        payload["objective"] = decl.objective
    if decl.scoring_window is not None:
        payload["scoring_window"] = decl.scoring_window.model_dump()
    payload["parameters"] = {name: payload["parameters"][name] for name in decl.parameters}
    if decl.is_single_metric:
        # The extractor prefers blocks over the variable whenever both are
        # present, so a phase inheriting the blocks of another one would be
        # scored on that other criterion without saying so.
        payload["outputs"] = {}
        payload["objective_blocks"] = []
    else:
        if decl.outputs:
            payload["outputs"] = {name: payload["outputs"][name] for name in decl.outputs}
        if decl.objective_blocks:
            selected = set(decl.objective_blocks)
            payload["objective_blocks"] = [
                block for block in payload["objective_blocks"] if block["name"] in selected
            ]
    payload["phases"] = None
    try:
        return CalibrationConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigValidationError(
            f"phase {decl.name!r} does not describe a runnable calibration: {exc}"
        ) from exc


def _injected_paths(
    phase_cfg: CalibrationConfig,
    frozen: list[FrozenParameter],
) -> dict[str, str]:
    """Return the config paths the trial pipeline must treat as varying.

    The phase's own parameters, plus the frozen ones: a preparation step that
    reads a frozen path has to re-run per trial, otherwise the prepared prefix
    would keep the value the TOML declared and the freeze would never reach
    the solver.
    """
    paths = resolve_override_paths(phase_cfg)
    for item in frozen:
        if item.path is not None:
            paths[item.name] = item.path
    return paths


# ---------------------------------------------------------------------------
# Freezing
# ---------------------------------------------------------------------------


def _freeze_into_baseline(trial_ctx: TrialContext, frozen: list[FrozenParameter]) -> None:
    """Write the frozen values into the baseline the phase forks from.

    ``TrialContext.fork`` starts every trial from a deep copy of ``base_cfg``
    and then writes the sampled values in, so a value written here reaches
    every trial of the phase without ever entering its search. The write goes
    through the same helper the fork uses, on a baseline freshly loaded from
    the TOML, so ``mode="scale"`` multiplies the declared value once and
    exactly as the phase that calibrated it did.
    """
    for item in frozen:
        apply_parameter_to_config(trial_ctx.base_cfg, item.parameter, item.value)


def _converged(report: CalibrationReport) -> bool:
    """Whether a phase produced a candidate the next phases can build on.

    Convergence, not quality: a coarse agreement still returns a number. What
    disqualifies a phase is having no best candidate at all, or a best cost
    that is the failed-evaluation sentinel.
    """
    if report.best_parameters is None or report.best_objective is None:
        return False
    return math.isfinite(report.best_objective) and report.best_objective < FAILED_EVAL_COST


def _frozen_by(
    decl: CalibPhaseDecl,
    report: CalibrationReport,
    declared: ParameterSpace,
) -> tuple[FrozenParameter, ...]:
    """Return what this phase hands to the phases that depend on it."""
    if not decl.freeze_on_success:
        return ()
    if not _converged(report):
        logger.warning(
            "Phase %s did not converge; its parameters stay free for the next phases.",
            decl.name,
        )
        return ()
    values = report.best_parameters or {}
    missing = [name for name in decl.parameters if name not in values]
    if missing:
        raise CalibrationError(
            f"phase {decl.name!r} converged but its best candidate carries no value for "
            f"{missing}; there is nothing to freeze for the phases that depend on it."
        )
    return tuple(
        FrozenParameter(parameter=declared[name], value=float(values[name]), phase=decl.name)
        for name in decl.parameters
    )


# ---------------------------------------------------------------------------
# Phase selection
# ---------------------------------------------------------------------------


def _phases_to_run(
    cfg: CalibrationConfig,
    phase: str | None,
) -> list[tuple[int, CalibPhaseDecl]]:
    """Return the declared phases to run, in declaration order."""
    declared = cfg.phases or []
    if not declared:
        raise CalibrationError(
            "the calibration declares no [[calibration.phases]]; run it through "
            "run_calibration_cli instead."
        )
    ordered = list(enumerate(declared))
    if phase is None:
        return ordered
    selected = [item for item in ordered if item[1].name == phase]
    if not selected:
        raise CalibrationError(
            f"unknown phase {phase!r}; the calibration declares {[item.name for item in declared]}."
        )
    return selected


def _require_dependency(decl: CalibPhaseDecl, ran: set[str]) -> None:
    """Refuse a phase whose dependency did not run in this invocation.

    A dependent phase is written against the values its dependency freezes.
    Running it without them would not fail: it would calibrate against the
    baseline the TOML declares, which is a different calibration than the one
    asked for, and nothing in the result would say so.
    """
    if decl.depends_on is None or decl.depends_on in ran:
        return
    raise CalibrationError(
        f"phase {decl.name!r} depends on {decl.depends_on!r}, which did not run in this "
        f"invocation, so the values {decl.depends_on!r} freezes are missing. Running "
        f"{decl.name!r} alone would calibrate it against un-frozen parameters. Run the "
        "staged calibration without selecting a single phase."
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_staged_calibration(
    config_path: Path | str,
    *,
    phase: str | None = None,
    objective: str | None = None,
    workspace: Path | str | None = None,
    project: str = "calibration",
    metric_fn: TrialMetricFn | None = None,
    store_factory: CalibrationStoreFactory | None = None,
) -> StagedCalibrationReport:
    """Run the phases of ``config_path`` one after the other.

    Parameters
    ----------
    config_path
        Path to a TOML declaring ``[calibration]`` with a ``phases`` table.
    phase
        Run only the phase of that name. It still needs the values its
        dependency freezes, so a phase whose dependency did not run in the
        same invocation is refused.
    objective
        Escape hatch ``"module.path:callable"`` selecting the metric
        extractor, forwarded to every phase.
    workspace
        Override the project catalog root, otherwise resolved from the TOML.
    project
        Project label written to ``calibration_sessions.project``.
    metric_fn
        Programmatic override for the metric extractor.
    store_factory
        Override for the calibration store, forwarded to every phase.
    """
    cfg_path = Path(config_path).expanduser().resolve()
    cfg, _raw = load_toml_calibration(cfg_path)
    selected = _phases_to_run(cfg, phase)
    declared = space_from_config(cfg)

    frozen: list[FrozenParameter] = []
    runs: list[PhaseRun] = []
    ran: set[str] = set()
    parent_session_id: str | None = None
    root_session_id: str | None = None

    for index, decl in selected:
        _require_dependency(decl, ran)
        phase_cfg = _phase_config(cfg, decl)
        space = space_from_config(phase_cfg)
        trial_ctx = prepare_trials(
            cfg_path,
            override_paths=_injected_paths(phase_cfg, frozen),
            parameter_space=space,
        )
        _freeze_into_baseline(trial_ctx, frozen)

        session_id = uuid.uuid4().hex
        if root_session_id is None:
            root_session_id = session_id
        chain = SessionChain(
            session_id=session_id,
            root_session_id=root_session_id,
            phase_name=decl.name,
            phase_index=index,
            parent_session_id=parent_session_id,
        )
        if workspace is not None:
            ws_root = Path(workspace).expanduser().resolve()
        else:
            ws_root = trial_ctx.workspace

        logger.info(
            "Calibration phase %d/%d %s | method=%s parameters=%s",
            index + 1,
            len(cfg.phases or []),
            decl.name,
            decl.method,
            list(decl.parameters),
        )
        report = run_calibration_core(
            phase_cfg,
            trial_ctx,
            workspace=ws_root,
            space=space,
            project_label=project,
            cfg_path=cfg_path,
            metric_fn=metric_fn,
            objective=objective,
            store_factory=store_factory,
            chain=chain,
        )

        froze = _frozen_by(decl, report, declared)
        frozen.extend(froze)
        runs.append(
            PhaseRun(
                name=decl.name,
                index=index,
                session_id=session_id,
                root_session_id=root_session_id,
                parent_session_id=parent_session_id,
                report=report,
                frozen=froze,
            )
        )
        parent_session_id = session_id
        ran.add(decl.name)

    return StagedCalibrationReport(
        phases=tuple(runs),
        frozen=tuple(frozen),
        root_session_id=str(root_session_id),
    )


__all__ = [
    "FrozenParameter",
    "PhaseRun",
    "StagedCalibrationReport",
    "run_staged_calibration",
]
