"""Distribution of the solute concentration across the domain, over time.

A concentration map answers "where" at one instant; this answers "how the
whole domain moves". One box per timestep, so the median tells whether the
plume is still being flushed, and the spread between the whiskers tells
whether the domain is becoming uniform or splitting into a clean part and a
loaded one. A reference concentration - a drinking-water limit, an input
concentration - can be drawn across it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.legend_placement import place_legend

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class ConcentrationBoxplot(BaseFigure):
    """One box of the per-cell concentration per timestep."""

    spec = FigureSpec(
        name="concentration_boxplot",
        title="Concentration distribution over time",
        kind="timeseries",
        required_fields=("concentration",),
        default_figsize=(8.0, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        layer: int | None = None,
        reference: float | None = None,
        scale: float = 1.0,
        units: str = "kg/m³",
        max_steps: int = 60,
        **_,
    ) -> Axes:
        n_steps = int(sim.n_timesteps or 0)
        if n_steps == 0:
            raise ValueError(f"no timestep recorded for sim {sim.sim_id}")
        step = max(1, n_steps // max_steps)
        steps = list(range(0, n_steps, step))

        samples: list[np.ndarray] = []
        kept: list[int] = []
        for index in steps:
            values = np.asarray(sim.field("concentration", timestep=index, layer=layer))
            finite = values[np.isfinite(values)] * scale
            if finite.size:
                samples.append(finite)
                kept.append(index)
        if not samples:
            raise ValueError(f"concentration field holds no finite cell for sim {sim.sim_id}")

        ax.boxplot(
            samples,
            positions=kept,
            widths=0.6 * step,
            showfliers=False,
            medianprops={"color": "#b3202c", "lw": 1.4},
            boxprops={"color": "#2e7d32"},
            whiskerprops={"color": "#2e7d32"},
            capprops={"color": "#2e7d32"},
        )
        ax.plot(
            kept,
            [float(sample.mean()) for sample in samples],
            lw=1.2,
            color="#1f6fb4",
            marker="o",
            ms=3,
            label="domain mean",
        )
        if reference is not None:
            ax.axhline(
                reference, color="k", lw=1.2, ls="--", label=f"reference {reference:g} {units}"
            )

        ax.set_xlabel("Timestep")
        ax.set_ylabel(f"Concentration ({units})")
        ax.grid(True, ls=":", lw=0.4)
        shown = f"{len(kept)} of {n_steps}" if step > 1 else f"{n_steps}"
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}\n{shown} timesteps")
        place_legend(ax, fontsize=8, framealpha=0.9)
        return ax
