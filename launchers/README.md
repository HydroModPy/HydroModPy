# Launchers Package

`launchers/` contient les points d'entree et les orchestrateurs de workflows.

## Sous-dossiers metier

Les sous-dossiers suivants structurent les futurs launchers specialises a
partir de la convention de nommage retenue :

- `data_overview/` : pour `DataOverviewLauncher`
- `process_simulation/` : pour `ProcessSimulationLauncher`
- `method_comparison/` : pour `MethodComparisonLauncher`
- `model_calibration/` : pour `ModelCalibrationLauncher`
- `hydro_cal_val/` : pour `HydroCalValLauncher`
- `mesh_catchment/` : pour `MeshCatchmentLauncher`

## Intention

- `DataOverviewLauncher` : illustration, visualisation et inventaire des
  donnees et de la configuration disponibles pour un site, sans simulation.
- `ProcessSimulationLauncher` : execution des simulations de processus.
- `MethodComparisonLauncher` : orchestration de variantes maillage/solveur
  pour un meme probleme et extraction d'observables comparables depuis les
  postprocess disque, avec CSV/JSON de metriques et rapport Markdown.
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

Commande recommandee pour la famille data-overview :

`python -m launchers data-overview run <path/to/config.toml>`

Commande recommandee pour la famille mesh-catchment :

`python -m launchers mesh-catchment run <path/to/config.toml>`

Commande recommandee pour comparer des methodes de resolution :

`python -m launchers method-comparison run <path/to/config.toml>`

Alias CLI principal :

`hmp compare <path/to/config.toml>`

Generation d'un template canonique derive des schemas `pydantic` :

`python -m launchers mesh-catchment template [--batch] [--profile user|dev|expert] [--output path/to/template.toml]`

Template method-comparison :

`python -m launchers method-comparison template [--output path/to/template.toml]`

Exemple de config prete a lancer :

`launchers/mesh_catchment/scenarios/config_example.toml`

Exemple de config batch par `outlet_id` :

`launchers/mesh_catchment/scenarios/config_headwater_100km2.toml`

Guide de prise en main dedie :

`launchers/mesh_catchment/README.md`

Guide method-comparison :

`launchers/method_comparison/README.md`

Exemple data-overview versionne :

`examples/projects/data_overview/project.toml`

Le sous-commande `template` imprime un TOML commente produit directement depuis
les schemas `mesh_catchment` et `mesh_catchment_batch`. Cela permet de repartir
d'un contrat a jour sans aller relire le code source.

Templates canoniques versionnes :

- `launchers/mesh_catchment/config_template.toml`
- `launchers/mesh_catchment/config_batch_template.toml`

Organisation du sous-package `mesh_catchment` :

- `launchers/mesh_catchment/*.py`
  : code runtime du launcher, orchestration mono-catchment, batch, templates et validation.
- `launchers/mesh_catchment/config_*.toml`
  : bases partagees et templates canoniques lies au contrat du launcher.
- `launchers/mesh_catchment/scenarios/*.toml`
  : scenarios runnable versionnes, separes du code et des templates.
- `launchers/mesh_catchment/tools/*.py`
  : utilitaires operatoires, par exemple le smoke runner batch de reference.

Configuration en deux niveaux (meme logique que process_simulation) :

- `launchers/mesh_catchment/config_common.toml`
  : tronc commun partage (`workspace`, `geographic`, `geographic.river_network`, `domain.depth_model`).
- `launchers/mesh_catchment/config_batch_common.toml`
  : base batch partagee qui specialise le tronc commun pour les scenarios multi-exutoires.
- `launchers/mesh_catchment/scenarios/config_example.toml`
  : exemple mono-catchment par defaut du launcher, sur le cas Nancon, avec sorties finales ecrites directement dans le dossier catchment.
- `launchers/mesh_catchment/scenarios/config_scoped_example.toml`
  : variante mono-catchment qui montre `interface_scope` et `refinement_scope`, avec sorties finales directes dans le dossier catchment.
- `launchers/mesh_catchment/scenarios/config_headwater_100km2.toml`
  : batch headwater autour de 100 km2 a partir d'une table d'exutoires preselectionnes.
- `launchers/mesh_catchment/scenarios/config_1000km2.toml`
  : batch autour de 1000 km2.
- `launchers/mesh_catchment/scenarios/config_s3_100km2.toml`
  : batch filtre par ordre de Strahler 3 autour de 100 km2.
- `launchers/mesh_catchment/config_template.toml`
  : template mono-catchment versionne, regenere depuis les schemas Pydantic.
- `launchers/mesh_catchment/config_batch_template.toml`
  : template batch versionne, regenere depuis les schemas Pydantic.

Les configs de scenario versionnees activent maintenant un pattern recommande
pour garder un maillage plus coarse hors bassin versant :

