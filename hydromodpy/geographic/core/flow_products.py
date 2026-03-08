"""Build the three hydrologic rasters used to delineate a catchment.

Starting from one regional DEM, this module prepares:
1. a hydrologically corrected DEM (no blocked drainage),
2. a D8 flow-direction raster (where each cell drains),
3. a D8 flow-accumulation raster (how much upstream area contributes).

These products are the minimum inputs needed downstream to:
- snap an outlet on a coherent drainage cell,
- delineate the watershed polygon from that outlet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import whitebox

from hydromodpy.geographic.geographic_io import ensure_crs

wbt = whitebox.WhiteboxTools()
wbt.verbose = False


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


def build_regional_flow_products(
    *,
    dem_init_path: str | Path,
    dem_out_dir_path: str | Path,
    dem_correc_type: str,
    crs_project: str | None = None,
    wbt_tool: object | None = None,
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
    wbt_tool:
        Optional Whitebox-like object injected for tests.
    """
    tool = wbt if wbt_tool is None else wbt_tool

    dem_in = str(dem_init_path)
    out_dir = Path(dem_out_dir_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    if dem_correc_type == "fill":
        correc = str(out_dir / "dem_fill.tif")
        # "fill": raise depression cells until drainage continuity is ensured.
        tool.fill_depressions(dem_in, correc)
    elif dem_correc_type == "breach":
        correc = str(out_dir / "dem_breach.tif")
        # "breach": cut short channels through barriers to restore connectivity.
        tool.breach_depressions(dem_in, correc)
    else:
        raise ValueError(f"Unknown dem_correc_type={dem_correc_type!r}. Expected 'fill' or 'breach'.")

    direc = str(out_dir / "dem_direc.tif")
    # D8 direction: each cell points to one of its 8 neighbors (steepest descent).
    tool.d8_pointer(correc, direc, esri_pntr=False)

    # D8 accumulation: upstream contributing area proxy used for outlet snapping.
    # `log=True` keeps values in a compact range and matches legacy behavior.
    acc = str(out_dir / "dem_acc.tif")
    tool.d8_flow_accumulation(correc, acc, log=True)

    # Normalize CRS metadata to keep downstream GIS/raster steps predictable.
    ensure_crs(correc, crs_project)
    ensure_crs(direc, crs_project)
    ensure_crs(acc, crs_project)

    return FlowProducts(correc=correc, direc=direc, acc=acc)
