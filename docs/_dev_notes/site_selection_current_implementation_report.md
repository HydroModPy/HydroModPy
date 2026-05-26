# Rapport d'implementation actuel - `site_selection`

Date: 2026-05-25

Ce document decrit l'etat actuel du developpement `site_selection`. Il complete
le plan long `site_selection_tool_implementation_plan.md`, qui reste un document
de strategie et de jalons.

## Synthese au 2026-05-25

### En clair

`site_selection` sert a preparer une campagne de modelisation: il propose des
sites possibles, calcule le bassin versant associe a chaque site, applique des
criteres simples, puis produit un dossier de controle avec cartes, tableaux et
fichiers SIG.

Le workflow est aujourd'hui utilisable pour les cas pilotes ou les exutoires
sont deja connus, par exemple des stations hydrometriques Hub'Eau ou un CSV de
sites. Dans ce cas, le code sait:

- lire les points de station ou les points d'exutoire fournis;
- replacer ces points sur le reseau DEM, ou d'abord sur BD Topage puis sur le
  DEM;
- delimiter les bassins versants depuis ces exutoires;
- garder ou rejeter les sites selon les criteres configures;
- produire un rapport HTML et des fichiers GeoJSON/GPKG/GeoParquet de controle.

Le workflow commence aussi a fonctionner sans station en entree. Dans ce mode,
HydroModPy regarde directement le DEM et propose lui-meme des exutoires
candidats. Cette partie existe, mais elle est encore exploratoire: elle sert
d'abord a verifier les sorties et les audits, pas encore a produire une bonne
selection regionale.

### Ce qui marche bien aujourd'hui

Le cas le plus fiable est le cas avec stations hydrometriques. Le rapport a
regarder en priorite est:

```text
examples/projects/17_site_selection_workflow/outputs/bretagne_hydrometry_50_500_small_bdtopage_rerun_v1/review/index.html
```

Dans ce rapport Bretagne compact:

- 7 stations sont traitees;
- les stations sont projetees sur BD Topage avec une distance tres courte
  entre la station et le reseau, environ 1.5 a 9 m;
- le snap final sur le DEM reste court, environ 64 a 105 m;
- les 7 sites sont selectionnes;
- le rapport permet de verifier visuellement la relation entre station,
  exutoire retenu et contour de bassin.

Ce cas montre le chemin attendu pour une selection pilotee par observations:

```text
station hydrometrique -> exutoire corrige -> bassin versant -> criteres -> rapport
```

### Ce que montre le dernier run DEM automatique

Le rapport suivant est different:

```text
examples/projects/17_site_selection_workflow/outputs/bretagne_generated_candidates_dem_v1/review/index.html
```

Ici, il n'y a pas de stations hydrometriques en entree. Le code essaie de creer
des exutoires tout seul a partir du DEM. Le rapport doit donc etre lu comme un
test de mecanique, pas comme un resultat metier.

Ce que ce rapport doit montrer:

- un fond DEM;
- un reseau calcule depuis le DEM;
- des exutoires candidats choisis automatiquement;
- les bassins delimites depuis ces exutoires;
- un tableau d'audit expliquant quels candidats ont ete gardes ou ignores;
- des liens vers les fichiers produits:
  `candidate_generation.jsonl`, `candidate_outlets.geojson`,
  `generated_dem_network.geojson`, les bassins GeoJSON et le manifest.

Le graphe parait mauvais parce que la methode automatique actuelle choisit les
cellules avec la plus forte accumulation d'eau. A l'echelle d'une region, ces
cellules sont generalement sur les grands cours d'eau tres aval. Le resultat
est donc logique pour l'algorithme, mais peu utile pour la selection souhaitee:
les bassins deviennent beaucoup trop grands et proches les uns des autres.

Dans le run Bretagne automatique actuel:

- 12 candidats sont generes;
- 12 bassins sont delimites;
- les 12 bassins sont selectionnes techniquement;
- mais ils font environ 3488 a 3779 km2, alors que la plage de controle etait
  50-500 km2;
- les 12 sites portent donc un avertissement de surface;
- le reseau BD Topage reutilise ne couvre pas bien ces candidats: le premier
  candidat est a environ 20 km du reseau de reference charge.

Conclusion: ce rapport prouve que les fichiers sortent, que le HTML fonctionne
et que l'audit existe. Il ne prouve pas encore que la generation automatique
choisit de bons sites.

Un exemple plus court a ete ajoute pour tester ce chemin sans lancer une region
complete:

```text
examples/projects/17_site_selection_workflow/configs/calvados_dem_area_light_100km2_fast.toml
```

Il limite le domaine au Calvados, demande seulement 10 bassins autour de 100 km2
et plafonne a 30 le nombre de candidats DEM a delimiter avant le tri final.
Pour les territoires administratifs francais, la generation de candidats DEM et
l'export du reseau DEM sont maintenant limites a la geometrie terrestre
effective du territoire, afin d'eviter les artefacts sur les cellules marines
presentes dans l'emprise raster.
La page HTML attendue est:

```text
examples/projects/17_site_selection_workflow/outputs/calvados_dem_area_light_100km2_fast_v1/review/index.html
```

Ce cas doit tourner plus vite que `normandie_dem_area_light_100km2.toml`.
Il sert a verifier la mecanique DEM automatique sur un departement; il ne doit
pas encore etre lu comme une selection metier definitive.

### Sorties disponibles

Pour chaque run complet, le dossier de sortie contient les fichiers de base:

- `site_selection_manifest.json`: resume officiel du run, des entrees et des
  sorties;
- `selected_sites.csv`: sites retenus;
- `rejected_sites.csv`: sites rejetes;
- `selection_decisions.jsonl`: raison de chaque decision;
- `criteria_components.jsonl`: details des criteres appliques;
- `review/index.html`: rapport de controle;
- `review/site_selection_map.png`: carte PNG integree au rapport.

Quand les sorties spatiales sont activees, on obtient aussi:

- `selected_outlets.geojson` et `rejected_outlets.geojson`: points d'exutoire;
- `selected_basins.geojson` et `rejected_basins.geojson`: contours de bassins;
- `site_selection.gpkg`: couches SIG rassemblees dans un GeoPackage;
- des fichiers GeoParquet separes pour les bassins, exutoires et observations.

En mode DEM automatique, trois fichiers supplementaires aident a comprendre ce
que le code a fait:

- `candidate_generation.jsonl`: liste des candidats acceptes ou ignores, avec
  la raison;
- `candidate_outlets.geojson`: points candidats envoyes a la delimitation;
- `generated_dem_network.geojson`: reseau extrait du DEM et affiche dans la
  carte.

### Ce qui a ete developpe

Les briques principales sont en place:

- orchestration `hmp run` pour lancer un workflow `site_selection`;
- lecture de configurations TOML dediees;
- chargement de donnees hydrometriques et DEM via les gestionnaires de donnees
  existants;
- creation d'exutoires candidats depuis stations, CSV ou DEM;
- snap court sur accumulation DEM;
- option BD Topage/custom pour rapprocher une station du reseau hydrographique
  avant le snap DEM;
- delimitation de bassin versant depuis un exutoire;
- criteres de surface, distance station-exutoire, influence, geologie et
  piezometrie;
- rapports HTML communs avec carte statique;
- exports CSV, JSONL, GeoJSON, GPKG et GeoParquet;
- audit des candidats DEM ignores et scoring par distance a un reseau de
  reference quand il est disponible.

### Ce qui reste a ameliorer

La priorite est de rendre la generation automatique de candidats plus
hydrologique. Au lieu de prendre simplement les cellules avec la plus forte
accumulation, il faut proposer des points qui correspondent mieux a une campagne
de selection:

- choisir des exutoires proches d'une surface cible, par exemple 50-500 km2;
- eviter que tous les candidats soient sur le meme grand troncon aval;
- generer des candidats par sous-bassins;
- utiliser les confluences et l'ordre du reseau;
- utiliser un reseau BD Topage complet comme aide a la localisation, pas
  seulement comme score de distance;
- mieux expliquer dans le rapport pourquoi un candidat est propose ou rejete.

Details des travaux a mener:

- Choisir des exutoires proches d'une surface cible, par exemple 50-500 km2.
  Aujourd'hui, le mode automatique choisit surtout les plus fortes
  accumulations. Cela donne des bassins tres grands, car les plus fortes
  accumulations sont souvent tres aval. Le bon comportement serait de chercher
  des cellules du reseau dont la surface amont calculee est proche de la plage
  demandee. Pour une campagne 50-500 km2, un point donnant 120 km2 devrait etre
  mieux classe qu'un point donnant 3700 km2, meme si ce dernier a une
  accumulation plus forte.

- Eviter que tous les candidats soient sur le meme grand troncon aval.
  L'espacement actuel evite deux points trop proches, mais il ne comprend pas la
  structure hydrographique. Deux points distants de plusieurs kilometres peuvent
  rester sur le meme cours d'eau aval et produire des bassins tres emboites. Il
  faut donc detecter quand plusieurs candidats appartiennent au meme axe
  principal et limiter leur nombre, ou bien garder seulement le meilleur
  candidat par troncon.

- Generer des candidats par sous-bassins.
  Une selection regionale doit couvrir plusieurs secteurs hydrologiques, pas
  seulement la partie aval du plus grand bassin. L'idee est de decouper le
  territoire en sous-domaines hydrologiques, puis de chercher des candidats dans
  chacun d'eux. Cela permettrait d'obtenir une carte plus repartie: plusieurs
  bassins de taille comparable, situes dans des secteurs differents.

- Utiliser les confluences et l'ordre du reseau.
  Les confluences sont des endroits ou deux branches du reseau se rejoignent.
  Elles sont souvent de bons points candidats, car elles definissent des bassins
  amont bien interpretable. L'ordre du reseau, par exemple Strahler, donne une
  indication de taille et d'importance des cours d'eau. Utiliser ces deux
  informations permettrait d'eviter les cellules isolees ou arbitraires et de
  proposer des exutoires situes sur des points hydrologiquement significatifs.

- Utiliser un reseau BD Topage complet comme aide a la localisation, pas
  seulement comme score de distance.
  Dans le dernier run, BD Topage est seulement utilise pour dire si un candidat
  DEM est loin ou proche du reseau de reference. Ce n'est pas suffisant. Une
  meilleure approche serait de chercher les candidats directement sur BD Topage,
  puis de les projeter localement sur le DEM pour delimiter le bassin. BD Topage
  servirait alors de squelette hydrographique officiel, et le DEM servirait a
  calculer le bassin versant. Cela devrait reduire les candidats mal places et
  rendre la logique carte/reseau/exutoire plus lisible.

- Mieux expliquer dans le rapport pourquoi un candidat est propose ou rejete.
  Le fichier `candidate_generation.jsonl` contient deja des raisons techniques,
  mais le HTML doit les rendre comprehensibles. Pour chaque candidat important,
  le rapport devrait dire par exemple: surface amont estimee, distance au
  candidat retenu le plus proche, distance a BD Topage, raison du rejet ou du
  classement, et eventuellement "meme troncon qu'un meilleur candidat". Le but
  est de pouvoir lire la carte et comprendre la decision sans ouvrir les JSONL.

Les autres points a consolider ensuite sont:

- brancher des sources regionales reelles d'influences anthropiques;
- brancher des sources BRGM/BSS ou regionales pour geologie et piezometrie;
- stabiliser les schemas finaux des couches d'evidence;
- faire une carte interactive une fois les sorties spatiales stabilisees.

## Positionnement

`site_selection` est maintenant structure comme un workflow amont. Son role est
de produire un catalogue de bassins candidats, les decisions de selection/rejet
et les evidences associees. Il ne lance pas de simulation, ne cree pas de cas
`site x recipe`, et ne remplace pas `regional_lab`.

La separation actuelle est:

```text
hydromodpy.spatial.site_selection = primitives spatiales, criteres, exports, manifest
hydromodpy.workflow.site_selection = orchestration workflow et chargement config
hydromodpy.workflow.site_selection_data = adaptateur vers les gestionnaires de donnees
hydromodpy.cli.commands.site_selection = commandes utilisateur
```

## Modules principaux

### `hydromodpy/spatial/site_selection`

- `config.py`: modeles Pydantic pour strategie, territoire, criteres, sorties.
  Il inclut aussi `map_context.layers`, optionnel, pour les couches de contexte
  des cartes de revue.
- `candidate_outlets.py`: representation, reprojection et espacement des
  exutoires candidats.
- `candidate_generation.py`: generation deterministe de premiers candidats
  depuis le raster d'accumulation DEM et exports d'audit associes.
- `flow_products_adapter.py`: adaptation vers les produits hydrologiques DEM
  existants.
- `delineation.py`: adaptation vers la delimitation existante par point.
- `reference_network.py`: projection optionnelle des exutoires sur un reseau
  hydrographique de reference avant le snap DEM local.
- `criteria.py`: composants auditables de criteres pour surface, observation,
  influence anthropique et geologie.
- `selection.py`: decisions retenu/rejete et traces de score/flags.
- `schemas.py`: schemas de colonnes et construction des lignes de sortie.
- `exports_tabular.py`: ecriture CSV et JSONL.
- `exports_geojson.py`: ecriture GeoJSON d'exutoires, contours de bassins et
  points d'observation.
- `exports.py`: facade publique des exports utilisee par le workflow.
- `manifest.py`: construction, lecture/ecriture et validation du manifest
  officiel.
- `artifacts.py`: assemblage manifest + rapport optionnel.
- `figures.py`: carte statique de revue depuis les artefacts declares dans le
  manifest.
- `html_report.py`: rapport HTML v0 depuis le manifest.
- `plan_report.py`: rapport HTML v0 pour les runs `plan_only`.
- `build.py`: chaine observation-led depuis des `PointRecord` deja charges.
- `README.md`: limites du package et contrat des sorties.

### `hydromodpy/workflow`

- `site_selection.py`: planification, selection depuis CSV de bassins,
  selection depuis hydrometrie, resolution du DEM via `[data.dem]` avec emprise
  par exutoires quand `request_extent = "outlets"`, et dispatch interne.
- `site_selection_data.py`: chargement hydrometrique via le data manager
  existant et resolution du DEM via `[data.dem]`. Le code ne duplique pas
  Hub'Eau ni les clients DEM.

### `hydromodpy/data`

- `data.common.administrative.france`: resolution locale des departements et
  emprises EPSG:2154 a partir de regions administratives francaises.
- `data.variables.dem.apis.ign_bdalti`: telechargement IGN BD ALTI 25 m avec
  `User-Agent` explicite et extraction dans un cache court (`D022`, `D035`,
  etc.) pour eviter les limites de longueur de chemin sous Windows. La source
  peut aussi declarer explicitement les departements IGN a charger, afin
  d'eviter l'overfetch provoque par une bbox regionale large.

### CLI

Commandes disponibles:

```bash
hmp site-selection plan CONFIG
hmp site-selection plan CONFIG --write-manifest --write-report
hmp site-selection select-catchments CONFIG CATCHMENTS_CSV
hmp site-selection build-observed CONFIG
hmp site-selection build-generated CONFIG
hmp site-selection report SITE_SELECTION_MANIFEST
hmp run CONFIG
```

`hmp run` accepte maintenant:

```toml
[workflow]
mode = "site_selection"
```

## Sorties actuelles

Une execution de selection ecrit toujours le coeur d'audit:

- `selection_decisions.jsonl`
- `criteria_components.jsonl`
- `site_selection_manifest.json`

Avec la sortie GeoJSON active par defaut, elle ecrit aussi:

- `selected_outlets.geojson`
- `rejected_outlets.geojson`
- `selected_basins.geojson`
- `rejected_basins.geojson`

Avec les sorties CSV actives, elle ecrit aussi:

- `selected_sites.csv`
- `rejected_sites.csv`
- `regional_lab_sites.csv`

Le rapport HTML n'est pas force. Il est produit seulement si:

```toml
[site_selection.output]
write_report_html = true
```

ou via la commande explicite:

```bash
hmp site-selection report outputs/.../site_selection_manifest.json
```

Quand le rapport HTML est produit, il ecrit aussi:

- `review/site_selection_map.png`

En mode `plan_only`, le workflow peut maintenant produire:

- `site_selection_plan.json`
- `review/index.html`

Ce HTML est un rapport de plan. Il ne contient pas de sites retenus/rejetes et
sert a relire la strategie, le territoire, les donnees necessaires et les
sorties prevues avant de lancer une vraie selection.

En mode `generated_candidates`, le workflow peut maintenant produire des sites
sans CSV de bassins et sans stations hydrometriques:

```toml
[site_selection.input]
mode = "generated_candidates"

[site_selection.outlets]
candidate_mode = "network_sampling"
max_generated_candidates = 50
min_distance_between_outlets_km = 2.0
```

Le workflow resout le DEM, construit les produits de flux, echantillonne les
cellules de forte accumulation, espace les candidats, puis reutilise la meme
chaine de delimitation et de selection que les autres modes. Les artefacts
specifiques sont:

- `candidate_generation.jsonl`: audit par cellule candidate, avec `status`,
  `rejection_reason`, accumulation, rang, distance au candidat deja retenu le
  plus proche et, quand un reseau de reference est charge, distance/score au
  reseau;
- `candidate_outlets.geojson`: exutoires candidats effectivement envoyes a la
  delimitation;
- `generated_dem_network.geojson`: reseau DEM vectorise a partir du raster
  d'accumulation, limite par `max_generated_network_cells`.

Quand `snap_strategy = "bdtopage_then_dem"` et qu'un reseau BD Topage/custom est
disponible, les candidats generes sont aussi scores par distance a ce reseau
avant la delimitation. Les attributs `reference_network_distance_m`,
`reference_network_score` et `reference_network_status` sont recopies dans
`candidate_generation.jsonl` et les GeoJSON d'exutoires.

Un exemple Bretagne a ete ajoute:

- config:
  `examples/projects/17_site_selection_workflow/configs/bretagne_generated_candidates_dem.toml`;
- sortie HTML inspectable:
  `examples/projects/17_site_selection_workflow/outputs/bretagne_generated_candidates_dem_v1/review/index.html`;
- sortie reseau DEM:
  `examples/projects/17_site_selection_workflow/outputs/bretagne_generated_candidates_dem_v1/generated_dem_network.geojson`.

Ce run utilise un DEM BD ALTI local, genere 12 candidats, les delimite et les
selectionne. Le reseau BD Topage local disponible est utilise en scoring
(`reference_network_distance_m`), mais pas en snap obligatoire, afin que le
rapport reste inspectable meme quand le GPKG de reference ne couvre pas tous les
candidats generes.

Les sorties de production peuvent maintenant etre activees explicitement:

- `site_selection.output.write_geopackage = true` ecrit
  `site_selection.gpkg` avec les couches `selected_outlets`,
  `rejected_outlets`, `selected_basins`, `rejected_basins` quand elles ne sont
  pas vides;
- `site_selection.output.write_geoparquet = true` ecrit les couches
  GeoParquet separees `selected_outlets.parquet`, `rejected_outlets.parquet`,
  `selected_basins.parquet`, `rejected_basins.parquet`, et
  `observation_points.parquet` quand des points d'observation geolocalises
  existent.

Ces sorties restent desactivees par defaut dans les exemples courts pour ne pas
alourdir les runs de revue. Le catalogue de candidats et le rapport Markdown
restent des jalons futurs.

Les evidences d'influence peuvent maintenant etre calculees depuis des couches
vectorielles:

```toml
[[site_selection.criteria.influence.layers]]
name = "Barrages"
path = "data/influence/barrages.gpkg"
influence_type = "major_dam_upstream"
id_field = "id"
label_field = "name"
severity_field = "severity"
major_values = ["major"]
```

Chaque couche est lue par le workflow, reprojetee dans le CRS des exutoires,
puis intersectee avec le contour de bassin quand il existe. En absence de
contour, `influence_search_radius_km` peut servir de rayon autour de l'exutoire.
Les matches sont ecrits dans `influence_evidence.jsonl`,
`influence_features.geojson`, `influence_features.parquet` et/ou la couche
`influence_features` de `site_selection.gpkg` selon les sorties activees.

Les evidences de geologie peuvent maintenant etre calculees depuis des couches
polygonales:

```toml
[[site_selection.criteria.geology.layers]]
name = "Geologie BRGM"
path = "data/geology/geology.gpkg"
class_field = "lithology"
id_field = "id"
label_field = "label"
```

Le workflow intersecte chaque contour de bassin avec la couche, calcule les
fractions de surface par classe, renseigne `geology_class`,
`dominant_geology`, `geology_area_fraction` et `geology_diversity_count`, puis
ecrit `geology_evidence.jsonl`. Avec les sorties spatiales actives, il ecrit
aussi `geology_basins.geojson`, `geology_basins.parquet` et/ou la couche
`geology_basins` de `site_selection.gpkg`.

Les evidences de piezometrie peuvent maintenant etre calculees depuis des
couches de points:

```toml
[[site_selection.criteria.observations.piezometer_layers]]
name = "Piezometres BSS"
path = "data/piezometry/piezometers.gpkg"
id_field = "bss_id"
label_field = "name"
record_years_field = "record_years"
quality_field = "quality"
```

Les points situes dans le bassin, ou dans le rayon
`piezometer_max_distance_km` autour de l'exutoire quand il est configure, sont
convertis en evidences `ObservationEvidence`. Le workflow renseigne
`piezometer_count`, `piezometers_in_basin`,
`nearest_piezometer_distance_km` et ecrit `piezometer_evidence.jsonl` en plus
de `observation_evidence.jsonl` et `observation_points.geojson`.

Les GeoJSON d'exutoires sont des points. Quand `outlet_snap_shp` existe, la
geometrie de `selected_outlets.geojson` est le point snappe; les proprietes
gardent aussi `outlet_original_x`, `outlet_original_y`,
`x_outlet_snapped`, `y_outlet_snapped` et `outlet_snap_distance_m`. Quand il
n'y a pas de snap disponible, la geometrie reste le point candidat original.
Les GeoJSON de bassins contiennent les contours quand `watershed_shp` existe et
peut etre lu. Si un contour est absent, le fichier reste ecrit et le bassin est
liste dans `hydromodpy_skipped_basins`.

Quand `site_selection.input.delineate_from_outlets = true`, les contours peuvent
etre recalcules depuis les exutoires. Le DEM n'est alors pas une responsabilite
de `site_selection`: il est soit fourni par `site_selection.dem.path` pour les
cas simples, soit declare proprement sous `[data.dem]` et charge/cache par les
gestionnaires de donnees. Le manifest conserve le chemin du DEM effectivement
utilise dans `flow_products.dem_path`.

Le snap d'exutoire est maintenant configurable:

- `site_selection.outlets.snap_strategy = "dem_accumulation"` conserve le
  comportement direct: Whitebox cherche localement le meilleur point sur le
  raster d'accumulation DEM, dans le rayon `snap_dist_m`.
- `site_selection.outlets.snap_strategy = "bdtopage_then_dem"` projette d'abord
  la station sur BD Topage ou un reseau custom, avec une limite
  `reference_network_max_distance_m`, puis lance le snap DEM avec un rayon court
  autour de ce point de reference.

La deuxieme option ne remplace pas le MNT pour delimiter le bassin. Elle sert a
eviter qu'un rayon de snap trop large choisisse une cellule plus accumulatrice
plusieurs kilometres en aval de la station.

Quand `site_selection.input.mode = "hydrometry"`, le meme principe est
applique sans CSV de candidats: le workflow charge les stations via les
gestionnaires de donnees avant de resoudre le DEM. Si
`site_selection.dem.request_extent = "outlets"`, l'emprise DEM est construite
depuis les stations reprojetees, avec la marge `site_selection.dem.margin_km`;
sinon elle reste derivee du territoire. Le workflow construit ensuite les
produits hydrologiques, puis delimite les bassins depuis les stations. Pour la
France, l'emprise administrative est transformee en WGS84 pour les requetes
Hub'Eau, et les stations Hub'Eau sont converties en Lambert-93 avant
delimitation. Quand Hub'Eau fournit `x_l93` et `y_l93`, ces coordonnees
officielles sont utilisees directement.

Les builds pilotes par observation ecrivent aussi:

- `observation_evidence.jsonl`
- `observation_points.geojson`

Les points d'observation sont extraits des evidences normalisees. La carte peut
donc symboliser differemment les stations hydrometriques, les piezometres et les
autres types d'observation, sans lire directement les schemas bruts Hub'Eau.

Les CSV de bassins pre-delimites peuvent maintenant embarquer des colonnes
normalisees de stations (`flow_station_id`, `flow_station_x`,
`piezometer_id`, `piezometer_x`, etc.). Elles sont converties en
`observation_evidence.jsonl` et `observation_points.geojson`. Ce chemin sert aux
fixtures, catalogues et extraits figes; les appels a Hub'Eau restent portes par
les gestionnaires de donnees existants.

