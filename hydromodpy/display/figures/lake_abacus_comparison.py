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

from hydromodpy.core.metrics.goodness_of_fit import nse, rmse
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

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
    """Reference vs simulated lake abacus (stage-volume), requestable via display."""

    spec = FigureSpec(
        name="lake_abacus_comparison",
        title="Lake abacus comparison",
        kind="comparison",
        default_figsize=(7.0, 5.0),
    )

    def render(self, sim: Run, ax: Axes, *, lake_id: str | None = None, **_: Any) -> Axes:
        from hydromodpy.results.lake_abacus_view import run_lake_abacus

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

        ax.plot(
            stage, real_volume, color="black", lw=1.6, marker="o", ms=3, label="Abacus (reference)"
        )
        ax.plot(
            stage,
            sim_volume,
            color="firebrick",
            lw=1.6,
            marker="s",
            ms=3,
            label="Simulated (carved bed)",
        )
        ax.set_xlabel(f"Stage [{stage_unit}]")
        ax.set_ylabel(f"Volume [{vol_unit}]")
        ax.set_title(f"Lake abacus - {lake_id or (sim.name or sim.sim_id)}")
        ax.legend(fontsize=9, loc="best")
        ax.grid(alpha=0.3)

        metrics = lake_abacus_fit_metrics(real_volume, sim_volume)
        if metrics:
            ax.text(
                0.015,
                0.97,
                f"storage NSE = {metrics['nse']:.4f}\nRMSE = {metrics['rmse']:.3g} {vol_unit}",
                transform=ax.transAxes,
                va="top",
                ha="left",
                fontsize=9,
                family="monospace",
                bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8, "edgecolor": "#ccc"},
            )
        return ax
