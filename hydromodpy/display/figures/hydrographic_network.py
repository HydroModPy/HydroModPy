"""Standalone views of one canonical hydrographic network by role."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.maps.axes import overlay_watershed_contour, style_relative_km_axes
from hydromodpy.display.maps.geo import GeoFigureMixin, project_gdf_for_metric_operations
from hydromodpy.display.maps.overlays import NetworkMap, network_map_of_role, plot_network_map

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


class _HydrographicNetworkRoleFigure(GeoFigureMixin, BaseFigure):
    """Render one persisted hydrographic network for a fixed canonical role.

    A mapped role draws the snapped map the run stored under
    ``[geographic.snap_streams] mode = "apply"``, one square per mapped cell,
    and the raw network otherwise (:func:`network_map_of_role`). When the
    snap is on, the note names the map drawn.
    """

    role: str
    color: str
    title: str
    subtitle: str

    def unavailable_reason(self, sim: Run) -> str | None:
        """Require the persisted network of this role.

        The requirement is a geographic feature, not a Zarr field or a
        catalog table, so it is expressed here instead of in ``spec``.
        """
        if not sim.has_hydrographic_network(self.role):
            return f"run has no '{self.role}' hydrographic network"
        return None

    def render(self, sim: Run, ax: Axes, **_) -> Axes:
        network = network_map_of_role(sim, self.role)
        raw_gdf = network.frame
        if raw_gdf is None or raw_gdf.empty:
            raise KeyError(
                f"hydrographic network figure '{self.spec.name}': "
                f"no '{self.role}' network for sim {sim.sim_id}"
            )

        watershed = _read_watershed(sim)
        fallback_crs = None if watershed is None else watershed.crs
        gdf = project_gdf_for_metric_operations(raw_gdf, fallback_crs=fallback_crs)
        if watershed is not None and gdf.crs is not None and watershed.crs is not None:
            if str(watershed.crs) != str(gdf.crs):
                watershed = watershed.to_crs(gdf.crs)

        plot_topography_background(ax, sim)
        plot_network_map(ax, network, gdf, color=self.color, linewidth=1.5, alpha=0.98, zorder=4)
        _outline_watershed(ax, sim, watershed, gdf)
        _frame_on(ax, gdf)
        style_relative_km_axes(ax)
        self.add_scale_bar(ax)
        self.add_north_arrow(ax)
        ax.set_title(self.title)
        ax.text(
            0.02,
            0.98,
            "\n".join(_note_lines(self.subtitle, network, gdf)),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8.2,
            bbox={"facecolor": "white", "alpha": 0.88, "edgecolor": "#c8c8c8"},
        )
        return ax


@register
class HydrographicNetworkReferenceFigure(_HydrographicNetworkRoleFigure):
    spec = FigureSpec(
        name="hydrographic_network_reference",
        title="Reference hydrographic network",
        kind="comparison",
        default_figsize=(7.8, 5.8),
    )
    role = "reference"
    color = "#123f6d"
    title = "Reference network"
    subtitle = "data.hydrography"


@register
class HydrographicNetworkGeneratedFigure(_HydrographicNetworkRoleFigure):
    spec = FigureSpec(
        name="hydrographic_network_generated",
        title="Generated hydrographic network",
        kind="comparison",
        default_figsize=(7.8, 5.8),
    )
    role = "generated"
    color = "#c2410c"
    title = "Generated from DEM"
    subtitle = "geographic.river_network"


PERMANENT_COLOR = "#123f6d"
"""Line colour of the permanent reaches, the minimal map."""

NOT_PERMANENT_COLOR = "#e66100"
"""Line colour of the reaches the maximal map adds to the minimal one."""

_PERMANENCE_COLUMN = "permanence"
"""The canonical column of ``hydromodpy.data.source.permanence``, read by name."""


@register
class HydrographicNetworkPermanenceFigure(GeoFigureMixin, BaseFigure):
    """Draw the mapped network split by permanence: the minimal and the maximal map.

    The maximal map is the ``reference`` role, every mapped reach. The minimal
    map is the ``reference_permanent`` role, the reaches that flow all year,
    which the loader writes only when its source says which reaches do (BD
    Topage, or a file with a ``permanence`` column). The reaches of the
    maximal map outside the minimal one are the intermittent extension. These
    are the two maps the two-bound network criterion scores, drawn as the run
    stored them: snapped under ``[geographic.snap_streams] mode = "apply"``.
    """

    spec = FigureSpec(
        name="hydrographic_network_permanence",
        title="Permanent and intermittent network",
        kind="comparison",
        default_figsize=(7.8, 5.8),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Require both mapped roles."""
        if not sim.has_hydrographic_network("reference"):
            return "run has no 'reference' hydrographic network"
        if not sim.has_hydrographic_network("reference_permanent"):
            return (
                "run has no 'reference_permanent' hydrographic network: its hydrography "
                "source does not say which reaches flow all year"
            )
        return None

    def render(self, sim: Run, ax: Axes, **_) -> Axes:
        from matplotlib.lines import Line2D

        maximal = network_map_of_role(sim, "reference")
        minimal = network_map_of_role(sim, "reference_permanent")
        for network in (maximal, minimal):
            if network.frame is None or network.frame.empty:
                raise KeyError(
                    f"hydrographic network figure '{self.spec.name}': "
                    f"no '{network.role}' network for sim {sim.sim_id}"
                )

        watershed = _read_watershed(sim)
        fallback_crs = None if watershed is None else watershed.crs
        max_gdf = project_gdf_for_metric_operations(maximal.frame, fallback_crs=fallback_crs)
        min_gdf = project_gdf_for_metric_operations(minimal.frame, fallback_crs=fallback_crs)
        if max_gdf.crs is not None and min_gdf.crs is not None:
            if str(min_gdf.crs) != str(max_gdf.crs):
                min_gdf = min_gdf.to_crs(max_gdf.crs)
        if watershed is not None and max_gdf.crs is not None and watershed.crs is not None:
            if str(watershed.crs) != str(max_gdf.crs):
                watershed = watershed.to_crs(max_gdf.crs)

        plot_topography_background(ax, sim)
        # The whole map first, the permanent reaches over it: what shows of the
        # lower layer is the intermittent extension.
        plot_network_map(
            ax, maximal, max_gdf, color=NOT_PERMANENT_COLOR, linewidth=1.3, alpha=0.95, zorder=4
        )
        plot_network_map(
            ax, minimal, min_gdf, color=PERMANENT_COLOR, linewidth=2.0, alpha=0.98, zorder=5
        )
        _outline_watershed(ax, sim, watershed, max_gdf)
        _frame_on(ax, max_gdf)
        style_relative_km_axes(ax)
        self.add_scale_bar(ax)
        self.add_north_arrow(ax)
        ax.set_title(self.spec.title)

        size_min = _map_size(minimal, min_gdf)
        size_max = _map_size(maximal, max_gdf)
        handles = [
            Line2D(
                [],
                [],
                color=PERMANENT_COLOR,
                linewidth=2.0,
                label=f"permanent, minimal map: {size_min.words()}",
            ),
            Line2D(
                [],
                [],
                color=NOT_PERMANENT_COLOR,
                linewidth=1.3,
                label=f"maximal map beyond it: {size_max.minus(size_min).words()}",
            ),
        ]
        # One box: the note as the legend title, so the two never overlap.
        ax.legend(
            handles=handles,
            loc="upper left",
            title="\n".join(_permanence_note_lines(maximal, max_gdf, size_max)),
            title_fontsize=8.2,
            fontsize=8.2,
            alignment="left",
            framealpha=0.88,
        )
        return ax


