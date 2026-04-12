# Perspective de developpement: calibration pilotee par simulation avec maillage factorise

Statut : conception cible avec premieres briques V1 implementees.

Ce document cadre une direction d'architecture pour brancher la calibration
sur le simulateur de flux sans reconstruire a chaque iteration tout le mapping
geometrique et tout le runtime de maillage.

L'objectif est de separer clairement :

- ce qui releve d'une preparation stable et factorisable,
- ce qui releve d'une actualisation rapide des proprietes,
- ce qui releve d'une extraction de sorties comparees aux observations.

Le cas d'usage cible est une calibration avec mises a jour repetees de
parametres hydrauliques et nombreuses evaluations du modele.

## Objet du document

Cette note repond a quatre questions liees :

- comment sortir les valeurs de proprietes du maillage lui-meme pour en faire
  des tableaux a part ;
- comment factoriser la partie maillage et plus generalement le runtime en une
  phase de preparation puis une phase d'actualisation ;
- comment raccorder ce schema a un futur launcher de calibration ;
- comment selectionner proprement les sorties a comparer, par exemple des
  charges, des flux ou des cartes de resurgence.

## Decisions actees pour V1

Les decisions suivantes sont considerees comme acquises pour la suite :

- `ModelCalibrationLauncher` vit dans `launchers/`, avec sa propre
  configuration, et pilote `CalibrationEngine`.
- la calibration doit etre multiobservables des la V1 ;
- la fonction objectif doit etre une fonction composite ponderee par blocs
  d'observables ;
- la V1 doit offrir une certaine flexibilite sur le choix des parametres a
  calibrer, mais sur des proprietes hydrauliques seulement ;
- le backend prioritaire de la V1 est `modflow6` ;
- la V1 cible en priorite `K` et `Sy`, et pas `Ss` ;
- la parametrisation par lithologie doit etre possible, sans etre obligatoire ;
- la parametrisation par lithologie doit etre visible dans le schema
  utilisateur des la V1 ;
- les observables de la V1 doivent couvrir a la fois :
  - des series temporelles ;
  - des scalaires agreges sur une fenetre ou une periode ;
- la frontiere `prepare` / `actualize` suit une interpretation stricte :
  `prepare()` doit inclure geometrie, supports spatiaux, selecteurs
  d'observables, et tous les mappings stables independants des candidats ;
- la strategie de mutation doit etre progressive :
  - V1 : partir encore des objets physiques et de `FieldParam`, mais en
    factorisant les projections geometriques ;
  - V2 : aller plus loin vers une mutation plus directe de tableaux solveur ;
- le contrat de sorties doit suivre trois niveaux :
  `RawRunOutputs -> CanonicalOutputBundle -> SelectedObservables` ;
- les structures pour les cartes de resurgence doivent etre prevues des la V1,
  mais leur calibration effective peut etre differee ;
- l'acces aux sorties doit suivre l'ordre de preference :
  runtime direct, puis postprocess memoire, puis lecture disque en dernier
  recours ;
- la persistance par defaut doit rester minimale, mais pour toutes les
  iterations.

## Diagnostic sur l'existant

## Etat d'implementation courant

Les briques suivantes sont maintenant presentes dans le depot :

- `hydromodpy.analysis.calibration.core.composite_objective` porte une
  fonction objectif composite ponderee par blocs, avec normalisation
  automatique des couts par IQR, puis ecart-type, puis seuil minimal.
- `CalibrationEngine` accepte un `objective_evaluator` composite en plus du
  contrat historique `observed/simulator`.
- `launchers/model_calibration` fournit un launcher dedie avec schema TOML,
  preparation de session, materialisation de configurations candidates,
  injection de parametres par chemins TOML, execution d'un candidat, lecture
  de sorties `calibration_outputs`/`outputs`, evaluation objective et
  persistance minimale JSONL.
- `ModelCalibrationLauncher.calibrate()` pilote maintenant `CalibrationEngine`
  en transformant chaque evaluation de parametres en run candidat du
  simulateur.
- `python -m launchers model-calibration run <config>` declenche la calibration
  complete et ecrit `calibration_result.json`.
- les echecs d'injection de parametres, de simulation ou d'evaluation objectif
  donnent un cout `+inf` et sont conserves dans l'historique minimal.
- la selection des sorties garde la compatibilite par nom d'observable et sait
  aussi lire une variable physique depuis `outputs`/`calibration_outputs`, avec
  interpolation ponderee pour les points et reduction simple pour les
  frontieres.
- `launchers/model_calibration/output_selection.py` isole maintenant le contrat
  `run_state -> CanonicalOutputBundle -> selected observables`.
- les demandes d'observables sont maintenant compilees une fois au `prepare`
  sous forme de `PreparedOutputSelector`, puis reutilisees pendant les
  evaluations de candidats.
- `launchers/model_calibration/property_arrays.py` introduit un contrat local
  `PropertyArraySet` pour representer `K` et `Sy` comme tableaux externes,
  avec modes globaux et lithologiques.
- les methodes qui exposent des echantillons de parametres (`gp_mapping`,
  `da_mh_gp`) produisent maintenant un artefact `model_distribution.json`
  interprete comme une distribution de modeles parametrises.
