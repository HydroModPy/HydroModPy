"""Vertical section colored by the aquifer properties the run was given.

``cross_section`` draws the geometry and the water table, which is what the
solver answered. This draws what it was asked: the conductivity and storage
fields, layer by layer, along the same line. A depth-decaying aquifer and a
uniform one give sections that look alike until the parameters are the
color, which is the whole point of the paper figure this reproduces. The
conductivity along the three axes of the K tensor and its three angles are
drawn the same way, the conductivities on one shared scale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import numpy as np

from hydromodpy.display.figure import (
    BaseFigure,
    FigureNotApplicable,
    FigureSpec,
    run_label,
    run_suffix,
)
from hydromodpy.display.figure_options import (
    CmapOrOwn,
    Opt,
    SectionLine,
    SectionOrientation,
    SectionSamples,
    SectionThrough,
)
from hydromodpy.display.figures._parameter_scale import (
    CONDUCTIVITY_FIELDS,
    CYCLIC_FIELDS,
    PARAMETER_CHOICES,
    PARAMETER_FIELDS,
    cmap_for,
    color_norm,
    mark_turn,
    parameter_label,
    parameter_name,
    refuse_other_variable,
    require_property,
    wrapped,
)
from hydromodpy.display.maps.transect import build_transect, layer_interfaces

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.results.run import Run


_LOG_OPTION = (
    "Force a log color scale on or off. Left out, each panel takes a log "
    "scale when its positive values span more than one decade. The conductivities "
    "of one figure share their scale, and the tensor angles are always linear."
)


class ParameterSection(BaseFigure):
    """Aquifer properties along one transect, one panel per property."""

    spec = FigureSpec(
        name="parameter_section",
        title="Parameter section",
        kind="section",
        required_fields=("hydraulic_conductivity", "layer_thickness", "topography"),
        optional_fields=tuple(
            name for name in PARAMETER_FIELDS if name != "hydraulic_conductivity"
        ),
        default_figsize=(11.0, 4.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        variable: Annotated[
            str,
            Opt(f"Property to draw: {PARAMETER_CHOICES}."),
        ] = "hydraulic_conductivity",
        line: SectionLine = None,
        orientation: SectionOrientation = "we",
        through: SectionThrough = None,
        n_samples: SectionSamples = None,
        log: Annotated[bool | None, Opt(_LOG_OPTION)] = None,
        cmap: CmapOrOwn = None,
        **_,
    ) -> Axes:
        require_property(sim, variable, figure="parameter_section")
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
        sampled = self._sample(sim, transect, interfaces, variable)
        self._panel(ax, variable, transect, interfaces, sampled, sampled, log=log, cmap=cmap)
        ax.set_ylabel("Elevation (m)")
        # The panel already names the property, and says when it is uniform.
        label = run_label(sim)
        if label:
            ax.set_title(f"{label}\n{ax.get_title()}")
        return ax

    def plot(
        self,
        sim: Run,
        *,
        variables: Annotated[
            tuple[str, ...] | list[str] | None,
            Opt(
                f"Properties to draw, one panel each: {PARAMETER_CHOICES}. Left out, "
                "every one the run set, K33 only where it differs from K."
            ),
        ] = None,
        line: SectionLine = None,
        orientation: SectionOrientation = "we",
        through: SectionThrough = None,
        n_samples: SectionSamples = None,
        log: Annotated[bool | None, Opt(_LOG_OPTION)] = None,
        cmap: CmapOrOwn = None,
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
        sampled = {name: self._sample(sim, transect, interfaces, name) for name in names}
        shared = _shared_conductivity(sampled)

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
            limits = shared if variable in CONDUCTIVITY_FIELDS else sampled[variable]
            self._panel(
                ax, variable, transect, interfaces, sampled[variable], limits, log=log, cmap=cmap
            )
        axes[0][0].set_ylabel("Elevation (m)")
        fig.suptitle(f"{self.spec.title}{run_suffix(sim)}")
        if save_path is not None:
            fig.savefig(save_path, bbox_inches="tight")
        return fig

    def _sample(
        self,
        sim: Run,
        transect,
        interfaces: np.ndarray,
        variable: str,
    ) -> np.ndarray:
        """Return ``variable`` along the transect, one row per layer."""
        values = np.atleast_2d(np.asarray(sim.field(variable), dtype="float64"))
        if values.shape[0] != interfaces.shape[0] - 1:
            raise ValueError(
                f"parameter_section: {variable!r} has {values.shape[0]} layer(s) "
                f"but the mesh has {interfaces.shape[0] - 1}"
            )
        return wrapped(variable, np.vstack([transect.sample(row) for row in values]))

    def _panel(
        self,
        ax: Axes,
        variable: str,
        transect,
        interfaces: np.ndarray,
        sampled: np.ndarray,
        limits: np.ndarray,
        *,
        log: bool | None,
        cmap: str | None,
    ) -> None:
        """Draw ``sampled`` on ``ax``, its color scale set over ``limits``."""
        sampled_interfaces = np.vstack([transect.sample(row) for row in interfaces])
        x_edges, y_edges = _quad_edges(transect.distance, sampled_interfaces)

        mesh = ax.pcolormesh(
            x_edges,
            y_edges,
            np.ma.masked_invalid(sampled),
            cmap=cmap_for(variable, cmap),
            norm=color_norm(variable, limits, log=log),
            shading="flat",
        )
        descriptor = self.field_descriptor_for(variable)
        name = parameter_name(variable)
        uniform = _uniform_value(sampled)
        if uniform is None:
            colorbar = ax.figure.colorbar(mesh, ax=ax, label=parameter_label(variable))
            if variable in CYCLIC_FIELDS:
                mark_turn(colorbar)
            ax.set_title(name, fontsize=10)
        else:
            # A colorbar around a single value pads a range matplotlib invented,
            # and a reader takes that padding for variation the run does not have.
            ax.set_title(f"{name}\nuniform, {uniform:.3g} {descriptor.units}", fontsize=10)
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
    zero. Drawing it produces a flat panel on a color scale invented around
    nothing, which reads as a result rather than as an absence, so a property
    that is zero everywhere is dropped unless it was asked for by name. A
    property asked for by name that the run does not hold is refused by name,
    where a figure left to choose draws only what the run has.
    """
    asked = bool(variables)
    names = [str(name) for name in variables] if variables else list(PARAMETER_FIELDS)
    for name in names:
        refuse_other_variable(name, figure="parameter_section")
    present = [name for name in names if sim.has_field(name)]
    missing = [name for name in names if name not in present]
    if asked and present and missing:
        named = ", ".join(repr(name) for name in missing)
        raise FigureNotApplicable(f"parameter_section: {named} is not in this run")
    drawn = present if asked else [name for name in present if _is_drawn_by_default(sim, name)]
    if not drawn:
        raise FigureNotApplicable(
            f"parameter_section: none of {', '.join(names)} is set in this run"
        )
    return drawn


