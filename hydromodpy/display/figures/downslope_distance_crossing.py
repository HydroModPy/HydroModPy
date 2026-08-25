"""The two downslope distances against the calibrated parameter.

``D_so`` is the mean descent from the simulated stream network down to the
mapped one, ``D_os`` the reverse. They move in opposite directions with the
parameter, and the calibrated point is where they meet: the zero of
``J_signed = D_so - D_os``, an intersection of two curves and not the minimum
of a distance. This figure is the only one that shows it, and reading it is
how a reader tells the criterion apart from a minimised mean distance.

The distances are plotted raw, each inside a band of one reference length,
which is the resolution below which two descents are the same measurement. The
crossing is annotated with the parameter value it gives. When no sign change
was sampled, the figure says so instead of pointing at a lowest point, because
the lowest point of either curve is not an estimate of anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.colormaps import HIGH_CONTRAST_TRIPLET
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._trial_diagnostics import TrialTable, trial_table

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

_SIMULATED_TO_MAPPED = HIGH_CONTRAST_TRIPLET[0]
_MAPPED_TO_SIMULATED = HIGH_CONTRAST_TRIPLET[2]


@register
class DownslopeDistanceCrossingFigure(BaseFigure):
    """``D_so`` and ``D_os`` versus the calibrated parameter, on a log axis.

    ``parameter_units`` defaults to the dimensionless mark, since the
    parameter this criterion calibrates is the ratio ``K/R``; a figure drawn
    over a conductivity passes its own. ``band_m`` defaults to the ``L_ref``
    the criterion published with each trial.
    """

    spec = FigureSpec(
        name="downslope_distance_crossing",
        title="Downslope distance crossing",
        kind="timeseries",
        required_tables=("calibration_iterations",),
        default_figsize=(7.6, 5.0),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        parameter: str | None = None,
        parameter_units: str = "-",
        session_id: str | None = None,
        output: str | None = None,
        band_m: float | None = None,
        **_,
    ) -> Axes:
        from matplotlib.patches import Patch

        table = trial_table(sim, session_id=session_id)
        name, values = table.parameter_values(parameter)
        d_so = table.diagnostic("D_so", output=output)
        d_os = table.diagnostic("D_os", output=output)

        order = np.argsort(values, kind="stable")
        values, d_so, d_os = values[order], d_so[order], d_os[order]
        if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
            raise ValueError(
                f"the parameter {name!r} carries a non-positive or missing value, and the "
                "crossing is read on a log axis. A root search over a ratio walks the "
                "decades, so its samples are strictly positive."
            )

        band = _band_half_width(table, band_m, output=output)
        if band is not None:
            for curve, color in ((d_so, _SIMULATED_TO_MAPPED), (d_os, _MAPPED_TO_SIMULATED)):
                # The lower edge is clipped at zero: a descent length cannot be
                # negative, so a band crossing the axis would claim a distance
                # the criterion can never measure.
                ax.fill_between(
                    values,
                    np.maximum(curve - band, 0.0),
                    curve + band,
                    color=color,
                    alpha=0.18,
                    linewidth=0.0,
                    zorder=1,
                )

        # A failed trial keeps its abscissa and carries NaN, which matplotlib
        # draws as a gap. Substituting a zero would put a perfect agreement
        # exactly where the model produced nothing.
        ax.plot(
            values,
            d_so,
            color=_SIMULATED_TO_MAPPED,
            lw=1.7,
            ls="-",
            marker="o",
            ms=4.5,
            zorder=3,
            label="D_so: simulated to mapped",
        )
        ax.plot(
            values,
            d_os,
            color=_MAPPED_TO_SIMULATED,
            lw=1.7,
            ls="--",
            marker="^",
            ms=4.5,
            zorder=3,
            label="D_os: mapped to simulated",
        )

        crossings = _sign_changes(values, d_so - d_os)
        if crossings:
            tightest = min(crossings, key=lambda crossing: crossing[2] / crossing[1])
            for crossing in crossings:
                ax.axvline(
                    crossing[0],
                    color="black",
                    lw=1.1,
                    ls=":",
                    zorder=2,
                    label=(
                        f"crossing: {name} = {crossing[0]:.4g}" if crossing is tightest else None
                    ),
                )
            note = f"{name} = {tightest[0]:.4g}"
            if len(crossings) > 1:
                note = f"{note}\n{len(crossings)} sign changes: the root is not unique"
            # Under the crossing rather than over it: the two curves meet in
            # the middle of the panel, so the space below that abscissa is the
            # one place neither a curve nor the legend competes for.
            ax.annotate(
                note,
                xy=(tightest[0], 0.03),
                xycoords=("data", "axes fraction"),
                ha="center",
                va="bottom",
                fontsize=9,
                bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"},
                zorder=6,
            )
        else:
            ax.annotate(
                "no sign change over the sampled range: no root is bracketed",
                xy=(0.5, 0.03),
                xycoords="axes fraction",
                ha="center",
                va="bottom",
                fontsize=9,
                bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#c8c8c8"},
                zorder=6,
            )

        ax.set_xscale("log")
        ax.set_xlabel(f"{name} ({parameter_units})")
        ax.set_ylabel("Downslope distance (m)")
        ax.set_ylim(bottom=0.0)
        ax.grid(True, which="both", ls=":", lw=0.4)
        ax.set_title(f"Downslope distance crossing - {sim.name or sim.sim_id}")
        handles, _labels = ax.get_legend_handles_labels()
        if band is not None:
            handles.append(
                Patch(
                    facecolor="0.55",
                    alpha=0.3,
                    label=f"one reference length either side ({band:.0f} m)",
                )
            )
        ax.legend(handles=handles, loc="best", fontsize=9, framealpha=0.9)
        return ax


def _band_half_width(
    table: TrialTable,
    band_m: float | None,
    *,
    output: str | None,
) -> float | None:
    """Return the half-width of the uncertainty band, in metres."""
    if band_m is not None:
        return float(band_m)
    if not table.has_diagnostic("L_ref", output=output):
        return None
    values = table.diagnostic("L_ref", output=output)
    finite = values[np.isfinite(values)]
    return float(np.median(finite)) if finite.size else None


def _sign_changes(
    values: np.ndarray,
    residual: np.ndarray,
) -> list[tuple[float, float, float]]:
    """Return ``(x, low, high)`` for every crossing of zero by ``residual``.

    The abscissa is interpolated in log space, which is the variable a root
    search over a ratio actually walks, so the reported value does not depend
    on where the sweep put its points.
    """
    keep = np.isfinite(values) & np.isfinite(residual)
    x, gap = values[keep], residual[keep]
    found = [(float(point), float(point), float(point)) for point in x[gap == 0.0]]
    for index in range(x.size - 1):
        low, high = float(gap[index]), float(gap[index + 1])
        if low * high >= 0.0:
            continue
        weight = low / (low - high)
        left, right = float(x[index]), float(x[index + 1])
        crossing = 10.0 ** (np.log10(left) + weight * (np.log10(right) - np.log10(left)))
        found.append((float(crossing), left, right))
    return sorted(found)
