"""Trial primitive - "prepare once, evaluate many".

The calibration loop needs a cheap inner step that lets the optimizer
evaluate hundreds of parameter combinations without re-running the
expensive setup phases (geographic, mesh, data loading) every time.

Three public entry points:

- :func:`prepare_trials` - load the TOML, compute which pipeline steps
  are affected by the calibration overrides, and run the shared prefix
  (steps ``[0..earliest)``) exactly once. Returns a
  :class:`TrialContext` that downstream trials fork from.
- :func:`run_trial_light` - fork the trial context, inject one
  parameter sample, run steps ``[earliest..8]`` with
  ``execution.lightweight = True`` so no Zarr / Parquet / provenance
  artifacts are written, extract the objective in RAM, and return a
  :class:`TrialResult`.
- :func:`promote_prepared_trial` - run the persistent downstream pipeline
  from the prepared context, writing the run of one trial into the
  directory the promotion reserved, without repeating setup work. Given
  the solve a trial kept, it reads that solve instead of solving again.

The storage contract is strict: ``run_trial_light`` never writes to the
store. Only promotion creates run artifacts. A trial the session may
promote leaves its solver folder in the run scratch
(:mod:`~hydromodpy.calibration.runners.kept_solves`).

A fork shares the prepared soil reservoir outputs and their input digests
on ``setup`` by reference, so a trial that leaves the soil parameters
alone reuses the soil in memory. The soil kernel and its digests run once,
at the data step, and a trial recomputes them only when it moves a soil
parameter.

Workflow access goes through :func:`trial_pipeline` so the
calibration package never imports the workflow or the configuration
package directly. The :class:`TrialPipeline` protocol carries the eight
calls a trial needs, six into the workflow layer and two loaders
(:meth:`~TrialPipeline.load_config`, :meth:`~TrialPipeline.load_document`)
that are the only path from calibration to a configuration file. The
pipeline is installed once by :func:`install_trial_pipeline`, called from
``hydromodpy.project`` only; a worker process of a parallel search receives
the dotted path of that installer through :func:`trial_pipeline_initializer`
and runs it itself.
"""

from __future__ import annotations

import copy as _copy
import math
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.calibration.runners.failure_watch import INFEASIBLE_PREFIX
from hydromodpy.calibration.runners.kept_solves import (
    KeptSolve,
    KeptSolveLauncher,
    RecordingLauncher,
    TrialSolveRetention,
)
from hydromodpy.calibration.runners.sandbox import sandbox_of
from hydromodpy.calibration.runners.verdict import water_budget_verdict
from hydromodpy.catchment.algorithms.river_network_config import river_network_for_the_mesh
from hydromodpy.core.console import progress
from hydromodpy.core.exceptions import CalibrationError, ConfigValidationError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.run_state import ExecutionRegistry, SlotRequest
from hydromodpy.core.units.physical_bounds import PHYSICAL_BOUNDS, PhysicalBoundsError
from hydromodpy.model.domain.spatial_support import (
    build_default_spatial_support_provider_registry,
    collect_requested_support_ids,
    resolve_support_configs,
)
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import close_sealed_attempt, finish_attempt
from hydromodpy.solver.base.plan import WATER_BUDGET_METRIC, WATER_BUDGET_WORST_METRIC

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.checks import CalibratedBy
    from hydromodpy.results.lineage import Lineage
    from hydromodpy.results.storage.run_facts import PromotionFacts


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Trial pipeline contracts
# ---------------------------------------------------------------------------


@runtime_checkable
class TrialStep(Protocol):
    """Minimal pipeline step contract used by the trial primitive."""

    name: str

    def run(self, state_in: Any) -> Any:
        """Execute the step and return the next state."""


@runtime_checkable
class TrialPipelineRunner(Protocol):
    """Minimal pipeline runner contract used by the trial primitive."""

    def run(self, state: Any) -> Any:
        """Execute every step over ``state`` and return the final state."""


@runtime_checkable
class TrialPipeline(Protocol):
    """Pipeline and configuration primitives needed by calibration trials."""

    def standard_steps(self) -> Sequence[TrialStep]:
        """Return the canonical ordered pipeline steps."""

    def earliest_affected_step(
        self,
        override_paths: Iterable[str],
        steps: Sequence[TrialStep],
    ) -> int:
        """Return the lowest step index affected by any override path."""

    def make_pipeline(
        self,
        steps: Sequence[TrialStep],
        *,
        run_dir: Path | None = None,
    ) -> TrialPipelineRunner:
        """Build a pipeline runner over the given steps."""

    def with_solver_launcher(
        self,
        steps: Sequence[TrialStep],
        launcher: Any,
    ) -> tuple[TrialStep, ...]:
        """Return ``steps`` with the run-solver step driven by ``launcher``."""

    def make_state(self, run_id: str, data: Mapping[str, Any]) -> Any:
        """Build a fresh pipeline state from ``run_id`` and an initial data mapping."""

    def apply_structural_updates_from_data(self, ctx: Any) -> None:
        """Bind freshly loaded data objects to runtime structures on ``ctx``."""

    def load_config(self, path: Path | str) -> BaseModel:
        """Load and validate the root project configuration from a TOML file."""

    def load_document(self, path: Path | str) -> dict[str, Any]:
        """Load the merged TOML document with base_config resolved."""

    def session_key(self, cfg: BaseModel) -> str | None:
        """Return the solution key of the case *cfg* describes, its search kept.

        The key a session seals and a plan compares: the request of the case with the
        digests of its inputs, then the code, the solver binaries and the numeric
        packages. ``None`` when the case cannot be told.
        """


