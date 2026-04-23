# Perspective MODFLOW 6 sur maillages gmsh triangulaires (DISV)

Liens :
[unified_mesh_pivot_architecture.md](unified_mesh_pivot_architecture.md),
[gmsh_mesh_integration_note.md](gmsh_mesh_integration_note.md),
[gmsh_conformal_meshing.md](gmsh_conformal_meshing.md),
[modflow_contracts.md](modflow_contracts.md),
[nwt_sunset_plan.md](nwt_sunset_plan.md),
[glossary.md](glossary.md).

Code : `hydromodpy/solver/modflow6/`, `hydromodpy/spatial/mesh/gmsh_grid/`.

## Objet du document

Cette note cadre en détail l'intégration de MODFLOW 6 sur des maillages
irréguliers triangulaires produits avec gmsh dans HydroModPy.

Le point important qui ressort de l'analyse du dépôt est le suivant:

- le format cible côté MODFLOW 6 est bien `DISV`,
- le dépôt possède déjà une abstraction de maillage générique avec
  `SolverMesh`,
- l'export géométrique `DISV` existe déjà,
- le principal verrou n'est donc pas la dernière conversion FloPy, mais la
  généralisation de toute la chaîne amont et aval qui reste encore largement
  structurée.

Cette note répond aussi à une autre question importante: comment réorganiser
`hydromodpy/solver/modflow6` pour le rapprocher au maximum de la structure
déjà mise en place dans `hydromodpy/solver/modflow_nwt/modflow`, avec des
modules de responsabilité similaire et, autant que possible, les mêmes noms.

## Sources de référence

Références externes principales:

- exemple officiel FloPy / MODFLOW 6 `DISV`:
  <https://modflow6-examples.readthedocs.io/en/latest/_notebooks/ex-gwf-disvmesh.html>
- documentation officielle `GWF-DISV`:
  <https://modflow6.readthedocs.io/en/stable/_mf6io/gwf-disv.html>
- documentation officielle `GWF-RCHA`:
  <https://modflow6.readthedocs.io/en/stable/_mf6io/gwf-rcha.html>
- documentation officielle `GWF-WEL`:
  <https://modflow6.readthedocs.io/en/stable/_mf6io/gwf-wel.html>
- documentation officielle `GWF-CHD`:
  <https://modflow6.readthedocs.io/en/stable/_mf6io/gwf-chd.html>
- documentation officielle `GWF-NPF`:
  <https://modflow6.readthedocs.io/en/stable/_mf6io/gwf-npf.html>

Fichiers locaux principalement concernés:

- `hydromodpy/solver/modflow6/modflow6.py`
- `hydromodpy/solver/modflow6/modflow6_config.py`
- `hydromodpy/solver/modflow_common/solver_mesh.py`
- `hydromodpy/spatial/mesh/adapters/flopy_adapter.py`
- `hydromodpy/solver/modflow_nwt/modflow/discretization.py`
- `hydromodpy/solver/modflow_nwt/modflow/property_mapping.py`
- `hydromodpy/solver/modflow_common/runtime_arrays.py`
- `hydromodpy/process/flow/sinks_sources.py`
- `hydromodpy/process/flow/boundary_conditions.py`
- `hydromodpy/spatial/mesh/gmsh_grid/gmsh_reader.py`
- `hydromodpy/spatial/mesh/gmsh_grid/gmsh_planar_mesh.py`
- `hydromodpy/spatial/mesh/gmsh_grid/planar_forcing_discretization.py`
- `hydromodpy/solver/boussinesq/mesh.py`
- `hydromodpy/solver/boussinesq/adapters/flow.py`

## Réponses directes aux questions

### 1. Est-ce que `solver_mesh.to_disv_kwargs` est le premier grand point de jonction ?

Pas exactement.

`SolverMesh.to_disv_kwargs()` existe déjà et correspond déjà à la conversion
géométrique finale vers le contrat FloPy `DISV`. La jonction la plus
importante n'est donc pas cette fonction en elle-même, mais l'étape qui
construit le `SolverMesh` à partir d'un maillage Gmsh avant la résolution.

Autrement dit:

- `to_disv_kwargs` est déjà la bonne interface terminale,
- la vraie première étape structurante est de faire produire un
  `SolverMesh` générique à partir de `gmsh_grid`,
- cette étape doit être intégrée en amont, dans la construction de la
  discrétisation spatiale, et non reportée à la fin.

### 2. Est-ce que les propriétés hydrauliques et géologiques doivent être dans la même fonction ?

Non, il vaut mieux éviter.

La géométrie `DISV` et les propriétés de milieux n'ont pas la même
responsabilité:

- `to_disv_kwargs` doit rester une fonction d'export de maillage,
- les propriétés hydrauliques et géologiques doivent rester dans une couche
  d'adaptation des données physiques vers des tableaux solver-ready,
- sinon on mélange la topologie du maillage avec le contenu physique des
  packages `NPF`, `STO`, `IC`, `RCHA`, `WEL`, `CHD`.

La bonne direction est donc:

- géométrie dans `SolverMesh` et l'export `DISV`,
- propriétés dans un module de `property_mapping` ou dans un adaptateur
  `flow_to_modflow_adapter`,
- package assembly dans la classe solveur.

### 3. Faut-il garder les grilles régulières MODFLOW 6 comme un cas d'irrégulier ?

En pratique, c'est déjà presque le cas.

Dans le code actuel, `modflow6.py` construit `ModflowGwfdisv` et non
`ModflowGwfdis`. Cela signifie que même la grille régulière est déjà exportée
vers MODFLOW 6 sous forme `DISV`.

La conclusion est importante:

- côté MF6, la cible interne n'est déjà plus une grille strictement
  cartésienne,
- le principal travail consiste donc à supprimer les hypothèses structurées
  restantes autour de cette géométrie,
- l'alignement "régulier et irrégulier aussi proches que possible" est une
  direction cohérente avec l'architecture déjà engagée.

### 4. Que signifie exactement l'usage actuel de `flatten_from_grid` pour `self.hk` ?

Cela montre que le code actuel part encore d'une logique structurée puis
aplatit les tableaux vers une forme compatible `DISV`.

Aujourd'hui, le chemin est:

