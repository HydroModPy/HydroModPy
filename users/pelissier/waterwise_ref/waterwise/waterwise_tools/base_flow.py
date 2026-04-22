# -*- coding: utf-8 -*-
"""
Created on Tue Apr 21 08:42:54 2026

@author: pelissierm
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
repo_root = Path(__file__).resolve().parents[1]   
sys.path.insert(0, str(repo_root))
from waterwise.database_tool import DatabaseTool



def export_baseflow(site_id, workdir, collect_point_id, area_km2, field=12):
    db = DatabaseTool()
    
    df = db.export_observations(site=site_id, field=field, collect_point_id=collect_point_id)
    
    if df.empty:
        print(f"No observed streamflow for {site_id}, cp={collect_point_id}, field={field}")
        return None
            
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["q"] = pd.to_numeric(df["daily_avg"], errors="coerce")
    df = df.dropna(subset=["timestamp", "q"]).copy()
    df.loc[df["q"] < 0, "q"] = np.nan
    
    #m3/s ????
    df["q_m3_day"] = df["q"]*86400
    
    area_m2 = float(area_km2) * 1e6
    df["year"] = df["timestamp"].dt.year
    
    def stats_year(sub_df):
        sub_df = sub_df.dropna(subset=["q_m3_day"])
        
        if sub_df.empty:
            return pd.Series({"qtot_obs": np.nan, "qbase_obs": np.nan})
        
        q25 = np.quantile(sub_df["q_m3_day"], 0.25)
        mean_under = sub_df.loc[sub_df["q_m3_day"] <= q25, "q_m3_day"].mean()
        mean_q = sub_df["q_m3_day"].mean()
        
        #mm/year
        qtot = (mean_q * 365.25)/area_m2*1000.0
        qbase = (mean_under*365.25)/area_m2*1000.0
        
        return pd.Series({"qtot_obs": qtot, "qbase_obs": qbase})
        
    yearly = df.groupby("year").apply(stats_year).reset_index()
    yearly = yearly.rename(columns={"year":"years"})
    
    yearly.to_csv(f"{workdir}/observed_streamflow_yearly.csv", index=False)
    
    
    
if __name__ == "__main__":
    workdir = 'Z:/HDPY_outputs/historic/_cont/results_pyhelp'
    site_id = "_cont"
    collect_point_id = 21
    area_km2 = 60.17
    
    export_baseflow(site_id, workdir, collect_point_id, area_km2)
