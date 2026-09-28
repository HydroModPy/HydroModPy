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
second shows the storage value and its metric. The third puts ``Doptim``
against the validity length the trial itself bounded it by (Eq. 4, in
metres): it qualifies the result and never withholds it, so the value and the
breach are drawn together. The fourth splits the cells into
valid, excess and missing, because a residual near zero is either a good fit
or a large excess cancelling a large gap, and a single number cannot tell
those two apart.

Nothing here is fabricated. A session that ran one phase draws with the second
panel marked as not run, a diagnostic no trial published is drawn as absent
rather than as zero, and a search that never changed sign says so instead of
pointing at its least bad point.

The card reads the keys the trial published, which depend on the maps the
output was scored on. One bound in the cost publishes its components
unsuffixed. Two bounds (a transient extent table and a minimal map) publish
only ``<key>_minimal`` and ``<key>_maximal``: the first panel then shows one
bracket per bound, and the two panels underneath show both bounds side by
side, read at the trial the search returned, which is where the run reads
Eq. 4. The two roots, their spread ``Delta`` and the combined value live in
the report (``extra["roots"]``), not in the trials, and are written when the
caller passes them. A one-state output with both maps scores the minimal map
and publishes the maximal one as a validation (``<key>_maximal_validation``),
drawn beside the scored map and never mixed into its verdict.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.core.stream_geometry import VALIDITY_PROVENANCE_BY_CODE
from hydromodpy.core.stream_snap import SNAP_MODE_CODE
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._stream_comparison import (
    AGREEMENT_COLORS,
    CRITERION_NAMES,
    class_label,
)
from hydromodpy.display.figures._trial_diagnostics import TrialTable, trial_table
from hydromodpy.display.figures.network_extent_bounds_map import (
    SIMULATED_MAXIMAL_COLOR,
    SIMULATED_MINIMAL_COLOR,
)
from hydromodpy.display.style import HIGH_CONTRAST_TRIPLET, place_legend
from hydromodpy.results.calibration_trials import calibration_sessions, calibration_trials

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run

VALIDITY_PROVENANCE_LABELS: dict[str, str] = {
    "auto": "two cells, 2 h_obs",
    "auto_floor": "one cell plus the snap floor F",
    "declared_accuracy": "widened by the declared positional accuracy",
    "user": "the declared validity_length",
}
"""What set the validity length, as the note under the bar says it."""

CLASS_NAMES: tuple[str, ...] = tuple(CRITERION_NAMES.values())
"""The three classes of the confusion map, in the order the card stacks them."""

_STAGE_LABELS: tuple[str, str] = ("root search", "storage")

RECHARGE_KEY: str = "R_mean_m_s"
"""The key the network criterion publishes the mean recharge under, per trial.

Spelled out here rather than imported: ``display`` sits below ``calibration``
in the layer matrix, so the two ends of this name are held by the tests that
build a trial the way the criterion writes it.
"""

BOUNDS: tuple[str, str] = ("minimal", "maximal")
"""The two bounds of an extent, in the order the criterion scores them.

Each bound suffixes its components ``_<bound>``. Spelled out for the same
reason as :data:`RECHARGE_KEY`, and held to the criterion by the tests.
"""

VALIDATION_SUFFIX: str = "_maximal_validation"
"""The suffix of the maximal map a one-state output scores outside its cost."""

H_OBS_KEY: str = "L_ref"
"""The key the criterion publishes ``h_obs`` under, the cell size on the map.

The run's Eq. 4 verdict reads it under this name and reports it as
``h_obs_m``; the card reads the trial, so it reads this one.
"""

