# Exemples `site_selection`

Ce dossier donne plusieurs configurations courtes pour illustrer deux principes
de selection differents. Certaines lignes CSV sont des fixtures synthetiques
pour tester la mecanique; les variantes hydrometriques materialisent au
contraire des sites issus du referentiel Hub'Eau afin de travailler sur des cas
plus proches d'un inventaire reel.

## Apercu rapide des exemples

| Exemple | Territoire | Jauge | Surface | Nb demande | Entree |
| --- | --- | --- | --- | --- | --- |
| [`bretagne_jauge_csv_10_1000km2.toml`](configs/bretagne_jauge_csv_10_1000km2.toml) | Bretagne | oui | 10-1000 km2 | 4 bassins CSV | Bassins/stations pre-normalises. |
| [`bretagne_jauge_50_500km2.toml`](configs/bretagne_jauge_50_500km2.toml) | Bretagne | oui | 50-500 km2 | non plafonne | Inventaire regional. |
| [`bretagne_jauge_7stations.toml`](configs/bretagne_jauge_7stations.toml) | Bretagne | oui | aucune plage | 7 stations | Stations explicites, snap BD Topage puis DEM. |
| [`finistere_jauge_elorn_dem.toml`](configs/finistere_jauge_elorn_dem.toml) | Finistere | oui | aucun critere | 1 station | Test departemental rapide du rapport HTML. |
| [`aura_jauge_regional_50_150km2.toml`](configs/aura_jauge_regional_50_150km2.toml) | Auvergne-Rhone-Alpes | oui | 50-150 km2 | non plafonne | Inventaire regional Hub'Eau. |
| [`aura_jauge_5stations.toml`](configs/aura_jauge_5stations.toml) | Auvergne-Rhone-Alpes | oui | aucun critere | 5 stations | Hub'Eau, stations explicites. |
| [`aura_non_jauge_csv_50_150km2.toml`](configs/aura_non_jauge_csv_50_150km2.toml) | Auvergne-Rhone-Alpes | non | 50-150 km2 | 20 bassins CSV | Bassins deja delimites, critere surface seul. |
| [`bretagne_non_jauge_dem_reseau_50_500km2.toml`](configs/bretagne_non_jauge_dem_reseau_50_500km2.toml) | Bretagne | non | 50-500 km2 | 12 candidats max | Generation experimentale depuis DEM/reseau. |
| [`calvados_non_jauge_dem_10bassins_100km2.toml`](configs/calvados_non_jauge_dem_10bassins_100km2.toml) | Calvados | non | cible 100 km2, 75-125 km2 | 10 bassins | Generation DEM rapide. |
| [`manche_non_jauge_dem_10bassins_100km2.toml`](configs/manche_non_jauge_dem_10bassins_100km2.toml) | Manche | non | cible 100 km2, 75-125 km2 | 10 bassins | Generation DEM departementale rapide. |
| [`normandie_non_jauge_dem_50bassins_100km2.toml`](configs/normandie_non_jauge_dem_50bassins_100km2.toml) | Normandie | non | cible 100 km2, 75-125 km2 | 50 bassins | Generation DEM regionale plafonnee. |
| [`corse_jauge_5stations.toml`](configs/corse_jauge_5stations.toml) | Corse | oui | aucun critere | 5 stations | Stations explicites Hub'Eau. |
| [`corse_non_jauge_csv_30_500km2.toml`](configs/corse_non_jauge_csv_30_500km2.toml) | Corse | non | 30-500 km2 | bassins CSV | Bassins deja delimites, preview surface. |

Dans les lignes jaugees, le nombre demande correspond au nombre de stations
chargees ou plafonnees quand la configuration le precise. Chaque station donne
un exutoire candidat, puis un bassin est delimite autour de cet exutoire.

### Vocabulaire des chemins d'execution

- `delineated_catchments`: les bassins candidats sont deja delimites et fournis
  dans un CSV. Le workflow relit ces bassins, applique les criteres et produit
  les exports officiels.
- `hydrometry`: le workflow charge les stations hydrometriques, typiquement via
  Hub'Eau, puis utilise chaque station comme exutoire candidat avant la
  delimitation DEM.