_PIPELINE: TrialPipeline | None = None
_INITIALIZER: str | None = None


def install_trial_pipeline(pipeline: TrialPipeline, *, initializer: str) -> None:
    """Register the global pipeline provider used by calibration trials.

    Only ``hydromodpy.project`` may call this function. A second call with an
    equal pipeline is a no-op; a different pipeline raises CalibrationError.
    """
    global _PIPELINE, _INITIALIZER
    if _PIPELINE is not None:
        if _PIPELINE == pipeline:
            return
        raise CalibrationError("A different TrialPipeline is already installed.")
    _PIPELINE = pipeline
    _INITIALIZER = initializer


def trial_pipeline() -> TrialPipeline:
    """Return the installed trial pipeline, or raise if none was wired."""
    if _PIPELINE is None:
        raise CalibrationError(
            "TrialPipeline is not installed. Call "
            "hydromodpy.project.trial_pipeline.fill_trial_pipeline() "
            "before running calibration trials."
        )
    return _PIPELINE


def trial_pipeline_initializer() -> str | None:
    """Return the module:function path of the initializer, or None."""
    return _INITIALIZER


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrialResult:
    """Outcome of a single lightweight trial.

    ``primary_metric`` is the scalar used by the optimizer (lower is
    better by convention: the blocks already flip higher-is-better metrics
    like NSE/KGE into costs). ``metrics`` holds the per-component
    breakdown. When ``status != "completed"``, ``primary_metric`` is
    ``nan`` and ``error`` carries the exception string. That string starts
    with ``INFEASIBLE_PREFIX`` when the candidate puts a quantity the search
    moves outside its physical range, see :func:`_failure_text`.
    """

    values: Mapping[str, float]
    metrics: Mapping[str, float]
    primary_metric: float
    status: Literal["completed", "failed", "crashed"]
    duration_s: float
    error: str | None = None


# ---------------------------------------------------------------------------
# TrialContext
# ---------------------------------------------------------------------------


