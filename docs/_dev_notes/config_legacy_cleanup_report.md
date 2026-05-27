# Config legacy cleanup report

Date: 2026-05-27

## Objectif

Retirer les remappages de configuration qui modifient silencieusement les
TOML anciens. Ce lot cible le fallback `calibration.outputs.*.support`, qui
injectait `support = "point"` quand le champ etait absent.

## Changements appliques

- `validate_calib_output()` ne modifie plus le payload avant validation.
- `CalibrationConfig.outputs` ne remappe plus les outputs sans `support`.
- Les outputs de calibration doivent maintenant porter un tag explicite:
  `support = "point"`, `support = "boundary"` ou `support = "cell"`.
- Ajout de tests qui verrouillent l'erreur attendue quand `support` manque.
- Le test de rejet des champs inconnus declare maintenant `support`
  explicitement, pour tester le bon comportement sans dependre de l'ancien
  fallback.

## Validation

Commandes executees:

```powershell
python -m pytest -q tests/unit/calibration/test_schemas.py tests/unit/calibration/test_config_enrichment.py tests/unit/calibration/test_cli_dispatch.py tests/unit/calibration/test_cli_composite_routing.py tests/unit/calibration/test_build_objective_from_config.py tests/unit/test_calibration_cli.py -o addopts=""
python -m ruff check hydromodpy/calibration/config.py tests/unit/calibration/test_schemas.py tests/unit/calibration/test_config_enrichment.py
rg -n "omits 'support'|defaulting to 'point'|legacy TOMLs|_default_output_support" hydromodpy tests docs/_dev_notes docs/source examples validation_cases -S --glob '!docs/source/_static/**' --glob '!docs/_build/**' --glob '!**/outputs/**'
```

Resultats:

- `130 passed` sur les tests calibration cibles;
- `ruff`: aucun probleme;
- aucune occurrence restante de l'ancien fallback `support` dans le code
  source, les tests ou les notes de chantier suivies.

## Etat apres lot

La configuration calibration ne contient plus de compatibilite silencieuse pour
les outputs sans support. Les TOML doivent etre explicites, ce qui evite
d'interpreter par erreur un output boundary/cell comme un point.

## Suite

Les prochains candidats legacy detectes sont plus limites:

1. occurrences de vocabulaire legacy dans certains tests de validation, a
   distinguer des tests de garde volontaires;
2. references documentaires generees a regenerer si elles proviennent de
   sorties de build ou de galleries statiques.

## Lot 2 - topographie synthetique explicite

Objectif: retirer le nettoyage automatique des anciens TOML
`expert_generated` qui exposaient toutes les cles topographiques, quelle que
soit la variante active.

Changements:

- suppression de `_TOPOGRAPHY_DEFAULT_LEAKS` et
  `_strip_default_topography_leaks`;
- `SyntheticGeographicConfig` ne supprime plus les champs hors variante avant
  validation;
- les exemples `03_canut_watershed/config_expert_generated.toml` et
  `05_nancon_data_overview/config_overview.toml` ont ete migres: les cles
  valables uniquement pour `linear` ou `radial_island` ne sont plus actives
  quand `kind = "flat"`;
- ajout d'un test qui verifie qu'un champ `right_to_left_amplitude` actif dans
  une topographie `flat` est rejete.

Validation:

```powershell
python -m pytest -q tests/unit/geographic_synthethic/test_synthetic_geographic.py tests/unit/geographic/test_domain_geographic_pipeline.py tests/unit/geographic/test_geographic_config.py tests/unit/config/test_toml_loader.py -o addopts=""
python -m ruff check hydromodpy/spatial/geographic/synthetic/config.py tests/unit/geographic_synthethic/test_synthetic_geographic.py
@'
from pathlib import Path
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
for path in [
    Path('examples/projects/05_nancon_data_overview/config_overview.toml'),
    Path('examples/projects/03_canut_watershed/config_expert_generated.toml'),
]:
    cfg = HydroModPyConfig.from_toml(path)
    print(path, cfg.geographic.synthetic.topography.kind)
'@ | python -
```

Resultats:

- `37 passed` sur les tests geographiques/config cibles;
- `ruff`: aucun probleme;
- les deux TOML exemples migres se chargent et gardent `topography.kind =
  "flat"`.

## Lot 3 - SGrid `bottom` et `layering` obligatoires

Objectif: retirer le remappage automatique des anciens payloads SGrid plats
(`genmtd_bot`, `bot_path`, `bot_raster`, `thick`, `zbot`, `genmtd_lay`, `nlay`,
`lay_decay`, `lay_proportions`) vers les sections imbriquees.

