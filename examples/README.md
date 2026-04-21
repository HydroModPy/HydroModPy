# HydroModPy — exemples

Suite d'exemples exécutables, alignés sur l'API **v0.5** :

- CLI `hmp` (`hmp run`, `hmp calibrate`, `hmp list`, `hmp show`, …).
- API Python `import hydromodpy as hmp` (`hmp.run`, `hmp.calibrate`,
  `hmp.open`).
- Stockage unifié via `SimulationCatalog` (DuckDB + Zarr).

## Prérequis communs

```bash
conda create -n hmp python=3.13
conda activate hmp
pip install -e .
```

Chaque exemple est **auto-contenu** dans son sous-dossier :

```
examples/<NN_nom>/
├── README.md      # description détaillée en français
├── project.toml   # configuration valide
└── run.py         # équivalent Python de la commande CLI
```

## Index

| # | Dossier | Titre | Solveur | Régime | Durée | Réseau |
|---|---|---|---|---|---|---|
| 00 | `00_getting_started/` | Aquifère Dupuit synthétique | MODFLOW-NWT | permanent | ~20 s | non |
| 01 | `01_calibration/` | Calibration Optuna sur K | MODFLOW-NWT | permanent | ~1 min | non |

## Ordre de lecture recommandé

1. **00_getting_started** — structure minimale d'un `project.toml`,
   premier run, découverte du catalogue.
2. **01_calibration** — bloc `[calibration]`, API `hmp.calibrate`,
   modes de persistance (`save_runs`).

## Archive

Les anciens exemples (pré-v0.5) sont conservés dans
[`examples_legacy_2/`](../examples_legacy_2/README_LEGACY.md) à titre
de trace historique. Ils ne fonctionnent plus avec l'API actuelle et
seront supprimés en v0.6.
