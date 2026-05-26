# Exemples `site_selection`

Ce dossier donne plusieurs configurations courtes pour illustrer deux principes
de selection differents. Certaines lignes CSV sont des fixtures synthetiques
pour tester la mecanique; les variantes hydrometriques materialisent au
contraire des sites issus du referentiel Hub'Eau afin de travailler sur des cas
plus proches d'un inventaire reel.

## 1. Bretagne, stations hydrometriques comme entree principale

Fichier:

```text
configs/bretagne_hydrometry_primary.toml
```

Principe:

- `strategy.principle = "observation_led"` ;
- les stations de debit sont le critere d'entree principal ;
- les controles de non-influence, de surface et de geologie viennent ensuite ;
- l'exemple part d'un CSV d'exutoires et de stations pre-normalisees ;
- le DEM est declare dans `[data.dem]` avec la source `ign_bdalti`, puis mis en
  cache hors du depot dans l'espace de donnees HydroModPy
  (`HYDROMODPY_WORKSPACE/data` si defini, sinon `~/hydromodpy/data`) ;
- la region `Bretagne` est declaree dans `[data.dem]`; le gestionnaire DEM
  resout les departements IGN correspondants sans les ecrire a la main ;
- `site_selection.dem.request_extent = "outlets"` garde un DEM limite pour la
  delimitation hydrologique ;
- `site_selection.dem.map_background_extent = "territory"` charge en plus un
  DEM regional pour la carte de revue, afin que la figure soit a l'echelle de
  la Bretagne ;
- les contours de bassins sont recalcules depuis les exutoires avec le DEM
  charge par `[data.dem]`, puis exportes dans
  `outputs/bretagne_hydrometry_primary_v1/catchments/.../watershed.shp` ;
- le snap d'exutoire reste en mode direct `dem_accumulation`, avec
  `snap_dist_m = 150` pour limiter les deplacements aval ;
- si l'on veut aller chercher de vraies stations Hub'Eau, il faut passer
  `site_selection.input.mode` a `hydrometry`; le chargement utilise alors les
  gestionnaires de donnees HydroModPy existants.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_primary.toml
```

Cette commande produit notamment:

- `selected_sites.csv` ;
- `rejected_sites.csv` ;
- `selected_basins.geojson`, construit depuis les `watershed.shp` calcules ;
- `rejected_basins.geojson`, construit depuis les `watershed.shp` calcules ;
- `observation_evidence.jsonl` ;
- `observation_points.geojson` ;
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
configs/bretagne_hydrometry_50_500_hubeau_preview.toml
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
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_hubeau_preview.toml
```

Cette variante sert de support de discussion sur un inventaire reel charge par
le workflow generique. Les variantes reduites ci-dessous utilisent le meme
chargement Hub'Eau, mais limitent le nombre de stations telechargees avec
`max_stations`.

Une variante reduite est fournie pour les iterations rapides sur la carte:

```text
configs/bretagne_hydrometry_50_500_small.toml
```

Elle charge 7 stations Hub'Eau explicites, situees dans une emprise compacte
de Bretagne, via `station_ids`; `max_stations = 7` garde la preview bornee. Le
DEM reste declare dans `[data.dem]` avec `source = "ign_geoplateforme_dem"`,
`dataset = "bd-alti"` et `regions = ["Bretagne"]`: le code passe donc par le
client Geoplateforme dynamique. Comme `site_selection.dem.request_extent =
"outlets"`, le workflow charge les stations avant le DEM et limite le DEM de
calcul a l'enveloppe des stations, plus la marge configuree.
Cette variante sert a verifier rapidement l'organisation du rapport HTML, la
presence de la carte, les symboles des stations et les contours de bassins; elle
ne remplace pas l'exemple complet pour l'analyse regionale.
Elle utilise le snap direct `dem_accumulation` avec un rayon court de 150 m.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_small.toml
```

Une variante equivalente contraint d'abord les exutoires par BD Topage, puis
lance le snap DEM local avec le meme rayon de 150 m:

```text
configs/bretagne_hydrometry_50_500_small_bdtopage.toml
```

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_small_bdtopage.toml
```

