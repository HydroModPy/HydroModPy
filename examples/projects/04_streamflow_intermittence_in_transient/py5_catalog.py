"""Relit les runs déjà calculés du projet, sans rien relancer, pour en
tirer ce que les TOML n'avaient pas demandé.

Il faut au moins un run de project.toml :

    hmp run project.toml
    python py5_catalog.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

import hydromodpy as hmp
from hydromodpy.display import names

HERE = Path(__file__).resolve().parent

# %% Le catalogue

# L'index du projet, .hmp/index.duckdb, ouvert en lecture seule : le script
# ne le modifie pas.
cat = hmp.open(HERE)

# Une ligne par run. Ceux qu'un if_exists = "replace" a remplacés sont à la
# corbeille, avec le statut "trashed".
frame = cat.frame
done = frame[frame["status"] == "completed"]
print(done[["name", "flow_regime", "n_timesteps", "duration_s"]].to_string(index=False))

# Les scores au débit de la jauge, pour tous les runs transitoires. Attention
# en les comparant : les runs journaliers n'ont ni la même période ni le même
# pas que les runs mensuels.
transient = cat.find(status="completed", flow_regime="transient")
scores = pd.DataFrame(
    {
        metric: transient.compare(metric, station="NANCON").set_index("name")["value"]
        for metric in ["nse", "log_nse", "kge"]
    }
)
print(scores.sort_values("nse", ascending=False).round(3))

# %% Un run

# Le dernier run de project.toml. find ne rend que les runs vivants, du plus
# récent au plus ancien. cat["nancon_intermittence_mf6"] viserait le run qui
# porte exactement ce nom, la toute première version, même à la corbeille.
run = cat.find(name_stem="nancon_intermittence_mf6")[0]
print(run.name, run.params)

# Les figures du catalogue se dessinent aussi depuis Python, avec les mêmes
# options que [display.overrides]. names() les liste toutes.
print(len(names()), "figures :", ", ".join(names()))

# La carte de suintement du mois le plus humide et du mois le plus sec, sur
# tout le maillage plutôt que sur le seul bassin.
figures = HERE / "runs" / run.name / "figures"
for date in ["2001-01-15", "2002-10-15"]:
    fig = hmp.figure(run, "seepage_map", time=date, extent="mesh")
    fig.savefig(figures / f"seepage_map_{date[:7]}.png", dpi=150)
    plt.close(fig)

# Une figure rendue est une figure matplotlib comme une autre : on peut la
# reprendre avant de l'enregistrer.
fig = hmp.figure(run, "hydrograph_sim_obs", log_y=True)
ax = fig.axes[0]
ax.axvspan(pd.Timestamp("2000-01-01"), pd.Timestamp("2001-01-01"), color="0.9", zorder=0)
ax.text(pd.Timestamp("2000-02-01"), 0.95, "mise en route", transform=ax.get_xaxis_transform())
fig.savefig(figures / "hydrograph_spinup.png", dpi=150)
plt.close(fig)

# %% Un export à la demande

# Les états de janvier 2001, en GeoTIFF, écrits dans share/<run>/ avec ceux
# que le TOML demande déjà.
for path in hmp.export(run, ["watertable_depth", "seepage_mask"], time="2001-01-15"):
    print(path)