_BOUND_COLORS: dict[str, str] = {
    "minimal": SIMULATED_MINIMAL_COLOR,
    "maximal": SIMULATED_MAXIMAL_COLOR,
}
_BOUND_HATCH: dict[str, str] = {"minimal": "", "maximal": "//"}

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
    closed, and then the card reports no calibrated point at all. ``bound`` is
    the bound whose residual was searched, empty for one bound in the cost.
    """

    parameter: str
    values: np.ndarray
    value: float
    low: float
    high: float
    row: int | None
    note: str
    bound: str = ""


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


@dataclass(frozen=True, slots=True)
class _MapView:
    """One map the two lower panels qualify, and the suffix its keys carry.

    ``label`` is empty when the output was scored on one map only: the panels
    then read exactly as they always did. ``bound`` picks the colour and the
    hatch of the map, and ``note`` qualifies it (a weight, or a validation
    outside the cost).
    """

    label: str
    suffix: str
    bound: str
    note: str = ""
    in_verdict: bool = True


@dataclass(frozen=True, slots=True)
class _Reading:
    """Where the two lower panels read the trial, and what they read on it.

    ``row`` is None when the card has no calibrated point, and ``missing``
    then says why, in the words the panels print.
    """

    row: int | None
    views: tuple[_MapView, ...]
    missing: str


@register
class MatchingHydrographicNetworkCard(BaseFigure):
    """A four-panel synthesis of one staged downslope-distance calibration.

    ``mean_recharge`` is the only quantity the card cannot reach on its own
    when the criterion did not publish it: the calibrated quantity is a ratio,
    so a conductivity read off the card without it would be a fiction.
    ``roots`` is the ``extra["roots"]`` record of a two-root search report:
    the trials hold each bound's bracket, but not ``Delta`` nor the combined
    value, which only the report carries.
    """

    spec = FigureSpec(
        name="matching_hydrographic_network_card",
        former_names=("abherve_two_stage_card",),
        title="Matching the hydrographic network: two-stage card",
        kind="comparison",
        required_tables=("calibration_iterations",),
        default_figsize=(11.5, 7.5),
    )

    def render(self, sim: Run, ax: Axes, **_) -> Axes:
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
        sim: Run,
        *,
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path: str | Path | None = None,
        parameter: str | None = None,
        storage_parameter: str | None = None,
        session_id: str | None = None,
        output: str | None = None,
        parameter_units: str | None = None,
        mean_recharge: float | None = None,
        recharge_units: str = "m/s",
        roots: Mapping[str, Any] | None = None,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec

        stages = _stage_chain(sim, session_id=session_id)
        table = stages[0].table
        recharge = _mean_recharge(table, mean_recharge, output=output)
        if _scores_two_bounds(table, output=output):
            searches = tuple(
                _root_search(stages[0], parameter=parameter, output=output, bound=bound)
                for bound in BOUNDS
            )
            reading = _two_bound_reading(stages[0], roots, output=output)
        else:
            searches = (_root_search(stages[0], parameter=parameter, output=output),)
            reading = _Reading(
                row=searches[0].row,
                views=_one_state_views(table, output=output),
                missing="no root was closed",
            )

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

        recharge_line = (
            f"mean recharge = {recharge:.4g} {recharge_units}"
            if recharge is not None
            else "mean recharge not declared: the ratio is not a conductivity"
        )
        units = parameter_units or _declared_units(stages[0], searches[0].parameter)
        if len(searches) == len(BOUNDS):
            self._draw_two_roots(
                ax_root,
                searches,
                reading,
                roots=roots,
                label=stages[0].label,
                units=units,
                recharge_line=recharge_line,
            )
        else:
            self._draw_root_search(
                ax_root,
                searches[0],
                label=stages[0].label,
                units=units,
                recharge_line=recharge_line,
            )
        self._draw_storage(
            ax_storage,
            stages[1] if len(stages) > 1 else None,
            parameter=storage_parameter,
            n_phases=len(stages),
            next_phase=_next_declared_phase(sim, stages),
        )
        self._draw_validity(ax_validity, table, reading, output=output)
        self._draw_counts(ax_counts, table, reading, output=output)

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
        recharge_line: str,
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
        lines.append(recharge_line)
        _say(ax, "\n".join(lines), xy=(0.5, 0.06), va="bottom")
        place_legend(ax, fontsize=8, framealpha=0.9)

    def _draw_two_roots(
        self,
        ax: Axes,
        searches: tuple[_RootSearch, ...],
        reading: _Reading,
        *,
        roots: Mapping[str, Any] | None,
        label: str,
        units: str,
        recharge_line: str,
    ) -> None:
        """Panel one of a two-bound search: one bracket per bound, and the value between.

        The brackets are read off the trials, one residual per bound, the way
        one bound is. ``Delta`` and the combined value exist only in the
        report's ``roots`` record, so without it the note says they are not
        shown rather than recomputing them under a second rule.
        """
        first = searches[0]
        ax.set_xscale("log")
        ax.set_ylim(0.0, 1.0)
        ax.set_yticks([])
        ax.set_xlabel(f"{first.parameter} ({units})")
        ax.set_title(f"Stage 1 - {label}, two bounds")
        ax.grid(True, which="both", axis="x", ls=":", lw=0.4)

        finite = int(np.sum(np.isfinite(first.values)))
        ax.plot(
            first.values,
            np.full(first.values.size, 0.62),
            marker="|",
            ms=16,
            ls="none",
            color=_EVALUATION_COLOR,
            zorder=3,
            label=f"evaluations of the search ({finite})",
        )
        record = roots or {}
        lines: list[str] = []
        for search in searches:
            entry = _root_entry(record, search.bound)
            value = _finite(entry.get("k_star"), search.value)
            low = _finite(entry.get("low"), search.low)
            high = _finite(entry.get("high"), search.high)
            if not np.isfinite(value):
                lines.append(f"K*_{search.bound}: {search.note}")
                continue
            color = _BOUND_COLORS[search.bound]
            if np.isfinite(low) and np.isfinite(high):
                ax.axvspan(
                    low,
                    high,
                    color=color,
                    alpha=0.30,
                    hatch=_BOUND_HATCH[search.bound] or None,
                    linewidth=0.0,
                    zorder=1,
                    label=f"bracket {search.bound}",
                )
            ax.axvline(
                value,
                color=color,
                lw=1.6,
                zorder=4,
                label=f"K*_{search.bound} = {value:.4g}",
            )
            lines.append(f"K*_{search.bound} = {value:.4g}, bracket [{low:.4g}, {high:.4g}]")

        if roots is None:
            lines.append("roots record not passed: Delta and the combined value are not shown")
        else:
            delta = _float_or_none(record.get("delta_log10"))
            lines.append(
                "Delta = log10(K*_maximal / K*_minimal) = "
                + (f"{delta:.3g} decade(s)" if delta is not None else "unknown")
            )
            combined = _float_or_none(record.get("value"))
            if combined is None:
                lines.append("combined value not solved: the search did not converge")
            else:
                ax.axvline(
                    combined,
                    color="black",
                    lw=1.4,
                    ls="--",
                    zorder=5,
                    label=f"{first.parameter} = {combined:.4g}",
                )
                weights = " / ".join(
                    f"{_finite(_root_entry(record, bound).get('weight'), float('nan')):.3g}"
                    for bound in BOUNDS
                )
                lines.append(
                    f"combined {first.parameter} = {combined:.4g}, "
                    f"weighted geometric mean {weights}"
                )
        if reading.row is not None:
            lines.append(
                f"diagnostics read at the returned trial, "
                f"{first.parameter} = {float(first.values[reading.row]):.4g}"
            )
        lines.append(recharge_line)
        _say(ax, "\n".join(lines), xy=(0.5, 0.04), va="bottom")
        place_legend(ax, fontsize=8, framealpha=0.9)

    def _draw_storage(
        self,
        ax: Axes,
        stage: _Stage | None,
        *,
        parameter: str | None,
        n_phases: int,
        next_phase: str | None = None,
    ) -> None:
        """Panel two: the storage value and the metric it was fitted on.

        A run promoted from the first phase is drawn before the second one
        starts. When the file declares a second phase, the panel names it as
        the one that comes next rather than as a stage that was never asked.
        """
        if stage is None:
            if next_phase is not None:
                _blank(
                    ax,
                    f"Stage 2 - {next_phase}",
                    f"comes next: this run closes stage 1,\n{next_phase} starts from it",
                )
                return
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
        ax.set_xlabel(f"{fit.parameter} ({_declared_units(stage, fit.parameter)})")
        ax.set_ylabel(f"cost, {fit.objective_name} (-)")
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
            lines.append(f"cost ({fit.objective_name}) = {fit.objective:.4g}")
        if fit.n_failed:
            lines.append(f"{fit.n_failed} of {fit.values.size} trials failed")
        _clear_bottom(ax)
        _say(ax, "\n".join(lines), xy=(0.5, 0.04), va="bottom")
        place_legend(ax, fontsize=8, framealpha=0.9)

    def _draw_validity(
        self,
        ax: Axes,
        table: TrialTable,
        reading: _Reading,
        *,
        output: str | None,
    ) -> None:
        """Panel three: ``Doptim`` against the trial's validity length, in metres.

        The bound is the ``validity_length_m`` the trial published, never a
        ratio the card assumes: a declared positional accuracy or a snap floor
        widens it past ``2 h_obs``, and the verdict the run reports reads it.
        ``roptim`` is written beside it for the paper's Table 1. An output
        scored on two maps gets one row per map, each against its own length.
        """
        title = "Validity of the agreement"
        ax.set_yticks([])
        ax.set_xlabel("Doptim = (D_so + D_os) / 2 (m)")
        ax.set_title(title)
        ax.grid(True, axis="x", ls=":", lw=0.4)

        if reading.row is None:
            # A bare axis would read as an indicator sitting at zero, so the
            # panel drops its scale along with the number it does not have.
            _blank(ax, title, f"{reading.missing}: no calibrated point to qualify")
            return
        if len(reading.views) > 1:
            self._draw_validity_rows(ax, table, reading, output=output)
            return
        row = reading.row
        value = _diagnostic_at(table, row, "Doptim", output=output)
        bound = _diagnostic_at(table, row, "validity_length_m", output=output)
        if value is None:
            _blank(ax, title, "Doptim not published: the agreement is not qualified")
            return
        if bound is None:
            _blank(
                ax,
                title,
                "validity length not published: the agreement is not qualified",
            )
            return

        within = value <= bound
        bars = ax.barh(
            [0.0],
            [value],
            height=0.5,
            color=_VALID_COLOR if within else _BREACH_COLOR,
            zorder=3,
        )
        bars[0].set_label(f"Doptim = {value:.4g} m")
        provenance = _validity_provenance(table, row, output=output)
        ax.axvline(
            bound,
            color="black",
            lw=1.3,
            ls="--",
            zorder=4,
            label=f"bound: Doptim <= {bound:.4g} m",
        )
        state = (
            "within the validity bound" if within else "bound breached, the calibrated value stands"
        )
        lines = [f"Doptim = {value:.4g} m {'<=' if within else '>'} {bound:.4g} m: {state}"]
        if provenance is not None:
            lines.append(f"validity length: {provenance}")
        ratio = _diagnostic_at(table, row, "roptim", output=output)
        h_obs = _diagnostic_at(table, row, H_OBS_KEY, output=output)
        if ratio is not None:
            scale = f", h_obs = {h_obs:.4g} m" if h_obs is not None else ""
            lines.append(f"roptim = Doptim / h_obs = {ratio:.4g}{scale}")
        snap = _snap_breach(table, row, output=output)
        if snap is not None:
            lines.append(snap)
        _say(ax, "\n".join(lines), xy=(0.5, 0.92), va="top")
        ax.set_xlim(0.0, max(value, bound) * 1.3)
        ax.set_ylim(-0.55, 1.25)
        ax.legend(loc="lower right", fontsize=8, framealpha=0.9)

    def _draw_validity_rows(
        self,
        ax: Axes,
        table: TrialTable,
        reading: _Reading,
        *,
        output: str | None,
    ) -> None:
        """Panel three for two maps: one bar and one bound per map, side by side.

        Each map is read under its own suffix against its own length, and the
        note gives each its Eq. 4 verdict. A map outside the run's verdict (a
        validation, a bound weighted zero) is qualified the same way and says
        it counts for nothing.
        """
        row = reading.row
        if row is None:
            return
        views = reading.views
        ax.set_yticks(range(len(views)), labels=[view.label for view in views])
        lines: list[str] = []
        extent = 0.0
        for index, view in enumerate(views):
            lines.extend(_validity_lines(table, row, view, output=output))
            value = _diagnostic_at(table, row, f"Doptim{view.suffix}", output=output)
            bound = _diagnostic_at(table, row, f"validity_length_m{view.suffix}", output=output)
            if value is None:
                ax.annotate(
                    f"Doptim {view.label} not published: absent, not zero",
                    xy=(0.0, index),
                    xytext=(6, 0),
                    textcoords="offset points",
                    va="center",
                    fontsize=8,
                    style="italic",
                    color=_EVALUATION_COLOR,
                )
                continue
            within = bound is not None and value <= bound
            color = (
                _EVALUATION_COLOR if bound is None else (_VALID_COLOR if within else _BREACH_COLOR)
            )
            bars = ax.barh(
                [index],
                [value],
                height=0.5,
                color=color,
                hatch=_BOUND_HATCH[view.bound] or None,
                edgecolor="white",
                zorder=3,
            )
            bars[0].set_label(f"Doptim {view.label} = {value:.4g} m")
            extent = max(extent, value)
            if bound is not None:
                ax.plot(
                    [bound, bound],
                    [index - 0.35, index + 0.35],
                    color="black",
                    lw=1.3,
                    ls="--",
                    zorder=4,
                    label=f"bound {view.label}: Doptim <= {bound:.4g} m",
                )
                extent = max(extent, bound)
        _say(ax, "\n".join(lines), xy=(0.5, 0.97), va="top", fontsize=8)
        ax.set_xlim(0.0, (extent or 1.0) * 1.3)
        # The rows sit in the lower half, the note above them: the axis runs
        # downwards so the first map reads first.
        ax.set_ylim(len(views) - 0.4, -0.6 - 1.5 * len(views))

    def _draw_counts(
        self,
        ax: Axes,
        table: TrialTable,
        reading: _Reading,
        *,
        output: str | None,
    ) -> None:
        """Panel four: the three classes side by side, never summed.

        Two maps put their two bars of one class next to each other, the
        second hatched, so the split of each map reads on its own.
        """
        title = "Cells at the calibrated point"
        ax.set_yticks(range(len(CLASS_NAMES)), labels=list(CLASS_NAMES))
        ax.invert_yaxis()
        ax.set_xlabel("Cells (-)")
        ax.set_title(title)
        ax.grid(True, axis="x", ls=":", lw=0.4)

        row = reading.row
        if row is None:
            # Three empty rows against a cell axis would read as three counts
            # of zero, which is the one reading this panel exists to prevent.
            _blank(ax, title, f"{reading.missing}: no calibrated point to split")
            return

        views = reading.views
        several = len(views) > 1
        height = 0.6 if not several else 0.8 / len(views)
        for index, (agreement, name) in enumerate(CRITERION_NAMES.items()):
            for rank, view in enumerate(views):
                where = index + (rank - (len(views) - 1) / 2.0) * height
                which = f" {view.label}" if several else ""
                count = _diagnostic_at(table, row, f"n_{name}{view.suffix}", output=output)
                if count is None:
                    # On the row of the class itself, where its bar would have
                    # been: an absent count is absent, never a bar of length zero.
                    ax.annotate(
                        f"{name}{which} not published: absent, not zero",
                        xy=(0.0, where),
                        xytext=(6, 0),
                        textcoords="offset points",
                        va="center",
                        fontsize=8 if several else 9,
                        style="italic",
                        color=_EVALUATION_COLOR,
                    )
                    continue
                hatch = _BOUND_HATCH[view.bound] if several else ""
                bars = ax.barh(
                    [where],
                    [count],
                    height=height * (0.95 if several else 1.0),
                    color=AGREEMENT_COLORS[agreement],
                    hatch=hatch or None,
                    edgecolor="white" if hatch else None,
                    zorder=3,
                )
                label = class_label(agreement) + (f", {view.label}" if several else "")
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


# ---------------------------------------------------------------------------
# the chain of phases
# ---------------------------------------------------------------------------


def _stage_chain(sim: Run, *, session_id: str | None) -> list[_Stage]:
    """Return the phases of one calibration, first phase first.

    The order is the one the sessions declare through ``phase_index``, never
    the order the trials happen to sit in the table. A run whose trials name
    no session is one phase.

    A promoted run carries the trials of the phase it came from only. The
    other phases of its chain, the sessions sharing its root, are read by
    session id, so the run promoted from the second phase still draws the
    first one.
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
    tables = {sid: trial_table(sim, session_id=sid) for sid in seen}
    roots = {_root_id(known.get(sid, {}), sid) for sid in seen}
    for sid, row in known.items():
        if sid in tables or _root_id(row, sid) not in roots:
            continue
        table = _chained_table(sim, sid)
        if table is not None:
            seen.append(sid)
            tables[sid] = table
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
                table=tables[sid],
                descriptor=descriptor,
            )
        )
    return stages


