"""The two phases of a downslope-distance calibration, on one page.

A staged calibration answers with two numbers obtained by two different
mechanisms: a root search closes a bracket on the ratio ``K/R``, then a second
phase fits a storage parameter against an objective. A report needs both, and
it needs the three things that qualify them: how coarse the agreement is, how
the network cells split between agreement, excess and gap, and against which
recharge the ratio was measured.

Four panels carry exactly that. The first shows the value the root search
closed on and the bracket it closed it in, because the stopping rule of the
search is the width of that bracket and never the size of the residual. The
second shows the storage value and its metric. The third puts ``roptim``
against its bound: it qualifies the result and never withholds it, so the
value and the breach are drawn together. The fourth splits the cells into
valid, excess and missing, because a residual near zero is either a good fit
or a large excess cancelling a large gap, and a single number cannot tell
those two apart.

Nothing here is fabricated. A session that ran one phase draws with the second
panel marked as not run, a diagnostic no trial published is drawn as absent
rather than as zero, and a search that never changed sign says so instead of
pointing at its least bad point.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._stream_comparison import (
    AGREEMENT_COLORS,
    CRITERION_NAMES,
    class_label,
)
from hydromodpy.display.figures._trial_diagnostics import TrialTable, trial_table
from hydromodpy.results.calibration_trials import calibration_trials

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run

DEFAULT_ROPTIM_MAX = 2.0
"""Equation 4 of the method: below it the agreement is declared valid."""

CLASS_NAMES: tuple[str, ...] = tuple(CRITERION_NAMES.values())
"""The three classes of the confusion map, in the order the card stacks them."""

_STAGE_LABELS: tuple[str, str] = ("root search", "storage")

RECHARGE_KEY: str = "R_mean_m_s"
"""The key the network criterion publishes the mean recharge under, per trial.

