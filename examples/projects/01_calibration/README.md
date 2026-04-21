# 01 — calibration

Boucle de calibration **Optuna** sur le cas synthétique Dupuit de
l'exemple 00. Un seul paramètre calibré : la conductivité hydraulique
`K` (échelle log, bornes `1e-6` à `1e-3` m/s).

## Objectif pédagogique

- Écrire un bloc `[calibration]` conforme à la config v0.5.
- Déclarer un paramètre calibrable avec `bounds`, `transform`, `path`.
- Comprendre le mode `save_runs = "best_n"` (seules les N meilleures
  itérations deviennent des simulations complètes).

## Prérequis

- `pip install -e .` depuis la racine du dépôt.
- `optuna` doit être installé (dépendance optionnelle du groupe
  calibration).

## Lancement

```bash
hmp calibrate examples/01_calibration/project.toml
# ou
python examples/01_calibration/run.py
```

Durée indicative : **~1 minute** pour 20 itérations.

## Ce qui est produit

- Une session dans la table `calibration_sessions` du workspace.
- 20 lignes dans `calibration_iterations` (trace complète).
- Les 3 meilleures itérations promues en simulations complètes
  (DuckDB + Zarr).

## Aller plus loin

- Augmenter `max_iter` pour une meilleure convergence.
- Ajouter `Sy_main = { bounds = [0.02, 0.30] }` sous
  `[calibration.parameters]` pour un second paramètre.
- Passer en régime transitoire (`flow.flow_regime = "transient"`) avec
  de vraies observations piézométriques dans `[observations]`.