- mapping des propriétés sur un maillage structuré,
- production d'arrays `(nlay, nrow, ncol)`,
- aplatissement via `solver_mesh.flatten_from_grid(...)`,
- consommation par `ModflowGwfnpf` et `ModflowGwfsto`.

Ce n'est pas absurde, mais ce n'est pas la forme cible la plus générale.

La forme cible plus propre pour MF6 est plutôt:

- produire directement des tableaux cellule-centriques
  `(nlay, ncpl)` ou `(ncpl,)`,
- puis seulement ré-étendre vers `(nlay, nrow, ncol)` quand un solveur ou un
  export structuré l'exige vraiment.

### 5. Y a-t-il bien une réorganisation à faire, et est-elle surtout dans `modflow6.py` ?

Oui.

L'analyse du dépôt confirme que:

- `hydromodpy/solver/modflow_nwt/modflow` est déjà découpé en plusieurs
  modules cohérents,
- `hydromodpy/solver/modflow6` concentre encore presque toute la logique dans
  `modflow6.py`,
- la majeure partie de la réorganisation à prévoir concerne donc bien
  `modflow6.py`.

### 6. Peut-on rapprocher fortement l'organisation de `modflow6` de celle de `modflow_nwt` ?

Oui, et c'est même la recommandation principale de cette note.

L'objectif raisonnable n'est pas une symétrie parfaite au caractère près,
mais une symétrie de responsabilités:

- même type de découpage,
- mêmes noms de modules quand cela a du sens,
- mêmes contrats d'entrée/sortie quand c'est possible,
- quelques helpers communs remontés dans `modflow_common` plutôt que
  dupliquer ou créer trop de micro-fonctions.

## Ce que le code fait déjà aujourd'hui

### Côté MODFLOW 6

Le point majeur est que `modflow6.py` utilise déjà `DISV`:

- `Modflow6.pre_processing()` instancie `flopy.mf6.ModflowGwfdisv`,
- `Modflow6Transport.pre_processing()` instancie `flopy.mf6.ModflowGwtdisv`.

Autrement dit, l'architecture MF6 est déjà orientée vers une grille générique
cellulaire, même si beaucoup de traitements amont et aval restent encore
indexés en `row/col`.

### Côté maillage solveur

`SolverMesh` est déjà l'abstraction centrale la plus utile pour ce chantier:

- il encapsule un maillage plan 2D plus les couches verticales,
- il sait représenter un maillage structuré ou non structuré,
- il sait fournir `to_disv_kwargs()`,
- il fournit des helpers de forme (`reshape_to_grid`,
  `flatten_from_grid`).

Cela veut dire qu'une bonne partie de la jonction conceptuelle existe déjà.

### Côté Gmsh

Le dépôt contient déjà des briques utiles pour des maillages irréguliers:

- lecture de maillage Gmsh,
- représentation plane Gmsh,
- discrétisation de forçages sur maillage plan non structuré,
- adaptation déjà faite côté Boussinesq.

Ce dernier point est important: l'architecture Boussinesq montre qu'il est
possible de préparer un maillage plan irrégulier en amont de la résolution
sans faire porter tout le poids de cette logique à la classe solveur.

## Lecture du contrat officiel DISV

### Ce que DISV impose réellement

D'après la documentation officielle `GWF-DISV`:

- `NCPL` est constant d'une couche à l'autre,
- le maillage plan est décrit par `VERTICES` et `CELL2D`,
- les couches verticales réutilisent la même topologie plane,
- `IDOMAIN` peut prendre `0`, `1`, et aussi `-1` pour certains cas de
  pass-through vertical,
- la géoréférence (`xorigin`, `yorigin`, rotation, CRS) est un sujet de
  positionnement, pas de connectivité.

Conclusion directe pour HydroModPy:

- un maillage triangulaire Gmsh extrudé verticalement vers plusieurs couches
  est un très bon candidat pour `DISV`,
- si la topologie change selon les couches, on sortirait du cas `DISV` et il
  faudrait plutôt penser `DISU`,
- pour l'objectif actuel, `DISV` est le bon niveau de complexité.

### Point de vigilance important: ordre des sommets

La documentation `GWF-DISV` précise que les sommets d'une cellule `CELL2D`
doivent être fournis dans un ordre cohérent de type horaire.

Or, dans l'état actuel:

- `to_flopy_disv_args()` reformate la connectivité existante,
- il ne normalise pas explicitement l'orientation des polygones,
- il calcule les centroïdes par moyenne simple des sommets,
- il ne valide pas explicitement les polygones dégénérés.

Ce point doit être traité avant de considérer l'export Gmsh -> DISV comme
robuste en production.

### Point de vigilance sur les index

Les fichiers texte MODFLOW 6 sont documentés avec des index de type 1-based,
mais l'usage FloPy pour construire les `gridprops` est, lui, naturellement
0-based côté Python.

L'exemple officiel `ex-gwf-disvmesh` montre précisément ce décalage.

Il ne faut donc pas corriger par erreur l'export actuel vers un faux 1-based
si l'on reste dans une chaîne FloPy.

## Analyse détaillée par catégorie

### 1. Géométrie du maillage et discrétisation spatiale

Le point de blocage principal n'est pas `to_disv_kwargs()`, mais
`build_spatial_discretization(...)`.

Aujourd'hui, cette fonction:

- vit dans `hydromodpy/solver/modflow_nwt/modflow/discretization.py`,
- est utilisée à la fois par `modflow_nwt` et par `modflow6`,
- résout les surfaces du domaine,
- construit une grille structurée via `StructuredGridBuilder`,
- convertit ensuite cette grille en `SolverMesh`.

Ce que cela signifie concrètement:

- la construction spatiale n'est déjà plus spécifique à NWT,
- mais elle reste limitée à un constructeur cartésien,
- et `modflow6` dépend encore d'un module rangé sous `modflow_nwt` pour une
  logique qui est en réalité plus générale.

Pour intégrer Gmsh proprement, la bonne évolution est de transformer cette
étape en dispatcher générique:

- résolution commune des surfaces top / bottom,
- choix d'un constructeur plan structuré ou Gmsh,
- production finale d'un `SolverMesh`,
- restitution d'un `SolverGridContext`.

La bonne granularité n'est donc pas:

- une nouvelle fonction spéciale "Gmsh vers DISV" dans `modflow6.py`,

