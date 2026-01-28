# -*- coding: utf-8 -*-
"""
Created on Sun Mar 23 11:45:06 2025

@author: mathi
"""

import re
import pandas as pd
import numpy as np
import os.path as osp
import matplotlib.pyplot as plt

def read_daily_help_output(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    results = {
        'years': [], 'days': [],
        'rain': [], 'runoff': [], 'et': [],
        'leak_first': [], 'leak_last': []
    }
    current_year = None

    for i, line in enumerate(lines):
        if "DAILY OUTPUT FOR YEAR" in line:
            match = re.search(r"\d{4}", line)
            if match:
                current_year = int(match.group())
            continue

        if current_year is not None:
            parts = line.strip().split()
            if len(parts) < 4:
                continue

            try:
                day_str = parts[0].replace('*', '0')
                rain_str = parts[1].replace('*', '0')
                runoff_str = parts[2].replace('*', '0')
                et_str = parts[3].replace('*', '0')

                day = int(day_str)
                rain = float(rain_str)
                runoff = float(runoff_str)
                et = float(et_str)

                leak_first_str = parts[6].replace('*', '0') if len(parts) > 6 else '0'
                leak_last_str  = parts[7].replace('*', '0') if len(parts) > 7 else '0'
                leak_first = float(leak_first_str)
                leak_last  = float(leak_last_str)

                results['years'].append(current_year)
                results['days'].append(day)
                results['rain'].append(rain)
                results['runoff'].append(runoff)
                results['et'].append(et)
                results['leak_first'].append(leak_first)
                results['leak_last'].append(leak_last)

            except ValueError:
                continue

    return results




def calc_area_daily_avg(cellnames, workdir):
    
    COMPONENTS = ['precip', 'runoff', 'evapo', 'rechg']
    all_dfs = []

    for cid in cellnames:
        fpath = osp.join(workdir, "help_input_files", ".temp", f"{cid}.OUT")
        try:
            data = read_daily_help_output(fpath)

            if not data['rain']:
                print(f"Pas de données journalières pour la cellule {cid}.")
                continue

            dates = [
                pd.Timestamp(y, 1, 1) + pd.Timedelta(days=(d - 1))
                for y, d in zip(data['years'], data['days'])
            ]

            df_cell = pd.DataFrame({
                'precip': np.array(data['rain']),
                'runoff': np.array(data['runoff']),
                'evapo':  np.array(data['et']),
                'rechg':  np.array(data['leak_last']),
            }, index=dates)

            all_dfs.append(df_cell)

        except Exception as e:
            print(f" Erreur pour la cellule {cid} : {e}")
            continue

    if not all_dfs:
        raise RuntimeError("Aucune donnée journalière n’a été chargée.")

    # Concat
    df_concat = pd.concat(all_dfs, axis=1)

    # Crée un multi-index de colonnes => (cell, flux)
    multi_cols = []
    cell_index = 0
    for df_cell in all_dfs:
        for comp in COMPONENTS:
            multi_cols.append((cell_index, comp))
        cell_index += 1

    df_concat.columns = pd.MultiIndex.from_tuples(multi_cols)

    # Moyenne spatiale => groupby(level=1).mean()
    df_mean = df_concat.groupby(level=1, axis=1).mean()

    return df_mean


def plot_daily(df_daily_mean, title="Bilan journalier moyen"):

    COMPONENTS = ['precip', 'runoff', 'evapo', 'rechg']
    LABELS = {
        'precip': 'Précipitations',
        'runoff': 'Ruissellement',
        'evapo': 'Évapotranspiration',
        'rechg': 'Recharge'
    }

    fig, ax = plt.subplots(figsize=(9, 5))
    for comp in COMPONENTS:
        if comp in df_daily_mean.columns:
            ax.plot(df_daily_mean.index, df_daily_mean[comp], label=LABELS.get(comp, comp))

    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("mm / jour")
    ax.legend()
    ax.grid(True)
    plt.show()


def calc_area_yearly_avg_from_daily(
    df_daily_mean: pd.DataFrame,
    year_from: int | float = -np.inf,
    year_to: int | float = np.inf,
    return_yearly_series: bool = False,
    full_year_columns: bool = True,
):
 
    if df_daily_mean is None or df_daily_mean.empty:
        raise ValueError("df_daily_mean est vide.")
    if not isinstance(df_daily_mean.index, pd.DatetimeIndex):
        raise TypeError("df_daily_mean doit etre indexe par des dates (DatetimeIndex).")

    years = df_daily_mean.index.year
    mask_years = (years >= year_from) & (years <= year_to)
    df = df_daily_mean.loc[mask_years].copy()
    if df.empty:
        raise ValueError("Aucune donnee dans la plage d'annees demandee.")

    yearly_series = df.groupby(df.index.year).sum(numeric_only=True)
    yearly_series.index.name = 'year'

    mean_interannual = yearly_series.mean(axis=0, numeric_only=True)

    if full_year_columns:
        target_cols = ['precip', 'rechg', 'runoff', 'evapo', 'subrun1', 'subrun2', 'perco']
        mean_interannual = mean_interannual.reindex(target_cols)
        yearly_series = yearly_series.reindex(columns=target_cols)

    if return_yearly_series:
        return mean_interannual, yearly_series
    return mean_interannual


def save_area_yearly_avg_from_daily(
    df_daily_mean: pd.DataFrame,
    out_csv: str,
    year_from: int | float = -np.inf,
    year_to: int | float = np.inf,
):
    mean_interannual = calc_area_yearly_avg_from_daily(
        df_daily_mean,
        year_from=year_from,
        year_to=year_to,
        return_yearly_series=False,
        full_year_columns=True,
    )
    df_out = mean_interannual.to_frame().T
    df_out.index = ['area_yearly_avg']
    df_out.to_csv(out_csv, encoding='utf-8')

