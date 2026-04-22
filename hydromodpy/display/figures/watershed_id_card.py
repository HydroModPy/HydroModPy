"""Watershed identity-card multi-panel figure.

Combines a topography map, outlet marker, a hydrograph preview and
a metadata table into a single compact summary figure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydromodpy.display.catalog import register
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.geo import GeoFigureMixin

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run


@register
class WatershedIdCardFigure(GeoFigureMixin, BaseFigure):
    """Six-panel summary: topography, outlet, hydrograph, metadata table."""

    spec = FigureSpec(
        name="watershed_id_card",
        title="Watershed identity card",
        kind="comparison",
        default_figsize=(10.0, 7.0),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        **_,
    ) -> Axes:
        ax.set_axis_off()
        ax.text(
            0.5,
            0.5,
            "watershed_id_card has its own plot()",
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
        save_path=None,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec

        fig = plt.figure(
            figsize=figsize or self.spec.default_figsize,
            dpi=dpi,
            constrained_layout=True,
        )
        gs = GridSpec(3, 3, figure=fig)

        ax_topo = fig.add_subplot(gs[:2, :2])
        ax_hydro = fig.add_subplot(gs[2, :2])
        ax_meta = fig.add_subplot(gs[:, 2])

        # -- Topography + outlet --
        try:
            dem = sim.geographic_raster("dem")
            ax_topo.imshow(dem, cmap="terrain", origin="upper")
        except Exception:
            ax_topo.text(0.5, 0.5, "no DEM", ha="center", va="center", transform=ax_topo.transAxes)
        ax_topo.set_title("Topography")
        ax_topo.set_aspect("equal", adjustable="datalim")
        try:
            self.add_scale_bar(ax_topo)
            self.add_north_arrow(ax_topo)
        except Exception:
            pass

        # -- Hydrograph preview --
        try:
            ts = sim.timeseries("discharge", station="_catchment")
            ax_hydro.plot(ts.index, ts.values, color="steelblue", lw=1.0)
            ax_hydro.set_ylabel("Q (m³/s)")
            ax_hydro.set_xlabel("Date")
            ax_hydro.grid(True, ls=":", lw=0.4)
        except Exception:
            ax_hydro.text(
                0.5, 0.5, "no hydrograph", ha="center", va="center", transform=ax_hydro.transAxes
            )
        ax_hydro.set_title("Outlet discharge")

        # -- Metadata table --
        ax_meta.set_axis_off()
        rows: list[tuple[str, str]] = [
            ("ID", str(sim.sim_id)),
            ("Name", str(sim.name or "")),
            ("Project", str(sim.project or "")),
            ("Solver", str(sim.solver or "")),
            ("Regime", str(sim.flow_regime or "")),
            ("Status", str(sim.status or "")),
            ("Cells", str(sim.n_cells or "-")),
            ("Layers", str(sim.n_layers or "-")),
            ("Timesteps", str(sim.n_timesteps or "-")),
        ]
        table = ax_meta.table(
            cellText=[[k, v] for k, v in rows],
            loc="center",
            colWidths=[0.45, 0.55],
            cellLoc="left",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.0, 1.3)
        ax_meta.set_title("Identity")

        fig.suptitle(f"Watershed ID card — {sim.name or sim.sim_id}", fontweight="bold")
        if save_path is not None:
            from pathlib import Path

            self._save(fig, Path(save_path), dpi=dpi)
        return fig