- `random_search` produit aussi un `model_distribution.json`, mais avec le
  role explicite `empirical_evaluated_model_ensemble` : il s'agit d'un ensemble
  empirique de candidats deja evalues, pas d'un posterior Bayesien.
- le launcher peut optionnellement relancer un sous-ensemble representatif de
  cette distribution avec sorties completes via
  `rerun_model_distribution_with_outputs`, et produire
  `model_distribution_reruns.json`.
- `persist_iteration_history = false` desactive l'ecriture JSONL des
  iterations tout en gardant le comptage et le dernier statut dans le
  manifeste.
- `persist_iteration_detail_level = "minimal"` reste le defaut strict ; les
  niveaux `"diagnostic"` et `"full"` ajoutent les informations de score, de
  blocs et de candidat dans l'historique JSONL quand elles sont demandees.
- `model_calibration.objective_mapping` fournit maintenant un diagnostic
  separe de cartographie de la fonction objectif : points CSV, grille JSON,
  figure PNG optionnelle, interpolation `idw`/`nearest`/`linear` et relances
  additionnelles parametrees sur un plan de coupe.
- `launchers/model_calibration/reporting.py` produit maintenant un
  `calibration_report.json` de synthese avec meilleur modele, statistiques
  d'iterations, contributions par bloc et resume des diagnostics ecrits.
- `actualize_candidate(...)` expose maintenant aussi un apercu
  `property_array_summary` des proprietes hydrauliques vectorisees du candidat,
  base sur les valeurs de reference quand elles sont inferrables depuis la
  configuration source.

Les limites restantes sont explicites :

- la selection des sorties dispose d'un `CanonicalOutputBundle` cote launcher,
  mais il reste a brancher ce contrat directement aux sorties solveur reelles ;
- les cartes de resurgence sont reservees dans le schema (`support = "map"`,
  `metric = "direct_cost"`), mais ne sont pas encore evaluables ;
- la parametrisation par lithologie dispose d'un premier contrat vectoriel
  (`PropertyArraySet`), mais son injection directe dans les solveurs reste a
  brancher ;
- l'apercu `property_array_summary` rendu par `actualize_candidate(...)`
  reste pour l'instant diagnostique : il n'est pas encore le contrat consomme
  directement par les adaptateurs solveur ;
- la factorisation fine du maillage et des tableaux de proprietes solveur
  reste la prochaine grande etape.
- la distribution de modeles reste volontairement legere par defaut : elle
  persiste des jeux de parametres et ne relance des simulations completes que
  si l'option dediee est activee.

Le depot contient deja plusieurs briques allant dans cette direction, mais
elles restent locales a certains appels et ne constituent pas encore un contrat
de runtime transversal.

Points d'appui principaux :

- `hydromodpy/solver/modflow_common/solver_mesh.py`
- `hydromodpy/solver/modflow_common/discretization_spatial.py`
- `hydromodpy/spatial/surface_sampling.py`
- `hydromodpy/spatial/field/core/field_param.py`
- `hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_fieldparam_discretization.py`
- `hydromodpy/solver/modflow_nwt/modflow/property_mapping.py`
- `hydromodpy/solver/modflow6/property_mapping.py`
- `hydromodpy/simulation/adapters/flow/boussinesq.py`
- `launchers/mesh_catchment/runtime_single_run.py`
- `hydromodpy/analysis/postprocess/timeseries/flow_timeseries.py`

Constats utiles :

- `SolverMesh` separe deja la geometrie plane, `top`, `botm` et le masque
  d'inactivite. C'est un bon support pour une phase preparee.
- `PreparedSurfaceSampler` applique deja le pattern "prepare once, sample many
  times" pour les surfaces.
- `discretize_fieldparam_on_sgrid(...)` et les `resolve_flow_property_arrays(...)`
  disposent deja de caches geometriques, mais ces caches sont recrees a
  l'echelle d'un appel et non a l'echelle d'une session de calibration.
- `FieldParam.to_mesh_field(...)` sait deja produire des valeurs par cellule
  a partir d'une discretisation de support, mais le contrat principal reste
  oriente "calculer des valeurs", pas "conserver une representation vectorielle
  reutilisable".
- les sorties de type `watertable_elevation`, `watertable_depth`,
  `seepage_areas`, `outflow_drain`, `accumulation_flux` existent deja cote
  postprocess et constituent un premier socle pour une couche de selection des
  observables.
- `modflow6` expose deja une chaine de sorties flow relativement exploitable
  pour une V1, alors que `boussinesq` reste plus heterogene selon les slices
  backend actuellement presentes dans le depot.
- le moteur de calibration existant reste structure autour d'un couple
  `observed 1D` / `simulator(params_dict) -> simulated 1D`, ce qui ne porte
  pas encore nativement une logique multiobservables par blocs.

## Reponse courte a la question de fond

Oui, le besoin est bien identifie :

- le maillage doit devenir un support geometrique prepare et immuable ;
- les proprietes doivent devenir des tableaux externes, remplacables ou
  recalculables rapidement ;
- la simulation doit pouvoir fonctionner en deux temps :
  `prepare` puis `actualize` ;
- les sorties a comparer doivent etre selectionnees par une couche d'extraction
  explicite, et non par lecture ad hoc de fichiers disperses.

## Principe cible

Le contrat de haut niveau vise est :