Spelled out here rather than imported: ``display`` sits below ``calibration``
in the layer matrix, so the two ends of this name are held by the tests that
build a trial the way the criterion writes it.
"""

_VALID_COLOR = HIGH_CONTRAST_TRIPLET[0]
_BREACH_COLOR = HIGH_CONTRAST_TRIPLET[2]
_TRIAL_COLOR = HIGH_CONTRAST_TRIPLET[0]
_BRACKET_COLOR = "0.55"
_EVALUATION_COLOR = "0.35"
_NOTE_BOX = {"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"}


@dataclass(frozen=True, slots=True)
class _Stage:
    """One phase of a chain: its trials, its name and its session row."""

    session_id: str | None
    label: str
    table: TrialTable
    descriptor: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _RootSearch:
    """What the first phase closed on, and the bracket it closed it in.

    ``row`` is the trial every diagnostic of the card is read at: the end of
    the bracket that best satisfies the criterion. It is None when no root was
    closed, and then the card reports no calibrated point at all.
    """

    parameter: str
    values: np.ndarray
    value: float
    low: float
    high: float
    row: int | None
    note: str


@dataclass(frozen=True, slots=True)
class _StorageFit:
    """What the second phase fitted, and the metric it fitted it on."""

    parameter: str
    values: np.ndarray
    objectives: np.ndarray
    objective_name: str
    value: float
    objective: float
    row: int | None

    @property
    def n_failed(self) -> int:
        """Trials that published no objective, which are drawn as gaps."""
        return int(np.sum(~np.isfinite(self.objectives)))


@register
class AbherveTwoStageCard(BaseFigure):
    """A four-panel synthesis of one staged downslope-distance calibration.

    ``mean_recharge`` is the only quantity the card cannot reach on its own
    when the criterion did not publish it: the calibrated quantity is a ratio,
    so a conductivity read off the card without it would be a fiction.
    """

    spec = FigureSpec(
        name="abherve_two_stage_card",
        title="Two-stage calibration card",
        kind="comparison",
        required_tables=("calibration_iterations",),
        default_figsize=(11.5, 7.5),
    )

    def render(self, sim: Run, ax: Axes, **_) -> Axes:
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "abherve_two_stage_card is a grid of panels: call plot()",
            ha="center",
            va="center",
        )
        return ax

    def plot(
        self,
        sim: Run,
        *,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path: str | Path | None = None,
        parameter: str | None = None,
        storage_parameter: str | None = None,
        session_id: str | None = None,
        output: str | None = None,
        parameter_units: str = "-",
        mean_recharge: float | None = None,
        recharge_units: str = "m/s",
        roptim_max: float = DEFAULT_ROPTIM_MAX,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec

        stages = _stage_chain(sim, session_id=session_id)
        root = _root_search(stages[0], parameter=parameter, output=output)
        recharge = _mean_recharge(stages[0].table, mean_recharge, output=output)

        fig = plt.figure(
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        # The two result panels sit on the top row and the two panels that
        # qualify them underneath, so the card reads result then caveat.
        gs = GridSpec(2, 2, figure=fig, width_ratios=[1.45, 1.0], height_ratios=[1.0, 0.85])
        ax_root = fig.add_subplot(gs[0, 0])
        ax_storage = fig.add_subplot(gs[0, 1])
        ax_validity = fig.add_subplot(gs[1, 0])
        ax_counts = fig.add_subplot(gs[1, 1])

        self._draw_root_search(
            ax_root,
            root,
            label=stages[0].label,
            units=parameter_units,
            recharge=recharge,
            recharge_units=recharge_units,
        )
        self._draw_storage(
            ax_storage,
            stages[1] if len(stages) > 1 else None,
            parameter=storage_parameter,
            n_phases=len(stages),
        )
        self._draw_validity(
            ax_validity,
            stages[0].table,
            root.row,
            bound=float(roptim_max),
            output=output,
        )
        self._draw_counts(ax_counts, stages[0].table, root.row, output=output)

        fig.suptitle(
            f"Two-stage calibration card - {sim.name or sim.sim_id[:8]}",
            fontweight="bold",
            fontsize=14,
        )
        if save_path is not None:
            self._save(fig, Path(save_path), dpi=dpi, sim=sim)
        return fig

    # ------------------------------------------------------------------
    # panels
    # ------------------------------------------------------------------

    def _draw_root_search(
        self,
        ax: Axes,
        root: _RootSearch,
        *,
        label: str,
        units: str,
        recharge: float | None,
        recharge_units: str,
    ) -> None:
        """Panel one: the closed value inside its bracket, on a log axis."""
        ax.set_xscale("log")
        ax.set_ylim(0.0, 1.0)
        ax.set_yticks([])
        ax.set_xlabel(f"{root.parameter} ({units})")
        ax.set_title(f"Stage 1 - {label}")
        ax.grid(True, which="both", axis="x", ls=":", lw=0.4)

        finite = int(np.sum(np.isfinite(root.values)))
        ax.plot(
            root.values,
            np.full(root.values.size, 0.62),
            marker="|",
            ms=16,
            ls="none",
            color=_EVALUATION_COLOR,
            zorder=3,
            label=f"evaluations of the search ({finite})",
        )
        lines: list[str] = []
        if root.row is None:
            lines.append(root.note)
        else:
            ax.axvspan(
                root.low,
                root.high,
                color=_BRACKET_COLOR,
                alpha=0.28,
                linewidth=0.0,
                zorder=1,
                label="bracket: the two ends that change sign",
            )
            ax.axvline(
                root.value,
                color="black",
                lw=1.4,
                zorder=4,
                label=f"{root.parameter} = {root.value:.4g}",
            )
            lines.append(f"closed on {root.parameter} = {root.value:.4g}")
            lines.append(
                f"bracket [{root.low:.4g}, {root.high:.4g}], a factor {root.high / root.low:.4g}"
            )
        lines.append(
            f"mean recharge = {recharge:.4g} {recharge_units}"
            if recharge is not None
            else "mean recharge not declared: the ratio is not a conductivity"
        )
        _say(ax, "\n".join(lines), xy=(0.5, 0.06), va="bottom")
        ax.legend(loc="best", fontsize=8, framealpha=0.9)

    def _draw_storage(
        self,
        ax: Axes,
        stage: _Stage | None,
        *,
        parameter: str | None,
        n_phases: int,
    ) -> None:
        """Panel two: the storage value and the metric it was fitted on."""
        if stage is None:
            _blank(
                ax,
                "Stage 2 - not run",
                "second phase not run:\nthis calibration holds one stage",
            )
            return

        title = f"Stage 2 - {stage.label}"
        if n_phases > 2:
            # A longer chain is drawn at its second phase and says so, rather
            # than picking one of the later ones without a word.
            title = f"{title} (2 of {n_phases})"
        fit = _storage_fit(stage, parameter=parameter)
        ax.set_title(title)
        ax.set_xlabel(f"{fit.parameter} (-)")
        ax.set_ylabel(f"{fit.objective_name} (-)")
        ax.margins(x=0.10)
        ax.grid(True, ls=":", lw=0.4)

        # A failed trial keeps its abscissa and carries NaN, so it leaves a
        # gap; drawn at zero it would read as a perfect objective.
        ax.plot(
            fit.values,
            fit.objectives,
            marker="o",
            ms=5.5,
            ls="none",
            color=_TRIAL_COLOR,
            zorder=3,
            label=f"trials ({fit.values.size})",
        )
        lines: list[str] = []
        if fit.row is None:
            lines.append("no objective published: the storage fit cannot be read")
        else:
            ax.axvline(
                fit.value,
                color="black",
                lw=1.4,
                zorder=4,
                label=f"{fit.parameter} = {fit.value:.4g}",
            )
            lines.append(f"{fit.parameter} = {fit.value:.4g}")
            lines.append(f"{fit.objective_name} = {fit.objective:.4g}")
        if fit.n_failed:
            lines.append(f"{fit.n_failed} of {fit.values.size} trials failed")
        _clear_bottom(ax)
        _say(ax, "\n".join(lines), xy=(0.5, 0.04), va="bottom")
        ax.legend(loc="best", fontsize=8, framealpha=0.9)

    def _draw_validity(
        self,
        ax: Axes,
        table: TrialTable,
        row: int | None,
        *,
        bound: float,
        output: str | None,
    ) -> None:
        """Panel three: ``roptim`` against its bound, with the state spelled out."""
        title = "Validity of the agreement"
        ax.set_yticks([])
        ax.set_xlabel("roptim = Doptim / L_ref (-)")
        ax.set_title(title)
        ax.grid(True, axis="x", ls=":", lw=0.4)

        value = _diagnostic_at(table, row, "roptim", output=output)
        if row is None:
            # A bare axis would read as an indicator sitting at zero, so the
            # panel drops its scale along with the number it does not have.
            _blank(ax, title, "no root was closed: no calibrated point to qualify")
            return
        if value is None:
            _blank(ax, title, "roptim not published: the agreement is not qualified")
            return

        within = value <= bound
        bars = ax.barh(
            [0.0],
            [value],
            height=0.5,
            color=_VALID_COLOR if within else _BREACH_COLOR,
            zorder=3,
        )
        bars[0].set_label(f"roptim = {value:.4g}")
        ax.axvline(
            bound,
            color="black",
            lw=1.3,
            ls="--",
            zorder=4,
            label=f"bound: roptim <= {bound:.4g}",
        )
        state = (
            "within the validity bound" if within else "bound breached, the calibrated value stands"
        )
        lines = [f"roptim = {value:.4g} {'<=' if within else '>'} {bound:.4g}: {state}"]
        declared = _diagnostic_at(table, row, "roptim_valid", output=output)
        if declared is not None and bool(declared >= 0.5) != within:
            lines.append("the session applied a different bound than the one drawn")
        _say(ax, "\n".join(lines), xy=(0.5, 0.88), va="top")
        ax.set_xlim(0.0, max(value, bound) * 1.3)
        ax.set_ylim(-0.55, 0.95)
        ax.legend(loc="lower right", fontsize=8, framealpha=0.9)

    def _draw_counts(
        self,
        ax: Axes,
        table: TrialTable,
        row: int | None,
        *,
        output: str | None,
    ) -> None:
        """Panel four: the three classes side by side, never summed."""
        title = "Cells at the calibrated point"
        ax.set_yticks(range(len(CLASS_NAMES)), labels=list(CLASS_NAMES))
        ax.invert_yaxis()
        ax.set_xlabel("Cells (-)")
        ax.set_title(title)
        ax.grid(True, axis="x", ls=":", lw=0.4)

        if row is None:
            # Three empty rows against a cell axis would read as three counts
            # of zero, which is the one reading this panel exists to prevent.
            _blank(ax, title, "no root was closed: no calibrated point to split")
            return

        for index, (agreement, name) in enumerate(CRITERION_NAMES.items()):
            count = _diagnostic_at(table, row, f"n_{name}", output=output)
            if count is None:
                # On the row of the class itself, where its bar would have
                # been: an absent count is absent, never a bar of length zero.
                ax.annotate(
                    f"{name} not published: absent, not zero",
                    xy=(0.0, index),
                    xytext=(6, 0),
                    textcoords="offset points",
                    va="center",
                    fontsize=9,
                    style="italic",
                    color=_EVALUATION_COLOR,
                )
                continue
            bars = ax.barh(
                [index], [count], height=0.6, color=AGREEMENT_COLORS[agreement], zorder=3
            )
            bars[0].set_label(f"{class_label(agreement)} ({int(count)} cells)")
            ax.annotate(
                f"{int(count)}",
                xy=(count, index),
                xytext=(4, 0),
                textcoords="offset points",
                va="center",
                fontsize=9,
            )
        ax.margins(x=0.16)


# ---------------------------------------------------------------------------
# the chain of phases
# ---------------------------------------------------------------------------


def _stage_chain(sim: Run, *, session_id: str | None) -> list[_Stage]:
    """Return the phases of one calibration, first phase first.

    The order is the one the sessions declare through ``phase_index``, never
    the order the trials happen to sit in the table. A run whose trials name
    no session is one phase.
    """
    frame = _iterations_frame(sim)
    known = _session_rows(sim)
    seen: list[str] = []
    if "session_id" in frame.columns:
        named = (_text_or_none(value) for value in frame["session_id"])
        seen = list(dict.fromkeys(value for value in named if value is not None))
    if session_id is not None:
        target = str(session_id)
        root = _root_id(known.get(target, {}), target)
        seen = [sid for sid in seen if _root_id(known.get(sid, {}), sid) == root] or [target]
    if not seen:
        return [
            _Stage(
                session_id=None,
                label=_STAGE_LABELS[0],
                table=trial_table(sim),
                descriptor={},
            )
        ]

    position = {sid: index for index, sid in enumerate(seen)}
    ordered = sorted(seen, key=lambda sid: (_phase_index(known.get(sid, {}), position[sid]), sid))
    stages: list[_Stage] = []
    for index, sid in enumerate(ordered):
        descriptor = known.get(sid, {})
        label = _text_or_none(descriptor.get("phase_name")) or _STAGE_LABELS[min(index, 1)]
        stages.append(
            _Stage(
                session_id=sid,
                label=label,
                table=trial_table(sim, session_id=sid),
                descriptor=descriptor,
            )
        )
    return stages


def _iterations_frame(sim: Run) -> pd.DataFrame:
    """Return the raw trial rows of a run, before any flattening."""
    return calibration_trials(sim)


def _session_rows(sim: Run) -> dict[str, dict[str, Any]]:
    """Return the session rows reachable from a run, keyed by session id.

    A run does not carry its sessions, the catalog it comes from does; rows
    of other calibrations are harmless, since only the ids named by this
    run's trials are ever looked up.
    """
    frame = getattr(sim, "calibration_sessions", None)
    if frame is None:
        catalog = getattr(sim, "_catalog", None)
        frame = getattr(catalog, "calibration_sessions", None) if catalog is not None else None
    if frame is None:
        return {}
    if not isinstance(frame, pd.DataFrame):
        frame = pd.DataFrame(list(frame))
    if frame.empty or "session_id" not in frame.columns:
        return {}
    return {str(row["session_id"]): dict(row) for row in frame.to_dict("records")}


def _root_id(descriptor: dict[str, Any], session_id: str) -> str:
    """Return the id of the chain a session belongs to."""
    return (
        _text_or_none(descriptor.get("root_session_id"))
        or _text_or_none(descriptor.get("parent_session_id"))
        or session_id
    )


def _phase_index(descriptor: dict[str, Any], fallback: int) -> int:
    """Return the declared rank of a phase, or where it showed up."""
    rank = _int_or_none(descriptor.get("phase_index"))
    return fallback if rank is None else rank


def _int_or_none(value: Any) -> int | None:
    """Return ``value`` as an integer, or None when a table left it empty."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# reading the two phases
