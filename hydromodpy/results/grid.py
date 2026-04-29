"""Scalar spatial metadata for a simulation: cell size, shape, extent.

Exposed as :attr:`hydromodpy.results.run.Run.grid`. Provides the
scalars typically needed when post-processing or plotting a
distributed simulation without reaching for the raw DEM transform.

Only applies to simulations whose mesh is regular in plan - the
MODFLOW ``dis`` and ``disv`` topologies. For ``disu`` (unstructured)
the builder raises: no uniform ``cell_size`` applies, and the caller
should use :attr:`~hydromodpy.results.run.Run.mesh` vertices instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.results.run import Run


__all__ = ["Grid", "build_grid"]


@dataclass(frozen=True, slots=True)
class Grid:
    """Scalar spatial metadata for a regular-in-plan simulation.

    Attributes
    ----------
    cell_size : float
        DEM pixel size in metres (uniform for ``dis`` / ``disv``).
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
        For a mask-consistent area use
        ``int(run.catchment_mask.sum()) * grid.cell_size ** 2``.
    """

    cell_size: float
    shape: tuple[int, int]
    extent: tuple[float, float, float, float]
    crs: str | None
    catchment_area_m2: float


def build_grid(run: Run) -> Grid:
    """Read scalar grid metadata for ``run`` from the catalog + DEM transform.

    Raises
    ------
    RuntimeError
        If the simulation uses an unstructured (``disu``) mesh, or if
        the required entries (``dem_res``, ``nrow``, ``ncol``) are
        missing from ``geographic_metadata``.
    """
    topology = run._load_row().get("mesh_topology")
    if topology == "disu":
        raise RuntimeError(
            f"Simulation '{run._sim_id}' uses an unstructured mesh "
            "('disu'): no uniform cell_size applies. Use run.mesh "
            "(vertices + face_node_connectivity) together with "
            "run.field(...) for spatial access."
        )

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
    crs = meta.get("crs_proj")
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