`config de reference -> prepare() -> actualize(params) -> run() -> canonicalize(outputs) -> select(observables) -> objective()`

Avec les responsabilites suivantes :

- `prepare()` construit tout ce qui est stable pour une famille de candidats ;
- `actualize(params)` ne touche qu'aux parametres variables et aux tableaux de
  proprietes ;
- `run()` execute le solveur sur la base preparee plus les tableaux actualises ;
- `canonicalize(outputs)` transforme les sorties solveur en variables
  physiques stables d'un point de vue metier ;
- `select(observables)` extrait les observables compares aux donnees ;
- `objective()` calcule la fonction composite ponderee par blocs.

## Architecture cible

### 1. PreparedSimulationContext

Objet central, cree une fois par configuration de reference.

Il regroupe :

- les objets runtime stables du launcher ;
- la geometrie plane et la geometrie solveur ;
- les surfaces et samplers prepares ;
- les supports spatiaux deja resolus ;
- les correspondances spatiales necessaires aux sorties ;
- les forcages et discretisations de conditions aux limites stables quand ils
  sont independants des parametres calibres ;
- les options d'execution qui ne changent pas entre candidats.

Ce contexte doit etre lisible, serialisable au besoin, et testable
independamment du solveur.

### 2. PreparedMeshGeometry

Objet dedie a la geometrie factorisee.

Il devrait contenir au minimum :

- le maillage planaire natif ;
- le `HydroMesh` pivot s'il est utile comme vue commune ;
- le `SolverMesh` ;
- les centroides, surfaces de cellules et longueurs caracteristiques ;
- `top`, `botm`, `inactive_mask` ;
- `layer_center_depths` et eventuellement `layer_thicknesses`.

Cet objet ne porte pas les valeurs hydrauliques variables.

Sa responsabilite est :

- la topologie ;
- la geometrie ;
- les conversions de forme ;
- les supports d'interpolation et d'indexation spatiale.

### 3. PreparedSupportMappings

Objet dedie aux projections geometriques couteuses qui servent au mapping des
proprietes.

Il stocke, pour chaque support spatial utile :

- l'identifiant du support ;
- la discretisation sur le maillage ;
- les cles de zones ;
- les fractions par cellule ;
- les metadonnees necessaires pour des mises a jour rapides.

Conceptuellement, il faut sortir ici ce qui est aujourd'hui recalcule dans
les caches locaux de :

- `sgrid_fieldparam_discretization.py`
- `modflow_nwt/modflow/property_mapping.py`
- `modflow6/property_mapping.py`

La forme cible la plus utile pour une calibration est une forme vectorielle du
type :

- `zone_keys`
- `fractions_by_zone`
- ou mieux une matrice compacte `A` telle que `values = A @ theta`

ou `theta` est le vecteur des valeurs de zones a calibrer.

### 4. PropertyArraySet

Objet dedie aux proprietes variables, separe du maillage.

Exemples de contenu :

- `hk_2d`
- `hk_3d`
- `sy_2d`
- `sy_3d`
- `ss_2d`
- `ss_3d`
- `drainage_conductance`
- `recharge_multiplier_field`

Point important :

- le maillage ne doit plus etre le support principal de l'etat variable ;
- les snapshots avec valeurs sur maillage restent utiles pour export ou debug ;
- le contrat runtime doit toutefois passer d'abord par des tableaux purs.

### 5. RawRunOutputs

Objet dedie aux sorties telles qu'elles sont produites par le solveur ou par
son adaptateur.

Il peut contenir :

- des objets runtime solveur ;
- des tableaux deja extraits ;
- des handles memoire vers des produits de postprocess ;
- en dernier recours, des references vers des artefacts disque.

Cet objet ne doit pas etre expose directement a la logique de calibration.

### 6. CanonicalOutputBundle

Objet dedie a la normalisation metier des sorties.

Il transforme `RawRunOutputs` en variables stables d'un point de vue
hydrologique, independantes du solveur.

Exemples de variables canoniques :

- `head`
- `watertable_elevation`
- `watertable_depth`
- `outlet_discharge`
- `drainage_flux`
- `accumulation_flux`
- `seepage_map`
- `storage`

### 7. PreparedOutputSelectors

Objet dedie a l'extraction des observables a comparer.

Il compile une fois :

- les selections spatiales ;
- les selections verticales ;
- les selections temporelles ;
- les reductions a appliquer.

Cela permet de ne pas redecider a chaque candidat :

- quelle cellule correspond a quel piezometre ;
- quel masque correspond a telle zone de resurgence ;
- quelle frontiere ou quel ensemble de cellules definit un flux compare ;
- quels pas de temps sont retenus.

### 8. SelectedObservables

Objet dedie a la materialisation finale des observables retenus pour la
comparaison.

Il doit porter :

- les series, scalaires ou cartes reduites selectionnees ;
- les observations associees ;
- les metadonnees de bloc ;
- les metriques a appliquer bloc par bloc.

### 9. CompositeObjectiveDefinition

Objet dedie a la combinaison des blocs d'observables.

Il doit permettre de definir, pour chaque bloc :

- la liste des observables qu'il consomme ;
- la metrique a appliquer ;
- le poids du bloc ;
- la regle de reduction en cout.

Le cout total est ensuite une somme ponderee des couts de blocs.

