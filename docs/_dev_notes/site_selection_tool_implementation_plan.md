# Plan d'implementation - outil de selection de sites HydroModPy

Date: 2026-05-12
Mise a jour: 2026-05-26

Statut: document de conception et de planification. Ce fichier detaille une
brique specifique: un outil independant de selection de sites, place en amont
des testbeds, regional labs, comparaisons et campagnes de calibration. La mise
a jour du 2026-05-15 recentre le plan sur une implementation progressive en
rassemblant les briques deja presentes dans le depot.

Document parent: `docs/_dev_notes/national_headwater_deployment_audit.md`.

Document voisin a ne pas fusionner ici:
`docs/_dev_notes/calibration_network_transient_audit.md`.

Document d'inventaire associe:
`docs/_dev_notes/site_selection_file_inventory.md`.

Rapport d'implementation actuel:
`docs/_dev_notes/site_selection_current_implementation_report.md`.

Note 2026-05-26: ce fichier reste le plan long historique. Le contrat court
terme stabilise est decrit dans
`docs/_dev_notes/site_selection_short_term_contract.md`, et l'etat courant dans
`docs/_dev_notes/site_selection_current_implementation_report.md`. Le package
spatial est maintenant organise en sous-packages
`candidates`, `config`, `domain`, `evaluation`, `evidence`, `hydrology`,
`outputs`, `pipelines` et `reports`; les anciens fichiers plats cites plus bas
doivent etre lus comme des references historiques, pas comme les chemins
actuels.

Note 2026-05-16: les premieres consolidations v0 sont implementees dans le code:
validation du manifest, schema CSV documente, criteres auditables
`area`/`flow_station`/`influence`/`geology`, sorties GeoJSON d'exutoires,
sorties GeoJSON de contours de bassins quand disponibles, points d'observation
normalises, carte PNG de controle, rapport HTML derive du manifest, validation
renforcee des artefacts, rapport HTML de plan pour les runs `plan_only` et
premier critere piezometrique auditable. La carte de revue accepte maintenant
des couches de contexte optionnelles, et les exemples incluent des contours de
bassins de fixture ainsi qu'un cas hydrometrique executable depuis des stations
pre-normalisees. Le present
document reste le plan long; l'etat exact du code est suivi dans le rapport
d'implementation courant.

## 1. Synthese

L'idee centrale est de creer un outil HydroModPy autonome de selection de sites.
Il ne lance pas de simulations. Il fabrique un catalogue robuste de bassins
candidats, avec leurs attributs, leurs diagnostics de qualite et leurs raisons
de selection ou de rejet.

Le point important est que la selection ne doit pas etre reduite a une recherche
de surface. La surface est un critere utile pour comparer des bassins, organiser
des campagnes par echelle ou eviter des objets numeriquement trop grands, mais
elle ne doit pas etre imperative par defaut. Un site peut etre interessant parce
qu'il possede une station hydrometrique, un piezometre pertinent, un contexte
geologique rare, une position hydrogeologique representative, une faible
anthropisation, une bonne qualite DEM, ou une valeur de contre-exemple. Chaque
critere doit rester explicite, versionne et exporte avec son evidence.

Le premier domaine d'application reste la France, parce que les donnees et les
exemples disponibles dans le depot y sont ancres. En revanche, le plan ne doit
pas enfermer l'outil dans le Massif Armoricain. Le Massif Armoricain est une
zone pilote utile; il ne doit etre qu'un cas de test regional parmi d'autres.

Le flux cible:

```text
territoire cible
+ DEM generique
+ couches de donnees optionnelles
+ criteres de generation de candidats
+ criteres de qualite, score, stratification et revue
= catalogue de sites candidats
```

Ce catalogue devient ensuite l'entree naturelle de `regional_lab` et du
`testbed`.

Decisions deja retenues dans la discussion:

- l'outil doit etre independant ;
- la methode de reference est `DEM-only` ;
- BD TOPAGE ne pilote pas la selection, elle peut servir de controle externe ;
- la surface est un critere configurable, pas une condition imperative par
  defaut ;
- une campagne peut utiliser une surface de preference, une classe de surface ou
  des bornes de securite, mais seulement si la configuration le demande ;
- une cible comme `100 km2` doit etre interpretee comme une preference ou une
  strate possible, pas comme un filtre dur implicite ;
- le DEM doit rester generique et pas trop couteux ;
- le comportement donnees souhaite est: utiliser le cache si disponible, sinon
  telecharger automatiquement ;
- la generation du reseau doit d'abord reprendre la methode deja presente dans
  HydroModPy: DEM corrige, D8 direction/accumulation, seuil d'aire contributive,
  Strahler optionnel ;
- les criteres de choix doivent etre organises comme des composants
  extensibles, pas comme une liste de conditions codees en dur ;
- les stations de debit, les points de suivi piezometrique, la geologie,
  l'hydrogeologie, l'occupation du sol et l'anthropisation sont des exemples de
  criteres mobilisables, mais ne constituent pas une liste fermee ;
- il peut exister plusieurs principes directeurs de selection. Par exemple, une
  campagne peut etre d'abord pilotee par l'existence de stations hydrometriques,
  puis seulement ensuite par des criteres d'influence, de surface et de geologie ;
- une autre campagne peut etre pilotee par un croisement direct de criteres
  physiques, par exemple surface, geologie, relief, climat et couverture
  spatiale, sans priorite initiale donnee aux stations ;
- la notion de region doit etre separee en plusieurs sens: region
  administrative, territoire de campagne, classe physiographique ou experte,
  bassin hydrographique, et groupe de stratification.

Decision d'architecture ajoutee le 2026-05-15:

- oui, la selection de sites doit devenir un workflow en soi, parce qu'elle a
  une configuration, des entrees, des artefacts, un manifest, des rapports et
  une reproductibilite propres ;
- ce workflow reste un workflow amont: il ne lance ni MF6, ni Boussinesq, ni
  calibration ;
- il doit d'abord consolider l'existant avant de recreer des algorithmes:
  catalogues regional-lab, `hydromodpy.analysis.catalog`, mesh gallery,
  inventaires Boussinesq, et page HTML de revue ;
- la page HTML de selection devient un artefact officiel du workflow de
  selection, ameliore progressivement avec le meme code que les exports.

## 2. Frontiere de responsabilite

### 2.1. Ce que l'outil fait

L'outil de selection:

- lit une configuration de selection ;
- resout un territoire cible ;
- prepare ou recupere le DEM necessaire ;
- calcule les produits hydrologiques du DEM ;
- genere un reseau topographique ;
- place des exutoires candidats ;
- delimite les bassins amont ;
- calcule la surface des bassins et l'evalue comme un critere configurable ;
- calcule des attributs par bassin ;
- croise les bassins avec des couches de contexte optionnelles ;
- detecte les observations disponibles autour ou dans les bassins ;
- applique des regles de qualite ;
- applique une selection ou une stratification ;
- exporte un catalogue de sites ;
- exporte un rapport de selection ;
- exporte les evidences qui expliquent chaque choix.

### 2.2. Ce que l'outil ne fait pas

L'outil ne doit pas:

- lancer MF6 ;
- lancer Boussinesq ;
- calibrer ;
- comparer des solveurs ;
- remplacer `regional_lab` ;
- remplacer `testbed` ;
- produire une analyse finale de resultats modeles ;
- coder en dur des hypotheses specifiques a la France dans le coeur ;
- imposer une seule definition de la region ;
- masquer les arbitrages de selection dans un score opaque.

La sortie de l'outil est une entree pour les autres briques.

```text
site_selection -> site catalog -> regional_lab -> testbed -> simulations
```

### 2.3. Recouvrement avec `regional_lab`

Il existe un recouvrement de vocabulaire, mais pas de responsabilite si la
frontiere est tenue strictement.

`regional_lab` fait deja une selection au sens operationnel:

- il lit un catalogue de sites deja existant ;
- il filtre ce catalogue par `region_id`, `cluster_id`, `tags`, `status`,
  `maturity`, `enabled` ;
- il applique des recettes ;
- il produit des cas `site x recipe` ;
- il delegue l'execution au testbed.

Le nouvel outil de `site_selection` fait une selection au sens geographique et
scientifique:

- il fabrique le catalogue de sites ;
- il delimite les bassins ;
- il calcule les exutoires, surfaces, signatures et flags ;
- il explique pourquoi un bassin est retenu ou rejete ;
- il produit une sortie compatible avec `regional_lab`.

La regle de separation doit etre simple:

```text
site_selection ne connait pas les recettes de simulation.
regional_lab ne delimite pas les bassins.
```

Cette separation est coherent avec le champ existant `source_selection_id` dans
`regional_lab`: ce champ peut porter la provenance de selection, par exemple
`france_100km2_dem_only_v1`, sans que `regional_lab` ait besoin de savoir comment
les bassins ont ete construits.

### 2.4. Workflow en soi ou simple composant ?

Recommandation: en faire un workflow en soi.

La raison n'est pas l'execution numerique. La raison est la tracabilite. Une
selection de sites depend de donnees, de seuils, de methodes de delimitation,
de criteres de rejet, de choix d'echantillonnage et d'une version de regles.
Elle doit donc produire un manifest et des artefacts auditables comme les autres
workflows HydroModPy.

Le workflow de selection doit cependant rester leger:

- il peut etre lance par `hmp run` avec `[workflow] mode = "site_selection"` ;
- il peut aussi exposer une commande directe `hmp site-selection ...` pour les
  usages interactifs ;
- il ecrit des catalogues, cartes, rapports et manifests ;
- il ne construit pas de cas `site x recipe` ;
- il ne lance aucune simulation.

Le mode mental recommande est:

```text
site_selection = workflow amont producteur de catalogue
regional_lab = workflow d'orchestration site x recette
testbed = workflow d'execution de variantes
```

### 2.5. Principes directeurs de selection

La strategie ne doit pas supposer un seul principe de selection. Le workflow doit
supporter plusieurs principes directeurs, chacun avec une logique claire de
generation des candidats et d'ordonnancement des criteres.

Deux principes v1 sont prioritaires:

```text
observation_led
criteria_crossing
```

`observation_led`

- point de depart: stations hydrometriques, eventuellement piezometres ou autres
  observations ;
- question scientifique: quels bassins observables peuvent servir de sites de
  validation, calibration ou reference ?
- premier critere: existence et qualite de l'observation ;
- criteres suivants: absence d'influence majeure, coherence du bassin controle
  par la station, couverture DEM, puis surface, geologie, region, occupation du
  sol ou autres axes de campagne.

Exemple:

```text
station hydro disponible
-> station non fortement influencee
-> bassin amont delimite depuis la station
-> controles barrage/prelevement/rejet/regularisation
-> caracterisation surface/geologie/relief/climat
-> selection/stratification finale
```

Avantages:

- produit des sites directement exploitables pour comparer le modele a des
  mesures ;
- donne un ancrage robuste aux campagnes de calibration ou validation ;
- facilite l'explication du choix a des utilisateurs metier.

Inconvenients:

- biaise l'inventaire vers les bassins deja instrumentes ;
- peut sous-representer certains contextes geologiques ou hydroclimatiques ;
- depend fortement de la qualite des metadonnees sur les influences.

`criteria_crossing`

- point de depart: territoire, DEM, reseau, couches geologiques, classes de
  surface, relief, climat, occupation du sol ou autres couches ;
- question scientifique: quels bassins representent bien la diversite physique
  du territoire ?
- premier critere: croisement de criteres physiques et spatiaux ;
- observations: bonus, information de rapport, ou strate optionnelle, mais pas
  point de depart obligatoire.

Exemple:

```text
territoire + DEM
-> candidats sur le reseau
-> croisement surface/geologie/relief/climat/anthropisation
-> thinning et equilibre spatial
-> bonus observations si disponibles
-> selection/stratification finale
```

Avantages:

- couvre mieux les contextes non instrumentes ;
- permet de construire une selection representative ou exploratoire ;
- ne depend pas d'un reseau de mesures preexistant.

Inconvenients:

- peut produire des sites difficiles a valider faute de mesures ;
- demande une revue humaine plus forte ;
- les poids entre criteres physiques doivent etre documentes.

Cas particulier utile: `area_only`

`area_only` ne doit pas etre un troisieme principe directeur dans la v1. C'est
un profil volontairement simple de `criteria_crossing` ou la surface est le seul
critere scientifique de selection. Les autres controles restent possibles, mais
ils doivent etre classes comme garde-fous techniques ou informations de rapport.

Exemple:

```text
territoire + DEM
-> candidats sur le reseau
-> delimitation des bassins
-> rejet technique des geometries invalides ou DEM incomplets
-> filtre ou score de surface
-> thinning/non-recouvrement
-> rapport geologie/observations sans effet sur la decision
```

Avantages:

- donne un cas de test tres lisible pour valider le moteur de selection ;
- permet de construire rapidement des catalogues comparables entre regions ;
- evite de melanger trop tot surface, geologie, observations et influence.

Inconvenients:

- ne garantit pas que les sites soient observables ;
- peut ignorer des contrastes geologiques ou hydrologiques importants ;
- doit etre presente comme un exercice de selection par taille, pas comme une
  selection representative de toute la complexite hydrologique.

Dans ce profil, `dem_coverage`, `geometry_validity`, `min_outlet_distance` ou
`overlap` ne comptent pas comme criteres scientifiques. Ce sont des conditions
techniques pour produire des bassins exploitables et non redondants. La geologie,
les stations hydrometriques et les piezometres peuvent etre calcules, mais ils
restent `report_only` si la campagne dit explicitement "surface seule".

Des principes futurs peuvent etre ajoutes sans changer le coeur, par exemple:

- `hydrogeology_led`: partir d'entites BDLISA ou de piezometres ;
- `impact_gradient`: chercher un gradient d'anthropisation ;
- `holdout_design`: construire des sites reserves a la validation ;
- `model_stress_test`: chercher des cas numeriquement ou physiquement difficiles.

