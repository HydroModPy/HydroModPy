"""Reference-vs-simulated lake abacus figure.

A diagnostic for the bathymetry bed reconstruction: it overlays the user abacus
(stage-volume and stage-area, the storage source of truth) on the abacus the
carved grid actually represents (the cells flooded at each stage). A good carve
makes the two curves overlap. Arrays in, PNG out; the function never touches the
solver or the catalog, so any caller can feed it the two abacus tables.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.metrics import nse, rmse
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run

__all__ = [
    "LakeAbacusComparison",
    "lake_abacus_fit_metrics",
    "plot_lake_abacus_comparison",
]


def lake_abacus_fit_metrics(
    real_volume: Any,
    simulated_volume: Any,
) -> dict[str, float]:
    """Return NSE/RMSE/max-abs-error of the simulated vs real storage curve."""
    real = np.asarray(real_volume, dtype=float)
    sim = np.asarray(simulated_volume, dtype=float)
    mask = np.isfinite(real) & np.isfinite(sim)
    if not np.any(mask):
        return {}
    real = real[mask]
    sim = sim[mask]
    return {
        "nse": float(nse(sim, real)),
        "rmse": float(rmse(sim, real)),
        "max_abs_error": float(np.max(np.abs(sim - real))),
        "n": float(real.size),
    }


def plot_lake_abacus_comparison(
    stage: Any,
    real_volume: Any,
    real_sarea: Any,
    simulated_volume: Any,
    simulated_sarea: Any,
    *,
    out_path: str | Path,
    lake_id: str = "lake",
    stage_unit: str = "m",
    volume_unit: str = "m3",
    area_unit: str = "m2",
    title: str | None = None,
) -> dict[str, float]:
    """Render the abacus comparison figure and return the storage-curve metrics.

    Left panel: stage-volume (real vs simulated). Right panel: stage-area (real
    vs simulated). Storage NSE/RMSE are annotated on the volume panel. The
    returned mapping mirrors :func:`lake_abacus_fit_metrics`.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    stage = np.asarray(stage, dtype=float)
    real_volume = np.asarray(real_volume, dtype=float)
    real_sarea = np.asarray(real_sarea, dtype=float)
    sim_volume = np.asarray(simulated_volume, dtype=float)
    sim_sarea = np.asarray(simulated_sarea, dtype=float)

    metrics = lake_abacus_fit_metrics(real_volume, sim_volume)

    fig, (ax_v, ax_a) = plt.subplots(1, 2, figsize=(11, 4), dpi=150)

    ax_v.plot(
        stage, real_volume, color="black", lw=1.6, marker="o", ms=3, label="Abacus (reference)"
    )
    ax_v.plot(
        stage,
        sim_volume,
        color="firebrick",
        lw=1.6,
        marker="s",
        ms=3,
        label="Simulated (carved bed)",
    )
    ax_v.set_xlabel(f"Stage [{stage_unit}]")
    ax_v.set_ylabel(f"Volume [{volume_unit}]")
    ax_v.set_title(title or f"Lake abacus - {lake_id}")
    ax_v.legend(fontsize=9, loc="best")
    ax_v.grid(alpha=0.3)
    if metrics:
        text = (
            f"storage NSE = {metrics['nse']:.4f}\n"
            f"storage RMSE = {metrics['rmse']:.3g} {volume_unit}\n"
            f"max |dV| = {metrics['max_abs_error']:.3g} {volume_unit}"
        )
        ax_v.text(
            0.015,
            0.97,
            text,
            transform=ax_v.transAxes,
            va="top",
            ha="left",
            fontsize=9,
            family="monospace",
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8, "edgecolor": "#ccc"},
        )

    ax_a.plot(
        stage, real_sarea, color="black", lw=1.6, marker="o", ms=3, label="Abacus (reference)"
    )
    ax_a.plot(
        stage,
        sim_sarea,
        color="steelblue",
        lw=1.6,
        marker="s",
        ms=3,
        label="Simulated (carved bed)",
    )
    ax_a.set_xlabel(f"Stage [{stage_unit}]")
    ax_a.set_ylabel(f"Wetted area [{area_unit}]")
    ax_a.set_title("Stage - area")
    ax_a.legend(fontsize=9, loc="best")
    ax_a.grid(alpha=0.3)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return metrics