def _chained_table(sim: Run, session_id: str) -> TrialTable | None:
    """Return the trials of another phase of the chain, or None when it has none.

    A phase that recorded no trial yet, or a run-shaped adapter that carries
    only its own phase, is not a stage the card can draw; the stages it does
    hold still draw.
    """
    try:
        return trial_table(sim, session_id=session_id)
    except ValueError:
        # calibration_trials raises ValueError for "no trial recorded", which
        # here means only that this phase has nothing to draw.
        return None


def _next_declared_phase(sim: Run, stages: list[_Stage]) -> str | None:
    """Return the name of the phase declared after the drawn ones, if any.

    Read from the configuration the run was replayed with: a staged
    calibration writes its phases into ``[[calibration.phases]]``, and the
    run promoted from the first phase is drawn before the second one exists.
    """
    snapshot = getattr(sim, "config_snapshot", None)
    calibration = snapshot.get("calibration") if isinstance(snapshot, Mapping) else None
    phases = calibration.get("phases") if isinstance(calibration, Mapping) else None
    if not isinstance(phases, list) or len(phases) <= len(stages):
        return None
    following = phases[len(stages)]
    name = following.get("name") if isinstance(following, Mapping) else None
    return _text_or_none(name) or _STAGE_LABELS[1]


def _session_config(descriptor: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the configuration a session recorded, parsed from the index text."""
    config = descriptor.get("config")
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            return {}
    return config if isinstance(config, Mapping) else {}


def _objective_label(descriptor: Mapping[str, Any]) -> str:
    """Return the metric a phase scored on, as its objective blocks name it.

    A phase scored through ``objective_blocks`` records the calibration's
    default ``objective`` as its session objective name, which is not the
    metric it used; the blocks are.
    """
    blocks = _session_config(descriptor).get("objective_blocks")
    metrics = [
        str(block["metric"])
        for block in blocks or ()
        if isinstance(block, Mapping) and _text_or_none(block.get("metric"))
    ]
    if metrics:
        return " + ".join(dict.fromkeys(metrics))
    return _text_or_none(descriptor.get("objective_name")) or "objective"


def _declared_units(stage: _Stage, parameter: str) -> str:
    """Return the units the session declared for ``parameter``, ``-`` when none."""
    parameters = _session_config(stage.descriptor).get("parameters")
    declared = parameters.get(parameter) if isinstance(parameters, Mapping) else None
    units = declared.get("units") if isinstance(declared, Mapping) else None
    return _text_or_none(units) or "-"


def _iterations_frame(sim: Run) -> pd.DataFrame:
    """Return the raw trial rows of a run, before any flattening."""
    return calibration_trials(sim)


def _session_rows(sim: Run) -> dict[str, dict[str, Any]]:
    """Return the session rows reachable from a run, keyed by session id.

    A run does not carry its sessions, the catalog it comes from does; rows
    of other calibrations are harmless, since only the ids named by this
    run's trials are ever looked up.
    """
    frame = calibration_sessions(sim)
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


def _root_search(
    stage: _Stage,
    *,
    parameter: str | None,
    output: str | None,
    bound: str = "",
) -> _RootSearch:
    """Return the closed value and the bracket of a root search.

    The reported value is an evaluated trial, the end of the tightest
    sign-changing bracket that best satisfies the criterion, so the
    diagnostics the card shows beside it were measured and not interpolated.
    ``bound`` reads the residual of one bound, ``J_signed_<bound>``, the one
    a two-root search closes on that bound.
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
        bound=bound,
    )
    key = f"J_signed_{bound}" if bound else "J_signed"
    if not stage.table.has_diagnostic(key, output=output):
        return replace(blank, note="no signed residual published: no bracket can be read")
    residual = stage.table.diagnostic(key, output=output)
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
        bound=bound,
    )


