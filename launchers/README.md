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

Generation d'un template canonique derive des schemas `pydantic` :

`python -m launchers mesh-catchment template [--batch] [--profile user|dev|expert] [--output path/to/template.toml]`

Commande directe (utile depuis un IDE) :

`python launchers/mesh_catchment/launcher.py <path/to/config.toml>`

Exemple de config prete a lancer :

`launchers/mesh_catchment/config_mesh_catchment_example.toml`

Exemple de config batch par `outlet_id` :

`launchers/mesh_catchment/config_mesh_catchment_batch_example.toml`

Le sous-commande `template` imprime un TOML commente produit directement depuis
les schemas `mesh_catchment` et `mesh_catchment_batch`. Cela permet de repartir
d'un contrat a jour sans aller relire le code source.

Templates canoniques versionnes :

- `launchers/mesh_catchment/config_mesh_catchment_template.toml`
- `launchers/mesh_catchment/config_mesh_catchment_batch_template.toml`

Configuration en deux niveaux (meme logique que process_simulation) :

- `launchers/mesh_catchment/config_mesh_catchment_common.toml`
  : tronc commun catchment (`workspace`, `geographic`, `geographic.river_network`).
- `launchers/mesh_catchment/config_mesh_catchment_example.toml`
  : divergence metier mesh via `[mesh_catchment]`.
- `launchers/mesh_catchment/config_mesh_catchment_batch_example.toml`
  : boucle batch via `[mesh_catchment_batch]` avec un dossier catchment par
  `outlet_id`.

## Flux mesh_catchment

Le workflow `mesh_catchment` s'appuie sur un runtime mono-catchment partage
entre :

- le launcher dedie `python -m launchers mesh-catchment run ...`
- la phase mesh embarquee dans `process_simulation`

L'objectif est d'eviter deux implementations qui divergent sur la preparation
du `workspace`, la generation du `river_trace`, les sorties par defaut ou
l'export du bundle d'echange.

### Flux mono-catchment

Quand seule la section `[mesh_catchment]` est presente :

1. le launcher charge le TOML et valide `[mesh_catchment]`
2. il charge `workspace` et `geographic`
3. il active `geographic.river_network` si `constraints_mode` utilise la
   riviere (`rivers_only` ou `geology_rivers`)
4. il construit le `DomainGeographicContext`
5. il recupere `river_trace` en memoire depuis ce contexte
6. il lance le case Gmsh conformal
7. il exporte, si possible, le bundle d'echange associe au maillage
8. il retourne un resume avec les chemins utiles (`output_mesh`,
   `output_summary_json`, `output_figure`, bundle)

Par defaut, les sorties sont resolues dans `results_stable/mesh/gmsh/` du
catchment courant, sauf override explicite dans `[mesh_catchment]`.

### Flux batch

Quand `[mesh_catchment_batch]` est active :

1. le launcher valide la table d'exutoires et la selection (`all` ou
   `selected`)
2. il derive un sous-workspace par `outlet_id`
3. il injecte `x_outlet` et `y_outlet` dans une copie de `geographic`
4. il derive les noms de sortie et le `catch_name` via les patterns batch
5. il relance exactement le meme runtime mono-catchment pour chaque outlet
6. il ecrit le manifest CSV au fil de l'eau

Le batch n'implemente donc pas un second moteur de maillage. Il boucle sur des
configs derivees, puis reutilise le chemin mono-catchment pour chaque outlet.

`continue_on_error = true` permet de continuer la boucle apres un echec et de
consigner l'erreur dans le manifest. Si `false`, le premier echec interrompt le
batch.

### Flux embarque dans process_simulation

`process_simulation` peut embarquer une phase `[mesh_catchment]`, mais pas un
batch complet :

- `[mesh_catchment]` : autorise
- `[mesh_catchment_batch]` : refuse si `enabled = true`

Dans ce cas, la phase mesh est executee une fois apres la construction des
supports spatiaux et avant les solveurs. Le resume de maillage est ensuite
range dans l'etat runtime (`mesh_summary`) et remonte dans les artefacts de run.

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
