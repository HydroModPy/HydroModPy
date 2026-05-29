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
- Alias actifs a conserver pour l'instant: `box_buff`, les attributs runtime `dem_res`,
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

Decision initiale: vivant au premier audit. Lot applique ensuite: les
consommateurs mesh ne lisent plus la trace riviere depuis
`DomainGeographicContext`; ils recoivent maintenant une `river_trace` explicite
ou le bundle canonique `GeographicDerivedFeatures`.

Decision courante: alias supprime de `DomainGeographicContext`. La trace reste
portee par `GeographicDerivedFeatures.rivers.river_mesh_trace`.

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

1. Relancer un build Sphinx ou la generation PlantUML si les SVG derives des
   sources `.wsd` doivent etre rafraichis dans le meme lot.

## Lot applique: suppression `DomainGeographicContext.river_mesh_trace`

Date: 2026-05-27

Objectif: retirer l'alias qui faisait porter un produit hydrographique/mesh par
la vue domaine `DomainGeographicContext`.

Changements:

- `DomainGeographicContext` ne declare plus `river_mesh_trace`.
- `GeographicDerivedFeatures.to_domain_geographic_context()` ne projette plus
  la trace riviere vers la vue domaine.
- `GeographicDerivedFeatures.from_domain_geographic_context()` reconstruit un
  bundle sans produits riviere quand la seule entree disponible est la vue
  domaine.
- `resolve_river_mesh_trace(...)` ne lit plus que
  `GeographicDerivedFeatures.rivers.river_mesh_trace`.
- Le runtime `mesh_catchment` transmet maintenant `geographic_features` au cas
  conformal en plus de la `river_trace` deja resolue.
- Le cas `reference_2d_geology_conformal` resout la trace riviere depuis
  `geographic_features` ou depuis une `river_trace` explicite, plus depuis
  `domain_geographic`.
- La source config in-memory des rivieres est renommee de
  `domain_geographic` vers `geographic_features`; `file` reste l'autre mode
  supporte.

Validation:

- `python -m pytest tests/unit/geographic/test_domain_geographic_pipeline.py
  tests/unit/launchers/test_mesh_catchment_config.py
  tests/unit/mesh/gmsh_grid/test_reference_2d_geology_conformal_case.py
  tests/unit/launchers/test_mesh_catchment_launcher.py
  tests/unit/launchers/test_launcher_run_id.py
  tests/unit/simulation/test_boussinesq_flow_adapter.py -q -o addopts=""`:
  97 passed.
- `python -m ruff check ...` sur les fichiers source/tests touches: OK.
- `python -m tools.doc_config`: 49 fichiers config/docs regeneres, dont
  `mesh_catchment.rst`, `hydromodpy-schema.json`,
  `hydromodpy-openapi.json` et `hmp-config-search.json`.
- `python -m pytest tests/unit/test_docs_config_consistency.py
  tests/unit/config/test_schema_export.py
  tests/unit/cli/test_dev_config_command.py -q -o addopts=""`: 37 passed.
- `git diff --check`: pas d'erreur de whitespace; seulement les avertissements
  CRLF deja emis par Git sur le workspace Windows.

Scan de controle:

```powershell
git grep -n 'domain_geographic.*river_mesh_trace\|river_mesh_trace.*domain_geographic\|source = "domain_geographic"\|source="domain_geographic"\|rivers.source == "domain_geographic"' -- hydromodpy/spatial hydromodpy/solver tests/unit
```

Resultat attendu: aucune dependance fonctionnelle restante; les seules
occurrences `domain_geographic` encore presentes cote mesh concernent le support
de domaine (`watershed_shp`, `box_buff_shp`, `surface_topo`, figures, bundle).

## Lot applique: retrait de `CatchmentDelineation.river_mesh_trace`

Date: 2026-05-28

Objectif: eviter une seconde surface runtime pour la trace riviere apres le
retrait de `DomainGeographicContext.river_mesh_trace`.

Changements:

- `GeographicRuntimeArtifacts.runtime_attributes()` n'expose plus
  `river_mesh_trace` comme attribut direct du runtime geographic.
- `SyntheticGeographic` n'hydrate plus `river_mesh_trace = None`.
- `CatchmentDelineation.get_geographic_derived_features()` continue de lire le
  bundle technique `_river_network_products` quand il existe. Son fallback ne
  reconstruit plus une trace depuis un attribut public legacy; il expose
  seulement les chemins de reseau generes disponibles.

Decision: `_river_network_products` reste conserve comme detail technique
interne d'hydratation vers `GeographicDerivedFeatures.rivers`. La surface
canonique cross-layer reste `GeographicDerivedFeatures.rivers.river_mesh_trace`.

Validation:

- Scan cible sur `self.river_mesh_trace`, l'attribut runtime
  `"river_mesh_trace"` et `getattr(self, "river_mesh_trace", ...)`: aucun
  resultat dans `hydromodpy` et `tests`.
- `python -m pytest tests/unit/geographic/test_domain_geographic_pipeline.py
  tests/unit/geographic/test_catchment_delineation_contract.py
  tests/unit/geographic/test_hydrographic_network.py
  tests/unit/geographic/test_river_network_products.py
  tests/unit/geographic_synthethic/test_synthetic_geographic.py -q -o
  addopts=""`: 28 passed.
- `python -m pytest tests/unit/mesh/gmsh_grid/test_reference_2d_geology_conformal_case.py
  tests/unit/launchers/test_mesh_catchment_config.py
  tests/unit/launchers/test_mesh_catchment_launcher.py
  tests/unit/launchers/test_launcher_run_id.py
  tests/unit/simulation/test_boussinesq_flow_adapter.py -q -o addopts=""`:
  93 passed.
- `python -m ruff check ...` sur les fichiers source/tests touches: OK.

## Scan final `historical` / `compatibility` / `legacy`

Date: 2026-05-28

Commande:

```powershell
rg -n "historical|compatibility|compatibilit|legacy|deprecated|alias" hydromodpy/spatial/geographic hydromodpy/spatial/mesh docs/source/architecture -g "*.py" -g "*.rst" -g "*.md" -g "*.wsd"
```

Corrections appliquees:

- Retrait des mentions d'alias persiste `river_network` dans les notes
  d'architecture hydrographique. Le store n'ecrit plus que
  `hydrographic_network_generated`; `river_network.shp` et
  `river_network_summary.json` restent seulement des noms de fichiers.
- Mise a jour des diagrammes sequence/persistence hydrographiques pour retirer
  l'ecriture de l'alias `river_network`.
- Rewording de `DomainGeographicContext` comme vue domaine courante plutot que
  payload de compatibilite historique.

Resultat apres correction: les occurrences restantes sont contractuelles ou hors
scope de cette suppression:

- noms de fichiers historiques conserves (`river_network.shp`,
  `river_network_summary.json`, rasters/domain rasters);
- aliases documentes et encore actifs (`SyntheticGridConfig.dx` / `dy`,
  `CellType` text aliases, unit aliases, aliases cartesian-grid);
- compatibilites d'autres sous-systemes (`modflow_nwt`, simulation time,
  solver compatibility, result catalog migration);
- docs de politique generale qui expliquent comment traiter les shims et
  aliases.

Scan anti-regression specifique:

```powershell
git grep -n 'legacy generated-feature alias\|legacy alias river_network\|+ legacy alias river_network\|mirrored under the legacy alias\|source = "domain_geographic"\|DomainGeographicContext.river_mesh_trace' -- hydromodpy tests docs ':!docs/source/_static/**'
```

Resultat: seules les entrees historiques du present rapport mentionnent encore
`DomainGeographicContext.river_mesh_trace`.
