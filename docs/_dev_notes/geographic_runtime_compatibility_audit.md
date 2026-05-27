# Geographic runtime compatibility audit

Date: 2026-05-27

## Objectif

Ouvrir un lot separe pour la compatibilite runtime geographic, distinct du
nettoyage du contrat TOML `[geographic]`. Le but de ce lot est de classer les
alias et payloads de compatibilite encore presents dans le runtime avant toute
suppression.

Regle du lot: aucune suppression directe sans consommateur audite. Plusieurs
occurrences qualifiees comme alias ou compatibilite sont encore des APIs
runtime consommees par les launchers, binders de domaine/mesh, post-processors,
store ingestion ou tests de contrat.

## Synthese

Etat du premier audit:

- Suppression runtime directe: non appliquee.
- Renommage doc-only applique: references obsoletes a un ancien
  `Geographic`/`geographic.py` remplacees par le runtime actuel
  `CatchmentDelineation`/`catchment_delineation.py`.
- Alias actifs a conserver pour l'instant: `box_buff`,
  `DomainGeographicContext.river_mesh_trace`, les attributs runtime `dem_res`,
  `dem_box_buff_data`, `dem_data`, `depressions_data`, `catch_area`, et les
  derivees `SyntheticGridConfig.dx` / `dy`.
- Alias supprimes dans ce lot: la feature store `river_network` pour le reseau
  hydrographique genere et la cle d'alias du contrat de nommage public. Les
  nouvelles surfaces persistees utilisent `hydrographic_network_generated`.
- Alias internes supprimes ensuite: `RiverNetworkProducts.network_shp` et
  `RiverNetworkProducts.summary_json`. Le bundle technique expose maintenant
  directement `hydrographic_network_generated_shp` et
  `hydrographic_network_generated_summary_json`.

## Classification

### 1. Alias de feature hydrographique generee

Elements:

- `HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME = "hydrographic_network_generated"`.
- `hydrographic_network_naming_contract(...)`.
- Supprimes: la constante et le helper d'alias du reseau genere, ainsi que la
  cle d'alias du contrat de nommage public.

Consommateurs constates:

- `hydromodpy/spatial/geographic/store_ingestion.py` ecrit maintenant seulement
  la feature canonique dans le store.
- `hydromodpy/results/run_hydrographic.py` expose les hints de nommage
  canoniques sans alias.
- `tests/unit/geographic/test_hydrographic_network.py` et
  `tests/unit/simulation/test_simulation_api.py` caracterisent l'absence
  d'alias dans le contrat public.

Decision: supprime pour les nouvelles ecritures et les hints publics. Les
filenames `river_network.shp` et `river_network_summary.json` restent des
artefacts disque etablis, pas des noms de features persistees.

### 2. Chemins de reseau genere

Elements:

- Champs canoniques `GeographicPaths.hydrographic_network_generated_shp` et
  `GeographicPaths.hydrographic_network_generated_summary_json`.
- Attributs runtime `hydrographic_network_generated_shp` et
  `hydrographic_network_generated_summary_json`.
- Champs canoniques equivalents sur `RiverNetworkProducts`.

Consommateurs constates:

- `hydromodpy/spatial/geographic/pipeline.py`.
- `hydromodpy/spatial/geographic/core/domain_geographic_pipeline.py`.
- `hydromodpy/spatial/geographic/catchment_delineation.py`.
- `hydromodpy/spatial/geographic/store_ingestion.py`.
- Cas de reference geographic et river-network.
- Tests golden/regression geographic.

Decision: alias de champs supprime. Les noms de fichiers `river_network.shp` et
`river_network_summary.json` restent des sorties etablies. Les champs et
payloads publics utilisent maintenant `hydrographic_network_generated_*`, y
compris dans `RiverNetworkProducts`.

### 3. `DomainGeographicContext.river_mesh_trace`

Element:

- Champ `river_mesh_trace` dans `DomainGeographicContext`.

Consommateurs constates:

- `hydromodpy/spatial/mesh/runtime_single_run.py` via
  `resolve_river_mesh_trace(...)`.
- Cas mesh `reference_2d_geology_conformal`.
- Tests launchers mesh-catchment, tests mesh et tests geographic.

Decision: vivant. Garder jusqu'a ce que les consommateurs mesh acceptent tous
`GeographicDerivedFeatures` directement et que la projection
`DomainGeographicContext` redevienne strictement domaine.

### 4. `box_buff` et `box_buff_shp`

Elements:

- `GeographicPaths.box_buff`.
- Attribut runtime `CatchmentDelineation.box_buff`.
- Champ `DomainGeographicContext.box_buff_shp`.

Consommateurs constates:

