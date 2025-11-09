# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Created on Wed Jun 11 09:45:12 2025

@author: mathi
"""
"""
This module orchestrates the full PyHELP workflow from raw inputs to a
NetCDF. it performs:

-Generation of climate CSV files (precip, airtemp, solrad) via 
the auxiliary main_cdf.py when they are not provided.

- Optional grid update using PyhelpGrid when grid_kwargs is set.

- Execution of the HELP model through help_example_cli.py (called via
the current Python environment) to compute daily outputs.

- Conversion of daily .OUT files into a NetCDF dataset containing
runoff, *evapotranspiration* and *recharge* time‑series for every cell.

"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict
import json

import numpy as np
import pandas as pd
import xarray as xr
from hydromodpy.pyhelp.daily_output import read_daily_help_output
from hydromodpy.pyhelp.pyhelp_grid import PyhelpGrid
from .pyhelp_netcdf_writer import pyhelp_outputs_rasterized_netcdf  
from hydromodpy.tools import get_logger

logger = get_logger(__name__)



def preprocessing_pyhelp(
    *,
    workdir: str,
    outpath: str,
    grid_csv: str | None = None,
    grid_base: str | None = None,
    dem: str | None = None,
    grid_kwargs: Dict | None = None,
    ready_csvs: List[str] | None = None,
    era5_folder: str | None = None,
    shapefile: str | None = None,
    main_py: str | None = None,
    help_cli: str | None = None,
    compress_level: int = 4,
):
    """Run the full PyHELP workflow.

    Parameters:

    workdir : str
        Destination folder where every intermediate and final file will be
        written.
    grid_csv, grid_base : str | None
        Path to the base COMPLETED grid CSV.
    dem : str | None
        Optional DEM raster required when the grid is updated.
    grid_kwargs : Dict | None
        Keyword arguments forwarded to pyhelp.pyhelp_grid.PyhelpGrid to
        chnage cell size, lat/lon rounding, etc. If None no update is done.
    ready_csvs : List[str] | None
        If provided, absolute paths to the three climate CSV inputs
        [precip, airtemp, solrad]. When None they will be generated via
        the main_cdf.py script.
    era5_folder, shapefile : str | None
        Additional parameters used by main_cdf.py.
    main_py, help_cli : str | None
        Custom paths for the auxiliary command‑line interfaces. When None the
        script will look for main_cdf.py and help_example_cli.py in
        the current file folder.
    compress_level : int, default 4
        zlib compression level (0–9) for the output NetCDF file.
    """
    
    workdir = Path(workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    outpath = Path(outpath).expanduser().resolve()

    if grid_csv:
        grid_csv = Path(grid_csv).expanduser()
        if not grid_csv.exists():
            raise FileNotFoundError(f"Grid CSV not found: {grid_csv}")

    repo_root = Path(__file__).resolve().parents[2]

    def _inject_pythonpath(env: dict) -> None:
        """Ensure child processes can import hydromodpy without installation."""
        paths = [str(repo_root)]
        existing = env.get("PYTHONPATH")
        if existing:
            paths.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(paths)


#%% Case 1 : ready_cscv is None
    #if ready_csvs (climatic) is None-> launch main_cdf.py   
    
    if ready_csvs is None:
        main_script = Path(main_py) if main_py else Path(__file__).with_name("main_cdf.py")
        if not main_script.exists():
            raise FileNotFoundError(f"main_cdf not found: {main_script}")
        
        env = os.environ.copy()
        
        if grid_csv is not None:
            env["PYHELP_BASE_GRID"] = str(grid_csv)
        
        env.update({
            "PYHELP_DEM": str(dem) if dem else "",
            "PYHELP_SHP": str(shapefile) if shapefile else "",
            "PYHELP_ERA5_FOLDER": str(era5_folder) if era5_folder else "",
            "PYHELP_GRID_KWARGS": json.dumps(grid_kwargs or {}),
            "PYHELP_WORKDIR": str(workdir),
        })

        # Use the current Python executable directly (no conda needed)
        _inject_pythonpath(env)

        cmd = [
            sys.executable,
            str(main_script),
            "--workdir", str(workdir),
        ]
        

        #User console informations from system
        logger.info("Launching main_cdf.py with Python %s.%s", sys.version_info.major, sys.version_info.minor)
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        logger.debug("main_cdf.py command: %s", " ".join(cmd))
        if proc.stdout:
            logger.debug("main_cdf.py stdout:\n%s", proc.stdout)
        if proc.stderr:
            logger.debug("main_cdf.py stderr:\n%s", proc.stderr)
        proc.check_returncode()
        
        grid_csv = workdir / "input_grid_base1.csv"
        
        #outputs from main_cdf.py
        ready_csvs = [
            workdir / "precip_input_data.csv",
            workdir / "airtemp_input_data.csv",
            workdir / "solrad_input_data.csv",
        ]

#%% Case 2 : ready_csvs is True or grid update/generation
        #ready_csvs is given but grid update (grid_kwargs is specified)
        
    elif grid_kwargs:
        logger.info("Updating PyHELP grid geometry before run")
        env = os.environ.copy()
        env.update({"PYHELP_SHP": str(shapefile) if shapefile else ""})
        base_grid = workdir.parents[3] / "10_coupling_with_land_surface_model_pyhelp" / "data" / "input_grid_base.csv"
        out_grid = workdir / "input_grid_base1.csv"
        pg = PyhelpGrid(str(base_grid), str(out_grid), str(dem or ""))
        pg.update_parameters(**grid_kwargs)
        grid_csv = out_grid
        
        for csv in ready_csvs:
            src = Path(csv).expanduser().resolve()
            dst = workdir / src.name
            shutil.copy2(src, dst)
            #print(f"[PyHELP preprocessing] copied : {src.name} to {dst}")

    if len(ready_csvs) != 3:
        raise ValueError("ready_csvs must contain [precip, tair, solrad]")
    precip_csv, tair_csv, solrad_csv = map(Path, ready_csvs)

    in_files = {
        Path(grid_csv): workdir / "input_grid_base1.csv",
        precip_csv: workdir / "precip_input_data.csv",
        tair_csv: workdir / "airtemp_input_data.csv",
        solrad_csv: workdir / "solrad_input_data.csv",
    }
    
    #Copy each input file into workdir
    for src, dst in in_files.items():
        if src.resolve() != dst.resolve():
            dst.write_bytes(src.read_bytes())
            
            

#%% Help_example_cli.py execution

    # Use the current Python executable directly (no conda needed)
    help_cli = Path(help_cli) if help_cli else Path(__file__).with_name("help_example_cli.py")

    cmd = [
        sys.executable,
        str(help_cli),
        "--workdir", str(workdir),
        "--grid_csv", str(in_files[Path(grid_csv)]),
        "--precip",   str(in_files[precip_csv]),
        "--tair",     str(in_files[tair_csv]),
        "--solrad",   str(in_files[solrad_csv]),
    ]
    
    logger.info("Executing pyHELP CLI workflow")
    logger.debug("pyHELP CLI command: %s", " ".join(cmd))
    env_cli = os.environ.copy()
    env_cli["PYHELP_WORKDIR"] = str(workdir)
    _inject_pythonpath(env_cli)

    # Run with real-time output display instead of capturing
    proc = subprocess.run(cmd, env=env_cli)

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    
    
    
    #%% Daily and spatialised NETCDF file generation

    nc_grid = pyhelp_outputs_rasterized_netcdf(
        workdir=workdir,
        outpath=outpath,
        grid_csv=grid_csv,
        dem=dem,
        compress_level=compress_level,
        clean_temp=True,
    )
