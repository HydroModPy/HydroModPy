"""The two phases of a downslope-distance calibration, on one page.

The subject is the ``Session`` of a staged calibration: a root search closes a
bracket on ``K/R``, then a storage phase fits a second parameter. The reading
rules of the four panels are in ``display/figures/README.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import numpy as np

from hydromodpy.core.scoring.stream_defaults import VALIDITY_PROVENANCE_BY_CODE
from hydromodpy.display.figure import PROMOTED_OPTION, BaseFigure, FigureSpec, run_suffix
from hydromodpy.display.figure_options import Opt, OutputName, ParameterUnits
from hydromodpy.display.figures._calibration_session import (
    as_mapping,
    float_or,
    int_or_none,
    phase_descriptors,
    returned_row,
    session_config,
    text,
    two_roots,
)
from hydromodpy.display.figures._stream_comparison import (
    CRITERION_NAMES,
    agreement_color,
    class_label,
    note_box,
)
from hydromodpy.display.figures._trial_diagnostics import TrialTable, trial_table
from hydromodpy.display.figures.network_extent_bounds_map import (
    SIMULATED_MAXIMAL_COLOR,
    SIMULATED_MINIMAL_COLOR,
)
from hydromodpy.display.style import HIGH_CONTRAST_TRIPLET, place_legend

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.session.view import Session

VALIDITY_PROVENANCE_LABELS: dict[str, str] = {
    "auto": "two cells, 2 h_obs",
    "declared_accuracy": "widened by the declared positional accuracy",
    "user": "the declared validity_length",
}
"""What set the validity length, as the note under the bar says it."""

CLASS_NAMES: tuple[str, ...] = tuple(CRITERION_NAMES.values())
"""The three classes of the confusion map, in the order the card stacks them."""

RECHARGE_KEY: str = "R_mean_m_s"
"""The key the criterion publishes the mean recharge under (``display`` cannot import it)."""

BOUNDS: tuple[str, str] = ("minimal", "maximal")
"""The two bounds of an extent, suffixing their components ``_<bound>``."""

VALIDATION_SUFFIX: str = "_validation"
"""Appended to the bound suffix of the map a one-state output scores outside its cost."""

H_OBS_KEY: str = "h_obs"
"""The key the criterion publishes ``h_obs`` under, the cell size on the map."""

_BOUND_COLORS = {"minimal": SIMULATED_MINIMAL_COLOR, "maximal": SIMULATED_MAXIMAL_COLOR}
_BOUND_HATCH = {"minimal": "", "maximal": "//"}
_TRIAL_COLOR = HIGH_CONTRAST_TRIPLET[0]
_BREACH_COLOR = HIGH_CONTRAST_TRIPLET[2]
_GREY = "0.35"
_ROOT_STAGE = "root search"
_STORAGE_STAGE = "storage"

_Stage = dict[str, Any]  # label, table, descriptor, best
_View = dict[str, Any]  # label, suffix, bound, note, in_verdict


class MatchingHydrographicNetworkCard(BaseFigure):
    """A four-panel synthesis of one staged downslope-distance calibration."""

    spec = FigureSpec(
        name="matching_hydrographic_network_card",
        former_names=("abherve_two_stage_card",),
        title="Matching the hydrographic network: two-stage card",
        kind="comparison",
        subject="session",
        default_figsize=(11.5, 7.5),
    )

    def unavailable_reason(self, session: Session) -> str | None:
        """Refuse a session that journaled no trial."""
        try:
            trial_table(session)
        except ValueError as exc:
            return str(exc)
        return None

    def render(self, session: Session, ax: Axes, **_) -> Axes:
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "matching_hydrographic_network_card is a grid of panels: call plot()",
            ha="center",
            va="center",
        )
        return ax

    def plot(
        self,
        session: Session,
        *,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path: str | Path | None = None,
        parameter: Annotated[
            str | None,
            Opt(
                "Parameter of the first stage, the root search, by name. Left out, the "
                "one that stage sampled."
            ),
        ] = None,
        storage_parameter: Annotated[
            str | None,
            Opt(
                "Parameter of the second stage, the storage fit, by name. Left out, the "
                "one that stage sampled."
            ),
        ] = None,
        output: OutputName = None,
        parameter_units: ParameterUnits = None,
        mean_recharge: Annotated[
            float | None,
            Opt(
                "Mean recharge the ratio K/R is read against, in recharge_units. Left "
                "out, the median R_mean_m_s the trials published, else none."
            ),
        ] = None,
        recharge_units: Annotated[
            str, Opt("Unit written after the mean recharge on the card.")
        ] = "m/s",
        roots: Annotated[
            Mapping[str, Any] | None,
            Opt(
                "Roots record of a two-bound search, as the session journal writes it. "
                "Left out, the one the session recorded.",
                python_only=True,
            ),
        ] = None,
        **opts: Any,
    ) -> MplFigure:
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec

        stages = _stages(session)
        first = stages[0]
        table = first["table"]
        if roots is None:
            roots = two_roots(first["descriptor"])
        recharge = mean_recharge if mean_recharge is not None else _recharge(table, output)
        two = _col(table, "J_signed", output) is None and all(
            _col(table, f"J_signed_{bound}", output) is not None for bound in BOUNDS
        )
        if two:
            searches = [_search(first, parameter, output, bound) for bound in BOUNDS]
            row, views = _two_bound_views(first, roots, output)
        else:
            searches = [_search(first, parameter, output, "")]
            row, views = searches[0]["row"], _one_state_views(table, output)
        missing = "the returned trial is not known" if two else "no root was closed"

        fig = plt.figure(
            figsize=figsize or self.spec.default_figsize, dpi=dpi, constrained_layout=True
        )
        # The two results sit on the top row and what qualifies them underneath.
        grid = GridSpec(2, 2, figure=fig, width_ratios=[1.45, 1.0], height_ratios=[1.0, 0.85])
        ax_root, ax_store = fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1])
        ax_valid, ax_count = fig.add_subplot(grid[1, 0]), fig.add_subplot(grid[1, 1])

        recharge_line = (
            f"mean recharge = {recharge:.4g} {recharge_units}"
            if recharge is not None
            else "mean recharge not declared: the ratio is not a conductivity"
        )
        units = parameter_units or _units(first["descriptor"], searches[0]["name"])
        _panel_root(ax_root, searches, first["label"], units, recharge_line, roots, row, two)
        _panel_storage(ax_store, stages, storage_parameter)
        if row is None:
            _blank(
                ax_valid, "Validity of the agreement", f"{missing}: no calibrated point to qualify"
            )
            _blank(
                ax_count,
                "Cells at the calibrated point",
                f"{missing}: no calibrated point to split",
            )
        else:
            _panel_validity(ax_valid, table, row, views, output)
            _panel_counts(ax_count, table, row, views, output)
        fig.suptitle(
            f"Two-stage calibration card{run_suffix(session)}", fontweight="bold", fontsize=14
        )
        if save_path is not None:
            self._save(fig, Path(save_path), dpi=dpi, sim=opts.get(PROMOTED_OPTION) or session)
        return fig


def _stages(session: Session) -> list[_Stage]:
    """Return one stage per phase by declared rank; a session with no phase is one stage."""
    rows = phase_descriptors(session)
    frame = session.trials
    named = (text(value) for value in frame["phase"]) if "phase" in frame.columns else ()
    names = list(dict.fromkeys(value for value in named if value is not None))
    if not names:
        descriptor = rows.get(None) or next(iter(rows.values()))
        label = text(descriptor.get("phase_name")) or _ROOT_STAGE
        return [_stage(label, trial_table(session), descriptor)]

    def rank(name: str) -> tuple[int, str]:
        index = int_or_none(rows.get(name, {}).get("phase_index"))
        return (names.index(name) if index is None else index, name)

    return [
        _stage(
            name,
            trial_table(session, phase=name),
            rows.get(name) or {**next(iter(rows.values())), "phase_name": name},
        )
        for name in sorted(names, key=rank)
    ]


def _stage(label: str, table: TrialTable, descriptor: dict[str, Any]) -> _Stage:
    return dict(label=label, table=table, descriptor=descriptor, best=descriptor.get("best_trial"))


def _col(table: TrialTable, name: str, output: str | None) -> np.ndarray | None:
    """Return a diagnostic by bare name, None when no trial published it or it is ambiguous."""
    return (
        table.diagnostic(name, output=output) if table.has_diagnostic(name, output=output) else None
    )


def _at(table: TrialTable, row: int | None, name: str, output: str | None) -> float | None:
    """Return one diagnostic at one trial, None when never published or not finite."""
    values = _col(table, name, output)
    if row is None or values is None or not np.isfinite(values[row]):
        return None
    return float(values[row])


def _units(descriptor: Mapping[str, Any], name: str) -> str:
    """Return the unit of a parameter, the journal bounds first, the frozen config second."""
    bound = as_mapping(as_mapping(descriptor.get("bounds")).get(name))
    declared = as_mapping(as_mapping(session_config(descriptor).get("parameters")).get(name))
    return text(bound.get("units")) or text(declared.get("units")) or "-"


def _cost_label(descriptor: Mapping[str, Any]) -> str:
    """Return the metrics of the objective blocks a phase scores on, else its cost name."""
    config = session_config(descriptor)
    name = text(descriptor.get("phase_name"))
    blocks = config.get("objective_blocks")
    for phase in config.get("phases") or ():
        if isinstance(phase, Mapping) and name is not None and phase.get("name") == name:
            blocks = phase.get("objective_blocks") or blocks
            break
    metrics = [
        str(block["metric"])
        for block in blocks or ()
        if isinstance(block, Mapping) and text(block.get("metric"))
    ]
    if metrics:
        return " + ".join(dict.fromkeys(metrics))
    return text(descriptor.get("cost_name")) or "objective"


def _recharge(table: TrialTable, output: str | None) -> float | None:
    """Return the median mean recharge the trials published, None when none did."""
    values = _col(table, RECHARGE_KEY, output)
    finite = [] if values is None else values[np.isfinite(values)]
    return float(np.median(finite)) if len(finite) else None


def _bracket(values: np.ndarray, residual: np.ndarray) -> tuple[int, int] | None:
    """Return the closest pair of samples, by factor, whose residuals change sign."""
    order = [i for i in np.argsort(values, kind="stable") if np.isfinite(values[i] * residual[i])]
    pairs = [
        (a, b)
        for a, b in zip(order[:-1], order[1:], strict=True)
        if residual[a] * residual[b] < 0.0
    ]
    return min(pairs, key=lambda pair: values[pair[1]] / values[pair[0]]) if pairs else None


def _search(stage: _Stage, parameter: str | None, output: str | None, bound: str) -> dict[str, Any]:
    """Return the value and bracket a root search closed on, read at an evaluated trial."""
    table = stage["table"]
    name, values = table.parameter_values(parameter)
    if np.any(np.isfinite(values) & (values <= 0.0)):
        raise ValueError(
            f"the parameter {name!r} carries a non-positive value, and a bracket over "
            "a ratio is measured as a factor between its two ends."
        )
    nan = float("nan")
    out: dict[str, Any] = dict(
        name=name, values=values, bound=bound, row=None, value=nan, low=nan, high=nan, note=""
    )
    residual = _col(table, f"J_signed_{bound}" if bound else "J_signed", output)
    if residual is None:
        out["note"] = "no signed residual published: no bracket can be read"
        return out
    pair = _bracket(values, residual)
    if pair is None:
        out["note"] = "no sign change over the sampled range: no root was closed"
        return out
    low, high = pair
    row = low if abs(residual[low]) <= abs(residual[high]) else high
    out.update(
        row=int(row), value=float(values[row]), low=float(values[low]), high=float(values[high])
    )
    return out


def _view(label: str, suffix: str, bound: str, note: str = "", in_verdict: bool = True) -> _View:
    return dict(label=label, suffix=suffix, bound=bound, note=note, in_verdict=in_verdict)


def _one_state_views(table: TrialTable, output: str | None) -> list[_View]:
    """Return the map in the cost, and the one only validated beside it when there is one."""
    for cost, checked in (("minimal", "maximal"), ("maximal", "minimal")):
        suffix = f"_{checked}{VALIDATION_SUFFIX}"
        if _col(table, f"D_optim{suffix}", output) is not None:
            return [
                _view(cost, "", cost, "in the cost"),
                _view(checked, suffix, checked, "validation outside the cost", False),
            ]
    return [_view("", "", "maximal")]


def _two_bound_views(
    stage: _Stage, roots: Mapping[str, Any] | None, output: str | None
) -> tuple[int | None, list[_View]]:
    """Return the trial a two-root search returned, and the two bounds read on it."""
    record = roots or {}
    table = stage["table"]
    declared = int_or_none(record.get("combined_trial_id"))
    row = None if declared is None else table.row_of_trial(declared)
    if row is None:
        row = returned_row(table, stage["descriptor"])
    views = []
    for bound in BOUNDS:
        weight = _at(table, row, f"weight_{bound}", output)
        if weight is None:
            weight = _number(as_mapping(record.get(bound)).get("weight"))
        in_verdict = weight is None or weight > 0.0
        note = "" if weight is None else f"weight {weight:.3g}"
        note += "" if in_verdict else ", outside the verdict"
        views.append(_view(bound, f"_{bound}", bound, note, in_verdict))
    return row, views


def _number(value: Any) -> float | None:
    """Return ``value`` as a finite float, None when it is not one."""
    number = float_or(value, float("nan"))
    return number if np.isfinite(number) else None


def _say(
    ax: Axes,
    message: str,
    xy: tuple[float, float] = (0.5, 0.5),
    va: str = "center",
    fontsize: int = 9,
) -> None:
    ax.annotate(
        message,
        xy=xy,
        xycoords="axes fraction",
        ha="center",
        va=va,
        fontsize=fontsize,
        bbox=note_box(),
        zorder=6,
    )


def _blank(ax: Axes, title: str, message: str) -> None:
    """Replace a panel by one sentence: nothing is drawn that no trial measured."""
    ax.clear()
    ax.set_axis_off()
    ax.set_title(title)
    _say(ax, message)


def _absent(ax: Axes, message: str, xy: tuple[float, float], fontsize: int = 8) -> None:
    """Say on its own row that a count is absent, never a bar of length zero."""
    ax.annotate(
        message,
        xy=xy,
        xytext=(6, 0),
        textcoords="offset points",
        va="center",
        fontsize=fontsize,
        style="italic",
        color=_GREY,
    )


def _panel_root(
    ax: Axes,
    searches: list[dict[str, Any]],
    label: str,
    units: str,
    recharge_line: str,
    roots: Mapping[str, Any] | None,
    row: int | None,
    two: bool,
) -> None:
    """Panel one: the closed value inside its bracket, one bracket per bound for two roots."""
    first = searches[0]
    ax.set_xscale("log")
    ax.set_ylim(0.0, 1.0)
    ax.set_yticks([])
    ax.set_xlabel(f"{first['name']} ({units})")
    ax.set_title(f"Stage 1 - {label}" + (", two bounds" if two else ""))
    ax.grid(True, which="both", axis="x", ls=":", lw=0.4)
    values = first["values"]
    ax.plot(
        values,
        np.full(values.size, 0.62),
        marker="|",
        ms=16,
        ls="none",
        color=_GREY,
        zorder=3,
        label=f"evaluations of the search ({int(np.isfinite(values).sum())})",
    )
    record = roots or {}
    lines: list[str] = []
    for search in searches:
        bound = search["bound"]
        entry = as_mapping(record.get(bound)) if two else {}
        value, low, high = (_number(entry.get(key)) for key in ("k_star", "low", "high"))
        value = search["value"] if value is None else value
        low = search["low"] if low is None else low
        high = search["high"] if high is None else high
        if not np.isfinite(value):
            lines.append((f"K*_{bound}: " if two else "") + search["note"])
            continue
        color = _BOUND_COLORS[bound] if two else "0.55"
        if np.isfinite(low) and np.isfinite(high):
            ax.axvspan(
                low,
                high,
                color=color,
                alpha=0.30 if two else 0.28,
                linewidth=0.0,
                zorder=1,
                hatch=(_BOUND_HATCH[bound] or None) if two else None,
                label=f"bracket {bound}" if two else "bracket: the two ends that change sign",
            )
        name = f"K*_{bound}" if two else search["name"]
        ax.axvline(
            value,
            color=color if two else "black",
            lw=1.6 if two else 1.4,
            zorder=4,
            label=f"{name} = {value:.4g}",
        )
        if two:
            lines.append(f"K*_{bound} = {value:.4g}, bracket [{low:.4g}, {high:.4g}]")
        else:
            lines += [
                f"closed on {search['name']} = {value:.4g}",
                f"bracket [{low:.4g}, {high:.4g}], a factor {high / low:.4g}",
            ]
    if two:
        lines += _two_root_lines(ax, first["name"], roots)
        if row is not None:
            lines.append(
                f"diagnostics read at the returned trial, {first['name']} = {float(values[row]):.4g}"
            )
    lines.append(recharge_line)
    _say(ax, "\n".join(lines), xy=(0.5, 0.04 if two else 0.06), va="bottom")
    place_legend(ax, fontsize=8, framealpha=0.9)


def _two_root_lines(ax: Axes, name: str, roots: Mapping[str, Any] | None) -> list[str]:
    """Draw the combined value of a two-root search and return the lines that report it."""
    if roots is None:
        return ["roots record not passed: Delta and the combined value are not shown"]
    delta = _number(roots.get("delta_log10"))
    lines = [
        "Delta = log10(K*_maximal / K*_minimal) = "
        + (f"{delta:.3g} decade(s)" if delta is not None else "unknown")
    ]
    combined = _number(roots.get("value"))
    if combined is None:
        return [*lines, "combined value not solved: the search did not converge"]
    ax.axvline(combined, color="black", lw=1.4, ls="--", zorder=5, label=f"{name} = {combined:.4g}")
    weights = " / ".join(
        f"{float_or(as_mapping(roots.get(bound)).get('weight'), float('nan')):.3g}"
        for bound in BOUNDS
    )
    return [*lines, f"combined {name} = {combined:.4g}, weighted geometric mean {weights}"]


def _panel_storage(ax: Axes, stages: list[_Stage], parameter: str | None) -> None:
    """Panel two: the storage value against its cost, or why there is none."""
    first = stages[0]
    if len(stages) < 2:
        declared = as_mapping(session_config(first["descriptor"])).get("phases") or []
        if len(declared) > len(stages):
            following = as_mapping(declared[len(stages)]).get("name") or _STORAGE_STAGE
            _blank(
                ax,
                f"Stage 2 - {following}",
                f"comes next: this run closes stage 1,\n{following} starts from it",
            )
        else:
            _blank(
                ax, "Stage 2 - not run", "second phase not run:\nthis calibration holds one stage"
            )
        return
    stage = stages[1]
    table = stage["table"]
    name, values = table.parameter_values(parameter)
    cost = np.asarray(table.cost_values()[1], dtype=float)
    finite = np.flatnonzero(np.isfinite(cost))
    hit = None if stage["best"] is None else table.row_of_trial(int(stage["best"]))
    if hit is not None and np.isfinite(cost[hit]):
        row: int | None = hit
    else:
        row = int(finite[np.argmin(cost[finite])]) if len(finite) else None
    cost_name = _cost_label(stage["descriptor"])
    ax.set_title(
        f"Stage 2 - {stage['label']}" + (f" (2 of {len(stages)})" if len(stages) > 2 else "")
    )
    ax.set_xlabel(f"{name} ({_units(stage['descriptor'], name)})")
    ax.set_ylabel(f"cost, {cost_name} (-)")
    ax.margins(x=0.10)
    ax.grid(True, ls=":", lw=0.4)
    ax.plot(
        values,
        cost,
        marker="o",
        ms=5.5,
        ls="none",
        color=_TRIAL_COLOR,
        zorder=3,
        label=f"trials ({values.size})",
    )
    lines = []
    if row is None:
        lines.append("no objective published: the storage fit cannot be read")
    else:
        ax.axvline(
            values[row], color="black", lw=1.4, zorder=4, label=f"{name} = {values[row]:.4g}"
        )
        lines += [f"{name} = {values[row]:.4g}", f"cost ({cost_name}) = {cost[row]:.4g}"]
    failed = int((~np.isfinite(cost)).sum())
    if failed:
        lines.append(f"{failed} of {values.size} trials failed")
    low, high = ax.get_ylim()
    # Room under the points for the note.
    ax.set_ylim(low - 0.35 * (high - low), high + 0.10 * (high - low))
    _say(ax, "\n".join(lines), xy=(0.5, 0.04), va="bottom")
    place_legend(ax, fontsize=8, framealpha=0.9)


def _provenance(table: TrialTable, row: int, suffix: str, output: str | None) -> str | None:
    """Return what set the validity length of one map, None when the trial says nothing."""
    code = _at(table, row, f"validity_length_provenance{suffix}", output)
    return VALIDITY_PROVENANCE_LABELS.get(VALIDITY_PROVENANCE_BY_CODE.get(code, ""))


def _validity_lines(table: TrialTable, row: int, view: _View, output: str | None) -> list[str]:
    """Return the reading of one map of the validity panel."""
    suffix = view["suffix"]
    head = view["label"] + (f" ({view['note']})" if view["note"] else "")
    value = _at(table, row, f"D_optim{suffix}", output)
    bound = _at(table, row, f"validity_length_m{suffix}", output)
    if value is None:
        reading = "D_optim not published, not qualified"
    elif bound is None:
        reading = f"D_optim = {value:.4g} m, validity length not published"
    else:
        within = value <= bound
        if view["in_verdict"]:
            verdict = "Eq. 4 holds" if within else "Eq. 4 fails"
        else:
            verdict = ("within" if within else "beyond") + " the bound, no verdict"
        reading = f"D_optim = {value:.4g} m {'<=' if within else '>'} {bound:.4g} m, {verdict}"
    scale = []
    residual = _at(table, row, f"J_signed{suffix}", output)
    if residual is not None:
        scale.append(f"J_signed = {residual:.4g} m")
    ratio = _at(table, row, f"r_optim{suffix}", output)
    h_obs = _at(table, row, f"{H_OBS_KEY}{suffix}", output)
    provenance = _provenance(table, row, suffix, output)
    if ratio is not None:
        scale.append(f"r_optim = {ratio:.4g}")
    if h_obs is not None:
        scale.append(f"h_obs = {h_obs:.4g} m")
    if provenance is not None:
        scale.append(f"length: {provenance}")
    return [f"{head}: {reading}"] + (["    " + ", ".join(scale)] if scale else [])


def _panel_validity(
    ax: Axes, table: TrialTable, row: int, views: list[_View], output: str | None
) -> None:
    """Panel three: D_optim against the validity length the trial bounded it by (Eq. 4)."""
    title = "Validity of the agreement"
    ax.set_yticks([])
    ax.set_xlabel("D_optim = (D_so + D_os) / 2 (m)")
    ax.set_title(title)
    ax.grid(True, axis="x", ls=":", lw=0.4)
    if len(views) == 1:
        value = _at(table, row, "D_optim", output)
        bound = _at(table, row, "validity_length_m", output)
        if value is None or bound is None:
            what = "D_optim" if value is None else "validity length"
            _blank(ax, title, f"{what} not published: the agreement is not qualified")
            return
        within = value <= bound
        bar = ax.barh(
            [0.0], [value], height=0.5, zorder=3, color=_TRIAL_COLOR if within else _BREACH_COLOR
        )
        bar[0].set_label(f"D_optim = {value:.4g} m")
        ax.axvline(
            bound,
            color="black",
            lw=1.3,
            ls="--",
            zorder=4,
            label=f"bound: D_optim <= {bound:.4g} m",
        )
        state = (
            "within the validity bound" if within else "bound breached, the calibrated value stands"
        )
        lines = [f"D_optim = {value:.4g} m {'<=' if within else '>'} {bound:.4g} m: {state}"]
        provenance = _provenance(table, row, "", output)
        if provenance is not None:
            lines.append(f"validity length: {provenance}")
        ratio = _at(table, row, "r_optim", output)
        h_obs = _at(table, row, H_OBS_KEY, output)
        if ratio is not None:
            lines.append(
                f"r_optim = D_optim / h_obs = {ratio:.4g}"
                + (f", h_obs = {h_obs:.4g} m" if h_obs is not None else "")
            )
        _say(ax, "\n".join(lines), xy=(0.5, 0.92), va="top")
        ax.set_xlim(0.0, max(value, bound) * 1.3)
        ax.set_ylim(-0.55, 1.25)
        ax.legend(loc="lower right", fontsize=8, framealpha=0.9)
        return
    ax.set_yticks(range(len(views)), labels=[view["label"] for view in views])
    lines: list[str] = []
    extent = 0.0
    for index, view in enumerate(views):
        lines += _validity_lines(table, row, view, output)
        value = _at(table, row, f"D_optim{view['suffix']}", output)
        bound = _at(table, row, f"validity_length_m{view['suffix']}", output)
        if value is None:
            _absent(ax, f"D_optim {view['label']} not published: absent, not zero", (0.0, index))
            continue
        color = _GREY if bound is None else (_TRIAL_COLOR if value <= bound else _BREACH_COLOR)
        bar = ax.barh(
            [index],
            [value],
            height=0.5,
            color=color,
            hatch=_BOUND_HATCH[view["bound"]] or None,
            edgecolor="white",
            zorder=3,
        )
        bar[0].set_label(f"D_optim {view['label']} = {value:.4g} m")
        extent = max(extent, value)
        if bound is not None:
            ax.plot(
                [bound, bound],
                [index - 0.35, index + 0.35],
                color="black",
                lw=1.3,
                ls="--",
                zorder=4,
                label=f"bound {view['label']}: D_optim <= {bound:.4g} m",
            )
            extent = max(extent, bound)
    _say(ax, "\n".join(lines), xy=(0.5, 0.97), va="top", fontsize=8)
    ax.set_xlim(0.0, (extent or 1.0) * 1.3)
    # Inverted, so the first map reads first, with room above for the note.
    ax.set_ylim(len(views) - 0.4, -0.6 - 1.5 * len(views))


def _panel_counts(
    ax: Axes, table: TrialTable, row: int, views: list[_View], output: str | None
) -> None:
    """Panel four: the three classes side by side, never summed."""
    several = len(views) > 1
    ax.set_yticks(range(len(CLASS_NAMES)), labels=list(CLASS_NAMES))
    ax.invert_yaxis()
    ax.set_xlabel("Cells (-)")
    ax.set_title("Cells at the calibrated point")
    ax.grid(True, axis="x", ls=":", lw=0.4)
    height = 0.8 / len(views) if several else 0.6
    for index, (agreement, name) in enumerate(CRITERION_NAMES.items()):
        for rank, view in enumerate(views):
            where = index + (rank - (len(views) - 1) / 2.0) * height
            which = f" {view['label']}" if several else ""
            count = _at(table, row, f"n_{name}{view['suffix']}", output)
            if count is None:
                _absent(
                    ax,
                    f"{name}{which} not published: absent, not zero",
                    (0.0, where),
                    fontsize=8 if several else 9,
                )
                continue
            hatch = _BOUND_HATCH[view["bound"]] if several else ""
            bars = ax.barh(
                [where],
                [count],
                height=height * (0.95 if several else 1.0),
                color=agreement_color(agreement),
                hatch=hatch or None,
                edgecolor="white" if hatch else None,
                zorder=3,
            )
            label = class_label(agreement) + (f", {view['label']}" if several else "")
            bars[0].set_label(f"{label} ({int(count)} cells)")
            ax.annotate(
                f"{int(count)}{which}",
                xy=(count, where),
                xytext=(4, 0),
                textcoords="offset points",
                va="center",
                fontsize=8 if several else 9,
            )
    ax.margins(x=0.32 if several else 0.16)
