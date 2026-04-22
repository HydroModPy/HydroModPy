from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sqlalchemy as db

sys.path.append(str(Path(__file__).resolve().parents[2]))

from waterwise.database_tool import DatabaseTool
from cerra.toolbox_newFuns_cerra_dev import generate_debiaser, evaluate_debias
from waterwise.pipelines.climate import _fixed_pyhelp_csv, _read_raw_pyhelp_csv


DB_NAMES = {
    "precip": "total_precipitation",        
    "airtemp": "air_temperature" 
}


def to_series(df):
    if df is None or df.empty:
        return pd.Series(dtype=float)
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce").dt.tz_localize(None).dt.normalize()
    df["daily_avg"] = pd.to_numeric(df["daily_avg"], errors="coerce")
    df = df.dropna(subset=["timestamp", "daily_avg"])
    return df.groupby("timestamp")["daily_avg"].mean().sort_index()


def first_point(db_tool, site_id, field):
    cp_id = int(db_tool.get_available_params(site_id).loc[lambda x: x["field"] == field, "collect_point_id"].dropna().iloc[0])
    engine = db_tool.get_engine()
    try:
        geom = pd.read_sql(db.text("""SELECT ST_AsText(geom) 
                                   AS geom 
                                   FROM sites.t_collect_points 
                                   WHERE id_collect_point = :cp_id"""), 
                                   engine, params={"cp_id": cp_id}).iloc[0]["geom"]
    finally:
        engine.dispose()
    lon, lat = geom.replace("POINT(", "").replace(")", "").split()
    return cp_id, float(lat), float(lon)


def read_cerra_ref(ref_csv, j):
    _, _, dates, vals = _read_raw_pyhelp_csv(ref_csv, decimals=2)
    
    ref = pd.Series(pd.to_numeric(vals.iloc[:,j], errors="coerce").to_numpy(), index=pd.to_datetime(dates, errors="coerce"))
    ref.index = ref.index.normalize()
    
    return ref.groupby(ref.index).mean().dropna().sort_index()


def debias_climate(site_id, workdir, var, method, clip_min=None, histo = True):
    db_tool = DatabaseTool()
    workdir = Path(workdir)

    in_csv = workdir / f"{var}_input_data.csv"
    out_csv = workdir / f"{var}_input_data_debiased.csv"

    # BD params (for sites infomrations)
    params = db_tool.get_available_params(site_id)

    db_name = DB_NAMES[var].lower()
    hit = params.loc[params["mnemonique"].astype(str).str.lower() == db_name]

    field = int(hit.iloc[0]["field"])
    cp_id, obs_lat, obs_lon = first_point(db_tool, site_id, field)
    
    print(f"collect point: {cp_id}")

    # read csv
    lat, lon, dates, vals = _read_raw_pyhelp_csv(in_csv, decimals=1)
    lat = pd.to_numeric(pd.Series(lat), errors="coerce")
    lon = pd.to_numeric(pd.Series(lon), errors="coerce")
    valid = lat.notna() & lon.notna()
    lat = lat[valid].tolist()
    lon = lon[valid].tolist()
    vals = vals.loc[:, valid.values].reset_index(drop=True)
    
    # Observations
    obs = to_series(db_tool.export_observations(site_id, field, collect_point_id=cp_id))
    
    j = int(np.argmin((np.asarray(lat) - obs_lat) ** 2 + (np.asarray(lon) - obs_lon) ** 2))
    
    raw = pd.Series(pd.to_numeric(vals.iloc[:, j], errors="coerce").to_numpy(), index=pd.to_datetime(dates, errors="coerce"))
    raw.index = raw.index.normalize()
    raw = raw.groupby(raw.index).mean().dropna().sort_index()
    
    if obs.empty:
        if histo:
            raise ValueError("No observations found.")
        ref_dir = sys.path.append(str(Path(workdir).resolve().parents[3]))
        ref_csv = Path(ref_dir, "waterwise", site_id, "results_pyhelp", f"{var}_input_data.csv")
        ref = read_cerra_ref(ref_csv, j)
        overlap = pd.concat([ref.rename("ref"), raw.rename("raw")], axis=1, join="inner").dropna()
    else:
        ref = obs
        overlap = pd.concat([obs.rename("obs"), raw.rename("raw")], axis=1, join="inner").dropna()
    
    #overlap = pd.concat([obs.rename("obs"), raw.rename("raw")], axis=1, join="inner").dropna()
    if len(overlap) < 30:
        raise ValueError("not enough overlap")
        
    #debiaser
    debiaser = generate_debiaser(overlap["obs"].to_numpy(dtype=float), overlap["raw"].to_numpy(dtype=float), method=method)
    
    #applying debiaser
    arr = vals.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, copy=True)
    
    for k in range(arr.shape[1]):
        if k % 50 == 0:
            print(f"{var}: pixel {k}/{arr.shape[1]}")
        mask = np.isfinite(arr[:,k])
        
        if method == "QuantileMappingDelta":
            arr[mask,k] = [debiaser(v, arr[mask, k]) for v in arr[mask, k]]
        else:
            arr[mask,k] = [debiaser(v) for v in arr[mask, k]]

    corrected = pd.DataFrame(arr)
    if clip_min is not None:
        corrected = corrected.clip(lower=clip_min)
    
    if var == "precip":
        corrected = corrected.mask(corrected < 1e-2, 0.0)
        
    #stats
    
    raw_corr = pd.Series(corrected.iloc[:, j].to_numpy(), index=pd.to_datetime(dates, errors="coerce"))
    check = pd.concat([obs.rename("obs"), raw.rename("raw"), raw_corr.rename("corr")], axis=1, join="inner").dropna()
    
    stats = evaluate_debias(
        check["obs"].to_numpy(dtype=float),
        check["raw"].to_numpy(dtype=float),
        check["corr"].to_numpy(dtype=float)        
        )

    print(check["obs"].mean())
    print(check["raw"].mean())
    print(check["corr"].mean())
    #plotting
    plot_debias_scatter(check, stats)

    _fixed_pyhelp_csv(out_csv, lat, lon, dates, corrected.round(2))
    print(f"\n{var}: done --> {out_csv}")
    