## Pourquoi sortir les valeurs du maillage

Le maillage doit rester un objet de geometrie.

Si les proprietes variables sont stockees comme etat principal dans les cellules
du maillage, on melange :

- la topologie ;
- les champs physiques ;
- les snapshots de postprocess ;
- la logique d'actualisation.

Cela pose probleme pour une calibration car :

- on fait des mises a jour repetees ;
- on veut eviter de reconstruire les relations geometriques ;
- on veut raisonner en termes de tableaux vectoriels et d'operateurs ;
- on veut pouvoir comparer ou stocker plusieurs jeux de proprietes sur une meme
  geometrie preparee.

La recommandation est donc :

- `HydroMesh` et `SolverMesh` restent geometriques ;
- les tableaux de proprietes vivent a part ;
- l'attachement des valeurs au maillage devient une operation secondaire de
  visualisation, d'export ou de diagnostic.

## Ce qui doit etre factorise dans la phase prepare

### Geometrie et maillage

La phase prepare doit construire une fois :

- le maillage planaire ;
- l'extrusion ou la discretisation verticale ;
- le `SolverMesh` ;
- les samplers de surfaces ;
- les centres de cellules ;
- les epaisseurs et profondeurs de couches ;
- les correspondances entre maillage natif et vues solveur.

### Supports spatiaux

La phase prepare doit aussi construire une fois :

- les supports `Field` resolus depuis `domain` ;
- leur projection sur le maillage ;
- les fractions par cellule ;
- les masques ou index de zones utiles aux objectifs.

### Forcages et conditions aux limites stables

La phase prepare doit aussi construire une fois, quand c'est compatible avec
le perimetre des parametres calibres :

- les discretisations de forcages non calibres ;
- les discretisations de conditions aux limites non calibrees ;
- les correspondances spatio-temporelles stables vers les sorties.

### Selection des sorties

La phase prepare doit compiler une fois :

- les points d'observation de charge ;
- les lignes, frontieres ou polygones de flux ;
- les emprises de comparaison pour les cartes ;
- les fenetres temporelles ;
- les eventuelles ponderations spatiales ou temporelles.

## Ce qui doit rester dans la phase actualize

La phase actualize prend un vecteur de parametres et ne fait que :

- construire ou mettre a jour les tableaux de proprietes ;
- injecter ces tableaux dans le solveur ou l'adaptateur ;
- preparer uniquement les termes runtime qui dependent effectivement des
  proprietes hydrauliques calibrees ;
- lancer le run.

Elle ne doit pas refaire :

- la lecture du maillage ;
- la discretisation du support geometrique ;
- le calcul des fractions de zones ;
- le couplage point-observation vers cellules ;
- la definition des fenetres de comparaison.

## Perimetre V1 des parametres calibres

La V1 doit rester flexible, mais dans un perimetre volontairement borne :
proprietes hydrauliques uniquement.

Backend prioritaire de la V1 :

- `modflow6` seulement.

Formes de parametrisation a couvrir en priorite :

- valeur homogene d'une propriete hydraulique ;
- valeurs par zone ou par lithologie via `values_by_key`, quand ce mode est
  souhaite ;
- facteur multiplicatif global applique a une propriete hydraulique ;
- facteurs par couche pour une propriete hydraulique ;
- facteurs par support spatial deja prepare.

Familles de proprietes visees en priorite :

- `K`
- `Sy`
- variantes directes ou facteurs derives de ces proprietes

Hors perimetre V1 :

- geometrie et maillage ;
- forcages climatiques ;
- structure des conditions aux limites ;
- parametres non hydrauliques ;
- definition des observables eux-memes.

## Strategie de mutation progressive

La mutation doit suivre deux etapes conceptuelles :

- V1 :
  partir encore des objets `Flow` et `FieldParam` comme source physique de
  verite, mais preparer a l'avance les projections geometriques et les
  correspondances spatiales ;
- V2 :
  aller vers des mises a jour plus directes de tableaux solveur quand les
  gains de performance et la lisibilite justifient cette evolution.

## Operateurs vectoriels recommandes

Une fois la phase prepare en place, l'actualisation doit se faire via des
operateurs de tableaux simples et explicites.

Operations a couvrir en priorite :

- `replace`
- `scale`
- `add`
- `clip`
- `apply_mask`
- `apply_zone_mapping`
- `apply_layer_factors`

Exemples d'usage :

- remplacer une valeur unique globale de `K` ;
- mettre a jour un vecteur de valeurs par lithologie ;
- appliquer un facteur multiplicatif par couche ;
- borner les valeurs physiques apres mise a jour ;
- construire un champ cellule par cellule a partir d'une matrice de fractions.

## Sorties a comparer : principe general

La calibration ne doit pas dependre directement d'un format solver ou d'un
fichier particulier.

La chaine cible est la suivante :

`RawRunOutputs -> CanonicalOutputBundle -> PreparedOutputSelectors -> SelectedObservables`

Ordre de preference recommande :

- extraction runtime directe ;
- extraction depuis un bundle de postprocess en memoire ;
- lecture disque seulement si aucune autre option n'est disponible.

## Multiobservables des la V1

Le multiobservables doit etre supporte des la premiere implementation.

Le principe recommande est de raisonner par blocs d'observables.

Un bloc represente une famille coherente d'observations, par exemple :

