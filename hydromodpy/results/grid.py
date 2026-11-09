"""Scalar metadata of the DEM raster a simulation was built from: pixel size, shape, extent.

Exposed as :attr:`hydromodpy.results.run.Run.grid`. It describes the DEM
raster, never the cells of the model: a mesh is not obliged to follow the
pixels. The cells of a run, their centers and their areas are read from
:attr:`hydromodpy.results.run.Run.mesh`. A global model on the one-cell mesh
gets the same answer, for the one pixel its DEM stores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hydromodpy.results.run.geographic import crs_proj_from_metadata

if TYPE_CHECKING:
    from hydromodpy.results.run import Run


__all__ = ["Grid", "build_grid"]


@dataclass(frozen=True, slots=True)
class Grid:
    """Scalar metadata of the DEM raster of a simulation.

    Attributes
    ----------
    cell_size : float
        DEM pixel size in meters.
    shape : tuple[int, int]
        DEM raster shape as ``(nrow, ncol)``.
    extent : tuple[float, float, float, float]
        CRS-aligned spatial extent as ``(xmin, xmax, ymin, ymax)`` -
        the 4-tuple expected by ``matplotlib.imshow(extent=...)``.
    crs : str | None
        Proj string describing the CRS, or ``None`` if unknown.
    catchment_area_m2 : float
        Catchment area from the watershed delineation polygon (m²),
        i.e. ``catch_area`` stored in the catalog converted to m².
        For the area of the catchment as the run saw it, sum
        ``run.mesh.cell_areas()`` over ``run.catchment_mask``, which is one
        value per face. For the polygon area on the mesh, weigh the same
        areas by ``views.catchment_weights(run)``, the share of each face
        inside the polygon. ``int(run.catchment_mask.sum()) * grid.cell_size ** 2``
        holds only for a run sealed before the basin of D was stored and whose
        cells are the DEM pixels, where the mask is the DEM raster mask.
    """

    cell_size: float
    shape: tuple[int, int]
    extent: tuple[float, float, float, float]
    crs: str | None
    catchment_area_m2: float


def build_grid(run: Run) -> Grid:
    """Read scalar grid metadata for ``run`` from the catalog + DEM transform.

    A global model on the one-cell mesh answers like any run, from the one
    pixel its DEM stores.

    Raises
    ------
    RuntimeError
        If the required entries (``dem_res``, ``nrow``, ``ncol``) are missing
        from ``geographic_metadata``.
    """
    meta = run._catalog.read_geographic_metadata(run._sim_id)
    missing = [k for k in ("dem_res", "nrow", "ncol") if k not in meta]
    if missing:
        raise RuntimeError(
            f"Grid metadata incomplete for simulation '{run._sim_id}' "
            f"(missing {missing} in geographic_metadata). The simulation "
            "may pre-date grid ingestion - re-run to populate."
        )

    cell_size = float(meta["dem_res"])
    shape = (int(meta["nrow"]), int(meta["ncol"]))
    crs = crs_proj_from_metadata(meta)
    catchment_area_m2 = float(meta["catch_area"]) * 1e6 if "catch_area" in meta else 0.0

    raster = run.geographic_raster("watershed_dem")
    t = raster.transform
    nrow, ncol = shape
    xmin, ymax = float(t[2]), float(t[5])
    extent = (
        xmin,
        xmin + ncol * float(t[0]),
        ymax + nrow * float(t[4]),
        ymax,
    )

    return Grid(
        cell_size=cell_size,
        shape=shape,
        extent=extent,
        crs=crs,
        catchment_area_m2=catchment_area_m2,
    )