- `dem_area_target`: recherche DEM simplifiee. Le workflow cherche
  automatiquement des exutoires dont le bassin amont est proche d'une surface
  cible, puis retient les bassins les mieux classes.
- `dem_network_sampling`: echantillonnage avance du reseau DEM. Le workflow
  expose les controles de generation d'exutoires (`candidate_mode`,
  distances, nombre maximal de candidats) avant la delimitation et la selection.
- `plan_only`: dry-run. Le workflow valide la configuration et ecrit le plan
  d'execution/rapport, sans charger les observations, generer de candidats ni
  selectionner de sites.

`region_id` n'est pas un filtre spatial. Quand le territoire contient une seule
region administrative, il est derive automatiquement depuis
`[site_selection.territory]`. Il ne doit etre renseigne que pour imposer un
libelle de sortie particulier, par exemple un departement en clair ou un
territoire multi-regions.

### Convention de nommage

Les TOML de selection suivent une denomination explicite:
`territoire_jauge|non_jauge[_source]_nombre[_surface].toml`. Le suffixe de
source est garde seulement quand il distingue vraiment le scenario; pour les
stations hydrometriques explicites, la source est deja lisible dans
`[hydrometry.sources]`. Le suffixe de surface est present seulement quand la
surface fait partie du scenario. Les identifiants de run (`selection_id`) et les
dossiers `outputs/...` suivent le meme nom court que le fichier TOML.

## 1. Bretagne, stations hydrometriques comme entree principale

Fichier:

```text
configs/bretagne_jauge_csv_10_1000km2.toml
```

Principe:

- `site_selection.input.mode = "delineated_catchments"` rejoue un inventaire
  de bassins deja delimites; le profil `gauged_downstream_station` reste donc
  explicite pour traiter ce CSV comme un inventaire jauge ;
- les stations de debit sont le critere d'entree principal ;
- les controles de non-influence, de surface et de geologie viennent ensuite ;
- l'exemple part d'un CSV d'exutoires et de stations pre-normalisees ;
- le DEM est declare dans `[data.dem]` avec la source `ign_geoplateforme_dem`,
  puis mis en
  cache hors du depot dans l'espace de donnees HydroModPy
  (`HYDROMODPY_WORKSPACE/data` si defini, sinon `~/hydromodpy/data`) ;
- la region `Bretagne` est declaree dans `[data.dem]`; le gestionnaire DEM
  resout les departements IGN correspondants sans les ecrire a la main ;
- `site_selection.dem.delineation_dem_extent_source = "candidate_outlets_bbox"`
  construit le DEM de calcul sur la boite englobante des exutoires/stations,
  elargie par `delineation_buffer_km`; c'est plus rapide pour une preview, mais
  cette marge doit couvrir l'amont necessaire a la delimitation hydrologique ;
- `site_selection.dem.review_map_dem_background = "territory_dem"` charge en plus un
  DEM regional pour la carte de revue, afin que la figure soit a l'echelle de
  la Bretagne ;
- les contours de bassins sont recalcules depuis les exutoires avec le DEM
  charge par `[data.dem]`, puis exportes dans
  `outputs/bretagne_jauge_csv_10_1000km2_v1/catchments/.../watershed.shp` ;
- le snap d'exutoire reste en mode direct `dem_accumulation`, avec
  `dem_snap_max_distance_m = 150` pour limiter les deplacements aval ;
- si l'on veut aller chercher de vraies stations Hub'Eau, il faut passer
  `site_selection.input.mode` a `hydrometry`; ce mode infere le profil
  `gauged_downstream_station` et utilise les gestionnaires de donnees
  HydroModPy existants.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_jauge_csv_10_1000km2.toml
