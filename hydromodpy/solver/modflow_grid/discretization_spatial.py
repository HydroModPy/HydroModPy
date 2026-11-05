"""Common spatial discretization builders for MODFLOW-family solvers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.exceptions import MeshError
from hydromodpy.core.fields.grid_reference import GridReference
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.base.protocols import DomainLike
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig, TopSamplingConfig
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_grid.top_sampling import (
    bottom_under_lowered_top,
    cells_cover_pixels,
    lower_crossing_cells,
    zonal_structured_top,
    zonal_top_flat,
)
from hydromodpy.spatial.domain.layering import (
    assert_bottom_below_top,
    coerce_vertical_config,
    layer_stack,
)
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from hydromodpy.spatial.surface_sampling import PreparedSurfaceSampler

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = [
    "StructuredGridBuilder",
    "StructuredGridSpec",
    "build_spatial_discretization",
    "resolve_domain_surfaces",
    "resolve_layer_bases",
    "SolverGridContext",
    "grid_reference_from_solver_mesh",
]

logger = get_logger(__name__)


def resolve_domain_surfaces(
    *,
    domain: DomainLike,
) -> tuple[Surface, Surface]:
    """Return the top and substratum surfaces used by spatial gridding.

    The domain builds its substratum on the grid of its top surface, so both
    have one shape. The extent is still compared, since a planar mesh samples
    each surface on its own.
    """
    if domain is None:
        raise ValueError("Modflow spatial geometry is domain-only: a Domain object is required.")

    surface_topo = getattr(domain, "surface_topo", None)
    substratum = getattr(domain, "substratum", None)
    if surface_topo is None or substratum is None:
        raise ValueError(
            "Modflow spatial geometry is domain-only: domain.surface_topo "
            "and domain.substratum are required."
        )
    surface_topo.assert_same_geographic_domain(substratum)
    return surface_topo, substratum


def resolve_layer_bases(
    *,
    domain: DomainLike,
    vertical_config: VerticalGridConfig | None,
) -> dict[str, Surface]:
    """Return the base surfaces the layering reads, by name, from ``domain.layer_bases``.

    Only a layering by surfaces reads any. A name the domain does not hold is
    refused when the layers are built, with the names it holds.
    """
    names = () if vertical_config is None else vertical_config.base_surface_names
    held = getattr(domain, "layer_bases", None) or {}
    return {name: held[name] for name in names if name in held}


# A valid cell thicker than this multiple of the median, and thicker than the floor
# below, is reported. Both bounds are needed: the multiple alone fires on a legitimate
# variable-thickness substratum, the floor alone fires on a genuinely deep aquifer.
_THICKNESS_OUTLIER_FACTOR = 10.0

_THICKNESS_OUTLIER_FLOOR_M = 500.0


def _warn_on_outlier_thickness(*, top: np.ndarray, bot: np.ndarray, valid: np.ndarray) -> None:
    """Report aquifer columns far thicker than the rest of the mesh.

    A raster NODATA sentinel that reaches the sampler as an ordinary elevation is
    interpolated as if it were terrain, so a cell whose stencil straddles the mask
    edge ends up kilometers deep with a perfectly clean top and an active idomain.
    Nothing downstream notices: the model converges and its mass balance closes,
    while those cells carry a transmissivity and a storage several hundred times the
    nominal ones. This check does not change the mesh; it makes the symptom visible
    whatever its cause.
    """
    if not np.any(valid):
        return
    thickness = (top - bot)[valid]
    median = float(np.median(thickness))
    if median <= 0.0:
        return
    limit = max(_THICKNESS_OUTLIER_FACTOR * median, _THICKNESS_OUTLIER_FLOOR_M)
    outliers = thickness > limit
    if not np.any(outliers):
        return
    logger.warning(
        "Aquifer thickness outliers: %d of %d valid cells are thicker than %.4g m "
        "(median thickness %.4g m, worst %.4g m). A cell kilometres deep usually means a "
        "raster NODATA sentinel was sampled as an elevation; check the substratum raster "
        "and the domain extent.",
        int(np.count_nonzero(outliers)),
        int(thickness.size),
        limit,
        median,
        float(thickness.max()),
    )


def _build_extruded_solver_mesh_from_runtime_planar(
    *,
    cell_mesh: PlanarCellMesh,
    top_surface: Surface,
    bottom_surface: Surface,
    vertical_config: VerticalGridConfig | None,
    nodata: float,
    top_sampling: TopSamplingConfig | None = None,
    channel_mask: np.ndarray | None = None,
    base_surfaces: dict[str, Surface] | None = None,
) -> SolverMesh:
    """Extrude an unstructured cell mesh: top, bottom and layer bases sampled at the cell centers."""
    hydro_mesh = cell_mesh.mesh
    x_centers, y_centers = cell_mesh.centers.T

    # Sample top/botm at the cell centers (Voronoi generators or triangle centroids)
    # from the domain surfaces.
    cfg = coerce_vertical_config(vertical_config)
    top_sampler = PreparedSurfaceSampler.from_surface(top_surface)
    bottom_sampler = PreparedSurfaceSampler.from_surface(bottom_surface)
    top_flat = np.asarray(top_sampler.sample(x_centers, y_centers), dtype=float).reshape(-1)
    bottom_flat = np.asarray(bottom_sampler.sample(x_centers, y_centers), dtype=float).reshape(-1)

    # Optional zonal projection: reduce every DEM pixel inside a cell (thalweg on
    # channel pixels) instead of one centroid sample. Default 'centroid' leaves
    # top_flat byte-identical, except on the crossing cells of a river chain, which
    # take their zonal minimum. Only top is zonal; bottom stays on the centroid.
    centroid_top = top_flat
    if top_sampling is not None and top_sampling.mode == "zonal":
        top_flat = zonal_top_flat(
            hydro_mesh=hydro_mesh,
            top_surface=top_surface,
            centroid_top=centroid_top,
            bottom_flat=bottom_flat,
            nodata=nodata,
            top_sampling=top_sampling,
            channel_mask=channel_mask,
            clamp_to_bottom=False,
        )
    else:
        top_flat = lower_crossing_cells(
            cell_mesh=cell_mesh,
            top_surface=top_surface,
            centroid_top=centroid_top,
            bottom_flat=bottom_flat,
            nodata=nodata,
            top_sampling=top_sampling,
        )
    bottom_flat = bottom_under_lowered_top(
        top=top_flat,
        centroid_top=centroid_top,
        bottom=bottom_flat,
        min_thickness_m=float((top_sampling or TopSamplingConfig()).min_thickness_m),
        nodata=nodata,
    )

    invalid = (
        ~np.isfinite(top_flat)
        | ~np.isfinite(bottom_flat)
        | (top_flat <= float(nodata))
        | (bottom_flat <= float(nodata))
    )
    top_flat = np.where(invalid, float(nodata), top_flat)
    bottom_flat = np.where(invalid, float(nodata), bottom_flat)
    assert_bottom_below_top(top=top_flat, bot=bottom_flat, nodata=nodata)
    _warn_on_outlier_thickness(top=top_flat, bot=bottom_flat, valid=~invalid)

    bases = {
        name: np.asarray(
            PreparedSurfaceSampler.from_surface(surface).sample(x_centers, y_centers), dtype=float
        ).reshape(-1)
        for name, surface in (base_surfaces or {}).items()
    }
    stack = layer_stack(
        top=top_flat,
        bottom=bottom_flat,
        invalid=invalid,
        vertical_config=cfg,
        bases=bases,
        nodata=nodata,
    )
    return SolverMesh(cell_mesh=cell_mesh, top=top_flat, botm=stack.botm, idomain=stack.idomain)


_GRID_MATCH_RTOL = 1e-9
"""Relative gap tolerated between the bounds and steps of the DEM grid and of the mesh."""


def _support_steps(support: RasterSupport) -> tuple[float, float]:
    """Cell width and height of a raster support, from its bounds when it holds no step."""
    dx = float(support.dx) if support.dx is not None else None
    dy = float(support.dy) if support.dy is not None else None
    if dx is None:
        dx = (float(support.xmax) - float(support.xmin)) / int(support.ncols)
    if dy is None:
        dy = (float(support.ymax) - float(support.ymin)) / int(support.nrows)
    return abs(dx), abs(dy)


def _assert_grid_matches_cell_mesh(support: RasterSupport, cell_mesh: PlanarCellMesh) -> None:
    """Refuse a regular mesh whose bounds or steps differ from the surfaces it is extruded on.

    The regular path reads the vertical grid from the surfaces and the planar grid
    from the mesh. They describe one grid only if the bounds and the steps agree; a
    drift of either would shift every cell against its elevation.
    """
    nrow, ncol = cell_mesh.structured_shape
    vertices = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    mesh_bounds = (
        float(vertices[:, 0].min()),
        float(vertices[:, 0].max()),
        float(vertices[:, 1].min()),
        float(vertices[:, 1].max()),
    )
    support_bounds = (
        float(support.xmin),
        float(support.xmax),
        float(support.ymin),
        float(support.ymax),
    )
    mesh_steps = (
        (mesh_bounds[1] - mesh_bounds[0]) / ncol,
        (mesh_bounds[3] - mesh_bounds[2]) / nrow,
    )
    support_steps = _support_steps(support)
    extents = (
        abs(support_bounds[1] - support_bounds[0]),
        abs(support_bounds[3] - support_bounds[2]),
    )
    gaps = [abs(mesh_bounds[i] - support_bounds[i]) / extents[i // 2] for i in range(4)] + [
        abs(mesh_steps[i] - support_steps[i]) / support_steps[i] for i in range(2)
    ]
    if max(gaps) > _GRID_MATCH_RTOL:
        raise MeshError(
            "The regular mesh and the DEM grid it is extruded on differ: mesh bounds "
            f"{mesh_bounds} and steps {mesh_steps} against support bounds "
            f"{support_bounds} and steps {support_steps}. "
            "Both must describe the same grid to 1e-9 relative."
        )


@dataclass(frozen=True)
class StructuredGridSpec:
    """The vertical part of a structured grid: top, layer bottoms and ``idomain``.

    ``top`` has the shape of the surfaces, ``botm`` and ``idomain`` one more
    axis for the layers. ``idomain`` is 1 active, 0 outside the domain, -1 a
    pinched cell of a layering by surfaces.
    """

    top: np.ndarray
    botm: np.ndarray
    nlay: int
    idomain: np.ndarray


class StructuredGridBuilder:
    """Build the vertical part of a regular grid from two absolute-elevation surfaces.

    ``top_surface`` and ``bottom_surface`` are absolute altitudes in the same
    datum, and the builder never adds one to the other. The geometry is metric.
    The planar grid is not built here. It is the mesh of the regular engine, and
    ``Surface.resample_to_shape(...)`` resamples the surfaces to its shape
    beforehand. The builder checks that the surfaces describe the same domain,
    asks :func:`hydromodpy.spatial.domain.layering.layer_stack`, which the
    unstructured extrusion calls too, for the layer bottoms and the ``idomain``,
    and returns them with the top in a :class:`StructuredGridSpec`.
    """

    def __init__(self):
        # No hidden state: deterministic transformations only.
        pass

    def build_from_surfaces(
        self,
        top_surface: Surface,
        bottom_surface: Surface,
        vertical_config: VerticalGridConfig | Mapping[str, object] | None = None,
        base_surfaces: Mapping[str, Surface] | None = None,
    ) -> StructuredGridSpec:
        """
        Build one structured grid from two absolute-elevation surfaces.

        The method intentionally separates three steps:
        1. Validate horizontal/geometric compatibility of inputs.
        2. Build `botm` and `idomain` with :func:`layer_stack`.
        3. Return a `StructuredGridSpec`.

        ``base_surfaces`` holds the layer bases a layering by surfaces reads, on
        the grid of ``top_surface``.
        """
        cfg = coerce_vertical_config(vertical_config)

        # 1) Horizontal compatibility checks.
        #    "Same geographic domain" means same CRS + same spatial extent.
        top_surface.assert_same_geographic_domain(bottom_surface)

        support = top_surface.support
        if support is None:
            raise ValueError("Top surface must carry a RasterSupport.")
        support.assert_complete_domain()

        top = np.asarray(top_surface.as_array(), dtype=float)
        bot = np.asarray(bottom_surface.as_array(), dtype=float)
        if top.shape != bot.shape:
            raise ValueError(
                "top_surface and bottom_surface must have the same discretization "
                f"before vertical grid construction: top{top.shape} != bottom{bot.shape}. "
                "Use Surface.resample_to_shape(...) beforehand."
            )

        nodata = float(cfg.nodata)

        # Mask invalid cells consistently in both surfaces.
        invalid = ~np.isfinite(top) | ~np.isfinite(bot) | (top <= nodata) | (bot <= nodata)
        top = np.array(top, dtype=float, copy=True)
        bot = np.array(bot, dtype=float, copy=True)
        top[invalid] = nodata
        bot[invalid] = nodata

        assert_bottom_below_top(top=top, bot=bot, nodata=nodata)

        # 2) Layer bottoms and idomain from config.
        bases = {}
        for name, surface in (base_surfaces or {}).items():
            values = np.asarray(surface.as_array(), dtype=float)
            if values.shape != top.shape:
                raise ValueError(
                    f"The layer base {name!r} has shape {values.shape}, the top {top.shape}."
                )
            bases[name] = values
        stack = layer_stack(
            top=top, bottom=bot, invalid=invalid, vertical_config=cfg, bases=bases, nodata=nodata
        )

        # The planar grid is the mesh's, the steps of the support are only checked.
        width = float(support.xmax) - float(support.xmin)
        height = float(support.ymax) - float(support.ymin)
        dx = float(support.dx) if support.dx is not None else width / int(support.ncols)
        dy = float(support.dy) if support.dy is not None else height / int(support.nrows)
        if dx <= 0 or dy <= 0:
            raise ValueError(f"Invalid support cell sizes: dx={dx}, dy={dy}.")

        return StructuredGridSpec(
            top=top,
            botm=stack.botm,
            nlay=int(stack.botm.shape[0]),
            idomain=stack.idomain,
        )


def _build_structured_solver_mesh(
    *,
    cell_mesh: PlanarCellMesh,
    top_surface: Surface,
    bottom_surface: Surface,
    vertical_config: VerticalGridConfig | None,
    nodata: float,
    top_sampling: TopSamplingConfig | None,
    channel_mask: np.ndarray | None,
    base_surfaces: dict[str, Surface] | None = None,
) -> tuple[SolverMesh, Surface, Surface]:
    """Extrude a regular mesh on the surfaces, resampled to its shape when they differ.

    The planar grid is the mesh's. The surfaces give only the vertical part: top,
    layer bottoms, layer bases and the ``idomain``. Returns the solver mesh and the
    top and bottom surfaces at the resolution of the mesh.
    """
    base_surfaces = dict(base_surfaces or {})
    nrow, ncol = cell_mesh.structured_shape
    if cell_mesh.mesh.structured_shape != cell_mesh.structured_shape:
        raise MeshError("A regular cell mesh must carry its shape on its HydroMesh too.")

    native_top = top_surface
    if np.asarray(top_surface.as_array()).shape != (nrow, ncol):
        top_surface = top_surface.resample_to_shape(
            nrow,
            ncol,
            resampling="bilinear",
            nodata=float(nodata),
            name=top_surface.name,
        )
        bottom_surface = bottom_surface.resample_to_shape(
            nrow,
            ncol,
            resampling="bilinear",
            nodata=float(nodata),
            name=bottom_surface.name,
        )
        top_surface.assert_same_geographic_domain(bottom_surface)
        base_surfaces = {
            name: surface.resample_to_shape(
                nrow, ncol, resampling="bilinear", nodata=float(nodata), name=surface.name
            )
            for name, surface in base_surfaces.items()
        }
    if top_surface.support is None:
        raise ValueError("Top surface must carry a RasterSupport.")
    _assert_grid_matches_cell_mesh(top_surface.support, cell_mesh)

    if (
        top_sampling is not None
        and top_sampling.mode == "zonal"
        and top_surface is not native_top
        and cells_cover_pixels(native_top, top_surface)
    ):
        # Only the top is zonal; the bottom keeps the planar resampling rule.
        top_surface = zonal_structured_top(
            native_top=native_top,
            grid_top=top_surface,
            grid_bottom=bottom_surface,
            nodata=nodata,
            top_sampling=top_sampling,
            channel_mask=channel_mask,
        )

    # The builder gives the vertical part only, the planar grid is the mesh's.
    spec = StructuredGridBuilder().build_from_surfaces(
        top_surface=top_surface,
        bottom_surface=bottom_surface,
        vertical_config=vertical_config,
        base_surfaces=base_surfaces,
    )
    solver_mesh = SolverMesh(
        cell_mesh=cell_mesh,
        top=spec.top.reshape(-1),
        botm=spec.botm.reshape(spec.nlay, -1),
        idomain=spec.idomain.reshape(spec.nlay, -1),
    )
    return solver_mesh, top_surface, bottom_surface


def build_spatial_discretization(
    *,
    domain: DomainLike,
    vertical_config: VerticalGridConfig | None,
    sgrid_config: SolverSGridConfig | None,
    cell_mesh: PlanarCellMesh,
    channel_mask: np.ndarray | None = None,
) -> SolverGridContext:
    """Extrude a planar cell mesh on the domain surfaces into the solver grid.

    The planar part is ``cell_mesh``: a regular grid (``structured_shape`` set) or
    any unstructured one. The vertical part comes from ``domain.surface_topo``,
    ``domain.substratum`` and ``vertical_config``, the ``[domain.layers]`` table that
    every solver reads; a layering by surfaces also reads ``domain.layer_bases``,
    and its pinched cells get ``idomain`` -1. A regular mesh whose shape differs from the surfaces gets
    them resampled to it, and its bounds and steps must equal those of the surfaces
    to 1e-9 relative.

    ``channel_mask`` (aligned to ``domain.surface_topo``) flags DEM channel pixels
    for zonal top sampling when ``sgrid_config.top_sampling.mode == 'zonal'``. It
    serves an unstructured mesh and a regular grid coarser than the DEM; a grid
    whose cells are the DEM pixels already holds the pixel values.

    The interfaces are checked once built: an active cell with a top at or
    below its bottom raises. The solver warns about active cells in more than one
    connected group once its grid is final (``active_connectivity``).
    """
    top_sampling: TopSamplingConfig | None = None
    if sgrid_config is not None:
        top_sampling = sgrid_config.top_sampling

    nodata = float(vertical_config.nodata if vertical_config is not None else -9999.0)

    top_surface, bottom_surface = resolve_domain_surfaces(domain=domain)
    base_surfaces = resolve_layer_bases(domain=domain, vertical_config=vertical_config)

    if cell_mesh.structured_shape is not None:
        solver_mesh, top_surface, bottom_surface = _build_structured_solver_mesh(
            cell_mesh=cell_mesh,
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            vertical_config=vertical_config,
            nodata=nodata,
            top_sampling=top_sampling,
            channel_mask=channel_mask,
            base_surfaces=base_surfaces,
        )
    else:
        solver_mesh = _build_extruded_solver_mesh_from_runtime_planar(
            cell_mesh=cell_mesh,
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            vertical_config=vertical_config,
            nodata=nodata,
            top_sampling=top_sampling,
            channel_mask=channel_mask,
            base_surfaces=base_surfaces,
        )
    solver_mesh.check_interfaces()

    return SolverGridContext(
        grid=grid_reference_from_solver_mesh(
            solver_mesh,
            crs=None if top_surface.support is None else getattr(top_surface.support, "crs", None),
            nodata=nodata,
        ),
        solver_mesh=solver_mesh,
        top_surface=top_surface,
        bottom_surface=bottom_surface,
    )


def grid_reference_from_solver_mesh(
    solver_mesh: SolverMesh,
    *,
    crs: str | None = None,
    nodata: float = -9999.0,
) -> GridReference:
    """Build a GridReference from a SolverMesh."""
    mesh_bounds = solver_mesh.planar_mesh.bounds()
    xmin, ymin = float(mesh_bounds[0]), float(mesh_bounds[1])
    xmax, ymax = float(mesh_bounds[2]), float(mesh_bounds[3])
    return GridReference(
        n_cells=solver_mesh.n_cells,
        bounds=(xmin, ymin, xmax, ymax),
        crs=crs,
        nodata=float(nodata),
        structured_shape=solver_mesh.structured_shape,
        cell_size_hint=float(solver_mesh.characteristic_length),
    )


@dataclass(slots=True)
class SolverGridContext:
    """Runtime bundle for one solver grid (structured or unstructured)."""

    grid: GridReference
    solver_mesh: SolverMesh
    top_surface: Surface
    bottom_surface: Surface
    template_raster_path: str | None = None

    @property
    def top_elevation(self) -> np.ndarray:
        """Top elevation as flat (n_cells,) array."""
        return np.asarray(self.solver_mesh.top, dtype=float)

    @property
    def bottom_layer(self) -> np.ndarray:
        """Bottom elevation of deepest layer as flat (n_cells,) array."""
        return np.asarray(self.solver_mesh.botm[-1], dtype=float)

    @property
    def nlay(self) -> int:
        return self.solver_mesh.nlay

    @property
    def n_cells(self) -> int:
        return self.solver_mesh.n_cells

    @property
    def is_structured(self) -> bool:
        return self.solver_mesh.is_structured

    @property
    def nrow(self) -> int:
        return self.solver_mesh.nrow

    @property
    def ncol(self) -> int:
        return self.solver_mesh.ncol
