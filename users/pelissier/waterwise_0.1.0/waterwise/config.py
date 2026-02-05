# -*- coding: utf-8 -*-
"""
Created on Thu Jan  8 10:38:22 2026

@author: pelissierm
"""
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Paths:
    data_root: Path
    out_root: Path
    climate_root: Path
    base_grid_csv: Path
    watershed_shp_rel: Path = Path("")

#for climate cerra management
@dataclass(frozen=True)
class CerraPaths:
    """
     Paths to acces CERRA data
    """
    # acces cerra forecast root directoty - forecast_root/_{variable}/{year}/{year}_alps.nc    
    forecast_root: Path
    # acces cerra land root directoty - land_root/_{variable}/{year}/{year}_alps.nc
    land_root: Path
    # acces cerra local root directoty - local_root/_{siteId}/{siteId}_{variable}.nc
    local_root: Path
    # acces cerra data statistic timeserie - local_root/_{siteId}/{siteId}_{variable}.nc
    timeserie_root : Path
    # acces cerra Alps grid file - can be generate from any {year}_alps.nc file 
    alps_grid: Path = Path("")


@dataclass(frozen=True)
class CerraParams:
    """
     Parameters to preprocess CERRA data
    """
    # Geographic information
    site_shape_epsg: int = 3035

    # Parameters used in make_local_climate
    local_buffer: float = 0.1
    local_checkplot: bool = True
    date_window = [1984,2025]

    # Parameters make pyhelp input
    spacestep_meter:int = 2500 #m
    timestep:str = '1D'
    interpolation_rule:str = 'nearest'


#temporary class
@dataclass(frozen=True)
class ClimateWindow:
    start_date: str = ""
    end_date: str = ""
    date_format: str = ""

@dataclass(frozen=True)
class RunOptions: 
    make_catchment: bool = True
    make_grid: bool = True
    make_climate_locale: bool = True
    make_climate_pyHelp: bool = True
    make_climate_timeserie: bool = True
    make_climate_plots = True
    make_climate: bool = True
    run_pyhelp: bool =True
    make_plots: bool = True
    save_png: bool = True
    