mais plutôt:

- une discrétisation spatiale commune à la famille MODFLOW,
- avec plusieurs backends planaires.

### 2. Discrétisation verticale

La discrétisation verticale actuelle est portée dans le même module de
`discretization.py` et, conceptuellement, elle est déjà commune.

En effet, elle sert à:

- transformer `surface_topo` et `substratum`,
- construire `top` et `botm`,
- définir `nlay`,
- produire un `SolverMesh` indépendant du solveur final.

Ces responsabilités ne dépendent ni de NWT, ni de MF6.

Conclusion:

- la discrétisation verticale doit clairement être commune,
- elle n'a pas de raison forte de rester logée sous `modflow_nwt`,
- elle doit être déplacée vers un module commun ou au moins re-exportée
  depuis un emplacement commun.

### 3. Discrétisation temporelle

La fonction `build_temporal_discretization_from_time_grid(...)` est déjà,
dans les faits, commune:

- elle est utilisée par `modflow_nwt`,
- elle est utilisée par `modflow6`,
- elle consomme un `time_grid` du launcher,
- elle produit `perlen`, `nper`, `nstp`, `steady`,
- elle n'instancie aucun package FloPy.

Elle est donc mal rangée conceptuellement.

La recommandation est nette:

- cette logique doit être commune à `modflow_nwt` et `modflow6`,
- elle doit sortir de `hydromodpy/solver/modflow_nwt/modflow/discretization.py`
  vers `hydromodpy/solver/modflow_common/discretization.py`, ou un module
  équivalent de niveau commun.

Le même raisonnement vaut pour:

- `_coerce_itmuni`,
- `TemporalDiscretizationResult`,
- `resolve_domain_surfaces(...)`,
- `project_surfaces_to_planar_grid(...)`.

### 4. Propriétés hydrauliques et géologiques

Le mapping des propriétés est aujourd'hui plus ambigu.

Point positif:

- `resolve_required_flow_properties(...)` est bien conceptuellement commun,
- une partie de la résolution des supports géologiques et des valeurs
  homogènes ou hétérogènes est réutilisable.

Point limitant:

- `resolve_flow_property_arrays(...)` produit aujourd'hui des tableaux
  structurés,
- il s'appuie sur `discretize_fieldparam_on_sgrid(...)`,
- `modflow6` consomme ensuite ces tableaux en les aplatissant.

Autrement dit, ce module est partagé, mais pas encore vraiment générique.

La cible recommandée est de le scinder en deux niveaux:

- un coeur commun de résolution des sources de propriétés
  (supports, fallback, validation, sélection des paramètres requis),
- une projection spatiale backend-dépendante:
  `structured` pour NWT, `cellular/DISV` pour MF6.

Pour rester proche de l'organisation NWT sans multiplier les fonctions, la
recommandation retenue est:

- garder `property_mapping.py` dans chaque solver,
- conserver un `property_mapping.py` structuré pour NWT,
- créer un `property_mapping.py` cellulaire pour MF6,
- extraire seulement quelques helpers communs bien choisis dans
  `modflow_common`.

Cette option garde une lecture simple:

- la logique propre au backend reste visible là où on s'attend à la trouver,
- les helpers communs restent limités,
- on évite un coeur trop abstrait et difficile à suivre.

### 5. Conditions initiales

Les conditions initiales côté MF6 sont déjà relativement bien orientées vers
une représentation générique:

- `_build_start_heads(...)` manipule déjà des tableaux plats,
- les modes `top`, `bottom`, `custom` sont peu dépendants du type de grille.

Le vrai point de vigilance est ailleurs:

- certaines corrections de têtes initiales sont couplées à des frontières
  latérales structurées,
- ce couplage devra être déplacé dans une couche d'adaptation des
  conditions aux limites.

Conclusion:

- pas de refonte majeure du coeur des conditions initiales,
- mais il faut dissocier initialisation des têtes et logique de frontières.

### 6. Conditions aux limites

Les conditions aux limites sont une des zones les plus structurées du code
MF6 actuel.

Cas observés:

- frontières latérales nord/sud/est/ouest basées sur `row/col`,
- calcul de cellules de bord par balayage structuré,
- logique spécifique "east side" pour certains indicateurs de sortie.

Pour un maillage triangulaire Gmsh, il faut remplacer cette hypothèse par une
logique de sélection de cellules ou de faces supportée par la géométrie du
maillage.

Il y a au moins trois niveaux d'évolution possibles:

1. niveau minimal:
   sélection par emprise géométrique du maillage
   (`xmin`, `xmax`, `ymin`, `ymax`) et proximité des bords;
2. niveau intermédiaire:
   sélection par cellules dont le centroïde intersecte une zone support;
3. niveau robuste:
   sélection à partir des groupes physiques Gmsh ou d'un support spatial
   explicite attaché à la frontière.

La recommandation retenue est:

- conserver le niveau minimal uniquement comme compatibilité historique,
- prendre comme cible de conception le niveau robuste,
- baser en priorité la sélection sur les groupes physiques Gmsh ou sur un
  support spatial explicite attaché à la frontière.

### 7. Puits et termes sources / puits

Les puits sont aujourd'hui encore largement pensés en indices
`(lay, row, col)`.

Exemples:

- conversion `_well_cell_to_disv(...)`,
- résolution de cellule dans `FlowWellConfig.resolve_cell(...)`,
- stress-period data construite à partir d'indices structurés.

Pour être réellement générique, le contrat doit évoluer vers au moins un de
ces modes:

- ciblage direct par `(layer, cell2d)`,
- ciblage par coordonnées `(x, y)` avec localisation dans le maillage,
- ciblage par support spatial ou identifiant de zone.

La recommandation retenue est de faire du mode `(x, y)` l'interface
applicative principale:

- l'utilisateur ou la config exprime un puits en coordonnées `(x, y)`,
- une couche d'adaptation le projette vers le `cell2d` correspondant,
- la représentation solver interne reste ensuite en indices cellule-centriques.

Le mode `(layer, cell2d)` reste utile comme contrat interne et comme point
de test, mais pas comme interface principale de configuration.

### 8. Recharge hétérogène

Le cas de la recharge est intéressant car une partie de l'outillage existe
déjà pour les maillages irréguliers.