def _scores_two_bounds(table: TrialTable, *, output: str | None) -> bool:
    """Whether the trials hold two bounds in the cost, and no unsuffixed residual.

    The criterion publishes ``J_signed`` only when one bound is in the cost;
    two bounds publish ``J_signed_minimal`` and ``J_signed_maximal`` alone.
    """
    if table.has_diagnostic("J_signed", output=output):
        return False
    return all(table.has_diagnostic(f"J_signed_{bound}", output=output) for bound in BOUNDS)


def _one_state_views(table: TrialTable, *, output: str | None) -> tuple[_MapView, ...]:
    """Return the maps of an output with one bound in the cost.

    One map reads the unsuffixed keys, exactly as before two maps existed.
    With both maps the unsuffixed keys carry the minimal map, the one in the
    cost, and the maximal map sits under ``_maximal_validation`` beside it.
    """
    if not table.has_diagnostic(f"Doptim{VALIDATION_SUFFIX}", output=output):
        return (_MapView(label="", suffix="", bound="maximal"),)
    return (
        _MapView(label="minimal", suffix="", bound="minimal", note="in the cost"),
        _MapView(
            label="maximal",
            suffix=VALIDATION_SUFFIX,
            bound="maximal",
            note="validation outside the cost",
            in_verdict=False,
        ),
    )


