# -*- coding: utf-8 -*-
"""Configuration objects for PyHELP preprocessing."""

from pathlib import Path
from typing import Optional, Union, Tuple


class PyhelpGridParams:
    """Class for PyHELP grid parameters."""

    def __init__(
        self,
        *,
        growth_start: int = 140,
        growth_end: int = 280,
        wind: float = 2.5,
        hum1: float = 60,
        hum2: float = 65,
        hum3: float = 70,
        hum4: float = 70,
        LAI: float = 2.4,
        EZD: float = 44.5,
        CN: float = 55,
        nlayer: int = 1,
        lay_type1: int = 1,
        thick1: float = 100,
        poro1: float = 0.45,
        fc1: float = 0.23,
        wp1: float = 0.116,
        ksat1: float = 0.0,
        dist_dr1: float = 50,
        slope1: float = 35,
            ):
        self.growth_start = growth_start
        self.growth_end = growth_end
        self.wind = wind    
        self.hum1 = hum1
        self.hum2 = hum2
        self.hum3 = hum3
        self.hum4 = hum4
        self.LAI = LAI
        self.EZD = EZD
        self.CN = CN
        self.nlayer = nlayer
        self.lay_type1 = lay_type1
        self.thick1 = thick1
        self.poro1 = poro1
        self.fc1 = fc1
        self.wp1 = wp1
        self.ksat1 = ksat1
        self.dist_dr1 = dist_dr1
        self.slope1 = slope1


class PyhelpPreprocessingConfig:
    """Configuration for the preprocessing workflow"""

    def __init__(
        self,
        *,
        workdir: Path,
        pyhelp_out_nc: Path,

        # Grid inputs
        grid_ready: Optional[Path] = None,
        grid_base : Optional[Path] = None,
        dem: Optional[Path],
        shapefile: Optional[Path] = None,

        # Climate inputs: either ready_csvs OR era5_folder
        ready_climatic_csvs: Optional[Tuple[Path, Path, Path]] = None,
        era5_folder: Optional[Path] = None,

        # Parameters
        grid_params: Optional[PyhelpGridParams] = None,

        compress_level: int = 4,
            ):
        
        
        self.workdir = Path(workdir)
        self.pyhelp_out_nc = Path(pyhelp_out_nc)

        self.grid_ready = Path(grid_ready) if grid_ready is not None else None
        self.grid_base = Path(grid_base)
        self.dem = Path(dem) if dem is not None else None
        self.shapefile = Path(shapefile) if shapefile is not None else None

        if ready_climatic_csvs is not None:
            self.ready_csvs = (
                Path(ready_climatic_csvs[0]),
                Path(ready_climatic_csvs[1]),
                Path(ready_climatic_csvs[2])         
                )
            
        self.era5_folder = Path(era5_folder) if era5_folder is not None else None

        self.grid_params = grid_params
        self.compress_level = int(compress_level)

        self.inputs_dir = self.workdir / "inputs"
        self.outputs_dir = self.workdir / "outputs"
        self.tmp_dir = self.workdir / "tmp"