- `domain.kind = "geographic_box_buffer"` pour conserver un support plus large
- `interface_scope.kind = "geographic_watershed"` pour ne materialiser les interfaces que dans le bassin
- `refinement_scope.kind = "geographic_watershed"` pour ne raffiner finement que dans le bassin

Cela laisse un fond de maillage plus grossier autour du bassin tout en gardant
le contexte geographique utile.

Script utilitaire pour lancer successivement tous les TOML runnable du dossier :

`python -m launchers.mesh_catchment.tools.run_all_configs`

Ordre d'execution du script :

- `config_example.toml`
- `config_scoped_example.toml`
- `config_headwater_100km2.toml`
  : precede de `hydromodpy_annex/preprocess/catchment_identification_scan/config_headwater_100km2.toml`
- `config_1000km2.toml`
  : precede de `hydromodpy_annex/preprocess/catchment_identification_scan/config_1000km2.toml`
- `config_s3_100km2.toml`
  : precede de `hydromodpy_annex/preprocess/catchment_identification_scan/config_s3_100km2.toml`

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

Sans option supplementaire, les sorties sont resolues dans
`results_stable/mesh/` du catchment courant, sauf override explicite dans
`[mesh_catchment]`.

Si `mesh_catchment.output_layout = "flat"` est active, le launcher mesh
dedie ecrit au contraire les artefacts finaux directement dans
`workspace.project_root` (`.msh`, resume JSON, figures, bundle) et garde les
intermediaires dans un workspace runtime separe, nettoye a la fin du run
reussi. Le dossier final du catchment ne contient alors plus de
`results_stable/`, `results_simulations/` ni `results_calibration/`.
Ce mode n'affecte pas `process_simulation`, qui conserve la structure
workspace standard.

Le bundle exporte aussi la surface de substratum (`z_bottom` aux noeuds,
`z_bottom_centroid` / `z_bottom_mean` par cellule) a partir de
`[domain.depth_model]`. Le launcher mesh relit donc egalement la section
`[domain]` du TOML, en pratique souvent heritee du `base_config`.

Pour le launcher dedie, `mesh_catchment.geographic_outputs_mode = "cleanup"`
supprime a la fin du run les artefacts intermediaires
`results_stable/geographic/` et `results_stable/demcorrecflow/` une fois le
maillage, les figures et le bundle ecrits. La valeur par defaut `keep`
conserve ces dossiers. Dans `process_simulation`, ce mode n'efface rien car
les sorties geographiques restent reutilisees par le workflow de simulation.

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

Le launcher verifie aussi avant la boucle que `geographic.dem_init_path` et,
si renseigne, `mesh_catchment.geology.source.reference_raster_path` couvrent
bien tous les exutoires selectionnes. Cela evite les echecs tardifs dus a un
DEM ou un raster de reference hors emprise.

### Flux embarque dans process_simulation

`process_simulation` peut soit embarquer une phase `[mesh_catchment]`, soit
reutiliser un maillage deja produit via `[mesh_input]`, mais pas un batch
complet :

- `[mesh_catchment]` : autorise
- `[mesh_input]` : autorise pour charger `mesh_path` et/ou `bundle_dir`
- `[mesh_catchment_batch]` : refuse si `enabled = true`

Dans ce cas, la phase mesh est executee une fois apres la construction des
supports spatiaux et avant les solveurs. Le resume de maillage est ensuite
range dans l'etat runtime (`mesh_summary`) et remonte dans les artefacts de run.

`[mesh_catchment]` et `[mesh_input]` sont mutuellement exclusifs dans un meme
run `process_simulation`.

Le launcher reste le meme dans tous les cas. Il n'existe pas de variante
`process_simulation_gmsh` separee : le maillage runtime Gmsh est simplement une
option d'entree du launcher standard. En pratique, ce contrat runtime mesh est
aujourd'hui consomme par `boussinesq` et `modflow6`. `modflownwt` reste borne au
backend structure `[modflownwt.sgrid.*]` et le launcher refuse donc
explicitement les combinaisons `modflownwt + [mesh_input]` ou
`modflownwt + [mesh_catchment]`.

## Architecture

Le launcher orchestre sans implementer de logique solveur :

1. Charge et valide le TOML.
2. Bootstrap les objets partages (workspace, geographic, domain, flow, transport).
3. Charge les donnees externes.
4. Applique les binders structurels.
5. Delegue l'execution aux runners et exporteurs metier.

## Separation des responsabilites

- Chargement donnees : `hydromodpy/data/runtime_loader.py`
- Binders structurels : `hydromodpy/spatial/geographic/structure_binders.py`,
  `hydromodpy/process/flow/structure_binders.py`
- Planification : `hydromodpy/simulation/planning/`
- Execution : `hydromodpy/simulation/execution/runner.py`
- Postprocess : `hydromodpy/analysis/postprocess/runner.py`