- `structure_binders.py` accepte `box_buff_shp`, puis retombe sur `box_buff`.
- `CatchmentDelineation.get_geographic_derived_features()` garde le meme
  fallback.
- Mesh domain loaders consomment `domain_geographic.box_buff_shp`.
- Tests de contrat geographic verifient explicitement
  `domain_geographic.box_buff_shp == geo.box_buff`.

Decision: vivant. La separation actuelle correspond a deux surfaces:
`box_buff` pour les chemins historiques produits par le runtime complet,
`box_buff_shp` pour la vue domaine.

### 5. Runtime synthetic geographic

Elements:

- `SyntheticGridConfig.dx` / `dy`.
- `SyntheticGeographic.dem_res`, `dx`, `dy`, `resolution`,
  `resolution_x`, `resolution_y`.
- `SyntheticGeographic.surface_topo`, `catch_area`, `dem_box_buff_data`,
  `dem_buff_data`, `dem_data`, `depressions_data`.
- Attributs de chemins et de workspace: `watershed_shp`,
  `watershed_box_buff_dem`, `geographic_path`, `figure_folder`, etc.

Consommateurs constates:

- Topographie synthetic et validation cases lisent `grid.dx` / `grid.dy`.
- Solvers MODFLOW 6/NWT lisent `dem_res`, `dem_box_buff_data`,
  `dem_data`, `depressions_data`.
- Data loader et domain setup lisent `get_domain_surface_topo()`,
  `surface_topo` et le support raster.
- Store ingestion lit `catch_area`, `dem_res`, `dem_box_buff_data` et les
  chemins geographic.
- Tests synthetic/geographic/golden caracterisent ces attributs.

Decision: vivant. Ne pas supprimer. Les commentaires peuvent etre reformules
comme contrat runtime courant plutot que dette legacy.

### 6. References doc-only a `Geographic` / `geographic.py`

Elements:

- `hydromodpy/spatial/geographic/README.md` mentionnait `geographic.py` et une
  classe `Geographic`.
- `hydromodpy/spatial/geographic/geographic_paths.py` mentionnait
  `Geographic.processing()`.

Consommateurs constates:

- Aucun fichier `hydromodpy/spatial/geographic/geographic.py`.
- Aucun `class Geographic` dans `hydromodpy/spatial/geographic`.

Decision: mort doc-only. Renomme vers `catchment_delineation.py`,
`CatchmentDelineation` et `CatchmentDelineation.processing()`.

## Commandes d'audit

```powershell
rg -n "legacy|Legacy|historical|compatibility|compatibilit|alias|deprecated" hydromodpy/spatial/geographic tests/unit/geographic docs/_dev_notes/geographic_config_legacy_cleanup_report.md -g "*.py" -g "*.md"
rg -n "hydrographic_network_naming_contract|HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME" hydromodpy tests docs/_dev_notes -g "*.py" -g "*.md"
rg -n "hydrographic_network_generated_shp|hydrographic_network_generated_summary_json|river_network_shp|river_network_summary_json|network_shp|summary_json" hydromodpy/spatial/geographic hydromodpy/workflow hydromodpy/display tests/unit/geographic tests/regression -g "*.py"
rg -n "\bbox_buff\b|\bbox_buff_shp\b|watershed_box_buff_dem|watershed_box_shp|watershed_shp" hydromodpy/workflow hydromodpy/spatial hydromodpy/display tests/unit/geographic tests/unit/simulation -g "*.py"
rg -n "river_mesh_trace|resolve_river_mesh_trace|DomainGeographicContext|domain_geographic" hydromodpy/workflow hydromodpy/spatial hydromodpy/physics hydromodpy/display tests/unit tests/regression -g "*.py"
rg -n "\.dx\b|\.dy\b|\.dem_res\b|\.resolution\b|\.resolution_x\b|\.resolution_y\b|\.x_pixel\b|\.y_pixel\b|\.geodata\b|\.x_coord\b|\.y_coord\b|\.centroid_long_lat_Greenwich\b|\.out_dir_path\b|\.add_data_folder\b|\.figure_folder\b|\.geographic_path\b|build_georeferencing\(" hydromodpy tests examples validation_cases -g "*.py"
rg -n "class Geographic\b|\bGeographic\b" hydromodpy/spatial/geographic hydromodpy/_lazy.py tests/unit/geographic -g "*.py"
```

## Suite recommandee

1. Migrer les consommateurs mesh vers `GeographicDerivedFeatures` lorsque
   possible, puis reevaluer `DomainGeographicContext.river_mesh_trace`.
2. Repasser un scan cible sur les descriptions `historical` et `compatibility`
   pour ne garder que les mentions contractuelles.