### 2.6. Pipeline commun

Quel que soit le principe directeur, la strategie commune est de separer
clairement cinq etapes:

```text
generer largement -> delimiter -> caracteriser -> evaluer -> selectionner
```

1. Generer largement

- produire des candidats depuis le principe choisi: stations pour
  `observation_led`, croisement de couches pour `criteria_crossing`, reseau DEM,
  imports ou classes de contexte ;
- eviter de bloquer la generation sur une preference de surface ;
- garder la provenance de chaque candidat.

2. Delimiter

- calculer le bassin amont, sa surface et ses geometries ;
- rejeter seulement les echecs structurels: bassin vide, geometrie invalide,
  exutoire incoherent, DEM absent ;
- ne pas rejeter un bassin parce que sa surface differe d'une preference, sauf
  si une campagne le configure explicitement.

3. Caracteriser

- calculer les signatures topographiques, hydrographiques, geologiques,
  hydrogeologiques, climatiques et d'occupation du sol selon les donnees
  disponibles ;
- detecter les stations hydrometriques, les piezometres et les autres
  observations ;
- stocker les evidences meme quand elles ne modifient pas la decision.

4. Evaluer

- appliquer des criteres versionnes, chacun avec un mode: `hard_reject`,
  `warning`, `score`, `stratify` ou `report_only` ;
- respecter l'ordre impose par le principe directeur. Dans `observation_led`, la
  qualite et la non-influence des stations viennent avant les criteres physiques ;
- traiter la surface comme `report_only` par defaut ;
- rendre toute utilisation forte de la surface visible dans le manifest.

5. Selectionner

- produire un catalogue retenu, un catalogue rejete et des decisions
  explicables ;
- equilibrer la selection par types de regions, observations, geologie ou autres
  axes de campagne ;
- garder assez d'information pour refaire la selection avec d'autres poids.

## 3. Pourquoi un outil independant

La selection de sites est un probleme a part entiere. Elle melange:

- geographie ;
- donnees nationales ;
- criteres scientifiques ;
- contraintes numeriques ;
- objectifs d'echantillonnage ;
- reproductibilite ;
- auditabilite.

Si cette logique reste dans des scripts exemples, on aura vite:

- des seuils caches ;
- des criteres non versionnes ;
- des catalogues difficiles a reproduire ;
- des selections impossibles a expliquer ;
- des difficultes a comparer deux campagnes.

Un outil dedie permet au contraire:

- une configuration claire ;
- des sorties stables ;
- des raisons de rejet explicites ;
- une reutilisation entre campagnes ;
- une integration propre avec `regional_lab`.

## 4. Forme utilisateur cible

### 4.1. Commandes possibles

Proposition de commandes:

```text
hmp site-selection plan config.toml
hmp site-selection build-observed config.toml
hmp site-selection select-catchments config.toml catchments.csv
hmp site-selection report outputs/site_selection/<selection_id>/site_selection_manifest.json
hmp run config.toml
```

Forme compatible avec le reste de HydroModPy:

```toml
[workflow]
mode = "site_selection"

[site_selection]
selection_id = "headwater_10km2_armorican_v1"
output_root = "outputs/site_selection/headwater_10km2_armorican_v1"

[site_selection.input]
# auto:
# - utilise catchments_csv si present ;
# - sinon utilise [hydrometry] si present ;
# - sinon produit seulement un plan auditable.
mode = "auto"
```

La commande directe et le mode `[workflow]` doivent appeler le meme coeur. Le
mode `[workflow]` est la forme recommandee pour les campagnes versionnees. La
commande directe est utile pour les reprises, le debug et la generation de
rapports.

Exemples maintenus dans le depot:

- `examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_primary.toml`
  illustre une strategie `observation_led` ou les stations hydrometriques
  pilotent d'abord la generation des candidats ;
- `examples/projects/17_site_selection_workflow/configs/auvergne_rhone_alpes_area_only.toml`
  illustre une strategie `criteria_crossing` avec profil `area_only`, ou la
  surface est le seul critere actif.

`plan`:

- valide la configuration ;
- resout les sources ;
- estime les tuiles DEM necessaires ;
- liste les donnees qui seront lues ou telechargees ;
- ne telecharge rien, sauf option explicite.

`build-observed`:

- execute une selection pilotee par les stations hydrometriques chargees via la
  section `[hydrometry]` existante ;
- produit les catalogues et les traces d'evidence ;
- reste un adaptateur: il ne connait pas le schema brut Hub'Eau, il consomme les
  `PointRecord` deja normalises par les gestionnaires de donnees.

`select-catchments`:

- applique les criteres de selection a un CSV de bassins deja delimites ;
- permet de travailler avant que toute la generation DEM-only soit complete ;
- sert de voie de migration pour les catalogues existants et les emprises
  importees.

`report`:

- lit le `site_selection_manifest.json` officiel ;
- regenere un `review/index.html` statique ;
- s'appuie sur les CSV/JSONL du workflow, pas sur des chemins caches ;
- affiche une v0 volontairement sobre: resume, strategie, sites retenus,
  sites rejetes, criteres traces, observations et liens vers artefacts.

`hmp run` avec `[workflow] mode = "site_selection"`:

- utilise `[site_selection.input]` pour choisir le mode d'execution ;
- ecrit un plan si aucune entree exploitable n'est declaree ;
- lance `build-observed` si `[hydrometry]` est present ;
- lance `select-catchments` si `site_selection.input.catchments_csv` est
  present ;
- renvoie toujours un resume court: action, `selection_id`, nombre de sites
  retenus/rejetes et principaux chemins de sortie ;
- ecrit toujours `site_selection_manifest.json` pour les executions de
  selection ;
- ecrit `review/index.html` seulement si `write_report_html = true` ou via la
  commande explicite `hmp site-selection report` ;
- ecrit, quand les sorties CSV sont activees, un `regional_lab_sites.csv`
  compatible avec `hydromodpy.analysis.testbed.regional_lab`.

### 4.2. Configuration minimale

Exemple volontairement simple:

```toml
[site_selection]
selection_id = "france_exploratory_dem_only_v1"
output_root = "outputs/site_selection/france_exploratory_dem_only_v1"

[site_selection.strategy]
principle = "criteria_crossing"

[site_selection.territory]
mode = "admin_regions"
country = "FR"
regions = ["Bretagne", "Normandie", "Pays de la Loire"]

[site_selection.dem]
source = "ign_bdalti"
resolution_m = 25
cache_policy = "use_cache_else_download"

[site_selection.hydrology]
method = "dem_only"
flow_algorithm = "d8"
network_threshold_area_km2 = 1.0
compute_strahler = true

[site_selection.criteria.area]
mode = "report"

[site_selection.output]
write_csv = true
write_regional_lab_csv = true
write_report_html = false
# Sorties futures, a activer seulement quand les writers correspondants existent.
write_geoparquet = false
write_report_md = false
```

Dans cette configuration minimale, la surface est seulement calculee et
rapportee. Elle n'est pas un filtre, et aucun bassin n'est rejete parce qu'il est
loin d'une valeur cible.

### 4.3. Configuration plus complete

```toml
[site_selection]
selection_id = "northwest_multicriteria_v1"
output_root = "outputs/site_selection/northwest_multicriteria_v1"
random_seed = 42

[site_selection.strategy]
principle = "criteria_crossing"
primary_axes = ["geology", "relief", "area", "admin_region"]
observation_role = "bonus"

[site_selection.territory]
mode = "admin_regions"
country = "FR"
regions = ["Bretagne", "Normandie", "Pays de la Loire"]
clip_to_territory = true

[site_selection.dem]
source = "ign_bdalti"
resolution_m = 25
cache_policy = "use_cache_else_download"
margin_km = 5.0
force_refresh = false

[site_selection.hydrology]
method = "dem_only"
flow_algorithm = "d8"
hydrologic_conditioning = "existing_default"
network_threshold_area_km2 = 1.0
compute_strahler = true

[site_selection.outlets]
candidate_mode = "network_sampling"
min_distance_between_outlets_km = 10.0
allow_nested_basins = false
snap_to_generated_stream = true

[site_selection.spatial_selection]
allow_nested_basins = false
min_outlet_distance_km = 10.0
max_pairwise_basin_overlap_fraction = 0.05
overlap_reference = "smaller_basin"
overlap_mode = "hard_reject"

[site_selection.filters]
max_urban_fraction = 0.10
exclude_major_obstacles = true
exclude_major_withdrawals = false
require_dem_coverage = true

[site_selection.characterization]
enabled = true
ruleset = "expert_v1"
dimensions = ["relief", "climate", "geology", "drainage", "anthropization"]

[site_selection.data_layers]
# Les couches restent optionnelles. Une couche absente ne doit pas casser le
# workflow, sauf si un critere bloquant la rend obligatoire.
enabled = ["geology", "hydrometry", "piezometry", "land_cover", "bdtopage"]
geology_source = "brgm_1m"
hydrometry_source = "hubeau_hydrometrie"
piezometry_source = "hubeau_piezometrie"
land_cover_source = "theia_oso"

[site_selection.criteria]
# Le ruleset porte la logique de decision. Il doit etre versionne, hashable et
# exporte pour que deux selections puissent etre comparees.
ruleset = "france_site_selection_v1"
hard_reject = ["dem_coverage", "geometry_validity"]
soft_score = [
  "area_preference",
  "observation_support",
  "geology_diversity",
  "regional_balance",
]
report_only = ["bdtopage_alignment", "nearby_piezometry"]

[site_selection.criteria.area]
mode = "score"
preferred_area_km2 = 100.0
score_half_width_fraction = 0.50
# hard_min_area_km2 = 10.0
# hard_max_area_km2 = 500.0

[site_selection.criteria.observations]
flow_station_mode = "bonus"
flow_station_max_distance_km = 5.0
piezometer_mode = "report"
piezometer_max_distance_km = 10.0

[site_selection.criteria.geology]
mode = "stratify"
prefer_diversity = true

[site_selection.stratification]
enabled = true
by = ["expert_region_type", "admin_region"]
max_sites_per_class = 20
prefer_observed_sites = false

[site_selection.output]
write_candidates = false
write_rejected = true
write_selected = true
write_csv = true
write_regional_lab_csv = true
write_report_html = true
write_geoparquet = false
write_report_md = false
```

Ici, `preferred_area_km2 = 100.0` signifie seulement que la proximite a `100 km2`
contribue au score. Les bornes dures sont commentees: les activer changerait la
nature scientifique de la campagne et devrait etre justifie dans le manifest.

`score_half_width_fraction = 0.50` signifie que l'effet de la surface diminue sur
une demi-largeur de `50%` autour de la preference. Pour `100 km2`, la plage de
score favorable est donc centree sur `100 km2`, avec une reference indicative
autour de `50-150 km2`. Ce n'est pas une tolerance de rejet. Un bassin de `35 km2`
ou `220 km2` peut rester candidat si ses autres criteres sont bons, sauf si
`hard_min_area_km2` ou `hard_max_area_km2` sont explicitement actives.

La section `spatial_selection` est independante de la surface. Elle sert a eviter
que la selection finale contienne plusieurs bassins qui racontent presque la meme
chose spatialement. Dans cet exemple, deux bassins retenus ne doivent pas se
recouvrir de plus de `5%` du plus petit bassin, et leurs exutoires doivent rester
espaces d'au moins `10 km`.

### 4.4. Configuration orientee stations hydrometriques

Exemple ou l'existence de stations hydro est le principe de selection principal:

```toml
[site_selection]
selection_id = "france_hydro_stations_reference_v1"
output_root = "outputs/site_selection/france_hydro_stations_reference_v1"
random_seed = 42

[site_selection.strategy]
principle = "observation_led"
primary_observation_type = "flow_station"
observation_source = "hubeau_hydrometrie"
candidate_mode = "station_outlets"

[site_selection.territory]
mode = "admin_regions"
country = "FR"
regions = ["Bretagne", "Normandie", "Pays de la Loire"]

[site_selection.dem]
source = "ign_bdalti"
resolution_m = 25
cache_policy = "use_cache_else_download"
margin_km = 5.0

[site_selection.hydrology]
method = "dem_only"
flow_algorithm = "d8"
network_threshold_area_km2 = 1.0
compute_strahler = true

[site_selection.criteria]
ruleset = "france_observed_reference_v1"
hard_reject = [
  "dem_coverage",
  "geometry_validity",
  "flow_station_available",
  "flow_station_not_strongly_influenced",
]
warning = ["area_outside_preference", "geology_missing", "piezometry_missing"]
soft_score = [
  "record_length",
  "area_preference",
  "geology_diversity",
  "regional_balance",
]
report_only = ["nearby_piezometry", "bdtopage_alignment"]

[site_selection.criteria.observations.flow_station]
mode = "hard_reject"
min_record_years = 5
max_station_to_outlet_distance_km = 2.0
require_station_inside_or_at_outlet = true

[site_selection.criteria.influence]
mode = "hard_reject"
reject_major_dam_upstream = true
reject_major_withdrawal_upstream = true
reject_major_regulated_reach = true
influence_search_radius_km = 25.0

[site_selection.criteria.area]
mode = "score"
preferred_area_km2 = 100.0
score_half_width_fraction = 0.75

[site_selection.criteria.geology]
mode = "stratify"
prefer_diversity = true
```

Dans cette logique, la station hydro n'est pas un bonus: elle definit le point de
depart. Les criteres de non-influence viennent ensuite, avant les criteres de
surface ou de geologie. La surface reste secondaire sauf si la campagne declare
explicitement des bornes bloquantes.

### 4.5. Exemple station hydro comme critere principal en Bretagne

Cet exemple sert a clarifier le cas ou les stations hydrometriques sont le
critere de selection principal. La Bretagne n'est pas choisie parce que l'outil
serait limite au Massif Armoricain, mais parce qu'elle constitue un premier cas
francais coherent avec les donnees deja presentes dans le depot: relief modere,
contexte de socle, bassins courts et instrumentation hydrometrique exploitable.

