from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Literal, Tuple


@dataclass
class PathConfig:
    out_path_mode: Literal["fixed", "env"] = "fixed"
    fixed_out_path: str = "/home/bb/Documents/02_Output_HydroModPy"
    data_subdir: str = "LakeRes"
    dem_relative: Tuple[str, ...] = (
        "MNT",
        "MNT_Bretagne_BD-ALTI-v2_2020-10_L93_75m.tif",
    )
    climate_relative: Tuple[str, ...] = (
        "Meteo",
        "Historiques SIM2",
        "climatic_data.csv",
    )
    dam_input_relative_candidates: Tuple[Tuple[str, ...], ...] = (
        (
            "Reservoir",
            "La_Cheze",
            "Donnees journalieres EBR",
            "dam_input_2004_2024.csv",
        ),
        (
            "Reservoir",
            "La_Cheze",
            "Donnees journalieres EBR",
            "dam_input_2004_2024_corrected2.csv",
        ),
        (
            "Reservoir",
            "La_Cheze",
            "Donnees journalieres EBR",
            "dam_input_2004_2024_corrected.csv",
        ),
    )
    hydrometry_relative: Tuple[str, ...] = ("Stations jaugeage",)
    hydrometry_filename: str = "france hydrometric stations.shp"
    intermittency_relative: Tuple[str, ...] = ("Stations ONDE",)
    intermittency_filename: str = "regional onde stations.shp"
    geology_relative: Tuple[str, ...] = ("Geologie",)
    geology_types_obs: str = "GEO1M.shp"
    geology_fields_obs: str = "CODE_LEG"
    hydrography_relative: Tuple[str, ...] = ("Hydrographie",)
    hydrography_types_obs: Tuple[str, ...] = ("CoursEau_FXX_clip_bre",)
    hydrography_fields_obs: Tuple[str, ...] = ("fid",)

    def dem_path(self, data_path: str) -> str:
        return os.path.join(data_path, *self.dem_relative)

    def climate_path(self, data_path: str) -> str:
        return os.path.join(data_path, *self.climate_relative)

    def dam_input_path(self, data_path: str) -> str:
        for rel in self.dam_input_relative_candidates:
            path = os.path.join(data_path, *rel)
            if os.path.exists(path):
                return path
        # Fallback to first candidate for explicit error message upstream.
        return os.path.join(data_path, *self.dam_input_relative_candidates[0])

    def hydrometry_path(self, data_path: str) -> str:
        return os.path.join(data_path, *self.hydrometry_relative)

    def intermittency_path(self, data_path: str) -> str:
        return os.path.join(data_path, *self.intermittency_relative)

    def geology_path(self, data_path: str) -> str:
        return os.path.join(data_path, *self.geology_relative)

    def hydrography_path(self, data_path: str) -> str:
        return os.path.join(data_path, *self.hydrography_relative)


@dataclass
class GeneralConfig:
    first_year: int = 2023
    last_year: int = 2023
    sim_state: str = "transient"
    freq_input: str = "D"
    subbassin: bool = False
    load_geographic: bool = False
    save_object: bool = True
    dis_perlen: bool = True
    model_name: str = "base"
    visual_plot: bool = False
    from_xyv: Tuple[int, int, int, int, str] = (331315, 6781273, 200, 10, "EPSG:2154")
    box: bool = False
    sink_fill: bool = False
    plot_cross: bool = True
    watershed_prefix: str = "barrage_Cheze_SFR_LAK"
    watershed_name_style: Literal["commun", "simplex"] = "commun"
    simplex_tag: str = "calib_V1_lvl"


@dataclass
class HydraulicConfig:
    nlay: int = 1
    lay_decay: float = 1.0
    bottom: float | None = None
    thick: float = 24.86968801
    hk_m_day: float = 0.000114826 * 24 * 3600
    hk_vertical: list | None = None
    cond_drain: float | None = None
    sy: float = 0.003807997
    poro_decay: float = 0.0


@dataclass
class BoundaryConfig:
    bc_left: float | None = None
    bc_right: float | None = None
    sea_level: str | float | None = "None"


