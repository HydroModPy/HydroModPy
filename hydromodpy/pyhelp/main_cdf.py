# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Created on Sat Jun 14 11:01:33 2025

@author: mathi
"""

"""
main_cdf.py – Generate grid and climate CSVS for PyHELP

- Reads input paths from environment variables (grid, DEM, shapefile, ERA5 folder)
- Optionally updates the grid using parameters in PYHELP_GRID_KWARGS
- Generates three daily CSVs (precip, airtemp, solrad) from ERA5 data
- Moves output files to PYHELP_WORKDIR
"""

import json, os, sys, shutil
from pathlib import Path

from hydromodpy.tools import get_logger

logger = get_logger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent))

from hydromodpy.pyhelp.pyhelp_grid import PyhelpGrid
from hydromodpy.pyhelp.pyhelp_era5 import PyhelpEra5


def _need(var: str):
    val = os.environ.get(var)
    if not val:
        sys.exit(f"[main_cdf] ERROR : missing environment variable « {var} »")
    return Path(val).expanduser().resolve()


def main():
    base_grid_env = os.environ.get("PYHELP_BASE_GRID", "").strip()
    if base_grid_env == "":
        workdir_path = Path(os.environ["PYHELP_WORKDIR"]).expanduser()
        base_grid = workdir_path / "input_grid_base.csv"
    else:
        base_grid = Path(base_grid_env).expanduser()

    dem_path = Path(os.environ.get("PYHELP_DEM", "")).expanduser()
    
    # Shapefile
    shp_path = os.environ.get("PYHELP_SHP")
    shp_path = Path(shp_path).expanduser() if shp_path else None

    era5_root = _need("PYHELP_ERA5_FOLDER")

    out_grid_csv = base_grid.parent / "input_grid_base1.csv"

    pg = PyhelpGrid(
        str(base_grid),
        str(out_grid_csv),
        str(dem_path) if dem_path else "",
        str(shp_path) if shp_path else ""
    )

    if "PYHELP_GRID_KWARGS" in os.environ:
        kwargs = json.loads(os.environ["PYHELP_GRID_KWARGS"])
        pg.update_parameters(**kwargs)

    logger.info("Grid specification written to %s", out_grid_csv)

    # Call PyhelpEra5 with or without shapefile
    if shp_path and shp_path.exists():
        pe = PyhelpEra5(str(era5_root), str(shp_path))
    else:
        pe = PyhelpEra5(str(era5_root))

    pe.extract_era5_daily_timeseries()
    
    workdir_path = Path(os.environ["PYHELP_WORKDIR"]).expanduser().resolve()
    
    for name in ("precip_input_data.csv", "airtemp_input_data.csv", "solrad_input_data.csv"):
        shutil.move(Path(era5_root) / name, workdir_path / name)
        logger.info("Climatic CSV %s moved to %s", name, workdir_path)


    for name in ("precip_input_data.csv",
             "airtemp_input_data.csv",
             "solrad_input_data.csv"):
        logger.debug("Climatic CSV ready at %s", Path(era5_root) / name)


    logger.info("main_cdf workflow completed")


if __name__ == "__main__":
    main()
