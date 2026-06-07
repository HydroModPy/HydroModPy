# Comparer la meme physique resolue par MODFLOW-NWT et MODFLOW 6.
#
# Lancer d'abord les deux cas permanents :
#   hmp run sim_steady_nwt.toml
#   hmp run sim_steady_mf6.toml
#   python compare_solvers.py

from pathlib import Path

import numpy as np

import hydromodpy as hmp

here = Path(__file__).resolve().parent
catalog = hmp.open(here)

nwt = list(catalog.find(name="sim_steady_nwt"))[0]
mf6 = list(catalog.find(name="sim_steady_mf6"))[0]

# Les deux runs utilisent des grilles differentes : NWT garde la
# resolution native du DEM, MF6 reechantillonne ici a 80 x 80. On compare
# donc des resumes, pas des mailles une a une.
print("NWT :", nwt.sim_id[:8], "|", nwt.field("head", -1).size, "mailles")
print("MF6 :", mf6.sim_id[:8], "|", mf6.field("head", -1).size, "mailles")

# Table de comparaison de metriques depuis le catalog. Les colonnes sont
# les deux sim ids.
table = hmp.compare_pair(nwt.sim_id, mf6.sim_id, workspace=here)
print("\ncomparaison des metriques :")
print(table.to_string())

# Statistiques de charge cote a cote.
print("\nresume des charges :")
for run in (nwt, mf6):
    h = run.field("head", timestep=-1).ravel()
    print(
        f"  {run.solver:<12} moyenne {np.nanmean(h):.2f} m  min {np.nanmin(h):.2f}  max {np.nanmax(h):.2f}"
    )
