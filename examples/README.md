# HydroModPy — exemples

Suite d'exemples alignés sur l'API **v0.6** :

- CLI `hmp` (`hmp run`, `hmp calibrate`, `hmp list`, `hmp show`, …).
- API Python `import hydromodpy as hmp` (`hmp.Project`, `hmp.Run`,
  `hmp.run`, `hmp.calibrate`, `hmp.open`).
- Stockage unifié via `SimulationCatalog` (DuckDB + Zarr).

`examples/` est un **workspace HydroModPy scaffolded**. Ses projets
vivent sous [`projects/`](projects/) et partagent les [données
d'entrée](data/) et la base `hydromodpy.duckdb` via la résolution
binaire de la v0.6.

## Prérequis

```bash
conda create -n hmp python=3.13
conda activate hmp
pip install -e .
```

## Données partagées

Le dossier [`data/`](data/) contient les données d'entrée partagées
par plusieurs exemples (DEM armoricain, hydrographie, BRGM, SIM2 Météo-
France, etc.) ainsi qu'un `cache.duckdb` local. Les chemins relatifs
dans les TOML d'exemple y pointent via `../../data/...`.

## Index

| # | Dossier | Titre | Solveur | Durée | Réseau |
|---|---|---|---|---|---|
| 00 | [`projects/00_getting_started/`](projects/00_getting_started/) | Aquifère Dupuit synthétique | MODFLOW-NWT | ~20 s | non |
| 01 | [`projects/01_calibration/`](projects/01_calibration/) | Calibration Optuna sur K | MODFLOW-NWT | ~1 min | non |
| 02 | [`projects/02_nancon_watershed/`](projects/02_nancon_watershed/) | Bassin du Nançon (MODFLOW-NWT) | MODFLOW-NWT | ~5 min | possible |
| 03 | [`projects/03_canut_watershed/`](projects/03_canut_watershed/) | Bassin du Canut (config expert) | MODFLOW-NWT | ~5 min | possible |
| 04 | [`projects/04_data_overview/`](projects/04_data_overview/) | Carte d'identité d'un bassin | — | ~1 min | oui |
| 05 | [`projects/05_nancon_data_overview/`](projects/05_nancon_data_overview/) | Overview complet Nançon | — | ~2 min | oui |
| 06 | [`projects/06_vire_selune/`](projects/06_vire_selune/) | Vire & Sélune — MF6 et NWT | MF6 / NWT | ~10 min | possible |
| 07 | [`projects/07_mesh_gallery/`](projects/07_mesh_gallery/) | Galerie de maillages (bundles) | — | instantané | non |
| 08 | [`projects/08_mesh_viewer/`](projects/08_mesh_viewer/) | Visualisation de bundles de maillage | — | instantané | non |
| 09 | [`projects/09_capability_gallery/`](projects/09_capability_gallery/) | Figures de référence (gallery statique) | — | — | non |

## Ordre de lecture recommandé

1. **00_getting_started** — structure minimale d'un `project.toml`,
   premier run, découverte du catalogue.
2. **01_calibration** — bloc `[calibration]`, API `hmp.calibrate`,
   `save_runs` (`best_n` / `all`).
3. **04_data_overview** — workflow « données seulement » (sans
   simulation) pour inventorier ce que charge le launcher.
4. **02_nancon_watershed** — premier bassin réel, Nançon (~110 km²).
5. **03_canut_watershed** — variante plus riche (config expert
   `config_expert_generated.toml`).
6. **06_vire_selune** — comparaison régime permanent / transitoire,
   MODFLOW-NWT vs MODFLOW 6, maillage régulier vs irrégulier.
7. **07_mesh_gallery** / **08_mesh_viewer** — cas « maillage seul »
   (inspection de bundles existants).
8. **09_capability_gallery** — figures publiées (gallery statique).

## Parcours alternatif pour un data-scientist

`00` → `01` → explorer `hmp.open("examples/")` puis
`catalog.to_dataframe()`, `catalog.best(...)`, `SimulationGroup` pour
ML-ready exports.

## Conventions

Chaque projet est un sous-dossier **auto-contenu** sous `projects/` :

```
examples/projects/<NN_nom>/
├── README.md          # description FR détaillée
├── project.toml       # configuration valide
└── run*.py            # équivalent Python (optionnel)
```

Les artefacts de run (`hydromodpy.duckdb`, Zarr) sont stockés au
niveau du workspace `examples/` et ignorés par `.gitignore`.

## Archive pré-v0.5

Les exemples historiques qui ne s'alignent plus sur l'API actuelle
sont conservés dans
[`examples_legacy_2/`](../examples_legacy_2/README_LEGACY.md) et
seront supprimés en v0.6.
