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
  au reseau de rivieres et/ou a la geologie, en mode mono-catchment ou batch
  par table d'exutoires.

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

Exemple de config batch par `outlet_id` :

`launchers/mesh_catchment/config_mesh_catchment_batch_example.toml`

Configuration en deux niveaux (meme logique que process_simulation) :

- `launchers/mesh_catchment/config_mesh_catchment_common.toml`
  : tronc commun catchment (`workspace`, `geographic`, `geographic.river_network`).
- `launchers/mesh_catchment/config_mesh_catchment_example.toml`
  : divergence metier mesh via `[mesh_catchment]`.
- `launchers/mesh_catchment/config_mesh_catchment_batch_example.toml`
  : boucle batch via `[mesh_catchment_batch]` avec un dossier catchment par
  `outlet_id`.

## Architecture

Le launcher orchestre sans implementer de logique solveur :

1. Charge et valide le TOML.
2. Bootstrap les objets partages (workspace, geographic, domain, flow, transport).
3. Charge les donnees externes.
4. Applique les binders structurels.
5. Delegue l'execution aux runners et exporteurs metier.

## Separation des responsabilites

- Chargement donnees : `hydromodpy/data_managers/runtime_loader.py`
- Binders structurels : `hydromodpy/domain/structure_binders.py`,
  `hydromodpy/process/flow/structure_binders.py`
- Planification : `hydromodpy/simulation/planning/`
- Execution : `hydromodpy/simulation/runtime/runner.py`
- Postprocess : `hydromodpy/postprocess/runner.py`
