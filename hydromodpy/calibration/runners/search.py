"""One search of a calibration: the ask/tell loop and what it reports about its result.

:func:`run_calibration_core` drives the loop through :class:`CalibrationEngine`, which
calls the evaluator once per suggestion, and builds the report. :func:`run_one_search`
runs it with its restarts, and :func:`run_single_search` wraps that in a session scope.
The verdicts, intervals and ratios the report carries are computed beside the loop.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from hydromodpy.calibration.config import (
    CalibrationConfig,
    window_bounds,
)
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
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
    stopping_kwargs,
)
from hydromodpy.calibration.persistence import (
    DEFAULT_PHASE,
    CalibrationPersistence,
    PhaseContext,
)
from hydromodpy.calibration.report import (
    NO_OTHER_TRIAL,
    interval_best_is_on_a_bound,
    interval_is_degenerate,
)
from hydromodpy.calibration.runners.failure_watch import INFEASIBLE_PREFIX, ConsecutiveFailureWatch
from hydromodpy.calibration.runners.prepared_model import (
    check_the_prepared_model,
    network_outputs_of,
)
from hydromodpy.calibration.runners.promotion import (
    promotion_name_check,
)
from hydromodpy.calibration.runners.recap import (
    cost_metric_label,
    cost_samples,
    parameter_units,
)
from hydromodpy.calibration.runners.restarts import (
    RestartSpread,
    run_restarts,
    run_side_by_side,
)
from hydromodpy.calibration.runners.state import (
    build_cache_context,
    load_metric_fn_entry_point,
    preload_hash_cache,
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
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.state.layout import stop_flag_for
from hydromodpy.results.derive.stream.geometry import VALIDITY_PROVENANCE_BY_CODE
from hydromodpy.results.session.descriptor import (
    CostInterval,
    ParameterWidth,
    RestartRange,
)

if TYPE_CHECKING:
    from hydromodpy.calibration.optim.engine import CalibrationSession
    from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.calibration.runners.trial import TrialContext

from hydromodpy.calibration.runners.document import (
    declared_window_text,
    refuse_an_objective_that_is_not_an_entry_point,
    resolve_stream_geometry_paths,
    session_cost_name,
    with_its_method,
)
from hydromodpy.calibration.runners.session_scope import (
    SessionScope,
    closing_session,
    keep_trial_solves,
    open_calibration_session,
    promote_and_close,
    refuse_a_phase_another_cost_scored,
    root_search_record,
    search_status,
)

logger = get_logger(__name__)


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
    from hydromodpy.core.units.quantities import factor_to_m_per_s

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
    root_search = root_search_record(session) or {}
    extra.update(root_search)
    if "roots" in root_search:
        _log_the_two_roots(root_search["roots"])
    return extra


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


def phase_cost_block_fractions(
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


def _score_a_trial(
    sugg: ParamSuggestion,
    *,
    evaluator: Any,
    persistence: CalibrationPersistence,
    context: PhaseContext,
    cfg: CalibrationConfig,
    space: ParameterSpace,
    cfg_path: Path | None,
    materialize_root: Path | None,
) -> EvaluationResult:
    """Run one suggestion through the evaluator and journal-ready result."""
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


def _search_extra(
    cfg: CalibrationConfig,
    session: CalibrationSession,
    *,
    space: ParameterSpace,
    values_by_trial: Mapping[int, Mapping[str, float]],
    interval_width: IntervalWidth | None,
    trial_ctx: TrialContext | None,
) -> dict[str, Any]:
    """Return what the report says about the result: ridge, intervals, ratios, verdicts."""
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
    return extra


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
        or evaluation_registry.evaluators.get(cfg.evaluator).evaluator_id
        != evaluation_registry.DEFAULT_EVALUATOR_ID
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
    evaluator = evaluation_registry.evaluators.create(cfg.evaluator, **evaluator_options)
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
        return _score_a_trial(
            sugg,
            evaluator=evaluator,
            persistence=persistence,
            context=context,
            cfg=cfg,
            space=space,
            cfg_path=cfg_path,
            materialize_root=materialize_root,
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
        stop_flag=stop_flag_for(persistence.directory),
    )

    t0 = time.perf_counter()
    session = engine.run()
    elapsed = time.perf_counter() - t0
    best = session.best

    extra = _search_extra(
        cfg,
        session,
        space=space,
        values_by_trial=values_by_trial,
        interval_width=interval_width,
        trial_ctx=trial_ctx,
    )

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
        cost_block_fractions=phase_cost_block_fractions(cfg, session.history, best),
        duration_s=float(session.duration_s if session.duration_s else elapsed),
        save_runs=cfg.save_runs,
        promoted=0,
        workspace=project_root,
        session_dir=persistence.directory,
    )


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
    bounds: Bounds | None = None,
) -> tuple[CalibrationReport, tuple[RestartSpread, ...]]:
    """Check the name, prepare, open the session, search, attach the width, promote and close.

    The sequence of a calibration without phases, from a TOML or from Python.
    ``bounds`` are the :class:`~hydromodpy.core.runtime.bounds.Bounds` of the
    call that launched it; ``prepare_trials`` builds its context under them.
    """
    promotion_name_check(case)
    paths = resolve_override_paths(cfg)
    # Asked of the class, before anything is built: preparing trials runs the
    # whole geographic, mesh and data prefix of the pipeline, and an evaluator
    # that replaces the model has no use for the model's setup.
    trial_ctx = (
        prepare_trials(cfg_path, override_paths=paths, parameter_space=space, bounds=bounds)
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