@dataclass
class TrialContext:
    """Prepared runtime state that a calibration loop forks from.

    Fields marked *shared* are referenced (not copied) by every fork;
    fields marked *per-trial* are freshly populated on every
    :meth:`fork` call.

    Attributes
    ----------
    base_cfg : HydroModPyConfig
        Immutable config produced by :class:`ValidateStep`. Every fork
        deep-copies this before injecting values. *Shared*.
    ctx : WorkflowContext
        Prepared workflow context. ``ctx.setup`` and ``ctx.loaded_data``
        are populated; ``ctx.execution`` is the fresh one built by
        :meth:`fork`; a lightweight run writes no index at all. The fork
        shallow-copies ``ctx.setup``, so the soil outputs, their input
        digests and the product keys stay shared by reference and a trial
        that leaves the soil parameters alone reuses the soil in memory.
        *Per-trial* (recreated on every fork).
    earliest : int
        Index of the first pipeline step that must re-run per trial.
    downstream_steps : tuple[TrialStep, ...]
        Full ordered tuple of pipeline steps (``00..11``). Trials run
        the slice ``[earliest:9]``.
    override_paths : Mapping[str, str]
        Parameter name → dotted config path for :meth:`fork` value
        injection.
    workspace : Path
        Project catalog root (for promotion and reporting).
    cfg_path : Path
        Source TOML path.
    raw_toml : Mapping[str, Any]
        Parsed TOML, used to rebuild per-trial contexts.
    kept_solves : TrialSolveRetention or None
        Which trial solves stay on disk for their promotion. The calibration
        core sets it for the span of one session; a fork never carries it.
    """

    base_cfg: BaseModel
    ctx: WorkflowContext
    earliest: int
    downstream_steps: tuple[TrialStep, ...]
    override_paths: Mapping[str, str]
    workspace: Path
    cfg_path: Path
    raw_toml: Mapping[str, Any] = field(default_factory=dict)
    parameter_space: Any = None
    requested_spatial_support_ids: tuple[str, ...] = ()
    requested_domain_supports: Mapping[str, object] = field(default_factory=dict)
    spatial_support_registry: Any = None
    kept_solves: TrialSolveRetention | None = None

    def fork(
        self,
        values: Mapping[str, float],
        *,
        slot_request: SlotRequest | None = None,
    ) -> TrialContext:
        """Return a new trial context isolated for one evaluation.

        - ``cfg`` is deep-copied and the calibration ``values`` are
          injected via the calibration parameter space (honors
          ``mode="replace"`` / ``"scale"``) when the space is provided,
          otherwise via raw dotted paths.
        - ``setup`` is shallow-copied into a fresh dataclass; the big
          prepared objects (``geographic``, ``cell_mesh``, ``domain``,
          ``workspace``, ``time_grid``, ...) stay shared by reference,
          but ``flow`` / ``transport`` are reset so the trial rebuilds them
          from the modified ``cfg.flow`` on demand.
        - ``slot_request`` (optional) goes on the forked setup. A
          :class:`TrialSandbox` passes one with a per-trial run name here, so
          each concurrent solver run writes to its own model folder under the
          shared scratch and never collides.
        - ``loaded_data`` is shared by reference (forcings are
          read-only after loading).
        - ``execution`` is freshly instantiated with
          ``lightweight=True``.
        - ``store`` / ``sim_id`` / ``parent_sim_id`` are left unset so
          no Zarr / Parquet / DuckDB rows are written.
        """
        from hydromodpy.core.state.run_state import WorkflowContext

        new_cfg = self.base_cfg.model_copy(deep=True)
        if self.parameter_space is not None:
            from hydromodpy.calibration.optim.parameters import apply_parameter_to_config

            for param in self.parameter_space:
                if param.name not in values or param.effective_path is None:
                    continue
                apply_parameter_to_config(new_cfg, param, float(values[param.name]))
        else:
            for pname, pvalue in values.items():
                path = self.override_paths.get(pname)
                if path:
                    set_by_path(new_cfg, path, pvalue)

        new_setup = _copy.copy(self.ctx.setup)
        new_setup.flow = None
        new_setup.model = None
        new_setup.slot_request = slot_request

        new_ctx = WorkflowContext(
            cfg=new_cfg,
            config_path=self.cfg_path,
            raw_toml=dict(self.raw_toml),
            bounds=self.ctx.bounds,
        )
        new_ctx.data_plan = self.ctx.data_plan
        new_ctx.setup = new_setup
        new_ctx.loaded_data = self.ctx.loaded_data
        new_ctx.execution = ExecutionRegistry(
            lightweight=True,
            rng=getattr(self.ctx.execution, "rng", None),
        )

        # Rebuild the flow from the patched cfg and re-bind the
        # loaded forcings (recharge, oceanic) to the fresh objects. Without
        # this, the trial solver runs on a Flow with zero recharge. The
        # rebuild is skipped when ``loaded_data`` has no real forcings
        # attached (e.g. unit tests using stub contexts).
        if (
            hasattr(new_ctx.loaded_data, "recharge")
            and getattr(new_setup, "domain", None) is not None
        ):
            trial_pipeline().apply_structural_updates_from_data(new_ctx)

        return TrialContext(
            base_cfg=self.base_cfg,
            ctx=new_ctx,
            earliest=self.earliest,
            downstream_steps=self.downstream_steps,
            override_paths=self.override_paths,
            workspace=self.workspace,
            cfg_path=self.cfg_path,
            raw_toml=self.raw_toml,
            parameter_space=self.parameter_space,
            requested_spatial_support_ids=self.requested_spatial_support_ids,
            requested_domain_supports=self.requested_domain_supports,
            spatial_support_registry=self.spatial_support_registry,
        )


# ---------------------------------------------------------------------------
# Preparation
# ---------------------------------------------------------------------------