# ---------------------------------------------------------------------------


def _root_search(stage: _Stage, *, parameter: str | None, output: str | None) -> _RootSearch:
    """Return the closed value and the bracket of a root search.

    The reported value is an evaluated trial, the end of the tightest
    sign-changing bracket that best satisfies the criterion, so the
    diagnostics the card shows beside it were measured and not interpolated.
    """
    name, values = stage.table.parameter_values(parameter)
    if np.any(np.isfinite(values) & (values <= 0.0)):
        raise ValueError(
            f"the parameter {name!r} carries a non-positive value, and a bracket over "
            "a ratio is measured as a factor between its two ends."
        )
    blank = _RootSearch(
        parameter=name,
        values=values,
        value=float("nan"),
        low=float("nan"),
        high=float("nan"),
        row=None,
        note="",
    )
    if not stage.table.has_diagnostic("J_signed", output=output):
        return replace(blank, note="no signed residual published: no bracket can be read")
    residual = stage.table.diagnostic("J_signed", output=output)
    bracket = _tightest_bracket(values, residual)
    if bracket is None:
        return replace(blank, note="no sign change over the sampled range: no root was closed")
    low, high = bracket
    row = low if abs(residual[low]) <= abs(residual[high]) else high
    return _RootSearch(
        parameter=name,
        values=values,
        value=float(values[row]),
        low=float(values[low]),
        high=float(values[high]),
        row=int(row),
        note="",
    )


