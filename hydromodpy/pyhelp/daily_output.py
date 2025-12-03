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

from hydromodpy.tools import get_logger

logger = get_logger(__name__)

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
                logger.warning("No daily HELP data available for cell %s", cid)
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

        except Exception:
            logger.exception("Failed processing daily HELP outputs for cell %s", cid)
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
    # groupby across columns via transpose to avoid deprecated axis param
    df_mean = df_concat.T.groupby(level=1).mean().T

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
