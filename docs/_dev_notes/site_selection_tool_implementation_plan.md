# Plan d'implementation - outil de selection de sites HydroModPy

Date: 2026-05-12

Statut: document de conception et de planification. Ce fichier detaille une
brique specifique: un outil independant de selection de sites, place en amont
des testbeds, regional labs, comparaisons et campagnes de calibration.

Document parent: `docs/_dev_notes/national_headwater_deployment_audit.md`.

Document voisin a ne pas fusionner ici:
`docs/_dev_notes/calibration_network_transient_audit.md`.

## 1. Synthese

L'idee centrale est de creer un outil HydroModPy autonome de selection de sites.
Il ne lance pas de simulations. Il fabrique un catalogue robuste de bassins
candidats, avec leurs attributs, leurs diagnostics de qualite et leurs raisons
de selection ou de rejet.

Le flux cible:

```text
territoire cible
+ DEM generique
+ surface cible
+ tolerance de surface
+ criteres de qualite
+ criteres de stratification
= catalogue de sites candidats
```

Ce catalogue devient ensuite l'entree naturelle de `regional_lab` et du
`testbed`.

Decisions deja retenues dans la discussion:

- l'outil doit etre independant ;
- la methode de reference est `DEM-only` ;
- BD TOPAGE ne pilote pas la selection, elle peut servir de controle externe ;
- la surface cible est un parametre fondamental ;
- la selection se fait autour de la surface cible, pas sous un plafond strict ;
- tolerance initiale: `+/- 25%` ;
- exemple de cible: `100 km2`, donc intervalle `75-125 km2` ;
- le DEM doit rester generique et pas trop couteux ;
- le comportement donnees souhaite est: utiliser le cache si disponible, sinon
  telecharger automatiquement ;
- la generation du reseau doit d'abord reprendre la methode deja presente dans
  HydroModPy: DEM corrige, D8 direction/accumulation, seuil d'aire contributive,
  Strahler optionnel.

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
- filtre les bassins autour d'une surface cible ;
- calcule des attributs par bassin ;
- applique des regles de qualite ;
- applique une selection ou une stratification ;
- exporte un catalogue de sites ;
- exporte un rapport de selection.

### 2.2. Ce que l'outil ne fait pas

L'outil ne doit pas:

- lancer MF6 ;
- lancer Boussinesq ;
- calibrer ;
- comparer des solveurs ;
- remplacer `regional_lab` ;
- remplacer `testbed` ;
- produire une analyse finale de resultats modeles ;
- coder en dur des hypotheses specifiques a la France dans le coeur.

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
hmp site-selection build config.toml
hmp site-selection report output/site_selection_manifest.json
hmp site-selection export-regional-lab output/selected_sites.geoparquet
```

`plan`:

- valide la configuration ;
- resout les sources ;
- estime les tuiles DEM necessaires ;
- liste les donnees qui seront lues ou telechargees ;
- ne telecharge rien, sauf option explicite.

`build`:

- execute la selection ;
- produit les catalogues et rapports.

`report`:

- regenere un rapport humain depuis les artefacts.

`export-regional-lab`:

- convertit la sortie en CSV compatible avec
  `hydromodpy.analysis.testbed.regional_lab`.

### 4.2. Configuration minimale

Exemple volontairement simple:

```toml
[site_selection]
selection_id = "france_100km2_dem_only_v1"
output_root = "outputs/site_selection/france_100km2_dem_only_v1"

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

[site_selection.area]
target_area_km2 = 100.0
tolerance_fraction = 0.25

[site_selection.output]
write_geoparquet = true
write_csv = true
write_regional_lab_csv = true
```

### 4.3. Configuration plus complete

```toml
[site_selection]
selection_id = "northwest_100km2_diverse_v1"
output_root = "outputs/site_selection/northwest_100km2_diverse_v1"
random_seed = 42

[site_selection.territory]
mode = "admin_regions"
country = "FR"
regions = ["Bretagne", "Normandie", "Pays de la Loire"]
clip_to_territory = true

[site_selection.dem]
source = "ign_bdalti"
resolution_m = 25
cache_policy = "use_cache_else_download"
frozen_manifest = ""
margin_km = 5.0
force_refresh = false

[site_selection.hydrology]
method = "dem_only"
flow_algorithm = "d8"
hydrologic_conditioning = "existing_default"
network_threshold_area_km2 = 1.0
compute_strahler = true