```

Cette commande produit notamment:

- `selected_sites.csv` ;
- `rejected_sites.csv` ;
- `selected_basins.geojson`, construit depuis les `watershed.shp` calcules ;
- `rejected_basins.geojson`, construit depuis les `watershed.shp` calcules ;
- `observation_evidence.jsonl` ;
- `observation_points.geojson` ;
- `report_artifact_manifest.json` ;
- `review/index.html` ;
- `review/site_selection_map.png`.

Pour executer une selection observee reelle, il faut passer
`site_selection.input.mode` a `hydrometry`; le DEM reste declare dans
`[data.dem]` et n'est pas stocke dans `site_selection`.

Les exemples ne fixent plus `site_selection.input.data_root` vers
`examples/data`: les donnees brutes et les caches regionaux doivent rester des
donnees de travail, partageables entre projets, mais non suivies dans Git.

## 2. Bretagne, stations Hub'Eau et surface 50-500 km2

Fichier:

```text
configs/bretagne_jauge_50_500km2.toml
```

Principe:

- les candidats sont charges directement depuis Hub'Eau par les gestionnaires
  de donnees HydroModPy, via `site_selection.input.mode = "hydrometry"` ;
- l'emprise de la Bretagne est transformee en WGS84 pour interroger Hub'Eau,
  sans script regional ni CSV intermediaire obligatoire ;
- la station de jaugeage reste le point d'entree: elle fixe l'exutoire ;
- la surface 50-500 km2 est controlee apres recalcul DEM et reportee en
  avertissement, afin de visualiser les ecarts possibles entre surfaces
  provider et surfaces recalculees ;
- cette plage est ecrite explicitement dans
  `[[site_selection.criteria.area.ranges]]` avec `min_area_km2` et
  `max_area_km2`, pour que la configuration reste lisible ;
- les contours de bassins sont recalcules depuis les exutoires avec le DEM IGN
  BD ALTI ;
- le DEM de calcul reste limite aux exutoires pour eviter une generation de
  produits hydrologiques sur toute la Bretagne ;
- le rapport cartographique recharge le DEM regional pour replacer les bassins
  dans leur contexte ;
- les triangles bleus representent les stations hydrometriques; les contours
  de bassins sont colores par classes de surface.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_jauge_50_500km2.toml
```

Cette variante sert de support de discussion sur un inventaire reel charge par
le workflow generique. Une variante reduite est fournie pour les iterations
rapides sur la carte:

```text
configs/bretagne_jauge_7stations.toml
```

Elle charge 7 stations explicites via `station_ids`. Les stations sont les
entrees a verifier: il n'y a pas de plage de surface additionnelle ni de seuil
d'overlap entre bassins. `allow_nested_basins = true` documente que des bassins
amont/aval peuvent coexister dans cette preview.

Le DEM reste declare dans `[data.dem]` avec `source =
"ign_geoplateforme_dem"`, `dataset = "bd-alti"` et `resolution_m = 25.0`. Le
gestionnaire DEM deduit la region depuis `[site_selection.territory]`. Comme
`site_selection.dem.delineation_dem_extent_source = "candidate_outlets_bbox"`,
le workflow charge les stations avant le DEM et limite le DEM de calcul a la
boite englobante des stations, plus `delineation_buffer_km = 30.0`. Le rapport
recharge un DEM regional avec
`site_selection.dem.review_map_dem_background = "territory_dem"` pour replacer les
bassins dans leur contexte.

Les exutoires sont d'abord contraints par BD Topage
(`snap_strategy = "bdtopage_then_dem"`, tolerance de 100 m), puis le snap DEM
local reste limite a 150 m. Cette variante sert a verifier rapidement
l'organisation du rapport HTML, les symboles des stations, le deplacement des
exutoires et les contours de bassins; elle ne remplace pas l'exemple complet
pour l'analyse regionale.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_jauge_7stations.toml
```

Elle produit en plus `outputs/bretagne_jauge_7stations/reference_network/bdtopage_reference_network.gpkg`.
Ce GeoPackage est un artefact technique de snapping: il n'est pas ajoute comme
couche de fond au rapport HTML, afin de ne pas confondre reseau de reference et
bassins effectivement selectionnes.

### Test departemental rapide: Finistere, Elorn

Une variante departementale tres courte sert a tester le contrat HTML sans
lancer tout le domaine Bretagne:

```text
configs/finistere_jauge_elorn_dem.toml
```

Elle utilise le departement `029`, une station Hub'Eau explicite
(`J341303001`, Elorn a Plouedern) et un DEM limite a la boite de la station,
avec `delineation_buffer_km = 5.0`. Ce buffer court est volontaire: le but est
de verifier rapidement les artefacts et le rapport, pas de figer une etude
hydrologique definitive.

Cette variante differe aussi du cas regional strict: `station_influence` est
classe en warning et non en hard reject. Le rapport conserve donc l'information
d'influence locale Hub'Eau, mais le site reste retenu avec avertissements. Le
cas regional Bretagne conserve `station_influence` en `hard_reject`.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/finistere_jauge_elorn_dem.toml
```

