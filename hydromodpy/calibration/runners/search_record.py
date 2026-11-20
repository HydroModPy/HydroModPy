"""What a search writes into the trial journal: the trace, the extras and the interval lines."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from hydromodpy.calibration.optim.adapters.bisection_adapter import (
    BOUNDS_COMPONENT,
    ROOT_BOUNDS,
    BisectionAdapter,
)
from hydromodpy.calibration.optim.cost_margin import (
    IntervalWidth,
    ParameterInterval,
    margin_intervals,
)
from hydromodpy.calibration.optim.engine import CalibrationSession
from hydromodpy.calibration.optim.optimizer import EvaluationResult
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.report import (
    NO_OTHER_TRIAL,
    interval_best_is_on_a_bound,
    interval_is_degenerate,
)
from hydromodpy.calibration.runners.session_scope import root_search_record
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scoring.stream_defaults import VALIDITY_PROVENANCE_BY_CODE

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


def margin_intervals_or_none(
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


def width_read_off_the_trials(
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


def log_parameter_interval(interval: ParameterInterval, best: EvaluationResult | None) -> None:
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


def r_optim_verdict_extra(
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


def network_ratios_extra(
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


def search_outcome_extra(session: CalibrationSession) -> dict[str, Any]:
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


def closes_two_roots(session: CalibrationSession) -> bool:
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