- un bloc de charges piezometriques ;
- un bloc de flux d'exutoire ;
- un bloc de drainage ou de resurgence ;
- un bloc cartographique.

Chaque bloc doit porter :

- ses observables selectionnees ;
- ses observations de reference ;
- sa metrique ;
- son poids ;
- sa contribution au cout total.

En V1, un bloc peut materialiser :

- soit une ou plusieurs series temporelles ;
- soit un ou plusieurs scalaires agreges sur une fenetre temporelle ou une
  periode d'interet.

## Fonction objectif composite

La fonction objectif de V1 doit etre une somme ponderee de couts de blocs.

Forme generale recommandee :

`cost_total = sum(weight_i * cost_i)`

ou :

- `cost_i` est le cout d'un bloc d'observables ;
- `weight_i` est le poids du bloc ;
- les poids peuvent etre normalises avant aggregation.

Selon les blocs, `cost_i` peut provenir :

- soit d'une metrique classique appliquee a des observations et simulations ;
- soit d'un operateur de comparaison specialise qui produit deja un cout ou un
  score directement exploitable, par exemple sur une carte binaire.

Cette approche permet :

- de melanger charges, flux et cartes ;
- de garder des metriques distinctes par bloc ;
- de garder un diagnostic lisible par type d'observable.

## Normalisation automatique recommandee

La normalisation automatique vise ici deux choses differentes :

- normaliser les poids pour que leur somme soit 1 ;
- normaliser les couts de blocs pour eviter qu'un bloc domine uniquement a
  cause de son unite ou de son ordre de grandeur.

Recommandation par defaut :

- normalisation des poids :
  `weight_i_normalized = weight_i / sum(weight_j)` ;
- normalisation des couts de blocs :
  - pour les couts deja sans dimension, par exemple `1 - NSE`, `1 - KGE`,
    `1 - IoU`, utiliser une echelle de reference egale a 1 ;
  - pour les couts dimensionnels, par exemple `RMSE` ou `MAE`, diviser par une
    echelle caracteristique du bloc observe.

Echelle caracteristique recommandee pour un bloc observe :

- V1 : ecart interquartile du bloc observe, avec repli sur l'ecart-type si
  l'IQR est nul ou non defini ;
- plancher numerique strict pour eviter toute division par zero.

Forme recommandee :

`normalized_cost_i = raw_cost_i / reference_scale_i`

puis :

`cost_total = sum(weight_i_normalized * normalized_cost_i)`

Cette proposition a deux avantages :

- elle rend les blocs plus comparables sans perdre leur logique propre ;
- elle reste simple a diagnostiquer et a expliquer.

Decision par defaut pour V1 :

- cette normalisation automatique est retenue comme comportement par defaut du
  launcher de calibration.

## Impact sur CalibrationEngine

Le moteur actuel reste centre sur un couple :

- `observed` 1D ;
- `simulator(params_dict) -> simulated` 1D de meme forme.

Cela signifie qu'un vrai multiobservables par blocs n'est pas represente
nativement aujourd'hui.

La recommandation pour la V1 est donc :

- garder `ModelCalibrationLauncher` comme orchestrateur principal ;
- garder `CalibrationEngine` comme moteur d'optimisation ;
- assumer une extension du coeur de calibration pour supporter une evaluation
  composite par blocs.

Forme recommandee de cette extension :

- introduire un module dedie, par exemple
  `hydromodpy/analysis/calibration/core/composite_objective.py` ;
- faire accepter a `CalibrationEngine` un evaluateur composite en plus du
  contrat historique `observed/simulated`.

Cette direction est preferable a un contournement purement launcher, car le
multiobservables fait partie du coeur de la logique de calibration.

## Types de selecteurs de sorties

### 1. Charges ou niveaux

Cas typique :

- charge hydraulique en un point ;
- niveau de nappe en un piezometre ;
- charge moyenne sur une zone.

Selecteur propose : `PointHeadSelector` ou `ZoneHeadSelector`.

Preparation :

- projection du point XY sur la cellule ou sur plusieurs cellules ;
- choix de la regle verticale :
  - nappe ;
  - couche fixe ;
  - intervalle crepine ;
- compilation des pas de temps utiles.

Actualisation / extraction :

- lecture de la variable canonique ;
- interpolation ponderee par defaut, avec selection simple seulement comme
  option de repli ;
- reduction temporelle eventuelle.

La V1 doit supporter deux formes :

- la serie temporelle complete extraite sur les pas de temps retenus ;
- un scalaire agrege sur une fenetre, par exemple moyenne, mediane, minimum,
  maximum ou somme selon la variable.

### 2. Flux

Cas typique :

- debit a l'exutoire ;
- flux de drainage sur une zone ;
- flux integre a travers une frontiere ;
- flux d'accumulation dans un sous-bassin.

Selecteur propose : `FluxAggregateSelector`.

Preparation :

- compilation du support spatial :
  - liste de cellules ;
  - frontiere ;
  - ligne ;
  - polygone ;
- choix de la reduction :
  - somme ;
  - moyenne ;
  - somme ponderee ;
- compilation des pas de temps.

Actualisation / extraction :

- lecture de la variable canonique ;
- application du masque ou des index prepares ;
- reduction en scalaire ou serie.

