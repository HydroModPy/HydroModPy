"""What the end of a calibration tells its reader, read off the run itself.

The console recap of ``hmp calibrate`` names, for each phase, the best value of
each parameter with its unit, the cost it reached, the metric that cost is and
the pairs it was scored on, the run promoted from it and the session folder
that holds its trials. Those
facts are known to the runner and to nobody after it, so the runner records
them in the report and the CLI only formats them.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibPhaseDecl,
    CalibrationConfig,
)
from hydromodpy.calibration.criteria.registry import NETWORK_ESTIMATORS
from hydromodpy.calibration.criteria.series import HIGHER_IS_BETTER
from hydromodpy.calibration.report import (
    NO_OTHER_TRIAL,
    interval_is_degenerate,
    samples_text,
    scored_entry,
)
from hydromodpy.results.checks import stop_line
from hydromodpy.results.metric_rule import CALIBRATION_ROLE
from hydromodpy.results.session.descriptor import ScoredSamples
from hydromodpy.results.storage.contract import SESSION_METHODS_FILENAME


def cost_metric_label(cfg: CalibrationConfig, phase: CalibPhaseDecl | None = None) -> str:
    """Name what the cost of a search is, the way a reader reads it.

    A score that rises with agreement (NSE, KGE) is minimized as one minus
    itself, so the label says ``1 - nse_log`` rather than ``nse_log``. A block
    that divides its cost by a reference scale, or transforms it, says so:
    ``log10(rmse / sd(observed))``. A cost of several blocks is their weighted
    sum and names each block. ``phase`` reads the blocks that phase scores;
    ``None`` reads the whole section.
    """
    if phase is not None and phase.is_single_metric:
        return _reading(phase.objective or cfg.objective)
    blocks = [block for block, _weight in cfg.objective_blocks_for(phase)]
    if len(blocks) == 1:
        return _block_reading(blocks[0])
    if blocks:
        parts = ", ".join(f"{block.name} {_block_reading(block)}" for block in blocks)
        return f"weighted sum of {parts}"
    return _reading(cfg.objective)


def _reading(metric: str) -> str:
    """Return how a cost built on ``metric`` reads."""
    return f"1 - {metric}" if str(metric) in HIGHER_IS_BETTER else str(metric)


def _block_reading(block: CalibObjectiveBlockDecl) -> str:
    """Return how the cost of one block reads, scale and cost transform included."""
    text = _reading(block.metric)
    if block.normalize_cost:
        scale = "validity_length" if str(block.metric) in NETWORK_ESTIMATORS else "sd(observed)"
        text = f"{text} / {scale}"
    if block.cost_transform == "log":
        return f"log10({text})"
    if block.cost_transform == "inverse":
        return f"-1 / ({text})"
    return text


def cost_samples(components: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Return, per dated output, the pairs a trial's cost was scored on.

    The block route writes ``<name>.n_paired`` and, as ordinal days,
    ``<name>.date_start`` / ``<name>.date_end`` into the components of every
    trial: the first and last period-end stamp it kept. ``<name>.n_sim_nan``
    counts the pairs a NaN simulated value took out. ``variable`` +
    ``objective`` is scored by that route too, its outputs named
    ``<variable>@<station>``. Empty when no output was paired, as for a
    network distance.
    """
    found = dict(components or {})
    names = sorted({key.rsplit(".", 1)[0] for key in found if key.endswith(".n_paired")})
    samples: dict[str, dict[str, Any]] = {}
    for name in names:
        entry: dict[str, Any] = {"n_paired": int(found[f"{name}.n_paired"])}
        lost = found.get(f"{name}.n_sim_nan")
        if lost is not None:
            entry["n_sim_nan"] = int(lost)
        start = found.get(f"{name}.date_start")
        end = found.get(f"{name}.date_end")
        if start is not None and end is not None:
            entry["start"] = date.fromordinal(int(start)).isoformat()
            entry["end"] = date.fromordinal(int(end)).isoformat()
        samples[name] = entry
    return samples


