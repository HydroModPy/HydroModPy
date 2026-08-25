# 04 - Streamflow intermittence in transient

Bassin du Nançon (Bretagne, EPSG:2154) extrait du MNT régional 75 m par
accrochage d'exutoire. Écoulement souterrain **transitoire mensuel** sur
trois ans (2000-2002), résolu avec **MODFLOW 6**, forcé par une recharge et
un ruissellement mensuels observés.

Le thème est l'intermittence : quand la recharge oscille entre hivers
humides et étés secs, la nappe monte et descend, donc les mailles de
suintement et le réseau actif simulé s'étendent et se contractent au fil de
l'année.

## Lancer

```bash
hmp run examples/projects/04_streamflow_intermittence_in_transient/project.toml

# intermittence saisonnière : suintement aux mois extrêmes, via l'API Python
python examples/projects/04_streamflow_intermittence_in_transient/run_manual.py

hmp viz gallery examples/projects/04_streamflow_intermittence_in_transient/project.toml
```

Durée : environ 15 s (36 pas de temps, solveur COMPLEX).

## Données

| Fichier | Famille | Rôle |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | MNT régional 75 m (couvre le Nançon) |
| `recharge/recharge_custom_NANCON_*.csv` | recharge | recharge mensuelle observée (mm/j) |
| `runoff/runoff_custom_NANCON_*.csv` | runoff | ruissellement mensuel, ajouté au débit de base |

## Intermittence

`run_manual.py` compte les mailles de suintement à chaque mois. Sur cette
période, le réseau humide passe de ~450 mailles (mois sec) à ~1670 (mois
humide) : environ **1200 mailles s'allument et s'éteignent** au fil du
temps. Ce sont les tronçons intermittents ; le cœur qui reste actif tout du
long est le réseau pérenne. Le script rend `seepage_map` au mois le plus
humide et au plus sec (même figure, deux `timestep`).

## Figures

| Figure | Ce qu'elle montre |
|---|---|
| `watershed_id_card` | carte d'identité du bassin |
| `mesh_map` | grille du solveur |
| `piezometric_map` | altitude de la nappe (dernier pas) |
| `watertable_depth_map` | profondeur de nappe + suintement |
| `seepage_map` | zones de suintement (variables dans le temps) |
| `simulated_active_network` | réseau drainant actif |
| `hydrograph` | débit simulé au cours du temps |
| `flux_timeseries` | bilan hydrique par pas de temps |
| `cross_section` | coupe topographie / nappe |
| `water_budget` | bilan cumulé par composante |

## Dette technique

Le script legacy calculait un `persistency_index` (fraction du temps où une
maille est active) et des cartes d'intermittence mensuelle/hebdomadaire/
quotidienne. Ces **champs agrégés dans le temps n'existent pas encore** comme
champs canoniques v1. En attendant, l'intermittence se lit via la dynamique
saisonnière du suintement (ci-dessus) plutôt que via un indice unique. Un
champ `persistency_index` agrégé serait le complément naturel.
