# -*- coding: utf-8 -*-
"""
Created on Thu Feb  5 13:08:47 2026

@author: pelissierm
"""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


SEASON = ["DJF", "JJA"]
agg = ["sum", "mean"]



@dataclass(frozen=True)
class PredictionGridSeries:
    time: pd.DatetimeIndex      
    lat: np.ndarray             
    lon: np.ndarray             
    values: np.ndarray          



def read_csv_prediction(path):
    
    path = Path(path)
    df = pd.read_csv(path)
    
    if str(df.columns[0]).strip().lower() == "latitude":
        raw_cols = list(df.columns[1:])
        lat = np.array([float(str(c)) for c in raw_cols], dtype=float)
        lon = df.iloc[0, 1:].to_numpy(dtype = float)
        
        time = pd.to_datetime(df.iloc[1:, 0].to_numpy(dtype=float))
        
        values = df.iloc[1:, 1:].to_numpy(dtype=float)
        
        return PredictionGridSeries(time, lat, lon, values)
    
    else:
        lat = df.iloc[0, 1:].to_numpy(dtype=float)
        lon = df.iloc[1, 1:].to_numpy(dtype=float)
        
        time = pd.to_datetime(df.iloc[2:, 0], errors="raise")
        values = df.iloc[2:, 1:].to_numpy(dtype=float)
        
        return PredictionGridSeries(time, lat, lon, values)


#%%Metrics 
def spatial_mean(values):
    return np.nanmean(values, axis=1)


def _season_year_mask(time, season):
    t = pd.to_datetime(time)

    if isinstance(t, pd.Series):
        y = t.dt.year.to_numpy(dtype=int)
        m = t.dt.month.to_numpy(dtype=int)
    else:
        y = np.asarray(t.year, dtype=int)
        m = np.asarray(t.month, dtype=int)

    if season == "DJF":
        mask = (m == 12) | (m == 1) | (m == 2)
        season_year = np.where(m == 12, y + 1, y)
    elif season == "JJA":
        mask = (m == 6) | (m == 7) | (m == 8)
        season_year = y
    else:
        raise ValueError(f"Unknown season: {season}")

    return pd.Index(season_year[mask], name="season_year"), mask

        

def seasonal_aggregation(time, series, season: SEASON, agg: agg):
    idx, mask = _season_year_mask(time, season)
    s = pd.Series(series[mask], index=idx)
    
    if agg == "sum":
        return s.groupby(level=0).sum()
    if agg == "mean":
        return s.groupby(level=0).mean()


def window_mean(seasonal, start_date, end_date):
    start_y = pd.Timestamp(start_date).year
    end_y = pd.Timestamp(end_date).year
    w = seasonal[(seasonal.index >=start_y) & (seasonal.index <= end_y)]
    
    return float(w.mean())


def relative_change_percent(future, reference):
    return 100.0 * (future - reference) / reference
    
#%%Classification (narratives)

"""
- C (contrastée) : été très sec ET hiver très humide
- S (sèche) : été très sec ET hiver pas très humide
- L (limitée) : le reste

"""
def classification_explore2(df, summer_col="dP_JJA", winter_col="dP_DJF", summer_dry_threshold=-20.0, winter_wet_threshold=20.0):
    summer_dry = df[summer_col] <= summer_dry_threshold
    winter_wet = df[winter_col] >= winter_wet_threshold

    out = pd.Series(index=df.index, dtype="object")
    out[summer_dry & winter_wet] = "C"
    out[summer_dry & ~winter_wet] = "S"
    out[~summer_dry] = "L"
    return out
    
    
def classification_plot(path):
    from waterwise.plots.plots_projection import classification_plot as _classification_plot

    return _classification_plot(path)