La carte statique peut aussi lire les couches optionnelles declarees dans:

```toml
[[site_selection.map_context.layers]]
name = "Hydrographie de contexte"
path = "..."
role = "hydrography"
```

Ces couches sont seulement un contexte visuel de revue. Les contours retenus
sont maintenant colores par classes de surface, avec un remplissage transparent
et des traits plus fins, pour que la carte reste lisible quand plusieurs bassins
sont compares sur la meme region. Les stations hydrometriques sont symbolisees
par de petits triangles bleus. Les exutoires retenus sont affiches au point
snappe quand il existe; un lien pointille station -> exutoire est trace quand le
deplacement depasse 250 m. Le cadrage privilegie les artefacts de selection si
le DEM regional est trop large ou ne recoupe pas les bassins, ce qui evite les
cartes vides ou les bassins minuscules au milieu d'un fond regional.

## Contrats stabilises

Le manifest officiel est maintenant validable:

- version de schema attendue: `site_selection_manifest_v1` ;
- presence des cles principales ;
- presence des artefacts d'audit obligatoires ;
- controle d'existence et de lisibilite des fichiers references dans `outputs`:
  JSON, JSONL, CSV, GeoJSON et PNG.
- carte PNG derivee des artefacts declares, avec contours, exutoires et points
  d'observation. Les contours de bassins retenus portent une symbologie par
  classes de surface.

`regional_lab_sites.csv` garde le schema historique attendu par les chargeurs de
catalogue:

```text
site_id, site_label, region_id, source_selection_id, site_status, maturity,
x, y, x_outlet, y_outlet, area_km2, tags, enabled
```

`selected_sites.csv` ajoute les champs de revue hydrologique issus du snap:

```text
x_outlet_snapped, y_outlet_snapped, outlet_snap_distance_m
```

Les champs `x`, `y`, `x_outlet` et `y_outlet` restent les coordonnees candidates
utilisees pour lancer la delimitation. Avec `bdtopage_then_dem`, ces
coordonnees peuvent etre le point projete sur le reseau de reference; les
proprietes GeoJSON conservent alors `reference_network_original_x/y` et
`reference_network_x/y`. Les GeoJSON et la carte utilisent l'exutoire snappe
quand il est disponible.

Pour les workflows pilotes par station hydrometrique, le critere
`flow_station.max_station_to_outlet_distance_km` est evalue sur la distance
entre la station et l'exutoire final affiche, c'est-a-dire l'exutoire snappe
quand la delimitation DEM en produit un. Les exemples station-led utilisent
maintenant `snap_dist_m = 150`, afin d'eviter les sauts kilometriques vers
l'aval. La contrainte de distance station -> exutoire reste auditee separement,
typiquement a 1 km dans les exemples Bretagne.

Les criteres auditables couvrent maintenant:

- `area`: surface en mode rejet dur, score, stratification, warning ou report ;
- `flow_station`: duree d'observation, distance station-exutoire finale,
  station dans ou a l'exutoire ;
- `piezometer`: presence/distance de suivi piezometrique, avec modes report,
  score, warning, stratification ou rejet dur ;
- `influence`: flags explicites de barrage, prelevement majeur ou troncon
  regule ;
- `geology`: evidence geologique disponible pour reporting, score simple ou
  stratification.

Une influence inconnue ne rejette pas automatiquement un bassin. Le rejet dur
est applique uniquement si une regle de rejet est configuree et si le flag
correspondant est explicitement present.

## Exemples maintenus

Dossier:

```text
examples/projects/17_site_selection_workflow
```

Cas fournis:

- `configs/bretagne_hydrometry_primary.toml`: principe `observation_led`, les
  stations hydrometriques sont l'entree principale. Le DEM est maintenant
  declare dans `[data.dem]` avec la source IGN `ign_bdalti`; l'exemple produit
  des contours recalcules depuis les exutoires.
- `configs/bretagne_hydrometry_50_500_hubeau_preview.toml`: principe
  `observation_led` applique a des stations Hub'Eau chargees directement par
  les gestionnaires de donnees HydroModPy. La plage 50-500 km2 est controlee
  apres recalcul DEM et reportee dans l'audit, sans script regional ni CSV
  intermediaire obligatoire.
- `configs/bretagne_hydrometry_50_500_small.toml`: meme principe, mais la
  source Hub'Eau est limitee a 7 stations explicites avec `station_ids` et
  `max_stations = 7`. Cette variante reduit le temps d'execution pour
  travailler la carte et le rapport HTML sans passer par une fixture CSV. Elle
  garde le snap direct
  `dem_accumulation` avec `snap_dist_m = 150`.
- `configs/bretagne_hydrometry_50_500_small_bdtopage.toml`: meme preview
  generique limitee a 7 stations, mais avec `snap_strategy =
  "bdtopage_then_dem"`. Le workflow telecharge ou reutilise une couche BD
  Topage dans `outputs/.../reference_network` puis reconcile localement chaque
  point avec le DEM.
- `configs/auvergne_rhone_alpes_area_only.toml`: principe `criteria_crossing`
  avec profil `area_only`, surface comme seul critere actif. La fixture
  courante contient 20 bassins entre 50 et 150 km2.
- `configs/auvergne_rhone_alpes_hydrometry_50_150.toml`: principe
  `observation_led` sans CSV de candidats. Les stations sont chargees depuis
  Hub'Eau sur l'emprise AURA, le DEM est resolu par `[data.dem]`, et la surface
  50-150 km2 est exprimee comme plage explicite de controle.

Le second exemple est executable localement sans telechargement grace a:

```text
fixtures/aura_area_50_150_catchments.csv
```

## Ce qui est volontairement limite

- Corrections courtes verrouillees:

  - les workflows lourds `hydrometry`, `generated_candidates` et
    `dem_area_light` emettent maintenant des messages de progression quand ils
    sont lances via `hmp run` ou via les sous-commandes `site-selection`. On
    voit explicitement le chargement des observations, la resolution du DEM, la
    construction des produits hydrologiques, puis le bilan candidats/retenus/
    rejetes;
  - en mode `hydrometry`, le message indique l'emprise DEM calculee depuis les
    stations quand `site_selection.dem.request_extent = "outlets"`;
  - les exports de bassins GeoJSON, GeoPackage et GeoParquet tentent maintenant
    de reparer les geometries invalides avant ecriture. Si Shapely ne peut pas
    reparer proprement, l'export reste robuste et ignore seulement les
    geometries vides.

- Le HTML v0 contient maintenant une carte statique de controle. Ce n'est pas
  encore une carte interactive riche.
- La carte est maintenant integree en base64 dans le HTML quand le PNG reste de
  taille raisonnable, tout en conservant le lien vers `site_selection_map.png`.
  Cela evite les previews HTML sans carte lorsque l'environnement d'affichage
  ne resout pas correctement les fichiers relatifs.
- Les runs avec vraie delimitation DEM peuvent etre longs meme sur un petit
  nombre de sites. Sur la Bretagne, 7 sites compacts restent executables pour
  iterer; 54 sites doivent etre consideres comme un run de production/cache.
- Les figures issues d'un DEM synthetique grossier ne sont pas un indicateur
  fiable de qualite hydrologique: elles peuvent produire des contours
  artificiels. Les figures de travail doivent utiliser un DEM reel ou un
  contour de bassin deja valide.
- Les controles d'influence peuvent etre calcules depuis des couches vecteur,
  mais les sources regionales reelles et leurs conventions de severite restent
  a stabiliser par campagne.
- La geologie peut etre croisee spatialement depuis une couche polygonale
  configuree, mais le branchement a une base BRGM/regionalisee et une
  typologie officielle de campagne restent a definir.
- La piezometrie peut etre croisee spatialement depuis une couche de points
  configuree, mais le chargement automatique des inventaires/chroniques via les
  gestionnaires de donnees reste a brancher.
- Le DEM-only sans CSV pre-delimite existe maintenant avec deux chemins:
  `generated_candidates` pour l'echantillonnage du reseau DEM et
  `dem_area_light` pour une selection rapide autour d'une surface cible.
  `generated_candidates` produit maintenant le reseau DEM vectorise, l'audit des
  candidats rejetes et le scoring BD Topage/custom quand disponible. Les
  confluences, l'ordre de Strahler explicite et les sorties de sous-bassins
  restent a enrichir.