Aujourd'hui, dans `modflow6.py`, la recharge hétérogène différée s'appuie
encore sur la discrétisation sur grille structurée.

Mais le dépôt contient déjà:

- `discretize_fields_on_planar_mesh(...)`,
- `discretize_points_on_planar_mesh(...)`,

dans `hydromodpy/spatial/mesh/gmsh_grid/planar_forcing_discretization.py`.

Conclusion très pratique:

- il n'y a pas besoin d'inventer une nouvelle famille d'API pour la recharge,
- il faut surtout injecter le bon backend de discrétisation selon le
  `SolverMesh`.

### 9. Sorties et post-traitements

Les sorties sont l'un des points qui demandent le plus de vigilance.

Le code actuel MF6 est encore très orienté raster structuré:

- `_to_export_array(...)` reshape vers `(nrow, ncol)` quand c'est possible,
- `_write_solver_grid_template()` ne produit rien pour un maillage
  non structuré,
- `accumulation_flux` est explicitement limité au cas structuré,
- plusieurs sorties sont écrites comme GeoTIFF et non comme données
  cellule-centriques.

Pour des maillages Gmsh, la recommandation retenue est de prendre les sorties
natives maillage comme sortie de référence:

- tableaux plats par cellule,
- éventuellement `VTU`, `CSV`, `NPZ` ou `GeoPackage`,
- sans dépendre d'une rasterisation.

Les rasters ne doivent plus être la sortie normale du backend Gmsh. Au mieux,
ils restent une option explicite et secondaire pour certains usages
d'interopérabilité.

### 10. Transport

Le solveur de transport MF6 utilise déjà `GWTDISV`, ce qui est positif.

En revanche, `modflow_common/runtime_arrays.py` reste structuré:

- il attend `nrow` et `ncol`,
- il construit des tableaux `sconc` sous forme 2D/3D structurée,
- il ne sait pas exprimer un état initial directement en `(nlay, ncpl)`.

Conclusion:

- si l'objectif est d'avoir rapidement `GWF + GWT` sur Gmsh, alors
  `runtime_arrays.py` doit être généralisé tôt dans le chantier,
- cette généralisation ne doit pas être reléguée en toute fin,
- le contrat transport doit accepter des formes cellule-centriques et non
  seulement structurées.

## Ce qui peut devenir commun entre MODFLOW-NWT et MODFLOW 6

### Oui, la discrétisation temporelle doit être commune

C'est déjà presque un fait de code:

- même fonction appelée depuis les deux solveurs,
- même contrat d'entrée,
- même sortie,
- aucune dépendance aux packages spécifiques NWT ou MF6.

Le meilleur état cible est:

- une implémentation dans `modflow_common/discretization.py`,
- des éventuels re-exports minces depuis
  `modflow_nwt/modflow/discretization.py` et `modflow6/discretization.py`
  pour préserver la lisibilité et limiter les ruptures.

Pour garder une lecture simple, il est pertinent de séparer cette
discrétisation commune en deux fichiers:

- un fichier temporel pour la discrétisation du temps,
- un fichier dédié à l'extraction / construction 3D à partir du maillage plan
  et des surfaces.

### Oui, la partie surfaces + discrétisation verticale doit être commune

Les fonctions qui résolvent:

- `surface_topo`,
- `substratum`,
- la projection des surfaces vers un support plan,
- la construction de `top`, `botm`, `inactive_mask`,

ne dépendent pas du solveur final.

Elles doivent donc être communes.

La partie à rendre extensible n'est pas la physique verticale, mais le
backend de construction du maillage plan:

- backend cartésien,
- backend Gmsh.

### La partie spatiale complète doit devenir commune, mais avec dispatch

Le bon modèle n'est pas "une discrétisation pour NWT" et "une autre pour MF6".

Le bon modèle est:

- un pipeline spatial commun,
- avec un choix de backend plan,
- et une sortie unique `SolverGridContext`.

Ensuite seulement, chaque solveur instancie ses packages FloPy.

## Est-ce que `modflow_common` est bien commun aujourd'hui ?

Réponse courte: partiellement.

### Ce qui est vraiment bien placé dans `modflow_common`

Ces éléments sont effectivement communs et à leur place:

- `executables.py`
- `solver_mesh.py`
- `grid_context.py`

Ils portent des abstractions stables et solver-agnostiques.

### Ce qui est commun aux deux solveurs, mais pas encore vraiment générique

Ces éléments sont partagés entre NWT et MF6, mais restent marqués par une
vision structurée ou raster:

- `runtime_arrays.py`
- `raster_export.py`
- `routing_context.py`
- `masstransfer.py`

Ils sont "communs d'usage", mais pas "communs de modèle".

Autrement dit:

- leur emplacement dans `modflow_common` n'est pas aberrant,
- mais leur nom ou leur contrat laisse croire qu'ils sont universels alors
  qu'ils ne le sont pas encore.

### Ce qui manque probablement dans `modflow_common`

Le manque le plus net est l'absence d'un vrai module commun pour:

- la discrétisation temporelle,
- la résolution top/bottom commune,
- le dispatch spatial structuré / Gmsh.

En pratique, c'est ce vide qui explique que `modflow6` importe encore
`build_spatial_discretization(...)` depuis `modflow_nwt`.

### Recommandation d'organisation pour `modflow_common`

La recommandation n'est pas d'y tout mettre.

Le bon critère est:

- mettre dans `modflow_common` ce qui est conceptuellement solver-agnostique,
- laisser dans chaque solveur l'adaptation vers les packages et conventions
  spécifiques,
- éviter d'y placer trop tôt des helpers trop fins ou trop provisoires.

Donc:

- oui pour `discretization.py` commun,
- oui pour des helpers communs minimum sur les propriétés si nécessaire,
- non à un gros fourre-tout regroupant toute la logique NWT et MF6.

À moyen terme, une évolution encore plus lisible pourrait être:

- un noyau `solver_common` pour ce qui est réellement multi-solveur,
- un noyau `modflow_common` pour ce qui est spécifique à la famille MODFLOW,
- et des solveurs concrets (`modflow_nwt`, `modflow6`, `boussinesq`, etc.)
  qui consomment l'un ou l'autre selon leur niveau de proximité.

## Chaîne réelle de la commande jusqu'au solveur

### Ce que fait déjà la commande de launcher