```toml
[site_selection]
selection_id = "bretagne_hydro_station_reference_v1"
output_root = "outputs/site_selection/bretagne_hydro_station_reference_v1"
random_seed = 42

[site_selection.strategy]
principle = "observation_led"
primary_observation_type = "flow_station"
observation_source = "hubeau_hydrometrie"
candidate_mode = "station_outlets"

[site_selection.territory]
mode = "admin_regions"
country = "FR"
regions = ["Bretagne"]
clip_to_territory = true

[site_selection.dem]
source = "ign_bdalti"
resolution_m = 25
cache_policy = "use_cache_else_download"
margin_km = 5.0

[site_selection.hydrology]
method = "dem_only"
flow_algorithm = "d8"
network_threshold_area_km2 = 1.0
compute_strahler = true

[site_selection.criteria]
ruleset = "france_observed_reference_v1"
hard_reject = [
  "dem_coverage",
  "geometry_validity",
  "flow_station_available",
  "flow_station_record_length",
  "flow_station_not_strongly_influenced",
]
warning = ["area_outside_preference", "geology_missing", "piezometry_missing"]
soft_score = [
  "record_length",
  "area_preference",
  "spatial_balance",
  "geology_diversity",
]
report_only = ["nearby_piezometry", "bdtopage_alignment"]

[site_selection.criteria.observations.flow_station]
mode = "hard_reject"
min_record_years = 10
max_station_to_outlet_distance_km = 2.0
require_station_inside_or_at_outlet = true

[site_selection.criteria.influence]
mode = "hard_reject"
reject_major_dam_upstream = true
reject_major_withdrawal_upstream = true
reject_major_regulated_reach = true
influence_search_radius_km = 25.0

[site_selection.criteria.area]
mode = "score"
preferred_area_km2 = 100.0
score_half_width_fraction = 0.75

[site_selection.criteria.geology]
mode = "stratify"
prefer_diversity = true

[site_selection.spatial_selection]
allow_nested_basins = true
min_outlet_distance_km = 5.0
overlap_mode = "warning"
same_mainstem_policy = "allow_with_warning"

[site_selection.output]
write_candidates = false
write_rejected = true
write_selected = true
write_csv = true
write_regional_lab_csv = true
write_report_html = true
write_geoparquet = false
write_report_md = false
```

Ordre de decision attendu:

```text
station Hub'Eau candidate
-> chronique minimale et localisation exploitable
-> bassin amont delimite
-> absence d'influence majeure connue
-> score de surface, geologie, equilibre spatial
-> selection finale et rapport d'evidences
```

La politique de recouvrement est volontairement plus souple que dans une
selection purement spatiale. Deux stations amont/aval peuvent etre informatives,
par exemple pour comparer des echelles de bassin ou documenter un gradient
d'influence. Le recouvrement produit donc d'abord un `warning`. Il ne devient
bloquant que si la campagne cherche explicitement un inventaire non imbrique.

### 4.6. Exemple surface comme unique critere en Auvergne-Rhone-Alpes

Cet exemple represente un cas tres different de la Bretagne: relief plus fort,
contrastes alpins, volcaniques, sedimentaires et alluviaux, bassins plus
heterogenes. Il sert a verifier que l'outil n'est pas construit autour d'une
region de socle armoricaine.

Ici, "surface seule" veut dire: la surface est le seul critere scientifique de
selection. Les controles de couverture DEM, de geometrie et de non-recouvrement
restent necessaires pour produire un catalogue propre, mais ils ne portent pas
le sens scientifique de la campagne. Les stations hydrometriques, piezometres et
classes geologiques sont calculees seulement pour le rapport.

```toml
[site_selection]
selection_id = "auvergne_rhone_alpes_area_only_100km2_v1"
output_root = "outputs/site_selection/auvergne_rhone_alpes_area_only_100km2_v1"
random_seed = 42

[site_selection.strategy]
principle = "criteria_crossing"
profile = "area_only"
primary_axes = ["area"]
observation_role = "report_only"
geology_role = "report_only"

[site_selection.territory]
mode = "admin_regions"
country = "FR"
regions = ["Auvergne-Rhone-Alpes"]
clip_to_territory = true

[site_selection.dem]
source = "ign_bdalti"
resolution_m = 25
cache_policy = "use_cache_else_download"
margin_km = 10.0

[site_selection.hydrology]
method = "dem_only"
flow_algorithm = "d8"
network_threshold_area_km2 = 1.0
compute_strahler = true

[site_selection.outlets]
candidate_mode = "network_sampling"
min_distance_between_outlets_km = 15.0
allow_nested_basins = false
snap_to_generated_stream = true

[site_selection.spatial_selection]
allow_nested_basins = false
min_outlet_distance_km = 15.0
max_pairwise_basin_overlap_fraction = 0.05
overlap_reference = "smaller_basin"
overlap_mode = "hard_reject"

[site_selection.criteria]
ruleset = "france_area_only_v1"
hard_reject = ["dem_coverage", "geometry_validity", "area_range"]
report_only = ["geology", "hydrometry", "piezometry", "bdtopage_alignment"]

[site_selection.criteria.area]
mode = "hard_reject"
target_area_km2 = 100.0
hard_min_area_km2 = 75.0
hard_max_area_km2 = 125.0

[site_selection.criteria.observations]
flow_station_mode = "report"
flow_station_max_distance_km = 5.0
piezometer_mode = "report"
piezometer_max_distance_km = 10.0

[site_selection.criteria.geology]
mode = "report"

[site_selection.output]
write_candidates = false
write_rejected = true
write_selected = true
write_csv = true
write_regional_lab_csv = true
write_report_html = true
write_geoparquet = false
write_report_md = false
```

Ordre de decision attendu:

```text
territoire Auvergne-Rhone-Alpes + DEM
-> candidats sur le reseau
-> delimitation et controles techniques
-> filtre 75-125 km2
-> retrait des bassins trop recouvrants
-> rapport geologie/observations sans effet sur la selection
```

Dans ce cas, une station hydrometrique proche ne sauve pas un bassin hors plage
de surface, et une geologie rare ne donne pas de bonus. C'est volontaire: ce
profil permet de tester une selection par taille pure. `target_area_km2` sert a
documenter l'intention de campagne, mais la decision automatique vient ici des
bornes `75-125 km2`. Si l'on veut ensuite une selection representative de
contextes physiques, il faut passer a un profil `criteria_crossing`
multi-criteres et declarer explicitement les axes ajoutes.

### 4.7. Synthese des exemples contrastes

| exemple | region | principe | critere principal | role de la surface | role des observations |
|---|---|---|---|---|---|
| `bretagne_hydro_station_reference_v1` | Bretagne | `observation_led` | station hydro exploitable et non fortement influencee | secondaire: `score` ou `report_only` | critere bloquant |
| `auvergne_rhone_alpes_area_only_100km2_v1` | Auvergne-Rhone-Alpes | `criteria_crossing` avec profil `area_only` | surface du bassin | critere principal et borne bloquante | `report_only` |

Ces deux exemples doivent rester dans la documentation comme tests de coherence.
Ils verifient deux choses differentes:

- le moteur respecte l'ordre logique d'une campagne fondee sur les observations ;
- le moteur peut aussi faire une selection volontairement simple par surface,
  dans une region sans lien direct avec le cas armoricain.

## 5. Architecture proposee

### 5.0. Briques existantes a rassembler

Le developpement doit partir des pieces deja realisees, pas d'un nouveau
prototype isole.

| brique existante | role a conserver | action |
|---|---|---|
| `hydromodpy/analysis/catalog.py` | Chargement/filtrage generique CSV/JSONL. | Reutiliser pour les entrees/sorties tabulaires simples. |
| `hydromodpy/analysis/testbed/regional_lab_catalog.py` | Lecture typed des catalogues de sites regional-lab. | Garder comme consommateur aval et verifier la compatibilite d'export. |
| `hydromodpy/analysis/testbed/regional_lab_site_selection.py` | Filtrage operationnel par site, region, famille, echelle, statut, maturite, tags. | Ne pas dupliquer dans `site_selection`; produire les champs attendus. |
| `hydromodpy/analysis/testbed/regional_lab_planning.py` | Expansion `site x recipe`. | Rester aval du workflow de selection. |
| `hydromodpy/analysis/testbed/regional_lab_bootstrap.py` | Helpers de bootstrap et preflight mesh. | Reutiliser dans les adaptateurs de campagnes, pas dans le coeur geographique. |
| `hydromodpy/spatial/site_selection/html_report.py` | Rapport HTML v0 depuis `site_selection_manifest.json`. | Renderer officiel sobre pour les sorties actuelles. |
| `hydromodpy/spatial/site_selection/reporting.py` | Page HTML/carte de revue deja amorcee pour l'inventaire Boussinesq. | Reutiliser plus tard pour enrichir la cartographie. |
| `examples/projects/10_testbed_workflow/site_tables/armorican_demo_sites.csv` | Ancien catalogue manuel de 8 sites. | L'utiliser comme fixture de migration et comparaison. |
| `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/natural_regional_lab_sites.csv` | Catalogue regional-lab naturel actuel. | Le traiter comme catalogue de reference pour valider les exports. |
| `examples/projects/07_mesh_gallery/**/case.json` et `bundle/` | Corpus de candidats mailles par echelle/outlet/variante. | L'utiliser comme source candidate importee et comme base de preflight. |
| `examples/data/dem/DEM_armorican_massif.tif` | DEM regional deja utilise pour les cartes et tests locaux. | Fixture reelle pour le premier workflow sans telechargement. |

La consolidation doit produire une seule chaine logique:

```text
catalogues ou candidats existants
-> normalisation site_selection
-> carte/HTML de revue
-> export regional_lab
-> regional_lab/testbed existants
```

### 5.0.1. Eviter la duplication hydrologique

Le workflow `site_selection` ne doit pas recreer une couche hydrologique
parallele a celles qui existent deja dans HydroModPy. Le mot "hydrology" peut
etre ambigu, car le depot contient deja plusieurs responsabilites distinctes:

- `hydromodpy.physics.hydrology`: logique de modeles, forçages et outils
  hydrologiques au sens simulation/physique ;
- `hydromodpy.spatial.geographic.core.flow_products`: production des rasters
  DEM corriges, direction D8 et accumulation D8 ;
- `hydromodpy.spatial.delineation`: backend Whitebox et operations de
  delimitation ;
- `hydromodpy.spatial.geographic.core.catchment_*`: objets et fonctions lies a
  la delimitation et aux metriques de bassins.

La selection de sites doit donc seulement orchestrer ces briques. Elle peut
avoir un module local pour:

- choisir les parametres de correction DEM selon la campagne ;
- demander ou retrouver les produits D8 existants ;
- enregistrer les chemins et versions dans le manifest ;
- exposer ces produits au generateur de candidats et a la delimitation.

Elle ne doit pas reimplementer le D8, l'accumulation, le remplissage des
depressions ou la delimitation de bassins. Si une fonction existe deja dans
`spatial.geographic` ou `spatial.delineation`, le module de selection doit
l'appeler.

### 5.1. Emplacement code

Decision actualisee:

```text
hydromodpy/
  spatial/
    site_selection/
      __init__.py
      config.py
      artifacts.py
      manifest.py
      html_report.py
      flow_products_adapter.py
      candidate_outlets.py
      delineation.py
      observations.py
      criteria.py
      filters.py
      selection.py
      exports.py
      reporting.py
      types.py
      build.py
  workflow/
      site_selection.py
      site_selection_data.py
  cli/
    commands/
      site_selection.py
```

Raison du choix:

- le package `hydromodpy/spatial/site_selection/` existe deja avec la brique
  `reporting.py` ;
- la responsabilite primaire est geographique: candidats, bassins, emprises,
  signatures spatiales, cartes ;
- les briques aval `regional_lab` et `testbed` sont deja dans
  `hydromodpy.analysis.testbed` et ne doivent pas etre deplacees ;
- `hydromodpy.analysis.catalog` fournit deja les primitives generiques de
  catalogue ;
- garder `site_selection` dans `spatial` evite de confondre choix de bassins et
  construction de campagnes numeriques.

Si le besoin d'un inventaire multi-sources non strictement spatial devient plus
large, une couche future pourra etre ajoutee, par exemple
`hydromodpy.analysis.site_inventory`. Elle ne doit pas bloquer le premier
developpement.

### 5.2. Modules

`config.py`

- modeles Pydantic de configuration ;
- validation des valeurs ;
- normalisation des chemins ;
- normalisation des criteres, seuils, modes et poids.

`strategy.py`

- declaration du principe directeur de selection ;
- modes v1: `observation_led` et `criteria_crossing` ;
- profils v1 de `criteria_crossing`: `dem_only`, `area_only` et
  `multicriteria` ;
- validation de l'ordre logique des criteres ;
- choix des politiques par defaut, notamment recouvrement strict en
  `criteria_crossing` et recouvrement plus explicite/revu humainement en
  `observation_led` ;
- production du plan d'evaluation applique a chaque candidat.

`territory.py`

- resolution d'un territoire ;
- modes: `admin_regions`, `admin_departments`, `polygon_file`, `bbox`,
  `site_catalog_extent`, `geoparquet_filter` ;
- union des geometries ;
- reprojection vers CRS de travail ;
- production d'une emprise avec marge.

`dem_context.py`

- demande de DEM pour l'emprise ;
- integration avec `hydromodpy.data.variables.dem.manager.DemManager` ;
- politique cache ;
- controle couverture ;
- reference au manifest de donnees.

`flow_products_adapter.py`

- adaptateur fin vers les produits hydrologiques spatiaux existants ;
- appel prioritaire a `hydromodpy.spatial.geographic.core.flow_products` ;
- reutilisation du backend `hydromodpy.spatial.delineation` pour les operations
  Whitebox ;
- DEM corrige, D8 direction et D8 accumulation comme artefacts, pas comme
  algorithmes recodes ;