@dataclass
class ReservoirConfig:
    lake_id: str = "reservoir_cheze"
    mask_relative: Tuple[str, ...] = (
        "Reservoir",
        "La_Cheze",
        "Masque",
        "Cheze_polygon_larger.shp",
    )
    bathymetry_relative: Tuple[str, ...] = (
        "Reservoir",
        "La_Cheze",
        "Bathymetrie",
        "Cheze_bathy_1m_NGF-elevation_v2enlarged.nc",
    )
    outlet_relative: Tuple[str, ...] | None = (
        "Reservoir",
        "La_Cheze",
        "Exutoire alternatif",
        "lakeres_outlets.shp",
    )
    stagemax: float = 87.3
    leakance_m_day: float = 1e-6 * 24 * 3600
    resti_threshold: float = 0.10

    def mask_path(self, data_path: str) -> str:
        return os.path.join(data_path, *self.mask_relative)

    def bathymetry_path(self, data_path: str) -> str:
        return os.path.join(data_path, *self.bathymetry_relative)

    def outlet_path(self, data_path: str) -> str | None:
        if self.outlet_relative is None:
            return None
        return os.path.join(data_path, *self.outlet_relative)


@dataclass
class StreamflowConfig:
    enabled: bool = True
    icalc: int = 1
    area_fraction: float = 0.7
    depth: float = 0.0
    hcond_max: float = 0.08
    thickm: float = 0.1
    roughch: float = 0.03
    correct_multiple_reaches: bool = False
    correct_elevations: bool = True


@dataclass
class OptimizationConfig:
    enabled: bool = False
    hk_bounds_m_day: Tuple[float, float] = (1e-6 * 24 * 3600, 1e-3 * 24 * 3600)
    sy_bounds: Tuple[float, float] = (0.001, 0.1)
    thick_bounds: Tuple[float, float] = (20.0, 40.0)
    xatol: float = 0.01
    fatol: float = 0.01
    maxiter: int = 200
    use_time_filter: bool = True
    calib_start_date: str = "2013-01-01"
    calib_end_date: str = "2022-12-31"
    use_seasonal_filter: bool = False
    season_start_month: int = 7
    season_start_day: int = 1
    season_end_month: int = 12
    season_end_day: int = 31


@dataclass
class RuntimeConfig:
    log_mode: str = "dev"
    make_volume_plot: bool = True


@dataclass
class ProjectConfig:
    paths: PathConfig = field(default_factory=PathConfig)
    general: GeneralConfig = field(default_factory=GeneralConfig)
    hydraulic: HydraulicConfig = field(default_factory=HydraulicConfig)
    boundary: BoundaryConfig = field(default_factory=BoundaryConfig)
    reservoir: ReservoirConfig = field(default_factory=ReservoirConfig)
    streamflow: StreamflowConfig = field(default_factory=StreamflowConfig)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    climate_agg_rules: Dict[str, str] = field(
        default_factory=lambda: {
            "recharge": "sum",
            "runoff": "sum",
            "precip": "sum",
            "evt": "sum",
            "etp": "sum",
            "t": "mean",
        }
    )
    dam_agg_rules: Dict[str, str] = field(
        default_factory=lambda: {
            "cheze_lvl": "mean",
            "cheze_vol": "mean",
            "canut": "mean",
            "meu": "mean",
            "usine": "mean",
            "resti": "mean",
        }
    )


def profile_common() -> ProjectConfig:
    cfg = ProjectConfig()
    cfg.paths.out_path_mode = "fixed"
    cfg.paths.fixed_out_path = "/home/bb/Documents/02_Output_HydroModPy"

    cfg.general.first_year = 2023
    cfg.general.last_year = 2023
    cfg.general.freq_input = "D"
    cfg.general.watershed_name_style = "commun"

    cfg.hydraulic.thick = 24.86968801
    cfg.hydraulic.hk_m_day = 0.000114826 * 24 * 3600
    cfg.hydraulic.sy = 0.003807997

    cfg.optimization.enabled = False
    cfg.runtime.make_volume_plot = True

    cfg.climate_agg_rules = {
        "recharge": "sum",
        "runoff": "sum",
        "precip": "sum",
        "evt": "sum",
        "etp": "sum",
        "t": "mean",
    }
    return cfg


def profile_simplex() -> ProjectConfig:
    cfg = ProjectConfig()
    cfg.paths.out_path_mode = "env"

    cfg.general.first_year = 2012
    cfg.general.last_year = 2022
    cfg.general.freq_input = "W"
    cfg.general.watershed_name_style = "simplex"

    cfg.hydraulic.thick = 26.0
    cfg.hydraulic.hk_m_day = 2.55e-5 * 24 * 3600
    cfg.hydraulic.sy = 0.005

    cfg.optimization.enabled = True
    cfg.optimization.calib_start_date = "2013-01-01"
    cfg.optimization.calib_end_date = "2022-12-31"
    cfg.runtime.make_volume_plot = False

    cfg.climate_agg_rules = {
        "recharge": "mean",
        "runoff": "mean",
        "precip": "mean",
        "evt": "mean",
        "etp": "mean",
        "t": "mean",
    }
    return cfg