[site_selection.outlets]
candidate_mode = "accumulation_area_window"
min_distance_between_outlets_km = 10.0
allow_nested_basins = false
snap_to_generated_stream = true

[site_selection.area]
target_area_km2 = 100.0
tolerance_fraction = 0.25

[site_selection.filters]
min_area_km2 = 75.0
max_area_km2 = 125.0
max_urban_fraction = 0.10
exclude_major_obstacles = true
exclude_major_withdrawals = false
require_dem_coverage = true

[site_selection.characterization]
enabled = true
ruleset = "expert_v1"
dimensions = ["relief", "climate", "geology", "drainage", "anthropization"]

[site_selection.stratification]
enabled = true
by = ["region_type", "admin_region"]
max_sites_per_class = 20
prefer_observed_sites = false

[site_selection.output]
write_candidates = true
write_rejected = true
write_selected = true
write_geoparquet = true
write_csv = true
write_regional_lab_csv = true
write_report_md = true
```

## 5. Architecture proposee

### 5.1. Emplacement code

Proposition de nouveau package:

```text
hydromodpy/
  analysis/
    site_selection/
      __init__.py
      config.py
      territory.py
      dem_context.py
      hydrology.py
      candidate_outlets.py
      delineation.py
      signatures.py
      expert_rules.py
      filters.py
      stratification.py
      exports.py
      reporting.py
      cli.py
      types.py
```

Raison du choix:

- `analysis` est coherent avec `testbed`, `comparison`, `regional_lab` ;
- l'outil prepare une analyse/campagne, il n'est pas une variable data simple ;
- il doit rester independant des solveurs.

Alternative:

```text
hydromodpy/spatial/site_selection/
```

Cette alternative est moins bonne si l'outil integre aussi donnees, typologie,
stratification et export regional_lab. Le spatial est central, mais pas suffisant
pour decrire toute la responsabilite.

### 5.2. Modules

`config.py`

- modeles Pydantic de configuration ;
- validation des valeurs ;
- normalisation des chemins ;
- conversion cible/tolerance en min/max.

`territory.py`

- resolution d'un territoire ;
- modes: `admin_regions`, `admin_departments`, `polygon_file`, `bbox`,
  `geoparquet_filter` ;
- union des geometries ;
- reprojection vers CRS de travail ;
- production d'une emprise avec marge.

`dem_context.py`

- demande de DEM pour l'emprise ;
- integration avec `hydromodpy.data.variables.dem.manager.DemManager` ;
- politique cache ;
- controle couverture ;
- reference au manifest de donnees.

`hydrology.py`

- appel aux produits hydrologiques existants ;
- DEM corrige ;
- D8 direction ;
- D8 accumulation ;
- reseau extrait par `threshold_area_km2` ;
- Strahler optionnel.

`candidate_outlets.py`

- detection des cellules candidates dont l'aire contributive est dans la
  fenetre cible ;
- filtrage sur le reseau genere ;
- thinning spatial ;
- suppression des doublons ;
- priorisation des candidats.

`delineation.py`

- delimitation de chaque bassin candidat ;
- calcul surface reelle ;
- rejet si hors tolerance ;
- detection des bassins vides ou incoherents.

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

`filters.py`

- filtres bloquants et filtres faibles ;
- raisons de rejet ;
- production de flags.

`stratification.py`

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

`reporting.py`

- rapport Markdown ;
- synthese par region administrative ;
- synthese par type expert ;
- synthese des rejets ;
- cartographie simple si dependances disponibles.

`cli.py`

- commandes utilisateur ;
- branchement avec le CLI `hmp`.

`types.py`

- dataclasses ou modeles serialisables.

## 6. Contrats de donnees

### 6.1. TerritorySpec

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

### 6.2. DemRequest

```text
source
resolution_m
bbox
margin_km
cache_policy
force_refresh
frozen_manifest
```

### 6.3. DemProduct

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

### 6.4. HydrologyProducts

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

### 6.5. CandidateOutlet

```text
candidate_id
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

### 6.6. DelineatedSite

```text
site_id
candidate_id
geometry
outlet_x
outlet_y
area_km2
target_area_km2
area_tolerance_fraction
area_error_fraction
enabled
site_status
selection_status
selection_reason
```

### 6.7. SiteSignature

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

### 6.8. ExpertRegion

```text
site_id
ruleset_id
relief_class
climate_class
geology_class
storage_class
drainage_class
anthropization_class
region_type
rule_evidence_json
```