La V1 doit supporter deux formes :

- la serie temporelle du flux retenu ;
- un scalaire agrege sur une fenetre ou une periode.

### 3. Cartes de resurgence

Cas typique :

- comparaison d'une carte de zones en emergence ;
- comparaison d'une emprise de seepage observee ;
- comparaison d'un motif spatial de surface exfiltrante.

Selecteur propose : `MapSelector`.

Preparation :

- definition de l'emprise d'etude ;
- choix du support de comparaison :
  - maillage natif ;
  - raster cible ;
  - masque binaire ;
- compilation du seuil de classification si besoin ;
- compilation des dates ou de la fenetre temporelle.

Actualisation / extraction :

- lecture de `seepage_map` ou de la variable equivalente ;
- eventuel seuillage ;
- resampling seulement si necessaire ;
- calcul de la metrique.

Statut recommande pour la V1 :

- les structures de configuration, de preparation et de selection doivent etre
  prevues ;
- la calibration effectivement active sur ce type de bloc peut rester differee
  a une iteration ulterieure.

## Recommandation importante sur les cartes

Pour les cartes de resurgence, il vaut mieux eviter de commencer par une
comparaison brute cellule a cellule.

Approche plus robuste pour une V1 :

- aire totale en resurgence ;
- proportion de surface active ;
- score binaire de type IoU ou F1 sur une carte seuillee ;
- moyennes zonales ;
- profils ou agregations spatiales simples.

Cette approche :

- est moins bruyante numeriquement ;
- limite la sensibilite au detail du maillage ;
- simplifie le contrat d'objectif ;
- rend les tests plus stables.

## Contrat de configuration propose

Un futur launcher pourrait exposer trois familles de configuration :

- les parametres calibres ;
- les sorties a extraire ;
- les objectifs de comparaison.

Exemple conceptuel :

```toml
[model_calibration]
simulation_config = "run_flow_reference.toml"
calibration_id = "flow_case_01"
disable_display = true
disable_postprocess = true
rerun_best_with_outputs = true
persist_model_distribution = true
rerun_model_distribution_with_outputs = false
model_distribution_max_reruns = 10
model_distribution_rerun_selection = "representative"
persist_iteration_history = true
persist_iteration_detail_level = "minimal"

[model_calibration.objective_mapping]
enabled = false
axes = ["K_global_factor", "Sy_global"]
additional_runs = 0
sampling = "adaptive"
interpolation = "idw"
grid_size = 60

[[model_calibration.parameter]]
name = "K_global_factor"
target = "flow.param.K"
mode = "replace"
parameterization = "global_factor"

[[model_calibration.parameter]]
name = "Sy_global"
target = "flow.param.Sy"
mode = "replace"
parameterization = "global_value"

# Variante optionnelle par lithologie :
#
# [[model_calibration.parameter]]
# name = "K_alluvium"
# target = "flow.param.K.values_by_key.alluvium"
# mode = "replace"
# parameterization = "lithology_value"

[[model_calibration.output]]
name = "pz_01"
variable = "watertable_elevation"
source = "runtime"
support = "point"
x = 845123.0
y = 6543210.0
time = "all"
reducer = "weighted_interpolation"

[[model_calibration.output]]
name = "q_outlet"
variable = "outlet_discharge"
source = "runtime"
support = "boundary"
boundary_id = "east_side"
time = "all"
reducer = "sum"

[[model_calibration.output]]
name = "q_outlet_lowflow_mean"
variable = "outlet_discharge"
source = "runtime"
support = "boundary"
boundary_id = "east_side"
time_window = ["2020-08-01", "2020-09-30"]
time_reducer = "mean"
reducer = "sum"

[[model_calibration.objective_block]]
name = "heads"
metric = "rmse"
weight = 1.0
uses_outputs = ["pz_01"]
normalize_cost = true

[[model_calibration.objective_block]]
name = "outlet_flux"
metric = "rmse"
weight = 1.0
uses_outputs = ["q_outlet", "q_outlet_lowflow_mean"]
normalize_cost = true

# Structures cartographiques prevues pour une iteration ulterieure :
#
# [[model_calibration.output]]
# name = "resurgence_lowflow"
# variable = "seepage_map"
# source = "postprocess"
# support = "map"
# time_window = ["2020-08-01", "2020-09-30"]
# comparison = "iou"
# threshold = 1e-6
#
# [[model_calibration.objective_block]]
# name = "resurgence_map"
# metric = "direct_cost"
# weight = 0.5
# uses_outputs = ["resurgence_lowflow"]
```

## Gestion des echecs de simulation

La calibration doit integrer explicitement le fait que certains candidats
peuvent :

- ne pas converger ;
- produire des sorties invalides ;
- echouer pendant l'injection des parametres ;
- echouer pendant l'extraction des observables.

Proposition par defaut pour la V1 :

- un candidat en echec recoit `cost_total = +inf` ;
- les valeurs d'objectif par bloc peuvent rester vides ou `+inf` selon le
  stade de l'echec ;
- aucune relance automatique n'est faite par defaut ;
- le run suivant peut continuer sans polluer le contexte prepare ;
- le meilleur candidat connu jusque-la reste inchange.
- un statut court et un motif court d'echec sont persistes pour
  l'iteration concernee.

Classification utile des echecs :