def prepare_trials(
    cfg_path: Path | str,
    *,
    override_paths: Mapping[str, str] | Iterable[str],
    steps: Sequence[TrialStep] | None = None,
    parameter_space: Any = None,
    config_overrides: Mapping[str, Any] | None = None,
    bounds: Any = None,
) -> TrialContext:
    """Load TOML, run steps ``[0..earliest)`` once, return a fork-able context.

    Parameters
    ----------
    cfg_path
        Path to the calibration TOML (must be a full HydroModPy config -
        ``base_config`` + ``[calibration]`` + ``[simulation]`` etc.).
    override_paths
        Either a mapping ``{parameter_name: dotted_path}`` or a raw
        iterable of dotted paths. The mapping form is preferred because
        :meth:`TrialContext.fork` uses it to inject values by name.
    steps
        Pipeline steps to compose over. Defaults to the workflow
        provider's ``standard_steps()``.
    parameter_space
        Optional :class:`~hydromodpy.calibration.optim.parameters.ParameterSpace`.
        When supplied, :meth:`TrialContext.fork` injects values through the
        calibration helper (``mode="replace"``/``"scale"``). Otherwise, it
        falls back to the raw dotted-path writer.
    config_overrides
        Dotted paths written into the configuration BEFORE the prefix runs.
        This is how a phase says what model it calibrates: a flow regime or a
        time step written after the prefix is prepared changes the baseline the
        forks copy, but not the time grid the prefix already built, so the
        phase silently runs the discretization of the one before it. A path
        that names no field, at any segment, raises
        :class:`~hydromodpy.core.exceptions.ConfigValidationError`.

        This is not ``override_paths``, which names what VARIES per trial and
        therefore decides how much of the pipeline re-runs. An entry there
        cuts the prepared prefix; an entry here changes what the prefix is
        prepared from.
    bounds
        The :class:`~hydromodpy.core.runtime.bounds.Bounds` of the call that
        launched the calibration. The resolve step puts them on the context
        the preparation builds, so a trial loads its data under the hosts the
        call allows. ``None`` keeps the all-allowing default.
    """
    cfg_path = Path(cfg_path).expanduser().resolve()
    pipeline = trial_pipeline()
    raw_toml = pipeline.load_document(cfg_path)
    # from_toml handles base_config inheritance + resolves relative paths
    # against the TOML directory (e.g. data.dem.source_path -> absolute).
    cfg = pipeline.load_config(cfg_path)

    for dotted, value in (config_overrides or {}).items():
        try:
            set_by_path(cfg, str(dotted), value)
        except ValueError as exc:
            raise ConfigValidationError(
                f"config override {dotted!r} cannot be written into the configuration: {exc}"
            ) from exc

    if isinstance(override_paths, Mapping):
        path_map: dict[str, str] = {str(k): str(v) for k, v in override_paths.items()}
        path_set = set(path_map.values())
    else:
        path_set = {str(p) for p in override_paths}
        path_map = {p: p for p in path_set}

    # Mirror Project._configure: a mesh that follows the rivers needs their network.
    cfg.geographic = river_network_for_the_mesh(cfg)

    # Mirror Project._configure: discover the spatial supports referenced by
    # heterogeneous flow parameters so step_03 (build_geographic) can validate
    # the contract. Without this the pipeline crashes on multi-zone configs
    # (e.g. piecewise-K calibration) because requested_domain_supports stays
    # empty in the pipeline state.
    requested_support_ids = collect_requested_support_ids(cfg.flow)
    requested_domain_supports = resolve_support_configs(
        cfg.domain,
        requested_support_ids,
    )
    spatial_support_registry = build_default_spatial_support_provider_registry()

    pipeline_steps: tuple[TrialStep, ...] = tuple(
        steps if steps is not None else pipeline.standard_steps()
    )
    # Cap at 9 (extract) - the trial primitive never runs derive/export/display.
    max_downstream = 9
    earliest = pipeline.earliest_affected_step(path_set, pipeline_steps)
    earliest = min(earliest, max_downstream)

    prep_slice = pipeline_steps[:earliest]
    state = pipeline.make_state(
        "calibration-prepare",
        {
            "cfg": cfg,
            "config_path": cfg_path,
            "raw_toml": raw_toml,
            "bounds": bounds,
            "skip_display": True,
            "requested_spatial_support_ids": requested_support_ids,
            "requested_domain_supports": requested_domain_supports,
            "spatial_support_registry": spatial_support_registry,
        },
    )
    if prep_slice:
        # The pipeline phases render the prep checklist themselves.
        state = pipeline.make_pipeline(prep_slice).run(state)

    ctx = state.get("ctx")
    if ctx is None:
        raise RuntimeError(
            "prepare_trials: pipeline did not produce a WorkflowContext - ensure ResolveStep ran."
        )

    # Mirror Project.py: resolve the time_grid once so subsequent trials
    # do not need to re-derive it. Step 06/07 require it in
    # preprocess_options and the pipeline's ResolveStep does not populate
    # it on its own.
    if getattr(ctx.setup, "time_grid", None) is None:
        try:
            from hydromodpy.core.time import require_flow_simulation_time_grid

            ctx.setup.time_grid = require_flow_simulation_time_grid(cfg)
        except Exception:
            logger.debug("prepare_trials: could not resolve time_grid eagerly")

    workspace_obj = getattr(ctx.setup, "workspace", None)
    workspace = Path(workspace_obj.project_root) if workspace_obj is not None else cfg_path.parent

    return TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=earliest,
        downstream_steps=pipeline_steps,
        override_paths=path_map,
        workspace=workspace,
        cfg_path=cfg_path,
        raw_toml=raw_toml,
        parameter_space=parameter_space,
        requested_spatial_support_ids=requested_support_ids,
        requested_domain_supports=requested_domain_supports,
        spatial_support_registry=spatial_support_registry,
    )