L'analyse de la chaîne d'exécution montre que la commande de run prépare déjà
une bonne partie du contexte nécessaire avant l'appel au solveur.

Le chemin est, en simplifiant:

1. `launchers/process_simulation/launcher.py`
   charge la config et construit `LauncherRunState`
2. `HydroModPyLauncher.run()`
   exécute `setup`, `data`, puis les phases maillage
3. `_run_mesh_phase()` et `_run_mesh_input_phase()`
   chargent ou produisent les objets maillage runtime
4. ces objets sont stockés dans `state.setup`
5. `SimulationRunner.execute(...)`
   appelle l'adapter du solveur demandé
6. l'adapter construit le solveur puis appelle `pre_processing(...)`

Le point essentiel est que la commande prépare déjà:

- `state.setup.time_grid`
- `state.setup.mesh_summary`
- `state.setup.mesh_planar`
- `state.setup.mesh_bundle`

La chaîne de commande n'est donc pas le verrou principal.

### Ce qui manque aujourd'hui côté MODFLOW

Ce qui manque n'est pas le chargement du maillage dans le launcher, mais le
raccord entre ce maillage runtime et les adapters MODFLOW.

Aujourd'hui:

- `hydromodpy/solver/boussinesq/adapters/flow.py`
  exploite explicitement `state.setup.mesh_planar` et `state.setup.mesh_bundle`
- `hydromodpy/solver/modflow6/adapters/flow.py`
  ne regarde pas ces objets
- `hydromodpy/solver/modflow_nwt/adapters/flow.py`
  ne les regarde pas non plus
- `build_preprocess_options(...)` ne transmet que `time_grid`

Autrement dit:

- le launcher sait déjà charger un maillage Gmsh,
- Boussinesq sait déjà l'utiliser au runtime,
- la famille MODFLOW ne sait pas encore consommer ce runtime mesh dans sa
  couche adapter.

### Conclusion de cohérence

Le premier point d'injection cohérent entre "commande" et "plan
d'implémentation" n'est pas `modflow6.py` seul.

C'est le triplet suivant:

- `SetupContext`
  comme source canonique du maillage runtime
- `solver/modflow_common/flow_adapter_helpers.py`
  comme point de passage commun du launcher vers les solveurs MODFLOW
- la discrétisation commune appelée ensuite par `pre_processing(...)`

En d'autres termes, si l'on veut une architecture cohérente avec la commande
actuelle, la bonne logique est:

- le launcher charge le maillage une fois,
- l'adapter flow le transmet au backend solveur,
- la discrétisation commune décide comment en faire un `SolverMesh`.

### Pourquoi ce point est important pour le plan

Cela change légèrement l'ordre pratique du chantier.

Dans la note précédente, le coeur du plan restait:

- rendre commune la discrétisation,
- rendre MF6 compatible Gmsh,
- rapprocher l'organisation de NWT.

Cette analyse ajoute un point de méthode:

- il faut aussi prévoir très tôt le contrat runtime
  "launcher/adapters -> solveur".

Sinon, on risque:

- de rendre `build_spatial_discretization(...)` compatible Gmsh,
- sans qu'aucun adapter MODFLOW ne lui transmette effectivement le maillage
  chargé par la commande.

### Recommandation de raccordement runtime

La solution la plus cohérente me paraît être:

- conserver `state.setup.mesh_planar` et `state.setup.mesh_bundle` comme
  sources runtime canoniques,
- enrichir le contrat de préprocessing MODFLOW pour qu'il puisse recevoir
  un maillage runtime optionnel,
- centraliser cette transmission dans
  `hydromodpy/solver/modflow_common/flow_adapter_helpers.py`.

Deux variantes étaient possibles:

1. enrichir `ModflowPreprocessOptions`
   avec `mesh_planar` et éventuellement `mesh_bundle`
2. enrichir `pre_processing(...)`
   avec un argument explicite supplémentaire pour le maillage runtime

La recommandation retenue est la seconde:

- le maillage runtime doit être visible dans la signature de
  `pre_processing(...)`,
- cela rend la dépendance géométrique explicite,
- cela évite de surcharger un objet d'options avec un objet de structure
  runtime,
- et cela améliore la lisibilité du contrat solveur.

### Effet sur `modflow_common`

Cette lecture par la commande montre aussi que `modflow_common` n'est pas
seulement un réservoir de helpers solveur.

Il devient le bon lieu pour porter:

- le contrat runtime commun des solveurs MODFLOW,
- la discrétisation commune,
- et les options de préprocessing partagées.

Cela renforce la recommandation précédente:

- sortir le contrat commun hors de l'arborescence NWT,
- faire de `solver/modflow_common/flow_adapter_helpers.py` le point d'entrée
  unique côté launcher,
- et faire dépendre NWT et MF6 du même pipeline amont.

## Jonctions précises à traiter dans le dépôt

### 1. Export DISV

Fichier principal:

- `hydromodpy/spatial/mesh/adapters/flopy_adapter.py`

À traiter:

- valider l'orientation des polygones avant export `CELL2D`,
- éventuellement normaliser l'ordre des sommets si nécessaire,
- vérifier la cohérence centroïde / polygone,
- ajouter des diagnostics de cellules dégénérées.

### 2. Construction du `SolverMesh`

Fichiers principaux:

- `hydromodpy/solver/modflow_nwt/modflow/discretization.py`
- `hydromodpy/solver/modflow_common/solver_mesh.py`
- `hydromodpy/spatial/mesh/gmsh_grid/gmsh_planar_mesh.py`

À traiter:

- sortir la construction commune de discrétisation de l'arborescence NWT,
- ajouter un backend de maillage plan Gmsh,
- conserver un point d'entrée unique qui retourne `SolverGridContext`.

### 3. Mapping des propriétés

Fichiers principaux:

- `hydromodpy/solver/modflow_nwt/modflow/property_mapping.py`
- futur `hydromodpy/solver/modflow6/property_mapping.py`

À traiter:

- isoler la partie commune de résolution des propriétés,
- garder un backend structuré NWT,
- créer un backend cellulaire MF6,
- éviter que MF6 dépende durablement d'un mapping pensé d'abord pour NWT.

### 4. Conditions initiales, frontières, puits

Fichiers principaux:

- `hydromodpy/solver/modflow6/modflow6.py`
- `hydromodpy/process/flow/sinks_sources.py`
- `hydromodpy/process/flow/boundary_conditions.py`

À traiter:

- généraliser la sélection de cellules hors schéma `row/col`,
- supporter des localisations par `cell2d` et à terme par `(x, y)`,
- extraire la logique MF6 de construction des stress-period data.

### 5. Forçages hétérogènes

Fichiers principaux:

- `hydromodpy/spatial/mesh/cartesian_grid/sgrid_field_discretization.py`
- `hydromodpy/spatial/mesh/gmsh_grid/planar_forcing_discretization.py`
- `hydromodpy/solver/modflow6/modflow6.py`

À traiter:

- introduire un dispatch structuré / maillage plan pour la recharge,
- réutiliser les outils Gmsh existants au lieu de recréer une API parallèle.

### 6. Sorties et post-traitements

Fichiers principaux:

- `hydromodpy/solver/modflow6/modflow6.py`
- `hydromodpy/solver/modflow_common/raster_export.py`
- `hydromodpy/solver/modflow_common/masstransfer.py`
- `hydromodpy/solver/modflow_common/routing_context.py`

À traiter:

- séparer les sorties natives maillage des exports raster,
- expliciter les indicateurs qui restent structurés seulement,
- ajouter une politique claire de non-disponibilité ou de rasterisation
  explicite pour les maillages Gmsh.

## Réorganisation cible de `modflow6` au plus proche de `modflow_nwt`

### Constat de départ

`modflow_nwt/modflow` est déjà découpé en:

- `discretization.py`
- `property_mapping.py`
- `flow_to_modflow_adapter.py`
- `postprocess.py`
- `diagnostics.py`
- `nwt_options.py`
- `nwt_config.py`
- `nwt_solver.py`

`modflow6`, à l'inverse, contient aujourd'hui essentiellement:

- `modflow6.py`
- `modflow6_config.py`

### Recommandation d'architecture cible

La cible la plus cohérente est:

- `hydromodpy/solver/modflow6/modflow6.py`
  classe orchestratrice légère, assemblage des packages, exécution solver
- `hydromodpy/solver/modflow6/discretization.py`
  re-export ou wrappers fins vers la discrétisation commune
- `hydromodpy/solver/modflow6/property_mapping.py`
  projection des propriétés vers des tableaux MF6 cellule-centriques
- `hydromodpy/solver/modflow6/flow_to_modflow_adapter.py`
  adaptation `Flow` / `Domain` vers `IC`, `CHD`, `DRN`, `WEL`, `RCHA`
- `hydromodpy/solver/modflow6/postprocess.py`
  calculs de sorties et distinction mesh-native / raster
- `hydromodpy/solver/modflow6/diagnostics.py`
  validations `DISV`, diagnostics de géométrie et de cohérence de jeux de
  données
- `hydromodpy/solver/modflow6/modflow6_config.py`
  configuration spécifique MF6

### Ce qu'il faut garder dans `modflow6.py`

Il est préférable de garder dans `modflow6.py`:

- la classe `Modflow6`,
- la création de `MFSimulation`, `TDIS`, `IMS`, `GWF`, `NPF`, `STO`, `RCHA`,
  `WEL`, `CHD`, `DRN`, `OC`,
- l'enchaînement `pre_processing / processing / post_processing`,
- éventuellement `Modflow6Transport` dans un premier temps.

En revanche, il faut en sortir progressivement:

- la logique de mapping de propriétés,
- la construction des stress-period data,
- la logique détaillée des BC et wells,
- les post-traitements,
- les validations géométriques.

### Peut-on reprendre les mêmes noms que NWT ?

Oui, c'est recommandé quand cela n'introduit pas d'ambiguïté.

Cette symétrie de noms apporte:

- une meilleure lisibilité du dépôt,
- des points d'entrée prévisibles,
- une maintenance plus simple,
- la possibilité de comparer plus facilement les deux solveurs.

Il y a cependant deux réserves utiles:

- garder `modflow6.py` comme fichier principal évite de casser les imports
  actuels autour de la classe `Modflow6`,
- ne pas forcer une symétrie artificielle quand le contrat MF6 diffère
  réellement, par exemple autour de `DISV`.

### Que faire des options aujourd'hui importées depuis NWT ?

Le fait que `modflow6.py` importe encore `ModflowPreprocessOptions`,
`ModflowRunOptions` et `ModflowPostprocessOptions` depuis NWT montre une
dépendance de structure inutile.

La recommandation la plus propre est:

- déplacer ces options communes vers `modflow_common`,
- re-exporter ensuite depuis NWT si besoin pour compatibilité,
- faire consommer à MF6 la version commune et non celle rangée sous NWT.

### Peut-on supprimer la dépendance conceptuelle de MF6 à NWT pour les grilles régulières ?

Oui.

La bonne direction est:

- sortir la discrétisation commune de l'arborescence NWT,
- faire dépendre NWT et MF6 d'un module commun,
- garder la même construction cartésienne quand on reste sur une grille
  régulière,
- mais sans faire passer conceptuellement MF6 "par NWT".

Autrement dit, MF6 doit pouvoir consommer directement:

- soit un `SolverMesh` construit depuis la grille cartésienne,
- soit un `SolverMesh` construit depuis Gmsh.

Dans les deux cas, le solveur ne devrait voir qu'un `SolverMesh`.

## Proposition de plan d'implémentation progressif

### Phase 0. Sécurisation avant refactor

Objectif:

- geler le comportement actuel sur les cas structurés.

Actions:

- documenter les cas de référence MF6 structurés existants,
- ajouter ou compléter des tests d'intégration simples sur
  `pre_processing`,
- vérifier la forme des sorties actuelles `hk`, `sy`, `ss`, `strt`,
  `rch_spd`.

Vérifications attendues:

- mêmes dimensions qu'avant,
- mêmes fichiers écrits,
- mêmes résultats sur un cas structuré simple.

### Phase 1. Sortir la discrétisation commune de NWT

Objectif:

- éliminer la dépendance de structure `modflow6 -> modflow_nwt.discretization`
  sans changer le comportement.

Actions:

