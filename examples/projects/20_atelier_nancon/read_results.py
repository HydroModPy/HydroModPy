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

# hmp.open renvoie un SimulationCatalog adosse a catalog.duckdb.
catalog = hmp.open(here)

# Tous les runs nommes. named_only=True ecarte les lignes techniques :
# runs ecrases dont le nom est efface, et snapshots de config effective
# au nom pointe.
sims = catalog.list_simulations(named_only=True)
# print(sims.columns)
print(sims[["name", "solver", "status", "n_timesteps", "ended_at"]].to_string(index=False))

# Prendre le run transient NWT. find() filtre sur le nom du catalog, qui
# est le nom de fichier TOML (ici "sim_transient_nwt").
run = list(catalog.find(name="sim_transient_nwt"))[0]
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

# Une serie temporelle : le debit simule a l'exutoire, une valeur par
# periode de stress mensuelle, renvoyee en Series pandas.
discharge = run.timeseries("discharge")
print(f"debit : {len(discharge)} pas, moyenne {discharge.mean():.3f} m3/s")

# Tracer l'hydrogramme et la distribution des charges, sauvegarder a cote du
# projet.
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
discharge.plot(ax=ax1, color="tab:blue")
ax1.set_title("Debit simule")
ax1.set_ylabel("m3/s")
ax2.hist(head.ravel(), bins=40, color="tab:green")
ax2.set_title("Nappe finale")
ax2.set_xlabel("charge (m)")
fig.tight_layout()
out = here / "read_results_output.png"
fig.savefig(out, dpi=120)
print("\nfigure sauvee :", out)

run = list(catalog.find(name="sim_transient_nwt"))[0]
