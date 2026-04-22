# -*- coding: utf-8 -*-
"""
Created on Thu Jan  8 15:33:28 2026

@author: pelissierm
"""

from dataclasses import dataclass
from pathlib import Path
import shutil
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class ClimateFiles:
    precip: Path
    airtemp: Path
    solrad: Path
    

def _read_raw_pyhelp_csv(path: Path, decimals: int = 2):
    df = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    #df = df.iloc[1:].reset_index(drop=True)

    lat = df.iloc[0, 1:].tolist()
    lon = df.iloc[1, 1:].tolist()
    data = df.iloc[2:].copy()

    date_str = data.iloc[:, 0].astype(str).str.strip()
    dates = pd.to_datetime(date_str, format="mixed", dayfirst=True, errors="raise")

    vals = data.iloc[:, 1:].apply(pd.to_numeric, errors="coerce").round(decimals)
    return lat, lon, dates, vals


def _fixed_pyhelp_csv(out_path: Path, lat, lon, dates, vals: pd.DataFrame):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("Latitude (dd)," + ",".join(map(str, lat)) + "\n")
        f.write("Longitude (dd)," + ",".join(map(str, lon)) + "\n\n")

    vals = vals.copy()
    vals.index = dates.dt.strftime("%d/%m/%Y")
    vals.to_csv(out_path, mode="a", header=False)
    

def filter_by_date(filepath: Path, start_date: str, end_date: str, header_rows: int = 2, date_format: str = "%d/%m/%Y"):
    df = pd.read_csv(filepath, header=None, dtype=str, keep_default_na=False)
    header = df.iloc[:header_rows].copy()
    data = df.iloc[header_rows:].copy()

    date_str = data.iloc[:, 0].astype(str).str.strip()
    dates = pd.to_datetime(date_str, format=date_format, dayfirst=True, errors="coerce")

    start_dt = pd.to_datetime(start_date, format=date_format, dayfirst=True)
    end_dt = pd.to_datetime(end_date, format=date_format, dayfirst=True)

    mask = dates.notna() & (dates >= start_dt) & (dates <= end_dt)

    out = pd.concat([header, data.loc[mask].reset_index(drop=True)], axis=0, ignore_index=True)
    out.to_csv(filepath, index=False, header=False)
    

#temporary function, might be deleted later on
def _backup_csv(out_path: Path, lat, lon, dates, backup_series: pd.Series):
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"Latitude (dd),{lat}\n")
        f.write(f"Longitude (dd),{lon}\n\n")

    tmp = pd.DataFrame({0: backup_series.to_numpy(dtype=float)})
    tmp.index = dates.dt.strftime("%d/%m/%Y")
    tmp.to_csv(out_path, mode="a", header=False)


def preprocess_climate_inputs(climate_map: dict,
                              workdir: Path, decimals: int, date_window, logger):
    workdir.mkdir(parents=True, exist_ok=True)

    inputs = [
        ("precip",  climate_map["precip_input"],  "min"),
        ("airtemp", climate_map["airtemp_input"], "max"),
        ("solrad",  climate_map["solrad_input"],  "max"),
    ]

    for name, raw_path, crit in inputs:
        lat, lon, dates, vals = _read_raw_pyhelp_csv(raw_path, decimals=decimals)

        means = np.nanmean(vals.to_numpy(dtype=float), axis=0)

        finite = np.isfinite(means)
        if not np.any(finite):
            col0 = 0
        else:
            if crit == "min":
                col0 = int(np.nanargmin(means))
            elif crit == "max":
                col0 = int(np.nanargmax(means))
            else:
                raise ValueError(f"crit invalide: {crit} (attendu: 'min' ou 'max')")

        backup_path = workdir / f"{name}_input_data_backup.csv"
        _backup_csv(backup_path, lat[col0], lon[col0], dates, vals.iloc[:, col0])

        for p in (raw_path, backup_path):
            filter_by_date(
                p,
                start_date=date_window.start_date,
                end_date=date_window.end_date,
                header_rows=2,
                date_format=date_window.date_format,
            )
            logger.info(f"[climate] filtered {p.name} to {date_window.start_date}..{date_window.end_date}")

    #climate_stats(workdir, climate_map)
    logger.info("[climate] stats extracted")



def copy_climate_from_cerra(site_id: str, climate_root: Path, workdir: Path, logger):
    """
    copy_climate_from_cerra 
    Find source files for each pyHelp variable and create a copy in workdir.

    :param site_id: _description_
    :type site_id: str
    :param climate_root: _description_
    :type climate_root: Path
    :param workdir: _description_
    :type workdir: Path
    :param logger: _description_
    :type logger: _type_
    :raises FileNotFoundError: _description_
    :return: _description_
    :rtype: _type_
    """
    src_dir = climate_root / site_id
    if not src_dir.is_dir():
        raise FileNotFoundError(f"Climate folder not found: {src_dir}")

    files = sorted([p.name for p in src_dir.iterdir() if p.is_file()])

    site_prefix = site_id.lstrip("_")

    def pick(cond):
        for f in files:
            if (f.startswith(site_id + "_") or f.startswith(site_prefix + "_")) and cond(f):
                return src_dir / f
        return None

    mapping = {
        "precip_input": pick(lambda f: "total_precipitation_pyhelp" in f),
        "airtemp_input": pick(lambda f: "2m_temperature_pyhelp" in f),
        "solrad_input": pick(lambda f: "surface_solar_radiation_downwards_pyhelp" in f),
    }

    missing = [k for k, v in mapping.items() if v is None]
    if missing:
        raise FileNotFoundError(
            f"Missing climate inputs for site={site_id} in {src_dir}: {missing}. "
            f"Files seen: {files}"
        )

    climate_map = {}
    workdir.mkdir(parents=True, exist_ok=True)
    for var_name, src in mapping.items():
        dst = workdir / f"{var_name}_data.csv"
        shutil.copyfile(src, dst)
        climate_map[var_name] = dst
        logger.info(f"[climate] copied {src.name} -> {dst}")

    return climate_map

# @TODO - remove check climate - not used in intergrated code
def check_climate_from_cerra(site_id: str, climate_root: Path, workdir: Path, logger):
    src_dir = climate_root / site_id
    if not src_dir.is_dir():
        raise FileNotFoundError(f"Climate folder not found: {src_dir}")

    site_prefix = site_id.lstrip("_")
    files = sorted([p.name for p in src_dir.iterdir() if p.is_file()])

    def pick(cond):
        for f in files:
            if f.startswith(site_prefix + "_") and cond(f):
                return src_dir / f
        return None

    mapping = {
        'precip_input': pick(lambda f: "total_precipitation_pyhelp" in f),
        'airtemp_input': pick(lambda f: "2m_temperature_pyhelp" in f),
        'solrad_input': pick(lambda f: "surface_solar_radiation_downwards_pyhelp" in f),
    }
    climate_map = {
        'precip_input': None,
        'airtemp_input': None,
        'solrad_input': None,
    }

    workdir.mkdir(parents=True, exist_ok=True)
    for var_name, src in mapping.items():
        if src is None:
            logger.warning(f"[climate] missing source for {var_name} (site={site_id})")
            continue
        climate_map[var_name] = src
        logger.info(f"[climate] {var_name} pyHelp input mapped at {src_dir / src}.")       
    return climate_map

