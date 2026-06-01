# Parcourir le catalog et le cache de donnees d'entree depuis Python.
#
#   python explore_catalog.py

from pathlib import Path

import hydromodpy as hmp

here = Path(__file__).resolve().parent
workspace = here.parents[1]  # examples/  (la racine du workspace)

# 1) Le catalog du projet : lister tous les runs, puis filtrer.
catalog = hmp.open(here)
sims = catalog.list_simulations()
sims = sims[sims["name"].notna()]
print("tous les runs du projet :")
print(sims[["name", "solver", "status"]].to_string(index=False))

mf6 = sims[sims["solver"] == "modflow6"]
print("\nseulement les runs MODFLOW 6 :")
print(mf6[["name", "status"]].to_string(index=False))

# 2) La facade V1 sur les trois portees DuckDB : simulations, inputs
#    (cache de donnees), projects. Ouverte sur le workspace pour que le
#    cache d'inputs (examples/data/cache.duckdb) soit dans la portee.
with hmp.open_catalog(workspace) as cat:
    inputs = cat.inputs.list()
    print("\nentrees du cache d'inputs :", len(inputs))
    if len(inputs):
        print("colonnes :", list(inputs.columns))
        print(inputs.head(15).to_string(index=False))
