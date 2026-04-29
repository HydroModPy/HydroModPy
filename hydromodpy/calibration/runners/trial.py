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
  artefacts are written, extract the objective in RAM, and return a
  :class:`TrialResult`.
- :func:`promote_trial` - re-run the full pipeline (``00..11``) via
  :class:`hydromodpy.Project`, persisting Zarr + Parquet + catalog rows.
  Used once the calibration loop has finished to materialise the top-N
  best iterations.

The storage contract is strict: ``run_trial_light`` never writes to
disk. Only ``promote_trial`` creates simulation artefacts.
"""

from __future__ import annotations

import copy as _copy
import logging
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.workflow.internals.dependencies import earliest_affected_step
from hydromodpy.workflow.internals.state import PipelineState

if TYPE_CHECKING:
    from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.workflow.internals.step import Step

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrialResult:
    """Outcome of a single lightweight trial.

    ``primary_metric`` is the scalar used by the optimizer (lower is
    better by convention - ScalarObjective already flips higher-is-better
    metrics like NSE/KGE into costs). ``metrics`` holds the per-component
    breakdown. When ``status != "completed"``, ``primary_metric`` is
    ``nan`` and ``error`` carries the exception string.
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
        :meth:`fork`; ``ctx.store`` is ``None`` in lightweight mode.
        *Per-trial* (recreated on every fork).
    earliest : int
        Index of the first pipeline step that must re-run per trial.
    downstream_steps : tuple[Step, ...]
        Full ordered tuple of pipeline steps (``00..11``). Trials run
        the slice ``[earliest:9]``.
    override_paths : Mapping[str, str]
        Parameter name → dotted config path for :meth:`fork` value
        injection.
    workspace : Path
        Workspace root (for :func:`promote_trial` and reporting).
    cfg_path : Path
        Source TOML path.
    raw_toml : Mapping[str, Any]
        Parsed TOML, used to rebuild per-trial contexts.
    """

    base_cfg: HydroModPyConfig
    ctx: WorkflowContext
    earliest: int
    downstream_steps: tuple[Step, ...]
    override_paths: Mapping[str, str]
    workspace: Path
    cfg_path: Path
    raw_toml: Mapping[str, Any] = field(default_factory=dict)
    parameter_space: Any = None

    def fork(self, values: Mapping[str, float]) -> TrialContext:
        """Return a new trial context isolated for one evaluation.

        - ``cfg`` is deep-copied and the calibration ``values`` are
          injected via the calibration parameter space (honours
          ``mode="replace"`` / ``"scale"``) when the space is provided,
          otherwise via raw dotted paths.
        - ``setup`` is shallow-copied into a fresh dataclass; the big
          prepared objects (``geographic``, ``mesh_planar``, ``domain``,
          ``workspace``, ``time_grid``, ...) stay shared by reference,
          but ``flow`` / ``transport`` / ``flow_runtime_overrides`` are
          reset so that the trial rebuilds them from the modified
          ``cfg.flow`` on demand.
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
            from hydromodpy.calibration.parameters import apply_parameter_to_config

            for param in self.parameter_space:
                if param.name not in values or param.effective_path is None:
                    continue
                apply_parameter_to_config(new_cfg, param, float(values[param.name]))
        else:
            for pname, pvalue in values.items():
                path = self.override_paths.get(pname)
                if path:
                    _set_by_path(new_cfg, path, pvalue)

        new_setup = _copy.copy(self.ctx.setup)
        new_setup.flow = None
        new_setup.transport = None
        new_setup.flow_runtime_overrides = None

        new_ctx = WorkflowContext(
            cfg=new_cfg,
            config_path=self.cfg_path,
            raw_toml=dict(self.raw_toml),
        )
        new_ctx.data_plan = self.ctx.data_plan
        new_ctx.setup = new_setup
        new_ctx.loaded_data = self.ctx.loaded_data
        new_ctx.execution = ExecutionRegistry(lightweight=True)

        # Rebuild flow / transport from the patched cfg and re-bind the
        # loaded forcings (recharge, oceanic) to the fresh objects. Without
        # this, the trial solver runs on a Flow with zero recharge. The
        # rebuild is skipped when ``loaded_data`` has no real forcings
        # attached (e.g. unit tests using stub contexts).
        if (
            hasattr(new_ctx.loaded_data, "recharge")
            and getattr(new_setup, "domain", None) is not None
        ):
            from hydromodpy.workflow.steps.data_loading import (
                apply_structural_updates_from_data,
            )

            apply_structural_updates_from_data(new_ctx)

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
        )