# ---------------------------------------------------------------------------
# Lightweight evaluation
# ---------------------------------------------------------------------------

_RECHARGE_PREFIX = "flow.sinks_sources.recharge."


def _phase_samples_the_recharge(trial_ctx: TrialContext) -> bool:
    """Whether the phase samples a value the recharge is computed from."""
    space = trial_ctx.parameter_space
    if space is not None:
        paths = [param.effective_path for param in space if param.effective_path]
    else:
        paths = list(trial_ctx.override_paths.values())
    return any(path.startswith(_RECHARGE_PREFIX) for path in paths)


class _FlowBuildLauncher:
    """Execute the flow runs of a plan alone, for a setup that stops before their solve."""

    def execute(self, plan: Any, state: Any, *, callbacks: Any = None) -> Any:
        from hydromodpy.solver.base.runner import SimulationRunner

        del callbacks
        runs = tuple(run for run in plan.runs if run.process_type == "flow")
        return SimulationRunner().execute(replace(plan, runs=runs), state)


@contextmanager
def built_model(trial_ctx: TrialContext, values: Mapping[str, float]) -> Iterator[Any]:
    """Yield the workflow context of one trial with its flow model built and not solved.

    The same fork and the same steps as :func:`run_trial_light`, up to the solver
    launcher, in a sandbox of its own that is swept on exit. A check that needs the
    model before the first solve reads it here, with what a trial reads.
    """
    pipeline = trial_pipeline()
    sandbox = sandbox_of(trial_ctx, 0)
    request = sandbox.slot_request(
        owns_recharge=_phase_samples_the_recharge(trial_ctx), stop_before_solve=True
    )
    with progress.suppressed(), sandbox:
        forked = trial_ctx.fork(values, slot_request=request)
        sandbox.track(forked.ctx.execution)
        names = [step.name for step in forked.downstream_steps]
        through_the_launcher = names.index("run_solver") + 1
        steps = pipeline.with_solver_launcher(
            forked.downstream_steps[forked.earliest : through_the_launcher], _FlowBuildLauncher()
        )
        state = _trial_state(pipeline, forked, "calibration-prepared-model")
        pipeline.make_pipeline(steps).run(state)
        yield forked.ctx


def _trial_state(pipeline: Any, forked: Any, run_id: str) -> Any:
    """Return the pipeline state of one forked trial context, display skipped."""
    return pipeline.make_state(
        run_id,
        {
            "cfg": forked.ctx.cfg,
            "config_path": forked.cfg_path,
            "raw_toml": dict(forked.raw_toml),
            "ctx": forked.ctx,
            "skip_display": True,
        },
    )


