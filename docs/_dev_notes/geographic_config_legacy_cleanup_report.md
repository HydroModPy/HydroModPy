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

## Proposition du lot suivant

Auditer `hydromodpy/spatial/geographic/README.md`,
`structure_binders.py`, `synthetic/*` et `core/hydrographic_network.py`: ces
occurrences `legacy` correspondent encore a des APIs de compatibilite reelles.
La prochaine etape doit decider ce qui reste contractuel, puis renommer les
descriptions ou supprimer les alias quand ils ne sont plus consommes.
