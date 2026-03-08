# Launchers Package

`launchers/` contient les orchestrateurs de workflows HydroModPy.

## CLI

Commande canonique :

```bash
hmp simulation path/to/config.toml
hmp simulation path/to/config.toml --out /tmp/results
```

Equivalent via module :

```bash
python -m launchers simulation path/to/config.toml
```

## Sous-dossiers

| Dossier | Classe | Etat |
|---|---|---|
| `process_simulation/` | `HydroModPyLauncher` | Fonctionnel |
| `data_overview/` | `DataOverviewLauncher` | Reserve (vide) |
| `model_calibration/` | `ModelCalibrationLauncher` | Reserve (vide) |
| `hydro_cal_val/` | `HydroCalValLauncher` | Reserve (vide) |

## Architecture

Le launcher orchestre sans implementer de logique solveur :

1. Charge et valide le TOML (`HydroModPyConfig`)
2. Bootstrap les objets partages (workspace, geographic, domain, flow, transport)
3. Charge les donnees externes (`DataManagersRuntimeLoader`)
4. Applique les binders structurels (geology->domain, oceanic->flow, climatic->recharge)
5. Delegue l'execution a `SimulationRunner` avec callbacks postprocess

## Separation des responsabilites

- **Chargement donnees** : `hydromodpy/data_managers/runtime_loader.py`
- **Binders structurels** : `hydromodpy/domain/structure_binders.py`, `hydromodpy/process/flow/structure_binders.py`
- **Planification** : `hydromodpy/simulation/planning/`
- **Execution** : `hydromodpy/simulation/runtime/runner.py`
- **Postprocess** : `hydromodpy/postprocess/runner.py` (pilote par `[postprocess]` dans le TOML)
