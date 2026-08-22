"""The optimal agreement of several catchments, against the bound that validates it.

``D_optim`` is the downslope distance the criterion reaches at its calibrated
point, and ``r_optim`` is that distance read against the resolution below which
two descents are the same measurement. Equation 4 of the method declares the
calibration valid while ``r_optim`` stays under two: past that, the two
networks agree only at a scale coarser than the one the model claims to
resolve.

One catchment cannot say whether its own ``r_optim`` is ordinary, so this chart
puts a set of sites on the same axes against their calibrated transmissivity,
and shades the zone the bound excludes. A site past the bound keeps its marker
and its name: the point of the figure is that the agreement degrades in a way a
reader can follow, and a chart that dropped the failures would claim a method
that never fails.

The records arrive through ``render``. A cross-site chart cannot be assembled
from one run, and this layer never reaches across projects.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.units.labels import axis_label
from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

_WITHIN_COLOR = HIGH_CONTRAST_TRIPLET[0]
_DISTANCE_COLOR = HIGH_CONTRAST_TRIPLET[1]
_BEYOND_COLOR = HIGH_CONTRAST_TRIPLET[2]
_ZONE_COLOR = "0.55"
_DISTANCE_INK = "#7A5C12"
"""A darkened sand, for the outline and the ordinate of the distance series.

The sand itself is too light to read as a thin line on white, and the right
ordinate needs to be tied to its series by something other than position.
"""

DEFAULT_VALIDITY_BOUND: float = 2.0
"""Equation 4 of the method. An argument, so a reader may test another."""


@dataclass(frozen=True, slots=True)
class SiteAgreement:
    """What one catchment contributes to the chart.

    ``transmissivity`` is the calibrated value in m2/s, ``d_optim`` the
    downslope distance at the calibrated point in metres, and ``r_optim`` that
    distance in units of the reference length. A site whose calibration never
    converged carries NaN rather than a zero, which would read as a perfect
    agreement.
    """

    label: str
    transmissivity: float
    d_optim: float
    r_optim: float

    def __post_init__(self) -> None:
        if not str(self.label).strip():
            raise ValueError("a site record needs a non-empty label to be readable on the chart.")
        transmissivity = float(self.transmissivity)
        if not math.isfinite(transmissivity) or transmissivity <= 0.0:
            raise ValueError(
                f"site {self.label!r} carries transmissivity {self.transmissivity!r}; the chart "
                "reads it on a log axis, so it must be finite and strictly positive."
            )
        for name in ("d_optim", "r_optim"):
            value = float(getattr(self, name))
            if math.isnan(value):
                continue
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(
                    f"site {self.label!r} carries {name}={getattr(self, name)!r}; it is a length "
                    "or a ratio of lengths, so it is either non-negative or NaN when the "
                    "calibration never reached an optimum."
                )


@register
class RoptimValidityChart(BaseFigure):
    """``D_optim`` and ``r_optim`` against transmissivity, over a set of sites."""

    spec = FigureSpec(
        name="roptim_validity_chart",
        title="Optimal agreement and validity bound",
        kind="comparison",
        default_figsize=(7.6, 5.0),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Refuse a run-driven render: one run holds one site.

        A gallery walks the figures of a single run, and this chart compares
        several catchments. Saying so here turns the crash of a figure driven
        by name into a skip carrying the reason.
        """
        del sim
        return (
            "compares the calibrated agreement of several sites, and a run holds "
            "one; this figure is drawn by passing the per-site records to render()"
        )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        sites: Sequence[SiteAgreement],
        bound: float = DEFAULT_VALIDITY_BOUND,
        transmissivity_units: str | None = None,
        highlight: str | None = None,
        **_,
    ) -> Axes:
        records = list(sites)
        if not records:
            raise ValueError("the chart needs at least one site record to place a catchment.")
        bound = float(bound)
        if not math.isfinite(bound) or bound <= 0.0:
            raise ValueError(f"the validity bound must be finite and positive, got {bound!r}.")

        transmissivity = np.array([record.transmissivity for record in records], dtype=float)
        d_optim = np.array([record.d_optim for record in records], dtype=float)
        r_optim = np.array([record.r_optim for record in records], dtype=float)
        measured = np.isfinite(r_optim)
        within = measured & (r_optim <= bound)
        beyond = measured & (r_optim > bound)

        top = _upper_limit(r_optim[measured], bound)
        ax.axhspan(
            bound,
            top,
            color=_ZONE_COLOR,
            alpha=0.25,
            linewidth=0.0,
            zorder=0,
            label=f"beyond the validity bound: r_optim > {bound:g}",
        )
        ax.axhline(
            bound,
            color="black",
            lw=1.1,
            ls="--",
            zorder=2,
            label=f"validity bound: r_optim = {bound:g}",
        )

        ax.scatter(
            transmissivity[within],
            r_optim[within],
            marker="o",
            s=58,
            color=_WITHIN_COLOR,
            edgecolors="white",
            linewidths=0.6,
            zorder=4,
            label=f"r_optim within the bound ({int(within.sum())})",
        )
        if np.any(beyond):
            # Kept on the same axes and on the same scale, never clipped: the
            # readable degradation past the bound is what the chart is for.
            ax.scatter(
                transmissivity[beyond],
                r_optim[beyond],
                marker="X",
                s=88,
                color=_BEYOND_COLOR,
                edgecolors="black",
                linewidths=0.8,
                zorder=5,
                label=f"r_optim beyond the bound ({int(beyond.sum())})",
            )
        for index in np.flatnonzero(measured):
            ax.annotate(
                records[index].label,
                xy=(transmissivity[index], r_optim[index]),
                xytext=(0.0, 8.0),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=7.5,
                zorder=6,
            )

        ring = _highlighted(records, highlight, sim)
        if ring is not None and measured[ring]:
            ax.scatter(
                [transmissivity[ring]],
                [r_optim[ring]],
                marker="o",
                s=210,
                facecolors="none",
                edgecolors="black",
                linewidths=1.4,
                zorder=6,
                label=f"{records[ring].label}: this catchment",
            )

        ax_d = ax.twinx()
        ax_d.scatter(
            transmissivity,
            d_optim,
            marker="s",
            s=46,
            color=_DISTANCE_COLOR,
            edgecolors=_DISTANCE_INK,
            linewidths=0.6,
            zorder=3,
            label="D_optim: distance at the optimum",
        )
        ax_d.set_ylabel("D_optim (m)", color=_DISTANCE_INK)
        ax_d.tick_params(axis="y", colors=_DISTANCE_INK)
        ax_d.set_ylim(bottom=0.0)

        ax.annotate(
            _validity_note(records, within=within, beyond=beyond, measured=measured, bound=bound),
            xy=(0.02, 0.02),
            xycoords="axes fraction",
            ha="left",
            va="bottom",
            fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"},
            zorder=7,
        )

        ax.set_xscale("log")
        ax.set_xlabel(axis_label("transmissivity", transmissivity_units))
        ax.set_ylabel("r_optim (-)")
        ax.set_ylim(0.0, top)
        ax.grid(True, which="both", ls=":", lw=0.4)
        ax.set_title(_title(records, ring))
        handles = ax.get_legend_handles_labels()[0] + ax_d.get_legend_handles_labels()[0]
        ax_d.legend(handles=handles, loc="upper left", fontsize=8.5, framealpha=0.9)
        return ax