Le 2026-06-05, ce run termine en moins d'une minute avec:

- 1 candidat ;
- 1 site selectionne avec avertissements ;
- `report_artifact_manifest.json` complet, 16 artefacts presents sur 16 ;
- HTML a inspecter:
  `outputs/finistere_jauge_elorn_dem_v1/review/index.html`.

## 3. Auvergne-Rhone-Alpes, stations hydrometriques autonomes

Fichier:

```text
configs/aura_jauge_regional_50_150km2.toml
```

Principe:

- `site_selection.input.mode = "hydrometry"` declenche le chargement des
  stations par les gestionnaires de donnees HydroModPy, sans CSV de candidats ;
- `[[hydrometry.sources]]` utilise Hub'Eau avec `extent = "study_area"`; le
  workflow transforme l'emprise de la region en WGS84 pour interroger l'API ;
- le DEM reste declare dans `[data.dem]`, avec `source =
  "ign_geoplateforme_dem"` et `regions = ["Auvergne-Rhone-Alpes"]`; les 12
  departements IGN sont deduits par le gestionnaire DEM ;
- les stations Hub'Eau sont fournies en longitude/latitude, mais le workflow
  utilise les coordonnees Lambert-93 disponibles dans les metadonnees Hub'Eau
  pour construire les exutoires candidats avant la delimitation ;
- la station hydrometrique reste le critere d'entree principal; la surface
  50-150 km2 est exprimee comme plage explicite et reportee en avertissement
  pour controler l'inventaire sans perdre les sites trop tot ;
- cette configuration est plus autonome, mais elle peut etre lourde: elle
  interroge Hub'Eau et prepare un DEM regional pour AURA.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/aura_jauge_regional_50_150km2.toml
```

Cette variante est le chemin cible pour remplacer progressivement les fixtures
par une selection observee reelle. Elle interroge toute l'emprise AURA et peut
donc etre longue.

Une variante de controle plus courte est fournie:

```text
configs/aura_jauge_5stations.toml
```

Elle utilise cinq stations Hub'Eau explicites, toujours avec le DEM regional
Geoplateforme. Elle sert a verifier rapidement le chemin reel
stations -> exutoires -> bassins -> rapport HTML, sans utiliser la grille de
fixture `area_only`.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/aura_jauge_5stations.toml
```

## 4. Auvergne-Rhone-Alpes, surface comme critere unique

Fichier:

```text
configs/aura_non_jauge_csv_50_150km2.toml
```

Principe:

- `strategy.profile = "area_only"`; ce profil infere `criteria_crossing` et
  l'axe principal `area` ;
- la surface est le seul critere actif, avec une plage stricte 50-150 km2 ;
- cette plage est ecrite comme une plage nommee `aura_50_150`, avec une borne
  minimale et une borne maximale explicites ;
- les observations et la geologie sont seulement reportees, pas utilisees pour
  retenir ou rejeter les sites ;
- l'entree est un CSV de bassins deja delimites pour isoler la logique de
  selection ;
- les contours de bassins sont fournis comme fixtures pour tester le rendu
  cartographique sans ajouter de reseau hydrographique de fond ;
- le DEM est declare dans `[data.dem]` par region administrative avec la source
  `ign_geoplateforme_dem`, ce qui permet de charger un fond DEM regional sans
  coder manuellement les 12 departements ;
- la fixture `aura_area_50_150_catchments.csv` contient 20 bassins
  reproductibles, non superposes, avec des surfaces reparties entre 52 et
  149 km2 ;
- la carte utilise la meme symbolisation par classes de surface que l'exemple
  Bretagne.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/aura_non_jauge_csv_50_150km2.toml