- reseau extrait par `threshold_area_km2` en reutilisant les primitives
  geographiques existantes quand elles sont disponibles ;
- Strahler optionnel si une primitive existante le fournit, sinon a reporter
  plutot qu'a recoder dans la v1 ;
- enregistrement des chemins, parametres et versions dans le manifest.

`candidate_outlets.py`

- detection des cellules candidates selon plusieurs strategies: echantillonnage
  du reseau, points d'observation, confluences, classes de surface, ou imports ;
- mode `station_outlets` pour les campagnes `observation_led` ;
- filtrage sur le reseau genere ;
- thinning spatial ;
- suppression des doublons ;
- priorisation des candidats.

`delineation.py`

- delimitation de chaque bassin candidat ;
- calcul surface reelle ;
- rejet uniquement pour les echecs structurels ou les criteres explicitement
  bloquants ;
- detection des bassins vides ou incoherents.

`data_layers.py`

- declaration et resolution des couches optionnelles ;
- normalisation des sources France v1: geologie BRGM, BDLISA, Hub'Eau,
  occupation du sol, BD TOPAGE, couches utilisateur ;
- controle de couverture par bassin ;
- production d'un inventaire des couches utilisees.

`observations.py`

- recherche des stations de debit proches ou incluses dans le bassin ;
- recherche des piezometres proches ou inclus dans le bassin ;
- calcul des distances, periodes disponibles et statuts de donnees ;
- evaluation des metadonnees d'influence disponibles: barrage, prelevement,
  regulation, rejet, derivation, station de qualite douteuse ;
- production d'evidences sans imposer que les observations soient obligatoires.

`signatures.py`

- calcul d'attributs par bassin ;
- topographie ;
- morphometrie ;
- drainage ;
- climat/recharge si disponible ;
- geologie/hydrogeologie si disponible ;
- occupation du sol/anthropisation si disponible.

`expert_rules.py`

- typologie lisible ;
- versions de regles ;
- categories comme `relief`, `climate`, `geology`, `storage`,
  `drainage_density`, `anthropization`.

`criteria.py`

- definition des familles de criteres ;
- evaluation des criteres bloquants, faibles, de score, de stratification et de
  rapport ;
- respect de l'ordre impose par le principe directeur ;
- stockage des poids, seuils, modes et evidences ;
- calcul des composantes de score sans masquer les raisons de decision.

`filters.py`

- filtres bloquants et filtres faibles ;
- raisons de rejet ;
- production de flags.

`selection.py`

- selection finale ;
- maximum par classe ;
- minimum par region ;
- diversification ;
- tri stable ;
- option aleatoire avec seed.

`exports.py`

- GeoParquet ;
- CSV ;
- JSONL ;
- CSV regional_lab ;
- manifest.

`manifest.py`

- construction et ecriture de `site_selection_manifest.json` ;
- chemins relatifs vers les artefacts ;
- compteurs selection/rejet/criteres ;
- strategie, territoire, ruleset et modes de criteres.

`artifacts.py`

- assemblage final des artefacts officiels ;
- ecriture du manifest ;
- declenchement optionnel du rapport HTML.

`html_report.py`

- rapport HTML v0 depuis le manifest ;
- tables retenus/rejetes ;
- synthese criteres/evidences ;
- liens vers CSV et JSONL.

`reporting.py`

- rapport Markdown ;
- page HTML/cartographique historique a consolider plus tard ;
- carte regionale avec topographie, contour de region, emprises disponibles et
  numeros de sites ;
- tables de correspondance numero/site ;
- miniatures cliquables et liens vers artefacts ;
- synthese par region administrative ;
- synthese par type expert ;
- synthese des rejets ;
- cartographie simple si dependances disponibles.

`workflow/site_selection.py`

- execution du workflow `site_selection` ;
- orchestration `plan`, `build-observed`, `select-catchments` et exports ;
- lecture/ecriture du manifest ;
- reprise depuis artefacts existants ;
- aucun lancement de simulation.

`cli/commands/site_selection.py`

- commandes utilisateur ;
- branchement avec le CLI `hmp`.

`types.py`

- dataclasses ou modeles serialisables.

## 6. Contrats de donnees

### 6.1. StrategySpec

```text
selection_principle
candidate_mode
primary_observation_type
primary_axes
criterion_order
observation_role
area_role
geology_role
influence_policy
spatial_overlap_policy
```

`selection_principle` porte le choix strategique principal. Ce champ doit etre
present dans le manifest et dans la configuration resolue, parce qu'il change le
sens de toute la selection. Une campagne `observation_led` et une campagne
`criteria_crossing` peuvent utiliser les memes donnees mais ne repondent pas a la
meme question.

### 6.2. TerritorySpec

```text
territory_id
mode
country
admin_level
admin_names
geometry
crs
bbox
source_dataset
source_version
```

Le territoire doit etre serialisable. Meme si l'utilisateur donne des noms de
regions, le manifest doit stocker les geometries resolues ou au moins un hash.

### 6.3. DemRequest

```text
source
resolution_m
path
bbox
margin_km
cache_policy
force_refresh
frozen_manifest
```

### 6.4. DemProduct

```text
dem_path
crs
resolution_x
resolution_y
bbox
nodata
source
source_version
cache_entry_id
downloaded
```

### 6.5. HydrologyProducts

```text
corrected_dem_path
d8_pointer_path
d8_accumulation_path
stream_raster_path
strahler_path
network_threshold_area_km2
flow_algorithm
conditioning_method
```

### 6.6. CandidateOutlet

```text
candidate_id
selection_principle
candidate_source
source_feature_id
x
y
crs
accumulation_area_km2
stream_order
distance_to_nearest_selected_km
territory_id
candidate_status
candidate_reason
```

`candidate_source` peut valoir `flow_station`, `piezometer`, `network_sample`,
`area_class`, `confluence`, `imported_catalog`, ou une valeur ajoutee plus tard.
Il est indispensable pour ne pas confondre un site issu d'une station et un site
issu d'un croisement de criteres physiques.

### 6.7. DelineatedSite

```text
site_id
candidate_id
geometry
outlet_x
outlet_y
area_km2
area_class
area_preference_km2
area_score
overlap_group_id
max_overlap_fraction_with_selected
nearest_selected_site_id
distance_to_nearest_selected_km
enabled
site_status
selection_status
selection_reason
```

`area_km2` est toujours mesuree et exportee. Les champs de preference de surface
sont optionnels et ne doivent etre remplis que si un critere de surface est
configure. Une aire hors preference ne doit pas entrainer un rejet sauf si la
campagne declare explicitement des bornes bloquantes.

### 6.8. SiteSignature

```text
site_id
mean_elevation_m
min_elevation_m
max_elevation_m
relief_amplitude_m
mean_slope_pct
hypsometry_bins
main_drain_length_km
drainage_density_km_km2
strahler_max
recharge_mean_mm_y
recharge_seasonality_index
geology_dominant
geology_fractions_json
hydrogeology_dominant
urban_fraction
forest_fraction
agriculture_fraction
observation_flags
anthropization_flags
```

### 6.9. DataLayerSummary

```text
layer_id
layer_family
source_dataset
source_version
source_path_or_url
coverage_fraction
feature_count
crs
resolution_or_scale
used_by_criteria
quality_flags
artifact_path
```

Cette table ou ce JSON de synthese explique quelles couches ont reellement ete
utilisees. Elle est importante pour les criteres optionnels: une couche absente
doit etre visible dans les sorties, meme si elle n'a pas bloque la selection.

### 6.10. ObservationEvidence

```text
site_id
observation_type
source_dataset
feature_id
feature_label
distance_to_outlet_km
distance_to_basin_km
inside_basin
record_start
record_end
record_year_count
quality_status
influence_status
influence_flags
upstream_dam_count
upstream_major_withdrawal_count
regulated_reach_flag
evidence_json
```

`observation_type` peut valoir par exemple `flow_station`, `piezometer`,
`onde_site` ou une valeur ajoutee plus tard. Le contrat ne doit donc pas etre
lie a une seule API. Pour la France v1, les providers naturels sont Hub'Eau
hydrometrie, Hub'Eau piezometrie et ONDE, mais le coeur doit seulement consommer
des observations normalisees.

`ObservationEvidence` n'est pas le schema brut Hub'Eau. C'est une table
d'audit normalisee par site et par observation candidate. Certaines colonnes
peuvent venir directement de Hub'Eau, d'autres sont calculees par
`site_selection`, et d'autres viennent de couches independantes.

Pour une station hydrometrique Hub'Eau:

- `source_dataset`, `feature_id`, `feature_label`, les coordonnees, la commune,
  le departement, l'altitude et les dates d'ouverture/fermeture peuvent venir du
  referentiel Hub'Eau hydrometrie ;
- `record_start`, `record_end`, `record_year_count` et `quality_status` peuvent
  etre calcules depuis les observations telechargees et leurs qualifications ;
- `distance_to_outlet_km`, `distance_to_basin_km` et `inside_basin` sont
  calcules par croisement spatial avec l'exutoire et le bassin delimite ;
- `influence_status`, `influence_flags`, `upstream_dam_count`,
  `upstream_major_withdrawal_count` et `regulated_reach_flag` ne doivent pas
  etre supposes disponibles dans Hub'Eau hydrometrie. Ils doivent venir de
  croisements avec d'autres couches: barrages, prelevements, troncons regules,
  BD TOPAGE, referentiels metier ou couches utilisateur ;
- `evidence_json` conserve les identifiants provider, les champs sources utiles,
  les versions de couches et les hypotheses de calcul.

Pour un piezometre, la meme table peut etre alimentee par Hub'Eau piezometrie,
mais les champs de qualite, de chronique et d'influence n'auront pas exactement
le meme sens. C'est pour cela que `observation_type` et `source_dataset` doivent
rester explicites.

### 6.11. ExpertRegion

```text
site_id
ruleset_id
relief_class
climate_class
geology_class
storage_class
drainage_class
anthropization_class
expert_region_type
rule_evidence_json
```

Le nom `ExpertRegion` designe une classe interpretable de bassin, pas forcement
une region administrative. Il peut correspondre a une combinaison de relief,
climat, geologie, drainage, stockage ou anthropisation. Cette distinction evite
de confondre le perimetre politique de travail avec la nature hydrologique ou
hydrogeologique du site.

### 6.12. CriteriaComponent

```text
site_id
selection_principle
criterion_id
criterion_family
criterion_mode
evaluation_stage
evaluation_order
criterion_status
raw_value
normalized_value
threshold
weight
score_component
blocking
reason
evidence_json
```

Ce contrat rend le systeme extensible. Ajouter un critere ne doit pas obliger a
modifier le schema principal du catalogue: le nouveau critere ajoute des lignes
dans `criteria_components.parquet`, puis eventuellement des colonnes derivees
dans les exports humains.

### 6.13. SelectionDecision

```text
site_id
selection_principle
selected
decision_stage
decision_reason
blocking_flags
warning_flags
rank_score
stratification_class
criteria_summary_json
```

## 7. Algorithme DEM-only

### 7.1. Principe

Le principe est de produire les exutoires candidats depuis le DEM lui-meme:

```text
DEM -> correction hydrologique -> D8 direction -> D8 accumulation
    -> reseau topographique -> candidats multi-strategies
    -> bassins -> criteres explicites -> selection/stratification
```

BD TOPAGE n'est pas necessaire pour choisir les sites. Il peut etre lu plus tard
comme diagnostic:

- distance entre reseau genere et BD TOPAGE ;
- densite comparee ;
- troncons BD TOPAGE absents du reseau DEM ;
- reseau DEM absent de BD TOPAGE ;
- flags de confiance.

### 7.2. Utiliser la methode deja existante

HydroModPy possede deja des briques:

- `hydromodpy.spatial.geographic.core.flow_products` ;
- `hydromodpy.spatial.geographic.core.river_network` ;
- `hydromodpy.spatial.geographic.core.catchment_from_point` ;
- configuration `geographic.river_network.threshold_area_km2`.

Le premier developpement doit les reutiliser. Il ne faut pas introduire une
nouvelle methode de routage si la methode actuelle suffit au pilote.

### 7.3. Surface comme critere non imperatif

La surface calculee du bassin est toujours un attribut important, mais elle ne
doit pas piloter seule la generation ni la selection. Le seuil d'extraction du
reseau et la preference de surface sont deux notions differentes:

- `network_threshold_area_km2`: aire minimale pour considerer une cellule comme
  appartenant au reseau topographique ;
- `preferred_area_km2`: valeur de reference optionnelle pour scorer ou
  stratifier les bassins ;
- `hard_min_area_km2` et `hard_max_area_km2`: bornes optionnelles, utilisees
  seulement si la campagne veut exclure des bassins trop petits ou trop grands.

Modes recommandes pour le critere de surface:

```text
mode = "report"   -> surface calculee et affichee, sans effet sur le choix
mode = "score"    -> bonus si la surface est proche d'une preference
mode = "stratify" -> classes de surface utilisees pour equilibrer la selection
mode = "warning"  -> flag si la surface sort d'une plage indicative
mode = "hard_reject" -> rejet seulement si la campagne le demande explicitement
```

Exemple non bloquant:

```text
network_threshold_area_km2 = 1.0
preferred_area_km2 = 100.0
score_half_width_fraction = 0.50
area_criterion_mode = "score"
```

Dans ce cas, le reseau est extrait a partir des cellules ayant au moins environ
`1 km2` amont. Les bassins proches de `100 km2` peuvent recevoir un meilleur
score, mais un bassin de `40 km2` ou `180 km2` peut rester candidat si d'autres
criteres le rendent utile: observation disponible, contexte geologique rare,
bonne couverture spatiale, ou role de contre-exemple.

### 7.4. Probleme des doublons

Une riviere peut contenir beaucoup de cellules consecutives produisant des
bassins presque identiques, meme sans fenetre de surface dure. Si on garde tout,
le catalogue devient redondant et difficile a relire.

