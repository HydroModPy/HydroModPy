# -*- coding: utf-8 -*-
"""
Created on Tue Jan 27 08:15:31 2026

@author: pelissierm
"""


from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple, Union

import numpy as np
import pandas as pd

from hydromodpy.pyhelp.processing import read_daily_help_output
from hydromodpy.tools import get_logger

logger = get_logger(__name__)


#%%config & constants

DAILY_COMPONENTS = ("precip", "runoff", "evapo", "rechg")

HELP_DAILY_KEYS = {
    "precip": "rain",
    "runoff": "runoff",
    "evapo": "et",
    "rechg": "leak last",
}

MONTHS = tuple(range(1, 13))

YEARLY_COLS: Tuple[str, ...] = ("precip", "rechg", "runoff", "evapo", "subrun1", "subrun2", "perco")


#%% private functions

@dataclass(frozen=True)
class DailyCellSeries:
    cid: str
    df: pd.DataFrame

#corrects dates format
def _to_dates(years, doy):
    dates = pd.to_datetime(years * 1000 + doy, format="%Y%j", errors="coerce")
    return pd.DatetimeIndex(dates)


def _parse_daily_outfile(cid, outpath):
    cid_str = str(cid)
    outpath = Path(outpath)
    
    try:
        d = read_daily_help_output(str(outpath))
    except Exception:
        logger.exception("Failed reading daily HELP output for cell %s (%s)", cid_str, outpath)
        return None

    years = np.asarray(d.get("years", []), dtype=int)
    doy = np.asarray(d.get("days", []), dtype=int)
    dates = _to_dates(years, doy)
    valid = ~pd.isna(dates)
    dates = dates[valid]
    df = pd.DataFrame(index=dates)

    # Standardize columns
    for out_var, in_key in HELP_DAILY_KEYS.items():
        arr = np.asarray(d.get(in_key, []), dtype=float)
        if arr.size == 0:
            df[out_var] = np.nan
            continue
        arr = arr[: valid.size]
        df[out_var] = arr[valid]

    df = df.dropna(how="any")  #only keep days where all components exist
    df = df.sort_index()
    return DailyCellSeries(cid=cid_str, df=df)


def _iter_cell_series_from_outfiles(cell_outfiles):
    for cid, outpath in cell_outfiles.items():
        s = _parse_daily_outfile(cid, outpath)
        if s is not None:
            yield s


#%%Public functions

def export_cells_daily_to_csv(cell_outfiles, out_csv, year_from, year_to, overwrite = True):
    
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    mode = "w" if overwrite else "a"
    header = overwrite or (not out_csv.exists())

    cols = ["cid", "date", "year", "doy", *DAILY_COMPONENTS]

    with out_csv.open(mode, encoding="utf-8", newline="") as f:
        if header:
            f.write(",".join(cols) + "\n")

        for s in _iter_cell_series_from_outfiles(cell_outfiles):
            df = s.df.copy()
            mask = (df.index.year >= year_from) & (df.index.year <= year_to)
            df = df.loc[mask]
            if df.empty:
                continue

            years = df.index.year.astype(int)
            doy = df.index.dayofyear.astype(int)

            out = df.copy()
            out.insert(0, "doy", doy)
            out.insert(0, "year", years)
            out.insert(0, "date", df.index)
            out.insert(0, "cid", s.cid)

            out.to_csv(f, index=False, header=False, float_format="%.6f")

    return out_csv


def calc_area_daily_avg(cellnames, workdir):
    
    workdir = Path(workdir)
    temp_dir = workdir / "help_input_files" / ".temp"

    series = []
    for cid in cellnames:
        outpath = temp_dir / f"{cid}.OUT"
        s = _parse_daily_outfile(cid, outpath)
        if s is not None:
            series.append(s.df)

    df_concat = pd.concat(series, axis=1, keys=range(len(series)))
    df_mean = df_concat.T.groupby(level=1).mean(numeric_only=True).T

    df_mean = df_mean.reindex(columns=list(DAILY_COMPONENTS))
    return df_mean

