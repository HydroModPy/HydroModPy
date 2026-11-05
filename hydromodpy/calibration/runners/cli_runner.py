"""CLI entry point ``hmp calibrate <calibration.toml>`` and the core search loop.

Workflow of a calibration without phases:

1. Load the TOML and validate the ``[calibration]`` section into a
   :class:`CalibrationConfig`, with the defaults of the project written in
   (``[site] gauge`` as the station, ``[metrics] window`` as the scoring window).
2. Name the case and reserve ``sessions/<case>/``; freeze the resolved
   document there as ``config.toml``; open the journal.
3. Prepare the downstream pipeline once via :func:`prepare_trials` when the
   resolved evaluator declares it needs one.
4. Drive the ask/tell loop through :class:`CalibrationEngine`, which calls the
   evaluator once per suggestion. Every trial goes to ``trials.jsonl``.
5. Promote the trials ``save_runs`` names, once, after the last restart: the
   best one to ``runs/<case>/``, the others under ``sessions/<case>/trials/``.
6. Close the session: ``session.json``, ``outcome.json``, ``README.md``.

Nothing here opens the index. SIGTERM writes ``aborted``, marks the cut
phase, and writes the pointer of the best trial of the last completed phase
(or of the cut phase when no phase completed) in under a second
(:func:`abort_session`); that trial is then promoted from its kept solve
when it has one (:func:`promote_best_after_abort`), anything else is left to
``hmp campaign promote``. The three runners close their session through one
scope (:func:`closing_session`).
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from hydromodpy.calibration.config import (
    CalibPhaseDecl,
    CalibrationConfig,
    window_bounds,
)
from hydromodpy.calibration.evaluation import TrialOutcome, TrialRequest
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.metrics.trial_series_capture import TrialSeriesSink
from hydromodpy.calibration.optim.adapters.bisection_adapter import (
    BOUNDS_COMPONENT,
    ROOT_BOUNDS,
    BisectionAdapter,
    roots_scored,
)
from hydromodpy.calibration.optim.cache import (
    ParamsHashCache,
    context_fingerprints,
    differing_members,
)
from hydromodpy.calibration.optim.cost_margin import (
    IntervalWidth,
    ParameterInterval,
    margin_intervals,
)
from hydromodpy.calibration.optim.diagnostics import (
    DEFAULT_CORRELATION_THRESHOLD,
    correlated_parameter_pairs,
)
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.objective import (
    cost_block_fractions,
    mean_cost_block_fractions,
)
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
    engine_traits,
)
from hydromodpy.calibration.optim.progress_reporter import ConsoleProgressReporter
from hydromodpy.calibration.optim.stopping import (
    budget_kwargs,
    resolve_budget,
    settled,
    stopping_kwargs,
)
from hydromodpy.calibration.persistence import (
    DEFAULT_PHASE,
    CalibrationPersistence,
    PhaseContext,
)
from hydromodpy.calibration.protocols import (
    deviations_in_force,
    expand_calibration_protocol,
    get_protocol,
)
from hydromodpy.calibration.report import (
    NO_OTHER_TRIAL,
    interval_best_is_on_a_bound,
    interval_is_degenerate,
)
from hydromodpy.calibration.runners.failure_watch import INFEASIBLE_PREFIX, ConsecutiveFailureWatch
from hydromodpy.calibration.runners.kept_solves import TrialSolveRetention, retention_capacity
from hydromodpy.calibration.runners.prepared_model import (
    check_the_prepared_model,
    network_outputs_of,
)
from hydromodpy.calibration.runners.promotion import (
    PromotionOutcome,
    promote_best_after_abort,
    promote_session,
    promotion_name_check,
)
from hydromodpy.calibration.runners.recap import (
    cost_metric_label,
    cost_samples,
    parameter_units,
    scored_samples,
)
from hydromodpy.calibration.runners.restarts import (
    RestartSpread,
    run_restarts,
    run_side_by_side,
)
from hydromodpy.calibration.runners.resume import trials_another_cost_scored
from hydromodpy.calibration.runners.sandbox import keep_trial_scratch
from hydromodpy.calibration.runners.session import (
    calibration_case_name,
    freeze_session_config,
    open_session_dir,
    project_root_for,
    search_windows,
    session_bounds,
    session_config_hash,
)
from hydromodpy.calibration.runners.state import (
    build_cache_context,
    load_metric_fn_entry_point,
    preload_hash_cache,
    space_from_config,
)
from hydromodpy.calibration.runners.state import (
    override_paths as resolve_override_paths,
)
from hydromodpy.calibration.runners.trial import (
    TrialMetricFn,
    prepare_trials,
)
from hydromodpy.calibration.runners.worker_pool import TrialWorkerPool
from hydromodpy.core.exceptions import (
    CalibrationError,
    UncertaintyNotAvailableError,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.interrupts import TerminationRequested, terminate_as_interrupt
from hydromodpy.core.state.paths import run_dir_rel, session_dir_rel
from hydromodpy.core.stream.geometry import VALIDITY_PROVENANCE_BY_CODE
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.core.workspace.path_registry import in_run_scratch
from hydromodpy.results.checks import CalibrationSessionStatus, StopState
from hydromodpy.results.session.descriptor import (
    BestTrial,
    CostInterval,
    ParameterWidth,
    ProtocolDeparture,
    RestartRange,
    ScoredSamples,
    SessionProtocol,
    SessionStatus,
)

if TYPE_CHECKING:
    from hydromodpy.calibration.optim.engine import CalibrationSession
    from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.calibration.runners.trial import TrialContext

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# TOML loader
# ---------------------------------------------------------------------------


def load_toml_calibration(path: Path) -> tuple[CalibrationConfig, dict]:
    """Return the validated ``[calibration]`` section of ``path`` and the raw TOML.

    Read through ``base_config`` resolution, the same way the pipeline reads the
    file. Reading it raw instead made a ``[calibration]`` section inherited from
    a base configuration invisible here while the pipeline resolved it, so a
    calibration overlay of two lines failed on "No [calibration] section".

    The legacy keys are migrated in memory first, as the project loader does,
    so a file ``hmp doctor --fix-config <file>`` would fix also runs unfixed.
    """
    from pydantic import ValidationError

    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.core.toml_io.error_locator import format_validation_error
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    try:
        raw = load_toml_with_base_config(path)
    except ValueError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    if "calibration" not in raw:
        raise ValueError(f"No [calibration] section in {path}")
    try:
        raw = expand_calibration_protocol(raw)
    except ValueError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    try:
        cfg = CalibrationConfig.model_validate(_with_project_defaults(raw, path))
    except ValidationError as exc:
        # The reader of this message writes TOML and does not read Python, so it
        # has to name the file, the line and the key rather than the model.
        raise ConfigError(
            format_validation_error(exc, source_path=path, loc_prefix=("calibration",))
        ) from None
    resolve_stream_geometry_paths(cfg, path)
    _resolve_parameter_names(cfg, path)
    return cfg, raw


def _with_project_defaults(raw: Mapping[str, Any], path: Path) -> dict[str, Any]:
    """Return the raw ``[calibration]`` table with ``[site] gauge`` and ``[metrics] window`` written in."""
    from hydromodpy.calibration.config import apply_project_defaults
    from hydromodpy.core.exceptions import ConfigError

    site = raw.get("site")
    metrics = raw.get("metrics")
    try:
        return apply_project_defaults(
            raw["calibration"],
            site_gauge=site.get("gauge") if isinstance(site, Mapping) else None,
            metrics_window=metrics.get("window") if isinstance(metrics, Mapping) else None,
        )
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from None


def _resolve_parameter_names(cfg: CalibrationConfig, config_path: Path) -> None:
    """Complete every parameter from the target it points at.

    The catalog is read off the resolved project configuration, which this
    section is one part of, so the project is built here. Anchored on the same
    file, and idempotent like :func:`resolve_stream_geometry_paths`, because a
    declaration is only ever completed where the file said nothing.
    """
    from hydromodpy.calibration.parameter_resolution import (
        UnresolvedParameterName,
        resolve_parameter_targets,
    )

    if not getattr(cfg, "parameters", None):
        return
    from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider

    try:
        project_cfg = get_root_config_provider().from_toml(config_path)
    except UnresolvedParameterName:
        # The names are the file's own business and the message already says which
        # one is wrong. Swallowing it here left the run to fail three steps later
        # on "must declare a 'path'", which accuses the form this file no longer
        # has to write.
        raise
    except Exception:
        # A file that is not a runnable project has nothing to resolve against.
        # Loading must stay possible anyway: `--list-phases` runs on a machine
        # holding none of the data, and the parameter without a path is refused
        # by the space and the preflight with their own message.
        logger.debug("No project configuration to resolve parameter names against", exc_info=True)
        return
    resolve_parameter_targets(cfg, project_cfg)


def resolve_stream_geometry_paths(cfg: CalibrationConfig, config_path: Path) -> None:
    """Anchor every relative map path of an output to the file that declares it.

    Both maps are anchored: ``map.complete`` and ``map.permanent``.

    A path in a TOML is relative to that TOML, the way ``base_config`` is, and a
    bare filename falls back to ``<project>/data/hydrography/`` like every other
    data path. Reading it against the working directory instead made the run
    depend on where it was launched from.

    Called from :func:`run_calibration_core`, where the CLI, the staged and the
    programmatic routes converge, and again from :func:`load_toml_calibration`
    for the readers that never run a calibration. Running twice is harmless: the
    second pass sees absolute paths and skips them.

    A path that resolves to nothing is left exactly as declared. Loading a
    configuration must not require its data to be present: ``--list-phases`` has
    to work on a machine that holds none of it, and the criterion already names
    the file it could not read.
    """
    base = config_path.expanduser().resolve().parent
    for name, role, candidate in cfg.map_files():
        if candidate.is_absolute():
            continue
        found = next(
            (
                trial
                for root in (base, base.parent, base.parent.parent)
                for trial in (root / candidate, root / "data" / "hydrography" / candidate.name)
                if trial.exists()
            ),
            None,
        )
        if found is not None:
            setattr(cfg.outputs[name].map, role, found.resolve())


def session_cost_name(cfg: CalibrationConfig, phase: CalibPhaseDecl | None = None) -> str:
    """Return the metric a search scores on, as its objective blocks name it.

    A search scored through blocks names their metrics, joined by ``" + "``
    when there are several. A single-metric search names its ``objective``.
    Without ``phase``, a staged session keeps the value and the window of its
    last phase, so it names what that phase scores.
    """
    last = phase if phase is not None else (cfg.phases[-1] if cfg.phases else None)
    if last is not None and last.is_single_metric:
        return str(last.objective or cfg.objective)
    metrics = [str(block.metric) for block, _weight in cfg.objective_blocks_for(last)]
    if metrics:
        return " + ".join(dict.fromkeys(metrics))
    return str(cfg.objective)


# ---------------------------------------------------------------------------
# Core loop (caller-agnostic)
# ---------------------------------------------------------------------------


def declared_window_text(cfg: CalibrationConfig, phase: CalibPhaseDecl | None = None) -> str:
    """Say the window a search scores on, as the file declares it.

    ``cfg`` is the ``[calibration]`` section and ``phase`` one of its phases,
    ``None`` for the section's own search. The phase's ``window``,
    else the section's; a transient phase carries ``[metrics] window`` there
    once the project defaults are applied. A bound left open reads as the
    first or last paired sample. Without a window, the whole run is scored.
    """
    window = getattr(cfg, "window", None)
    if phase is not None and phase.window is not None:
        window = phase.window
    if window is not None and (window.start or window.end):
        start = window.start or "the first paired sample"
        end = window.end or "the last paired sample"
        return f"window {start} to {end}"
    return "no window, all of the run"


def keep_trial_solves(cfg: CalibrationConfig, trial_ctx: TrialContext | None) -> None:
    """Give the session a retention of trial solves when it promotes any.

    A promoted trial then reads the solve its trial left on disk instead of
    being solved again. A session that promotes nothing keeps nothing: each
    trial deletes its solver folder on exit, as before.
    """
    if trial_ctx is None:
        return
    retention = TrialSolveRetention(retention_capacity(cfg))
    trial_ctx.kept_solves = retention if retention.keeps_any else None


def release_trial_solves(trial_ctx: TrialContext | None) -> None:
    """Delete the trial solves the session still keeps, and detach the retention.

    Runs on every exit path, beside :func:`release_session_scratch`, and never
    raises: a folder that cannot be removed is left to the run scratch sweep.
    """
    if trial_ctx is None or trial_ctx.kept_solves is None:
        return
    retention, trial_ctx.kept_solves = trial_ctx.kept_solves, None
    retention.release()


def release_session_scratch(trial_ctx: TrialContext | None) -> None:
    """Drop the preprocessing tree the session shared across its trials.

    Trials skip the setup steps and read the tree built once for the session,
    so no trial may delete it; and only a *promoted* run reaches the export
    step that normally does. A session that promotes nothing therefore used to
    leave hundreds of MB of DEM and flow rasters under ``.hmp/scratch``. This
    runs on every exit path (success, failure, SIGINT) and never raises.

    ``None`` when the named evaluator prepared no model: nothing was built, so
    there is nothing to release.
    """
    from hydromodpy.spatial.geographic.preprocessing_cleanup import cleanup_stable_folder

    if trial_ctx is None:
        return
    geographic = getattr(getattr(trial_ctx.ctx, "setup", None), "geographic", None)
    if geographic is None:
        return
    geographic_cfg = getattr(getattr(trial_ctx, "base_cfg", None), "geographic", None)
    keep = keep_trial_scratch() or bool(getattr(geographic_cfg, "write_intermediates", False))
    try:
        cleanup_stable_folder(geographic, keep=keep)
    except Exception:  # noqa: BLE001 - cleanup never decides the session outcome
        logger.warning("Could not remove the calibration session scratch", exc_info=True)


def calibration_trace(
    history: Iterable[Any],
    values_by_trial: Mapping[int, Mapping[str, float]],
) -> list[dict[str, Any]]:
    """Return the session history in the shape the diagnostics read.

    The cost travels under ``cost``, which the diagnostics know as a
    meta column. Under any other name it is taken for one more calibrated
    parameter, and a single-parameter search then reports the parameter as
    correlated with its own cost.
    """
    return [
        {
            "parameters": dict(values_by_trial[item.trial_id]),
            "cost": item.cost,
        }
        for item in history
        if item.trial_id in values_by_trial
    ]


def _margin_intervals_or_none(
    trace: list[dict[str, Any]],
    names: list[str],
    space: ParameterSpace,
    width: IntervalWidth,
    optimizer: Any = None,
) -> list[ParameterInterval]:
    """Return the interval around each calibrated value, or nothing.

    A root search reads its answer's interval on the curve of its trials
    (:meth:`BisectionAdapter.root_interval`), any other search on their envelope.

    A criterion solved at zero, such as the stream-network gap, has no fraction
    of itself to take, so a share of the best cost means nothing there. Reporting
    nothing is the honest answer rather than a number under a rule nobody chose,
    and the run says which line turns it back on. The same holds for one mesh
    cell no trial measured, and for a share on network distances.
    """
    if width.margin is None:
        logger.warning(
            "No interval was reported around the calibrated values: the width is one "
            "mesh cell, and no trial measured the mesh. Write [calibration.uncertainty] "
            "cost_margin in metres, such as '25 m', to get one."
        )
        return []
    if width.kind == "relative" and width.on_distances:
        logger.warning(
            "No interval was reported around the calibrated values: cost_margin is a "
            "share of the best cost, and this search is scored only on network "
            "distances, in metres, where a fraction has no meaning. Write a length such "
            "as '25 m', or leave it unwritten for one mesh cell."
        )
        return []
    bounds = {param.name: (param.lower, param.upper) for param in space}
    try:
        if isinstance(optimizer, BisectionAdapter):
            root = optimizer.root_interval(margin=float(width.margin), kind=width.kind)
            return [] if root is None else [root]
        return margin_intervals(
            trace,
            names,
            bounds=bounds,
            margin=float(width.margin),
            kind=width.kind,
        )
    except ValueError as exc:
        logger.warning(
            "No interval was reported around the calibrated values: %s Write "
            "[calibration.uncertainty] cost_margin as a length such as '25 m' to get one.",
            exc,
        )
        return []


def _cell_measured_by_the_criterion(results: Iterable[EvaluationResult | None]) -> float | None:
    """Return the mesh cell the network criterion measured on a trial, or ``None``.

    Every trial of one search scores the same mesh, so the first finite value
    is the cell. ``None`` when no trial scored a network output.
    """
    for result in results:
        if result is None:
            continue
        for key, value in (result.components or {}).items():
            if str(key).endswith(".cell_spacing_m") and math.isfinite(float(value)):
                return float(value)
    return None


def _width_read_off_the_trials(
    width: IntervalWidth, best: EvaluationResult | None, history: Iterable[EvaluationResult]
) -> IntervalWidth:
    """Return ``width`` with its one mesh cell measured, and log the width read."""
    if width.margin is None:
        cell = _cell_measured_by_the_criterion([best, *history])
        if cell is not None:
            width = width.measured(cell)
    where = {
        "phase": "written in the phase",
        "section": "written in [calibration.uncertainty]",
        "default": f"default, {width.rule}",
    }[width.source]
    logger.info(
        "Interval width: %s %s (%s).",
        "unmeasured" if width.margin is None else f"{width.margin:.4g}",
        width.kind,
        where,
    )
    return width


def _log_parameter_interval(interval: ParameterInterval, best: EvaluationResult | None) -> None:
    """Log the range the trials could not tell apart from one calibrated value.

    A value that reaches a search bound is the best point of a search that was
    forbidden to look further, not a value the trials converged onto: that is
    a warning, not an informational line, and it names the cost it was reached at.
    A value inside its bounds whose range reaches one is another statement: the
    trials do not close it on that side.
    """
    reach = [
        side
        for side, hit in (
            ("lower", interval.reaches_lower_bound),
            ("upper", interval.reaches_upper_bound),
        )
        if hit
    ]
    if reach and not interval_best_is_on_a_bound(interval.to_dict()):
        logger.warning(
            "%s = %.4g: the trials within %.3g of the best run to the %s search bound, so "
            "they do not close it on that side.",
            interval.name,
            interval.best,
            interval.threshold,
            " and ".join(reach),
        )
        return
    if reach:
        logger.warning(
            "%s = %.4g reached the %s search bound, at a cost of %.4g: this is the best "
            "point of a search that was forbidden to look further, not a value the trials "
            "converged onto.",
            interval.name,
            interval.best,
            " and ".join(reach),
            best.cost if best is not None else float("nan"),
        )
        return
    if interval_is_degenerate(interval.to_dict()):
        logger.info(
            "%s = %.4g: %s (%.3g of the best), over %d trials.",
            interval.name,
            interval.best,
            NO_OTHER_TRIAL,
            interval.threshold,
            interval.n_trials,
        )
        return
    logger.info(
        "%s = %.4g, and %d of %d trials scored within %.3g of the best over [%.4g, %.4g].",
        interval.name,
        interval.best,
        interval.n_within,
        interval.n_trials,
        interval.threshold,
        interval.lower,
        interval.upper,
    )


CONDUCTIVITY_PATH = "flow.param.K.field.value"
"""The homogeneous conductivity, the one parameter the paper's ratios divide."""


