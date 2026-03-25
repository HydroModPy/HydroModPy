"""Generate core hydrologic rasters from a source DEM.

Purpose
-------
Produce the minimum raster stack required by outlet-based delineation:
1. hydrologically corrected DEM,
2. D8 flow-direction raster,
3. D8 flow-accumulation raster.

Pipeline position
-----------------
This is one of the first compute-heavy steps in geographic preprocessing.
All downstream catchment and river-network products depend on these rasters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.backends import WhiteboxBackend, WhiteboxWorkflowsBackend, get_whitebox_backend

from hydromodpy.spatial.geographic.geographic_io import ensure_crs


@dataclass(frozen=True)
class FlowProducts:
    """Paths to rasters produced from the source DEM.

    Attributes
    ----------
    correc:
        Hydrologically corrected DEM.
    direc:
        D8 direction raster (encoded neighbor direction per cell).
    acc:
        D8 accumulation raster (upstream contributing cells, log-scaled here).
    """

    correc: str
    direc: str
    acc: str
    correc_data: object | None = None
    direc_data: object | None = None
    acc_data: object | None = None


def build_regional_flow_products(
    *,
    dem_init_path: str | Path,
    dem_out_dir_path: str | Path,
    dem_correc_type: str,
    crs_project: str | None = None,
    backend: WhiteboxBackend | None = None,
) -> FlowProducts:
    """Generate corrected DEM, D8 direction and D8 accumulation rasters.

    Parameters
    ----------
    dem_init_path:
        Input regional DEM.
    dem_out_dir_path:
        Output directory for generated rasters.
    dem_correc_type:
        Hydrologic correction strategy:
        - ``"fill"``: fills closed depressions so water can exit each cell,
        - ``"breach"``: carves narrow paths through barriers/depressions.
    crs_project:
        Optional CRS to enforce on output metadata.
    backend:
        Optional Whitebox backend injected for runtime/tests.
    """
    tool = get_whitebox_backend() if backend is None else backend

    dem_in = str(dem_init_path)
    out_dir = Path(dem_out_dir_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    if dem_correc_type == "fill":
        correc = str(out_dir / "dem_fill.tif")
    elif dem_correc_type == "breach":
        correc = str(out_dir / "dem_breach.tif")
    else:
        raise ValueError(f"Unknown dem_correc_type={dem_correc_type!r}. Expected 'fill' or 'breach'.")

    direc = str(out_dir / "dem_direc.tif")
    acc = str(out_dir / "dem_acc.tif")

    correc_data = None
    direc_data = None
    acc_data = None
    if isinstance(tool, WhiteboxWorkflowsBackend):
        dem_data = tool.read_raster(dem_in)
        if dem_correc_type == "fill":
            # "fill": raise depression cells until drainage continuity is ensured.
            correc_data = tool.fill_depressions_raster(dem_data)
        else:
            # "breach": cut short channels through barriers to restore connectivity.
            correc_data = tool.breach_depressions_raster(dem_data)
        # D8 direction: each cell points to one of its 8 neighbors (steepest descent).
        direc_data = tool.d8_pointer_raster(correc_data, esri_pntr=False)
        # D8 accumulation: upstream contributing area proxy used for outlet snapping.
        # `log=True` keeps values in a compact range and matches legacy behavior.
        acc_data = tool.d8_flow_accumulation_raster(correc_data, log=True)
        tool.write_raster(correc_data, correc)
        tool.write_raster(direc_data, direc)
        tool.write_raster(acc_data, acc)
    else:
        if dem_correc_type == "fill":
            # "fill": raise depression cells until drainage continuity is ensured.
            tool.fill_depressions(dem_in, correc)
        else:
            # "breach": cut short channels through barriers to restore connectivity.
            tool.breach_depressions(dem_in, correc)
        tool.d8_pointer(correc, direc, esri_pntr=False)
        tool.d8_flow_accumulation(correc, acc, log=True)

    # Normalize CRS metadata to keep downstream GIS/raster steps predictable.
    ensure_crs(correc, crs_project)
    ensure_crs(direc, crs_project)
    ensure_crs(acc, crs_project)

    return FlowProducts(
        correc=correc,
        direc=direc,
        acc=acc,
        correc_data=correc_data,
        direc_data=direc_data,
        acc_data=acc_data,
    )
