"""Vertical section coloured by the aquifer properties the run was given.

``cross_section`` draws the geometry and the water table, which is what the
solver answered. This draws what it was asked: the conductivity and storage
fields, layer by layer, along the same line. A depth-decaying aquifer and a
uniform one give sections that look alike until the parameters are the
colour, which is the whole point of the paper figure this reproduces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.transect import build_transect, layer_interfaces

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run


PARAMETER_FIELDS = ("hydraulic_conductivity", "specific_yield", "specific_storage")
"""Aquifer properties this section can colour, in the order panels are drawn."""

LOG_SCALE_DECADES = 1.0
"""Span, in decades, above which a parameter is coloured on a log scale."""


@register
class ParameterSection(BaseFigure):
    """Aquifer properties along one transect, one panel per property.

    Options
    -------
    ``variables``
        Properties to draw. Defaults to every one the run persisted.
    ``line``
        ``[x0, y0, x1, y1]`` in the project CRS. Overrides ``orientation``.
    ``orientation``
        ``"we"`` (west to east, default) or ``"sn"`` (south to north).
    ``through``
        ``[x, y]`` the section must pass through. Defaults to the outlet.
    ``log``
        Force a log colour scale on or off. Defaults to deciding per panel.
    """

    spec = FigureSpec(
        name="parameter_section",
        title="Parameter section",
        kind="section",
        required_fields=("hydraulic_conductivity", "layer_thickness", "topography"),
        optional_fields=("specific_yield", "specific_storage"),
        default_figsize=(11.0, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        variable: str = "hydraulic_conductivity",
        line: tuple[float, float, float, float] | list[float] | None = None,
        orientation: str = "we",
        through: tuple[float, float] | list[float] | None = None,
        n_samples: int | None = None,
        log: bool | None = None,
        cmap: str = "viridis",
        **_,
    ) -> Axes:
        transect = _section_transect(
            sim,
            line=line,
            orientation=orientation,
            through=through,
            n_samples=n_samples,
        )
        interfaces = layer_interfaces(sim)
        if interfaces is None:
            raise ValueError("parameter_section: the run persisted no layer thickness")
        self._panel(ax, sim, transect, interfaces, variable, log=log, cmap=cmap)
        ax.set_ylabel("Elevation (m)")
        # The panel already names the property, and says when it is uniform.
        ax.set_title(f"{sim.name or sim.sim_id}\n{ax.get_title()}")
        return ax

    def plot(
        self,
        sim: Run,
        *,
        variables: tuple[str, ...] | list[str] | None = None,
        line: tuple[float, float, float, float] | list[float] | None = None,
        orientation: str = "we",
        through: tuple[float, float] | list[float] | None = None,
        n_samples: int | None = None,
        log: bool | None = None,
        cmap: str = "viridis",
        figsize: tuple[float, float] | None = None,
        dpi: int = 150,
        save_path=None,
        **_,
    ) -> MplFigure:
        import matplotlib.pyplot as plt

        names = _resolve_variables(sim, variables)
        transect = _section_transect(
            sim,
            line=line,
            orientation=orientation,
            through=through,
            n_samples=n_samples,
        )
        interfaces = layer_interfaces(sim)
        if interfaces is None:
            raise ValueError("parameter_section: the run persisted no layer thickness")

        width, height = figsize or self.spec.default_figsize
        fig, axes = plt.subplots(
            1,
            len(names),
            figsize=(width * len(names) / 2.0, height),
            dpi=dpi,
            sharey=True,
            constrained_layout=True,
            squeeze=False,
        )
        for ax, variable in zip(axes[0], names, strict=True):
            self._panel(ax, sim, transect, interfaces, variable, log=log, cmap=cmap)
        axes[0][0].set_ylabel("Elevation (m)")
        fig.suptitle(f"{self.spec.title} - {sim.name or sim.sim_id}")
        if save_path is not None:
            fig.savefig(save_path, bbox_inches="tight")
        return fig

    def _panel(
        self,
        ax: Axes,
        sim: Run,
        transect,
        interfaces: np.ndarray,
        variable: str,
        *,
        log: bool | None,
        cmap: str,
    ) -> None:
        from matplotlib.colors import LogNorm

        values = np.atleast_2d(np.asarray(sim.field(variable), dtype="float64"))
        if values.shape[0] != interfaces.shape[0] - 1:
            raise ValueError(
                f"parameter_section: {variable!r} has {values.shape[0]} layer(s) "
                f"but the mesh has {interfaces.shape[0] - 1}"
            )
        sampled = np.vstack([transect.sample(row) for row in values])
        sampled_interfaces = np.vstack([transect.sample(row) for row in interfaces])
        x_edges, y_edges = _quad_edges(transect.distance, sampled_interfaces)

        norm = None
        if _use_log_scale(sampled) if log is None else bool(log):
            positive = sampled[np.isfinite(sampled) & (sampled > 0.0)]
            if positive.size:
                norm = LogNorm(vmin=float(positive.min()), vmax=float(positive.max()))
        mesh = ax.pcolormesh(
            x_edges,
            y_edges,
            np.ma.masked_invalid(sampled),
            cmap=cmap,
            norm=norm,
            shading="flat",
        )
        descriptor = self.field_descriptor_for(variable)
        uniform = _uniform_value(sampled)
        if uniform is None:
            ax.figure.colorbar(mesh, ax=ax, label=self.axis_label_for(variable))
            ax.set_title(descriptor.long_name, fontsize=10)
        else:
            # A colorbar around a single value pads a range matplotlib invented,
            # and a reader takes that padding for variation the run does not have.
            ax.set_title(
                f"{descriptor.long_name}\nuniform, {uniform:.3g} {descriptor.units}",
                fontsize=10,
            )
        inside = transect.inside
        ax.set_xlim(
            float(transect.distance[inside].min()),
            float(transect.distance[inside].max()),
        )
        ax.set_xlabel("Distance along section (m)")

    def unavailable_reason(self, sim: Run) -> str | None:
        reason = super().unavailable_reason(sim)
        if reason is not None:
            return reason
        if layer_interfaces(sim) is None:
            return "the run persisted no per-face layer thickness"
        return None


def _resolve_variables(sim: Run, variables: tuple[str, ...] | list[str] | None) -> list[str]:
    """Return the properties to draw, refusing a run that persisted none.

    A property left out of ``param_list`` is still handed to the solver, as
    zero. Drawing it produces a flat panel on a colour scale invented around
    nothing, which reads as a result rather than as an absence, so a property
    that is zero everywhere is dropped unless it was asked for by name.
    """
    asked = variables is not None
    names = [str(name) for name in variables] if variables else list(PARAMETER_FIELDS)
    present = [name for name in names if sim.has_field(name)]
    if not asked:
        present = [name for name in present if _is_set(sim, name)]
    if not present:
        raise ValueError(f"parameter_section: none of {', '.join(names)} is set in this run")
    return present


def _is_set(sim: Run, variable: str) -> bool:
    """Return whether the run gave ``variable`` anything but zeros."""
    values = np.asarray(sim.field(variable), dtype="float64")
    return bool(np.any(np.isfinite(values) & (values != 0.0)))


def _section_transect(
    sim: Run,
    *,
    line,
    orientation: str,
    through,
    n_samples: int | None,
):
    transect = build_transect(
        sim,
        line=tuple(line) if line is not None else None,
        orientation="sn" if str(orientation).lower() == "sn" else "we",
        through=tuple(through) if through is not None else None,
        n_samples=n_samples,
    )
    if not transect.inside.any():
        raise ValueError("parameter_section: the line does not intersect the mesh")
    return transect


def _uniform_value(values: np.ndarray) -> float | None:
    """Return the single value ``values`` holds, or None when it varies."""
    finite = values[np.isfinite(values)]
    if finite.size == 0 or float(finite.min()) != float(finite.max()):
        return None
    return float(finite[0])


def _use_log_scale(values: np.ndarray) -> bool:
    """A parameter spanning more than a decade reads as flat on a linear scale."""
    positive = values[np.isfinite(values) & (values > 0.0)]
    if positive.size == 0:
        return False
    return float(np.log10(positive.max() / positive.min())) > LOG_SCALE_DECADES


def _quad_edges(distance: np.ndarray, interfaces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the ``(n_layers + 1, n_samples + 1)`` corners of the section quads.

    The interfaces are known at the sample points; the quads need them at the
    boundaries between samples, so each interface is interpolated onto the
    edge abscissa rather than shifted by half a cell. Samples that fell
    outside the mesh carry no elevation, and a corner with no coordinate
    would drop its two neighbouring quads, so they are extended from the
    nearest interface the line did cross.
    """
    edges = np.empty(distance.size + 1, dtype="float64")
    edges[1:-1] = 0.5 * (distance[:-1] + distance[1:])
    edges[0] = distance[0] - 0.5 * (distance[1] - distance[0])
    edges[-1] = distance[-1] + 0.5 * (distance[-1] - distance[-2])

    rows = []
    for row in interfaces:
        known = np.isfinite(row)
        if not known.any():
            raise ValueError("parameter_section: the line crossed no layered cell")
        rows.append(np.interp(edges, distance[known], row[known]))
    y_edges = np.vstack(rows)
    x_edges = np.broadcast_to(edges, y_edges.shape)
    return np.asarray(x_edges, dtype="float64"), y_edges