Elle produit en plus `outputs/bretagne_hydrometry_50_500_small_bdtopage_v1/reference_network/bdtopage_reference_network.gpkg`.
Ce GeoPackage est un artefact technique de snapping: il n'est pas ajoute comme
couche de fond au rapport HTML, afin de ne pas confondre reseau de reference et
bassins effectivement selectionnes.

## 3. Auvergne-Rhone-Alpes, stations hydrometriques autonomes

Fichier:

```text
configs/auvergne_rhone_alpes_hydrometry_50_150.toml
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
hmp run examples/projects/17_site_selection_workflow/configs/auvergne_rhone_alpes_hydrometry_50_150.toml
```

Cette variante est le chemin cible pour remplacer progressivement les fixtures
par une selection observee reelle. Elle interroge toute l'emprise AURA et peut
donc etre longue.

Une variante de controle plus courte est fournie:

```text
configs/auvergne_rhone_alpes_hydrometry_preview.toml
```

Elle utilise cinq stations Hub'Eau explicites, toujours avec le DEM regional
Geoplateforme. Elle sert a verifier rapidement le chemin reel
stations -> exutoires -> bassins -> rapport HTML, sans utiliser la grille de
fixture `area_only`.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/auvergne_rhone_alpes_hydrometry_preview.toml
```

## 4. Auvergne-Rhone-Alpes, surface comme critere unique

Fichier:

```text
configs/auvergne_rhone_alpes_area_only.toml
```

Principe:

- `strategy.principle = "criteria_crossing"` ;
- `strategy.profile = "area_only"` ;
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
hmp run examples/projects/17_site_selection_workflow/configs/auvergne_rhone_alpes_area_only.toml
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
- `selection_decisions.jsonl` ;
- `site_selection_manifest.json`.

Le rapport HTML est derive du manifest et des artefacts ci-dessus. Il est active
explicitement dans ces exemples avec:

```toml
[site_selection.output]
write_report_html = true
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

Un mode autonome de generation de candidats existe pour les campagnes sans CSV
de bassins et sans stations comme entrees:

```toml
[site_selection.input]
mode = "generated_candidates"

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
hmp site-selection build-generated path/to/config.toml
```

Exemple local avec DEM Bretagne deja present dans `examples/data/dem`:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_generated_candidates_dem.toml
```

Il produit notamment
`outputs/bretagne_generated_candidates_dem_v1/review/index.html`,
`candidate_generation.jsonl` et `generated_dem_network.geojson`.

Les tests unitaires associes utilisent parfois des contours synthetiques pour
aller vite; l'exemple `bretagne_generated_candidates_dem.toml` lance lui une
delimitation DEM reelle sur le DEM local configure.

## 5. Calvados, DEM automatique rapide sur un departement

Fichier:

```text
configs/calvados_dem_area_light_100km2_fast.toml
```

Principe:

- le territoire est limite au departement du Calvados (`departments = ["014"]`)
  au lieu d'une region complete;
- le DEM est charge par Geoplateforme uniquement pour ce departement;
- le mode `dem_area_light` cherche des exutoires dont la surface amont est
  proche de 100 km2, dans la fenetre 75-125 km2;
- `n_basins = 10` limite le nombre de bassins retenus;
- `max_candidates_before_delineation = 30` limite le nombre de candidats DEM
  a delimiter avant le tri final, ce qui rend l'exemple plus rapide;
- les candidats et le reseau DEM exporte sont limites a la geometrie terrestre
  du departement, pas seulement a l'emprise rectangulaire du raster;
- le rapport HTML reste actif pour controler visuellement les exutoires, le
  reseau DEM et les contours de bassins.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/calvados_dem_area_light_100km2_fast.toml
```

La sortie principale a inspecter est:

```text
examples/projects/17_site_selection_workflow/outputs/calvados_dem_area_light_100km2_fast_v1/review/index.html
```

Cet exemple sert a tester rapidement le chemin DEM automatique sur un domaine
reel plus petit que la Normandie. Il ne garantit pas encore une selection
hydrologiquement optimale: il sert surtout a verifier que la generation de
candidats, la delimitation, les rejets et le rapport tournent sans lancer un
cas regional lourd.

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
