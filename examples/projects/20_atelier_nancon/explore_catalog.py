# Parcourir le catalog et le cache de donnees d'entree depuis Python.
#
#   python explore_catalog.py

from pathlib import Path

import hydromodpy as hmp

here = Path(__file__).resolve().parent
workspace = here.parents[1]  # examples/  (la racine du workspace)

# 1) The index of the project: list every run, then filter.
proj = hmp.open(here)
sims = proj.store.frame
sims = sims[sims["name"].notna()]
print("tous les runs du projet :")
print(sims[["name", "solver", "status"]].to_string(index=False))

mf6 = sims[sims["solver"] == "modflow6"]
print("\nseulement les runs MODFLOW 6 :")
print(mf6[["name", "status"]].to_string(index=False))

# 2) Le cache de donnees d'entree (data/cache.duckdb). Ouvert sur le
#    workspace pour que le cache d'inputs (examples/data/cache.duckdb)
#    soit dans la portee.
from hydromodpy.catalog import InputsNamespace

inputs_ns = InputsNamespace(workspace)
inputs = inputs_ns.list()
print("\nentrees du cache d'inputs :", len(inputs))
if len(inputs):
    print("colonnes :", list(inputs.columns))
    print(inputs.head(15).to_string(index=False))
inputs_ns.close()
