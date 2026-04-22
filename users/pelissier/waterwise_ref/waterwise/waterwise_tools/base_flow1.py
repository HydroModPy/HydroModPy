# -*- coding: utf-8 -*-
"""
Created on Tue Apr 21 14:51:33 2026

@author: pelissierm
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
from waterwise.database_tool import DatabaseTool

repo_root = 'C:/Users/Pelissierm/Hydromodpy/hydromodpy/pyhelp'
sys.path.insert(0, str(repo_root))
from bilan import (
    calc_yearly_streamflow,
    plot_sim_vs_obs_yearly_streamflow,
    plot_streamflow_scatter,
)


def _resolve_area_km2(workdir):
    workdir = Path(workdir)
    shp = workdir.parent / "results_stable" / "geographic" / "watershed.shp"

    gdf = gpd.read_file(shp)
    area_m2 = gdf.to_crs(3035).geometry.area.sum()

    return area_m2 / 1e6


def run_streamflow_validation(site_id, workdir, output_help, output_surf, logger=None):
    try:
        workdir = Path(workdir)
        obs_file = workdir / "observed_streamflow_yearly.csv"

        if not obs_file.exists():
            msg = f"No observed streamflow file for {site_id}"
            if logger:
                logger.info(msg)
            return 0, "no_obs_file"

        obs_qflow = pd.read_csv(obs_file, index_col="years")
        sim_qflow = calc_yearly_streamflow(output_help, output_surf)

        title = f"{site_id} - Débits simulés vs observés"
        plot_sim_vs_obs_yearly_streamflow(
            sim_qflow,
            obs_qflow,
            title,
            figname=workdir / "streamflow_yearly.png",
        )

        plot_streamflow_scatter(
            sim_qflow,
            obs_qflow,
            title,
            figname=workdir / "streamflow_scatter.png",
        )

        return 0, f"ok;nyears={len(obs_qflow)};plots=1"

    except Exception as exc:
        if logger:
            logger.exception("Streamflow validation failed for %s", site_id)
        return 1, f"exception:{type(exc).__name__}"


def export_baseflow(site_id, workdir, logger=None):
    db = DatabaseTool()

    try:
        params = db.get_available_params(site_id).copy()

        if params.empty:
            return 0, "no_params"

        mask = params["mnemonique"].astype(str).str.contains(
            "debit|débit|flow|stream|discharge|runoff",
            case=False, na=False, regex=True)
        params = params.loc[mask].copy()

        if params.empty:
            return 0, "no_streamflow_source"

        params["date_to"] = pd.to_datetime(params["date_to"], errors="coerce")
        params = params.sort_values("date_to", ascending=False)

        collect_point_id = int(params.iloc[0]["collect_point_id"])
        field = int(params.iloc[0]["field"])

        df = db.export_observations(site=site_id, field=field, collect_point_id=collect_point_id)

        if df.empty:
            return 0, f"empty_obs;cp={collect_point_id};field={field}"

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df["q"] = pd.to_numeric(df["daily_avg"], errors="coerce")
        df = df.dropna(subset=["timestamp", "q"]).copy()
        df.loc[df["q"] < 0, "q"] = np.nan

        if df.empty:
            return 0, f"empty_after_cleaning;cp={collect_point_id};field={field}"
        
        #mm/year
        df["q_m3_day"] = (df["q"] / 1000.0) * 86400.0
        #area_km2 = _resolve_area_km2(workdir)
        area_km2 = 39
        area_m2 = area_km2 * 1e6
        df["year"] = df["timestamp"].dt.year

        def stats_year(sub_df):
            sub_df = sub_df.dropna(subset=["q_m3_day"])

            if sub_df.empty:
                return pd.Series({"qtot_obs": np.nan, "qbase_obs": np.nan})

            q25 = np.quantile(sub_df["q_m3_day"], 0.25)
            mean_under = sub_df.loc[sub_df["q_m3_day"] <= q25, "q_m3_day"].mean()
            mean_q = sub_df["q_m3_day"].mean()

            qtot = (mean_q * 365.25) / area_m2 * 1000.0
            qbase = (mean_under * 365.25) / area_m2 * 1000.0

            return pd.Series({"qtot_obs": qtot, "qbase_obs": qbase})

        yearly = df.groupby("year").apply(stats_year).reset_index()
        yearly = yearly.rename(columns={"year": "years"})
        yearly.to_csv(Path(workdir) / "observed_streamflow_yearly.csv", index=False)

        return 0, f"ok;cp={collect_point_id};field={field};nyears={len(yearly)}"

    except Exception as exc:
        if logger:
            logger.exception("Baseflow export failed for %s", site_id)
        return 1, f"exception:{type(exc).__name__}"


if __name__ == "__main__":
    ret, diag = export_baseflow(site_id="_cont",
                                workdir="Z:/HDPY_outputs/historic/_cont/results_pyhelp")

    print("ret =", ret)
    print("diag =", diag)