def _upper_limit(measured: np.ndarray, bound: float) -> float:
    """Return an ordinate top that shows the shaded zone and every site in it."""
    highest = float(np.max(measured)) if measured.size else 0.0
    return max(bound * 1.25, highest * 1.12)


def _highlighted(
    records: Sequence[SiteAgreement],
    highlight: str | None,
    sim: Run | None,
) -> int | None:
    """Return the index of the site the run is about, when it is in the set."""
    wanted = highlight or getattr(sim, "name", None) or getattr(sim, "sim_id", None)
    if not wanted:
        return None
    for index, record in enumerate(records):
        if record.label == str(wanted):
            return index
    return None


def _title(records: Sequence[SiteAgreement], ring: int | None) -> str:
    """Return the title, naming the catchment the run is about when it is there."""
    count = len(records)
    plural = "site" if count == 1 else "sites"
    title = f"Optimal agreement across {count} {plural}"
    if ring is None:
        return title
    return f"{title} - {records[ring].label}"


def _validity_note(
    records: Sequence[SiteAgreement],
    *,
    within: np.ndarray,
    beyond: np.ndarray,
    measured: np.ndarray,
    bound: float,
) -> str:
    """Return the one-line reading of the chart, including its absences."""
    total = int(measured.sum())
    if not total:
        note = (
            f"no site carries an r_optim: the bound r_optim > {bound:g} is drawn but "
            "nothing was placed against it"
        )
    elif np.any(beyond):
        names = ", ".join(records[index].label for index in np.flatnonzero(beyond))
        note = (
            f"{int(beyond.sum())} of {total} calibrated sites beyond r_optim > {bound:g}: {names}"
        )
    else:
        count = int(within.sum())
        subject = "site agrees" if count == 1 else "sites agree"
        note = (
            f"no site beyond r_optim > {bound:g}: the {count} calibrated {subject} within the bound"
        )
    unmeasured = int(np.sum(~measured))
    if unmeasured:
        subject = "site carries" if unmeasured == 1 else "sites carry"
        note = f"{note}\n{unmeasured} {subject} no r_optim: never plotted, never a zero"
    return note
