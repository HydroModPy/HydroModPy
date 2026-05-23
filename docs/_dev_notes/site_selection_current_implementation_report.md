# Rapport d'implementation actuel - `site_selection`

Date: 2026-05-23

Ce document decrit l'etat actuel du developpement `site_selection`. Il complete
le plan long `site_selection_tool_implementation_plan.md`, qui reste un document
de strategie et de jalons.

## Synthese au 2026-05-23

Ce qui est developpe et cable:

- workflow amont `site_selection` distinct de `regional_lab`, avec planification,
  selection depuis CSV pre-delimite, selection depuis observations
  hydrometriques et dispatch par `hmp run`;
- primitives spatiales dediees pour candidats, delimitation par point,
  criteres auditables, selection/rejet, exports tabulaires et GeoJSON;
- manifest officiel `site_selection_manifest.json`, validation des artefacts,
  rapport HTML derive du manifest et carte PNG statique de revue;
- integration des gestionnaires de donnees existants pour l'hydrometrie et le
  DEM, sans duplication des clients Hub'Eau ou IGN dans les primitives
  spatiales;
- exemples Bretagne et Auvergne-Rhone-Alpes avec fixtures legeres, sorties de
  revue et configurations TOML maintenues;
- support des regions administratives francaises pour resoudre les
  departements IGN attendus quand `[data.dem]` declare une region.

Ce qui reste a developper ou consolider:

- generation autonome de candidats depuis le DEM et les reseaux, sans CSV
  pre-delimite ni stations comme seuls exutoires;
- calcul automatique des flags d'influence depuis des couches regionales
  chargees par le workflow;
- croisement spatial geologique avec une source BRGM/regionalisee et une
  typologie configurable;
- croisement spatial automatique des piezometres depuis les donnees chargees par
  les gestionnaires;
- sortie polygonale robuste de production (`GeoParquet` ou `GeoPackage`) en
  complement du GeoJSON de revue;
- carte interactive, seulement apres stabilisation des sorties polygonales et
  des couches d'observation;
- remise au vert de la validation locale dans le workspace courant: voir la
  section "Verification actuelle" pour les blocages observes.

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
- `flow_products_adapter.py`: adaptation vers les produits hydrologiques DEM
  existants.
- `delineation.py`: adaptation vers la delimitation existante par point.
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
  selection depuis hydrometrie, resolution du DEM regional et dispatch interne.
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

Les sorties GeoParquet, catalogue de candidats et rapport Markdown sont gardees
desactivees par defaut tant que leurs writers ne sont pas implementes.

Les GeoJSON d'exutoires sont des points. Les GeoJSON de bassins contiennent les
contours quand `watershed_shp` existe et peut etre lu. Si un contour est absent,
le fichier reste ecrit et le bassin est liste dans `hydromodpy_skipped_basins`.

Quand `site_selection.input.delineate_from_outlets = true`, les contours peuvent
etre recalcules depuis les exutoires. Le DEM n'est alors pas une responsabilite
de `site_selection`: il est soit fourni par `site_selection.dem.path` pour les
cas simples, soit declare proprement sous `[data.dem]` et charge/cache par les
gestionnaires de donnees. Le manifest conserve le chemin du DEM effectivement
utilise dans `flow_products.dem_path`.

Quand `site_selection.input.mode = "hydrometry"`, le meme principe est
applique sans CSV de candidats: le workflow charge les stations via les
gestionnaires de donnees, resout le DEM via `[data.dem]`, construit les produits
hydrologiques, puis delimite les bassins depuis les stations. Pour la France,
l'emprise administrative est transformee en WGS84 pour les requetes Hub'Eau, et
les stations Hub'Eau sont converties en Lambert-93 avant delimitation. Quand
Hub'Eau fournit `x_l93` et `y_l93`, ces coordonnees officielles sont utilisees
directement.

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
sont maintenant colores par classes de surface, pour que la carte reste lisible
quand plusieurs bassins sont compares sur la meme region. Les stations
hydrometriques sont symbolisees par de petits triangles bleus; quand l'exutoire
retenu est la station hydro, le point d'exutoire n'est pas redessine par-dessus.

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