def run_trial_light(
    trial_ctx: TrialContext,
    values: Mapping[str, float],
    *,
    objective: str = "nse",
    variable: str = "head",
    metric_fn: TrialMetricFn | None = None,
    trial_id: int | None = None,
    reject_water_budget_above: float | None = None,
) -> TrialResult:
    """Execute one lightweight trial and return its :class:`TrialResult`.

    Runs steps ``[earliest..8]`` against a fork of ``trial_ctx`` with
    ``execution.lightweight = True``. Steps 06/07 skip Zarr, Parquet
    and provenance writes; step 07 also skips the catalog ingestion
    callback. After the solver returns, ``metric_fn`` (or the default
    extractor when ``None``) pulls the objective in RAM.

    Parameters
    ----------
    trial_ctx
        Prepared :class:`TrialContext` from :func:`prepare_trials`.
    values
        Parameter sample keyed by calibration name (matching
        ``trial_ctx.override_paths``).
    objective
        Name of the scalar metric (``"nse"``, ``"kge"``, ``"rmse"``, …).
        Forwarded to ``metric_fn`` when one is supplied, which repeats what
        that extractor was built on rather than choosing anything: the single
        metric extractor refuses a pair it was not built for, because the
        producer, the loaded records and the gauge the search follows are
        chosen when it is built.
    variable
        Observed variable to compare against (``"head"``, ``"discharge"``).
        Same rule as ``objective``.
    metric_fn
        Optional RAM-only extractor with signature
        ``(ctx, objective, variable) -> (primary, metrics)``. When
        ``None`` the default stub fails the trial with a non-finite
        objective. The full extractor is wired in by the calibration CLI.
    trial_id
        Unique trial id. When set, the trial runs under a private
        :class:`TrialSandbox` identity (its own run name and model folder)
        so concurrent trials never share solver input/output files, and the
        trial's solver output is cleaned up afterwards, unless the session
        retention (``trial_ctx.kept_solves``) keeps it for a promotion.
    """
    pipeline = trial_pipeline()
    sandbox = sandbox_of(trial_ctx, trial_id) if trial_id is not None else None
    request = (
        sandbox.slot_request(owns_recharge=_phase_samples_the_recharge(trial_ctx))
        if sandbox is not None
        else None
    )
    retention = trial_ctx.kept_solves if sandbox is not None else None
    keeps_solves = retention is not None and retention.keeps_any
    # The water-balance gate reads the figure the solver reported for the run, and
    # only the recording launcher hands the run results back to the trial.
    recorder = (
        RecordingLauncher() if keeps_solves or reject_water_budget_above is not None else None
    )

    t0 = time.monotonic()
    with progress.suppressed(), sandbox or nullcontext():
        try:
            forked = trial_ctx.fork(values, slot_request=request)
            if sandbox is not None:
                sandbox.track(forked.ctx.execution)
        except Exception as exc:
            return TrialResult(
                values=dict(values),
                metrics={},
                primary_metric=float("nan"),
                status="failed",
                duration_s=time.monotonic() - t0,
                error=_failure_text(exc, f"fork: {type(exc).__name__}: {exc}", trial_ctx),
            )

        # Trials only run [earliest..8]. Derive/export/display are reserved
        # for promotion (steps 09-11). ``skip_display`` says so to results
        # planning: a trial draws nothing, so under ``keep_per_cell_budget =
        # false`` no figure adds a term to the per-cell budget it keeps.
        downstream_slice = forked.downstream_steps[forked.earliest : 9]
        if recorder is not None:
            downstream_slice = pipeline.with_solver_launcher(downstream_slice, recorder)
        state = _trial_state(pipeline, forked, "calibration-trial")

        try:
            if downstream_slice:
                state = pipeline.make_pipeline(downstream_slice).run(state)
        except Exception as exc:
            logger.debug("Trial %s pipeline crashed", trial_id, exc_info=True)
            return TrialResult(
                values=dict(values),
                metrics={},
                primary_metric=float("nan"),
                status="crashed",
                duration_s=time.monotonic() - t0,
                error=_failure_text(exc, f"{type(exc).__name__}: {exc}", trial_ctx),
            )

        extractor = metric_fn if metric_fn is not None else _default_metric_extractor
        try:
            primary, metrics = extractor(forked.ctx, objective=objective, variable=variable)
        except Exception as exc:
            return TrialResult(
                values=dict(values),
                metrics={},
                primary_metric=float("nan"),
                status="failed",
                duration_s=time.monotonic() - t0,
                error=f"metric_fn: {type(exc).__name__}: {exc}",
            )

        if not math.isfinite(float(primary)):
            return TrialResult(
                values=dict(values),
                metrics=dict(metrics),
                primary_metric=float("nan"),
                status="failed",
                duration_s=time.monotonic() - t0,
                error="metric_fn returned a non-finite objective",
            )

        # A run whose water balance does not close routed water that came from
        # nowhere, so its cost is not comparable to a run that closed. Rejecting
        # it here, before it is scored, is what stops it being ranked and promoted.
        gate_metrics = {**metrics, **_reported_water_budget(recorder)}
        verdict = water_budget_verdict(gate_metrics, threshold=reject_water_budget_above)
        if verdict is not None and not verdict.passed:
            return TrialResult(
                values=dict(values),
                metrics=dict(metrics),
                primary_metric=float("nan"),
                status="failed",
                duration_s=time.monotonic() - t0,
                error=verdict.message,
            )

        # Offered while the sandbox is still open: a solve the retention keeps
        # must not be deleted by the exit below.
        if (
            keeps_solves
            and retention is not None
            and sandbox is not None
            and recorder is not None
            and trial_id is not None
            and retention.offer(trial_id, float(primary), sandbox.output_dirs(), recorder.results)
        ):
            sandbox.keep_outputs()

    return TrialResult(
        values=dict(values),
        metrics=dict(metrics),
        primary_metric=float(primary),
        status="completed",
        duration_s=time.monotonic() - t0,
    )


def _moved_quantities(trial_ctx: TrialContext) -> frozenset[str]:
    """The physical quantities the search moves, as labels of the registry.

    Read off each moved parameter's name and the segments of its path, so
    ``flow.param.Sy.field.value`` moves the specific yield. A label, not an id,
    because the registry spells one quantity several ways (``sy`` and
    ``specific_yield``).
    """
    paths = getattr(trial_ctx, "override_paths", None) or {}
    pairs = [(str(k), str(v)) for k, v in dict(paths).items()]
    for param in getattr(trial_ctx, "parameter_space", None) or ():
        pairs.append((str(param.name), str(param.effective_path or "")))
    labels: set[str] = set()
    for name, path in pairs:
        for word in (name, *path.split(".")):
            bound = PHYSICAL_BOUNDS.get(word.lower())
            if bound is not None:
                labels.add(bound.label)
    return frozenset(labels)