- Le catalogue de candidats et le rapport Markdown restent des jalons futurs.

## Verification actuelle

### Cas tests developpes

Les tests `tests/unit/site_selection` sont organises par niveau de contrat:

| Fichier | Ce qui est teste | Ce qu'il faut en attendre |
| --- | --- | --- |
| `test_config.py` | validation TOML/Pydantic, profils `area_only` et `observation_led`, regions FR | les configurations invalides sont rejetees tot avec des erreurs explicites |
| `test_candidate_outlets.py` | construction et reprojection des exutoires candidats depuis stations/CSV, espacement minimal | les candidats gardent les metadonnees de station et les doublons proches sont filtres |
| `test_candidate_generation.py` | generation de candidats depuis un raster d'accumulation, workflow `generated_candidates`, workflow `dem_area_light`, reseau DEM vectorise et scoring reseau de reference | un DEM peut produire des exutoires candidats reproductibles, audites avec raisons de rejet, visualisables en GeoJSON et enrichis par distance/score BD Topage/custom |
| `test_criteria.py` | surface, station hydro, piezometrie, influence, geologie | chaque critere produit un composant auditable, avec score, flags et rejet dur si configure |
| `test_selection.py` | decision finale, recouvrement entre bassins, echecs de delimitation, rejet des stations trop eloignees apres snap | les bassins retenus/rejetes sont stables et explicables |
| `test_filters.py` | calcul du recouvrement spatial | le filtre de recouvrement utilise le denominateur attendu |
| `test_exports.py` | CSV, JSONL, GeoJSON, GeoPackage, GeoParquet, schema `selected_sites.csv`, geometrie d'exutoire snappe | les artefacts d'audit et les exports GIS gardent leurs colonnes/cles stables; l'exutoire cartographie est le point snappe quand disponible |
| `test_reference_network.py` | projection d'un exutoire sur un reseau de reference et rejet si trop eloigne | l'option BD Topage/custom reste bornee et auditable |
| `test_influence_layers.py` | croisement de couches vectorielles d'influence avec les bassins, injection de flags et export GeoJSON | les influences calculees automatiquement alimentent le critere `influence` et restent auditables |
| `test_geology_piezometry_layers.py` | croisement geologique polygonal, association de piezometres, sorties workflow associees | les couches configurees alimentent les criteres `geology` et `piezometer`, puis produisent JSONL, GeoJSON, GPKG et points d'observation |
| `test_manifest_report.py` | manifest officiel, validation d'artefacts, HTML, PNG, GPKG et GeoParquet | le rapport reste derive du manifest et detecte les artefacts invalides |
| `test_synthetic_spatial_review.py` | scenario spatial synthetique complet | la chaine ecrit bassins, observations, carte PNG et HTML de revue |
| `test_workflow_plan.py` | planification, CSV pre-delimites, plan-only, resolution DEM | les commandes workflow ecrivent les sorties attendues sans lancer de solveur |
| `test_build.py` | build station-led depuis `PointRecord`, delimitation, exports | la chaine observations -> exutoires -> bassins -> selection fonctionne sur fixtures |
| `test_data_layers.py` | adaptateur hydrometrie et racine de donnees par defaut | `site_selection` passe par les data managers et respecte `HYDROMODPY_WORKSPACE` |
| `test_delineation.py` | delegation a la delimitation existante, pre-snap reseau de reference et gestion d'erreur | les echecs de delimitation deviennent des candidats rejetes auditables |
| `test_flow_products_adapter.py` | delegation aux produits hydrologiques DEM existants | `site_selection` ne reimplemente pas les produits de flux |
| `test_observation_evidence.py` | normalisation des evidences d'observation | les sorties ne dependent pas directement des schemas bruts fournisseur |
| `test_example_configs.py` | exemples Bretagne/AURA et runs fixtures | les TOML d'exemple restent chargeables et executables sur donnees legeres |
| `test_workflow_dispatch.py` | enregistrement `site_selection` dans le dispatch `hmp run` | le workflow doit etre resolu comme mode officiel |

Tests connexes hors dossier `site_selection`:

- `tests/unit/data_managers/test_france_administrative_regions.py`: registre
  des regions francaises, alias et departements deduits;
- `tests/unit/data_managers/test_geoplateforme_dem_downloader.py`: parsing Atom,
  pagination, cache local et fallback BD ALTI;
- `tests/unit/data_managers/test_dem_manager.py`: resolution DEM `ign_bdalti`
  par departements explicites ou regions;
- `tests/unit/launchers/test_hmp_simulation_cli.py`: dispatch `hmp run` vers le
  workflow `site_selection`;
- `tests/integration/test_cli_subcommands.py`: aide CLI, `config check`, plan
  `site-selection` et generation de rapport plan-only.

### Comment les faire fonctionner

Commande cible dans un environnement complet. `pytest-xdist` doit etre installe
car `pytest.ini` configure `--dist=loadgroup`; il est deja declare dans
`pyproject.toml` sous l'extra `test`.

```bash
python -m pytest -q tests/unit/site_selection
```

Resultat observe le 2026-05-23:

```text
90 passed
```

Resultat relance le 2026-05-24 apres les changements BD Topage/doc:

```text
91 passed
```

Resultat relance le 2026-05-24 apres l'ajout des sorties GPKG/GeoParquet:

```text
93 passed
```

Resultat cible relance apres l'ajout des couches d'influence automatiques:

```text
35 passed
```

Resultat complet `tests/unit/site_selection` relance apres regeneration de la
reference TOML:

```text
95 passed
```

Resultat complet `tests/unit/site_selection` relance le 2026-05-25 apres ajout
du croisement geologie/piezometrie generique:

```text
98 passed
```

Resultat complet `tests/unit/site_selection` relance le 2026-05-25 apres ajout
du mode `generated_candidates`:

```text
100 passed
```

Resultat complet `tests/unit/site_selection` relance le 2026-05-25 apres reseau
DEM vectorise, audit des rejets, scoring reseau de reference et exemple
Bretagne genere:

```text
108 passed
```

Pour les tests de donnees associes au DEM et aux regions francaises:

```bash
python -m pytest -q tests/unit/data_managers/test_dem_manager.py tests/unit/data_managers/test_geoplateforme_dem_downloader.py tests/unit/data_managers/test_france_administrative_regions.py
```

Resultat observe le 2026-05-23:

```text
14 passed
```

Commande de verification ciblee complete:

```bash
python -m pytest -q tests/unit/site_selection tests/unit/data_managers/test_dem_manager.py tests/unit/data_managers/test_geoplateforme_dem_downloader.py tests/unit/data_managers/test_france_administrative_regions.py tests/unit/launchers/test_hmp_simulation_cli.py tests/integration/test_cli_subcommands.py
```

Resultat observe le 2026-05-23:

```text
158 passed
```

Commandes de lint et tests a relancer avant integration:

```bash
python -m ruff check hydromodpy/spatial/site_selection hydromodpy/workflow/site_selection.py hydromodpy/workflow/site_selection_data.py hydromodpy/cli/commands/site_selection.py tests/unit/site_selection
python -m pytest -q tests/unit/site_selection tests/unit/data_managers/test_dem_manager.py tests/unit/data_managers/test_geoplateforme_dem_downloader.py tests/unit/data_managers/test_france_administrative_regions.py tests/unit/launchers/test_hmp_simulation_cli.py tests/integration/test_cli_subcommands.py
```

Resultat lint cible relance le 2026-05-24:

```text
All checks passed!
```

## Consolidations realisees

1. Validation explicite du manifest et de l'existence des artefacts references.
2. Schema de colonnes documente pour `selected_sites.csv` et
   `regional_lab_sites.csv`.
3. Criteres auditables et tests unitaires au-dela de la surface: observations,
   piezometrie, influence, geologie.
4. Sorties geometriques GeoJSON pour exutoires, contours de bassins quand
   disponibles, et points d'observation.
5. HTML conserve comme rapport derive du manifest, enrichi seulement par les
   artefacts stabilises, les familles de criteres disponibles et une carte PNG
   lisible.

## Prochaines consolidations recommandees

### Lecture pedagogique des priorites

Les evolutions ci-dessous ne sont pas equivalentes. Elles repondent a quatre
questions differentes:

1. Ou proposer des sites quand on n'a pas deja une station ou un CSV?
   C'est le role de la generation autonome de candidats DEM/reseau.
2. Pourquoi rejeter ou degrader un site?
   C'est le role des influences, de la geologie et de la piezometrie.
3. Comment livrer les resultats a un SIG ou a une analyse de production?
   C'est le role des exports GeoPackage/GeoParquet stabilises.
4. Comment verifier rapidement une campagne?
   C'est le role de la carte interactive, qui doit rester une vue derivee des
   artefacts, pas une deuxieme source de verite.

L'ordre recommande est donc:

1. ameliorer les candidats DEM-only;
2. brancher les couches metier reelles;
3. figer les schemas d'export;
4. construire ensuite la carte interactive.

Cet ordre evite de faire une belle interface sur des candidats encore trop
pauvres, ou de figer un schema avant de connaitre les evidences metier
reellement disponibles.

### 1. Generation autonome de candidats DEM/reseau

Objectif:

- permettre un run `criteria_crossing` ou `dem_only` sans CSV de bassins
  pre-delimites et sans stations hydrometriques imposees comme seuls exutoires;
- produire automatiquement une grille ou un catalogue de candidats le long du
  reseau hydrographique, puis reutiliser la chaine existante de delimitation et
  de selection.

Etat actuel:

- `site_selection` sait charger des candidats depuis un CSV et sait construire
  des exutoires depuis des stations deja chargees;
- les produits DEM (`dem_fill`, direction, accumulation) sont deja construits
  par les primitives existantes;
- `candidate_mode = "network_sampling"` est maintenant executable avec
  `site_selection.input.mode = "generated_candidates"`;
- le code lit le raster d'accumulation, selectionne les cellules les plus
  accumulatrices, applique `min_distance_between_outlets_km`, borne le nombre
  de candidats avec `max_generated_candidates`, puis delimite chaque candidat.

Travail technique:

- Enrichir l'echantillonnage actuel.
  Aujourd'hui, le code choisit surtout les cellules de plus forte accumulation.
  Cela repere bien les grands axes aval, mais pas forcement les sites utiles
  pour une campagne 50-500 km2. Il faut donc ajouter plusieurs manieres de
  proposer des exutoires:

  - sorties de bassin: points situes a l'aval de sous-bassins de taille
    compatible avec la cible;
  - confluences: points ou deux branches du reseau se rejoignent, souvent plus
    faciles a interpreter hydrologiquement;
  - points espaces regulierement: points repartis le long du reseau pour eviter
    de tout concentrer sur la zone de plus forte accumulation;
  - classes d'accumulation: points tires dans plusieurs classes, par exemple
    petits, moyens et grands bassins, au lieu de garder seulement les plus
    grandes accumulations.

  Le resultat attendu est une liste de candidats plus variee: des bassins de
  tailles differentes, mieux repartis dans la region, et moins concentres sur un
  seul grand cours d'eau aval.

- Contraindre optionnellement les candidats par BD Topage ou par un reseau
  custom.
  Le DEM calcule son propre reseau a partir de la topographie. Ce reseau peut
  etre decale par rapport au reseau hydrographique officiel, surtout avec un
  MNT grossier, des ouvrages, des zones planes ou des corrections hydrauliques
  imparfaites. L'idee est donc de ne garder, ou de mieux classer, que les
  candidats proches d'un reseau de reference comme BD Topage ou un reseau fourni
  par l'utilisateur.

  Deux usages sont possibles:

  - contrainte douce: le candidat reste possible, mais il recoit un mauvais
    score s'il est loin du reseau de reference;
  - contrainte dure: le candidat est rejete s'il est trop loin du reseau de
    reference.

  Cela reprend l'esprit de `bdtopage_then_dem`, mais pour les candidats generes
  automatiquement, pas seulement pour les stations hydrometriques.

- Ajouter une relation plus riche avec le reseau de reference.
  La distance au reseau est une premiere information, mais elle ne suffit pas.
  Il faut aussi savoir sur quel type de troncon le candidat tombe. Par exemple,
  un candidat proche d'un petit fossé et un candidat proche d'un cours d'eau
  principal ne doivent pas forcement etre classes de la meme maniere.

  Les informations utiles a calculer sont:

  - distance du candidat au reseau de reference;
  - identifiant du troncon BD Topage ou custom le plus proche;
  - ordre ou importance du cours d'eau, si cette information est disponible;
  - statut du candidat: proche du reseau, trop eloigne, ambigu, hors emprise;
  - score de confiance combinant distance, importance du troncon et coherence
    avec la surface amont DEM.

  Le but est que le rapport puisse dire: ce candidat est bon parce qu'il est sur
  un troncon coherent du reseau de reference, ou au contraire ce candidat est
  douteux parce qu'il est loin du reseau officiel.

- Exporter les candidats ignores avant delimitation.
  La delimitation des bassins est couteuse. On ne veut donc pas delimiter toutes
  les cellules possibles du reseau. Le code filtre d'abord beaucoup de points:
  certains sont trop proches d'un meilleur candidat, d'autres sont sous le seuil
  d'accumulation, d'autres depassent la limite du nombre de candidats.

  Pour auditer correctement une campagne, il peut etre utile de conserver la
  trace de ces candidats ignores. L'export doit indiquer:

  - coordonnees du point ignore;
  - accumulation ou surface amont estimee;
  - raison du rejet avant delimitation;
  - candidat retenu le plus proche, quand le rejet vient de l'espacement;
  - distance au reseau de reference, si elle a ete calculee.

  Cela permet de justifier pourquoi certains secteurs du reseau n'apparaissent
  pas dans les bassins finalement delimites.

Sorties attendues:

- `candidate_outlets.geojson`, disponible pour les candidats generes;
- `candidate_generation.jsonl` avec source du candidat, accumulation, seuil
  utilise, rang et coordonnees raster;
- runs `hmp run` possibles avec `mode = "site_selection"` et sans
  `catchments_csv`, via `site_selection.input.mode = "generated_candidates"`.

Critere de validation:

- un test synthetique prouve qu'un raster d'accumulation simple produit des
  candidats reproductibles;
- un test workflow prouve que ces candidats sont delimites et que les exports
  `candidate_generation.jsonl` et `candidate_outlets.geojson` sont ecrits;
- un exemple regional court reste a ajouter pour produire des bassins sans CSV
  d'entree sur donnees reelles;
- le manifest doit distinguer clairement candidats generes, candidats delimites,
  sites selectionnes et sites rejetes.

Etat de test:

- `tests/unit/site_selection/test_candidate_generation.py` verifie la selection
  deterministe de cellules de forte accumulation et l'ecriture des artefacts
  candidats;
- le meme fichier verifie un workflow `generated_candidates` complet avec
  delimitation simulee et manifest d'action `generated_candidates`.

### 2. Influence automatique

Objectif:

- ne plus dependre uniquement de flags deja presents dans les CSV
  (`major_dam_upstream`, `major_withdrawal_upstream`, etc.);
- calculer ces flags depuis des couches regionales chargees par le workflow.

Etat actuel:

- les criteres d'influence existent et sont auditables;
- une influence inconnue ne rejette pas un bassin;
- le code sait consommer des flags explicites;
- le workflow peut maintenant lire des couches vectorielles declarees dans
  `site_selection.criteria.influence.layers`, les intersecter avec les bassins
  et remplir automatiquement les flags consommes par `criteria.influence`;
- les evidences sont exportables en JSONL, GeoJSON, GeoParquet et couche GPKG.

Travail technique:

- brancher des sources de donnees regionales reelles et stabiliser leurs
  champs de correspondance (`id_field`, `label_field`, `severity_field`);
- ajouter au besoin des modes de relation plus hydrologiques: influence sur le
  reseau amont, influence dans un buffer du reseau, influence a distance de
  l'exutoire;
- enrichir la carte HTML avec une legende et des popups specifiques aux
  influences;
- documenter une convention de severite commune pour les campagnes France.

Sources possibles a brancher, sans les coder en dur dans les primitives:

- obstacles, barrages, seuils et plans d'eau;
- prelevements et rejets significatifs;
- troncons explicitement regules ou fortement artificialises;
- couches locales propres a une campagne.

Sorties attendues:

- `influence_evidence.jsonl`, disponible quand au moins une influence est
  detectee;
- `influence_features.geojson`, `influence_features.parquet` et couche
  `influence_features` dans `site_selection.gpkg` selon les switches de sortie;
