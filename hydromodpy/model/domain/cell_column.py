"""The top and the bottom of each cell, read from the DEM and the substratum before the solve.

A ``CellColumn`` holds one top and one bottom per cell of the planar mesh, in m a.s.l.
``prepare_solver`` builds it once and the solver reads it, so no backend samples the
DEM itself. Two rules give it. ``modflow_column`` is the one of the MODFLOW family. On
an unstructured mesh it samples the DEM at the cell centres, lowers a cell a river
chain crosses off its centre to its zonal minimum, and moves the bottom down with a top
lowered far under the centre sample. On a regular grid it resamples the surfaces to the
grid, and in the zonal mode it reduces the DEM pixels each cell covers. A cell with no
valid top or bottom gets ``nodata`` for both. ``centre_column`` is the one of
Boussinesq. It samples at the centres, takes the mean of the finite corners where the
centre falls on no data, and leaves the cells that have none as NaN.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from hydromodpy.catchment.raster_support import RasterSupport
from hydromodpy.catchment.surface import Surface
from hydromodpy.catchment.surface_sampling import PreparedSurfaceSampler
from hydromodpy.core.exceptions import MeshError
from hydromodpy.core.logging import get_logger
from hydromodpy.mesh.cells.zonal_stats import regular_grid_cell_ids, zonal_top
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.model.domain.domain import Domain
from hydromodpy.model.domain.geometry import RasterGeometry
from hydromodpy.model.domain.top_sampling_config import TopSamplingConfig

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CellColumn:
    """The top and the bottom of every cell, flat in the order of the cells, in m a.s.l.

    ``modflow_column`` gives ``nodata`` to both where a cell has no valid column.
    ``centre_column`` leaves NaN there.
    """

    top: np.ndarray
    bottom: np.ndarray


def modflow_column(
    *,
    cell_mesh: PlanarCellMesh,
    domain: Domain,
    top_sampling: TopSamplingConfig | None,
    channel_mask: np.ndarray | None,
) -> CellColumn:
    """The column of the MODFLOW family, from ``domain.surface_topo`` and ``domain.substratum``.

    ``channel_mask`` (aligned to ``domain.surface_topo``, see :func:`zonal_channel_mask`)
    flags the DEM channel pixels of the zonal mode. It serves an unstructured mesh and a
    regular grid coarser than the DEM. A regular grid whose shape differs from the
    surfaces gets them resampled to it, and its bounds and steps must equal those of the
    surfaces to 1e-9 relative.
    """
    nodata = float(domain.config.layers.nodata)
    top_surface, bottom_surface = resolve_domain_surfaces(domain=domain)
    if cell_mesh.structured_shape is not None:
        top, bottom = _structured_column(
            cell_mesh=cell_mesh,
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            nodata=nodata,
            top_sampling=top_sampling,
            channel_mask=channel_mask,
        )
    else:
        top, bottom = _extruded_column(
            cell_mesh=cell_mesh,
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            nodata=nodata,
            top_sampling=top_sampling,
            channel_mask=channel_mask,
        )
    invalid = (
        ~np.isfinite(top)
        | ~np.isfinite(bottom)
        | (top <= float(nodata))
        | (bottom <= float(nodata))
    )
    return CellColumn(
        top=np.where(invalid, float(nodata), top), bottom=np.where(invalid, float(nodata), bottom)
    )


def centre_column(
    *,
    cell_mesh: PlanarCellMesh,
    domain: Domain,
    top_sampling: TopSamplingConfig | None = None,
    channel_mask: np.ndarray | None = None,
) -> CellColumn:
    """The column of Boussinesq: both surfaces sampled at the cell centres.

    A cell whose centre falls on no data takes the mean of its finite corners, and stays
    NaN when none is finite. ``top_sampling`` and ``channel_mask`` are not read, they
    let both rules answer one call.
    """
    if domain is None:
        raise ValueError("Boussinesq runtime mesh construction requires a domain")
    top_surface = getattr(domain, "surface_topo", None)
    bottom_surface = getattr(domain, "substratum", None)
    if top_surface is None:
        raise ValueError("domain.surface_topo is required for runtime mesh construction")
    if bottom_surface is None:
        raise ValueError("domain.substratum is required for runtime mesh construction")
    return CellColumn(
        top=_sampled_at_centres(PreparedSurfaceSampler.from_surface(top_surface), cell_mesh),
        bottom=_sampled_at_centres(PreparedSurfaceSampler.from_surface(bottom_surface), cell_mesh),
    )


def _sampled_at_centres(sampler: PreparedSurfaceSampler, cell_mesh: PlanarCellMesh) -> np.ndarray:
    """One surface value per cell: at its center, else the mean of its finite corners."""
    centers = cell_mesh.centers
    values = np.asarray(sampler.sample(centers[:, 0], centers[:, 1]), dtype=float).reshape(-1)
    missing = np.flatnonzero(~np.isfinite(values))
    if missing.size == 0:
        return values
    vertices = cell_mesh.mesh.vertices
    triangles = np.asarray(cell_mesh.mesh.flat_connectivity, dtype=int)
    corners = triangles[missing]
    at_corners = sampler.sample(vertices[corners, 0], vertices[corners, 1]).reshape(corners.shape)
    for row, cell in enumerate(missing.tolist()):
        finite = at_corners[row][np.isfinite(at_corners[row])]
        values[cell] = float(np.nanmean(finite)) if finite.size else np.nan
    return values


def _extruded_column(
    *,
    cell_mesh: PlanarCellMesh,
    top_surface: Surface,
    bottom_surface: Surface,
    nodata: float,
    top_sampling: TopSamplingConfig | None,
    channel_mask: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Top and bottom of an unstructured mesh, sampled at the cell centers."""
    hydro_mesh = cell_mesh.mesh
    x_centers, y_centers = cell_mesh.centers.T

    # Sample top/botm at the cell centers (Voronoi generators or triangle centroids)
    # from the domain surfaces.
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
    return top_flat, bottom_flat