@dataclass(frozen=True)
class _MapSize:
    """How much of a map is drawn: a length and a reach count, or a cell count."""

    count: int
    length_m: float | None

    def minus(self, other: _MapSize) -> _MapSize:
        """Return the size of this map beyond ``other``, which it contains."""
        length = None
        if self.length_m is not None and other.length_m is not None:
            length = max(self.length_m - other.length_m, 0.0)
        return _MapSize(count=max(self.count - other.count, 0), length_m=length)

    def words(self) -> str:
        """Return the size as a legend reads it."""
        if self.length_m is None:
            return f"{self.count} cells"
        return f"{_fmt_km(self.length_m)}, {self.count} reaches"


def _map_size(network: NetworkMap, gdf) -> _MapSize:
    """Measure a raw map in km and reaches, a snapped one in cells."""
    if network.snapped:
        import numpy as np

        placed = np.where(gdf["snapped_cell"] >= 0, gdf["snapped_cell"], gdf["raw_cell"])
        return _MapSize(count=int(np.unique(placed).size), length_m=None)
    return _MapSize(count=int(len(gdf.index)), length_m=_measure_linework_length_m(gdf))


def _permanence_note_lines(network: NetworkMap, gdf, size: _MapSize) -> list[str]:
    """Return the note: the source, the map drawn, the reaches by permanence class."""
    lines = ["data.hydrography"]
    label = network.label()
    if label is not None:
        lines.append(label)
    lines.append(f"maximal map: {size.words()}")
    if network.snapped or _PERMANENCE_COLUMN not in gdf.columns:
        return lines
    for value, group in gdf.groupby(_PERMANENCE_COLUMN, sort=True):
        length_m = _measure_linework_length_m(group)
        lines.append(f"  {value}: {_fmt_km(length_m)}, {int(len(group.index))} reaches")
    return lines