- champs de synthese dans les attributs de bassin et, a terme, dans
  `selected_sites.csv` et `rejected_sites.csv`.

Critere de validation:

- un bassin avec une influence explicite en amont doit etre rejete si la regle
  est en `hard_reject`;
- un bassin sans couche disponible doit rester en statut "inconnu" et non
  rejete par defaut;
- la carte et le HTML doivent permettre de voir quelle influence explique le
  rejet.

Etat de test:

- `tests/unit/site_selection/test_influence_layers.py` verifie qu'une couche
  vectorielle intersectant un bassin renseigne `major_dam_upstream` et provoque
  un rejet en mode `hard_reject`;
- le meme fichier verifie l'export GeoJSON des evidences d'influence.

### 3. Croisement geologie et piezometrie

Objectif geologie:

- passer d'une classe geologique deja fournie dans un CSV a un vrai croisement
  spatial entre bassins et couche geologique;
- permettre une typologie configurable par campagne.

Etat actuel geologie:

- le critere `geology` existe comme evidence, score simple ou stratification;
- le workflow sait lire des couches polygonales declarees dans
  `site_selection.criteria.geology.layers`;
- le croisement calcule les fractions de surface par classe, la classe
  dominante et un compteur de diversite simple;
- ces attributs alimentent le critere `geology` et les exports d'evidence.

Travail technique geologie:

- brancher une source BRGM ou regionalisee concrete dans les gestionnaires de
  donnees, sans coder le fournisseur dans les primitives spatiales;
- ajouter une table de regroupement optionnelle si les classes fournisseur sont
  trop fines pour une campagne;
- documenter le schema de sortie final quand la typologie sera stabilisee.

Objectif piezometrie:

- calculer automatiquement la presence et la distance de piezometres utiles au
  lieu de ne consommer que des colonnes CSV pre-normalisees.

Etat actuel piezometrie:

- le critere `piezometer` existe et peut etre en `report_only`, `warning`,
  `score`, `stratify` ou `hard_reject`;
- les points d'observation normalises peuvent deja etre exportes et symbolises;
- le workflow sait lire des couches de points declarees dans
  `site_selection.criteria.observations.piezometer_layers`;
- il associe les piezometres situes dans le bassin ou proches de l'exutoire,
  puis renseigne les distances et le nombre de points disponibles;
- le chargement d'un inventaire piezometrique fournisseur par data manager reste
  a brancher.

Travail technique piezometrie:

- charger l'inventaire piezometrique via les gestionnaires de donnees, pas dans
  les primitives `spatial.site_selection`;
- ajouter au besoin des relations supplementaires: distance au reseau ou
  distance a la station hydrometrique;
- stabiliser les conventions de champs pour periode disponible et statut de
  qualite selon la source reelle.

Sorties attendues:

- `geology_evidence.jsonl`, disponible quand une couche geologique matche un
  bassin;
- `geology_basins.geojson`, `geology_basins.parquet` et couche
  `geology_basins` dans `site_selection.gpkg` selon les switches de sortie;
- `piezometer_evidence.jsonl`, disponible quand au moins un piezometre est
  associe a un bassin;
- `observation_points.geojson`, `observation_points.parquet` et couche
  `observation_points` enrichies avec les piezometres geolocalises.

Critere de validation:

- un bassin recoupant plusieurs classes geologiques doit avoir des fractions
  auditees et une classe dominante reproductible;
- un piezometre dans le bassin ou proche de l'exutoire doit produire une
  evidence lisible dans le HTML et dans le GeoJSON.

Etat de test:

- `tests/unit/site_selection/test_geology_piezometry_layers.py` verifie la
  geologie dominante et les fractions issues d'une couche polygonale;
- le meme fichier verifie qu'un piezometre dans le bassin renseigne les
  attributs consommes par le critere `piezometer`;
- le test workflow verifie l'ecriture de `geology_evidence.jsonl`,
  `geology_basins.geojson`, `piezometer_evidence.jsonl`,
  `observation_points.geojson` et des couches GPKG correspondantes.

### 4. Sortie polygonale robuste GeoParquet/GPKG

Objectif:

- conserver le GeoJSON comme format de revue leger, mais ajouter un format de
  production plus robuste pour les bassins, exutoires et couches d'evidence;
- eviter les limites du GeoJSON pour les geometries lourdes, les CRS, les
  schemas de colonnes et les usages GIS.

Etat actuel:

- `selected_basins.geojson`, `rejected_basins.geojson`,
  `selected_outlets.geojson`, `rejected_outlets.geojson` et
  `observation_points.geojson` sont produits quand les geometries existent;
- `write_geopackage = true` produit maintenant `site_selection.gpkg` avec les
  couches non vides `selected_outlets`, `rejected_outlets`,
  `selected_basins`, `rejected_basins`, puis `observation_points` quand les
  evidences d'observation portent une localisation. Les couches
  `influence_features` et `geology_basins` sont ajoutees quand les evidences
  correspondantes existent;
- `write_geoparquet = true` produit maintenant des fichiers GeoParquet separes
  par couche spatiale disponible, incluant les evidences d'influence, de
  geologie et les points d'observation/piezometrie quand presents;
- le manifest reference ces sorties et valide maintenant les artefacts GPKG et
  GeoParquet, en plus des GeoJSON, CSV, JSONL et PNG.

Travail technique:

- stabiliser le schema de production au-dela des champs deja exportes:
  decision, surface, CRS, snap, distances, criteres principaux et chemins
  d'artefacts sources sont presents; il reste a figer le schema final des
  evidences fournisseur reelles;
- ajouter une etape de validation/reparation geometrique plus explicite quand
  les contours proviennent de shapefiles temporaires;
- documenter si les piezometres restent dans `observation_points` ou si une
  couche specialisee `piezometer_points` devient necessaire;
- documenter le schema final une fois ces couches branchees.

Sorties attendues:

- option GeoPackage deja disponible: `site_selection.gpkg` avec couches
  `selected_basins`, `rejected_basins`, `selected_outlets`,
  `rejected_outlets`, `observation_points`, `influence_features` et
  `geology_basins` quand les evidences existent;
- option GeoParquet deja disponible: fichiers separes par couche, adaptes aux
  traitements analytiques;
- les piezometres sont pour l'instant exportes comme points d'observation
  normalises dans `observation_points`.

Critere de validation:

- GeoPandas relit les couches avec le bon CRS et les bons champs; cette
  validation est couverte par `tests/unit/site_selection/test_exports.py`;
- `validate_selection_manifest()` accepte les artefacts GPKG et GeoParquet
  lisibles; cette validation est couverte par
  `tests/unit/site_selection/test_manifest_report.py`;
- la carte statique et la future carte interactive doivent pouvoir etre
  reconstruites depuis ces sorties sans relire les shapefiles temporaires de
  delimitation.

### 5. Carte interactive

Objectif:

- remplacer le PNG statique par une vue de revue plus riche, sans faire du HTML
  une deuxieme source de verite;
- permettre d'inspecter facilement pourquoi un site est retenu ou rejete.

Etat actuel:

- le rapport HTML derive du manifest et embarque une carte PNG lisible;
- les rapports HTML commencent a converger vers des blocs communs documentes
  dans `docs/_dev_notes/html_block_reports_audit.md`;
- la carte statique sait afficher bassins, exutoires, stations, liens
  station-exutoire et couches de contexte.

Travail technique:

- construire la carte interactive a partir du manifest et des artefacts GIS
  stabilises, pas depuis des fichiers temporaires;
- ajouter des couches activables: bassins retenus/rejetes, exutoires snappes,
  stations, piezometres, influences, BD Topage, geologie, fond DEM simplifie;
- ajouter des popups par site avec decision, score, surface, snap, distance
  station-exutoire, criteres en warning et raisons de rejet;
- ajouter des filtres simples par statut, classe de surface, source
  d'observation et presence d'influence;
- reutiliser le gabarit de blocs HTML commun pour eviter un rapport specifique
  non maintenable.

Ordre recommande:

1. stabiliser d'abord les sorties polygonales GeoParquet/GPKG;
2. brancher geologie, piezometrie et influence comme couches/evidences;
3. seulement ensuite produire la carte interactive, qui consommera ces sorties.

Critere de validation:

- ouvrir `review/index.html` hors serveur doit rester possible;
- la carte doit fonctionner quand certains artefacts optionnels sont absents;
- un test HTML doit verifier la presence des couches attendues et des liens
  vers les artefacts sources.