def scored_samples(
    components: Mapping[str, Any] | None, *, case_id: str, window: str = CALIBRATION_ROLE
) -> list[ScoredSamples]:
    """Return :func:`cost_samples` as the descriptor of a session records it."""
    return [
        scored_entry(name, info, case_id=case_id, window=window)
        for name, info in cost_samples(components).items()
    ]


def parameter_units(cfg: CalibrationConfig) -> dict[str, str]:
    """Return the declared unit of each calibrated parameter, ``-`` when none."""
    return {name: str(param.units or "-") for name, param in cfg.parameters.items()}


def write_methods(session_dir: Path, paragraph: str) -> Path:
    """Write the methods paragraph beside the trials and return its path."""
    path = Path(session_dir) / SESSION_METHODS_FILENAME
    path.write_text(f"# Methods\n\n{paragraph.strip()}\n", encoding="utf-8")
    return path


def percent(share: float) -> str:
    """Return a share of the cost as a percentage a reader cannot misread.

    Whole per cents, except near the ends: a share below 1 % keeps one
    significant digit, so a block weighted 1000 to 1 reads 0.1 % and not 0 %,
    which would say it is off. A share above 99 % keeps as many decimals as its
    complement, so the two blocks of that pair still add up to 100 %.
    """
    value = float(share) * 100.0
    if 0.0 < value < 1.0:
        rounded, decimals = _one_significant_digit(value)
        return f"{rounded:.{decimals}f}%"
    if 99.0 < value < 100.0:
        rounded, decimals = _one_significant_digit(100.0 - value)
        return f"{100.0 - rounded:.{decimals}f}%"
    return f"{value:.0f}%"


def _one_significant_digit(value: float) -> tuple[float, int]:
    """Return ``value`` rounded to one significant digit, and its decimals in plain notation."""
    import math

    decimals = max(0, -math.floor(math.log10(value)))
    rounded = round(value, decimals)
    return rounded, max(0, -math.floor(math.log10(rounded)))


def shares_text(shares: dict[str, float]) -> str:
    """Return one block-per-token rendering of a share mapping, as percentages."""
    return ", ".join(f"{name} {percent(value)}" for name, value in shares.items())