def _failure_text(exc: BaseException, text: str, trial_ctx: TrialContext) -> str:
    """Return the error text of a failed trial, marked infeasible when it is.

    A trial is infeasible when a :class:`PhysicalBoundsError` in the chain of
    its exception refuses a quantity the search moves: the pipeline
    wraps a step error in a ``StepError``, and the candidate check of
    ``mode = "scale"`` raises a ``ValueError`` while handling one. The optimizer
    gets the failed cost either way, and the consecutive-failure watch leaves an
    infeasible point out of its streak. A refusal of a fixed value, or one that
    names no parameter, repeats on every trial: it stays a failure the watch
    counts.
    """
    seen: set[int] = set()
    link: BaseException | None = exc
    while link is not None and id(link) not in seen:
        if isinstance(link, PhysicalBoundsError):
            bound = PHYSICAL_BOUNDS.get(str(link.param_id or "").lower())
            if bound is not None and bound.label in _moved_quantities(trial_ctx):
                return f"{INFEASIBLE_PREFIX}: {text}"
        seen.add(id(link))
        link = link.__cause__ or link.__context__
    return text


# Signature of a RAM-only metric extractor.
from collections.abc import Callable as _Callable  # noqa: E402

TrialMetricFn = _Callable[..., tuple[float, Mapping[str, float]]]


def _reported_water_budget(recorder: RecordingLauncher | None) -> dict[str, float]:
    """Return the worst model water-balance discrepancy the trial's runs reported.

    The figure is a run metric written by the solver adapter, not a component of
    the objective, so it is read from the run results the recorder kept. Each of
    the two keys keeps the largest magnitude over the runs, signed: the last step
    under ``WATER_BUDGET_METRIC`` and the worst step under
    ``WATER_BUDGET_WORST_METRIC``. A key no run reported is left out: absent is
    not zero.
    """
    if recorder is None:
        return {}
    worst: dict[str, float] = {}
    for result in recorder.results.values():
        reported = getattr(result, "metrics", None) or {}
        for key in (WATER_BUDGET_METRIC, WATER_BUDGET_WORST_METRIC):
            if reported.get(key) is None:
                continue
            value = float(reported[key])
            if math.isfinite(value) and (key not in worst or abs(value) > abs(worst[key])):
                worst[key] = value
    return worst


def _default_metric_extractor(
    ctx: WorkflowContext,
    *,
    objective: str,
    variable: str,
) -> tuple[float, Mapping[str, float]]:
    """Placeholder extractor.

    The trial primitive has no observation plan by itself, so the
    default extractor returns ``nan`` and the caller marks the trial
    failed. The calibration CLI replaces this with the configured
    extractor.
    """
    del ctx, objective, variable  # unused until Phase 2
    return float("nan"), {}


# ---------------------------------------------------------------------------
# Promotion (full pipeline)
# ---------------------------------------------------------------------------