def _tightest_bracket(values: np.ndarray, residual: np.ndarray) -> tuple[int, int] | None:
    """Return the closest pair of samples whose residuals differ in sign.

    Tightness is a factor between the two ends, which is the width a search
    over a ratio halves, and not their difference.
    """
    keep = [
        index
        for index in np.argsort(values, kind="stable")
        if np.isfinite(values[index]) and np.isfinite(residual[index])
    ]
    pairs = [
        (int(low), int(high))
        for low, high in zip(keep[:-1], keep[1:], strict=False)
        if residual[low] * residual[high] < 0.0
    ]
    if not pairs:
        return None
    return min(pairs, key=lambda pair: values[pair[1]] / values[pair[0]])


def _storage_fit(stage: _Stage, *, parameter: str | None) -> _StorageFit:
    """Return the storage value a phase settled on, and its metric."""
    name, values = stage.table.parameter_values(parameter)
    frame = stage.table.frame
    objectives = (
        pd.to_numeric(frame["objective_value"], errors="coerce").to_numpy(dtype="float64")
        if "objective_value" in frame.columns
        else np.full(values.size, np.nan)
    )
    row = _best_row(frame, objectives, stage.descriptor)
    return _StorageFit(
        parameter=name,
        values=values,
        objectives=objectives,
        objective_name=_text_or_none(stage.descriptor.get("objective_name")) or "objective",
        value=float(values[row]) if row is not None else float("nan"),
        objective=float(objectives[row]) if row is not None else float("nan"),
        row=row,
    )