def calc_cells_yearly_avg_from_daily(cell_outfiles, year_from, year_to, fill_missing):

    rows = []

    for s in _iter_cell_series_from_outfiles(cell_outfiles):
        df = s.df
        mask = (df.index.year >= year_from) & (df.index.year <= year_to)
        df = df.loc[mask]

        if df.empty:
            out = {c: fill_missing for c in YEARLY_COLS}
            out["cid"] = s.cid
            rows.append(out)
            continue

        yearly = df.groupby(df.index.year).sum(numeric_only=True)
        mean_interannual = yearly.mean(axis=0, numeric_only=True)

        out = {c: fill_missing for c in YEARLY_COLS}
        out.update(mean_interannual.to_dict())
        out["cid"] = s.cid
        rows.append(out)

    if not rows:
        return pd.DataFrame(columns=list(YEARLY_COLS)).set_index(pd.Index([], name="cid"))

    df_out = pd.DataFrame(rows).set_index("cid")
    df_out = df_out.reindex(columns=list(YEARLY_COLS))
    return df_out


def save_cells_yearly_avg_from_daily(cell_outfiles, out_csv, year_from, year_to, fill_missing):
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    df = calc_cells_yearly_avg_from_daily(cell_outfiles=cell_outfiles, year_from=year_from, year_to=year_to, fill_missing=fill_missing)
    df.to_csv(out_csv, encoding="utf-8")
    return out_csv


def calc_cells_monthly_climatology_from_daily(
    cell_outfiles,
    year_from,
    year_to,
    require_full_years = True,
    output_format = "wide"
):
    """
    output_format:
      - "wide": one row per cid, columns like precip_01 ... rechg_12
      - "long": MultiIndex (cid, month) with columns precip/runoff/evapo/rechg
    """
    if output_format not in {"wide", "long"}:
        raise ValueError("output_format must be 'wide' or 'long'")

    records = []

    for s in _iter_cell_series_from_outfiles(cell_outfiles):
        df = s.df.copy()
        mask = (df.index.year >= year_from) & (df.index.year <= year_to)
        df = df.loc[mask]
        if df.empty:
            continue

        df["year"] = df.index.year
        df["month"] = df.index.month

        monthly_by_year = (
            df.groupby(["year", "month"])[list(DAILY_COMPONENTS)]
              .sum(numeric_only=True)
              .sort_index()
        )
        if monthly_by_year.empty:
            continue

        if require_full_years:
            tmp = monthly_by_year.reset_index()
            months_count = tmp.groupby("year")["month"].nunique()
            full_years = months_count[months_count == 12].index.values
            monthly_by_year = monthly_by_year.loc[
                monthly_by_year.index.get_level_values(0).isin(full_years)
            ]
            if monthly_by_year.empty:
                continue

        clim = monthly_by_year.groupby(level="month").mean(numeric_only=True).reindex(MONTHS)

        if output_format == "long":
            out = clim.reset_index().rename(columns={"month": "month"})
            out.insert(0, "cid", s.cid)
            records.append(out)
        else:
            row = {"cid": s.cid}
            for m in MONTHS:
                for v in DAILY_COMPONENTS:
                    row[f"{v}_{m:02d}"] = float(clim.loc[m, v]) if pd.notna(clim.loc[m, v]) else np.nan
            records.append(pd.DataFrame([row]))

    if not records:
        return pd.DataFrame()

    if output_format == "long":
        out = pd.concat(records, ignore_index=True)
        out = out.set_index(["cid", "month"]).sort_index()
        return out

    return pd.concat(records, ignore_index=True).set_index("cid")


def save_cells_monthly_climatology_from_daily(cell_outfiles, out_csv, year_from, year_to, require_full_years = True, output_format = "wide"):

    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    df = calc_cells_monthly_climatology_from_daily(
        cell_outfiles=cell_outfiles,
        year_from=year_from,
        year_to=year_to,
        require_full_years=require_full_years,
        output_format=output_format,
    )
    df.to_csv(out_csv, encoding="utf-8")
    return out_csv