### 6.9. SelectionDecision

```text
site_id
selected
decision_stage
decision_reason
blocking_flags
warning_flags
rank_score
stratification_class
```

## 7. Algorithme DEM-only

### 7.1. Principe

Le principe est de produire les exutoires candidats depuis le DEM lui-meme:

```text
DEM -> correction hydrologique -> D8 direction -> D8 accumulation
    -> reseau topographique -> candidats par aire contributive
    -> bassins -> filtre surface
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

### 7.3. Selection par surface cible

La surface cible ne doit pas etre confondue avec le seuil d'extraction du reseau.

Deux grandeurs differentes:

- `network_threshold_area_km2`: aire minimale pour considerer une cellule comme
  appartenant au reseau topographique ;
- `target_area_km2`: aire amont souhaitee pour un bassin candidat.

Exemple:

```text
network_threshold_area_km2 = 1.0
target_area_km2 = 100.0
tolerance_fraction = 0.25
```

Dans ce cas:

- le reseau est extrait des cellules ayant au moins environ `1 km2` amont ;
- les exutoires candidats sont des cellules du reseau dont l'aire amont est
  proche de `100 km2`, donc dans `[75, 125] km2`.

### 7.4. Probleme des doublons

Une riviere peut contenir beaucoup de cellules consecutives dont l'aire amont est
dans la fenetre `[75, 125] km2`. Si on garde tout, on obtient des bassins presque
identiques.

Il faut donc une strategie de thinning:

- grouper les cellules candidates connectees ;
- choisir un representant par segment ;
- imposer une distance minimale entre exutoires ;
- rejeter les bassins trop recouvrants ;
- optionnellement garder le candidat le plus proche de la surface cible.

Regle de depart proposee:

```text
candidate_score =
  abs(area_km2 - target_area_km2) / target_area_km2
  + overlap_penalty
  + distance_penalty
```

On selectionne les meilleurs candidats par classe/territoire.

### 7.5. Bassins imbriques

Question importante: autorise-t-on des bassins imbriques ?

Pour un inventaire national propre, il vaut mieux par defaut:

```text
allow_nested_basins = false
```

Mais il faut garder l'option:

```text
allow_nested_basins = true
```

Car pour une analyse de sensibilite ou une comparaison multi-echelle, les bassins
imbriques peuvent etre utiles.

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

### 10.2. Typologie experte v1

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

`region_type` peut etre compose:

```text
hilly_humid_crystalline_low_storage
lowland_intermediate_sedimentary_high_storage
mountain_humid_karstic_high_drainage
```

### 10.3. Regles exemple

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

### 10.4. Versionner les regles

Chaque typologie doit stocker:

```text
ruleset_id = "expert_v1"
ruleset_hash = "..."
region_type = "hilly_humid_crystalline_low_storage"
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
- utile pour typologie et priorisation.

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

### 12.1. Statuts

Proposition:

```text
candidate
rejected_area
rejected_duplicate
rejected_nested
rejected_dem_coverage
rejected_territory
rejected_quality
selected
selected_priority
selected_holdout
```

### 12.2. Flags bloquants

```text
DEM_MISSING
DEM_INCOMPLETE_COVERAGE
FLOW_ACCUMULATION_FAILED
OUTLET_OUTSIDE_TERRITORY
CATCHMENT_EMPTY
CATCHMENT_AREA_OUT_OF_RANGE
CATCHMENT_GEOMETRY_INVALID
DUPLICATE_CANDIDATE
NESTED_BASIN_REJECTED
```

### 12.3. Flags non bloquants

```text
LOW_RELIEF
FLAT_AREA
HIGH_URBAN_FRACTION
POSSIBLE_MAJOR_OBSTACLE
POSSIBLE_MAJOR_WITHDRAWAL
NO_OBSERVATION_NEARBY
BDTOPAGE_MISMATCH
GEOLOGY_MISSING
RECHARGE_MISSING
```

### 12.4. Score de selection

Le score ne doit pas remplacer les flags, mais aider a trier:

```text
score =
  area_score
+ spacing_score
+ data_quality_score
+ diversity_score
+ observation_bonus
- warning_penalty
```

Pour garder la selection explicable, chaque composante doit etre exportee.

## 13. Sorties

### 13.1. Repertoire de sortie

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
  expert_regions.parquet
  selection_decisions.parquet
  selection_report.md
  selection_summary.json
```

### 13.2. `regional_lab_sites.csv`

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
site_status
maturity
x
y
area_km2
tags
enabled
```

