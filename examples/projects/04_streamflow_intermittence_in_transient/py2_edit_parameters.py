"""Charge project.toml en objet Python, change K et Sy, lance le modèle
modifié et le compare au modèle de référence.

    python py2_edit_parameters.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

import hydromodpy as hmp
from hydromodpy.config import HydroModPyConfig

HERE = Path(__file__).resolve().parent

# %% La référence

# Le modèle tel que project.toml le décrit, relancé à chaque exécution (une
# minute). Avec if_exists = "replace", le run précédent part à la corbeille.
reference = hmp.run(HERE / "project.toml")

# %% Le modèle modifié

# from_toml suit les base_config et rend l'objet que `hmp run` valide : chaque
# clé du TOML y devient un attribut.
cfg = HydroModPyConfig.from_toml(HERE / "project.toml")
K = cfg.flow.param["K"].field
Sy = cfg.flow.param["Sy"].field
print(f"project.toml : K = {K.value} {K.unit}, Sy = {Sy.value}")

# Chaque affectation est validée : une unité autre que celle du champ, ou un
# nom de figure inconnu, lève une erreur tout de suite.
K.value = 2e-5
Sy.value = 0.02

# Un essai n'a pas besoin de toutes les figures ni des exports. On remplace la
# liste entière : un append sur la liste échapperait à la validation.
cfg.display.figures = ["hydrograph_log_nse", "seepage_map"]
cfg.export = []

# La config complète du run est gardée dans runs/<nom du run>/config.toml.
variant = hmp.run(cfg, name="nancon_variant")
print(variant.name)

# %% Comparaison

# Scores du catalogue, sur les 36 mois du run.
scores = pd.concat(
    {
        run.name: run.metrics.query("station_id == 'NANCON'").set_index("metric_name")["value"]
        for run in (reference, variant)
    },
    axis=1,
)
print(scores.loc[["nse", "log_nse", "kge", "pbias"]].round(3))

months = reference.periods.edges[:-1]
q_obs = hmp.read(reference, "discharge_obs").resample("MS").mean().reindex(months)
in_catchment = reference.catchment_mask.ravel()
cell_km2 = reference.grid.cell_size**2 / 1e6

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, constrained_layout=True)
ax1.plot(months, q_obs, color="k", lw=1, label="jaugé")
for run, color in [(reference, "tab:blue"), (variant, "tab:red")]:
    label = f"{run.name} (K = {run.params['K']:.0e} m/s, Sy = {run.params['Sy']})"
    ax1.plot(months, hmp.read(run, "discharge").to_numpy(), color=color, label=label)
    seepage = hmp.read(run, "seepage_mask").to_numpy() > 0
    ax2.plot(months, (seepage & in_catchment).sum(axis=1) * cell_km2, color=color)
ax1.set_yscale("log")
ax1.set_yticks([0.2, 0.5, 1, 2], ["0.2", "0.5", "1", "2"])
ax1.minorticks_off()
ax1.set_ylabel("débit (m³/s)")
ax1.legend(fontsize="small")
ax2.set_ylabel("surface suintante (km²)")

# Une figure qui compare deux runs n'appartient à aucun des deux : share/figures.
out = HERE / "share" / "figures" / "reference_vs_variant.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=150)
print(out)
plt.show()