def _two_bound_reading(
    stage: _Stage,
    roots: Mapping[str, Any] | None,
    *,
    output: str | None,
) -> _Reading:
    """Return the trial a two-root search returned, and its two bounds.

    The run reads Eq. 4 on that trial, once per bound, so the card does too.
    It is the combined trial of the roots record when the report is passed,
    else the best trial the session declared. A bound weighted zero is not
    searched and the run reads no verdict on it; the card still draws it.
    """
    record = roots or {}
    declared = _int_or_none(record.get("combined_trial_id"))
    if declared is None:
        declared = _int_or_none(stage.descriptor.get("best_trial"))
    row = _trial_row(stage.table.frame, declared)
    views: list[_MapView] = []
    for bound in BOUNDS:
        weight = _diagnostic_at(stage.table, row, f"weight_{bound}", output=output)
        if weight is None:
            weight = _float_or_none(_root_entry(record, bound).get("weight"))
        in_verdict = weight is None or weight > 0.0
        note = "" if weight is None else f"weight {weight:.3g}"
        if not in_verdict:
            note += ", outside the verdict"
        views.append(
            _MapView(
                label=bound,
                suffix=f"_{bound}",
                bound=bound,
                note=note,
                in_verdict=in_verdict,
            )
        )
    return _Reading(
        row=row,
        views=tuple(views),
        missing="the returned trial is not known",
    )


