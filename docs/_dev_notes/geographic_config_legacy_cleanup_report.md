# Geographic config legacy cleanup report

Date: 2026-05-27

## Objectif

Retirer le format historique ou les champs de bassin etaient poses
directement sous `[geographic]`:

```toml
[geographic]
catch_def = "from_outlet_coord"
dem_init_path = "dem.tif"
x_outlet = 1.0
y_outlet = 2.0
```

Le format canonique est maintenant explicite:

```toml
[geographic]

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "dem.tif"
x_outlet = 1.0
y_outlet = 2.0
```

## Changements appliques

- Migration des TOML sources et fixtures vers `[geographic.catchment]`.
- Migration des overlays imbriques:
  `testbed.variant.overlay.geographic.catchment`,
  `testbed.variant_from_catalog.overlay.geographic.catchment` et
  `comparison.base_simulation_overlay.geographic.catchment`.
- Migration des directives de merge/delete portant sur les champs de bassin
  vers le meme niveau `catchment`.
- Suppression du helper transitoire `normalize_geographic_catchment_payload()`
  et des listes de cles legacy associees.
- `hydromodpy/config/toml_section_loader.py` ne resout plus que le payload
  imbrique `catchment`.
- Les payloads plats sont maintenant rejetes par `GeographicConfig`.
- Les lecteurs bruts de TOML qui consommaient encore directement
  `geographic.x_outlet` / `geographic.y_outlet` lisent maintenant
  `geographic.catchment`.
- Les descriptions de champs TOML savent resoudre les champs des unions
  imbriquees, dont `[geographic.catchment]`.
- Les snippets de documentation utilisateur qui montraient encore les champs
  de bassin sous `[geographic]` ont ete migres.

## Controles

- Scan section-aware des 430 TOML suivis par Git: 0 cle de bassin active sous
  `[geographic]` ou sous un overlay `*.geographic`.
- Deux sorties d'exemple non suivies sous
  `examples/projects/18_site_selection_to_testbed/outputs/.../_generated_configs`
  ont aussi ete migrees localement vers `[geographic.catchment]`.
- Recherche du helper de compatibilite:
  `normalize_geographic_catchment_payload`,
  `_LEGACY_FLAT_KEYS`, `_remap_legacy_flat_payload`,
  `delegates_geographic_payload_normalization`: aucune occurrence dans le code
  source et les tests.
- Recherche des acces directs aux anciennes cles plates via
  `geographic.get(...)`: aucune occurrence Python sous `hydromodpy`, `tests`,
  `examples`, `tools` et `validation_cases`.

## Validation

Commandes executees:

```powershell
python -m ruff check hydromodpy/spatial/geographic/geographic_config.py hydromodpy/config/toml_section_loader.py hydromodpy/core/toml_io/descriptions.py hydromodpy/calibration/reporting/network_transient_html.py hydromodpy/display/catchment_report/context.py examples/projects/10_testbed_workflow/generate_nwt_flux_testbed_web_report.py tests/unit/geographic/test_geographic_config.py tests/unit/config/test_toml_loader.py tests/unit/launchers/test_testbed_launcher.py tests/unit/launchers/test_comparison_launcher.py tests/unit/launchers/test_site_selection_bridge_examples.py tests/unit/calibration/test_network_transient_html_sections_behavior.py
python -m pytest tests/unit/geographic/test_geographic_config.py tests/unit/config/test_toml_loader.py tests/unit/launchers/test_data_overview_config.py tests/unit/launchers/test_testbed_launcher.py tests/unit/launchers/test_comparison_launcher.py tests/unit/launchers/test_site_selection_bridge_examples.py tests/unit/calibration/test_network_transient_html_helpers.py tests/unit/calibration/test_network_transient_html_sections_behavior.py -q
python -m pytest tests/unit/geographic/test_geographic_cache.py tests/unit/geographic/test_domain_geographic_pipeline.py tests/unit/geographic/test_catchment_delineation_contract.py tests/unit/geographic/test_reference_river_network_nancon_case.py tests/unit/geographic/test_run_geographic_case_golden.py tests/unit/geographic/test_run_geographic_dem_processing_golden.py tests/unit/geographic/test_run_geographic_river_network_golden.py -q
python -m pytest tests/unit/solver/modflow_nwt/test_modflow_config.py -q
python -m pytest tests/unit/launchers/test_mesh_catchment_launcher.py -q
```

Resultats:

- `99 passed, 1 skipped` sur les tests config/launchers/calibration cibles;
- `17 passed` sur les tests geographic cibles;
- `10 passed` sur les tests modflow config;
- `21 passed` sur les tests mesh catchment launcher;
- `19 passed` sur `tests/unit/config/test_toml_loader.py` apres renommage des
  tests qui mentionnaient encore la normalisation TOML;
