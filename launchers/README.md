# Launchers Package

`launchers/` contient les points d'entree et les orchestrateurs de workflows.

## Sous-dossiers metier

Les sous-dossiers suivants structurent les futurs launchers specialises a
partir de la convention de nommage retenue :

- `data_overview/` : pour `DataOverviewLauncher`
- `process_simulation/` : pour `ProcessSimulationLauncher`
- `model_calibration/` : pour `ModelCalibrationLauncher`
- `hydro_cal_val/` : pour `HydroCalValLauncher`
- `mesh_catchment/` : pour `MeshCatchmentLauncher`

## Intention

- `DataOverviewLauncher` : illustration, visualisation et inventaire des
  donnees et de la configuration disponibles pour un site, sans simulation.
- `ProcessSimulationLauncher` : execution des simulations de processus.
- `ModelCalibrationLauncher` : orchestration des workflows de calibration.
- `HydroCalValLauncher` : mise en place d'une strategie hydrologique de
  calibration-validation.
- `MeshCatchmentLauncher` : generation de maillage catchment conforme
  au reseau de rivieres (mode force, geometries geologiques ignorees pour le maillage).

Cette arborescence prepare une separation claire des responsabilites sans
modifier le launcher principal existant.

## CLI

Commande recommandee pour la famille simulation :

`python -m launchers simulation run <path/to/config.toml>`

Commande recommandee pour la famille mesh-catchment :

`python -m launchers mesh-catchment run <path/to/config.toml>`

Commande directe (utile depuis un IDE) :

`python launchers/mesh_catchment/launcher.py <path/to/config.toml>`

Exemple de config prete a lancer :

`launchers/mesh_catchment/config_mesh_catchment_example.toml`

Configuration en deux niveaux (meme logique que process_simulation) :

- `launchers/mesh_catchment/config_mesh_catchment_common.toml`
  : tronc commun catchment (`workspace`, `geographic`, `geographic.river_network`).
- `launchers/mesh_catchment/config_mesh_catchment_example.toml`
  : divergence metier mesh via `[mesh_catchment]`.

## Separation loading/update

- Le chargement des donnees reste dans `hydromodpy/data_managers/runtime_loader.py`.
- Les mises a jour structurelles issues de ces donnees (ex. geology->domain,
  oceanic->flow) sont portees par les modules metier:
  `hydromodpy/domain/structure_binders.py` et
  `hydromodpy/process/flow/structure_binders.py`.
- Le launcher orchestre l'ordre: chargement data puis binders structurels.

## Postprocess

- Les post-traitements standards apres `flow`/`transport` sont pilotes par
  `[postprocess]` dans le TOML et executes par `hydromodpy/postprocess/runner.py`.
- Ce mecanisme remplace les anciens scripts projet-specifiques.