def promote_prepared_trial(
    trial_ctx: TrialContext,
    values: Mapping[str, float],
    *,
    name: str | None = None,
    sim_id: str | None = None,
    run_dir: Path | None = None,
    lineage: Lineage | None = None,
    calibrated_by: CalibratedBy | None = None,
    promotion: PromotionFacts | None = None,
    kept: KeptSolve | None = None,
    spared: Sequence[Path] = (),
    keep_per_cell_budget: bool | None = None,
    outputs: Mapping[str, Any] | None = None,
) -> str:
    """Run a full promoted simulation from an already prepared trial context.

    ``sim_id`` reserves the id of the promoted run instead of letting the
    pipeline mint one. ``run_dir`` is the directory the promotion reserved for
    the run (``runs/<case>`` paired with the session, or a kept trial under
    ``sessions/<case>/trials/<n>``): the pipeline is built on it and writes
    the run there. ``lineage`` and ``calibrated_by`` are the blocks of its
    seal that name the session, the phase and the trial; they travel in the
    pipeline state under their own names, where the run steps read them.
    ``promotion`` is what the session says about the run (its objective, the
    parameters it set, the ones that ended on a bound); the step that opens
    the run writes it into the facts of the run.

    The attempt of ``run_dir`` is closed here: ``completed`` once the run is
    sealed, ``failed`` or ``aborted`` when the pipeline raises. A promotion is
    not launched under :func:`~hydromodpy.workflow.record.attempt.run_attempt`, so
    nothing else would close it.

    ``kept`` is the solve the trial of ``values`` left on disk. The run then
    goes on from extraction on that solve: the solver step hands it over
    instead of writing inputs and solving, so the store, the tables, the
    figures and the seal are those a replay writes. Without it, the run is
    solved again.

    ``spared`` names the solver folders of other kept trials, which the export
    step of this run must leave in the run scratch for their own promotion.

    ``outputs`` are the calibration outputs of the phase the run is promoted from,
    which the derive step reads the series of the stations with. Left ``None``, it
    reads those of the calibration of the run.

    ``keep_per_cell_budget`` overrides ``[simulation.results] keep_per_cell_budget``
    for this run only. ``None`` leaves what the project file says. The override is
    set on the results section of the forked configuration, a copy: the base
    configuration of the session is never touched.
    """
    pipeline = trial_pipeline()
    forked = trial_ctx.fork(values)
    ctx = forked.ctx
    if keep_per_cell_budget is not None:
        simulation = ctx.cfg.simulation
        simulation.results = simulation.results.model_copy(
            update={"keep_per_cell_budget": keep_per_cell_budget}
        )
    ctx.execution.lightweight = False
    ctx.execution.simulation_plan = None
    ctx.setup.run_id = name or "promoted"
    ctx.sim_id = None
    ctx.reserved_sim_id = None if sim_id is None else str(sim_id)

    state = pipeline.make_state(
        f"calibration-promote-{ctx.setup.run_id}",
        {
            "cfg": ctx.cfg,
            "config_path": forked.cfg_path,
            "raw_toml": dict(forked.raw_toml),
            "ctx": ctx,
            "skip_display": False,
            "lineage": lineage,
            "calibrated_by": calibrated_by,
            "promotion": promotion,
            "station_outputs": outputs,
            # The geographic preprocessing tree is shared by every promotion of
            # the session. Dropped by the export step of the first one, it left
            # the next ones with no watershed to ingest, so their catchment
            # series summed the whole domain. The session end drops it.
            "keep_preprocessing": True,
            "kept_scratch": tuple(str(folder) for folder in spared),
            "spatial_support_registry": forked.spatial_support_registry,
            "requested_spatial_support_ids": forked.requested_spatial_support_ids,
            "requested_domain_supports": forked.requested_domain_supports,
        },
    )
    prepare_index = _step_index_by_name(forked.downstream_steps, "prepare_solver")
    start_index = (
        min(forked.earliest, prepare_index) if prepare_index is not None else forked.earliest
    )
    downstream_slice: Sequence[TrialStep] = forked.downstream_steps[start_index:]
    if kept is not None:
        downstream_slice = pipeline.with_solver_launcher(downstream_slice, KeptSolveLauncher(kept))

    try:
        final = pipeline.make_pipeline(downstream_slice, run_dir=run_dir).run(state)
    except BaseException as exc:
        if run_dir is not None:
            _close_attempt(run_dir, exc)
        raise
    if run_dir is not None:
        _close_attempt(run_dir, None)

    final_ctx = final.get("ctx") if final is not None else None
    produced = getattr(final_ctx, "sim_id", None) if final_ctx is not None else None
    if produced is None:
        raise RuntimeError("Promoted calibration trial did not produce a simulation id")
    if sim_id is not None and str(produced) != str(sim_id):
        raise RuntimeError(
            f"Promoted run took the id {produced} instead of the reserved {sim_id}; "
            "everything written against the reservation would name another run."
        )
    return str(produced)


def _close_attempt(run_dir: Path, error: BaseException | None) -> None:
    """Close the attempt of a promoted run when it is still running.

    ``completed`` once the run is sealed. A pipeline that raised leaves it
    ``aborted`` on SIGINT or SIGTERM (both unwind as ``KeyboardInterrupt``),
    ``failed`` otherwise; one that returned without the seal, ``failed``.
    """
    outcome = read_outcome(run_dir)
    if outcome is None or outcome.status != "running":
        return
    if error is None and is_sealed(run_dir):
        close_sealed_attempt(run_dir)
        return
    status = "aborted" if isinstance(error, KeyboardInterrupt) else "failed"
    cause = error if error is not None else RuntimeError("the promoted run ended without its seal")
    try:
        finish_attempt(run_dir, status=status, error=cause)
    except OSError:
        # The error of the pipeline is the one to raise; this one is only logged.
        logger.exception("Could not write the outcome of %s", run_dir)


def _step_index_by_name(steps: Sequence[TrialStep], name: str) -> int | None:
    for index, step in enumerate(steps):
        if getattr(step, "name", None) == name:
            return index
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

__all__ = (
    "TrialContext",
    "TrialMetricFn",
    "TrialPipeline",
    "TrialPipelineRunner",
    "TrialResult",
    "TrialStep",
    "built_model",
    "install_trial_pipeline",
    "prepare_trials",
    "promote_prepared_trial",
    "run_trial_light",
    "trial_pipeline",
    "trial_pipeline_initializer",
)
