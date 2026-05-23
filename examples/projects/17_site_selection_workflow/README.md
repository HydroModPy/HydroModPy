# Exemples `site_selection`

Ce dossier donne quatre configurations courtes pour illustrer deux principes de
selection differents. Certaines lignes CSV sont des fixtures synthetiques pour
tester la mecanique; la variante `50_500_hubeau` materialise au
contraire des sites issus du referentiel Hub'Eau afin de travailler sur un cas
plus proche d'un inventaire reel.

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

- les candidats sont des stations/sites Hub'Eau de Bretagne est materialises
  dans `fixtures/bretagne_hubeau_50_500_candidates.csv` ;
- `build_bretagne_hubeau_50_500_candidates.py` interroge le referentiel
  Hub'Eau, filtre les stations existantes qui respectent les criteres amont
  et ecrit aussi `fixtures/bretagne_hubeau_50_500_station_inventory.csv` ;
- la station de jaugeage reste le point d'entree: elle fixe l'exutoire ;
- la surface 50-500 km2 sert de filtre amont dans l'inventaire Hub'Eau; apres
  recalcul DEM, elle est reportee en avertissement pour conserver tous les
  bassins trouves et visualiser les ecarts possibles entre surfaces de
  reference et surfaces recalculees ;
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

Cette variante sert de support de discussion sur un inventaire reel: le CSV de
candidats contient toutes les stations bretonnes trouvees par le script dans la
gamme 50-500 km2 avec les filtres amont declares, et la carte montre tous les
bassins qui ont ete retenus par le workflow.

Une variante reduite est fournie pour les iterations rapides sur la carte:

```text
configs/bretagne_hydrometry_50_500_small.toml
```

Elle utilise 7 stations situees dans une emprise compacte de Bretagne. Le DEM
reste declare dans `[data.dem]` avec `source = "ign_bdalti"` et
`regions = ["Bretagne"]`: le code garde donc la meme organisation que
l'exemple complet, mais le nombre de delimitations est beaucoup plus faible.
Cette variante sert a verifier rapidement l'organisation du rapport HTML, la
presence de la carte, les symboles des stations et les contours de bassins; elle
ne remplace pas l'exemple complet pour l'analyse regionale.

Commande utile:

```bash
hmp run examples/projects/17_site_selection_workflow/configs/bretagne_hydrometry_50_500_small.toml
```

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
- le DEM reste declare dans `[data.dem]`, avec `regions =
  ["Auvergne-Rhone-Alpes"]`; les 12 departements IGN sont deduits par le
  gestionnaire DEM ;
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
par une selection observee reelle.

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
- les contours de bassins et une hydrographie de contexte sont fournis comme
  fixtures pour tester le rendu cartographique ;
- le DEM est declare dans `[data.dem]` par region administrative
  `Auvergne-Rhone-Alpes`, ce qui permet de charger un fond DEM regional sans
  coder manuellement les 12 departements ;
- `build_aura_area_50_150_candidates.py` genere 20 bassins reproductibles,
  non superposes, avec des surfaces reparties entre 52 et 149 km2 ;
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

Dans cette fixture, les contours de bassins sont volontairement synthetiques:
ils testent la mecanique d'exports et de figures, pas une delimitation reelle.

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