def _non_negative(value: Any) -> float | None:
    """Return ``value`` as a float when it is finite and not negative, else None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0.0 else None


def _conductivity_unit(trial_ctx: Any, param: CalibParameter) -> str:
    """Return the unit the model reads the conductivity value in.

    The sample is written as-is into ``flow.param.K.field.value``, so the field's
    own unit rules. The declaration's ``units`` comes next, then ``m/s``.
    """
    flow = getattr(getattr(trial_ctx, "base_cfg", None), "flow", None)
    entry = (getattr(flow, "param", None) or {}).get("K")
    unit = getattr(getattr(entry, "field", None), "unit", None)
    for candidate in (unit, param.units):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return "m/s"


def _r_optim_verdict_extra(
    outputs: Mapping[str, Any] | None,
    components: Mapping[str, float] | None,
) -> dict[str, Any]:
    """Read Eq. 4 on the trial the search returns, once per network output.

    The paper reads ``r_optim <= 2`` at the optimum ("At this point", HESS
    27, p. 3225), and so does this: a trial on the way to the root is not the
    result, and bounding it refused whole brackets. The bound is a length:
    ``D_optim <= validity_length_m``, which each trial publishes with its
    provenance beside ``r_optim`` and ``r_optim_valid``. ``r_optim`` is still
    ``D_optim / h_obs``, the paper's Eq. 3, for comparison with its Table 1.

    Returns ``{"r_optim_verdict": {key: {value, D_optim, h_obs,
    validity_length_m, provenance, valid, causes}}}``, or nothing when no
    network output published a ``r_optim``. ``causes`` lists what failed:
    ``"doptim"`` (D_optim above the length) and ``"empty"`` (no simulated
    network at the returned trial, so nothing to qualify). A failure warns
    once. With ``verdict.on_invalid = "error"`` it
    raises :class:`CalibrationError`; the caller has already saved the
    session, and a staged calibration stops there, before freezing anything.

    An output scored on two bounds has no unsuffixed ``r_optim``: Eq. 4 is
    read on each bound in the cost, under ``<output>_minimal`` and
    ``<output>_maximal`` (:func:`_r_optim_reads`), each against its own length.
    """
    found = components or {}
    verdicts: dict[str, dict[str, Any]] = {}
    fatal: list[str] = []
    reads = [
        (name, output, key, suffix)
        for name, output in sorted((outputs or {}).items())
        if output.support == "network"
        for key, suffix in _r_optim_reads(name, found)
    ]
    for name, output, key, suffix in reads:
        verdict = _eq4_verdict(name, found, suffix=suffix)
        verdicts[key] = verdict
        if verdict["valid"]:
            continue
        message = _eq4_violation_message(key, verdict)
        logger.warning(message)
        if output.verdict.on_invalid == "error":
            fatal.append(message)
    if fatal:
        raise CalibrationError(" ".join(fatal))
    return {"r_optim_verdict": verdicts} if verdicts else {}


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _eq4_verdict(name: str, found: Mapping[str, float], *, suffix: str) -> dict[str, Any]:
    """Return the Eq. 4 verdict of one bound of one output, from its components."""
    value = float(found[f"{name}.r_optim{suffix}"])
    optimal = float(found.get(f"{name}.D_optim{suffix}", float("nan")))
    h_obs = float(found.get(f"{name}.h_obs{suffix}", float("nan")))
    length = float(found.get(f"{name}.validity_length_m{suffix}", float("nan")))
    code = float(found.get(f"{name}.validity_length_provenance{suffix}", float("nan")))
    causes: list[str] = []
    if not math.isfinite(optimal):
        causes.append("empty")
    elif not (math.isfinite(length) and optimal <= length):
        causes.append("doptim")
    return {
        "value": _finite_or_none(value),
        "D_optim": _finite_or_none(optimal),
        "h_obs": _finite_or_none(h_obs),
        "validity_length_m": _finite_or_none(length),
        "provenance": VALIDITY_PROVENANCE_BY_CODE.get(code),
        "valid": not causes,
        "causes": causes,
    }


def _eq4_violation_message(key: str, verdict: Mapping[str, Any]) -> str:
    """Say why Eq. 4 fails on one bound, naming every cause."""
    length = verdict["validity_length_m"]
    bound = f"{length:.4g} m" if length is not None else "not published"
    if "empty" in verdict["causes"]:
        return (
            f"Output {key!r}: D_optim is not a number at the returned trial, so the validity "
            f"length {bound} cannot qualify it: the simulated network is empty there."
        )
    parts: list[str] = []
    if "doptim" in verdict["causes"]:
        ratio = verdict["value"]
        parts.append(
            f"the mean mismatch D_optim = {verdict['D_optim']:.4g} m exceeds the validity "
            f"length {bound} ({verdict['provenance'] or 'provenance unknown'}), r_optim = "
            + (f"{ratio:.3g} cells of h_obs" if ratio is not None else "not a number")
        )
    return (
        f"Output {key!r}: Eq. 4 fails: "
        + "; and ".join(parts)
        + ". It qualifies the calibrated value; it does not say the value is wrong."
    )


def _r_optim_reads(name: str, found: Mapping[str, float]) -> list[tuple[str, str]]:
    """Return ``(verdict key, component suffix)`` for each r_optim Eq. 4 reads on an output.

    One bound in the cost: the unsuffixed ``r_optim``, keyed by the output.
    Two bounds: each bound weighted above zero, keyed ``<output>_<bound>``.
    The maximal map of a one-state output with both maps is a validation
    outside the cost, and is not read here.
    """
    if f"{name}.r_optim" in found:
        return [(name, "")]
    if float(found.get(f"{name}.{BOUNDS_COMPONENT}", 1.0)) < 2.0:
        return []
    return [
        (f"{name}_{bound}", f"_{bound}")
        for bound in ROOT_BOUNDS
        if f"{name}.r_optim_{bound}" in found
        and float(found.get(f"{name}.weight_{bound}", 1.0)) > 0.0
    ]


def _network_ratios_extra(
    *,
    network_outputs: Iterable[str],
    components: Mapping[str, float] | None,
    best_parameters: Mapping[str, float] | None,
    space: ParameterSpace,
    trial_ctx: Any = None,
) -> dict[str, Any]:
    """Return the derived values of Abherve et al. (2023), Table 1, or nothing.

    The network criterion compares two networks and drives any parameter. The
    paper's ratios exist only when the one parameter the search moved is the
    homogeneous conductivity written as a value. A thickness, a zone or a
    multiplier divided by R names nothing, so every other search gets none.

    - ``k_over_r``: K/R, what the criterion identifies at fixed geometry.
    - ``k_optim_m_s``: K in m/s, the calibrated value against that recharge.
    - ``d_sat_m``: dsat, the saturated thickness averaged over the catchment.
    - ``t_over_r_m``: T/R = (K/R) dsat, a length.
    - ``t_optim_m2_s``: Toptim = K dsat.

    R and dsat are read off the best trial, ``<output>.R_mean_m_s`` and
    ``<output>.d_sat_m``, on the first network output by name, which the note
    names. The run is already saved when this runs, so a conductivity unit that
    is not one logs a warning and publishes nothing rather than raise.
    """
    outputs = sorted(network_outputs)
    if not outputs or not best_parameters or len(best_parameters) != 1:
        return {}
    ((name, value),) = best_parameters.items()
    param = next((p for p in space if p.name == name), None)
    if param is None or param.effective_path != CONDUCTIVITY_PATH or param.mode != "replace":
        return {}
    from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s

    unit = _conductivity_unit(trial_ctx, param)
    try:
        conductivity = float(value) * factor_to_m_per_s(unit)
    except ValueError as exc:
        logger.warning("No K/R in the report: %s", exc)
        return {}
    found = components or {}
    output = outputs[0]
    recharge = _non_negative(found.get(f"{output}.R_mean_m_s"))
    if not recharge:
        return {}
    k_over_r = conductivity / recharge
    extra: dict[str, Any] = {"k_over_r": k_over_r, "k_optim_m_s": conductivity}
    window = _recharge_window(trial_ctx)
    if window is not None:
        extra["r_mean_window"] = {"start": window[0], "end": window[1]}
    over = "" if window is None else f" over {window[0]} to {window[1]}"
    note = (
        f"k_over_r = {k_over_r:.4g} against R_mean_m_s = {recharge:.4g} m/s{over} on output "
        f"{output!r}, k_optim = {conductivity:.4g} m/s"
    )
    d_sat = _non_negative(found.get(f"{output}.d_sat_m"))
    if d_sat is not None:
        extra["d_sat_m"] = d_sat
        extra["t_over_r_m"] = k_over_r * d_sat
        extra["t_optim_m2_s"] = conductivity * d_sat
        note += (
            f", d_sat = {d_sat:.4g} m, t_over_r = {k_over_r * d_sat:.4g} m, "
            f"t_optim = {conductivity * d_sat:.4g} m2/s"
        )
        ratio = _non_negative(found.get(f"{output}.d_sat_over_d"))
        if ratio is not None:
            extra["d_sat_over_d"] = ratio
            if ratio > 0.5:
                note += (
                    f". The aquifer runs {ratio:.0%} full: T/R depends on the imposed "
                    "thickness there"
                )
    extra["k_over_r_note"] = note + "."
    return extra


def _recharge_window(trial_ctx: Any) -> tuple[str, str] | None:
    """Return the dates the recharge of a trial is the mean of, or None when it has none.

    The window the phase prepared its trials on, which a steady regime writes into
    ``[simulation.time]``: the mean recharge is only readable with its dates, since
    a three-year window and a sixty-year normal give another K/R.
    """
    time = getattr(getattr(getattr(trial_ctx, "base_cfg", None), "simulation", None), "time", None)
    start, end = getattr(time, "start_datetime", None), getattr(time, "end_datetime", None)
    if start is None or end is None:
        return None
    return str(start)[:10], str(end)[:10]


def _search_outcome_extra(session: CalibrationSession) -> dict[str, Any]:
    """Return how the search stopped, and the root search's final bracket.

    ``search`` records why the engine stopped (``stop_state``), whether that
    is convergence, the rule, the declared budget and the extension granted
    once. A staged calibration freezes nothing from a phase whose search is
    not :func:`~hydromodpy.calibration.optim.stopping.settled`.
    ``bracket`` exists only for the root search: the interval whose two ends
    change sign, in physical units, which is what the search proved about the
    root beyond the trial it returns.

    A root search on two bounds publishes ``roots`` instead
    (:meth:`~hydromodpy.calibration.optim.adapters.bisection_adapter.
    BisectionAdapter.roots_record`): per bound its root ``k_star``, weight
    and final bracket, then ``delta_log10 = log10(K*_maximal / K*_minimal)``
    and the combined ``value``, the trial the search returns.
    """
    extra: dict[str, Any] = {
        "search": {
            "stop_state": session.stop_state,
            "converged": bool(session.converged),
            "stopping_rule": session.stopping_rule,
            "max_trials": int(session.max_trials),
            "extension": int(session.extension),
            "n_evaluations": len(session.history),
        }
    }
    root_search = _root_search_record(session) or {}
    extra.update(root_search)
    if "roots" in root_search:
        _log_the_two_roots(root_search["roots"])
    return extra


def _root_search_record(session: CalibrationSession | None) -> dict[str, Any] | None:
    """Return the root search's ``bracket`` or ``roots``, None for any other search.

    The session journal keeps this record, so a report read back later shows
    what the live run printed.
    """
    if session is None or not isinstance(session.optimizer, BisectionAdapter):
        return None
    record: dict[str, Any] = {}
    bracket = session.optimizer.bracket_record()
    if bracket is not None:
        record["bracket"] = bracket
    roots = session.optimizer.roots_record()
    if roots is not None:
        record["roots"] = roots
    outside = session.optimizer.root_outside_bounds()
    if outside is not None:
        record["root_outside_bounds"] = outside
    return record or None


def _closes_two_roots(session: CalibrationSession) -> bool:
    """Whether the search closed one root per bound, and says so once.

    Its value lies between two roots, where the weighted cost is not smallest,
    so an interval of trials scoring within a width of the lowest cost would
    sit around one of the roots and not around the value. The width of such an
    answer is the spread of its roots, published under ``roots``.
    """
    optimizer = session.optimizer
    if not isinstance(optimizer, BisectionAdapter) or optimizer.roots != 2:
        return False
    logger.info(
        "No interval of trials is reported around a value combined from two roots: its "
        "width is the spread between them, Delta, reported with the roots."
    )
    return True


def _log_the_two_roots(roots: Mapping[str, Any]) -> None:
    """Say the two roots, their spread and the value returned between them."""
    minimal, maximal = roots["minimal"], roots["maximal"]
    delta = roots.get("delta_log10")
    value = roots.get("value")
    logger.info(
        "%s: K*_minimal = %.6g (bracket [%.6g, %.6g]), K*_maximal = %.6g (bracket "
        "[%.6g, %.6g]), Delta = %s decade(s); returned %s = %s, their geometric mean "
        "weighted %.3g / %.3g.",
        roots["parameter"],
        minimal["k_star"],
        minimal["low"],
        minimal["high"],
        maximal["k_star"],
        maximal["low"],
        maximal["high"],
        f"{delta:.3g}" if delta is not None else "unknown",
        roots["parameter"],
        f"{value:.6g}" if value is not None else "not solved",
        minimal["weight"],
        maximal["weight"],
    )
    # On the Nancon the spread reached 1.28 decades, and the mean met neither map.
    if delta is not None and abs(delta) > 0.5:
        logger.warning(
            "The two roots lie %.3g decades apart, more than half a decade: the value returned "
            "between them satisfies neither map. Read each root on its own.",
            abs(delta),
        )


def _phase_cost_block_fractions(
    cfg: CalibrationConfig,
    history: list[EvaluationResult],
    best: EvaluationResult | None,
) -> dict[str, Any] | None:
    """Return the ``cost_block_fractions`` a finished phase's report carries.

    ``"mean"`` averages each block's fraction of the cost over the finished
    trials (``status == "completed"`` and a finite objective, the convention
    every optimizer adapter reads its own history with); ``"mean_n_trials"``
    is how many of them entered that average. ``"best"`` reads the fraction at
    the trial the search reports. ``None`` for a phase scored through a
    single metric, with no ``[[calibration.objective_blocks]]`` declared, or
    when no finished trial gives a computable fraction.
    """
    blocks = [(str(block.name), float(block.weight)) for block in cfg.objective_blocks or []]
    if not blocks:
        return None
    finished = [
        result for result in history if result.status == "completed" and math.isfinite(result.cost)
    ]
    mean_result = mean_cost_block_fractions(blocks, (result.components for result in finished))
    if mean_result is None:
        return None
    mean_fractions, n_trials = mean_result
    payload: dict[str, Any] = {"mean": mean_fractions, "mean_n_trials": n_trials}
    if best is not None:
        best_fractions = cost_block_fractions(best.components, blocks)
        if best_fractions is not None:
            payload["best"] = best_fractions
    return payload


def _first_trial_pairing(history: list[EvaluationResult]) -> dict[str, dict[str, Any]] | None:
    """Return, per output, the dates and pair count the first trial retained.

    Read from ``history[0]`` (:func:`~hydromodpy.calibration.runners.recap.cost_samples`):
    the pairing a search sets up before its first candidate. A later trial
    can keep fewer pairs, a dry cell drops one, so the cost of the best trial
    is read with its own pairs (``extra["cost_samples"]``). ``None`` when no
    output names a station: nothing was paired.
    """
    if not history:
        return None
    return cost_samples(history[0].components) or None


class _DerivativeEvaluator:
    """Run the model at one parameter set and hand back the vectors a width is read from.

    A class at module level so that a worker process can build it, like any
    evaluator of a pool. The simulated and the observed vector travel as the one
    row of ``trial_series_sink``, which a pool already returns.
    """

    evaluator_id: ClassVar[str] = "linearized_width"
    needs_prepared_model: ClassVar[bool] = True

    def __init__(self, *, cfg: CalibrationConfig, trial_ctx: TrialContext) -> None:
        from hydromodpy.calibration.metrics.composite import build_paired_vector_capture

        self._cfg = cfg
        self._trial_ctx = trial_ctx
        self.trial_series_sink = TrialSeriesSink()
        self._capture, self._captured = build_paired_vector_capture(
            cfg.outputs or {},
            ctx=trial_ctx.ctx,
            objective_blocks=list(cfg.objective_blocks or []),
            window=window_bounds(cfg.window),
            min_samples=int(cfg.aggregate.min_samples),
        )

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        from hydromodpy.calibration.runners.trial import run_trial_light

        self._captured.clear()
        result = run_trial_light(
            self._trial_ctx,
            dict(request.values),
            objective=self._cfg.objective,
            variable=self._cfg.variable,
            metric_fn=self._capture,
            trial_id=request.trial_id,
            reject_water_budget_above=self._cfg.reject_water_budget_above,
        )
        # A run a water-budget rejection marks failed leaves no vector to reuse.
        captured = result.status == "completed" and "simulated" in self._captured
        if captured:
            self.trial_series_sink.rows = [
                {key: self._captured[key] for key in ("simulated", "observed")}
            ]
        return TrialOutcome(
            cost=result.primary_metric,
            status="completed" if captured else "failed",
            duration_s=result.duration_s,
            error=result.error,
        )


def attach_a_linearized_width(
    report: CalibrationReport,
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext,
    space: ParameterSpace,
    perturbation: float,
) -> CalibrationReport:
    """Attach a first-order width to the answer the search returned.

    One model run per parameter around the optimum, then the optimum itself, last,
    so the residuals read are the fit's. The runs go side by side when the search
    does, in worker processes that last for these runs only. A calibration whose
    parameters the data cannot separate is refused a width rather than given a
    fabricated one, and the failure says which. A run that fails, or that a
    water-budget rejection marks failed, leaves no width either: its vector is
    never reused for another one.
    """
    import numpy as np

    from hydromodpy.calibration.optim.fosm import (
        forward_difference_jacobian,
        linearized_covariance,
        uncertainty_from_covariance,
    )

    if not report.best_parameters:
        logger.warning("No candidate was scored, so there is no answer to put a width beside.")
        return report

    # Only the typed refusal, which says the document cannot carry a width at
    # all: every other way this function declines leaves the report standing,
    # and a search already paid for is too expensive to throw away over a
    # declaration. A record that failed to load, or an output naming no
    # station, still leaves loudly the way it always did.
    # These runs keep no solve: they are not trials, and retention ranks by cost.
    options = {"cfg": cfg, "trial_ctx": replace(trial_ctx, kept_solves=None)}
    try:
        evaluator = _DerivativeEvaluator(**options)
    except UncertaintyNotAvailableError as exc:
        logger.warning("No width is reported: %s", exc)
        return report

    names = [name for name in space.names if name in report.best_parameters]
    width = min(cfg.parallel, len(names) + 1)
    pool = TrialWorkerPool(_DerivativeEvaluator, options, width=width) if width > 1 else None
    runner = pool or evaluator
    fit: dict[str, Any] = {}

    def _run(request: TrialRequest) -> Mapping[str, Any]:
        outcome = runner.evaluate(request)
        if outcome.status != "completed":
            moved = ", ".join(
                f"{name} = {float(value):.4g}" for name, value in request.values.items()
            )
            reason = f": {outcome.error}" if outcome.error else ""
            raise UncertaintyNotAvailableError(
                f"the run at {moved} ended {outcome.status}{reason}, so no derivative is "
                "taken there."
            )
        [row] = runner.trial_series_sink.drain()
        return row

    def _simulate_all(runs):
        # One id per run, since they may run side by side.
        requests = [TrialRequest(-index, dict(run)) for index, run in enumerate(runs, start=1)]
        if pool is None:
            rows = [_run(request) for request in requests]
        else:
            rows = run_side_by_side(_run, requests, width=len(requests), on_stop=pool.close)
        # The reference ran last, so the vectors kept are the fit's.
        fit.update(rows[-1])
        return [row["simulated"] for row in rows]

    logger.info(
        "Taking %d derivative(s) around the answer at a %.3g relative step; the calibrated "
        "values do not move.",
        len(names),
        perturbation,
    )
    try:
        jacobian = forward_difference_jacobian(
            names, report.best_parameters, _simulate_all, relative_step=perturbation
        )
    except UncertaintyNotAvailableError as exc:
        logger.warning("No width is reported: %s", exc)
        return report
    finally:
        if pool is not None:
            pool.close()
    residuals = np.asarray(fit["simulated"], dtype=float) - np.asarray(fit["observed"], dtype=float)
    try:
        covariance = linearized_covariance(jacobian, residuals)
    except ValueError as exc:
        logger.warning("No width is reported: %s", exc)
        return report
    widths = uncertainty_from_covariance(names, report.best_parameters, covariance)
    for item in widths:
        tradeoff = item.strongest_tradeoff()
        logger.info(
            "%s = %.4g +- %.4g%s",
            item.parameter,
            item.value,
            item.sigma,
            "" if tradeoff is None else f", correlated {tradeoff[1]:+.2f} with {tradeoff[0]}",
        )
    return replace(report, parameter_uncertainty=widths)


def _engine_kwargs(cfg: CalibrationConfig, space: ParameterSpace, *, start_at: Any) -> dict:
    """Return everything the engine is constructed with beyond the space and the seed.

    A root search is also told how many roots its network outputs score, so
    its budget counts both when an output is scored on two bounds.
    """
    kwargs = stopping_kwargs(
        cfg.method, space, precision=cfg.precision, declared=cfg.method_options
    )
    kwargs.update(budget_kwargs(cfg.method, cfg.max_trials))
    traits = engine_traits(cfg.method)
    if start_at is not None and traits.accepts_a_start_point:
        kwargs["start_at"] = start_at
    if traits.takes_width:
        kwargs["width"] = cfg.parallel
    if cfg.method == BisectionAdapter.name:
        declared = cfg.outputs or {}
        kwargs["roots"] = roots_scored(
            declared[name] for name in network_outputs_of(cfg) if name in declared
        )
        # The width the engine asks for, so the counted budget, and "auto"
        # sized from it, count the bracket cut into that many parts.
        kwargs["batch"] = max(cfg.batch_size, cfg.parallel)
    return kwargs


def with_its_method(cfg: CalibrationConfig) -> CalibrationConfig:
    """Return ``cfg`` with the method it runs written in.

    Itself when the file names one. Otherwise a copy carrying the method its
    criteria call for (``CalibrationConfig.method_for``), so every reader after
    this point, the session journal and the params hash included, sees the name
    that ran.
    """
    method, reason = cfg.method_for()
    if reason is None:
        return cfg
    logger.info("The calibration names no method and runs %s: %s.", method, reason)
    return cfg.model_copy(update={"method": method})


def refuse_an_objective_that_is_not_an_entry_point(objective: str | None) -> None:
    """Refuse an ``objective=`` that does not name a Python callable.

    ``objective=`` is an entry point specification, ``"module.path:callable"``,
    on all three routes. A metric NAME handed to it was silently ignored: a
    caller asking for ``objective="kge"`` on a document declaring ``nse``
    calibrated on ``nse`` and nothing said so.

    Called at the entry of each public route rather than where the value is
    consumed. Two reasons, both measured. A staged run that reuses its phases
    from disk never reaches the consumer, so the value traveled into the reuse
    fingerprint without ever being checked. And the consumer sits after
    ``prepare_trials``, so a refused call used to pay the whole geographic,
    mesh and data prefix first, and leave a fresh catalog, a lock and a WAL
    behind in a workspace where no calibration ever ran.
    """
    if not objective or ":" in objective:
        return
    raise CalibrationError(
        f"objective={objective!r} is not a 'module.path:callable' entry point. "
        "objective= names a Python callable to build the metric extractor with, and "
        "a metric name is not one. Declare the metric where the document declares "
        "metrics: [calibration] objective for the single-metric route, a block's "
        "'metric' for the composite one, or objective_blocks=[{'name': ..., "
        "'metric': ..., 'uses_outputs': [...]}] when calling Project.calibrate, "
        "which passes no [calibration] table."
    )


def run_calibration_core(
    cfg: CalibrationConfig,
    trial_ctx: TrialContext | None,
    *,
    persistence: CalibrationPersistence,
    space: ParameterSpace,
    project_root: Path,
    cfg_path: Path | None = None,
    metric_fn: TrialMetricFn | None = None,
    objective: str | None = None,
    phase: PhaseContext | None = None,
    start_at: Any | None = None,
    interval_width: IntervalWidth | None = None,
    pool_for: Callable[..., TrialWorkerPool] | None = None,
) -> CalibrationReport:
    """Heart of the calibration loop: one search, journaled as it goes.

    The caller opened the session (``persistence``) and closes it; this runs
    one search of it and returns its report. It promotes nothing: a phase is
    promoted once, after its last restart, by the caller.

    ``start_at`` is where the search begins, in transformed space, and is how a
    restart-based uncertainty makes one repetition differ from the next. It is
    handed to the engine only when the engine declares it accepts one; on any
    other engine a new seed is the whole of the difference.

    ``interval_width`` is the width the interval beside each value is read
    with, as the staged runner resolved it for the phase. Unset, it is resolved
    from ``cfg``. One mesh cell is measured off the trials, which the network
    criterion records beside its cost.

    ``phase`` names the phase and the restart the trials of this search belong
    to; unset, the one phase of a calibration without phases.

    ``pool_for(evaluator_class, options, width=...)`` gives the pool of workers
    that serves a search at ``parallel > 1``, and its caller closes it. It is
    required there. Restarts side by side share one, so that together they run
    ``parallel`` trials at once and no more.

    The caller is responsible for building a :class:`TrialContext` when the
    named evaluator declares it needs one, and passing ``None`` when it does
    not, and for the :class:`ParameterSpace`. ``cfg_path`` is what a declared
    the map paths are anchored on, and where candidates are
    materialized from.
    """
    from hydromodpy.calibration.report import CalibrationReport

    if cfg_path is not None:
        resolve_stream_geometry_paths(cfg, cfg_path)
    cfg = with_its_method(cfg)
    # Same refusal for a mono-phase run as for a staged one: an optimizer_kwarg
    # foreign to the declared method used to die as a bare TypeError inside the
    # adapter constructor, after the first solve.
    cfg.validate_registry()
    override_paths = resolve_override_paths(cfg)
    context = phase or PhaseContext()

    engine_cache: ParamsHashCache | None = None
    if cfg.use_cache:
        engine_cache = ParamsHashCache()
        preload_hash_cache(project_root, engine_cache)

    refuse_an_objective_that_is_not_an_entry_point(objective)
    if metric_fn is None and objective and ":" in objective:
        metric_fn = load_metric_fn_entry_point(objective)

    if cfg.validation_window is not None and (
        metric_fn is not None
        or evaluation_registry.resolve_id(cfg.evaluator) != evaluation_registry.DEFAULT_EVALUATOR_ID
    ):
        raise CalibrationError(
            "validation_window is scored by the blocks of the HydroModPy pipeline, and a metric "
            "function or another evaluator returns only its cost: remove validation_window."
        )

    # The evaluator is resolved by the name the document wrote, and built with
    # only the options its class names.
    evaluator_options = dict(
        cfg=cfg,
        trial_ctx=trial_ctx,
        space=space,
        workspace=project_root,
        cfg_path=cfg_path,
        metric_fn=metric_fn,
    )
    evaluator = evaluation_registry.create(cfg.evaluator, **evaluator_options)
    if trial_ctx is None and cfg.save_runs != "none" and "save_runs" in cfg.model_fields_set:
        raise CalibrationError(
            f"calibration.evaluator names {getattr(evaluator, 'evaluator_id', cfg.evaluator)!r}, "
            "which runs no HydroModPy model, and save_runs asks for the best trials to be "
            "replayed through the pipeline and written as runs. There is no pipeline to "
            "replay them through: write save_runs = 'none'."
        )
    # Only a model has the Python work threads cannot share. Each worker builds its
    # own evaluator: the one above has checked the document, and leaves here.
    if cfg.parallel > 1 and trial_ctx is not None:
        evaluator = pool_for(type(evaluator), evaluator_options, width=cfg.parallel)

    optimizer = build_optimizer(
        cfg.method,
        space,
        seed=cfg.seed,
        **_engine_kwargs(cfg, space, start_at=start_at),
    )
    cache_context = build_cache_context(
        cfg=cfg,
        trial_ctx=trial_ctx,
        space=space,
        override_paths=override_paths,
        objective_entrypoint=objective,
    )
    refuse_a_phase_another_cost_scored(persistence, context.name, cache_context)
    persistence.record_context(context.name, context_fingerprints(cache_context))

    materialize_root: Path | None = None
    if cfg.materialize_candidates:
        if cfg_path is None:
            raise ValueError(
                "calibration.materialize_candidates is True but no source TOML "
                "is available. Provide cfg_path or run from a TOML-loaded Project."
            )
        from hydromodpy.results.storage.contract import SESSION_CANDIDATES_DIRNAME

        materialize_root = persistence.directory / SESSION_CANDIDATES_DIRNAME
        materialize_root.mkdir(parents=True, exist_ok=True)

    def wrapped_evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        # The evaluator keys the sandbox of the trial and the solve it keeps on
        # the id it is handed: the session number, the one the journal line,
        # the candidate file and the promotion name the trial by.
        number = persistence.assign_trial_number(sugg.trial_id, context)
        result = evaluator.evaluate(TrialRequest(trial_id=number, values=sugg.values))
        # The journal accepts only finite lifecycle states. A "failed" metric
        # error is "infeasible" when the evaluator said so by its prefix, and
        # "crashed" otherwise.
        db_status = result.status
        if result.status == "failed":
            infeasible = (result.error or "").startswith(INFEASIBLE_PREFIX)
            db_status = "infeasible" if infeasible else "crashed"
        meta: dict[str, object] = {}
        if result.error:
            meta["error"] = result.error
            logger.warning("Calibration trial %d %s: %s", sugg.trial_id, db_status, result.error)
        if cfg.persist_iteration_detail == "full":
            meta["block_costs"] = dict(result.components)
        # Drained unconditionally, win or lose: the sink is a thread-local
        # owned by the shared evaluator, and the worker thread that just ran
        # this trial will be reused for another one. Only a completed trial's
        # rows are written; a failed trial's partial rows are dropped here.
        series_sink = getattr(evaluator, "trial_series_sink", None)
        if series_sink is not None:
            rows = series_sink.drain()
            if rows and result.status == "completed":
                meta["trial_series"] = rows
        if materialize_root is not None and cfg_path is not None:
            from hydromodpy.calibration.runners.materialize import materialize_candidate

            try:
                overlay_path = materialize_candidate(
                    cfg_path,
                    dict(sugg.values),
                    space,
                    materialize_root,
                    iteration_index=number,
                )
                meta["materialized_overlay"] = str(overlay_path)
            except Exception as exc:
                logger.warning(
                    "Failed to materialize overlay for trial %d: %s",
                    sugg.trial_id,
                    exc,
                )
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            cost=result.cost,
            status=db_status,
            duration_s=result.duration_s,
            components=dict(result.components) or None,
            metadata=meta,
        )

    # An EvaluationResult carries no parameters, and a cache hit never reaches
    # the evaluator, so the suggestion is the only place the values of a trial
    # are seen. Keeping them is what lets the report name the best candidate.
    values_by_trial: dict[int, dict[str, float]] = {}

    # A mis-configured search fails the same way on every trial. Stopping on a
    # streak refuses it in seconds instead of spending the whole budget and then
    # reporting a best candidate chosen between values that all came from one
    # error.
    failure_watch = ConsecutiveFailureWatch()

    def on_iteration(sugg: ParamSuggestion, result: EvaluationResult) -> None:
        values_by_trial[sugg.trial_id] = {k: float(v) for k, v in sugg.values.items()}
        line = persistence.append_iteration(
            sugg, result, detail=cfg.persist_iteration_detail, phase=context
        )
        rows = (result.metadata or {}).get("trial_series")
        if rows:
            from hydromodpy.results.session.trial_series import write_trial_series

            write_trial_series(persistence.directory, line.trial, rows)
        # After the trial is recorded, so a stopped search still shows what it
        # tried, and only for trials the engine actually ran: a cache hit never
        # reaches this callback.
        failure_watch.record(
            failed=result.status != "completed",
            error=str((result.metadata or {}).get("error") or ""),
        )

    # "auto" becomes the count the engine publishes, so the log and the progress
    # bar show what the run will spend.
    budget = resolve_budget(optimizer, cfg.max_trials)
    logger.info(
        "Calibration %s phase %s | method=%s max_trials=%d save_runs=%s",
        persistence.directory.name,
        context.name,
        cfg.method,
        budget,
        cfg.save_runs,
    )

    engine = CalibrationEngine(
        space=space,
        optimizer=optimizer,
        evaluator=wrapped_evaluator,
        before_batch=lambda batch: persistence.assign_trial_numbers(
            [sugg.trial_id for sugg in batch], context
        ),
        max_trials=budget,
        batch_size=cfg.batch_size,
        parallel=cfg.parallel,
        cache=engine_cache,
        cache_context=cache_context,
        progress=ConsoleProgressReporter(
            cfg.method,
            budget,
            label=getattr(optimizer, "progress_label", None),
        ),
        session_id=persistence.descriptor.session_id,
        on_iteration=on_iteration,
        on_stop=evaluator.close if isinstance(evaluator, TrialWorkerPool) else None,
    )

    t0 = time.perf_counter()
    session = engine.run()
    elapsed = time.perf_counter() - t0
    best = session.best

    # Two parameters that move together among the trials under the cost margin
    # were never told apart by the data: the search stopped on a ridge and reported
    # that point as a minimum. Read off the trace the session already holds, so it
    # costs nothing. With no margin to read, no correlation is reported either.
    trace = calibration_trace(session.history, values_by_trial)
    names = [param.name for param in space]
    width = _width_read_off_the_trials(
        interval_width if interval_width is not None else cfg.interval_width_for(),
        best,
        session.history,
    )
    intervals = (
        []
        if _closes_two_roots(session)
        else _margin_intervals_or_none(trace, names, space, width, session.optimizer)
    )
    pairs = (
        correlated_parameter_pairs(trace, names, threshold=0.0, below_cost=intervals[0].threshold)
        if intervals
        else []
    )
    correlated = [pair for pair in pairs if abs(pair[2]) >= DEFAULT_CORRELATION_THRESHOLD]
    for first, second, coefficient in pairs:
        logger.info("Under the cost margin, %s and %s: r = %+.2f.", first, second, coefficient)
    for first, second, coefficient in correlated:
        logger.warning(
            "Calibration parameters %s and %s moved together (r = %+.2f): the trials under "
            "the cost margin do not tell them apart, so the reported pair is one point on a "
            "ridge.",
            first,
            second,
            coefficient,
        )

    for interval in intervals:
        _log_parameter_interval(interval, best)

    extra: dict[str, Any] = {"interval_width": width.to_dict()}
    if correlated:
        extra["correlated_parameters"] = correlated
    if pairs:
        extra["parameter_correlations"] = pairs
    if intervals:
        extra["parameter_intervals"] = [interval.to_dict() for interval in intervals]
    pairing = _first_trial_pairing(session.history)
    if pairing:
        logger.info(
            "First trial paired: %s",
            "; ".join(
                f"{name} {info['n_paired']} pair(s)"
                + (
                    f" ({info['n_sim_nan']} lost to a NaN simulated value)"
                    if info.get("n_sim_nan")
                    else ""
                )
                + (f" from {info['start']} to {info['end']}" if "start" in info else "")
                for name, info in pairing.items()
            ),
        )
        extra["first_trial_pairing"] = pairing
    extra.update(
        _network_ratios_extra(
            network_outputs=[
                name for name, output in (cfg.outputs or {}).items() if output.support == "network"
            ],
            components=best.components if best is not None else None,
            best_parameters=values_by_trial.get(best.trial_id) if best is not None else None,
            space=space,
            trial_ctx=trial_ctx,
        )
    )
    extra.update(_search_outcome_extra(session))
    extra.update(_r_optim_verdict_extra(cfg.outputs, best.components if best else None))
    # Read by the console recap, which cannot reach the configuration.
    extra["parameter_units"] = parameter_units(cfg)
    extra["cost_metric"] = cost_metric_label(cfg)
    extra["cost_window"] = declared_window_text(cfg)
    scored = cost_samples(best.components if best is not None else None)
    if scored:
        extra["cost_samples"] = scored
    extra["search_status"] = search_status(session)

    return CalibrationReport(
        session_id=persistence.descriptor.session_id,
        method=cfg.method,
        extra=extra,
        status=extra["search_status"],
        cost_name=session_cost_name(cfg),
        cost_label=extra["cost_metric"],
        n_trials=len(session.history),
        best_cost=best.cost if best else None,
        best_trial=persistence.trial_number(best.trial_id, context) if best else None,
        best_parameters=values_by_trial.get(best.trial_id) if best else None,
        cost_block_fractions=_phase_cost_block_fractions(cfg, session.history, best),
        duration_s=float(session.duration_s if session.duration_s else elapsed),
        save_runs=cfg.save_runs,
        promoted=0,
        workspace=project_root,
        session_dir=persistence.directory,
    )


def search_status(session: CalibrationSession) -> SessionStatus:
    """Return the status a finished search leaves its phase in.

    ``completed`` when every trial ran and the search settled (its rule met,
    its plan exhausted, or the budget of a search with no rule of its own
    spent); ``partial`` when trials ran but some failed, the budget ended
    before a rule the engine has, or a root closed outside the declared bounds;
    ``failed`` when nothing completed.
    """
    n_total = len(session.history)
    n_ok = sum(1 for item in session.history if item.status in ("completed", "cached"))
    if n_total == 0 or n_ok == 0:
        return "failed"
    if (
        n_ok < n_total
        or not session.settled
        or "root_outside_bounds" in (_root_search_record(session) or {})
    ):
        return "partial"
    return "completed"


def session_status_of(reports: Sequence[CalibrationReport]) -> SessionStatus:
    """Return the status of a session from the searches it ran, the worst winning."""
    statuses = [str(report.extra.get("search_status", "completed")) for report in reports]
    if not statuses or "failed" in statuses:
        return "failed"
    if "partial" in statuses:
        return "partial"
    return "completed"


def calibrated_status(status: SessionStatus) -> CalibrationSessionStatus:
    """Return how the seal of a promoted run names the session that promoted it."""
    return "aborted" if status in ("aborted", "failed") else status


def answered_best(
    persistence: CalibrationPersistence, report: CalibrationReport, phase: str
) -> tuple[BestTrial | None, list[ScoredSamples]]:
    """Return the pointer and the scored samples of the trial the search answered with.

    A tie on the cost can set that trial apart from the lowest cost of the journal.
    """
    line = persistence.answered_trial(report.best_trial, phase) or persistence.best_trial(phase)
    case_id = persistence.case_id
    components = None if line is None else line.cases[case_id].components
    return persistence.best_pointer(line), scored_samples(components, case_id=case_id)


def promote_and_close(
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext | None,
    persistence: CalibrationPersistence,
    project_root: Path,
    report: CalibrationReport,
    phase: str,
    status: SessionStatus,
    stop_note: str | None = None,
    widths: Mapping[str, ParameterWidth] | None = None,
) -> CalibrationReport:
    """Promote the trials of ``phase`` and close the session; return the final report.

    ``stop_note`` names the phases of a staged session that froze the best of
    a budget-only search or closed a root outside its bounds, written in
    ``session.json``. ``widths`` is the width of each calibrated value.
    """
    stop_state, stopping_rule = search_stop(report, persistence, phase)
    promotion = PromotionOutcome()
    if trial_ctx is not None and cfg.save_runs != "none" and status != "failed":
        promotion = promote_session(
            cfg=cfg,
            trial_ctx=trial_ctx,
            persistence=persistence,
            project_root=project_root,
            phase=phase,
            session_status=calibrated_status(status),
            override_paths=resolve_override_paths(cfg),
            stop_state=stop_state,
            stopping_rule=stopping_rule,
            answered=report.best_trial,
        )
    final_status: SessionStatus = status
    error: str | None = None
    if promotion.failures:
        # The search is sound and kept; only the written runs are missing.
        final_status = "partial"
        error = "; ".join(promotion.failures)
        logger.error(
            "Promotion failed for %d of %d run(s) of session %s; the search results are "
            "kept, the failed runs were not written.",
            len(promotion.failures),
            len(promotion.failures) + promotion.count,
            persistence.directory.name,
        )
    elif final_status == "partial":
        error = _why_partial(persistence, report, stop_note)
    elif final_status == "failed":
        failed = _failed_trials(persistence)
        error = f"no trial completed; {failed}" if failed else "no trial completed"
    persistence.refresh_phase_best(phase)
    pointer, scored = answered_best(persistence, report, phase)
    descriptor = persistence.finalize_session(
        status=final_status,
        best=pointer,
        error=error,
        root_search={key: report.extra[key] for key in ("bracket", "roots") if key in report.extra},
        scored=scored,
        stop_state=stop_state,
        stopping_rule=stopping_rule,
        stop_note=stop_note,
        widths=widths,
    )
    write_session_readme(persistence)
    extra = dict(report.extra)
    if promotion.failures:
        # Read by the console recap and the CLI exit code. The search itself is
        # sound and kept: only the replayed runs are missing.
        extra["promotion_failures"] = list(promotion.failures)
    return replace(
        report,
        extra=extra,
        status=final_status,
        promoted=promotion.count,
        cost_name=descriptor.cost_name,
        cost_label=descriptor.cost_label,
        best_cases={} if pointer is None else dict(pointer.cases),
        windows=dict(descriptor.windows),
    )


def search_stop(
    report: CalibrationReport, persistence: CalibrationPersistence, phase: str
) -> tuple[StopState | None, str | None]:
    """Return why the search of ``phase`` stopped, and the rule it stops on.

    Read on the search record of the report, or, for a phase reused from disk,
    whose report carries none, on the descriptor of that phase.
    """
    search = report.extra.get("search")
    if isinstance(search, Mapping):
        return search.get("stop_state"), search.get("stopping_rule")
    reused = persistence.phase(phase)
    if reused is not None:
        return reused.stop_state, reused.stopping_rule
    return None, None


def _why_partial(
    persistence: CalibrationPersistence, report: CalibrationReport, note: str | None = None
) -> str:
    """Say why a search closed ``partial``: failed trials, rule not met, what ``note`` says.

    A search can meet its stopping rule and still close ``partial`` because a
    trial failed; the message then names the trials, not the rule.
    """
    failed = _failed_trials(persistence)
    reasons = [failed] if failed else []
    search = report.extra.get("search") or {}
    if search and not settled(search["stop_state"], search["stopping_rule"]):
        reasons.append(f"stopping rule ({search.get('stopping_rule')}) not met")
    if note:
        reasons.append(note)
    return "; ".join(reasons) or "stopping rule not met"


def _failed_trials(persistence: CalibrationPersistence) -> str | None:
    """Name the trials of the session that failed or crashed, the first ten in full."""
    failed = [
        line.trial
        for line in persistence.trials()
        if line.status in ("failed", "crashed", "infeasible")
    ]
    if not failed:
        return None
    shown = ", ".join(str(number) for number in failed[:10])
    more = f" and {len(failed) - 10} more" if len(failed) > 10 else ""
    return f"{len(failed)} trial(s) failed: trial {shown}{more}"


def pointer_phase(persistence: CalibrationPersistence, phase: str) -> str:
    """Return the phase whose best trial a closed session points at.

    The last completed phase, or ``phase``, the one under way, when no phase
    completed.
    """
    completed = [item for item in persistence.phases() if item.status == "completed"]
    return completed[-1].name if completed else phase


def abort_session(persistence: CalibrationPersistence, *, phase: str, error: str) -> str:
    """Write ``aborted``, mark the cut phase, and point at the best trial so far.

    Three small writes and nothing else: the signal that ends the process may
    be followed by one that cannot be caught. ``phase`` is the phase under
    way; its descriptor, when it has one, goes to ``aborted`` with its own
    best trial. Returns the phase the session pointer was read from
    (:func:`pointer_phase`).
    """
    cut = persistence.phase(phase)
    if cut is not None and cut.status == "running":
        persistence.finish_phase(
            phase, status="aborted", best=persistence.best_pointer(persistence.best_trial(phase))
        )
    pointed = pointer_phase(persistence, phase)
    persistence.finalize_session(
        status="aborted",
        best=persistence.best_pointer(persistence.held_trial(pointed)),
        error=error,
        widths=persistence.phase_widths(),
    )
    return pointed


def fail_session(persistence: CalibrationPersistence, *, phase: str, error: str) -> None:
    """Write ``failed`` with the error, pointing at the best trial so far."""
    persistence.finalize_session(
        status="failed",
        best=persistence.best_pointer(persistence.held_trial(pointer_phase(persistence, phase))),
        error=error,
        widths=persistence.phase_widths(),
    )


@dataclass
class SessionScope:
    """What closing a session needs, filled in as a runner goes.

    ``phase`` is the phase under way, the one an interruption cuts, and
    ``trial_ctx`` the prepared model of that phase, whose kept solves and
    scratch are released on every exit. ``persistence`` is None until the
    runner opened the session.
    """

    cfg: CalibrationConfig
    project_root: Path
    persistence: CalibrationPersistence | None = None
    trial_ctx: TrialContext | None = None
    phase: str = DEFAULT_PHASE


@contextmanager
def closing_session(scope: SessionScope) -> Iterator[SessionScope]:
    """Close the session of ``scope`` on every exit the runner did not close itself.

    A signal (SIGTERM, SIGINT) writes ``aborted`` and the pointer first
    (:func:`abort_session`), then promotes the pointed trial from its kept
    solve (:func:`promote_best_after_abort`). An error of the search writes
    ``failed`` with its message. The kept solves and the scratch of the phase
    are released last, after the promotion that reads them.
    """
    try:
        # A calibration is hours long, so what ends it is often not a keyboard: a
        # scheduler time limit, a container stop, a plain kill. All of those are
        # SIGTERM, which by default ends the process where it stands and would
        # leave this session running on disk for good. Here, and not in the search,
        # because restarts side by side run it off the main thread.
        with terminate_as_interrupt():
            yield scope
    except KeyboardInterrupt as exc:
        # TerminationRequested is a KeyboardInterrupt: SIGTERM and SIGINT alike.
        if scope.persistence is not None:
            abort_and_promote(
                scope, error="SIGTERM" if isinstance(exc, TerminationRequested) else "SIGINT"
            )
        raise
    except Exception as exc:
        if scope.persistence is not None:
            fail_session(scope.persistence, phase=scope.phase, error=str(exc))
        raise
    finally:
        if scope.persistence is not None:
            scope.persistence.stop_pulse()
        release_trial_solves(scope.trial_ctx)
        release_session_scratch(scope.trial_ctx)


def abort_and_promote(scope: SessionScope, *, error: str) -> PromotionOutcome:
    """Abort the session of ``scope`` and promote its pointed trial from its kept solve."""
    persistence = scope.persistence
    assert persistence is not None
    pointed = abort_session(persistence, phase=scope.phase, error=error)
    promotion = promote_best_after_abort(
        cfg=scope.cfg,
        trial_ctx=scope.trial_ctx,
        persistence=persistence,
        project_root=scope.project_root,
        phase=pointed,
        override_paths=resolve_override_paths(scope.cfg),
    )
    if promotion.best_sim_id is not None:
        persistence.refresh_phase_best(pointed)
        persistence.set_best(persistence.best_pointer(persistence.held_trial(pointed)))
    for failure in promotion.failures:
        logger.error("Promotion after the interruption failed: %s", failure)
    return promotion


def write_session_readme(persistence: CalibrationPersistence) -> Path:
    """Render ``README.md`` of the session from its descriptor, trials and phases."""
    from hydromodpy.results.readme import render_session_readme, write_readme

    text = render_session_readme(
        persistence.descriptor, persistence.trials(), None, phases=persistence.phases()
    )
    return write_readme(persistence.directory, text)


def run_one_search(
    cfg: CalibrationConfig,
    trial_ctx: TrialContext | None,
    *,
    persistence: CalibrationPersistence,
    space: ParameterSpace,
    project_root: Path,
    cfg_path: Path,
    metric_fn: TrialMetricFn | None,
    objective: str | None,
    phase: PhaseContext,
    passed_start: Any | None = None,
    interval_width: IntervalWidth | None = None,
) -> tuple[CalibrationReport, tuple[Any, ...]]:
    """Run one phase, restarts included, and return its report and the restart spread.

    Restarts run side by side, ``parallel`` of them at most, on one pool of
    ``parallel`` workers: a search that holds a prepared model, which is the only one
    that has a pool. The restarts share it, so the budget of the search is the width.
    """
    pools: list[TrialWorkerPool] = []
    guard = threading.Lock()

    def shared_pool(evaluator_class, options, *, width):
        with guard:
            if not pools:
                pools.append(TrialWorkerPool(evaluator_class, options, width=width))
            return pools[0]

    def close_pools() -> None:
        for pool in pools:
            pool.close()

    def _one_search(restart_seed: int, start_at: Any, restart: int = 0) -> CalibrationReport:
        return run_calibration_core(
            cfg
            if restart_seed == (cfg.seed or 0)
            else cfg.model_copy(update={"seed": restart_seed}),
            trial_ctx,
            persistence=persistence,
            space=space,
            project_root=project_root,
            cfg_path=cfg_path,
            metric_fn=metric_fn,
            objective=objective,
            phase=replace(phase, restart=phase.restart + restart),
            start_at=passed_start if start_at is None else start_at,
            interval_width=interval_width,
            pool_for=shared_pool,
        )

    try:
        uncertainty = getattr(cfg, "uncertainty", None)
        if getattr(uncertainty, "method", None) == "multistart":
            logger.info(
                "Running %d restarts: the answer is the best of them, the spread is reported "
                "beside it, and each restart is a full search.",
                int(uncertainty.restarts),
            )
            best, spread = run_restarts(
                _one_search,
                method=cfg.method,
                space=space,
                restarts=int(uncertainty.restarts),
                seed=cfg.seed,
                width=cfg.parallel if trial_ctx is not None else 1,
                on_stop=close_pools,
            )
            _log_restart_spread(spread)
            return best, spread
        return _one_search(cfg.seed or 0, None), ()
    finally:
        close_pools()


def parameter_widths(
    report: CalibrationReport, spread: Sequence[RestartSpread] = ()
) -> dict[str, ParameterWidth]:
    """Return what the report and the restarts say of the width of each value.

    A value nothing was read for is left out. ``correlated`` holds the
    coefficients over the trials under the cost margin, not those of a linearized
    width, which stay in the report beside its sigma. A value combined from two
    roots has no interval: its width is the spread in ``root_search``.
    """
    intervals = {item["name"]: item for item in report.extra.get("parameter_intervals", ())}
    sigmas = {item.parameter: item.sigma for item in report.parameter_uncertainty or ()}
    restarts = {item.parameter: item for item in spread}
    pairs = report.extra.get("parameter_correlations", ())
    widths: dict[str, ParameterWidth] = {}
    for name in report.best_parameters or ():
        width = ParameterWidth(sigma=sigmas.get(name))
        if name in intervals:
            fields = {key: intervals[name][key] for key in CostInterval.model_fields}
            width.interval = CostInterval(**fields)
        if name in restarts:
            item = restarts[name]
            width.restarts = RestartRange(
                lowest=item.lowest, highest=item.highest, values=list(item.values)
            )
        for first, second, coefficient in pairs:
            if name in (first, second):
                width.correlated[second if name == first else first] = coefficient
        if width != ParameterWidth():
            widths[name] = width
    return widths


def _with_linearized_width(
    report: CalibrationReport,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext | None,
    space: ParameterSpace,
) -> CalibrationReport:
    """Attach the linearized width a document asks for, or refuse when nothing can be perturbed."""
    uncertainty = getattr(cfg, "uncertainty", None)
    if getattr(uncertainty, "method", None) != "linearized":
        return report
    if trial_ctx is None:
        raise CalibrationError(
            "uncertainty.method is 'linearized', which perturbs each calibrated value and "
            "rebuilds the model to read the sensitivity off it. The evaluator named here "
            "runs no HydroModPy model, so there is nothing to rebuild. Use 'cost_profile', "
            "which reads the trace the search already produced, or 'multistart'."
        )
    return attach_a_linearized_width(
        report,
        cfg=cfg,
        trial_ctx=trial_ctx,
        space=space,
        perturbation=float(uncertainty.perturbation),
    )


def load_calibration_document(
    config_path: Path | str, workspace: Path | str | None
) -> tuple[Path, Path, CalibrationConfig, dict, str]:
    """Return the file, the project root, the section, the raw TOML and the case of a document."""
    cfg_path = Path(config_path).expanduser().resolve()
    project_root = project_root_for(cfg_path, workspace)
    cfg, raw = load_toml_calibration(cfg_path)
    return cfg_path, project_root, cfg, raw, calibration_case_name(cfg_path)


def run_single_search(
    cfg: CalibrationConfig,
    *,
    space: ParameterSpace,
    cfg_path: Path,
    case: str,
    raw: dict,
    project_root: Path,
    project: str | None,
    metric_fn: TrialMetricFn | None,
    objective: str | None,
    resume: bool,
) -> tuple[CalibrationReport, tuple[RestartSpread, ...]]:
    """Check the name, prepare, open the session, search, attach the width, promote and close.

    The sequence of a calibration without phases, from a TOML or from Python.
    """
    promotion_name_check(case)
    paths = resolve_override_paths(cfg)
    # Asked of the class, before anything is built: preparing trials runs the
    # whole geographic, mesh and data prefix of the pipeline, and an evaluator
    # that replaces the model has no use for the model's setup.
    trial_ctx = (
        prepare_trials(cfg_path, override_paths=paths, parameter_space=space)
        if evaluation_registry.needs_prepared_model(cfg.evaluator)
        else None
    )
    check_the_prepared_model(cfg, trial_ctx, space)
    persistence, _reopened = open_calibration_session(
        project_root,
        case,
        resume=resume,
        raw=raw,
        cfg=cfg,
        space=space,
        trial_ctx=trial_ctx,
        project=project,
        objective=objective,
    )
    keep_trial_solves(cfg, trial_ctx)
    scope = SessionScope(
        cfg=cfg, project_root=project_root, persistence=persistence, trial_ctx=trial_ctx
    )
    with closing_session(scope):
        report, spread = run_one_search(
            cfg,
            trial_ctx,
            persistence=persistence,
            space=space,
            project_root=project_root,
            cfg_path=cfg_path,
            metric_fn=metric_fn,
            objective=objective,
            phase=PhaseContext(DEFAULT_PHASE, 0, 0),
        )
        report = _with_linearized_width(report, cfg, trial_ctx, space)
        report = promote_and_close(
            cfg=cfg,
            trial_ctx=trial_ctx,
            persistence=persistence,
            project_root=project_root,
            report=report,
            phase=DEFAULT_PHASE,
            status=str(report.extra.get("search_status", "completed")),
            stop_note=report.extra.get("root_outside_bounds"),
            widths=parameter_widths(report, spread),
        )
    return report, spread


def _log_restart_spread(spread: Sequence[RestartSpread]) -> None:
    for item in spread:
        logger.info(
            "%s: best %.4g, restarts spanned %.4g to %.4g over %d searches%s.",
            item.parameter,
            item.best,
            item.lowest,
            item.highest,
            len(item.values),
            " - more than a factor ten, so this calibration did not identify it"
            if item.spans_a_decade
            else "",
        )


def describe_dry_run(
    cfg: CalibrationConfig, cfg_path: Path, *, workspace: Path | str | None = None
) -> dict[str, Any]:
    """Return what the calibration of ``cfg`` would do, without writing anything.

    The version is the one the session would reserve now
    (:func:`~hydromodpy.results.catalog.registration.next_version_dirname`); the
    promoted run takes the same directory name under ``runs/``.
    """
    from hydromodpy.results.catalog.registration import next_version_dirname

    project_root = project_root_for(cfg_path, workspace)
    case = calibration_case_name(cfg_path)
    dirname = next_version_dirname(project_root, case)
    phases = [
        {
            "name": decl.name,
            "parameters": list(decl.parameters),
            "max_trials": cfg.max_trials_for(decl),
            "window": declared_window_text(cfg, decl),
        }
        for decl in cfg.phases or ()
    ] or [
        {
            "name": DEFAULT_PHASE,
            "parameters": list(cfg.parameters),
            "max_trials": cfg.max_trials,
            "window": declared_window_text(cfg),
        }
    ]
    return {
        "case": case,
        "project_root": str(project_root),
        "session_dir": session_dir_rel(dirname),
        "run_dir": run_dir_rel(dirname),
        "version": dirname,
        "phases": phases,
        "solves_in_parallel": max(
            [cfg.parallel_for(decl) for decl in cfg.phases or ()] or [cfg.parallel]
        ),
        "save_runs": cfg.save_runs,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@in_run_scratch(
    lambda config_path, **kw: project_root_for(Path(config_path), kw.get("workspace")),
    lambda config_path, **_kw: Path(config_path).stem,
    check=lambda *_a, **kw: refuse_an_objective_that_is_not_an_entry_point(kw.get("objective")),
)
def run_calibration_cli(
    config_path: Path | str,
    *,
    objective: str | None = None,
    workspace: Path | str | None = None,
    project: str | None = None,
    metric_fn: TrialMetricFn | None = None,
    resume: bool = False,
) -> CalibrationReport:
    """Run a calibration described by ``config_path``.

    Parameters
    ----------
    config_path
        Path to a TOML that declares ``[calibration]`` plus the full
        ``[simulation]`` / ``[flow]`` / ``[data]`` blocks.
    objective
        Optional escape hatch: ``"module.path:callable"`` selects the
        RAM metric extractor. ``metric_fn`` wins when both are given;
        a value that is not an entry point is refused.
    workspace
        Override the project root (defaults to the one resolved from the
        location of the TOML).
    project
        Project name written in the outcome of the session. Unset, the name
        of the project root folder.
    metric_fn
        Programmatic override for the metric extractor.
    resume
        Reopen the latest session of the case instead of starting a new one;
        the trials already journaled preload the cache.
    """
    cfg_path, project_root, cfg, raw, case = load_calibration_document(config_path, workspace)
    cfg = with_its_method(cfg)
    report, _spread = run_single_search(
        cfg,
        space=space_from_config(cfg),
        cfg_path=cfg_path,
        case=case,
        raw=raw,
        project_root=project_root,
        project=project,
        metric_fn=metric_fn,
        objective=objective,
        resume=resume,
    )
    return report


def session_method(cfg: CalibrationConfig) -> str:
    """Return the search method a session journals.

    The method the document runs (``CalibrationConfig.method_for``), chosen
    from what the search scores when the file names none. A staged document
    names the method of each phase, joined in declaration order.
    """
    if cfg.phases:
        return " + ".join(cfg.method_for(phase)[0] for phase in cfg.phases)
    return cfg.method_for()[0]


def refuse_a_phase_another_cost_scored(
    persistence: CalibrationPersistence, phase_name: str, cache_context: Mapping[str, Any]
) -> None:
    """Refuse to add trials to a phase whose earlier trials another cost scored.

    A reopened session (``--resume``, ``--phase``) keeps its journal, and the
    best trial is chosen over every line of the phase. A document changed in
    anything that moves a cost (model, input files, outputs, objective, scoring
    window) would let a trial scored the old way be promoted under the new one.
    A changed budget, method, precision or bound moves no cost and passes.
    """
    differ, unchecked = trials_another_cost_scored(
        persistence, phase_name, cache_context=cache_context
    )
    if differ:
        changed = differing_members(
            persistence.recorded_context(phase_name), context_fingerprints(cache_context)
        )
        raise CalibrationError(
            f"{persistence.directory.name} holds {len(differ)} trial(s) of phase "
            f"{phase_name!r} that this document does not score the same way: "
            f"{', '.join(changed) or 'the cost'} changed since they ran. A session keeps "
            "one cost, so that its best trial is a fair pick. Start a new session (drop "
            "--resume or --phase), or give the variant its own --case."
        )
    if unchecked:
        logger.warning(
            "%d trial(s) of phase %r in %s recorded no fingerprint: this run cannot check "
            "that the same cost scored them.",
            len(unchecked),
            phase_name,
            persistence.directory.name,
        )


def refuse_a_changed_cost(
    persistence: CalibrationPersistence,
    phase_name: str,
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext | None,
    space: ParameterSpace,
    objective: str | None,
) -> None:
    """Refuse, writing nothing, a reopening whose cost differs from the journal's.

    Run before :meth:`CalibrationPersistence.resume_session` and ``start_phase``,
    so that a refusal leaves the session on disk as it was.
    """
    cache_context = build_cache_context(
        cfg=cfg,
        trial_ctx=trial_ctx,
        space=space,
        override_paths=resolve_override_paths(cfg),
        objective_entrypoint=objective,
    )
    refuse_a_phase_another_cost_scored(persistence, phase_name, cache_context)


def open_calibration_session(
    project_root: Path,
    case: str,
    *,
    resume: bool,
    raw: Mapping[str, Any],
    cfg: CalibrationConfig,
    space: ParameterSpace,
    trial_ctx: TrialContext | None,
    project: str | None,
    objective: str | None = None,
) -> tuple[CalibrationPersistence, bool]:
    """Reserve or reopen ``sessions/<case>`` and open its journal.

    A new session freezes the resolved document as ``config.toml`` and writes
    the opening descriptor. A reopened one goes back to ``running`` and keeps
    its trials. Returns the persistence and whether the session was reopened.
    """
    session_dir, reopened = open_session_dir(project_root, case, resume=resume)
    persistence = CalibrationPersistence(session_dir)
    if reopened:
        refuse_a_changed_cost(
            persistence,
            DEFAULT_PHASE,
            cfg=cfg,
            trial_ctx=trial_ctx,
            space=space,
            objective=objective,
        )
        persistence.resume_session()
        persistence.start_pulse()
        return persistence, True
    freeze_session_config(session_dir, raw, cfg)
    persistence.start_session(
        session_id=uuid.uuid4().hex,
        case_id=case,
        site=_site_name(raw),
        project=project or project_root.name,
        config_hash=session_config_hash(raw, trial_ctx),
        hydromodpy_version=HYDROMODPY_VERSION,
        method=session_method(cfg),
        cost_name=session_cost_name(cfg),
        # The value the session keeps is the one of its last phase.
        cost_label=cost_metric_label(cfg, cfg.phases[-1] if cfg.phases else None),
        bounds=session_bounds(space, case),
        windows=search_windows(cfg, raw),
        protocol=_protocol_of_session(cfg, trial_ctx, raw),
    )
    persistence.start_pulse()
    return persistence, False


def _protocol_of_session(
    cfg: CalibrationConfig, trial_ctx: TrialContext | None, raw: Mapping[str, Any] | None = None
) -> SessionProtocol | None:
    """Return the protocol a session follows and where it leaves the publication, or None."""
    declared = cfg.protocol
    if declared is None:
        return None
    base_cfg = getattr(trial_ctx, "base_cfg", None)
    departures = [
        ProtocolDeparture(
            key=item.key,
            here=item.here,
            paper=item.paper,
            value=None if item.value is None else str(item.value),
            always=item.state == "always",
            written=item.written,
        )
        for item in deviations_in_force(
            cfg, getattr(base_cfg, "geographic", None), _metrics_window_of(raw)
        )
        if item.state in ("always", "departs")
    ]
    protocol = get_protocol(declared.name)
    return SessionProtocol(
        name=protocol.name,
        version=protocol.version if declared.version is None else str(declared.version),
        departures=departures,
    )


def _metrics_window_of(raw: Mapping[str, Any] | None) -> Any:
    """Return ``[metrics] window`` of a document, or None."""
    metrics = None if raw is None else raw.get("metrics")
    return metrics.get("window") if isinstance(metrics, Mapping) else None


def _site_name(raw: Mapping[str, Any]) -> str | None:
    """Return ``[site] name`` of a document, or None."""
    site = raw.get("site")
    name = site.get("name") if isinstance(site, Mapping) else None
    return str(name) if name else None


__all__ = [
    "SessionScope",
    "abort_and_promote",
    "abort_session",
    "attach_a_linearized_width",
    "calibrated_status",
    "closing_session",
    "declared_window_text",
    "describe_dry_run",
    "fail_session",
    "load_toml_calibration",
    "open_calibration_session",
    "parameter_widths",
    "refuse_a_changed_cost",
    "pointer_phase",
    "promote_and_close",
    "refuse_an_objective_that_is_not_an_entry_point",
    "resolve_stream_geometry_paths",
    "run_calibration_cli",
    "run_calibration_core",
    "run_one_search",
    "search_status",
    "session_method",
    "session_cost_name",
    "search_stop",
    "session_status_of",
    "write_session_readme",
]