- `parameter_injection_failed`
- `solver_run_failed`
- `invalid_outputs`
- `output_selection_failed`
- `objective_evaluation_failed`

## Persistance minimale par iteration

La persistance par defaut doit etre legere mais systematique.

Pour chaque iteration, il est recommande de conserver au minimum :

- `iteration_id`
- le vecteur de parametres
- la vue nommee des parametres
- la valeur de la fonction objectif totale
- les valeurs de fonction objectif par bloc
- le statut d'iteration
- le motif court d'echec quand il existe

Par defaut, on ne conserve pas :

- les sorties completes du solveur ;
- les rasters intermediaires ;
- les fichiers de postprocess complets ;
- les maillages enrichis pour chaque candidat.

La relance du meilleur candidat avec sorties completes doit rester une option
explicite du launcher. La relance d'une distribution de modeles doit etre une
deuxieme option explicite, limitee par `model_distribution_max_reruns`, pour
eviter de transformer automatiquement une calibration stochastique en campagne
massive de postprocess.

Le niveau `minimal` doit rester suffisant pour reconstruire une cartographie
simple de la fonction objectif : parametres, objectif total, contributions par
bloc et statut. Les niveaux `diagnostic` et `full` sont reserves aux analyses
plus fines et ne doivent pas devenir le mode par defaut.

## Cartographie de la fonction objectif

La cartographie est volontairement separee dans
`launchers/model_calibration/objective_mapping.py`. Elle n'appartient pas au
coeur HydroModPy et ne doit pas modifier la logique d'optimisation : elle
exploite les simulations deja realisees, puis ajoute optionnellement quelques
simulations de diagnostic.

Contrat actuel :

- `enabled = false` par defaut ;
- `axes = ["param_a", "param_b"]` choisit le plan 2D cartographie ;
- si `axes` est absent, les deux premiers parametres sont utilises ;
- avec plus de deux parametres, les autres parametres sont fixes au meilleur
  jeu de parametres connu ;
- `additional_runs` demande des simulations supplementaires sur cette coupe ;
- `sampling = "adaptive"` privilegie les zones localement variables et peu
  couvertes ;
- `sampling = "latin_hypercube"` donne une couverture plus neutre ;
- `interpolation = "idw"` est le defaut robuste sans dependance forte ;
- `interpolation = "nearest"` sert de diagnostic sans lissage ;
- `interpolation = "linear"` utilise `scipy.interpolate.griddata` si disponible
  et bascule sur `idw` en secours ;
- les artefacts ecrits sont `objective_mapping_points.csv`,
  `objective_mapping_grid.json` et, si possible, `objective_mapping.png`.

Cette cartographie doit etre interpretee comme une surface empirique de la
zone exploree, pas comme une evaluation exhaustive de l'espace des parametres.
Les points `+inf` ou en echec sont conserves dans le CSV et visualises comme
echecs quand la figure est produite.

## Cycle d'execution cible

### Phase 1 : prepare

1. Charger la configuration de simulation de reference.
2. Construire les objets runtime stables du launcher.
3. Construire le maillage et la geometrie solveur.
4. Preparer les surfaces et samplers.
5. Resoudre les supports spatiaux et leurs discretisations.
6. Compiler les selecteurs de sorties.
7. Produire un `PreparedSimulationContext`.

### Phase 2 : actualize

1. Recevoir un vecteur de parametres candidats.
2. Le convertir en `PropertyArraySet`.
3. Injecter ces tableaux dans le solveur ou dans l'adaptateur.
4. Executer le run.
5. Construire un `CanonicalOutputBundle`.
6. Appliquer les `PreparedOutputSelectors`.
7. Retourner le vecteur d'observables et le score.

### Phase 3 : finalisation

1. Persister le meilleur jeu de parametres.
2. Persister la distribution de modeles quand la methode en fournit une.
3. Relancer si besoin le meilleur candidat avec sorties completes.
4. Relancer si besoin un sous-ensemble representatif de la distribution avec
   sorties completes.
5. Archiver les diagnostics de calibration.

## Impacts d'implementation recommandes

### Nouveau launcher

Creer un launcher dedie, par exemple :

- `launchers/model_calibration/config.py`
- `launchers/model_calibration/launcher.py`
- `launchers/model_calibration/runtime.py`
- `launchers/model_calibration/parameter_injection.py`
- `launchers/model_calibration/output_selection.py`
- `launchers/model_calibration/objective_blocks.py`
- `launchers/model_calibration/failure_policy.py`
- `launchers/model_calibration/persistence.py`
- `launchers/model_calibration/reporting.py`

### Couche de preparation

Introduire des dataclasses ou contrats clairs :

- `PreparedSimulationContext`
- `PreparedMeshGeometry`
- `PreparedSupportMappings`
- `PropertyArraySet`
- `RawRunOutputs`
- `CanonicalOutputBundle`
- `PreparedOutputSelectors`
- `SelectedObservables`
- `CompositeObjectiveDefinition`

### Adaptateurs solveur

Les adaptateurs flow doivent pouvoir consommer :

- une geometrie preparee ;
- un paquet de tableaux de proprietes ;
- un contrat de sorties canoniques.

Ils ne doivent plus etre obliges de remonter eux-memes de la configuration a
toute la discretisation geometrique a chaque evaluation.