def _is_set(sim: Run, variable: str) -> bool:
    """Return whether the run gave ``variable`` anything but zeros."""
    values = np.asarray(sim.field(variable), dtype="float64")
    return bool(np.any(np.isfinite(values) & (values != 0.0)))


def _is_drawn_by_default(sim: Run, variable: str) -> bool:
    """Return whether a figure left to choose gives ``variable`` a panel.

    MODFLOW 6 stores K33 for every run, equal to K when the aquifer is not
    anisotropic, and a panel that repeats the one beside it says nothing.
    """
    if not _is_set(sim, variable):
        return False
    if variable == "hydraulic_conductivity_k33" and sim.has_field("hydraulic_conductivity"):
        k = np.asarray(sim.field("hydraulic_conductivity"), dtype="float64")
        k33 = np.asarray(sim.field(variable), dtype="float64")
        return k.shape != k33.shape or not np.allclose(k, k33, rtol=1e-9, atol=0.0, equal_nan=True)
    return True


def _shared_conductivity(sampled: dict[str, np.ndarray]) -> np.ndarray:
    """Return every conductivity drawn, which sets the one scale they share."""
    rows = [values.ravel() for name, values in sampled.items() if name in CONDUCTIVITY_FIELDS]
    return np.concatenate(rows) if rows else np.empty(0)


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


def _quad_edges(distance: np.ndarray, interfaces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the ``(n_layers + 1, n_samples + 1)`` corners of the section quads.

    The interfaces are known at the sample points; the quads need them at the
    boundaries between samples, so each interface is interpolated onto the
    edge abscissa rather than shifted by half a cell. Samples that fell
    outside the mesh carry no elevation, and a corner with no coordinate
    would drop its two neighboring quads, so they are extended from the
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