def result_lines(result: Any) -> list[str]:
    """Return the lines to print for a finished calibration.

    Reads only what :class:`hydromodpy.calibration.report.CalibrationReport`
    already carries: the best value per parameter, the cost it was reached
    at, the metric that cost is (``extra["cost_metric"]``) and the pairs it was
    scored on (``extra["cost_samples"]``, ``extra["cost_window"]``), the interval or
    width beside a value when the run produced one, a
    caution when the trials could not tell two parameters apart, ``k_over_r``
    when a network calibration published one in ``extra``, and, when the
    phase declared two or more objective blocks, the mean share of the cost
    each one actually took (with how many trials the mean covers) and its
    share at the best trial. A phase reused from disk that could not
    recompute a share prints why instead
    (``extra["cost_block_fractions_absent_note"]``). A root search on one
    bound prints its final ``bracket``; a root search on two bounds prints
    ``roots`` instead, one line per bound then the spread and the combined
    value (:func:`_roots_lines`). Returns nothing for a
    result that carries no ``best_parameters`` (a run that evaluated no
    candidate), so the caller stays silent rather than guessing.
    """
    best_parameters = getattr(result, "best_parameters", None)
    if not best_parameters:
        return []

    widths = {item.parameter: item for item in getattr(result, "parameter_uncertainty", ())}
    extra = getattr(result, "extra", None) or {}
    intervals = {item["name"]: item for item in extra.get("parameter_intervals", [])}
    units = extra.get("parameter_units") or {}

    lines: list[str] = []
    for name, value in best_parameters.items():
        line = f"  {name} = {value:.6g}"
        if units.get(name, "-") != "-":
            line += f" {units[name]}"
        width = widths.get(name)
        interval = intervals.get(name)
        if width is not None:
            line += f"  (sigma {width.sigma:.3g})"
        elif interval is not None and interval_is_degenerate(interval):
            line += f"  ({NO_OTHER_TRIAL})"
        elif interval is not None:
            line += f"  [{interval['lower']:.6g}, {interval['upper']:.6g}]"
        if interval is not None and (
            interval["reaches_lower_bound"] or interval["reaches_upper_bound"]
        ):
            line += "  -- reached the search bound"
        lines.append(line)

    best_cost = getattr(result, "best_cost", None)
    if best_cost is not None:
        # A cost of 0.12 on an NSE reads as a poor score; the metric says it is 1 - NSE.
        metric = extra.get("cost_metric")
        lines.append(f"  cost: {best_cost:.6g}" + (f" ({metric})" if metric else ""))
        scored = scored_on_line(extra)
        if scored:
            lines.append(f"  scored on: {scored}")
    best_rel_dir = getattr(result, "best_rel_dir", None)
    if best_rel_dir:
        lines.append(f"  calibrated run: {best_rel_dir}")

    reported_tradeoff = False
    for name, width in widths.items():
        tradeoff = width.strongest_tradeoff()
        if tradeoff is not None and abs(tradeoff[1]) >= 0.9:
            lines.append(
                f"  caution: {name} and {tradeoff[0]} trade off (r = {tradeoff[1]:+.2f}), "
                "not identified separately."
            )
            reported_tradeoff = True
    if not reported_tradeoff:
        for first, second, coefficient in extra.get("correlated_parameters", []):
            lines.append(
                f"  caution: {first} and {second} moved together (r = {coefficient:+.2f}), "
                "not identified separately."
            )

    if "k_over_r_note" in extra:
        lines.append(f"  {extra['k_over_r_note']}")
    elif "k_over_r" in extra:
        lines.append(f"  k_over_r = {extra['k_over_r']:.4g}")

    for name, verdict in sorted((extra.get("r_optim_verdict") or {}).items()):
        lines.append(f"  {_r_optim_line(name, verdict)}")
    if extra.get("bracket"):
        lines.append(f"  {_bracket_line(extra['bracket'])}")
    if extra.get("roots"):
        lines.extend(f"  {line}" for line in _roots_lines(extra["roots"]))
    if extra.get("search"):
        lines.append(f"  {search_line(extra['search'])}")

    shares = getattr(result, "cost_block_fractions", None) or {}
    mean_shares = shares.get("mean")
    if mean_shares and len(mean_shares) > 1:
        n_trials = shares.get("mean_n_trials")
        mean_label = (
            f"mean over {n_trials} finished trials"
            if n_trials is not None
            else "mean over the finished trials"
        )
        lines.append(f"  cost share ({mean_label}): {shares_text(mean_shares)}")
        best_shares = shares.get("best")
        if best_shares:
            lines.append(f"  cost share (best trial): {shares_text(best_shares)}")
    elif "cost_block_fractions_absent_note" in extra:
        lines.append(f"  cost share: {extra['cost_block_fractions_absent_note']}")

    return lines


def scored_on_line(extra: Mapping[str, Any]) -> str | None:
    """Return the pairs the best cost was scored on, and the window it declares.

    A cost that paired no record, a network distance, prints only its window.
    """
    window = extra.get("cost_window")
    samples = extra.get("cost_samples")
    if samples:
        return f"{samples_text(samples)}, best trial" + (f" ({window})" if window else "")
    if window:
        return f"{window}, pairs not counted"
    return None