- créer un module commun de discrétisation,
- y déplacer la discrétisation temporelle,
- y déplacer la résolution de surfaces et la discrétisation verticale,
- conserver des wrappers fins dans les anciens emplacements si cela limite les
  régressions.

Vérifications attendues:

- `modflow_nwt` inchangé sur ses tests,
- `modflow6` inchangé sur ses tests,
- pas de différence sur les géométries structurées.

### Phase 2. Décomposer `modflow6.py` à comportement constant

Objectif:

- rapprocher l'architecture de MF6 de celle de NWT sans encore introduire
  Gmsh.

Actions:

- extraire `postprocess.py`,
- extraire `diagnostics.py`,
- extraire `flow_to_modflow_adapter.py`,
- laisser `modflow6.py` orchestrer seulement.

Vérifications attendues:

- aucun changement de résultats sur cas structuré,
- baisse nette de la taille et de la complexité de `modflow6.py`.

### Phase 3. Généraliser les propriétés vers un contrat cellulaire

Objectif:

- préparer MF6 à consommer directement des tableaux en `(nlay, ncpl)`.

Actions:

- introduire un mapping MF6 dédié,
- garder NWT sur son mapping structuré,
- factoriser seulement les helpers réellement communs,
- réduire le rôle de `flatten_from_grid(...)` à une compatibilité transitoire.

Vérifications attendues:

- mêmes `k`, `sy`, `ss` pour les cas structurés,
- comparaison cellule à cellule entre ancien et nouveau chemin.

### Phase 4. Introduire la construction Gmsh -> `SolverMesh`

Objectif:

- permettre à la discrétisation spatiale commune de produire un maillage
  solveur non structuré.

Actions:

- brancher un backend plan Gmsh dans la discrétisation commune,
- s'appuyer sur les briques déjà présentes côté `gmsh_grid`,
- ajouter les validations d'orientation et de qualité des polygones.

Vérifications attendues:

- `solver_mesh.to_disv_kwargs()` valide sur un petit cas triangulaire,
- `ModflowGwfdisv` s'instancie correctement,
- les couches verticales restent cohérentes.

### Phase 5. Généraliser recharge, puits et frontières

Objectif:

- faire fonctionner les principaux termes sources / limites sur les deux types
  de maillage.

Actions:

- recharge hétérogène via dispatch structuré / planar mesh,
- puits supportant `cell2d` puis `(x, y)`,
- frontières latérales revues pour sortir du tout `row/col`,
- support possible de groupes physiques Gmsh à moyen terme.

Vérifications attendues:

- cas structuré inchangé,
- cas Gmsh simple avec un puits et une recharge hétérogène,
- cas Gmsh simple avec une frontière imposée identifiable.

### Phase 6. Revoir les sorties

Objectif:

- éviter que le support Gmsh soit bloqué par un post-traitement raster-only.

Actions:

- définir des sorties natives maillage par défaut,
- garder les GeoTIFF seulement pour les cas structurés ou sur rasterisation
  explicite,
- isoler `accumulation_flux` comme indicateur structuré tant qu'il n'existe
  pas d'équivalent maillage.

Vérifications attendues:

- les sorties structurées historiques restent disponibles,
- les sorties Gmsh existent au moins sous forme de tableaux par cellule.

### Phase 7. Étendre au transport si nécessaire

Objectif:

- rendre GWT cohérent avec GWF sur maillage Gmsh.

Actions:

- généraliser `runtime_arrays.py`,
- permettre `sconc_init` et `sconc_input` en forme cellulaire,
- vérifier la chaîne `RCHA` auxiliaire concentration.

Vérifications attendues:

- cas structuré inchangé,
- petit cas GWT sur maillage triangulaire.

## Recommandation d'organisation cible

### Principe central

Le solveur doit dépendre d'un objet unique de géométrie:

- `SolverMesh`.

Le reste doit se structurer autour de ce principe:

- discrétisation commune produit `SolverMesh`,
- mapping des propriétés projette vers `SolverMesh`,
- adaptation des BC et sources cible `SolverMesh`,
- solveur FloPy consomme `SolverMesh`,
- post-traitements partent des sorties solver et reviennent vers
  `SolverMesh`.

### Principe de sobriété

Pour rester proche de NWT et de Boussinesq sans créer trop de fonctions:

- extraire seulement les vraies responsabilités,
- éviter les micro-helpers trop spécialisés,
- privilégier quelques modules stables et lisibles,
- ne pas dupliquer de gros pans de logique si un dispatch propre suffit.

### Organisation recommandée

La meilleure cible me semble être:

1. `modflow_common`
   contient les abstractions vraiment communes
2. `modflow_nwt/modflow`
   contient l'adaptation structurée spécifique NWT
3. `modflow6`
   contient l'adaptation `DISV` spécifique MF6
4. `gmsh_grid`
   reste la source de construction du maillage irrégulier
5. `SolverMesh`
   est le contrat unique qui relie géométrie, propriétés et solveurs

### Séparation recommandée entre backend cartésien et backend Gmsh

La séparation recommandée n'est pas:

- un solveur MF6 "structuré" d'un côté,
- et un solveur MF6 "non structuré" entièrement distinct de l'autre.

La séparation recommandée est plus locale:

- backend cartésien pour construire le maillage plan et projeter certains
  champs,
- backend Gmsh pour construire le maillage plan et projeter les champs
  associés,
- même contrat `SolverMesh` en sortie,
- même solveur MF6 en aval.

Cette approche garde le code plus lisible:

- on voit immédiatement où la divergence cartésien / Gmsh se situe,
- le reste du pipeline reste commun et plus facile à suivre,
- on évite de dupliquer toute la logique `GWF`, `GWT`, `NPF`, `STO`,
  `RCHA`, `CHD`, `WEL`, `OC`.

Décision retenue:

- ne pas maintenir une voie MF6 structurée spécifique continue en parallèle
  de la voie non structurée,
- garder uniquement une divergence locale de backend en amont,
- et conserver un pipeline solveur commun en aval.

## Risques principaux

- risque de régression sur les cas structurés si l'on mélange trop tôt
  refactor et nouvelle fonctionnalité Gmsh
- risque géométrique sur l'orientation des triangles et des polygones `DISV`
- risque d'hétérogénéité de contrats entre propriétés, recharge, BC et
  post-traitements
- risque de conserver trop de logique raster implicite dans des chemins qui
  devraient devenir mesh-native
