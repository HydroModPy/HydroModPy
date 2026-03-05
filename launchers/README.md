# Launchers Package

`launchers/` contient les points d'entree et les orchestrateurs de workflows.

## Sous-dossiers metier

Les sous-dossiers suivants structurent les futurs launchers specialises a
partir de la convention de nommage retenue :

- `data_overview/` : pour `DataOverviewLauncher`
- `process_simulation/` : pour `ProcessSimulationLauncher`
- `model_calibration/` : pour `ModelCalibrationLauncher`
- `hydro_cal_val/` : pour `HydroCalValLauncher`

## Intention

- `DataOverviewLauncher` : illustration, visualisation et inventaire des
  donnees et de la configuration disponibles pour un site, sans simulation.
- `ProcessSimulationLauncher` : execution des simulations de processus.
- `ModelCalibrationLauncher` : orchestration des workflows de calibration.
- `HydroCalValLauncher` : mise en place d'une strategie hydrologique de
  calibration-validation.

Cette arborescence prepare une separation claire des responsabilites sans
modifier le launcher principal existant.

## Separation loading/update

- Le chargement des donnees reste dans `hydromodpy/data_managers/runtime_loader.py`.
- Les mises a jour structurelles issues de ces donnees (ex. geology->domain,
  oceanic->flow) sont portees par `launchers/structure_updaters.py`.
- Le launcher orchestre l'ordre: chargement data puis binders structurels.