Changements:

- suppression de `_LEGACY_BOTTOM_KEYS`, `_LEGACY_LAYERING_KEYS`,
  `_migrate_legacy_bottom`, `_migrate_legacy_layering` et du validateur
  `_migrate_legacy_payload`;
- `SGridConfig` attend maintenant directement `bottom={...}` et
  `layering={...}`;
- `SGridConfig.from_toml()` ne resout plus `bot_path`; il resout uniquement
  `bottom.path`;
- le loader de demo `run_demo_config.py` resout aussi `bottom.path`;
- migration des TOML de demo/cas cartesiens vers `[case.sgrid.bottom]` et
  `[case.sgrid.layering]`;
- migration des tests unitaires SGrid et ajout d'un test de rejet des anciens
  champs plats.

Validation:

```powershell
python -m pytest -q tests/unit/mesh/cartesian_grid/test_sgrid_generation.py tests/unit/mesh/cartesian_grid/field_discretization/test_sgrid_fieldparam_discretization.py -o addopts=""
python -m ruff check hydromodpy/spatial/mesh/cartesian_grid/sgrid_config.py hydromodpy/spatial/mesh/cartesian_grid/sgrid_from_config.py hydromodpy/spatial/mesh/cartesian_grid/examples/discretization/run_demo_config.py tests/unit/mesh/cartesian_grid/test_sgrid_generation.py tests/unit/mesh/cartesian_grid/field_discretization/test_sgrid_fieldparam_discretization.py
@'
from pathlib import Path
from hydromodpy.spatial.mesh.cartesian_grid.examples.discretization.run_demo_config import load_sgrid_fieldparam_discretization_toml
for path in [
    Path('hydromodpy/spatial/mesh/cartesian_grid/examples/discretization/run_demo_config_2d.toml'),
    Path('hydromodpy/spatial/mesh/cartesian_grid/examples/discretization/run_demo_3d_config.toml'),
    Path('hydromodpy/spatial/mesh/gmsh_grid/cases/comparison_cartesian_vs_gmsh_2d/case_config_cartesian.toml'),
    Path('hydromodpy/spatial/mesh/gmsh_grid/cases/comparison_cartesian_vs_gmsh_3d/case_config_cartesian.toml'),
]:
    cfg = load_sgrid_fieldparam_discretization_toml(path, section='case')
    print(path, cfg['sgrid']['bottom']['kind'], cfg['sgrid']['layering']['kind'])
'@ | python -
```

Resultats:

- `30 passed` sur les tests SGrid/field-discretization cibles;
- `ruff`: aucun probleme;
- les quatre TOML migres se chargent avec les couples attendus:
  `constant_thickness/decay`, `constant_thickness/constant`,
  `constant_thickness/decay`, `constant_thickness/list`.

## Lot 4 - `[geographic.catchment]` obligatoire

Objectif: retirer le format historique ou `catch_def`, `dem_init_path`,
`x_outlet`, `y_outlet`, `snap_dist`, `buff_area` et `polyg_shp_path` etaient
poses directement sous `[geographic]`.

Changements:

- migration des TOML sources, fixtures et overlays vers
  `[geographic.catchment]`;
- suppression du helper `normalize_geographic_catchment_payload()` et des
  listes de cles legacy associees;
- `toml_section_loader` ne resout plus que le payload imbrique `catchment`;
- ajout/conservation de tests de rejet du payload plat;
- migration des snippets de documentation utilisateur qui montraient encore
  l'ancien format.

Validation:

```powershell
python -m pytest -q tests/unit/config/test_toml_loader.py tests/unit/geographic/test_geographic_config.py tests/unit/geographic/test_domain_geographic_pipeline.py tests/unit/geographic/test_catchment_delineation_contract.py tests/unit/launchers/test_data_overview_config.py tests/unit/solver/modflow_nwt/test_modflow_config.py -o addopts=""
python -m ruff check hydromodpy/spatial/geographic/geographic_config.py hydromodpy/config/toml_section_loader.py tests/unit/geographic/test_geographic_config.py tests/unit/config/test_toml_loader.py tests/unit/geographic/test_domain_geographic_pipeline.py tests/unit/geographic/test_catchment_delineation_contract.py tests/unit/launchers/test_data_overview_config.py tests/unit/solver/modflow_nwt/test_modflow_config.py
```

Resultats:

- `47 passed` sur les tests config/geographic/launchers/solver cibles;
- `ruff`: aucun probleme;
- scan section-aware des TOML suivis: 0 cle de bassin active sous
  `[geographic]` ou `*.geographic`.