# ---------------------------------------------------------------------------
# Preparation
# ---------------------------------------------------------------------------


def prepare_trials(
    cfg_path: Path | str,
    *,
    override_paths: Mapping[str, str] | Iterable[str],
    steps: Sequence[Step] | None = None,
    parameter_space: Any = None,
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
        Pipeline steps to compose over. Defaults to
        :func:`hydromodpy.workflow.orchestrator.standard_steps`.
    parameter_space
        Optional :class:`~hydromodpy.calibration.parameters.ParameterSpace`.
        When supplied, :meth:`TrialContext.fork` injects values through the
        calibration helper (``mode="replace"``/``"scale"``). Otherwise, it
        falls back to the raw dotted-path writer.
    """
    from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.config.toml_loader import load_toml_with_base_config
    from hydromodpy.spatial.domain.spatial_support import (
        build_default_spatial_support_provider_registry,
    )
    from hydromodpy.workflow.orchestrator import standard_steps
    from hydromodpy.workflow.runner import Pipeline
    from hydromodpy.workflow.steps.setup import (
        collect_requested_support_ids,
        resolve_support_configs,
    )

    cfg_path = Path(cfg_path).expanduser().resolve()
    raw_toml = load_toml_with_base_config(cfg_path)
    # from_toml handles base_config inheritance + resolves relative paths
    # against the TOML directory (e.g. data.dem.source_path -> absolute).
    cfg = HydroModPyConfig.from_toml(cfg_path)

    if isinstance(override_paths, Mapping):
        path_map: dict[str, str] = {str(k): str(v) for k, v in override_paths.items()}
        path_set = set(path_map.values())
    else:
        path_set = {str(p) for p in override_paths}
        path_map = {p: p for p in path_set}

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

    pipeline_steps = tuple(steps if steps is not None else standard_steps())
    # Cap at 9 (extract) - the trial primitive never runs derive/export/display.
    max_downstream = 9
    earliest = earliest_affected_step(path_set, pipeline_steps)
    earliest = min(earliest, max_downstream)

    prep_slice = pipeline_steps[:earliest]
    state: PipelineState = PipelineState(
        run_id="calibration-prepare",
        data={
            "cfg": cfg,
            "config_path": cfg_path,
            "raw_toml": raw_toml,
            "requested_spatial_support_ids": requested_support_ids,
            "requested_domain_supports": requested_domain_supports,
            "spatial_support_registry": spatial_support_registry,
        },
    )
    if prep_slice:
        state = Pipeline(prep_slice).run(state)

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
            from hydromodpy.core.time import (
                apply_explicit_time_window_to_tgrids,
                require_flow_simulation_time_grid,
            )

            apply_explicit_time_window_to_tgrids(cfg)
            ctx.setup.time_grid = require_flow_simulation_time_grid(cfg)
        except Exception:
            logger.debug("prepare_trials: could not resolve time_grid eagerly")

    workspace_obj = getattr(ctx.setup, "workspace", None)
    workspace = Path(workspace_obj.root) if workspace_obj is not None else cfg_path.parent

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
    )


# ---------------------------------------------------------------------------
# Lightweight evaluation
# ---------------------------------------------------------------------------


def run_trial_light(
    trial_ctx: TrialContext,
    values: Mapping[str, float],
    *,
    objective: str = "nse",
    variable: str = "head",
    metric_fn: TrialMetricFn | None = None,
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
        Forwarded to ``metric_fn`` when one is supplied.
    variable
        Observed variable to compare against (``"head"``, ``"discharge"``).
    metric_fn
        Optional RAM-only extractor with signature
        ``(ctx, objective, variable) -> (primary, metrics)``. When
        ``None`` the default stub returns ``(nan, {})`` - the full
        extractor is wired in by the calibration CLI in Phase 2.
    """
    from hydromodpy.workflow.runner import Pipeline

    t0 = time.monotonic()
    try:
        forked = trial_ctx.fork(values)
    except Exception as exc:  # pragma: no cover - value injection bug
        return TrialResult(
            values=dict(values),
            metrics={},
            primary_metric=float("nan"),
            status="failed",
            duration_s=time.monotonic() - t0,
            error=f"fork: {type(exc).__name__}: {exc}",
        )

    # Trials only run [earliest..8]. Derive/export/display are reserved
    # for promote_trial (steps 09-11).
    downstream_slice = forked.downstream_steps[forked.earliest : 9]
    state: PipelineState = PipelineState(
        run_id="calibration-trial",
        data={
            "cfg": forked.ctx.cfg,
            "config_path": forked.cfg_path,
            "raw_toml": dict(forked.raw_toml),
            "ctx": forked.ctx,
        },
    )

    try:
        if downstream_slice:
            state = Pipeline(downstream_slice).run(state)
    except Exception as exc:
        return TrialResult(
            values=dict(values),
            metrics={},
            primary_metric=float("nan"),
            status="crashed",
            duration_s=time.monotonic() - t0,
            error=f"{type(exc).__name__}: {exc}",
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

    return TrialResult(
        values=dict(values),
        metrics=dict(metrics),
        primary_metric=float(primary),
        status="completed",
        duration_s=time.monotonic() - t0,
    )


# Signature of a RAM-only metric extractor.
from collections.abc import Callable as _Callable  # noqa: E402

TrialMetricFn = _Callable[..., tuple[float, Mapping[str, float]]]


def _default_metric_extractor(
    ctx: WorkflowContext,
    *,
    objective: str,
    variable: str,
) -> tuple[float, Mapping[str, float]]:
    """Placeholder extractor.

    Phase 1 ships the trial primitive without the observation-plan
    machinery: the default extractor returns ``nan`` and an empty
    metrics dict so that unit tests can exercise the lightweight
    pipeline without observations wired. Phase 2 replaces this with a
    reading of ``ctx.loaded_data.hydrometry`` + the observation plan.
    """
    del ctx, objective, variable  # unused until Phase 2
    return float("nan"), {}


# ---------------------------------------------------------------------------
# Promotion (full pipeline)
# ---------------------------------------------------------------------------


def promote_trial(
    cfg_path: Path | str,
    values: Mapping[str, float],
    *,
    paths: Mapping[str, str] | None = None,
    name: str | None = None,
    tags: Sequence[str] = (),
    session_id: str | None = None,
) -> str:
    """Run the full simulation pipeline with calibration values baked in.

    Opens a :class:`hydromodpy.Project`, deep-copies its config with
    ``values`` injected via their dotted ``paths``, runs the full plan,
    and returns the resulting ``sim_id``. Zarr + Parquet + catalog rows
    are written exactly like a normal ``hmp run``.

    Parameters
    ----------
    cfg_path
        Path to the TOML that was used for calibration.
    values
        Parameter sample to bake into the promoted run.
    paths
        Parameter name → dotted config path mapping. When omitted the
        caller must have already configured the values via
        ``Project.run(**values)`` conventions (flat Flow.parameters).
    name
        Run name (falls back to ``"promoted_<short sid>"``).
    tags
        Extra tags, usually including ``"calibration:<session_id>"``.
    session_id
        Optional calibration session UUID; added as
        ``"calibration:<sid>"`` tag when supplied.
    """
    from hydromodpy.project import Project

    cfg_path = Path(cfg_path).expanduser().resolve()
    project = Project(cfg_path)
    try:
        if paths:
            for pname, pvalue in values.items():
                dotted = paths.get(pname)
                if dotted:
                    _set_by_path(project.cfg, dotted, pvalue)
            run = project.run(name=name or "promoted")
        else:
            run = project.run(name=name or "promoted", **dict(values))
        sim_id = run.sim_id

        tag_list: list[str] = list(tags)
        if session_id:
            tag_list.append(f"calibration:{session_id}")
        if tag_list:
            store = getattr(project, "store", None) or getattr(project, "_store", None)
            writer = getattr(store, "write_tags", None)
            if callable(writer):
                try:
                    writer(sim_id, tag_list)
                except Exception:
                    logger.exception("Failed to attach tags %s to sim %s", tag_list, sim_id)
    finally:
        project.close()

    return sim_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_by_path(cfg: Any, path: str, value: Any) -> None:
    """Set ``value`` on the leaf at dotted ``path`` under ``cfg``.

    Traversal handles Pydantic attributes (``getattr``/``setattr``) and
    mapping entries (``"cfg.flow.param.K"`` where ``param`` is a dict
    keyed by parameter name) transparently.
    """
    parts = path.split(".")
    target: Any = cfg
    for part in parts[:-1]:
        if isinstance(target, Mapping):
            target = target[part]
        else:
            target = getattr(target, part)
    leaf_key = parts[-1]
    if isinstance(target, Mapping):
        target[leaf_key] = value
    else:
        setattr(target, leaf_key, value)


__all__ = (
    "TrialContext",
    "TrialResult",
    "TrialMetricFn",
    "prepare_trials",
    "run_trial_light",
    "promote_trial",
)
