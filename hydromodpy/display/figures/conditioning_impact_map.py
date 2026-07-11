"""Map of how much surface conditioning modified the mesh top (the DEM)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.ugrid import render_face_field

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
    """Per-cell change of the mesh top from surface conditioning (the fill + breach).

    Delta = the conditioned top minus the pre-conditioning top on the run's own
    mesh (blue = lowered, red = raised). By default the reference is the
    pre-conditioning top persisted beside the topography, so a single conditioned
    run renders its own impact. Passing another run as ``reference`` overrides it
    with a two-run difference (both must share the mesh). Lake cells cancel out
    (their bed is carved identically), so the map shows the aquifer modification.
    """

    spec = FigureSpec(
        name="conditioning_impact_map",
        title="Conditioning impact on the DEM",
        kind="comparison",
        default_figsize=(7.5, 6.0),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        reference: Run | None = None,
        cmap: str = "RdBu_r",
        clip_percentile: float = 99.0,
        **_,
    ) -> Axes:
        top = _top_surface(sim)
        if reference is not None:
            ref = _top_surface(reference)
        else:
            ref = sim.mesh.topography_reference
            if ref is None:
                raise ValueError(
                    "conditioning_impact_map: this run has no persisted "
                    "pre-conditioning top; run with condition_top on, or pass a "
                    "'reference' run sharing the mesh"
                )
            ref = np.asarray(ref, dtype=float).ravel()
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
            cbar_label="conditioned top - reference (m)  |  red raised, blue lowered",
        )
        ax.set_title(
            f"DEM modified by conditioning: {frac * 100:.0f}% of cells "
            f"(scale +/-{vmax:.1f} m) - {sim.sim_id}"
        )
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        return ax
