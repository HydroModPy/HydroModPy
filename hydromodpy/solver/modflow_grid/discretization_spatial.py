"""Common spatial discretization builders for MODFLOW-family solvers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.exceptions import MeshError
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.base.protocols import DomainLike
from hydromodpy.solver.modflow_grid.grid_context import (
    SolverGridContext,
    grid_reference_from_solver_mesh,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.domain.layering import (
    assert_bottom_below_top,
    coerce_vertical_config,
    layer_stack,
)
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig
from hydromodpy.spatial.mesh.ops.zonal_stats import regular_grid_cell_ids, zonal_top
from hydromodpy.spatial.mesh.structured_grid.sgrid_config import (
    SolverSGridConfig,
    TopSamplingConfig,
)
from hydromodpy.spatial.mesh.structured_grid.sgrid_generation import StructuredGridBuilder
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from hydromodpy.spatial.surface_sampling import PreparedSurfaceSampler

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

logger = get_logger(__name__)


def resolve_domain_surfaces(
    *,
    domain: DomainLike,
) -> tuple[Surface, Surface]:
    """Validate and return top/substratum surfaces used by spatial gridding."""
    if domain is None:
        raise ValueError("Modflow spatial geometry is domain-only: a Domain object is required.")

    surface_topo = getattr(domain, "surface_topo", None)
    substratum = getattr(domain, "substratum", None)
    if surface_topo is None or substratum is None:
        raise ValueError(
            "Modflow spatial geometry is domain-only: domain.surface_topo "
            "and domain.substratum are required."
        )
    if not isinstance(surface_topo, Surface) or not isinstance(substratum, Surface):
        raise TypeError("Domain surfaces must be Surface instances.")

    top = np.asarray(surface_topo.as_array(), dtype=float)
    bot = np.asarray(substratum.as_array(), dtype=float)
    if top.shape != bot.shape:
        raise ValueError(f"Domain surface mismatch: top{top.shape} != substratum{bot.shape}.")

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
    edge ends up kilometres deep with a perfectly clean top and an active idomain.
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


def _zonal_top_flat(
    *,
    hydro_mesh: object | None = None,
    grid_support: object | None = None,
    active: np.ndarray | None = None,
    top_surface: Surface,
    centroid_top: np.ndarray,
    bottom_flat: np.ndarray,
    nodata: float,
    top_sampling: TopSamplingConfig,
    channel_mask: np.ndarray | None,
    label: str = "Zonal top sampling",
    clamp_to_bottom: bool = True,
) -> np.ndarray:
    """Zonal per-cell top from the DEM; falls back to the centroid sample.

    Reduces every DEM pixel inside each cell (thalweg stat on channel pixels,
    area stat on hillslope pixels) instead of one bilinear sample at the cell
    generator. Requires a fully georeferenced ``top_surface``; without it the
    centroid projection is returned unchanged. The cells are the ``hydro_mesh``
    polygons, or the boxes of the regular grid described by ``grid_support``.
    ``label`` opens the log line. With ``clamp_to_bottom`` a top lowered to within
    ``min_thickness_m`` of ``bottom_flat`` is raised back to that distance; without
    it the caller moves the bottom (see :func:`_bottom_under_lowered_top`).
    """
    from rasterio.transform import from_bounds

    support = getattr(top_surface, "support", None)
    fields = ("xmin", "xmax", "ymin", "ymax", "nrows", "ncols")
    if support is None or any(getattr(support, name, None) is None for name in fields):
        logger.warning("Zonal top sampling needs a georeferenced surface; using centroid sample.")
        return centroid_top

    dem = np.asarray(top_surface.as_array(), dtype=float)
    out_shape = (int(support.nrows), int(support.ncols))
    if dem.shape != out_shape:
        logger.warning(
            "Surface array %s does not match its support %s; using centroid sample.",
            dem.shape,
            out_shape,
        )
        return centroid_top
    transform = from_bounds(
        float(support.xmin),
        float(support.ymin),
        float(support.xmax),
        float(support.ymax),
        int(support.ncols),
        int(support.nrows),
    )
    labels = None
    if grid_support is not None:
        labels = regular_grid_cell_ids(
            dem_transform=transform,
            dem_shape=out_shape,
            grid_bounds=(
                float(grid_support.xmin),
                float(grid_support.xmax),
                float(grid_support.ymin),
                float(grid_support.ymax),
            ),
            grid_shape=(int(grid_support.nrows), int(grid_support.ncols)),
        )
    result = zonal_top(
        planar_mesh=hydro_mesh,
        labels=labels,
        active=active,
        dem=dem,
        transform=transform,
        out_shape=out_shape,
        centroid_top=centroid_top,
        nodata=float(nodata),
        channel_mask=channel_mask,
        hillslope_stat=top_sampling.hillslope_stat,
        channel_stat=top_sampling.channel_stat,
        min_pixels=int(top_sampling.min_pixels),
        spike_guard_tol_m=float(top_sampling.spike_guard_tol_m),
        bottom=bottom_flat if clamp_to_bottom else None,
        min_thickness_m=float(top_sampling.min_thickness_m),
    )
    logger.info(
        "%s: %d/%d cells zonal (%d channel), %d lowered "
        "(max -%.2f m, mean -%.2f m), %d spike-reverted, %d thickness-clamped.",
        label,
        int(result.info["n_zonal"]),
        int(result.info["n_cells"]),
        int(result.info["n_channel_cells"]),
        int(result.info["n_lowered"]),
        result.info["max_lowered_m"],
        result.info["mean_lowered_m"],
        int(result.info["n_spike_reverted"]),
        int(result.info["n_thickness_clamped"]),
    )
    return result.top


_MIN_COLUMN_SHARE = 0.1
"""A lowered top keeps at least this share of the column its centre sample gave.

