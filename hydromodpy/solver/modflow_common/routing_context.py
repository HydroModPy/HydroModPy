"""Solver-aligned hydrologic routing products built from a solver DEM."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydromodpy.spatial.delineation import WhiteboxWorkflowsBackend
from hydromodpy.spatial.geographic.core.flow_products import build_regional_flow_products


@dataclass(frozen=True, slots=True)
class SolverRoutingContext:
    """Hydrologic routing rasters aligned with one solver grid."""

    dem_path: str
    correc_path: str
    direc_path: str
    acc_path: str


def build_solver_routing_context(
    *,
    dem_path: str | Path,
    output_dir: str | Path,
    dem_correc_type: str,
    crs_project: str | None = None,
    backend: WhiteboxWorkflowsBackend | None = None,
) -> SolverRoutingContext:
    """Build flow-correction and D8 routing rasters from one solver DEM."""
    dem_in = Path(dem_path)
    if not dem_in.exists():
        raise FileNotFoundError(f"Solver DEM raster not found: {dem_in}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    products = build_regional_flow_products(
        dem_init_path=dem_in,
        dem_out_dir_path=out_dir,
        dem_correc_type=str(dem_correc_type),
        crs_project=crs_project,
        backend=backend,
    )
    return SolverRoutingContext(
        dem_path=str(dem_in),
        correc_path=str(products.correc),
        direc_path=str(products.direc),
        acc_path=str(products.acc),
    )