- risque de sur-abstraction si l'on essaie d'unifier NWT et MF6 plus que de
  raison

## Décisions à prendre pour lancer la suite

Pour passer de l'analyse à l'implémentation, il manque surtout quelques
décisions de cadrage.

### 1. Cible du premier incrément

Décision retenue:

- commencer par le contrat runtime commun,
- mais avec un backend Gmsh activé d'abord uniquement pour MF6,
- puis poursuivre ensuite vers un contrat commun plus avancé.

### 2. Source géométrique canonique côté runtime

La discussion distingue deux besoins:

- la géométrie canonique minimale du maillage,
- les métadonnées enrichies utiles pour les frontières robustes et certains
  forçages.

L'état actuel du code montre que `GmshPlanarMesh2D` porte bien la géométrie
et la connectivité, mais ne conserve pas à lui seul les groupes physiques ou
des tags de frontière suffisamment riches pour satisfaire tout le besoin
"frontières robustes".

Décision retenue:

- adopter un couple `géométrie minimale + métadonnées de support`,
- prendre `state.setup.mesh_planar` comme source géométrique canonique
  minimale,
- conserver à côté un objet de métadonnées de support pour les groupes
  physiques, tags et informations de frontière,
- ne pas surcharger `mesh_planar` avec toutes les responsabilités métier,
- porter ces métadonnées dans une dataclass dédiée, explicite et propre,
  plutôt que dans un wrapper implicite du bundle.

### 2 bis. Dataclass dédiée de métadonnées de support

Le rôle exact de cette dataclass est de porter uniquement les informations de
support qui complètent la géométrie, sans ré-encoder toute la maille.

Nom recommandé:

- `GmshSupportMetadata` pour la dataclass,
- `mesh_support` pour le champ correspondant dans `state.setup`.

Elle ne doit donc pas contenir:

- la géométrie complète des sommets,
- la connectivité principale du maillage,
- les tableaux solver-ready déjà extraits.

Elle doit plutôt contenir des vues d'indexation et de qualification:

- groupes physiques Gmsh pertinents,
- tags de frontière,
- tags rivière ou autres supports hydrologiques,
- mappings légers cellule / arête / groupe,
- éventuels identifiants de support spatial externes.

L'objectif est de garder une séparation nette:

- `mesh_planar` dit "où sont les cellules et comment elles sont connectées",
- la dataclass de support dit "quelles cellules / arêtes portent quel sens
  métier".

### 2 ter. Emplacement et encapsulation de cette dataclass

La place la plus cohérente pour cette dataclass n'est ni dans
`process/flow`, ni dans `modflow_common`, ni dans le solveur MF6 lui-même.

La recommandation est:

- une dataclass définie dans la couche Gmsh/runtime,
- proche du chargement de maillage,
- indépendante des solveurs concrets,
- stockée ensuite dans `state.setup` au même titre que `mesh_planar`.

Cette organisation respecte mieux l'encapsulation:

- la couche Gmsh connaît les groupes physiques et leurs conventions,
- la couche launcher/runtime stocke l'objet préparé,
- l'adapter transmet cet objet sans le redéfinir,
- le solveur le consomme sans connaître le format brut du bundle.

### 2 quater. Cycle de vie recommandé

Le cycle de vie recommandé est:

1. chargement du maillage par le launcher
2. construction immédiate de la dataclass de support
3. stockage dans `state.setup`
4. transmission explicite à `pre_processing(...)`
5. consommation par la discrétisation et les adapters BC / puits

Cette séquence présente plusieurs avantages:

- pas de reconstruction répétée de la même information,
- pas de lecture intermédiaire de fichiers pour reconstruire les supports,
- pas de dépendance du solveur à un bundle brut plus lourd que nécessaire,
- une chaîne de responsabilité facile à relire.

### 2 quinquies. Contrat mémoire et absence de fichiers intermédiaires

Le contrat cible reste un contrat en mémoire vive:

- le launcher charge le maillage source,
- construit `mesh_planar`,
- construit la dataclass de support,
- stocke les deux dans `state.setup`,
- puis les adapters et solveurs les manipulent en mémoire.

Les écritures disque restent optionnelles et distinctes:

- entrées solver quand on écrit le modèle,
- sorties solver et post-traitement,
- éventuellement exports de diagnostic si on choisit de les activer.

La dataclass de support ne doit pas imposer de sérialisation intermédiaire
pour exister.

### 3. Mode de transmission du maillage au solveur

Décision retenue:

- enrichir explicitement la signature de `pre_processing(...)`
  avec un argument supplémentaire pour le maillage runtime,
- garder `ModflowPreprocessOptions` pour les vraies options d'exécution et de
  préparation, pas pour transporter un gros objet de structure.

### 4. Niveau de support du premier jalon

Décision retenue:

- procéder progressivement,
- commencer par géométrie + propriétés + IC,
- puis ajouter recharge,
- puis BC / puits,
- puis sorties,
- avec extension précoce au transport pour ne pas bloquer `GWT`.

### 5. Place du refactor `modflow6`

Il faut choisir si l'on:

- refactorise `modflow6.py` avant toute extension Gmsh,
- ou si l'on introduit un premier support Gmsh minimal puis on découpe.

Recommandation:

- faire au moins un petit refactor préalable du point de raccordement
  launcher/adapters/discretization,
- puis découper `modflow6.py` en parallèle du support Gmsh.

## Conclusion

La conclusion principale de cette analyse est la suivante:

- MODFLOW 6 est déjà, dans ce dépôt, beaucoup plus proche d'un solveur
  "maillage générique" qu'il n'y paraît,
- le format `DISV` est déjà la colonne vertébrale du backend MF6,
- la priorité n'est pas de réécrire `to_disv_kwargs`, mais de rendre
  commune et générique la construction du `SolverMesh`,
- la seconde priorité est de découper `modflow6.py` selon une structure très
  proche de `modflow_nwt`,
- la troisième priorité est de faire sauter les dernières hypothèses
  structurées dans les propriétés, BC, puits, recharge et sorties.

La trajectoire la plus sûre est donc:

- refactor d'abord,
- généralisation ensuite,
- validation progressive à chaque étape,
- et maintien d'une symétrie forte entre `modflow_nwt` et `modflow6`.
