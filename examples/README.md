# HydroModPy — exemples

Suite d'exemples alignés sur l'API **v0.5** :

- CLI `hmp` (`hmp run`, `hmp calibrate`, `hmp list`, `hmp show`, …).
- API Python `import hydromodpy as hmp` (`hmp.run`, `hmp.calibrate`,
  `hmp.open`).
- Stockage unifié via `SimulationCatalog` (DuckDB + Zarr).

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
dans les TOML d'exemple y pointent via `../data/...`.

## Index

| # | Dossier | Titre | Solveur | Durée | Réseau |
|---|---|---|---|---|---|
| 00 | [`00_getting_started/`](00_getting_started/) | Aquifère Dupuit synthétique | MODFLOW-NWT | ~20 s | non |
| 01 | [`01_calibration/`](01_calibration/) | Calibration Optuna sur K | MODFLOW-NWT | ~1 min | non |
| 02 | [`02_nancon_watershed/`](02_nancon_watershed/) | Bassin du Nançon (MODFLOW-NWT) | MODFLOW-NWT | ~5 min | possible |
| 03 | [`03_canut_watershed/`](03_canut_watershed/) | Bassin du Canut (config expert) | MODFLOW-NWT | ~5 min | possible |
| 04 | [`04_data_overview/`](04_data_overview/) | Carte d'identité d'un bassin | — | ~1 min | oui |
| 05 | [`05_nancon_data_overview/`](05_nancon_data_overview/) | Overview complet Nançon | — | ~2 min | oui |
| 06 | [`06_vire_selune/`](06_vire_selune/) | Vire & Sélune — MF6 et NWT | MF6 / NWT | ~10 min | possible |
| 07 | [`07_mesh_gallery/`](07_mesh_gallery/) | Galerie de maillages (bundles) | — | instantané | non |
| 08 | [`08_mesh_viewer/`](08_mesh_viewer/) | Visualisation de bundles de maillage | — | instantané | non |
| 09 | [`09_capability_gallery/`](09_capability_gallery/) | Figures de référence (gallery statique) | — | — | non |

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

Chaque exemple est un sous-dossier **auto-contenu** :

```
examples/<NN_nom>/
├── README.md          # description FR détaillée
├── project.toml       # configuration valide
└── run*.py            # équivalent Python (optionnel)
```

Les artefacts de run (workspace local, `hydromodpy.duckdb`, Zarr) sont
ignorés par `.gitignore`.

## Archive pré-v0.5

Les exemples historiques qui ne s'alignent plus sur l'API actuelle
sont conservés dans
[`examples_legacy_2/`](../examples_legacy_2/README_LEGACY.md) et
seront supprimés en v0.6.