Colonnes supplementaires utiles:

```text
target_area_km2
area_tolerance_fraction
area_error_fraction
outlet_x
outlet_y
outlet_crs
territory_id
admin_region
region_type
relief_class
climate_class
geology_class
drainage_class
anthropization_class
selection_reason
blocking_flags
warning_flags
dem_source
dem_resolution_m
source_selection_manifest
```

### 13.3. Manifest

Le manifest doit repondre aux questions:

- quelle configuration a ete utilisee ?
- quel territoire ?
- quel DEM ?
- quelles donnees ont ete telechargees ?
- quelles donnees venaient du cache ?
- quelle version de regles ?
- combien de candidats ?
- combien rejetes ?
- combien selectionnes ?
- pourquoi ?

## 14. Integration avec `regional_lab`

### 14.1. Frontiere actuelle

`regional_lab` sait deja:

- lire un catalogue CSV/JSONL ;
- mapper les colonnes ;
- filtrer par region, famille, tags, statut, maturite ;
- appliquer des recettes ;
- produire inventaire, plan et rapports.

Le nouvel outil doit donc produire un catalogue conforme.

### 14.2. Flux recommande

```text
hmp site-selection build site_selection.toml

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
- colonnes `cluster_family`, `cluster_scale`, `region_id`, `tags` ;
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

Si une campagne veut changer la surface cible, la tolerance, le territoire ou la
methode DEM-only, elle doit relancer `site_selection` et produire un nouveau
`source_selection_id`.

## 15. Plan d'implementation

### Milestone 0 - specification

Objectif:

- figer le contrat de config et de sortie.

Taches:

- creer ce document ;
- definir les modeles Pydantic ;
- definir les artefacts attendus ;
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

- identifier les points dont l'aire amont est proche de la cible.

Taches:

- convertir accumulation en aire km2 ;
- appliquer fenetre `[target*(1-tol), target*(1+tol)]` ;
- contraindre aux cellules de reseau ;
- grouper/thinner les candidats ;
- calculer score aire ;
- exporter `candidate_outlets.parquet`.

Livrable:

- liste de candidats avec aire amont.

### Milestone 5 - delimitation et filtrage

Objectif:

- transformer les candidats en bassins.

Taches:

- reutiliser la delimitation depuis point ;
- calculer surface polygonale ;
- rejeter hors tolerance ;
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
- evidence JSON.

Livrable:

- `site_signatures.parquet` ;
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
- quotas par region_type.

Livrable:

- `selected_sites.geoparquet` ;
- `selected_sites.csv`.

### Milestone 8 - export regional_lab

Objectif:

- brancher directement sur les campagnes.

Taches:

- mapping colonnes ;
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
- sites par region_type ;
- top warnings ;
- liens vers artefacts.

Livrable:

- `selection_report.md` ;
- eventuellement HTML plus tard.

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
- conversion surface/tolerance ;
- selection par fenetre d'aire ;
- thinning de candidats ;
- rejection reasons ;
- typologie experte ;
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

- toutes les cellules d'un troncon peuvent entrer dans la fenetre de surface.

Mitigation:

- regroupement par segments ;
- distance minimale ;
- rejet bassins tres recouvrants ;
- score proche cible.

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

### 17.5. Reproductibilite

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
2. Quelle distance minimale entre exutoires pour une cible de `100 km2` ?
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

## 19. Recommandation de premier prototype

Prototype minimal utile:

- territoire: `polygon_file` ou `bbox` ;
- DEM: `custom` d'abord, puis `ign_bdalti` ;
- methode: DEM-only ;
- reseau: methode existante `threshold_area_km2` ;
- surface cible: `100 km2` ;
- tolerance: `0.25` ;
- candidats: fenetre d'accumulation ;
- thinning simple ;
- export `selected_sites.csv` et `regional_lab_sites.csv` ;
- rapport Markdown.

Ce prototype permettrait de valider le coeur sans attendre:

- geologie ;
- SIM2 ;
- occupation du sol ;
- BDLISA ;
- prelevements ;
- BD TOPAGE.

Ensuite seulement on ajoute les signatures physiques et la typologie experte.

## 20. Conclusion

L'outil de selection de sites doit devenir la brique amont des campagnes
HydroModPy. Son role est de transformer un territoire et des criteres explicites
en un catalogue de bassins auditable.

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
donnees, ses hypotheses, ses versions et ses limites.