Il faut donc une strategie de thinning:

- grouper les cellules candidates connectees ;
- choisir un representant par segment ;
- imposer une distance minimale entre exutoires ;
- rejeter les bassins trop recouvrants ;
- optionnellement favoriser le candidat le plus utile selon les criteres de la
  campagne: observation, diversite geologique, representativite regionale,
  qualite DEM ou surface preferee.

Regle de depart proposee:

```text
candidate_score =
  overlap_penalty
  + distance_penalty
  + optional_area_preference_penalty
  - observation_bonus
  - diversity_bonus
```

On selectionne les meilleurs candidats par classe/territoire.

### 7.5. Recouvrement et bassins imbriques

Le recouvrement doit etre traite comme un critere spatial propre, distinct de la
surface. Deux bassins peuvent avoir des surfaces tres differentes et pourtant
porter presque la meme information si l'un est majoritairement inclus dans
l'autre.

Politique recommandee par defaut:

```text
criteria_crossing:
  allow_nested_basins = false
  max_pairwise_basin_overlap_fraction = 0.05
  overlap_reference = "smaller_basin"
  overlap_mode = "hard_reject"

observation_led:
  allow_nested_basins = true
  overlap_mode = "warning"
```

Dans `criteria_crossing`, l'objectif est souvent de couvrir un territoire ou une
diversite de contextes. Il faut donc eviter de retenir deux bassins presque
identiques. Une regle simple est:

```text
overlap_fraction =
  area(intersection(candidate, selected_site)) / min(area(candidate), area(selected_site))
```

Si `overlap_fraction > max_pairwise_basin_overlap_fraction`, le candidat est
rejete ou garde en reserve selon le mode choisi.

Dans `observation_led`, il faut etre plus prudent. Deux stations hydrometriques
sur le meme cours d'eau peuvent etre imbriquees mais utiles: controle amont/aval,
gradient d'influence, fermeture d'un sous-bassin, validation multi-echelle. Dans
ce cas, le recouvrement doit d'abord produire un `warning` et une evidence, pas
un rejet automatique, sauf si la campagne demande un inventaire strictement non
imbrique.

Options utiles:

```text
allow_nested_basins = false
min_outlet_distance_km = 10.0
max_pairwise_basin_overlap_fraction = 0.05
overlap_reference = "smaller_basin"
overlap_mode = "hard_reject" | "warning" | "score"
same_mainstem_policy = "allow_with_warning" | "reject_downstream" | "keep_best"
```

Avantages d'une politique stricte:

- catalogue moins redondant ;
- meilleure couverture spatiale ;
- revue humaine plus simple.

Inconvenients:

- peut supprimer des couples amont/aval utiles ;
- peut supprimer des stations observees rares ;
- depend de la qualite de la delimitation des bassins.

### 7.6. Resolution DEM

Le document ne doit pas imposer une resolution unique. Il faut une resolution par
profil:

```text
profile = "national_default" -> 25 m
profile = "regional_refined" -> 5 m ou 10 m
profile = "local_reference" -> custom haute resolution
```

La valeur par defaut pour un premier deploiement national devrait etre
intermediaire, par exemple `25 m`, car l'objectif est la robustesse et le cout.

## 8. Politique de cache et telechargement

### 8.1. Comportement par defaut

Decision retenue:

```text
cache sinon telechargement
```

Donc:

1. L'outil calcule l'emprise necessaire.
2. Il interroge le catalogue/cache.
3. Si le DEM couvre l'emprise, il le reutilise.
4. Sinon, il telecharge les tuiles manquantes si la source le permet.
5. Il indexe le resultat dans le catalogue.
6. Il utilise ce DEM pour les traitements.

### 8.2. Politiques de cache

Valeurs proposees:

```text
use_cache_else_download
use_cache_only
download_only
refresh
frozen
```

`use_cache_else_download`

- mode par defaut ;
- pratique en phase exploratoire.

`use_cache_only`

- utile si les donnees ont ete preparees a la main ;
- echoue si une donnee manque.

`download_only`

- telecharge sans reutiliser les anciens caches ;
- rarement utile.

`refresh`

- force un nouveau telechargement et remplace/complete le cache ;
- utile si la source a ete mise a jour.

`frozen`

- aucun cache miss autorise ;
- toute donnee doit correspondre a un manifest fige ;
- mode recommande pour production nationale reproductible.

Semantique recommandee:

- `cache_policy` est le champ canonique qui decrit la strategie ;
- `force_refresh` ne doit etre qu'un raccourci de compatibilite ou de CLI, mappe
  vers `refresh` dans la configuration resolue ;
- `frozen_manifest` est requis seulement si `cache_policy = "frozen"` ;
- `source = "custom"` doit fournir `path`, et ce chemin doit etre copie dans le
  manifest resolu ;
- le manifest doit distinguer la source demandee, la source effectivement lue et
  les artefacts produits.

Avantage de cette separation:

- la configuration reste lisible pour les usages interactifs ;
- les campagnes reproductibles peuvent etre gelees sans changer le reste du
  workflow ;
- les tests unitaires peuvent utiliser `custom` sans dependance reseau.

Inconvenient:

- il faut etre strict dans la validation pour eviter les combinaisons ambigues,
  par exemple `force_refresh = true` avec `cache_policy = "frozen"`.

### 8.3. Integration avec l'existant

Le code existant a deja:

- `DemManager` ;
- source `ign_bdalti` ;
- source `custom` ;
- cache DuckDB ;
- `force_refresh` ;
- detection bbox ;
- logique de `data_freeze`.

Le nouvel outil devrait consommer ces mecanismes, pas les dupliquer.

### 8.4. Cas manuel

Il faut garder une voie manuelle:

```toml
[site_selection.dem]
source = "custom"
path = "data/dem/my_dem.tif"
cache_policy = "use_cache_only"
```

Raison:

- certaines donnees peuvent venir d'un depot local ;
- certains telechargements peuvent necessiter une authentification ;
- les URLs institutionnelles peuvent changer ;
- les campagnes reproductibles preferent souvent des donnees deja gelees.

## 9. Territoire cible

### 9.1. Modes a supporter

L'outil doit supporter plusieurs modes:

```text
admin_regions
admin_departments
polygon_file
bbox
site_catalog_extent
geoparquet_filter
```

`admin_regions`

- l'utilisateur donne des noms de regions ;
- l'outil resout les geometries via une source administrative configuree ;
- utile pour: Bretagne + Normandie + Pays de la Loire.

`admin_departments`

- utile pour des campagnes plus fines ;
- evite parfois les regions trop larges.

`polygon_file`

- mode le plus generique ;
- l'utilisateur donne un GeoPackage, Shapefile ou GeoParquet.

`bbox`

- utile pour tests rapides ;
- pas ideal scientifiquement.

`site_catalog_extent`

- utile si on veut enrichir une selection existante.

`geoparquet_filter`

- utile si on veut partir d'une couche de bassins ou d'entites deja produite ;
- permet de filtrer par attributs, par exemple une region d'etude, une famille
  geologique ou une campagne precedente.

### 9.2. Generique vs France

Le coeur doit manipuler:

```text
territory = geometry + metadata
```

Pas:

```text
territory = region francaise
```

Pour la France, on peut proposer un resolver base sur Admin Express, data.gouv
ou une couche administrative fournie par l'utilisateur. Mais le code de selection
ne doit pas supposer les noms francais.

Le premier deploiement peut donc fournir des adaptateurs France, mais le coeur
du workflow doit rester base sur des geometries, des identifiants de sources et
des metadonnees. Cela permet d'appliquer le meme outil a la Bretagne, au Massif
Central, aux Alpes, au Bassin Parisien ou a un regroupement de departements sans
changer l'algorithme.

### 9.3. Exemple admin

```toml
[site_selection.territory]
mode = "admin_regions"
country = "FR"
admin_source = "custom"
admin_path = "data/admin/admin_express_regions.gpkg"
name_field = "nom"
regions = ["Bretagne", "Normandie", "Pays de la Loire"]
```

### 9.4. Exemple polygone utilisateur

```toml
[site_selection.territory]
mode = "polygon_file"
path = "data/territories/northwest_project_area.gpkg"
layer = "project_area"
```

## 10. Caracterisation et identification des regions

### 10.1. Principe

L'identification des regions ne doit pas etre seulement administrative. Elle
doit etre calculee a l'echelle du bassin.

Chaque bassin recoit une signature:

```text
signature =
  topographie
+ morphometrie
+ climat/recharge
+ geologie/hydrogeologie
+ occupation du sol
+ observations disponibles
+ anthropisation
```

Ensuite on peut produire:

- une typologie experte lisible ;
- une stratification ;
- plus tard, un clustering statistique.

### 10.2. Notion de region

Le mot `region` est ambigu et doit etre explicite dans le workflow. On distingue
au moins cinq notions:

```text
territory
admin_region
hydro_region
expert_region_type
selection_group
```

`territory`

- perimetre de campagne donne par l'utilisateur ;
- exemple: Bretagne + Normandie + Pays de la Loire, un departement, une bbox ou
  un polygone de projet ;
- sert a limiter la recherche et a organiser les sorties.

`admin_region`

- region administrative francaise ou autre unite administrative ;
- utile pour les quotas, les rapports et le dialogue avec les acteurs ;
- avantage: lisible et stable pour les utilisateurs ;
- inconvenient: rarement homogene du point de vue hydrologique ou geologique.

`hydro_region`

- famille hydrographique ou hydrogeologique issue de donnees physiques ;
- peut venir d'un bassin versant majeur, d'une entite BDLISA, d'une grande unite
  geologique ou d'une typologie climatique ;
- avantage: plus proche des processus ;
- inconvenient: depend fortement des donnees disponibles et de leur echelle.

`expert_region_type`

- classe calculee par le workflow a l'echelle du bassin candidat ;
- exemple: `hilly_humid_crystalline_low_storage` ;
- avantage: directement reliee aux criteres scientifiques ;
- inconvenient: les seuils doivent etre versionnes et justifies.

`selection_group`

- groupe pratique pour la campagne, par exemple `headwater_10km2`,
  `observed_100km2`, `karstic_holdout` ;
- avantage: souple pour organiser les exports et les revues ;
- inconvenient: peut devenir arbitraire si la provenance n'est pas documentee.

Pour l'instant, le perimetre reste la France. Cela justifie des sources France v1
et des exemples francais, mais pas une logique limitee au Massif Armoricain. Le
Massif Armoricain doit rester un pilote commode pour tester les chemins locaux,
pas une hypothese structurelle.

### 10.3. Typologie experte v1

Classes de depart:

```text
relief = lowland | hilly | mountain
climate = dry | intermediate | humid
geology = crystalline | sedimentary | karstic | alluvial | volcanic | mixed
storage = low | medium | high | unknown
drainage = low | medium | high
anthropization = low | medium | high | unknown
observation = ungauged | flow | piezo | flow_and_piezo | onde | mixed
```

`expert_region_type` peut etre compose:

```text
hilly_humid_crystalline_low_storage
lowland_intermediate_sedimentary_high_storage
mountain_humid_karstic_high_drainage
```

Ces classes ne doivent pas etre obligatoires pour tous les usages. Une campagne
peut choisir de les utiliser seulement pour le rapport, pour la stratification,
ou pour une priorisation douce. Les rendre bloquantes trop tot risquerait de
rejeter des bassins simplement parce qu'une couche geologique ou de recharge est
incomplete.

### 10.4. Regles exemple

Relief:

```text
if mean_slope_pct < 2 and relief_amplitude_m < 100:
    relief = "lowland"
elif mean_slope_pct < 8 and relief_amplitude_m < 500:
    relief = "hilly"
else:
    relief = "mountain"
```

Climat:

```text
if recharge_mean_mm_y > 350:
    climate = "humid"
elif recharge_mean_mm_y > 150:
    climate = "intermediate"
else:
    climate = "dry"
```

Geologie:

```text
if crystalline_fraction > 0.6:
    geology = "crystalline"
elif carbonate_fraction > 0.6 and karst_flag:
    geology = "karstic"
elif sedimentary_fraction > 0.6:
    geology = "sedimentary"
elif alluvial_fraction > 0.4:
    geology = "alluvial"
else:
    geology = "mixed"
```

Drainage:

```text
if drainage_density_km_km2 > 1.5:
    drainage = "high"
elif drainage_density_km_km2 > 0.7:
    drainage = "medium"
else:
    drainage = "low"
```

### 10.5. Versionner les regles

Chaque typologie doit stocker:

```text
ruleset_id = "expert_v1"
ruleset_hash = "..."
expert_region_type = "hilly_humid_crystalline_low_storage"
rule_evidence_json = {...}
```

Cela permet de comparer les selections si les seuils changent.

## 11. Donnees mobilisables

### 11.1. Donnees indispensables

DEM:

- source principale du workflow ;
- doit couvrir le territoire avec marge ;
- doit permettre accumulation et delimitation.

Limite administrative ou polygone:

- sert seulement a limiter le territoire de recherche ;
- pas a definir les bassins.

### 11.2. Donnees fortement utiles

Geologie:

- BRGM 1M ou 50k ;
- utile pour typologie et priorisation ;
- peut aussi servir a forcer une diversite de contextes, par exemple garder des
  bassins cristallins, sedimentaires, karstiques et alluviaux.

Avantage:

- donne un sens physique fort a la selection.

Inconvenient:

- les cartes geologiques changent d'echelle et de nomenclature ; il faut donc
  normaliser les classes et garder les fractions d'origine dans les evidences.

Recharge/climat:

- SIM2/SAFRAN-ISBA ou source equivalent ;
- utile pour typologie et interpretation.

Occupation du sol:

- Theia OSO, Corine Land Cover ou source custom ;
- utile pour anthropisation et recharge potentielle.

Obstacles/prelevements:

- utile pour exclure ou flagger les bassins fortement modifies.

Observations:

- Hub'Eau hydrometrie ;
- Hub'Eau piezometrie ;
- ONDE ;
- utile pour selection de sites de validation.

