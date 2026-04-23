"""Mean recharge map per cell."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display._map_axes import overlay_watershed_contour, style_map_axes
from hydromodpy.display._ugrid import last_timestep, render_face_field
from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class RechargeMap(BaseFigure):
    """Per-cell recharge at a single timestep.

    Reads the ``recharge`` field from the Zarr store. If ``timestep`` is None
    the latest available step is used.
    """

    spec = FigureSpec(
        name="recharge_map",
        title="Recharge map",
        kind="spatial",
        required_fields=("recharge",),
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        timestep: int | None = None,
        cmap: str = "YlGnBu",
        **_,
    ) -> Axes:
        ts = last_timestep(sim) if timestep is None else timestep
        rch = np.asarray(sim.field("recharge", timestep=ts))
        if rch.ndim == 2:
            rch = rch[0]
        render_face_field(ax, sim, rch, cmap=cmap, cbar_label="Recharge (m/d)")
        overlay_watershed_contour(ax, sim)
        style_map_axes(ax)
        # Spatially uniform recharge produces a cosmetic colorbar with a
        # microscopic range - annotate the mean value so the plot is readable.
        mean_val = float(rch[~_nanmask(rch)].mean()) if rch.size else 0.0
        title = f"Recharge - {sim.name or sim.sim_id}"
        if rch.size and _is_uniform(rch):
            title += f"  ({mean_val:.2e} m/d, uniform)"
        ax.set_title(title)
        return ax


def _nanmask(a):
    import numpy as _np

    return _np.isnan(a)


def _is_uniform(a, *, rtol: float = 1e-9) -> bool:
    """Return True when the non-NaN values of ``a`` are all equal."""
    import numpy as _np

    vals = a[~_np.isnan(a)]
    if vals.size == 0:
        return False
    return bool(_np.allclose(vals, vals.flat[0], rtol=rtol))