## Note DEM Geoplateforme

Le plan dedie au telechargement robuste des DEM/MNT IGN par departement est
documente dans:

```text
docs/_dev_notes/geoplateforme_dem_downloader_implementation_plan.md
```

Ce chantier doit rester dans la couche `hydromodpy.data.variables.dem` et dans
un CLI autonome sous `tools/`. Il ne doit pas etre implemente dans
`site_selection`.

Etat d'implementation au 2026-05-17:

- ajout d'un registre valide de regions francaises dans
  `hydromodpy.data.common.administrative.france`, avec canonicalisation des
  noms utilises dans les TOML `site_selection` quand `country = "FR"`;
- ajout du client isole
  `hydromodpy.data.variables.dem.apis.geoplateforme_download`;
- ajout de la couche produit
  `hydromodpy.data.variables.dem.apis.ign_dem_fr`, avec fallback BD ALTI 25 m
  sur la table historique quand la decouverte Geoplateforme est indisponible;
- ajout du CLI autonome `tools/download_dem_fr/download_dem_fr.py`;
- ajout des tests unitaires sans reseau pour regions, parsing Atom,
  pagination, cache local et fallback BD ALTI.

## Organisation des donnees et chemin par defaut

Les DEM, archives IGN, couches geologiques regionales, inventaires Hub'Eau
materialises et rasters assembles sont des donnees. Ils ne doivent pas etre
stockes par defaut dans `examples/data` ni suivis par Git.

Regle mise en place:

- le CLI `tools/download_dem_fr/download_dem_fr.py` ecrit par defaut dans
  `HYDROMODPY_WORKSPACE/data/dem/raw_ign` si `HYDROMODPY_WORKSPACE` est defini,
  sinon dans `~/hydromodpy/data/dem/raw_ign`;
- les appels `site_selection` au gestionnaire de donnees utilisent
  `HYDROMODPY_WORKSPACE/data` si disponible, sinon `~/hydromodpy/data`, quand
  aucun `workspace_root` ou `data_root` explicite n'est fourni;
- `[data.dem]` accepte maintenant `regions = [...]` pour `source =
  "ign_bdalti"` et resout les departements francais correspondants dans le
  gestionnaire DEM;
- les exemples Bretagne ne pointent plus explicitement vers `examples/data`;
- l'exemple AURA declare maintenant un DEM regional par
  `regions = ["Auvergne-Rhone-Alpes"]` et peut utiliser ce DEM comme fond de
  carte meme si les bassins d'entree restent pre-delimites;
- les criteres de surface des exemples utilisent des plages explicites
  `[[site_selection.criteria.area.ranges]]` avec `min_area_km2` et
  `max_area_km2`, au lieu d'un melange peu lisible de surface cible,
  preference et demi-largeur de score;
- les gros artefacts locaux deja generes sous `examples/data/dem`,
  `examples/data/geology` et `examples/projects/17_site_selection_workflow/outputs`
  sont ignores de facon ciblee par `.gitignore`.

Cette organisation separe:

- code versionne: clients, workflows, tests, schemas et documentation;
- fixtures legeres versionnables: petits CSV/GeoJSON necessaires aux exemples;
- donnees fournisseurs et produits lourds: cache utilisateur ou workspace.

## Progression vers une demande autonome Rhone-Alpes

Objectif: pouvoir demander une figure ou un rapport AURA sans preparer a la
main les departements, les DEM ou les chemins de donnees.

Etapes progressives:

1. Valider le territoire `regions = ["Auvergne-Rhone-Alpes"]` via le registre
   de regions francaises et resoudre les 12 departements IGN attendus:
   `01`, `03`, `07`, `15`, `26`, `38`, `42`, `43`, `63`, `69`, `73`, `74`.
2. Telecharger en cache les archives BD ALTI 25 m des departements AURA avec
   le CLI ou directement via `DemManager`.
3. Assembler un DEM regional produit dans `<workspace>/data/dem`, reference
   dans `data/cache.duckdb`, puis reutilise tant que le cache est valide.
4. Brancher l'exemple AURA sur `[data.dem]`, comme la Bretagne, pour que la
   carte de revue utilise le DEM regional reel au lieu d'un fond fixture. Ce
   branchement est fait: le DEM est demande par region, pas par liste manuelle
   de departements.
5. Remplacer progressivement les bassins synthetiques AURA par une selection
   autonome: le chemin stations hydro comme exutoires est maintenant cable dans
   `auvergne_rhone_alpes_hydrometry_50_150.toml`; le chemin candidats generes
   par croisement de criteres et delimites depuis le DEM reste a construire.

Ce chemin evite de melanger trois responsabilites: `site_selection` choisit et
documente les sites, `hydromodpy.data.variables.dem` recupere les DEM, et le
workspace porte les donnees reutilisables.

## Couche generique de decisions

Objectif court terme: rendre les deux modes utilises maintenant plus lisibles et
preparer les extensions sans reecrire le workflow:

- selection par surface de bassin seule;
- selection de bassins jauges par station hydrometrique a l'aval;
- rejet ou avertissement via les influences deja materialisees en couches
  locales, par exemple un barrage majeur en amont.

Mise en place:

- ajout du sous-paquet `hydromodpy.spatial.site_selection.decisions`;
- ajout de `DecisionRecord`, `EvidenceRecord` et `SiteDecisionSummary`;
- conversion automatique des `CriteriaComponent` existants en decisions
  normalisees `ACCEPT`, `WARNING`, `REJECT` ou `NEUTRAL`;
- ajout d'une decision finale par bassin pour rendre auditables les rejets qui
  ne sont pas des criteres metier, par exemple `target_count_reached` ou un
  echec de delimitation;
- ajout des exports `site_selection_decisions.jsonl` et
  `site_selection_decisions.csv`.

Cette etape ne remplace pas les fichiers existants. `selection_decisions.jsonl`
et `criteria_components.jsonl` restent le contrat historique; les nouveaux
fichiers sont une couche plus generique et plus stable pour l'evolution vers un
dossier de decision complet.

## Decoupage des criteres par famille

Le fichier historique `criteria.py` portait tous les evaluateurs de criteres.
Il reste maintenant une facade de compatibilite: les imports publics existants
continuent de fonctionner, mais le code metier est range par famille:

- `criteria_common.py`: `CriteriaComponent` et helpers de parsing;
- `criteria_area.py`: critere de surface de bassin;
- `criteria_observations.py`: station hydrometrique et piezometres;
- `criteria_influence.py`: influences anthropiques deja normalisees en flags;
- `criteria_geology.py`: geologie.

Ce decoupage ne change pas le comportement. Il rend explicite l'endroit ou
ajouter une regle metier, par exemple enrichir l'hydrometrie dans
`criteria_observations.py` ou remplacer progressivement les flags locaux
d'influence par des regles provider dans `criteria_influence.py`.

## Couche generique de preuves

Objectif: relier les decisions normalisees a des preuves auditables sans
remplacer les exports specialises deja disponibles.

Mise en place:

- ajout de `evidence_refs.py` pour construire des identifiants deterministes:
  `flow_station:<site>:<station>`,
  `influence:<site>:<type>:<feature>` et
  `geology:<site>:<source>:<classe>`;
- ajout d'adaptateurs vers `EvidenceRecord` pour:
  - `ObservationEvidence`, utilise pour les stations hydrometriques et les
    piezometres;
  - `InfluenceEvidence`, utilise pour les couches locales d'influence;
  - `GeologyEvidence`, utilise pour les intersections geologiques;
- ajout de l'export `site_selection_evidence.jsonl` quand au moins une preuve
  normalisee existe;
- ajout de `evidence_ref` dans les `DecisionRecord` lorsque le critere peut
  etre relie a une preuve concrete.

Limites assumees a ce stade:

- la surface de bassin reste une metrique de critere, pas une preuve externe;
- les influences utilisent encore les couches vectorielles locales deja
  configurees; ROE/BNPE restent une evolution provider future;
- une decision d'influence peut referencer la premiere preuve bloquante et
  conserve la liste complete dans `properties.evidence_json.evidence_refs`.

Cette etape rend le cas court terme plus auditable: un rejet pour barrage amont
renvoie maintenant a une preuve d'influence stable, et une selection par station
peut renvoyer a la station hydrometrique normalisee correspondante.
