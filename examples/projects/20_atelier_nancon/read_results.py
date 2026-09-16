# Lire un resultat de simulation dans le catalog du projet et le tracer.
#
# Les sorties d'un run atterrissent a cote du projet : catalog.duckdb
# porte les metadonnees, simulations/<run>.zarr.zip les champs spatiaux,
# et simulations/<run>.parquet/ les series temporelles et les bilans.
#
# Lancer d'abord une simulation, puis ce script :
#   hmp run sim_transient_nwt.toml
#   python read_results.py

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

import hydromodpy as hmp

here = Path(__file__).resolve().parent

# hmp.open renvoie un Catalog adosse a catalog.duckdb.
catalog = hmp.open(here)

# Tous les runs nommes. named_only=True ecarte les lignes techniques :
# runs ecrases dont le nom est efface, et snapshots de config effective
# au nom pointe.
sims = catalog.list_simulations(named_only=True)
# print(sims.columns)
print(sims[["name", "solver", "status", "n_timesteps", "ended_at"]].to_string(index=False))

# Prendre le run transient NWT. find() filtre sur le nom du catalog, qui
# est [simulation].name dans le TOML (ici "transient_nwt"), pas le nom de
# fichier.
run = list(catalog.find(name="transient_nwt"))[0]
print("\nrun choisi :", run.name, "|", run.solver, "|", run.n_timesteps, "pas de temps")

# Valeurs des parametres actifs enregistrees pour ce run.
print("\nparametres :")
print(run.parameters)

# Les champs spatiaux disponibles pour ce run, tous lisibles via run.field().
print("\nchamps disponibles :", run.array.list_fields())

# Un champ spatial : la nappe finale, en tableau plat sur les mailles
# actives (forme [couche, n_mailles]).
head = run.field("head", timestep=-1)
print(f"\ncharge : {head.size} mailles, min {np.nanmin(head):.2f} m, max {np.nanmax(head):.2f} m")

# Bilan de masse global, une ligne par periode de stress mensuelle.
# MODFLOW-NWT n'alimente pas encore la table timeseries "discharge" dans ce
# checkout (budgets par composante non extraits) ; total_in du bilan est la
# serie qui marche partout, quel que soit le solveur.
mass_balance = run.mass_balance
total_in = mass_balance.set_index("timestep")["total_in"]
print(f"bilan : {len(total_in)} pas, entrees moyennes {total_in.mean():.3f} m3/s")

# Tracer le bilan et la distribution des charges, sauvegarder a cote du
# projet.
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
total_in.plot(ax=ax1, color="tab:blue")
ax1.set_title("Bilan - entrees totales")
ax1.set_ylabel("m3/s")
ax2.hist(head.ravel(), bins=40, color="tab:green")
ax2.set_title("Nappe finale")
ax2.set_xlabel("charge (m)")
fig.tight_layout()
out = here / "read_results_output.png"
fig.savefig(out, dpi=120)
print("\nfigure sauvee :", out)