- `ruff`: aucun probleme.

## Documentation generee locale

`docs/_build` et `docs/build` ne sont pas suivis par Git. Un build Sphinx HTML
complet a ete tente pour rafraichir les pages locales, mais il n'a pas termine
dans le timeout local de 15 minutes. Les pages HTML locales concernees et leurs
`_sources` ont donc ete rafraichies mecaniquement pour retirer les anciens
libelles qui associaient directement les champs de bassin a `[geographic]`
dans les artefacts non suivis.

## Etat

Le chantier `[geographic]` plat est clos cote contrat de configuration: les
fichiers suivis utilisent le format imbrique, le loader ne remappe plus
silencieusement, et le modele refuse les payloads plats.

## Proposition appliquee

Supprimer ou renommer les derniers artefacts explicitement marques `legacy`
dans la zone geographic/catchment quand ils ne servent plus a caracteriser un
contrat encore utile, puis faire un scan global docs/outils pour les references
historiques qui ne sont plus des notes de developpement.

## Lot suivant applique: renommage des tests de contrat CatchmentDelineation

- Le fichier de tests de caracterisation historique de `CatchmentDelineation`
  est renomme en `tests/unit/geographic/test_catchment_delineation_contract.py`.
- Les golden files associes sont renommes vers
  `catchment_delineation_*_contract_golden.json`.
- Les helpers et tests internes ne portent plus le vocabulaire `legacy`; ils
  documentent maintenant un contrat runtime encore actif.
- `hydromodpy/spatial/geographic/cases/update_geographic_goldens.py` pointe sur
  le nouveau fichier de tests.
- Les descriptions/commentaires qui parlaient de "legacy behavior" pour
  `buff_area`, les metadonnees DEM et les produits raster ont ete reformules
  autour du contrat courant.

Controles executes:

```powershell
rg -n "test_geographic_legacy_characterization|geographic_legacy_characterization|_build_geographic_legacy|_legacy_signature|test_geographic_legacy" hydromodpy tests docs -g "*.py" -g "*.md" --glob "!docs/_dev_notes/geographic_config_legacy_cleanup_report.md"
rg -n "Numeric values keep legacy behavior|legacy percentage-based|legacy Geographic|legacy runtime attributes|legacy raster-products|legacy rasters|legacy behavior when an ``AREA``|legacy ``AREA``" hydromodpy tests examples validation_cases docs -g "*.py" -g "*.toml" -g "*.md" --glob "!docs/_dev_notes/geographic_config_legacy_cleanup_report.md"
python -m ruff check hydromodpy/spatial/geographic/geographic_config.py hydromodpy/spatial/geographic/core/catchment_domain.py hydromodpy/spatial/geographic/core/catchment_metrics.py hydromodpy/spatial/geographic/dem_metadata.py hydromodpy/spatial/geographic/domain_rasters.py hydromodpy/spatial/geographic/pipeline.py tests/unit/geographic/test_catchment_delineation_contract.py hydromodpy/spatial/geographic/cases/update_geographic_goldens.py
python -m pytest tests/unit/geographic/test_catchment_delineation_contract.py tests/unit/geographic/test_geographic_config.py tests/unit/geographic/test_geographic_cache.py -q
```

Resultats:

- les deux scans cibles ne retournent plus d'occurrence active;
- `ruff`: aucun probleme;
- `15 passed` sur les tests geographic cibles.

## Proposition appliquee

Auditer `hydromodpy/spatial/geographic/README.md`,
`structure_binders.py`, `synthetic/*` et `core/hydrographic_network.py`: ces
occurrences `legacy` correspondent encore a des APIs de compatibilite reelles.
La prochaine etape doit decider ce qui reste contractuel, puis renommer les
descriptions ou supprimer les alias quand ils ne sont plus consommes.

Audit detaille ouvert dans
`docs/_dev_notes/geographic_runtime_compatibility_audit.md`.

## Lot suivant applique: vocabulaire geographic et transition hydrographic

- Le vocabulaire de feature historique a ete retire du contrat hydrographique.
- Une etape transitoire a d'abord renomme l'ancien nom de feature en alias de
  compatibilite avant sa suppression complete dans le lot suivant.
- L'ingestion du store ecrit maintenant seulement le nom canonique
  `hydrographic_network_generated`.
- Les docstrings/commentaires de `README.md`, `structure_binders.py`,
  `synthetic/*`, `flow_products.py` et `river_network.py` decrivent le contrat
  courant sans vocabulaire `legacy`.
- Le commentaire du cas `run_geographic_config.toml` ne reference plus
  `examples_legacy`.

Controles executes:

