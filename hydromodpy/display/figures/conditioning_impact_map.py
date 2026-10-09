"""Map of the top difference between two runs on one mesh."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureNotApplicable, FigureSpec, run_suffix
from hydromodpy.display.figure_options import Cmap, Opt, ReferenceRun
from hydromodpy.display.figure_registry import register
from hydromodpy.display.maps.ugrid import render_face_field

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


def _top_surface(run: Run) -> np.ndarray:
    """Per-cell model top (the persisted mesh topography)."""
    topo = run.mesh.topography
    if topo is None:
        raise ValueError(
            "conditioning_impact_map: run has no persisted per-cell topography; "
            "re-run with a solver that writes the mesh topography array"
        )
    return np.asarray(topo, dtype=float).ravel()


@register
class ConditioningImpactMap(BaseFigure):
    """Per-cell top difference between two runs on one mesh (``sim`` minus ``reference``).

    It maps what one configuration did to the model top against another: fill
    against capped breach, bed regularisation off against on (blue = lowered,
    red = raised). ``reference=<run>`` is required and both runs must share the
    mesh. Lake cells cancel out when their bed is carved identically, so the map
    shows the aquifer modification.
    """

    spec = FigureSpec(
        name="conditioning_impact_map",
        title="Top difference between two runs",
        kind="comparison",
        default_figsize=(7.5, 6.0),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Skip, with a sentence, a run that kept no mesh top to compare."""
        try:
            mesh = sim.mesh
        except (RuntimeError, KeyError, FileNotFoundError) as exc:
            return f"run carries no mesh to compare ({type(exc).__name__})"
        if mesh is None or mesh.topography is None:
            return "run persisted no mesh topography"
        return super().unavailable_reason(sim)

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        reference: ReferenceRun = None,
        cmap: Cmap = "RdBu_r",
        clip_percentile: Annotated[
            float,
            Opt(
                "Percentile of the absolute differences that sets the ends of the "
                "colour scale, never under 0.5 m, so a few carved cells do not flatten "
                "the rest.",
                unit="%",
            ),
        ] = 99.0,
        **_,
    ) -> Axes:
        if reference is None:
            raise FigureNotApplicable(
                "this figure differences the tops of two runs on one mesh: pass reference=<run>."
            )
        top = _top_surface(sim)
        ref = _top_surface(reference)
        if top.shape != ref.shape:
            raise ValueError(
                f"conditioning_impact_map: meshes differ (sim {top.size} cells, "
                f"reference {ref.size}); both runs must share the delineation and grid"
            )
        delta = top - ref
        finite = delta[np.isfinite(delta)]
        vmax = float(np.percentile(np.abs(finite), clip_percentile)) if finite.size else 1.0
        vmax = max(vmax, 0.5)
        frac = float(np.mean(np.abs(finite) > 0.01)) if finite.size else 0.0
        render_face_field(
            ax,
            sim,
            delta,
            cmap=cmap,
            vmin=-vmax,
            vmax=vmax,
            cbar_label="top - reference top (m)  |  red raised, blue lowered",
        )
        ax.set_title(
            f"Top differs from the reference{run_suffix(reference, ' {}')}: "
            f"{frac * 100:.0f}% of cells (scale +/-{vmax:.1f} m){run_suffix(sim)}"
        )
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        return ax