def resample_to_mesh_shape(surface: Surface, cell_mesh: PlanarCellMesh, nodata: float) -> Surface:
    """``surface`` resampled (bilinear) to the shape of the regular mesh, as it is when it has it."""
    nrow, ncol = cell_mesh.structured_shape
    if np.asarray(surface.as_array()).shape == (nrow, ncol):
        return surface
    return surface.resample_to_shape(
        nrow, ncol, resampling="bilinear", nodata=float(nodata), name=surface.name
    )


def _structured_column(
    *,
    cell_mesh: PlanarCellMesh,
    top_surface: Surface,
    bottom_surface: Surface,
    nodata: float,
    top_sampling: TopSamplingConfig | None,
    channel_mask: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Top and bottom of a regular mesh, resampled to its shape when the surfaces differ."""
    if cell_mesh.mesh.structured_shape != cell_mesh.structured_shape:
        raise MeshError("A regular cell mesh must carry its shape on its HydroMesh too.")

    native_top = top_surface
    grid_top = resample_to_mesh_shape(top_surface, cell_mesh, nodata)
    grid_bottom = resample_to_mesh_shape(bottom_surface, cell_mesh, nodata)
    if grid_top is not native_top:
        grid_top.assert_same_geographic_domain(grid_bottom)
    if grid_top.support is None:
        raise ValueError("Top surface must carry a RasterSupport.")
    _assert_grid_matches_cell_mesh(grid_top.support, cell_mesh)

    if (
        top_sampling is not None
        and top_sampling.mode == "zonal"
        and grid_top is not native_top
        and cells_cover_pixels(native_top, grid_top)
    ):
        # Only the top is zonal; the bottom keeps the planar resampling rule.
        grid_top = zonal_structured_top(
            native_top=native_top,
            grid_top=grid_top,
            grid_bottom=grid_bottom,
            nodata=nodata,
            top_sampling=top_sampling,
            channel_mask=channel_mask,
        )
    return (
        np.asarray(grid_top.as_array(), dtype=float).reshape(-1),
        np.asarray(grid_bottom.as_array(), dtype=float).reshape(-1),
    )


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


def resolve_domain_surfaces(
    *,
    domain: Domain,
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


def zonal_top_flat(
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
    it the caller moves the bottom (see :func:`bottom_under_lowered_top`).
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
"""A lowered top keeps at least this share of the column its center sample gave.

The Flume meshes MODFLOW 6 solves under Newton keep 11.6 % of the center column at the
least (3.5 m of 30 m); columns of 0.2 to 1.6 m beside 30 m neighbors do not converge.
"""


def bottom_under_lowered_top(
    *,
    top: np.ndarray,
    centroid_top: np.ndarray,
    bottom: np.ndarray,
    min_thickness_m: float,
    nodata: float,
) -> np.ndarray:
    """Bottom that follows a top lowered far under the center sample.

    The bottom is sampled at the cell center, the zonal top reduces every pixel
    of the cell. A coarse cell on a pit or a steep valley side can hold a pixel
    tens of meters under its center sample. Leaving the bottom there keeps a column
    of a few decimeters, whose transmissivity is nil next to the neighbors and
    which MODFLOW 6 cannot solve under Newton. When the lowered top leaves less than
    ``min_thickness_m``, or less than :data:`_MIN_COLUMN_SHARE` of the center-sample
    column, the bottom moves down with the top and the column keeps the thickness
    of the center sample. A cell whose top was not lowered, or whose column stays
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
    """Boolean mask of the cells a river chain crosses off their center.

    A crossing cell is a cell of a ``rivers`` chain with a lateral offset above
    zero: the river runs through it, but its center lies beside the line. That is
    the pair of cells a contact line crosses a river with, a cell that two thalwegs
    closer than half a cell share, and the end cell of a river that starts near the
    domain boundary. A chain that publishes no offset holds the line in every cell.
    """
    crossing = np.zeros(cell_mesh.n_cells, dtype=bool)
    for chain in cell_mesh.chains("rivers"):
        if chain.offset_m is not None:
            crossing[chain.cell_ids[chain.offset_m > 0.0]] = True
    return crossing


def lower_crossing_cells(
    *,
    cell_mesh: PlanarCellMesh,
    top_surface: Surface,
    centroid_top: np.ndarray,
    bottom_flat: np.ndarray,
    nodata: float,
    top_sampling: TopSamplingConfig | None,
) -> np.ndarray:
    """Top of the centroid mode with the crossing cells at their zonal minimum.

    The sample at the center of a crossing cell lands beside the river, on a bank.
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
    return zonal_top_flat(
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


def cells_cover_pixels(native_top: Surface, grid_top: Surface, *, min_pixels: float = 2.0) -> bool:
    """True when a grid cell spans at least ``min_pixels`` DEM pixels, else log why not.

    Below that, a pixel center falls in one cell out of several and the block
    statistic is a checkerboard of raw pixels, so the resample stays.
    """
    pixel_area = native_top.support.cell_area
    cell_area = grid_top.support.cell_area
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


def zonal_structured_top(
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
    zonal = zonal_top_flat(
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


def zonal_channel_mask(
    *, raster: RasterGeometry | None, surface: Surface, top_sampling: TopSamplingConfig | None
) -> np.ndarray | None:
    """Boolean channel-pixel mask aligned to ``surface`` for zonal top sampling.

    Only produced when ``top_sampling.mode == 'zonal'`` and its ``channel_source``
    requests one. Reads the channel tree A over the whole model domain, the
    full-extent raster the model carries in ``raster.channel.link``, and reprojects
    it (nearest) onto the DEM grid of ``surface``. The rasters clipped to the
    watershed miss the buffer the grid keeps active, so they are the fallback only.
    Returns ``None`` (channel class disabled, every pixel treated as hillslope) when
    zonal is off, the source is 'none', or no stream raster / georeferenced surface
    is available.
    """
    if top_sampling is None or top_sampling.mode != "zonal":
        return None
    if top_sampling.channel_source == "none":
        return None

    channel = None if raster is None else raster.channel
    path = None
    if channel is not None and channel.link is not None and os.path.exists(channel.link):
        path = channel.link
        logger.info("Zonal channel mask reads the full-extent channel tree: %s.", path)
    if path is None and channel is not None:
        for candidate in channel.clipped:
            if os.path.exists(candidate):
                path = candidate
                logger.info(
                    "Zonal channel mask reads the stream raster clipped to the watershed "
                    "(no full-extent raster in the corrected-flow folder): %s.",
                    path,
                )
                break
    if path is None:
        logger.warning(
            "Zonal channel_source=%s but no stream raster found; the channel class "
            "is disabled (every DEM pixel treated as hillslope).",
            top_sampling.channel_source,
        )
        return None

    support = getattr(surface, "support", None)
    fields = ("xmin", "xmax", "ymin", "ymax", "nrows", "ncols")
    if support is None or any(getattr(support, name, None) is None for name in fields):
        logger.warning("Zonal channel mask needs a georeferenced surface; channel class disabled.")
        return None

    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject

    out_shape = (int(support.nrows), int(support.ncols))
    dst_transform = from_bounds(
        float(support.xmin),
        float(support.ymin),
        float(support.xmax),
        float(support.ymax),
        int(support.ncols),
        int(support.nrows),
    )
    # The fill value must not be 0: GDAL moves a valid source pixel equal to the
    # destination nodata to the next float (5e-324), so with 0 every background
    # pixel of the stream raster turned "positive" and the channel class covered
    # the whole catchment (measured on the Flume: 146 384 pixels for 4 197).
    dst = np.full(out_shape, -1.0, dtype=np.float64)
    with rasterio.open(path) as src:
        src_nodata = src.nodata
        src_crs = src.crs
        dst_crs = support.crs if support.crs is not None else src_crs
        # WhiteboxTools strips the delineated stream raster CRS to an engineering
        # LOCAL_CS tag, but it is delineated from the same projected DEM domain, so
        # it is already co-registered with the model top. Asking PROJ to transform
        # an engineering CRS to the projected DEM CRS raises, so treat a missing or
        # non-standard tag as the model coordinate space (a pure nearest resample).
        if src_crs is None or not (src_crs.is_projected or src_crs.is_geographic):
            src_crs = dst_crs
        try:
            reproject(
                source=src.read(1).astype(np.float64),
                destination=dst,
                src_transform=src.transform,
                src_crs=src_crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.nearest,
                src_nodata=src_nodata,
                dst_nodata=-1.0,
            )
        except Exception as exc:  # noqa: BLE001 - degrade, never abort the build
            logger.warning(
                "Zonal channel mask reprojection failed (%s); channel class disabled.", exc
            )
            return None
    # Channel pixels carry a positive link id / stream flag; 0 is background. A
    # nearest reproject can still copy the source nodata value into the target
    # (it is not always filled with dst_nodata), so require a strictly positive
    # value and drop a positive nodata sentinel explicitly.
    mask = np.isfinite(dst) & (dst > 0.0)
    if src_nodata is not None and float(src_nodata) > 0.0:
        mask &= dst != float(src_nodata)
    if top_sampling.channel_buffer_px > 0:
        from scipy import ndimage

        mask = ndimage.binary_dilation(mask, iterations=int(top_sampling.channel_buffer_px))
    logger.info(
        "Zonal channel mask: %d/%d channel pixels from %s.", int(mask.sum()), mask.size, path
    )
    return mask