def _trial_row(frame: pd.DataFrame, trial: int | None) -> int | None:
    """Return the row of one trial number, or None when it is not in the table."""
    if trial is None or "iteration" not in frame.columns:
        return None
    numbers = pd.to_numeric(frame["iteration"], errors="coerce").to_numpy(dtype="float64")
    matches = np.flatnonzero(numbers == float(trial))
    return int(matches[0]) if matches.size else None


def _root_entry(record: Mapping[str, Any], bound: str) -> Mapping[str, Any]:
    """Return the entry of one bound in a roots record, empty when absent."""
    entry = record.get(bound)
    return entry if isinstance(entry, Mapping) else {}


def _float_or_none(value: Any) -> float | None:
    """Return ``value`` as a finite float, or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _finite(value: Any, fallback: float) -> float:
    """Return ``value`` as a finite float, or ``fallback``."""
    number = _float_or_none(value)
    return fallback if number is None else number


def _validity_lines(
    table: TrialTable,
    row: int,
    view: _MapView,
    *,
    output: str | None,
) -> list[str]:
    """Return the note of one map: its residual, its Eq. 4 verdict, its scale.

    The verdict is the run's: ``Doptim`` within the map's own length, and no
    snap that moved the map too far. A map outside the verdict gets the same
    reading under another word, so it is never taken for a verdict.
    """
    suffix = view.suffix
    heading = view.label + (f" ({view.note})" if view.note else "")
    residual = _diagnostic_at(table, row, f"J_signed{suffix}", output=output)
    value = _diagnostic_at(table, row, f"Doptim{suffix}", output=output)
    bound = _diagnostic_at(table, row, f"validity_length_m{suffix}", output=output)
    snap = _snap_breach(table, row, output=output, suffix=suffix)
    if value is None:
        reading = "Doptim not published, not qualified"
    elif bound is None:
        reading = f"Doptim = {value:.4g} m, validity length not published"
    else:
        within = value <= bound
        if view.in_verdict:
            verdict = "Eq. 4 holds" if within and snap is None else "Eq. 4 fails"
        else:
            verdict = ("within" if within else "beyond") + " the bound, no verdict"
        reading = f"Doptim = {value:.4g} m {'<=' if within else '>'} {bound:.4g} m, {verdict}"
    lines = [f"{heading}: {reading}"]
    scale = [f"J_signed = {residual:.4g} m"] if residual is not None else []
    ratio = _diagnostic_at(table, row, f"roptim{suffix}", output=output)
    h_obs = _diagnostic_at(table, row, f"{H_OBS_KEY}{suffix}", output=output)
    provenance = _validity_provenance(table, row, output=output, suffix=suffix)
    if ratio is not None:
        scale.append(f"roptim = {ratio:.4g}")
    if h_obs is not None:
        scale.append(f"h_obs = {h_obs:.4g} m")
    if provenance is not None:
        scale.append(f"length: {provenance}")
    if scale:
        lines.append("    " + ", ".join(scale))
    if snap is not None:
        lines.append(f"    {snap}")
    return lines


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
        objective_name=_objective_label(stage.descriptor),
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


def _validity_provenance(
    table: TrialTable, row: int, *, output: str | None, suffix: str = ""
) -> str | None:
    """Return what set the validity length at one trial, or None when unpublished."""
    code = _diagnostic_at(table, row, f"validity_length_provenance{suffix}", output=output)
    name = None if code is None else VALIDITY_PROVENANCE_BY_CODE.get(code)
    return None if name is None else VALIDITY_PROVENANCE_LABELS[name]


def _snap_breach(
    table: TrialTable, row: int, *, output: str | None, suffix: str = ""
) -> str | None:
    """Return the line saying the applied snap breaks Eq. 4, or None.

    Only ``[geographic.snap_streams] mode = "apply"`` adds this half of the
    verdict: the snapped map may not move further than its bound on its 90th
    percentile, nor lose more than its share of rejected cells. ``suffix``
    reads the indices of one map of an output scored on several.
    """
    mode = _diagnostic_at(table, row, f"snap_mode{suffix}", output=output)
    if mode != SNAP_MODE_CODE["apply"]:
        return None
    p90 = _diagnostic_at(table, row, f"snap_displacement_p90_m{suffix}", output=output)
    p90_max = _diagnostic_at(table, row, f"snap_displacement_bound_m{suffix}", output=output)
    rejected = _diagnostic_at(table, row, f"snap_rejected_share{suffix}", output=output)
    rejected_max = _diagnostic_at(table, row, f"snap_rejected_share_max{suffix}", output=output)
    causes: list[str] = []
    if p90 is None or p90_max is None or p90 > p90_max:
        causes.append("its displacement p90 exceeds its bound")
    if rejected is None or rejected_max is None or rejected > rejected_max:
        causes.append("it rejected more cells than allowed")
    if not causes:
        return None
    return "snapped map breaks Eq. 4: " + " and ".join(causes)


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


def _say(
    ax: Axes,
    text: str,
    *,
    xy: tuple[float, float] = (0.5, 0.5),
    va: str = "center",
    fontsize: float = 9,
) -> None:
    """Put one note on a panel, in the same box across the whole card."""
    ax.annotate(
        text,
        xy=xy,
        xycoords="axes fraction",
        ha="center",
        va=va,
        fontsize=fontsize,
        bbox=_NOTE_BOX,
        zorder=6,
    )