def _outline_watershed(ax: Axes, sim: Run, watershed, gdf) -> None:
    """Draw the catchment outline, from its polygon when the run stored one."""
    if watershed is not None and not watershed.empty:
        watershed.boundary.plot(ax=ax, color="#404040", linewidth=0.9, alpha=0.7, zorder=6)
        return
    overlay_watershed_contour(
        ax,
        sim,
        color="#404040",
        linewidth=0.9,
        alpha=0.7,
        target_crs=None if gdf.crs is None else str(gdf.crs),
    )


def _frame_on(ax: Axes, gdf) -> None:
    """Fit the axes to a network, with a margin of four per cent."""
    bounds = _total_bounds(gdf)
    if bounds is None:
        return
    xmin, ymin, xmax, ymax = bounds
    pad_x = max((xmax - xmin) * 0.04, 1.0)
    pad_y = max((ymax - ymin) * 0.04, 1.0)
    ax.set_xlim(xmin - pad_x, xmax + pad_x)
    ax.set_ylim(ymin - pad_y, ymax + pad_y)


def _note_lines(subtitle: str, network: NetworkMap, gdf) -> list[str]:
    """Return the note of a network map: its source, the map drawn, its size."""
    lines = [subtitle]
    label = network.label()
    if label is not None:
        lines.append(label)
    if network.snapped:
        import numpy as np

        placed = np.where(gdf["snapped_cell"] >= 0, gdf["snapped_cell"], gdf["raw_cell"])
        lines.append(f"cells: {int(np.unique(placed).size)} from {int(len(gdf.index))} mapped")
        return lines
    lines.append(f"segments: {int(len(gdf.index))}")
    lines.append(f"length: {_fmt_km(_measure_linework_length_m(gdf))}")
    return lines


def _total_bounds(gdf) -> tuple[float, float, float, float] | None:
    import numpy as np

    if gdf is None or gdf.empty:
        return None
    minx, miny, maxx, maxy = [float(v) for v in gdf.total_bounds]
    if not np.isfinite([minx, miny, maxx, maxy]).all():
        return None
    return (minx, miny, maxx, maxy)


def _read_watershed(sim: Run):
    try:
        gdf = sim.geographic("watershed")
    except Exception:
        return None
    if gdf is None or gdf.empty:
        return None
    return gdf


def plot_topography_background(ax, sim: Run, *, alpha: float = 0.82) -> None:
    """Draw cell topography with the same terrain palette as context maps."""
    import numpy as np
    from matplotlib.collections import PolyCollection

    try:
        mesh = sim.mesh
        z_interfaces = np.asarray(mesh.z_interfaces, dtype=float)
        vertices = np.asarray(mesh.vertices)
        face_node_connectivity = np.asarray(mesh.face_node_connectivity)
    except Exception:
        return
    if z_interfaces.ndim == 1:
        top = z_interfaces
    elif z_interfaces.shape[0] <= z_interfaces.shape[-1]:
        top = z_interfaces[0]
    else:
        top = z_interfaces[:, 0]

    polygons = []
    for row in face_node_connectivity:
        nodes = row[row >= 0] if row.dtype.kind in "iu" else row[~np.isnan(row)]
        polygons.append(vertices[nodes.astype(int)][:, :2])
    flat = np.asarray(top).ravel()
    if flat.size != len(polygons):
        return
    collection = PolyCollection(
        polygons,
        array=flat,
        cmap="terrain",
        edgecolors="none",
        alpha=alpha,
        zorder=0,
    )
    ax.add_collection(collection)
    ax.autoscale_view()


def _measure_linework_length_m(gdf) -> float:
    import numpy as np

    if gdf is None or gdf.empty:
        return 0.0
    metric_gdf = project_gdf_for_metric_operations(gdf)
    return float(np.sum(np.asarray(metric_gdf.length, dtype=float)))


def _fmt_km(length_m: float | None) -> str:
    if length_m is None:
        return "-"
    return f"{length_m / 1000.0:.2f} km"