def _best_row(
    frame: pd.DataFrame,
    objectives: np.ndarray,
    descriptor: dict[str, Any],
) -> int | None:
    """Return the trial a session settled on, the one it declared when it did."""
    declared = _int_or_none(descriptor.get("best_trial"))
    if declared is not None and "iteration" in frame.columns:
        numbers = pd.to_numeric(frame["iteration"], errors="coerce").to_numpy(dtype="float64")
        matches = np.flatnonzero(numbers == float(declared))
        if matches.size and np.isfinite(objectives[matches[0]]):
            return int(matches[0])
    finite = np.flatnonzero(np.isfinite(objectives))
    if not finite.size:
        return None
    return int(finite[np.argmin(objectives[finite])])


def _mean_recharge(table: TrialTable, given: float | None, *, output: str | None) -> float | None:
    """Return the recharge the criterion ran with, declared or published."""
    if given is not None:
        return float(given)
    if not table.has_diagnostic(RECHARGE_KEY, output=output):
        return None
    values = table.diagnostic(RECHARGE_KEY, output=output)
    finite = values[np.isfinite(values)]
    return float(np.median(finite)) if finite.size else None


def _diagnostic_at(
    table: TrialTable,
    row: int | None,
    name: str,
    *,
    output: str | None,
) -> float | None:
    """Return one diagnostic at one trial, or None when it was never published."""
    if row is None or not table.has_diagnostic(name, output=output):
        return None
    value = float(table.diagnostic(name, output=output)[row])
    return value if np.isfinite(value) else None


def _text_or_none(value: Any) -> str | None:
    """Return a non-empty string, or None for anything a table left empty."""
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _blank(ax: Axes, title: str, message: str) -> None:
    """Empty one panel down to its title and the reason it stays empty."""
    ax.clear()
    ax.set_axis_off()
    ax.set_title(title)
    _say(ax, message)


def _clear_bottom(ax: Axes, share: float = 0.35) -> None:
    """Open room under the data so a note never sits on top of a trial."""
    low, high = ax.get_ylim()
    span = high - low
    if span <= 0.0:
        return
    ax.set_ylim(low - share * span, high + 0.10 * span)


def _say(ax: Axes, text: str, *, xy: tuple[float, float] = (0.5, 0.5), va: str = "center") -> None:
    """Put one note on a panel, in the same box across the whole card."""
    ax.annotate(
        text,
        xy=xy,
        xycoords="axes fraction",
        ha="center",
        va=va,
        fontsize=9,
        bbox=_NOTE_BOX,
        zorder=6,
    )