Les observations ne doivent pas etre traitees comme un critere unique. Une
station de debit proche de l'exutoire, un piezometre dans le bassin et un point
ONDE n'ont pas le meme role.

Hydrometrie:

- peut donner un bonus si une station est proche de l'exutoire ou controle une
  aire coherente avec le bassin ;
- peut devenir un critere fort pour une campagne de validation debit ;
- ne doit pas devenir obligatoire par defaut, sinon l'inventaire sera biaise vers
  les bassins deja jauges.

Dans une strategie `observation_led`, l'hydrometrie change de statut:

- l'existence d'une station devient le principe de generation des candidats ;
- la longueur de chronique, la qualite et la coherence station/bassin deviennent
  des criteres primaires ;
- les influences amont doivent etre controlees avant les criteres de surface ou
  de geologie.

Controle d'influence des stations:

- barrages, retenues et grands plans d'eau amont ;
- prelevements ou restitutions majeurs ;
- regulation connue du troncon ;
- rejet industriel ou urbain dominant ;
- incoherence entre aire controlee annoncee et aire DEM calculee.

Ces controles peuvent etre `hard_reject` dans une campagne de reference
hydrologique, mais seulement `warning` ou `report_only` dans une campagne qui
cherche justement des gradients d'influence.

Piezometrie:

- utile pour selectionner des sites ou le comportement souterrain est observable ;
- peut aider a choisir des bassins pour la calibration ou la validation de
  stockage ;
- relation plus indirecte avec le bassin de surface: distance, aquifere et unite
  hydrogeologique doivent etre exportes comme evidence.

ONDE ou observations d'assec:

- utile pour identifier des petits bassins sensibles a l'intermittence ;
- peut etre un critere de stratification ou de rapport ;
- rarement suffisant seul pour retenir ou rejeter un site.

### 11.3. Donnees optionnelles

BD TOPAGE:

- controle qualite ;
- comparaison de reseaux ;
- non bloquant dans le mode `DEM-only`.

Sols:

- utile pour stockage/infiltration ;
- peut attendre une deuxieme version si l'acces aux donnees est complexe.

Hydrogeologie BDLISA:

- tres utile scientifiquement ;
- peut devenir prioritaire pour la parametrisation, mais pas forcement pour
  l'inventaire DEM-only minimal.

## 12. Filtres et decisions

### 12.1. Organisation des criteres

Les criteres doivent etre organises par familles et par mode d'utilisation.
L'objectif est d'ajouter des criteres sans modifier toute la chaine de sortie.

Familles de criteres possibles:

```text
geometry_area
spatial_overlap
dem_hydrology
observations
hydro_station_influence
geology_hydrogeology
climate_recharge
land_cover_anthropization
spatial_balance
numerical_readiness
external_consistency
```

Modes d'utilisation:

```text
hard_reject
warning
score
stratify
report_only
```

Le principe directeur decide quels criteres sont primaires:

```text
observation_led:
  primary = observation_available + observation_quality + non_influence
  secondary = area + geology + hydrogeology + spatial_balance

criteria_crossing:
  primary = configured physical/spatial axes
  secondary = observations + influence diagnostics + local refinements
```

Dans `observation_led`, une station hydro peut donc etre le premier critere au
sens fort: sans station, il n'y a pas de candidat dans cette campagne. Les
criteres de non-influence viennent immediatement apres, car une station fortement
modifiee par un barrage, une derivee ou un prelevement majeur ne porte pas le
meme signal hydrologique. Les criteres de surface, de geologie ou de region
interviennent ensuite pour trier, stratifier ou documenter.

Dans `criteria_crossing`, le workflow ne part pas des stations. Il croise
directement les axes physiques ou spatiaux declares: surface, geologie, relief,
climat, occupation du sol, hydrogeologie, representativite regionale, etc. Les
stations peuvent alors etre un bonus, une strate ou une information de rapport,
mais elles ne definissent pas le catalogue initial.

`hard_reject`

- rejette un site si une condition minimale n'est pas respectee ;
- exemples par defaut: DEM absent, geometrie invalide, bassin vide ;
- exemples seulement si la campagne le demande: aire sous une borne minimale,
  aire au-dessus d'une borne maximale, anthropisation excessive ;
- avantage: robuste et facile a expliquer ;
- inconvenient: peut exclure trop fortement si les donnees amont sont
  incompletes.

`warning`

- conserve le site mais ajoute un flag ;
- exemples: geologie manquante, faible relief, station de debit trop eloignee ;
- avantage: garde de la souplesse pour la revue humaine ;
- inconvenient: demande une lecture attentive du rapport.

`score`

- ajoute ou retranche une composante de priorisation ;
- exemples: bonus si une station hydrometrique fiable est proche, bonus de
  diversite geologique, penalite si l'occupation urbaine est elevee ;
- avantage: permet de classer des sites comparables ;
- inconvenient: peut masquer les arbitrages si les composantes ne sont pas
  exportees separement.

`stratify`

- sert a equilibrer la selection finale entre classes ;
- exemples: maximum par `expert_region_type`, quota par `admin_region`, diversite
  geologique ;
- avantage: evite une selection concentree dans une seule zone ou un seul type
  physique ;
- inconvenient: peut retenir un site moins bon localement pour ameliorer la
  representativite globale.

`report_only`

- calcule une information sans influencer automatiquement la decision ;
- exemples: distance a BD TOPAGE, presence de piezometres proches, fraction
  alluviale ;
- avantage: evite de surcontraindre la v1 ;
- inconvenient: laisse une part de decision a la revue humaine.

Chaque critere doit avoir:

```text
criterion_id
family
mode
thresholds
weight
required_data_layers
evidence_fields
version
```

Cas particulier de la surface:

- `area_km2` est toujours calculee ;
- `preferred_area_km2` est optionnel ;
- la surface est `report_only` par defaut ;
- elle devient `score`, `stratify`, `warning` ou `hard_reject` uniquement si la
  configuration le precise ;
- une campagne `area_only` est autorisee, mais elle doit declarer que la surface
  est le seul critere scientifique et que les autres couches sont `report_only`
  ou garde-fous techniques ;
- une borne dure de surface doit etre justifiee dans le manifest, car elle peut
  exclure des sites scientifiquement utiles.

Cas particulier du recouvrement:

- le recouvrement doit etre calcule apres delimitation, pas avant ;
- il compare les geometries de bassins, pas seulement la distance entre exutoires ;
- dans `criteria_crossing`, le mode par defaut recommande est `hard_reject` ou
  `score` fort, pour eviter un catalogue redondant ;
- dans `observation_led`, le mode par defaut recommande est `warning`, parce que
  des stations amont/aval peuvent etre utiles ;
- toute exception doit etre explicite dans `criteria_components.parquet`.

Cette structure permet de commencer simplement, puis d'ajouter des criteres plus
scientifiques. Par exemple, une campagne nationale peut d'abord utiliser
couverture DEM, geometrie valide et espacement, puis ajouter la surface comme
score ou classe de stratification, puis un bonus d'observation de debit, puis
une stratification par geologie dominante.

### 12.2. Statuts

Proposition:

```text
candidate
rejected_area_if_configured
rejected_duplicate
rejected_nested
rejected_overlap
rejected_too_close
rejected_dem_coverage
rejected_territory
rejected_station_missing
rejected_station_influenced
rejected_quality
selected
selected_priority
selected_holdout
```

### 12.3. Flags bloquants

```text
DEM_MISSING
DEM_INCOMPLETE_COVERAGE
FLOW_ACCUMULATION_FAILED
OUTLET_OUTSIDE_TERRITORY
CATCHMENT_EMPTY
CATCHMENT_GEOMETRY_INVALID
OUTLET_TOO_CLOSE_TO_SELECTED
BASIN_OVERLAP_TOO_HIGH
FLOW_STATION_MISSING
FLOW_STATION_TOO_SHORT_RECORD
FLOW_STATION_STRONGLY_INFLUENCED
MAJOR_DAM_UPSTREAM
MAJOR_WITHDRAWAL_UPSTREAM
DUPLICATE_CANDIDATE
NESTED_BASIN_REJECTED
```

### 12.4. Flags non bloquants

```text
LOW_RELIEF
FLAT_AREA
HIGH_URBAN_FRACTION
AREA_OUTSIDE_PREFERENCE
BASIN_OVERLAP_WARNING
POSSIBLE_MAJOR_OBSTACLE
POSSIBLE_MAJOR_WITHDRAWAL
NO_OBSERVATION_NEARBY
FLOW_STATION_FAR_FROM_OUTLET
PIEZOMETRY_MISSING
POSSIBLE_STATION_INFLUENCE
BDTOPAGE_MISMATCH
GEOLOGY_MISSING
GEOLOGY_CLASS_UNCERTAIN
RECHARGE_MISSING
```

### 12.5. Score de selection

Le score ne doit pas remplacer les flags, mais aider a trier:

```text
score =
  optional_area_score
+ spacing_score
+ overlap_score
+ data_quality_score
+ diversity_score
+ observation_bonus
+ geology_diversity_score
- influence_penalty
- warning_penalty
```

Pour garder la selection explicable, chaque composante doit etre exportee.

Exemples de composants:

- `optional_area_score`: proximite a une surface preferee, si ce critere est
  active ;
- `spacing_score`: distance aux sites deja retenus ;
- `overlap_score`: penalite ou rejet si le bassin recouvre trop fortement un
  site deja retenu ;
- `observation_bonus`: presence d'une station de debit ou d'un suivi
  piezometrique pertinent ;
- `influence_penalty`: penalite ou rejet selon le principe directeur et la force
  de l'influence detectee ;
- `geology_diversity_score`: contribution a la diversite geologique de la
  campagne ;
- `data_quality_score`: couverture DEM, couches disponibles et coherence des
  geometries ;
- `warning_penalty`: penalites liees aux flags non bloquants.

## 13. Sorties

### 13.1. Nature des sorties

Les sorties doivent servir plusieurs usages distincts. Le workflow ne doit donc
pas produire seulement un CSV final.

Sorties canoniques:

- decrivent les candidats, bassins, signatures, criteres et decisions ;
- sont lisibles par machine ;
- doivent etre stables dans le temps autant que possible.

Sorties SIG:

- portent les geometries: territoire, exutoires, bassins, emprises disponibles ;
- servent a la revue spatiale et aux controles externes ;
- doivent indiquer le CRS et la source de chaque geometrie.

Sorties de decision:

- expliquent pourquoi un site est retenu, rejete ou mis en attente ;
- stockent les flags, scores, criteres et evidences ;
- doivent permettre de reconstruire une selection sans relire tout le code.

Sorties de compatibilite:

- adaptent la selection pour `regional_lab` et les testbeds ;
- ne sont pas le resultat scientifique complet ;
- peuvent contenir des alias historiques comme `x_outlet` et `y_outlet`.

Sorties de revue humaine:

- rapport Markdown, synthese JSON et page HTML ;
- doivent etre lisibles par campagne, pas seulement par developpeur ;
- doivent montrer les arbitrages: surface, observations, geologie, regions,
  flags et raisons de rejet.

La separation est volontaire:

- avantage: les exports aval peuvent evoluer sans casser le catalogue canonique ;
- avantage: les criteres restent auditables ;
- inconvenient: il y a plus d'artefacts a maintenir, donc le manifest doit etre
  strict et central.

### 13.2. Repertoire de sortie

```text
outputs/site_selection/<selection_id>/
  site_selection_manifest.json
  site_selection_config_resolved.toml
  territory.gpkg
  dem_request.json
  hydrology_products.json
  candidate_outlets.parquet
  candidate_outlets.gpkg
  delineated_sites.geoparquet
  rejected_sites.parquet
  selected_sites.geoparquet
  selected_sites.csv
  regional_lab_sites.csv
  site_signatures.parquet
  observation_evidence.parquet
  data_layers_summary.json
  criteria_components.parquet
  criteria_summary.json
  expert_regions.parquet
  selection_decisions.parquet
  selection_report.md
  selection_summary.json
  review/
    index.html
    map_selection.png
    selected_site_emprises.geojson
    assets/
```

`selected_site_emprises.geojson` doit etre interprete selon la maturite du
workflow. Dans la consolidation de l'existant, il peut contenir les emprises de
mesh ou les emprises disponibles avec un champ `geometry_source`. Apres la
delimitation DEM-only, il doit contenir les polygones de bassins.

### 13.3. `selected_sites.*`

`selected_sites.geoparquet` est l'export canonique des sites retenus. Il doit
porter au minimum:

```text
site_id
selection_id
selection_principle
territory_id
admin_region
expert_region_type
geometry
outlet_x
outlet_y
outlet_crs
area_km2
area_class
area_preference_km2
optional_area_score
max_overlap_fraction_with_selected
nearest_selected_site_id
distance_to_nearest_selected_km
selection_status
selection_reason
rank_score
blocking_flags
warning_flags
criteria_summary_json
```

`selected_sites.csv` est une vue tabulaire de confort. Elle peut perdre la
geometrie, mais pas les identifiants, les statuts et les chemins vers les
artefacts.

### 13.4. `regional_lab_sites.csv`

Colonnes minimales compatibles:

```text
site_id
site_label
cluster_id
cluster_label
cluster_family
cluster_scale
region_id
source_selection_id
selection_principle
site_status
maturity
x
y
x_outlet
y_outlet
area_km2
tags
enabled
```

Colonnes supplementaires utiles:

```text
target_area_km2
area_score_half_width_fraction
area_class
area_preference_km2
optional_area_score
max_overlap_fraction_with_selected
nearest_selected_site_id
distance_to_nearest_selected_km
outlet_x
outlet_y
outlet_crs
territory_id
candidate_source
admin_region
expert_region_type
hydro_region
relief_class
climate_class
geology_class
drainage_class
anthropization_class
observation_summary
criteria_summary_json
selection_reason
blocking_flags
warning_flags
dem_source
dem_resolution_m
source_selection_manifest
```