`selected_sites.csv` et `regional_lab_sites.csv` partagent un schema documente:

```text
site_id, site_label, region_id, source_selection_id, site_status, maturity,
x, y, x_outlet, y_outlet, area_km2, tags, enabled
```

Les criteres auditables couvrent maintenant:

- `area`: surface en mode rejet dur, score, stratification, warning ou report ;
- `flow_station`: duree d'observation, distance station-exutoire, station dans
  ou a l'exutoire ;
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
  `observation_led` applique a un inventaire Hub'Eau Bretagne 50-500 km2. Le
  script `build_bretagne_hubeau_50_500_candidates.py` ecrit 54 candidats et le
  workflow regenere 54 contours depuis les exutoires sur DEM IGN BD ALTI.
- `configs/bretagne_hydrometry_50_500_small.toml`: meme principe, mais avec 7
  stations dans une emprise compacte. Cette variante reduit le temps
  d'execution pour travailler la carte et le rapport HTML sans lancer les 54
  delimitations de l'inventaire complet.
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
- Les controles d'influence sont auditables a partir de flags deja presents,
  mais pas encore calcules automatiquement depuis des couches barrage ou
  prelevement.
- La geologie est auditable quand une classe geologique est fournie, mais le
  croisement spatial avec une base BRGM/regionalisee reste a implementer.
- La piezometrie est maintenant auditable comme critere simple, mais le
  croisement spatial automatique avec les chroniques piezometriques reste a
  implementer.
- Le DEM-only complet pour generer des candidats sans CSV pre-delimite n'est pas
  encore complet. Le chemin station-led sans CSV est maintenant cable, mais son
  execution reelle peut etre lourde sur une grande region comme AURA car elle
  depend du chargement Hub'Eau et du DEM regional.
- Les sorties GeoParquet et Markdown restent des jalons futurs.

## Verification actuelle

### Cas tests developpes

Les tests `tests/unit/site_selection` sont organises par niveau de contrat:

| Fichier | Ce qui est teste | Ce qu'il faut en attendre |
| --- | --- | --- |
| `test_config.py` | validation TOML/Pydantic, profils `area_only` et `observation_led`, regions FR | les configurations invalides sont rejetees tot avec des erreurs explicites |
| `test_candidate_outlets.py` | construction et reprojection des exutoires candidats depuis stations/CSV, espacement minimal | les candidats gardent les metadonnees de station et les doublons proches sont filtres |
| `test_criteria.py` | surface, station hydro, piezometrie, influence, geologie | chaque critere produit un composant auditable, avec score, flags et rejet dur si configure |
| `test_selection.py` | decision finale, recouvrement entre bassins, echecs de delimitation | les bassins retenus/rejetes sont stables et explicables |
| `test_filters.py` | calcul du recouvrement spatial | le filtre de recouvrement utilise le denominateur attendu |
| `test_exports.py` | CSV, JSONL, GeoJSON, schema `selected_sites.csv` | les artefacts d'audit et les exports GIS gardent leurs colonnes/cles stables |
| `test_manifest_report.py` | manifest officiel, validation d'artefacts, HTML et PNG | le rapport reste derive du manifest et detecte les artefacts invalides |
| `test_synthetic_spatial_review.py` | scenario spatial synthetique complet | la chaine ecrit bassins, observations, carte PNG et HTML de revue |
| `test_workflow_plan.py` | planification, CSV pre-delimites, plan-only, resolution DEM | les commandes workflow ecrivent les sorties attendues sans lancer de solveur |
| `test_build.py` | build station-led depuis `PointRecord`, delimitation, exports | la chaine observations -> exutoires -> bassins -> selection fonctionne sur fixtures |
| `test_data_layers.py` | adaptateur hydrometrie et racine de donnees par defaut | `site_selection` passe par les data managers et respecte `HYDROMODPY_WORKSPACE` |
| `test_delineation.py` | delegation a la delimitation existante et gestion d'erreur | les echecs de delimitation deviennent des candidats rejetes auditables |
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