```

La sortie ecrit notamment:

- `selected_sites.csv` ;
- `rejected_sites.csv` ;
- `regional_lab_sites.csv` ;
- `selected_outlets.geojson` ;
- `rejected_outlets.geojson` ;
- `selected_basins.geojson` ;
- `rejected_basins.geojson` ;
- `criteria_components.jsonl` ;
- `site_selection_decisions.csv` ;
- `site_selection_decisions.jsonl` ;
- `site_selection_evidence.jsonl` si des preuves normalisees existent ;
- `site_selection_manifest.json` ;
- `report_artifact_manifest.json`.

Le rapport HTML est derive du manifest et des artefacts ci-dessus. La forme
privilegiee est le contrat generique, utilise par les exemples publics:

```toml
[report.html]
profile = "site_selection"
build_at_end = true
```

En mode selection executee, il produit alors aussi:

- `review/index.html` ;
- `review/site_selection_map.png`.

Les sorties GIS de production sont disponibles mais desactivees par defaut dans
ces exemples courts. Pour les produire, ajouter dans `[site_selection.output]`:

```toml
write_geopackage = true
write_geoparquet = true
```

Le run ecrit alors `site_selection.gpkg` et les couches GeoParquet separees
pour les exutoires, bassins et points d'observation disponibles.

Les couches d'influence peuvent etre ajoutees sous:

```toml
[[site_selection.criteria.influence.layers]]
name = "Barrages de controle"
path = "data/influence/barrages.gpkg"
influence_type = "major_dam_upstream"
id_field = "id"
label_field = "name"
severity_field = "severity"
major_values = ["major"]
```

Le workflow intersecte ces couches avec les contours de bassins, renseigne les
flags comme `major_dam_upstream`, puis ecrit `influence_evidence.jsonl` et les
couches GIS d'influence si les sorties spatiales correspondantes sont actives.

Les couches de geologie peuvent etre ajoutees sous:

```toml
[[site_selection.criteria.geology.layers]]
name = "Geologie de controle"
path = "data/geology/geology.gpkg"
class_field = "lithology"
id_field = "id"
label_field = "label"
```

Le workflow calcule alors la geologie dominante par bassin, les fractions de
surface par classe et ecrit `geology_evidence.jsonl`. Avec les sorties GIS
actives, il ajoute aussi `geology_basins.geojson`, `geology_basins.parquet` ou
la couche `geology_basins` dans `site_selection.gpkg`.

Les couches de piezometres peuvent etre ajoutees sous:

```toml
[[site_selection.criteria.observations.piezometer_layers]]
name = "Piezometres de controle"
path = "data/piezometry/piezometers.gpkg"
id_field = "bss_id"
label_field = "name"
record_years_field = "record_years"
quality_field = "quality"
```

Les piezometres dans le bassin, ou proches de l'exutoire si
`piezometer_max_distance_km` est configure, sont ajoutes a
`piezometer_evidence.jsonl`, `observation_evidence.jsonl` et
`observation_points.geojson`.

Un mode avance de generation de candidats existe pour les campagnes sans CSV de
bassins et sans stations comme entrees. Contrairement a `dem_area_target`, il ne
cherche pas directement une surface cible: il echantillonne des cellules du
reseau DEM selon les controles de `[site_selection.outlets]`. Il reste teste,
mais il n'est pas dans le contrat metier court terme stabilise:

```toml
[site_selection.input]
mode = "dem_network_sampling"

[site_selection.outlets]
candidate_mode = "network_sampling"
max_generated_candidates = 50
min_distance_between_outlets_km = 2.0
```

Ce mode utilise le raster d'accumulation DEM pour proposer des exutoires,
ecrit `candidate_generation.jsonl`, `candidate_outlets.geojson` et
`generated_dem_network.geojson`, puis lance la meme delimitation/selection que
les autres chemins. L'audit distingue les cellules candidates acceptees et
rejetees, avec la raison du rejet. Si `bdtopage_then_dem` est actif et qu'un
reseau BD Topage/custom est disponible, les candidats portent aussi une distance
et un score au reseau de reference.

La carte HTML de revue lit directement `generated_dem_network.geojson`, ce qui
permet de verifier visuellement la relation entre reseau DEM, exutoires
candidats et contours de bassins.
Commande equivalente au `hmp run`:

```bash
hmp site-selection build-dem-network path/to/config.toml
```

Exemple local avec DEM Bretagne deja present dans `examples/data/dem`:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_non_jauge_dem_reseau_50_500km2.toml
```

