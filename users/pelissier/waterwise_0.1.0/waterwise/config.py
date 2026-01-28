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
    make_climate: bool = True
    run_pyhelp: bool =True
    make_plots: bool = True
    save_png: bool = True
    