Regle de compatibilite:

- `x` et `y` restent les coordonnees de reference attendues par
  `regional_lab` ;
- `x_outlet` et `y_outlet` doivent etre exportes aussi, car plusieurs recettes
  et templates existants les utilisent directement ;
- `outlet_x` et `outlet_y` peuvent etre gardes dans les exports canoniques, mais
  le CSV aval doit rester compatible avec les conventions existantes ;
- `area_km2` est l'aire calculee si elle existe ;
- `target_area_km2` peut etre exporte pour compatibilite historique, ou si une
  campagne declare une preference de surface ou une plage de surface nommee ;
- `area_preference_km2` et `optional_area_score` rendent explicite le fait que la
  surface a ete utilisee comme critere non imperatif ;
- quand un catalogue historique n'a pas encore d'aire calculee fiable,
  `area_km2` peut etre vide, mais le manifest doit le signaler.

### 13.5. Manifest

Le manifest doit repondre aux questions:

- quelle configuration a ete utilisee ?
- quel principe directeur de selection ?
- quel territoire ?
- quel DEM ?
- quelles donnees ont ete telechargees ?
- quelles donnees venaient du cache ?
- quelle version de regles ?
- quelles couches optionnelles etaient disponibles ?
- quels criteres etaient bloquants, faibles, de score ou seulement rapportes ?
- combien de candidats ?
- combien rejetes ?
- combien selectionnes ?
- pourquoi ?

### 13.6. Page HTML de revue

La page HTML commence comme un artefact de revue humaine, puis devient une
sortie officielle du workflow. Elle doit etre associee a une seule selection
identifiee par `selection_id`; elle ne doit pas devenir une page globale qui
melange toutes les campagnes.

Sources actuelles:

```text
hydromodpy/spatial/site_selection/html_report.py
hydromodpy/spatial/site_selection/reporting.py
```

`html_report.py` porte le rapport HTML v0 branche sur
`site_selection_manifest.json`. `reporting.py` reste le renderer historique plus
cartographique issu de l'inventaire Boussinesq; il pourra etre refactorise plus
tard pour enrichir la v0 avec fonds cartographiques et emprises.

Sortie actuelle/cible:

```text
outputs/site_selection/<selection_id>/review/index.html
```

Regles de contenu v0:

- resume de la campagne et compteurs ;
- strategie, territoire et ruleset ;
- tables des sites retenus et rejetes ;
- raisons de rejet et flags bloquants ;
- synthese des criteres traces ;
- liens vers `selected_sites.csv`, `rejected_sites.csv`,
  `regional_lab_sites.csv`, `site_selection_decisions.jsonl`,
  `criteria_components.jsonl` et le manifest.

Regles de contenu cartographique a ajouter ensuite:

- titre court centre sur le type de selection, par exemple `headwater 10 km2` ;
- carte principale avec topographie regionale en fond, contour de region et
  emprise disponible de chaque site ;
- numeros sobres sur la carte, pas de legende complete repetee ;
- coordonnees et distances en unites relatives au territoire de revue ;
- table HTML qui relie numero, `site_id`, surface, famille, statut, tags,
  observations, classes geologiques, flags et chemins utiles ;
- miniatures ou cartes de bassin cliquables quand elles existent ;
- graphiques simples de repartition: surface, altitude, pente, espacement,
  classes/regions ;
- aucun detail de methode numerique MF6/Boussinesq dans cette page.

Dans les premieres versions, `emprise disponible` peut vouloir dire emprise de
mesh ou contour reconstruit depuis un bundle. Une fois la delimitation DEM-only
active, la meme page doit afficher les bassins amont. Le champ `geometry_source`
doit rendre cette difference visible.

Ameliorations progressives prevues:

1. stabiliser le rendu actuel depuis les inventaires existants ;
2. rendre les filtres `selection_id`, `scale`, `family`, `tags`, `site_group`
   reproductibles depuis config ;
3. ajouter les candidats rejetes et les raisons de rejet ;
4. ajouter les controles de couverture spatiale et d'espacement ;
5. brancher la page sur le manifest du workflow au lieu de scripts ad hoc ;
6. reutiliser la meme page pour les selections par echelle ou par famille.

## 14. Integration avec `regional_lab`

### 14.1. Frontiere actuelle

`regional_lab` sait deja:

- lire un catalogue CSV/JSONL ;
- mapper les colonnes ;
- filtrer par region, famille, tags, statut, maturite ;
- appliquer des recettes ;
- produire inventaire, plan et rapports.

Le nouvel outil doit donc produire un catalogue conforme.

Les fichiers actuels qui servent de reference de compatibilite sont:

- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/natural_regional_lab.toml` ;
- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/natural_regional_lab_sites.csv` ;
- `hydromodpy/analysis/testbed/regional_lab_catalog.py` ;
- `hydromodpy/analysis/testbed/regional_lab_site_selection.py`.

Le premier objectif n'est donc pas de refaire `regional_lab`, mais de produire
un `regional_lab_sites.csv` equivalent ou meilleur a partir d'artefacts
`site_selection`.

### 14.2. Flux recommande

```text
hmp site-selection build-observed site_selection.toml

hmp run natural_regional_lab.toml
```

Ou:

```toml
[regional_lab.catalog]
path = "../../outputs/site_selection/france_100km2_dem_only_v1/regional_lab_sites.csv"
```

### 14.3. Pourquoi ne pas fusionner

`site_selection`:

- fabrique les sites.

`regional_lab`:

- fabrique les cas site x recette.

`testbed`:

- lance les cas et collecte les metriques.

Cette separation garde chaque outil testable et comprehensible.

### 14.4. Points de contact autorises

Les deux briques doivent se parler par artefacts, pas par appels internes
fortement couples.

Points de contact recommandes:

- `regional_lab_sites.csv` ;
- `selected_sites.geoparquet` ;
- `site_selection_manifest.json` ;
- colonne `source_selection_id` ;
- colonne `selection_principle` ;
- colonnes `cluster_family`, `cluster_scale`, `region_id`, `tags` ;
- colonnes de coordonnees compatibles: `x`, `y`, `x_outlet`, `y_outlet` ;
- chemins optionnels vers produits geographiques si une recette en a besoin.

Ce que `regional_lab` peut faire avec ces champs:

- filtrer les sites ;
- grouper les sites ;
- choisir quelles recettes appliquer ;
- documenter la provenance de la selection.

Ce que `regional_lab` ne doit pas faire:

- recalculer le DEM ;
- regenerer le reseau hydrographique ;
- rede limiter les bassins ;
- modifier les criteres de selection geographique.

Si une campagne veut changer le territoire, la methode DEM-only, les criteres ou
les poids de decision, elle doit relancer `site_selection` et produire un nouveau
`source_selection_id`. Cela vaut aussi si la surface passe de simple information
rapportee a critere de score, de stratification ou de rejet.

## 15. Plan d'implementation

Le plan de developpement doit commencer par rassembler l'existant. Les jalons
historiques ci-dessous restent valables pour l'algorithme DEM-only, mais la
premiere tranche doit etre un workflow de consolidation capable de lire des
catalogues/candidats existants, de produire la page HTML de revue, et d'exporter
un catalogue regional-lab compatible.

Ordre de decision recommande:

1. stabiliser le contrat de configuration, de criteres et de sorties ;
2. consolider les catalogues et emprises existants ;
3. rendre la page HTML officielle pour la revue humaine ;
4. ajouter progressivement la detection DEM-only ;
5. enrichir les criteres: observations, geologie, hydrogeologie, occupation du
   sol, anthropisation et representativite territoriale.

Les jalons A et B peuvent donc avancer avant l'algorithme DEM-only complet, mais
ils doivent rester honnetes sur la provenance des geometries. Avant le Milestone
5, une emprise peut etre une emprise de mesh ou une emprise importee, pas encore
un bassin delimite par le workflow.

### Milestone A - consolidation de l'existant

Objectif:

- disposer d'un workflow amont utilisable avant meme d'implementer toute la
  detection DEM-only.

Taches:

- definir `[workflow] mode = "site_selection"` ;
- brancher un coeur commun appele par `hmp run` et par `hmp site-selection` ;
- lire un catalogue existant de type `natural_regional_lab_sites.csv` ;
- lire les candidats/imports issus de `examples/projects/07_mesh_gallery` ;
- reutiliser `hydromodpy.analysis.catalog` pour les lectures generiques ;
- produire la page HTML via le rapport manifest courant ;
- ecrire un `site_selection_manifest.json` minimal ;
- ecrire `selected_sites.csv` et `regional_lab_sites.csv` ;
- ecrire `criteria_components.parquet` minimal avec au moins provenance,
  principe directeur, surface calculee, mode du critere de surface et statut ;
- documenter la provenance par `source_selection_id`.

Livrable:

- un workflow qui regenere une selection `headwater 10 km2` depuis l'existant ;
- `review/index.html` associe ;
- export regional-lab relisible par `regional_lab`.

### Milestone B - page HTML et carte comme artefact officiel

Objectif:

- faire de la page HTML de revue le support de validation humaine de chaque
  selection.

Taches:

- deplacer les options utiles du script de revue dans la configuration
  `site_selection` ;
- garantir une page par selection, pas une page globale ;
- conserver le fond topo regional et le contour de region ;
- afficher l'emprise disponible des sites, avec `geometry_source` ;
- garder les numeros sobres sur la carte et les details dans la table ;
- ajouter les graphiques de distribution utiles: surface, classes expertes,
  observations disponibles, geologie si disponible ;
- verifier que la page ne contient pas de detail de methode numerique.

Livrable:

- `outputs/site_selection/<selection_id>/review/index.html` ;
- `map_selection.png` ;
- `selected_site_emprises.geojson`.

### Milestone 0 - specification contractuelle

Objectif:

- figer le contrat de config, de criteres et de sortie.

Taches:

- creer ce document ;
- definir les modeles Pydantic ;
- definir les artefacts attendus ;
- definir le schema extensible des criteres ;
- definir les principes directeurs v1: `observation_led` et
  `criteria_crossing` ;
- definir les alias de colonnes compatibles `regional_lab` ;
- choisir le nom du package ;
- choisir le nom des commandes CLI.

Livrable:

- fichier de spec ;
- tests de validation config sans execution.

### Milestone 1 - territoire

Objectif:

- resoudre un territoire cible.

Taches:

- implementer `polygon_file` ;
- implementer `bbox` ;
- preparer l'interface `admin_regions` ;
- exporter `territory.gpkg` ;
- calculer bbox + marge.

Livrable:

- `TerritorySpec` ;
- tests unitaires avec polygone synthetique.

### Milestone 2 - DEM cache/download

Objectif:

- obtenir le DEM necessaire sans logique ad hoc.

Taches:

- connecter l'outil au `DemManager` ;
- supporter `custom` ;
- supporter `ign_bdalti` si la source est configuree ;
- implementer `use_cache_else_download` ;
- preparer `frozen` ;
- ecrire `dem_request.json`.

Livrable:

- DEM resolu pour une petite bbox ;
- tests avec DEM custom local ;
- pas de test unitaire dependant d'une API externe.

### Milestone 3 - produits hydrologiques

Objectif:

- produire les rasters necessaires.

Taches:

- reutiliser `flow_products` ;
- reutiliser `river_network` ;
- exposer `network_threshold_area_km2` ;
- ecrire `hydrology_products.json` ;
- gerer les echecs.

Livrable:

- corrected DEM ;
- D8 direction ;
- D8 accumulation ;
- stream raster ;
- Strahler si demande.

### Milestone 4 - exutoires candidats

Objectif:

- identifier des points candidats sur le reseau sans supposer qu'une surface
  cible soit obligatoire.

Taches:

- convertir accumulation en aire km2 ;
- produire plusieurs strategies de candidats: echantillonnage du reseau, classes
  de surface, observations proches, confluences, imports ;
- supporter `station_outlets` pour `observation_led` ;
- contraindre aux cellules de reseau ;
- grouper/thinner les candidats ;
- calculer la surface comme attribut et, si configure, comme score optionnel ;
- exporter `candidate_outlets.parquet`.

Livrable:

- liste de candidats avec aire amont et provenance de generation.

### Milestone 5 - delimitation et filtrage

Objectif:

- transformer les candidats en bassins.

Taches:

- reutiliser la delimitation depuis point ;
- calculer surface polygonale ;
- rejeter uniquement les echecs structurels et les criteres explicitement
  bloquants ;
- rejeter geometries invalides ;
- gerer bassins imbriques ;
- exporter sites rejetes et retenus.

Livrable:

- `delineated_sites.geoparquet` ;
- `rejected_sites.parquet`.

### Milestone 6 - signatures et regions expertes

Objectif:

- caracteriser les bassins.

Taches:

- topographie ;
- morphometrie ;
- drainage ;
- classes expertes minimales ;
- structure pour geologie/recharge/occupation du sol en option ;
- structure pour stations de debit, piezometres et autres observations ;
- evidence JSON par couche et par critere.

Livrable:

- `site_signatures.parquet` ;
- `observation_evidence.parquet` ;
- `data_layers_summary.json` ;
- `expert_regions.parquet`.

### Milestone 7 - stratification

Objectif:

- produire une selection finale utile.

Taches:

- `max_sites_per_class` ;
- `limit` global ;
- tri stable ;
- seed aleatoire optionnelle ;
- quotas par admin region ;
- quotas par `expert_region_type` ;
- quotas ou bonus par disponibilite d'observations ;
- diversification geologique optionnelle.

Livrable:

- `selected_sites.geoparquet` ;
- `selected_sites.csv`.

### Milestone 8 - export regional_lab

Objectif:

- brancher directement sur les campagnes.

Taches:

- mapping colonnes ;
- alias `x`, `y`, `x_outlet`, `y_outlet` ;
- tags ;
- `source_selection_id` ;
- `cluster_family` / `cluster_scale` ;
- manifest associe ;
- exemple de `natural_regional_lab.toml`.

