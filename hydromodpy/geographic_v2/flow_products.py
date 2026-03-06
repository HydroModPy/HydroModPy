"""Build regional hydrologic rasters used by catchment delineation.

Products are computed on the full input DEM support:
- corrected DEM (fill/breach),
- D8 flow direction,
- D8 flow accumulation.
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
    """Regional flow products generated from one DEM."""

    correc: str
    direc: str
    acc: str


def build_regional_flow_products(
    *,
    dem_init_path: str | Path,
    dem_out_dir_path: str | Path,
    dem_correc_type: str,
    crs_project: str | None = None,
) -> FlowProducts:
    """
    Build correction, D8 direction and D8 accumulation rasters from a DEM.

    `dem_correc_type` must be `"fill"` or `"breach"`.
    """
    # Step 1 - Normalize and prepare output directory.
    dem_in = str(dem_init_path)
    out_dir = Path(dem_out_dir_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 2 - Hydrologic correction of the DEM.
    if dem_correc_type == "fill":
        correc = str(out_dir / "dem_fill.tif")
        wbt.fill_depressions(dem_in, correc)
    elif dem_correc_type == "breach":
        correc = str(out_dir / "dem_breach.tif")
        wbt.breach_depressions(dem_in, correc)
    else:
        raise ValueError(f"Unknown dem_correc_type={dem_correc_type!r}. Expected 'fill' or 'breach'.")

    # Step 3 - D8 flow direction raster.
    direc = str(out_dir / "dem_direc.tif")
    wbt.d8_pointer(correc, direc, esri_pntr=False)

    # Step 4 - D8 accumulation raster.
    acc = str(out_dir / "dem_acc.tif")
    wbt.d8_flow_accumulation(correc, acc, log=True)

    # Step 5 - Enforce CRS metadata for all generated rasters.
    ensure_crs(correc, crs_project)
    ensure_crs(direc, crs_project)
    ensure_crs(acc, crs_project)

    return FlowProducts(correc=correc, direc=direc, acc=acc)
