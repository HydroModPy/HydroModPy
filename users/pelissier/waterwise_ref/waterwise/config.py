from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Paths:
    data_root: Path
    out_root: Path
    climate_root: Path
    base_grid_csv: Path
    watershed_shp_rel: Path = Path("")


@dataclass(frozen=True)
class CerraPaths:
    forecast_root: Path
    land_root: Path
    local_root: Path
    timeserie_root: Path
    alps_grid: Path = Path("")


@dataclass(frozen=True)
class CerraParams:
    site_shape_epsg: int = 3035
    local_buffer: float = 0.1
    local_checkplot: bool = True
    date_window: tuple[int, int] = (1984, 2025)
    spacestep_meter: int = 2500
    timestep: str = "1D"
    interpolation_rule: str = "nearest"


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
    make_climate_pyhelp: bool = True
    make_climate_timeserie: bool = True
    make_climate_plots: bool = True
    make_climate: bool = True
    make_climate_debiaser: bool = True
    run_pyhelp: bool = True
    run_validation: bool = True
    make_plots: bool = True
    save_png: bool = True
    run_predictions: bool = False
    stats_historical: bool = True
    stats_prediction: bool =True


@dataclass(frozen=True)
class RuntimeConfig:
    paths: Paths
    cerra_paths: CerraPaths
    cerra_params: CerraParams
    date_window: ClimateWindow
    options: RunOptions
    rasters_dir: Path
    dem_path: Path
    sites_xlsx: Path
    xlsx_out: Path | None = None
    ref_root: Path | None = None
    proj_root: Path | None = None
    pred_out_root: Path | None = None


STATUS_COLUMNS: tuple[str, ...] = (
    "catchment_done",
    "grid_done",
    "climate_local_done",
    "climate_ts_done",
    "climate_inputs_done",
    "climate_processed_done",
    "pyhelp_done",
)


def ensure_status_columns(df, columns: Iterable[str] = STATUS_COLUMNS):
    for col in columns:
        if col not in df.columns:
            df[col] = 0
    return df