Livrable:

- `regional_lab_sites.csv` compatible.

### Milestone 9 - rapport

Objectif:

- rendre la selection lisible.

Taches:

- resume compteurs ;
- histogramme surfaces ;
- rejets par raison ;
- sites par region ;
- sites par `admin_region`, `hydro_region` et `expert_region_type` ;
- synthese observations disponibles ;
- synthese geologie/hydrogeologie si disponible ;
- synthese des criteres et poids ;
- top warnings ;
- liens vers artefacts ;
- generation HTML depuis le manifest.

Livrable:

- `selection_report.md` ;
- `review/index.html`.

### Milestone 10 - durcissement national

Objectif:

- rendre le workflow fiable a grande echelle.

Taches:

- mode `frozen` ;
- reprise apres interruption ;
- parallelisation controlee ;
- verrous de cache ;
- logs structures ;
- tests de non-regression sur petit DEM.

Livrable:

- premiere campagne pilote robuste.

## 16. Tests

### 16.1. Tests unitaires

Tester sans donnees externes:

- validation config ;
- validation des principes directeurs et de l'ordre des criteres ;
- evaluation du critere de surface dans les modes `report`, `score`,
  `stratify`, `warning` et `hard_reject` ;
- evaluation du recouvrement entre polygones synthetiques ;
- evaluation d'une strategie `observation_led` avec station fictive influencee
  et non influencee ;
- generation de candidats sans fenetre d'aire obligatoire ;
- thinning de candidats ;
- rejection reasons ;
- typologie experte ;
- evaluation des criteres par mode: `hard_reject`, `warning`, `score`,
  `stratify`, `report_only` ;
- normalisation des observations fictives ;
- alias de colonnes `regional_lab` ;
- export CSV regional_lab.

### 16.2. Tests integration petits

Utiliser un DEM synthetique minuscule:

- pente simple ;
- deux thalwegs ;
- exutoires attendus ;
- bassins attendus.

Tester:

- generation accumulation ;
- candidats ;
- delimitation ;
- croisement avec couches vectorielles synthetiques ;
- selection finale sans recouvrement excessif ;
- scoring et stratification ;
- exports.

### 16.3. Tests API

Les telechargements IGN/Hub'Eau/SIM2 ne doivent pas etre requis en unit tests.

Approche:

- tests API marques `external` ;
- mocks/fakes pour les tests courants ;
- fixtures locales petites ;
- manifests geles.

## 17. Risques

### 17.1. Trop de candidats presque identiques

Cause:

- toutes les cellules d'un troncon peuvent produire des bassins tres proches ;
- les modes de generation larges produisent plus de candidats qu'une fenetre de
  surface stricte.

Mitigation:

- regroupement par segments ;
- distance minimale ;
- rejet bassins tres recouvrants ;
- score de representativite par criteres ;
- surface comme score optionnel, pas comme unique filtre.

### 17.2. Zones plates

Cause:

- D8 instable ;
- corrections hydrologiques sensibles.

Mitigation:

- flags `LOW_RELIEF`, `FLAT_AREA` ;
- controle accumulation ;
- possibilite de rejeter les zones trop incertaines au debut.

### 17.3. Cout DEM

Cause:

- haute resolution nationale ;
- tuiles nombreuses ;
- traitements lourds.

Mitigation:

- resolution par defaut intermediaire ;
- cache ;
- telechargement a la demande ;
- prechauffage optionnel par region ;
- mode `plan` avant `build`.

### 17.4. Generique du code

Cause:

- tentation de coder des regions francaises et sources IGN directement dans les
  algorithmes.

Mitigation:

- `TerritorySpec` generique ;
- providers de donnees ;
- source IGN comme configuration ;
- tests avec polygone/DEM custom.

### 17.5. Biais des criteres d'observation

Cause:

- les bassins avec stations de debit ou piezometres sont plus faciles a valider ;
- les rendre obligatoires peut exclure les bassins non instrumentes ;
- les reseaux de mesure ne sont pas repartis uniformement.

Mitigation:

- utiliser les observations comme bonus ou critere de stratification par defaut ;
- reserver les criteres bloquants aux campagnes explicitement orientees
  validation observee ;
- exporter la distance, la periode disponible et la qualite de chaque observation.

### 17.6. Confusion entre principe directeur et critere secondaire

Cause:

- traiter une station hydro comme un simple bonus alors que la campagne vise des
  bassins observes ;
- ou, inversement, imposer des stations dans une campagne qui cherche surtout la
  representativite physique du territoire.

Mitigation:

- rendre `selection_principle` obligatoire dans la configuration resolue ;
- documenter l'ordre des criteres dans le manifest ;
- verifier que `observation_led` applique les controles de non-influence avant
  les criteres de surface/geologie ;
- verifier que `criteria_crossing` ne rejette pas les bassins non jauges par
  defaut.

### 17.7. Sur-specialisation des regions

Cause:

- confondre region administrative, region geologique, region hydrologique et
  groupe de selection ;
- calibrer les seuils sur le seul Massif Armoricain.

Mitigation:

- nommer explicitement `admin_region`, `hydro_region`, `expert_region_type` et
  `selection_group` ;
- tester rapidement sur au moins deux contextes francais contrastes ;
- versionner les regles expertes et garder les evidences de classification.

### 17.8. Reproductibilite

Cause:

- donnees telechargees a des dates differentes ;
- APIs changeantes ;
- caches partiels.

Mitigation:

- manifest ;
- checksums ;
- mode `frozen` ;
- `site_selection_config_resolved.toml`.

## 18. Questions ouvertes pour la suite

Questions a trancher progressivement:

1. Les bassins selectionnes peuvent-ils se recouvrir, ou faut-il un inventaire
   non imbrique par defaut ?
2. Quelle distance minimale entre exutoires selon les objectifs de campagne et
   les classes de surface ?
3. Quelle resolution DEM par defaut pour `national_default` ?
4. Faut-il produire d'abord des sites non calibres partout, ou privilegier les
   sites avec observations ?
5. Quels flags sont bloquants pour la premiere campagne ?
6. Quelle source administrative utiliser pour les regions francaises ?
7. Est-ce que la typologie experte doit etre obligatoire ou optionnelle ?
8. Quelle est la taille maximale acceptable d'un catalogue de candidats ?
9. Faut-il inclure BD TOPAGE dans le rapport de qualite v1 ou attendre v2 ?
10. Comment nommer durablement les `site_id` pour rester stables si les criteres
    changent ?
11. Quel statut donner aux observations: bonus par defaut, stratification, ou
    critere bloquant pour certaines campagnes ?
12. Quelle nomenclature geologique minimale utiliser en France v1 pour comparer
    des regions tres differentes ?
13. Faut-il produire un export unique tres riche ou plusieurs tables specialisees
    liees par `site_id` ?
14. Quelle sortie doit etre consideree comme canonique pour la reprise:
    `selected_sites.geoparquet`, manifest, ou les deux ?
15. Combien de notions de region doivent etre exposees dans l'interface
    utilisateur sans la rendre confuse ?
16. Dans quels cas la surface doit-elle rester informative, devenir un score,
    devenir une strate, ou devenir une borne bloquante ?
17. Quels principes directeurs faut-il supporter en v1 au-dela de
    `observation_led` et `criteria_crossing` ?
18. Quelle definition operationnelle de station hydrometrique non influencee
    retenir pour une premiere campagne France ?
19. Quels deux contextes francais contrastes doivent etre utilises comme tests
    de non-specialisation, par exemple Bretagne et Auvergne-Rhone-Alpes ?
20. Quelle tolerance de surface choisir pour un profil `area_only`: plage stricte,
    score autour d'une cible, ou classes de surface ?

## 19. Recommandation de premier prototype

Prototype minimal utile, dans l'ordre:

1. prototype de consolidation depuis l'existant ;
2. prototype `criteria_crossing` DEM-only autonome ;
3. prototype `area_only` sur une region contrastee ;
4. prototype `observation_led` depuis stations hydrometriques.

### 19.1. Prototype de consolidation

Ce prototype doit etre fait en premier.

Entrees:

- `natural_regional_lab_sites.csv` ;
- `examples/projects/07_mesh_gallery/**/case.json` et `bundle/` ;
- `DEM_armorican_massif.tif` pour le fond de carte ;
- inventaires Boussinesq existants si disponibles.

Ce prototype utilise le Massif Armoricain parce que les donnees existent deja
dans le depot. Il ne doit pas introduire de logique specifique a ce massif. Les
champs de region, de criteres et de provenance doivent rester utilisables pour
une autre region francaise.

Sorties:

- `site_selection_manifest.json` ;
- `selected_sites.csv` ;
- `regional_lab_sites.csv` ;
- `criteria_components.parquet` minimal ;
- `data_layers_summary.json` minimal ;
- `review/index.html` ;
- `review/map_selection.png` ;
- `review/selected_site_emprises.geojson`.

Critere de succes:

- on peut reconstruire la page de choix des sites sans script Boussinesq
  specifique ;
- on peut exporter un catalogue relisible par `regional_lab` ;
- on peut faire une revue humaine par selection, par exemple `headwater 10 km2` ;
- on voit explicitement quelles geometries viennent d'un bundle existant et non
  d'une delimitation DEM-only.

### 19.2. Prototype `criteria_crossing` DEM-only

Prototype minimal utile ensuite:

- territoire: `polygon_file` ou `bbox` ;
- DEM: `custom` d'abord, puis `ign_bdalti` ;
- methode: DEM-only ;
- reseau: methode existante `threshold_area_km2` ;
- surface: calculee et rapportee, avec preference optionnelle `100 km2` en mode
  `score` seulement ;
- candidats: echantillonnage de reseau, classes de surface optionnelles, ou
  points importes ;
- thinning simple ;
- criteres: couverture DEM, geometrie valide, espacement, surface optionnelle ;
- export `selected_sites.csv` et `regional_lab_sites.csv` ;
- rapport Markdown et HTML.

### 19.3. Prototype `area_only`

Prototype minimal utile pour verifier le cas "surface comme unique critere":

- territoire: une region francaise differente du premier cas de consolidation,
  par exemple `Auvergne-Rhone-Alpes` ;
- observations et geologie: calculees mais forcees en `report_only` ;
- candidats: echantillonnage de reseau DEM-only ;
- surface: borne dure ou classe de surface declaree explicitement, par exemple
  `75-125 km2` autour d'une cible `100 km2` ;
- recouvrement: `hard_reject`, pour obtenir un catalogue non redondant ;
- exports: `selected_sites.geoparquet`, `criteria_components.parquet`,
  `data_layers_summary.json`, `regional_lab_sites.csv`, rapport Markdown et
  HTML.

Ce prototype doit prouver que le moteur ne rend pas implicitement obligatoires
les stations, la geologie ou une region particuliere.

### 19.4. Prototype `observation_led`

Prototype minimal utile pour les bassins observes:

- territoire: une region francaise pilote, par exemple `Bretagne` ;
- observations: stations Hub'Eau hydrometrie ;
- candidats: exutoires issus des stations ;
- delimitation: bassin amont DEM-only depuis la station ;
- premier filtre: station disponible, chronique minimale, coherence
  station/bassin ;
- second filtre: non-influence majeure par barrage, prelevement ou regulation ;
- criteres suivants: surface en `report` ou `score`, geologie en `stratify`,
  equilibre spatial ;
- exports: `selected_sites.geoparquet`, `observation_evidence.parquet`,
  `criteria_components.parquet`, `regional_lab_sites.csv`, rapport Markdown et
  HTML.

Ce prototype doit montrer que l'ordre des criteres change selon le principe:
station et non-influence d'abord, surface et geologie ensuite.

Ces prototypes permettent de valider le coeur sans attendre toutes les couches
optionnelles:

- geologie ;
- SIM2 ;
- occupation du sol ;
- BDLISA ;
- prelevements ;
- BD TOPAGE.

Ensuite seulement on ajoute les signatures physiques et la typologie experte
complete. Les observations hydrometriques peuvent etre centrales dans
`observation_led`, mais rester `report_only` ou `score` dans
`criteria_crossing`.

## 20. Conclusion

L'outil de selection de sites doit devenir la brique amont des campagnes
HydroModPy. Son role est de transformer un territoire et des criteres explicites
en un catalogue de bassins auditable.

Il doit donc etre traite comme un workflow autonome, mais uniquement pour la
production d'artefacts de selection. Il ne remplace pas `regional_lab`, il le
prepare.

La bonne separation est:

```text
site_selection = choisir et documenter les sites
regional_lab = croiser sites et recettes
testbed = executer et collecter
comparison = comparer des sorties
calibration = ajuster des parametres
```

Cette separation garde le systeme evolutif. Elle permet aussi de traiter la
selection de sites comme un resultat scientifique a part entiere, avec ses
donnees, ses hypotheses, ses criteres, ses versions et ses limites.

Le coeur du plan est donc double:

- produire des bassins documentes par une methode DEM-only reproductible ;
- produire une decision explicable, extensible et revisable ;
- rendre explicite le principe directeur de selection avant de discuter les
  criteres secondaires.

Les criteres de choix doivent rester ouverts. La presence d'une station de debit,
d'un suivi piezometrique, d'une classe geologique rare ou d'une region physique
particuliere peut aider a selectionner un site. Mais ces informations doivent
etre explicites dans les evidences et configurees comme criteres de campagne, pas
enfouies dans un script local.

Si le principe est `observation_led`, les stations et leur non-influence sont au
coeur de la selection. Si le principe est `criteria_crossing`, les stations ne
sont qu'un critere parmi d'autres. Cette distinction doit apparaitre dans la
configuration, les sorties et le rapport.

La premiere implementation doit rassembler les pieces deja presentes: catalogues
regional-lab, mesh gallery, primitives de catalogues, inventaires de campagnes
et renderer HTML. L'algorithme DEM-only complet viendra ensuite dans la meme
structure, sans casser les artefacts de revue deja utilisables.