@register
class LakeAbacusComparison(BaseFigure):
    """Reference abacus vs the carved-bed geometry, requestable via display.

    This is a GEOMETRY check, not a water-balance one. MODFLOW 6 reads the
    stage-volume-area relation from the ``laktab``, which carries the reference
    abacus verbatim, so lake storage is exact no matter what this figure shows. The
    simulated curve integrates the bed elevations actually carved into the grid: a
    gap means the mesh cuvette is not the real one, which biases the lake-aquifer
    exchange elevations, the seepage, and (in ``dynamic_area`` mode) which cells wet
    and dry at a given stage.
    """

    spec = FigureSpec(
        name="lake_abacus_comparison",
        title="Lake abacus comparison",
        kind="comparison",
        default_figsize=(7.0, 5.0),
    )

    def render(self, sim: Run, ax: Axes, *, lake_id: str | None = None, **_: Any) -> Axes:
        from hydromodpy.results.run.lake_abacus_view import run_lake_abacus

        try:
            ab = run_lake_abacus(sim, lake_id)
        except KeyError:
            ax.text(0.5, 0.5, "no lake abacus", ha="center", va="center", transform=ax.transAxes)
            return ax
        stage = np.asarray(ab["stage"], dtype=float)
        real_volume = np.asarray(ab["real_volume"], dtype=float)
        sim_volume = np.asarray(ab["sim_volume"], dtype=float)
        vol_unit = str(ab.get("volume_unit", "m3"))
        stage_unit = str(ab.get("stage_unit", "m"))

        # Millions of cubic metres: a reservoir abacus spans 1e7, and raw m3 leaves the
        # axis unreadable with an offset exponent in the corner.
        scale, scaled_unit = (1e6, "Mm3") if vol_unit == "m3" else (1.0, vol_unit)
        real_plot = real_volume / scale
        sim_plot = sim_volume / scale

        # No per-point markers: an abacus carries hundreds of rows, and a marker on each
        # of them turns both curves into thick crenellated bands.
        ax.plot(stage, real_plot, color="#111111", lw=2.0, label="Abacus (reference)")
        ax.plot(stage, sim_plot, color="#b3352c", lw=1.8, label="Simulated (carved bed)")
        # The gap IS the message: shade it so an over- or under-storing grid reads at a
        # glance instead of having to compare two nearly parallel lines.
        ax.fill_between(
            stage,
            real_plot,
            sim_plot,
            color="#b3352c",
            alpha=0.16,
            linewidth=0,
            label="Storage gap",
        )
        ax.set_xlabel(f"Stage [{stage_unit}]")
        ax.set_ylabel(f"Volume [{scaled_unit}]")
        # Name the lake, not just the run: a two-lake model renders one curve per lake and
        # the default picks the first, so the run name alone leaves the reader guessing.
        which = lake_id or str(ab.get("lake_id") or "")
        run_label = sim.name or sim.sim_id
        title = f"Lake abacus - {which} ({run_label})" if which else f"Lake abacus - {run_label}"
        ax.set_title(title)
        ax.legend(fontsize=9, loc="upper left", frameon=False)
        ax.grid(alpha=0.25, linewidth=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)

        metrics = lake_abacus_fit_metrics(real_volume, sim_volume)
        if metrics:
            # NOT a storage check: MF6 converts stage to volume through the laktab, which
            # carries the REFERENCE abacus verbatim, so the lake water balance is exact
            # whatever this figure shows. What is compared here is the carved BED geometry
            # (which cells exchange with the lake, at which elevation, and which ones dry
            # out in marnage mode), so the gap bears on lake-aquifer exchange and seepage.
            lines = [
                f"bed fidelity NSE  {metrics['nse']:+.4f}",
                f"RMSE              {metrics['rmse'] / scale:.3g} {scaled_unit}",
            ]
            # The full-pool gap is what a modeller acts on: it says how much storage the
            # grid adds or loses at the crest, where the reservoir actually operates.
            if real_volume[-1] > 0.0:
                gap = 100.0 * (sim_volume[-1] - real_volume[-1]) / real_volume[-1]
                lines.append(f"full pool         {gap:+.1f} % vs reference")
                lines.append("(bed geometry, not lake storage)")
            # One panel holds one lake, but a multi-lake run must not hide the others:
            # list every sibling's full-pool gap so a bad cuvette cannot go unseen just
            # because its lake is not the one plotted.
            siblings = [name for name in ab.get("lake_ids", ()) if name != which]
            if siblings:
                lines.append("")
                lines.append("other lakes (full pool):")
                for name in siblings:
                    try:
                        other = run_lake_abacus(sim, name)
                    except KeyError:  # pragma: no cover - lake listed but unreadable
                        continue
                    other_real = np.asarray(other["real_volume"], dtype=float)
                    other_sim = np.asarray(other["sim_volume"], dtype=float)
                    if other_real.size and other_real[-1] > 0.0:
                        other_gap = 100.0 * (other_sim[-1] - other_real[-1]) / other_real[-1]
                        lines.append(f"  {name}  {other_gap:+.1f} %")
            ax.text(
                0.985,
                0.05,
                "\n".join(lines),
                transform=ax.transAxes,
                va="bottom",
                ha="right",
                fontsize=8.5,
                family="monospace",
                bbox={
                    "boxstyle": "round,pad=0.45",
                    "facecolor": "white",
                    "alpha": 0.85,
                    "edgecolor": "#d0d0d0",
                },
            )
        return ax