### Noyau calibration

Le multiobservables par blocs impose vraisemblablement une extension minimale
du coeur de calibration, par exemple dans :

- `hydromodpy/analysis/calibration/core/engine.py`
- ou un nouveau module de type
  `hydromodpy/analysis/calibration/core/composite_objective.py`

## Proposition de tests

### Tests unitaires

- construction de `PreparedMeshGeometry` sur maillage structure et non
  structure ;
- construction de `PreparedSupportMappings` a partir de supports simples ;
- generation de `PropertyArraySet` par operateurs vectoriels ;
- compilation des selecteurs de sorties ;
- extraction d'observables sur un `CanonicalOutputBundle` synthetique.
- evaluation d'une fonction composite ponderee par blocs.

### Tests d'integration techniques

- `prepare()` ne doit etre appele qu'une fois pour plusieurs candidats ;
- `actualize()` ne doit pas reconstruire les mappings geometriques ;
- deux candidats differents doivent reutiliser la meme geometrie preparee ;
- le run doit pouvoir retourner des sorties exploitables sans postprocess
  disque complet.
- un candidat en echec doit donner `+inf` sans casser la boucle de calibration.
- la persistance minimale doit etre ecrite pour toutes les iterations.
- une methode Bayesienne/stochastique doit produire une distribution de
  modeles.
- la relance optionnelle d'un sous-ensemble de distribution doit ecrire un
  manifeste dedie sans ajouter d'entrees a l'historique minimal d'iterations.

### Tests d'integration metier

- calibration sur un bloc de charges ;
- calibration sur un bloc de flux d'exutoire ;
- calibration composite avec combinaison charge + flux ;
- preparation et validation d'un bloc cartographique de resurgence sans
  activation de sa calibration.

### Tests de non-regression

- ne pas casser `process_simulation` hors calibration ;
- ne pas casser `mesh_catchment` ;
- ne pas casser les mappings `FieldParam` existants ;
- ne pas imposer de mutation du `HydroMesh` pour les usages historiques.

## Risques et points de vigilance

- si l'on garde trop longtemps des caches implicites et disperses, on obtient
  une architecture difficile a raisonner ;
- si l'on stocke encore l'etat variable principal dans le maillage, la
  calibration restera couteuse et peu lisible ;
- si l'extraction des sorties repose d'abord sur les fichiers disque, le cout
  et la fragilite runtime resteront eleves ;
- la comparaison brute de cartes peut etre trompeuse si le support de sortie
  varie trop d'un cas a l'autre ;
- la phase `actualize` ne doit pas devenir une pseudo-phase `prepare` cachee.
- une extension mal dessinee du moteur de calibration peut rendre le
  multiobservables difficile a maintenir.

## Recommandation finale

La trajectoire conseillee est :

- V1 : separer explicitement geometrie preparee, tableaux de proprietes et
  selection des sorties ;
- V1 : limiter les parametres calibres aux proprietes hydrauliques, mais avec
  une parametrisation flexible ;
- V1 : cibler `modflow6` comme backend flow prioritaire ;
- V1 : cibler `K` et `Sy`, avec parametrisation par lithologie optionnelle ;
- V1 : supporter le multiobservables par blocs avec fonction composite
  ponderee ;
- V1 : supporter des series temporelles et des scalaires agreges par fenetre ;
- V1 : utiliser par defaut `RMSE` pour les blocs `heads` et `flux` ;
- V1 : utiliser une interpolation ponderee par defaut pour les observables
  ponctuels de type charge ;
- V1 : activer par defaut la normalisation automatique des poids et des couts
  de blocs ;
- V1 : garder un run complet par candidat, mais sans refaire les mappings
  geometriques ;
- V1 : introduire une extension minimale du noyau calibration pour supporter
  une evaluation composite ;
- V1 : prevoir les structures des blocs cartographiques de resurgence sans les
  activer encore en calibration ;
- V1 : persister les distributions de modeles pour les methodes
  Bayesiennes/stochastiques ;
- V1 : permettre une relance optionnelle et bornee d'un sous-ensemble de ces
  modeles avec sorties completes ;
- V2 : optimiser plus finement l'injection runtime et les sorties si le cout
  solveur devient le verrou dominant.

En synthese :

- le maillage doit etre factorise ;
- les proprietes doivent devenir des tableaux a part ;
- la simulation doit suivre un schema
  `prepare -> actualize -> run -> canonicalize -> select -> objective` ;
- les sorties de calibration doivent etre selectionnees par une couche dediee,
  capable de gerer des charges, des flux et des cartes de resurgence ;
- la V1 cible d'abord `modflow6` ;
- la fonction objectif doit etre composite et ponderee par blocs ;
- la V1 se concentre sur `K` et `Sy` ;
- la lithologie est optionnelle mais exposee dans le schema utilisateur ;
- la V1 couvre des series temporelles et des scalaires agreges ;
- `RMSE` est la metrique par defaut pour les blocs `heads` et `flux` ;
- l'extraction ponctuelle des charges utilise une interpolation ponderee par
  defaut ;
- la normalisation automatique est activee par defaut ;
- la persistance doit rester minimale par iteration ;
- les methodes Bayesiennes/stochastiques doivent pouvoir produire une
  distribution de modeles, avec relance complete seulement sur option.