```powershell
rg -n "legacy|Legacy|examples_legacy" hydromodpy/spatial/geographic tests/unit/geographic -g "*.py" -g "*.toml" -g "*.md"
rg -n "legacy_feature_name|legacy_feature_name_for_role|HYDROGRAPHIC_NETWORK_GENERATED_LEGACY_FEATURE_NAME|_ROLE_TO_LEGACY" hydromodpy tests examples docs -g "*.py" -g "*.md" -g "*.toml" --glob "!docs/_dev_notes/geographic_config_legacy_cleanup_report.md"
python -m ruff check hydromodpy/spatial/geographic/core/hydrographic_network.py hydromodpy/spatial/geographic/store_ingestion.py hydromodpy/results/run_hydrographic.py hydromodpy/spatial/geographic/structure_binders.py hydromodpy/spatial/geographic/synthetic/config.py hydromodpy/spatial/geographic/synthetic/synthetic_geographic.py hydromodpy/spatial/geographic/core/flow_products.py hydromodpy/spatial/geographic/core/river_network.py tests/unit/geographic/test_hydrographic_network.py tests/unit/simulation/test_simulation_api.py
python -m pytest tests/unit/geographic/test_hydrographic_network.py -q
python -m pytest tests/unit/simulation/test_simulation_api.py -q
```

Resultats:

- les scans cibles ne retournent plus d'occurrence active;
- `ruff`: aucun probleme;
- `6 passed` sur `tests/unit/geographic/test_hydrographic_network.py`;
- `63 passed` sur `tests/unit/simulation/test_simulation_api.py`.

## Lot suivant applique: suppression du nom de feature `river_network`

- La constante et le helper d'alias hydrographique genere sont retires.
- `hydrographic_network_naming_contract(...)` n'expose plus de cle d'alias.
- `persist_geographic_to_store(...)` n'ecrit plus la feature alias
  `river_network`; seule `hydrographic_network_generated` est persistee pour
  le reseau genere.
- Les rapports calibration qui lisaient encore `river_network` via
  `run.geographic(...)` lisent maintenant la feature canonique.
- Les runners de reference geographic n'exportent plus les cles payload
  `river_network_shp` / `river_network_summary_json`; ils exposent les cles
  canoniques `hydrographic_network_generated_*`.
- `GeographicPaths` n'expose plus les champs `river_network_shp` et
  `river_network_summary_json`; le contrat interne utilise directement
  `hydrographic_network_generated_shp` et
  `hydrographic_network_generated_summary_json`.
- Les filenames disque `river_network.shp` et `river_network_summary.json`
  restent inchanges.

Controles executes:

```powershell
rg -n "legacy_feature_name|legacy_feature_name_for_role|HYDROGRAPHIC_NETWORK_GENERATED_LEGACY_FEATURE_NAME|_ROLE_TO_LEGACY|alias_feature_name|alias_feature_name_for_role|HYDROGRAPHIC_NETWORK_GENERATED_ALIAS_FEATURE_NAME|_ROLE_TO_ALIAS|_RIVER_NETWORK_STORE_NAME" hydromodpy tests examples docs -g "*.py" -g "*.md" --glob "!docs/_dev_notes/geographic_config_legacy_cleanup_report.md"
rg -n "_safe_geographic\\([^\\n]*river_network|run\\.geographic\\([^\\n]*river_network|geographic\\([^\\n]*river_network|write_geographic_feature\\([^\\n]*river_network|\"river_network\" in store\\.feature_names|feature_crs\\[\"river_network\"\\]" hydromodpy tests examples -g "*.py"
python -m ruff check hydromodpy/spatial/geographic/core/hydrographic_network.py hydromodpy/spatial/geographic/store_ingestion.py hydromodpy/results/run_hydrographic.py hydromodpy/calibration/reporting/network_transient_html.py tests/unit/geographic/test_hydrographic_network.py tests/unit/simulation/test_simulation_api.py tests/unit/workflow/test_hydrographic_network_persistence.py
python -m pytest tests/unit/geographic/test_hydrographic_network.py tests/unit/workflow/test_hydrographic_network_persistence.py tests/unit/simulation/test_simulation_api.py::TestSimulationData::test_hydrographic_network_comparison_accessor_and_capability -q
python -m pytest tests/unit/geographic/test_reference_river_network_nancon_case.py -q
```

Resultats:

- les scans cibles ne retournent plus d'occurrence active;
- `ruff`: aucun probleme;
- `12 passed` sur les tests hydrographic/store/simulation cibles;
- `1 passed` sur le runner de reference river-network.

## Proposition du lot suivant

Elargir le nettoyage hors `hydromodpy/spatial/geographic`: commencer par
`hydromodpy/results`, `hydromodpy/analysis/comparison` et les tests associes,
ou la plupart des occurrences restantes semblent etre des aliases/resultats de
compatibilite encore exposes.