def _r_optim_line(name: str, verdict: Mapping[str, Any]) -> str:
    """Return the Eq. 4 verdict of one network output, read at the returned trial.

    Eq. 4 bounds ``D_optim`` by the validity length, in meters; ``r_optim`` is
    printed beside it as the paper's ratio.
    """
    length = verdict.get("validity_length_m")
    provenance = verdict.get("provenance")
    bound = f"{float(length):.4g} m" if length is not None else "not published"
    if provenance:
        bound += f" ({provenance})"
    causes = list(verdict.get("causes") or [])
    value = verdict.get("value")
    optimal = verdict.get("D_optim")
    if "empty" in causes or optimal is None:
        return (
            f"r_optim ({name}): not a number, the simulated network is empty at the "
            f"returned trial (validity length {bound})"
        )
    ratio = f"{float(value):.3g}" if value is not None else "not a number"
    sign = ">" if "doptim" in causes else "<="
    head = f"r_optim ({name}) = {ratio}, D_optim = {float(optimal):.4g} m {sign} {bound}"
    if verdict.get("valid"):
        return f"{head}, Eq. 4 holds"
    reasons = []
    if "doptim" in causes:
        reasons.append("coarse agreement")
    return f"{head}, Eq. 4 fails: " + ", and ".join(reasons or ["not qualified"])


def _bracket_line(bracket: Mapping[str, Any]) -> str:
    """Return the root search's final bracket, in the parameter's own units."""
    state = "closed" if bracket.get("closed") else "open, the budget ran out first"
    return (
        f"bracket on {bracket['parameter']}: [{float(bracket['low']):.6g}, "
        f"{float(bracket['high']):.6g}], width {float(bracket['relative_width']):.2%} ({state})"
    )


def _root_line(bound: str, root: Mapping[str, Any]) -> str:
    """Return one bound's root and its final bracket, in the parameter's own units."""
    state = "closed" if root.get("closed") else "open, the budget ran out first"
    return (
        f"K*_{bound} = {float(root['k_star']):.6g}, bracket [{float(root['low']):.6g}, "
        f"{float(root['high']):.6g}], width {float(root['relative_width']):.2%} ({state})"
    )


def _roots_lines(roots: Mapping[str, Any]) -> list[str]:
    """Return the two-root search's per-bound roots, their spread and the combined value.

    One line per bound (:func:`_root_line`), then ``Delta = log10(K*_maximal /
    K*_minimal)``, then the value the search returns, the weighted geometric
    mean of the two roots, with its weights.
    """
    lines = [_root_line("minimal", roots["minimal"]), _root_line("maximal", roots["maximal"])]
    delta = roots.get("delta_log10")
    delta_text = f"{delta:.3g}" if delta is not None else "unknown"
    lines.append(f"Delta = log10(K*_maximal / K*_minimal) = {delta_text} decade(s)")
    weights = f"{float(roots['minimal']['weight']):.3g} / {float(roots['maximal']['weight']):.3g}"
    value = roots.get("value")
    if value is None:
        lines.append(f"{roots['parameter']}: not solved (weighted geometric mean, {weights})")
    else:
        lines.append(
            f"{roots['parameter']} = {float(value):.6g}, weighted geometric mean of the "
            f"two roots ({weights})"
        )
    return lines


def search_line(search: Mapping[str, Any]) -> str:
    """Return why the search stopped, whether that is convergence, and what it spent."""
    spent = f"{search.get('n_evaluations')} evaluation(s) of {search.get('max_trials')} declared"
    extension = int(search.get("extension") or 0)
    if extension:
        spent += f" + {extension} extension"
    return f"search: {stop_line(search.get('stop_state'), search.get('stopping_rule'))}, {spent}"


def staged_result_lines(result: Any) -> list[str]:
    """Return the lines to print for a finished staged calibration.

    Formats each phase's report with :func:`result_lines`
    and prefixes it with the phase's name, so a staged run prints as much per
    phase (cost, interval, cost share) as a single search prints for itself.
    """
    lines: list[str] = []
    for phase_run in getattr(result, "phases", ()):
        phase_lines = result_lines(getattr(phase_run, "report", None))
        if not phase_lines:
            continue
        lines.append(f"phase {phase_run.name}:")
        lines.extend(phase_lines)
        stop_note = getattr(phase_run, "stop_note", None)
        if stop_note:
            lines.append(f"  {stop_note}")
    return lines


__all__ = [
    "cost_metric_label",
    "cost_samples",
    "parameter_units",
    "percent",
    "result_lines",
    "scored_samples",
    "search_line",
    "shares_text",
    "staged_result_lines",
    "write_methods",
]
