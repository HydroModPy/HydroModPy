# -*- coding: utf-8 -*-
"""
Created on Thu Jan  8 15:11:21 2026

@author: pelissierm
"""

from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class SitePaths:
    site_id:str
    site_root: Path
    results_pyhelp: Path
    clipped_rasters: Path
    plots_pyhelp: Path
    
def site_paths(out_root: Path, site_id: str):
    site_root = out_root / site_id
    results_pyhelp = site_root / "results_pyhelp"
    clipped_rasters = results_pyhelp / "clipped_rasters"
    plots_pyhelp = results_pyhelp / "plots_pyhelp"
    
    return SitePaths(
        site_id = site_id,
        site_root=site_root,
        results_pyhelp=results_pyhelp, 
        clipped_rasters=clipped_rasters,
        plots_pyhelp=plots_pyhelp
        )