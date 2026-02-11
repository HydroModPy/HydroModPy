from __future__ import annotations

import logging
import os

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.dates import DateFormatter


def plot_volume_comparison(
    dam_df: pd.DataFrame,
    timeseries_df: pd.DataFrame | None,
    simulations_folder: str,
    model_name: str,
    freq_input: str,
    lake_id: str,
) -> None:
    if timeseries_df is None:
        logging.warning("Pas de séries simulées disponibles pour la comparaison.")
        return

    target_col = f"{lake_id}_level"
    if target_col not in timeseries_df.columns:
        logging.warning("Colonne absente: %s", target_col)
        logging.warning("Colonnes disponibles: %s", ", ".join(timeseries_df.columns))
        return

    observed = dam_df["cheze_lvl"]
    simulated = timeseries_df[target_col]

    common_dates = observed.index.intersection(simulated.index)
    if common_dates.empty:
        logging.warning("Aucune date commune entre observé et simulé.")
        return

    observed = observed.loc[common_dates]
    simulated = simulated.loc[common_dates]

    plt.figure(figsize=(12, 6))
    plt.plot(observed.index, observed, "b-", linewidth=2, label="Niveau observé")
    plt.plot(simulated.index, simulated, "r--", linewidth=2, label="Niveau simulé")

    plt.xlabel("Date", fontsize=12)
    plt.ylabel("Niveau (m)", fontsize=12)
    plt.title("Comparaison des niveaux du réservoir Chézé", fontsize=14)
    plt.legend(fontsize=12)
    plt.grid(True, linestyle="--", alpha=0.7)

    if freq_input in {"D", "W"}:
        plt.gca().xaxis.set_major_formatter(DateFormatter("%d-%m-%Y"))
    plt.gcf().autofmt_xdate()

    plt.text(
        0.01,
        0.01,
        f"Modèle: {model_name}",
        transform=plt.gca().transAxes,
        fontsize=8,
        verticalalignment="bottom",
    )

    plt.tight_layout()

    output_dir = os.path.join(simulations_folder, model_name, "_figures")
    os.makedirs(output_dir, exist_ok=True)
    plt.savefig(os.path.join(output_dir, "volume_comparison.png"), dpi=300)
    plt.close()