def plot_debias_scatter(check, stats):
    xymax = check.max().max()
    xymin = check.min().min()

    plt.figure(figsize=(6, 6))
    
    # plt.scatter(check["obs"], check["raw"], s=10, alpha=0.4, label="raw")
    # plt.scatter(check["obs"], check["corr"], s=10, alpha=0.4, label="corrected", color="green")
    
    plt.loglog(check["obs"], check["raw"], ".", alpha=0.4, label="raw")
    plt.loglog(check["obs"], check["corr"], ".", alpha=0.4, label="corrected", color="green")

    plt.plot([xymin, xymax], [xymin, xymax], "k--", label="1:1")

    plt.xlabel("Observations")
    plt.ylabel("Model")
    plt.legend(bbox_to_anchor=(1.1, 1), loc='upper right')

    plt.text(
        0.02, 0.98,
        f"RMSE raw = {stats['rmse_raw']:.2f}\n"
        f"RMSE corr = {stats['rmse_corr']:.2f}\n"
        f"Bias raw = {stats['diff_raw_mean']:.2f}\n"
        f"Bias corr = {stats['diff_corr_mean']:.2f}",
        transform=plt.gca().transAxes,
        va="top"
    )

    plt.tight_layout()
    plt.show()


def plot_debias_hist(check, stats):
    plt.figure(figsize=(6,4))
      
    plt.hist(check["raw"], bins=10, alpha=0.5, label="raw")
    plt.hist(check["corr"], bins=10, alpha=0.5, label="corr")
    
    plt.xlabel("Value")
    plt.ylabel("Frequency")
    plt.legend()
    
    plt.text(
        0.02, 0.98,
        f"RMSE raw = {stats['rmse_raw']:.2f}\n"
        f"RMSE corr = {stats['rmse_corr']:.2f}\n"
        f"Bias raw = {stats['diff_raw_mean']:.2f}\n"
        f"Bias corr = {stats['diff_corr_mean']:.2f}",
        transform=plt.gca().transAxes,
        va="top"
    )

    plt.tight_layout()
    plt.show()


def debias_precip_and_airtemp(site_id, workdir):
    debias_climate(site_id, workdir, "precip", "LinearScaling",  clip_min=0.0, histo=True)
    debias_climate(site_id, workdir, "airtemp", "LinearScaling", histo=False)


if __name__ == "__main__":
    debias_precip_and_airtemp(
        site_id="_rech",
        #workdir=Path('Z:/HDPY_outputs/prediction/rech/_CESM2')
        workdir=Path('Z:/HDPY_outputs/historic/_rech/results_pyhelp')
    )