The Flume meshes MODFLOW 6 solves under Newton keep 11.6 % of the centre column at the
least (3.5 m of 30 m); columns of 0.2 to 1.6 m beside 30 m neighbours do not converge.
"""


def _bottom_under_lowered_top(
    *,
    top: np.ndarray,
    centroid_top: np.ndarray,
    bottom: np.ndarray,
    min_thickness_m: float,
    nodata: float,
) -> np.ndarray:
    """Bottom that follows a top lowered far under the centre sample.

    The bottom is sampled at the cell centre, the zonal top reduces every pixel
    of the cell. A coarse cell on a pit or a steep valley side can hold a pixel
    tens of metres under its centre sample. Leaving the bottom there keeps a column
    of a few decimetres, whose transmissivity is nil next to the neighbours and
    which MODFLOW 6 cannot solve under Newton. When the lowered top leaves less than
    ``min_thickness_m``, or less than :data:`_MIN_COLUMN_SHARE` of the centre-sample
    column, the bottom moves down with the top and the column keeps the thickness
    of the centre sample. A cell whose top was not lowered, or whose column stays
    thick enough, is untouched, byte for byte.
    """
    valid = (
        np.isfinite(top)
        & np.isfinite(bottom)
        & np.isfinite(centroid_top)
        & (top > float(nodata))
        & (bottom > float(nodata))
        & (centroid_top > float(nodata))
    )
    column = np.maximum(centroid_top - bottom, float(min_thickness_m))
    floor = np.maximum(float(min_thickness_m), _MIN_COLUMN_SHARE * column)
    follows = valid & (top < centroid_top) & (top - bottom < floor)
    if not follows.any():
        return bottom
    lowered = np.where(follows, top - column, bottom)
    logger.info(
        "Zonal top: %d cells would keep less than %.0f %% of their column under their lowered "
        "top; their bottom follows the top (down by up to %.2f m, the centre-sample thickness "
        "kept).",
        int(follows.sum()),
        100.0 * _MIN_COLUMN_SHARE,
        float((bottom - lowered)[follows].max()),
    )
    return lowered


def _crossing_cells(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """Boolean mask of the cells a river chain crosses off their centre.

    A crossing cell is a cell of a ``rivers`` chain with a lateral offset above
    zero: the river runs through it, but its centre lies beside the line. That is
    the pair of cells a contact line crosses a river with, a cell that two thalwegs
    closer than half a cell share, and the end cell of a river that starts near the
    domain boundary. A chain that publishes no offset holds the line in every cell.
    """
    crossing = np.zeros(cell_mesh.n_cells, dtype=bool)
    for chain in cell_mesh.chains("rivers"):
        if chain.offset_m is not None:
            crossing[chain.cell_ids[chain.offset_m > 0.0]] = True
    return crossing


def _lower_crossing_cells(
    *,
    cell_mesh: PlanarCellMesh,
    top_surface: Surface,
    centroid_top: np.ndarray,
    bottom_flat: np.ndarray,
    nodata: float,
    top_sampling: TopSamplingConfig | None,
) -> np.ndarray:
    """Top of the centroid mode with the crossing cells at their zonal minimum.

    The sample at the centre of a crossing cell lands beside the river, on a bank.
    Those cells, and only those, take the lowest DEM pixel they hold, the channel
    statistic ``min``, so the river cell keeps its incised low. The other cells keep
    the centroid sample, byte for byte. The caller moves the bottom of a cell whose
    lowered top comes within the minimum thickness of it.
    """
    crossing = _crossing_cells(cell_mesh)
    valid = (
        np.isfinite(centroid_top)
        & np.isfinite(bottom_flat)
        & (centroid_top > float(nodata))
        & (bottom_flat > float(nodata))
    )
    crossing &= valid
    if not crossing.any():
        return centroid_top
    sampling = (top_sampling or TopSamplingConfig()).model_copy(update={"channel_stat": "min"})
    # Every pixel of a crossing cell counts as channel: the river runs through it.
    every_pixel = np.ones(np.asarray(top_surface.as_array()).shape, dtype=bool)
    return _zonal_top_flat(
        hydro_mesh=cell_mesh.mesh,
        active=crossing,
        top_surface=top_surface,
        centroid_top=centroid_top,
        bottom_flat=bottom_flat,
        nodata=nodata,
        top_sampling=sampling,
        channel_mask=every_pixel,
        label="Crossing-cell top sampling",
        clamp_to_bottom=False,
    )


def _cell_area(support: RasterSupport) -> float:
    """Mean cell area of a raster support from its bounds and shape, NaN when unknown."""
    fields = (support.xmin, support.xmax, support.ymin, support.ymax, support.nrows, support.ncols)
    if any(value is None for value in fields):
        return float("nan")
    width = (float(support.xmax) - float(support.xmin)) / int(support.ncols)
    height = (float(support.ymax) - float(support.ymin)) / int(support.nrows)
    return abs(width * height)


def _cells_cover_pixels(native_top: Surface, grid_top: Surface, *, min_pixels: float = 2.0) -> bool:
    """True when a grid cell spans at least ``min_pixels`` DEM pixels, else log why not.

    Below that, a pixel centre falls in one cell out of several and the block
    statistic is a checkerboard of raw pixels, so the resample stays.
    """
    pixel_area = _cell_area(native_top.support)
    cell_area = _cell_area(grid_top.support)
    if not (np.isfinite(pixel_area) and np.isfinite(cell_area)):
        return True  # no georeferencing: the zonal step warns and keeps the resample
    if pixel_area > 0.0 and cell_area >= min_pixels * pixel_area * (1.0 - 1e-9):
        return True
    logger.info(
        "Zonal top sampling skipped: a grid cell (%.0f m2) covers fewer than %.0f DEM pixels "
        "(%.0f m2 each), so the resampled top is kept.",
        cell_area,
        min_pixels,
        pixel_area,
    )
    return False


def _zonal_structured_top(
    *,
    native_top: Surface,
    grid_top: Surface,
    grid_bottom: Surface,
    nodata: float,
    top_sampling: TopSamplingConfig,
    channel_mask: np.ndarray | None,
) -> Surface:
    """Top of a structured grid coarser than its DEM, from the zonal statistics.

    ``native_top`` is the DEM the cells are reduced from, ``grid_top`` its
    resample to the solver grid (fallback and spike reference). Only the values
    of active cells change: a cell the resample left without data stays inactive,
    so the idomain does not move.
    """
    centroid = np.asarray(grid_top.as_array(), dtype=float).reshape(-1)
    dead = ~np.isfinite(centroid) | (centroid <= float(nodata))
    zonal = _zonal_top_flat(
        grid_support=grid_top.support,
        active=~dead,
        top_surface=native_top,
        centroid_top=centroid,
        bottom_flat=np.asarray(grid_bottom.as_array(), dtype=float).reshape(-1),
        nodata=nodata,
        top_sampling=top_sampling,
        channel_mask=channel_mask,
    )
    values = np.where(dead, centroid, zonal).reshape(grid_top.as_array().shape)
    return Surface(name=grid_top.name, values=values, support=grid_top.support)


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
    """Extrude an unstructured cell mesh: top, bottom and layer bases sampled at the cell centres."""
    hydro_mesh = cell_mesh.mesh
    x_centers, y_centers = cell_mesh.centers.T

    # Sample top/botm at the cell centres (Voronoi generators or triangle centroids)
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
        top_flat = _zonal_top_flat(
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
        top_flat = _lower_crossing_cells(
            cell_mesh=cell_mesh,
            top_surface=top_surface,
            centroid_top=centroid_top,
            bottom_flat=bottom_flat,
            nodata=nodata,
            top_sampling=top_sampling,
        )
    bottom_flat = _bottom_under_lowered_top(
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
        and _cells_cover_pixels(native_top, top_surface)
    ):
        # Only the top is zonal; the bottom keeps the planar resampling rule.
        top_surface = _zonal_structured_top(
            native_top=native_top,
            grid_top=top_surface,
            grid_bottom=bottom_surface,
            nodata=nodata,
            top_sampling=top_sampling,
            channel_mask=channel_mask,
        )

    # The builder keeps the vertical part only: its own planar vertices are ignored.
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


__all__ = [
    "build_spatial_discretization",
    "resolve_domain_surfaces",
    "resolve_layer_bases",
]