Commande cible dans un environnement complet, avec `pytest-xdist` disponible
car `pytest.ini` configure `--dist=loadgroup`:

```bash
python -m pytest -q tests/unit/site_selection
```

Si `pytest-xdist` n'est pas installe, neutraliser les `addopts` du `pytest.ini`:

```bash
python -m pytest -q -o addopts= tests/unit/site_selection
```

Pour tester seulement le coeur fonctionnel dans le workspace courant, en
contournant le test de dispatch qui pointe encore vers un ancien module:

```bash
python -m pytest -q -o addopts= tests/unit/site_selection --ignore=tests/unit/site_selection/test_workflow_dispatch.py
```

Resultat observe le 2026-05-23:

```text
76 passed
```

Pour les tests de donnees associes au DEM et aux regions francaises:

```bash
python -m pytest -q -o addopts= tests/unit/data_managers/test_dem_manager.py tests/unit/data_managers/test_geoplateforme_dem_downloader.py tests/unit/data_managers/test_france_administrative_regions.py
```

Resultat observe le 2026-05-23 dans ce workspace:

```text
12 passed, 2 failed
```

Les 2 echecs viennent de `test_dem_manager.py`: les tests instancient encore
`DemSourceConfig(...)`, qui est maintenant une union annotee/discriminee et non
un modele instanciable directement. La correction attendue est de passer par la
validation de `DemConfig` avec des dictionnaires de sources, ou d'instancier
`IgnBdaltiDemSource` directement.

### Blocages de validation observes

Etat local au 2026-05-23:

- `python -m pytest -q tests/unit/site_selection` echoue avant collecte si
  `pytest-xdist` n'est pas installe, a cause de l'option
  `--dist=loadgroup`;
- `test_workflow_dispatch.py` importe `hydromodpy.workflow_dispatch`, module
  qui n'existe plus dans le paquet actuel; le test doit etre aligne sur
  `hydromodpy.workflow.dispatch` ou sur `hydromodpy.project.dispatch.workflow`;
- plusieurs fichiers du workspace sont en conflit Git (`UU`). Ces conflits ne
  doivent pas etre confondus avec une limite fonctionnelle de `site_selection`,
  mais ils peuvent bloquer une verification complete du depot.

Commandes de verification a relancer apres correction de ces points:

```bash
python -m ruff check hydromodpy/spatial/site_selection hydromodpy/workflow/site_selection.py hydromodpy/workflow/site_selection_data.py hydromodpy/cli/commands/site_selection.py tests/unit/site_selection
python -m pytest -q tests/unit/site_selection tests/unit/data_managers/test_dem_manager.py tests/unit/data_managers/test_geoplateforme_dem_downloader.py tests/unit/data_managers/test_france_administrative_regions.py tests/unit/launchers/test_hmp_simulation_cli.py tests/integration/test_cli_subcommands.py
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

1. Remettre au vert la suite de validation locale: pre-requis `pytest-xdist`,
   import de dispatch `site_selection`, tests DEM alignes sur l'union
   discriminee des sources.
2. Brancher le calcul automatique des flags d'influence depuis des couches
   regionales clairement chargees par le workflow, pas par les primitives
   spatiales.
3. Ajouter le croisement geologique spatial avec une source explicite et une
   strategie de typologie configurable.
4. Brancher le croisement spatial automatique des piezometres depuis les couches
   chargees par le workflow.
5. Introduire une sortie polygonale plus robuste (`GeoParquet` ou `GeoPackage`)
   en complement du GeoJSON de revue.
6. Ajouter une carte interactive seulement apres stabilisation de la sortie
   polygonale et des couches d'observation.

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