Il produit notamment
`outputs/bretagne_non_jauge_dem_reseau_50_500km2_v1/review/index.html`,
`candidate_generation.jsonl` et `generated_dem_network.geojson`.

Les tests unitaires associes utilisent parfois des contours synthetiques pour
aller vite; l'exemple `bretagne_non_jauge_dem_reseau_50_500km2.toml` lance lui une
delimitation DEM reelle sur le DEM local configure.

## 5. Calvados, DEM automatique rapide sur un departement

Fichier:

```text
configs/calvados_non_jauge_dem_10bassins_100km2.toml
```

Principe:

- le territoire est limite au departement du Calvados (`departments = ["014"]`)
  au lieu d'une region complete;
- le DEM est charge par Geoplateforme uniquement pour ce departement;
- le mode `dem_area_target` est le chemin DEM simplifie: il cherche des exutoires
  dont la surface amont est proche de 100 km2, dans la fenetre 75-125 km2;
- `n_basins = 10` limite le nombre de bassins retenus;
- `max_candidates_before_delineation = 30` limite le nombre de candidats DEM
  a delimiter avant le tri final, ce qui rend l'exemple plus rapide;
- les candidats et le reseau DEM exporte sont limites a la geometrie terrestre
  du departement, pas seulement a l'emprise rectangulaire du raster;
- le rapport HTML reste actif pour controler visuellement les exutoires, le
  reseau DEM et les contours de bassins.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/calvados_non_jauge_dem_10bassins_100km2.toml
```

La sortie principale a inspecter est:

```text
examples/projects/17_site_selection_workflow/outputs/calvados_non_jauge_dem_100km2_v1/review/index.html
```

Cet exemple sert a tester rapidement le chemin DEM automatique sur un domaine
reel plus petit que la Normandie. Il ne garantit pas encore une selection
hydrologiquement optimale: il sert surtout a verifier que la generation de
candidats, la delimitation, les rejets et le rapport tournent sans lancer un
cas regional lourd.

## Validation de cloture du chantier `site_selection`

Les exemples courts a rejouer avant cloture sont:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/calvados_non_jauge_dem_10bassins_100km2.toml
hmp run examples/projects/17_site_selection_workflow/configs/finistere_jauge_elorn_dem.toml
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_jauge_7stations.toml
```

Le 2026-05-26, ils produisent les resultats attendus suivants:

| Exemple | Profil effectif | Resultat attendu | HTML a inspecter |
| --- | --- | --- | --- |
| `calvados_non_jauge_dem_10bassins_100km2.toml` | `area_only` | 26 candidats, 10 selectionnes, 16 rejetes | `outputs/calvados_non_jauge_dem_100km2_v1/review/index.html` |
| `finistere_jauge_elorn_dem.toml` | `gauged_downstream_station` | 1 candidat, 1 selectionne avec avertissements, 0 rejete | `outputs/finistere_jauge_elorn_dem_v1/review/index.html` |
| `bretagne_jauge_7stations.toml` | `gauged_downstream_station` | 6 candidats, 6 selectionnes, 0 rejete | `outputs/bretagne_jauge_7stations/review/index.html` |

Pour ces runs, verifier aussi `review/site_selection_map.png`,
`site_selection_manifest.json` et `report_artifact_manifest.json`.
La variante BD Topage ecrit en plus
`reference_network/bdtopage_reference_network.gpkg`; ce fichier reste un
artefact technique de snapping et ne doit pas etre interprete comme couche de
preuve du bassin.

## Regions francaises dans les TOML

Quand `country = "FR"` et `territory.mode = "admin_regions"`, les noms de
regions sont valides explicitement. Utiliser les libelles canoniques suivants:

```text
Auvergne-Rhone-Alpes
Bourgogne-Franche-Comte
Bretagne
Centre-Val-de-Loire
Corse
Grand-Est
Guadeloupe
Guyane
Hauts-de-France
Ile-de-France
La-Reunion
Martinique
Mayotte
Normandie
Nouvelle-Aquitaine
Occitanie
Pays-de-la-Loire
Provence-Alpes-Cote-d-Azur
```

Les alias accents usuels sont normalises, mais les abreviations comme `AURA`,
`PACA` ou `IDF` ne sont pas acceptees dans les TOML de production pour garder
les fichiers explicites.
