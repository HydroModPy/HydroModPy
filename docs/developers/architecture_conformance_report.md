# Rapport de conformité architecture — HydroModPy v0.4

**Date :** 2026-04-21
**Branche :** `dev-refact_v2` au commit `31b90697` (HEAD, avant F08)
**Base :** `run_migration.sh` (P01-P13) + `run_finalization.sh` (F01-F07), phase F08 en cours
**Méthodologie :** vérification directe du code, indépendante de `migration_report_dev_refact_v2.md` (obsolète).
**Fichier de référence pour chaque spec :** `architecture_cible/XX_*.md`.

Ce rapport atteste la conformité du codebase v0.4 aux 14 spécifications
d'architecture cible, en inventoriant pour chaque spec un ensemble de
_checkpoints_ concrets (fichier/classe/CLI/table DuckDB/import). Chaque
checkpoint est noté :

- **OK**       — conforme, avec une preuve (file:line ou commande).
- **ÉCART**    — divergence assumée/documentée ailleurs (F02, OVERRIDE spec, etc.).
- **MANQUANT** — divergence résiduelle. Une tâche de suivi est proposée.

---

## Executive summary

| Spec | OK | Écart | Manquant | Verdict global |
|------|----|-------|----------|----------------|
| 01_structure_packages.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 02_config_pydantic.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 03_data_contracts.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 04_storage_ideal.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 05_solver_contracts.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 06_pipeline_execution.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 07_calibration.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 08_postprocess_display.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 09_tests_ideaux.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 10_ux_cli_api.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 11_frontend_ready.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 12_input_data_rethink.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 13_coherence_globale.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| 14_plan_migration.md | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| **TOTAL** | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

---

## Détail par spécification

### 01_structure_packages.md
**Résumé :** L'arborescence actuelle diverge fortement de la cible (pas de `_cli/`, pas de `physics/`, pas de `core/io|logging|exceptions`, `watershed/` toujours présent, packages `pipeline/` et `schema/` non prévus, profondeur 6, god-modules > 2000 l. toujours présents).
**Checkpoints :** 25 au total, OK=5, ÉCART=17, MANQUANT=3.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | Package `_cli/` remplace `__main__.py` monolithique | ÉCART | `hydromodpy/_cli` n'existe pas ; `hydromodpy/__main__.py` = 1890 lignes (cible ≤ 80). |
| 2 | `__init__.py` ≤ 80 lignes, sans bootstrap PROJ_DATA ni `LogManager()` eager | ÉCART | `hydromodpy/__init__.py` = 448 lignes ; lignes 20–218 = bootstrap PROJ_DATA, ligne 243 `_log_manager = LogManager(...)` au chargement. |
| 3 | `core/` est feuille du DAG (aucune dépendance `hydromodpy.*`) | ÉCART | `rg '^from hydromodpy\.(?!core)' hydromodpy/core` → 53 occurrences dans 9 fichiers (`core/config/hydromodpy_config.py:13`, `core/state/setup.py:8`, `core/state/data.py:3`, `core/config/generate_toml.py:11`…). |
| 4 | `core/exceptions.py` + hiérarchie centrale utilisée | ÉCART | Aucun `core/exceptions.py` ni `hydromodpy/exceptions.py`. Les `*Error` trouvés sont dispersés dans `data/adapters/*`. |
| 5 | `core/io/` (raster_io, vector_io, crs, http_client) | MANQUANT | `hydromodpy/core/io` absent. Utilitaires éparpillés dans `core/tools/` (`raster_io.py`, `geospatial.py`, `io_utils.py`). |
| 6 | `core/logging/` | MANQUANT | Absent. `LogManager` dans `core/tools/log_manager.py`. |
| 7 | `core/version.py` avec `__version__` isolé | ÉCART | Calculé inline dans `hydromodpy/__init__.py:229-236`. |
| 8 | `core/backends/` supprimé, backends déplacés sous `spatial/delineation/` | OK | `core/backends` absent ; `spatial/delineation/` contient `base.py`, `registry.py`, `whitebox_cli_backend.py`, `whitebox_workflows_backend.py`, `pysheds_backend.py`, `synthetic_backend.py`. |
| 9 | Package `process/` renommé en `physics/` | ÉCART | `hydromodpy/physics` absent ; `hydromodpy/process/` conservé (décision de scope). |
| 10 | Package `watershed/` supprimé | ÉCART | `hydromodpy/watershed/` toujours présent (façade legacy). |
| 11 | `workflow/` absorbé dans `simulation/workflows/` | ÉCART | `workflow/` top-level inchangé ; `simulation/workflows/` n'existe pas. |
| 12 | `runners/` top-level disparaît | ÉCART | `hydromodpy/runners/` toujours présent (shells CLI). |
| 13 | `simulation/results/` renommé en `simulation/extraction/` | ÉCART | Toujours `simulation/results/` (collision avec `results/` non levée). |
| 14 | `solver/utils/mesh/` déplacé vers `spatial/mesh/` | ÉCART | `solver/utils/mesh/` conservé (cartesian_grid + gmsh_grid). |
| 15 | `data/common/` aplati (`data/base_manager.py`) | ÉCART | `data/common/` conservé avec `base_manager.py`, `base_config.py`, `clients/`, etc. |
| 16 | Pas de duplication `data/{hydrometry,…}/` vs `data/variables/…/` | ÉCART | Les deux coexistent (façades legacy + managers canoniques). |
| 17 | Aucun `cases/` dans le runtime | ÉCART | 11 dossiers `cases/` dans le runtime (`data/variables/*/cases/`, `spatial/{field,domain,geographic}/cases/`, etc.). |
| 18 | Profondeur max d'import ≤ 4 niveaux | ÉCART | `solver/utils/mesh/gmsh_grid/cases/reference_3d_mesh/` = 6 niveaux. |
| 19 | Aucun fichier > 800 lignes | ÉCART | `solver/modflow6/modflow6.py` 2892, `analysis/comparison/runtime.py` 2061, `__main__.py` 1890, `analysis/batch/runtime.py` 1828, `solver/boussinesq/boussinesq.py` 1667, `solver/modflow_nwt/modflow/flow_to_modflow_adapter.py` 1394, `results/catalog.py` 1077. |
| 20 | `results/io/exporters/` dédié | ÉCART | `results/exporters/` à plat (csv/geotiff/hmp_package/netcdf/shapefile/vtu). Pas de `geopackage.py` ni `waterml.py`. |
| 21 | API publique `hmp.*` ≤ 25 symboles sans `*Manager/*Config/*Result` | ÉCART | `__init__.py` expose ~38 symboles dont `HydrographyConfig/Manager/Result`, `IntermittencyConfig/Manager`, `OceanicConfig/Manager`. |
| 22 | CLI `hmp`/`hydromodpy` installé via pyproject.toml | OK | Entries pointent sur `hydromodpy.__main__:main` (divergence chemin documentée : spec visait `_cli/main.py`). |
| 23 | `spatial/delineation/` multi-backend | OK | `base.py` (Protocol), `registry.py`, 4 backends (cli, workflows, pysheds, synthetic). |
| 24 | `spatial/surface.py` consolidé | OK (partiel) | `spatial/surface.py` existe mais `surface_sampling.py` subsiste à côté. |
| 25 | `validation_cases/` à la racine du repo | OK | `validation_cases/` présent mais coexiste avec les `cases/` in-package (cf. #17). |

**Écarts assumés :**
- CLI monolithique (`__main__.py`) conservée au lieu de `_cli/`.
- Sous-packages `pipeline/`, `schema/`, `calibration/`, `display/` top-level (non prévus par la spec qui les range sous `analysis/`).
- `analysis/calibration/`, `analysis/display/`, `analysis/postprocess/`, `analysis/metrics/` absents (fonctionnalités déplacées dans top-level dédiés).
- `process/` conservé au lieu de `physics/` (renommage hors scope migration).
- God-modules > 800 lignes : 7 fichiers dépassent la limite (décision post-v0.4).

**Manquants :**
- `core/io/` (raster_io.py, vector_io.py, crs.py, http_client.py) — suivi `v0.5-core-io-scaffold`.
- `core/logging/` dédié — suivi `v0.5-core-logging-extract`.
- `core/exceptions.py` hiérarchie centrale — suivi `v0.5-exceptions-hierarchy`.

---

### 02_config_pydantic.md
**Résumé :** Fondations Pydantic v2 + `ParamLevel` + types pint en place ; `HydroModelBase`, refonte `FlowConfig`/`Forcing`/`GridConfig`, round-trip `tomlkit` et validation physique centrale restent non implémentés.
**Checkpoints :** 21 au total, OK=8, ÉCART=9, MANQUANT=4.

| # | Checkpoint | Verdict | Preuve / Note |
|---|------------|---------|---------------|
| 1 | `HydroModelBase` racine avec `ConfigDict(extra="forbid", serialize_by_alias, populate_by_name, validate_assignment)` | MANQUANT | `grep -r "class HydroModelBase"` → 0 résultat ; chaque config déclare son propre `model_config`. |
| 2 | `HydroModPyConfig` agrégateur root | OK (partiel) | `hydromodpy/core/config/hydromodpy_config.py:63` présent, mais `model_config = ConfigDict(arbitrary_types_allowed=True)` sans `extra="forbid"` (ÉCART). |
| 3 | `extra="forbid"` sur les sous-configs | OK | 116 occurrences dans 52 fichiers. |
| 4 | `from_toml` minimaliste | ÉCART | `hydromodpy_config.py:192-299` ~110 lignes avec dispatcher custom + `from_toml_section` (flow, data). |
| 5 | `to_toml(profile=...)` round-trip | MANQUANT | Aucun résultat sous `hydromodpy/core/config` ; seul `streamlit_config.py` en possède un équivalent ad-hoc. |
| 6 | Validateur cross-section (`solver.engine ↔ packages.engine`, `flow_regime=transient ⇒ ic`) | MANQUANT | Aucun `model_validator` transverse dans `HydroModPyConfig`. |
| 7 | `ParamLevel` user/dev/expert disponibles | OK | `hydromodpy/core/config/param_level.py:22` `PROFILES = {"user": 0, "dev": 1, "expert": 2}`. |
| 8 | `Profile(IntEnum)` comparable | ÉCART | `PROFILES` reste un `dict[str,int]` ; `ParamLevel` est dataclass. |
| 9 | `VisibleWhen` + validateur cible | ÉCART | `VisibleWhen` présent (`param_level.py:35`) mais aucun `_check_visible_when_targets`. |
| 10 | Types pint `Length`, `Time`, `FlowRate`, `HydraulicConductivity`, `SpecificStorage`, `SpecificYield`, `Area`, `Volume`, `Dimensionless` | OK | `core/units/types.py:161-171` ; ré-exports via `core/units/__init__.py:14-24`. |
| 11 | Registre pint partagé `UREG` | OK | `core/units/registry.py` + `UREG` exporté `core/units/__init__.py:13`. |
| 12 | `pydantic-pint` en dépendance core | OK | `pyproject.toml:58-59`. |
| 13 | `FlowPhysicalProperties` migré vers types pint (F01) | OK | `process/flow/physical_properties.py:39-41,59,75,88` utilise `HydraulicConductivity/SpecificYield/SpecificStorage`. |
| 14 | xfail `test_bare_number_falls_back_to_canonical_unit` + `test_flow_physical_properties_defaults_and_overrides` résolus (F01) | OK | `tests/unit/config/test_units_roundtrip.py:34,93` plus aucun marker `xfail`. |
| 15 | `FlowConfig` refactoré (runtime: FlowRuntimeConfig, types pint) | ÉCART | `process/flow/flow_config.py:51` hérite encore de `ProcessSpatialConfig` ; pas d'import pint (confirme F01 scope limité). |
| 16 | `TimeseriesVariableConfig` factorisant etp/humidity/... | MANQUANT | Les 14 configs timeseries restent séparées. |
| 17 | Union discriminée `Forcing` | MANQUANT | `ConstantForcing/SyntheticForcing/CsvForcing` absents. |
| 18 | `GridConfig` unifié + suppression suffixe `Schema` | ÉCART | `SGridConfig` toujours présent ; 31 classes `*Schema` subsistent. |
| 19 | CLI `hmp config <out.toml> --profile {user,dev,expert}` | OK | `__main__.py:1470-1475` + `_cmd_config`. |
| 20 | CLI `hmp schema export` + `hmp config schema` | OK | `__main__.py:1491-1509` + `1517-1533`. |
| 21 | `PHYSICAL_BOUNDS` centralisé + `validate_physical_value` | ÉCART | Seul `calibration/parameters.py` utilise des bounds physiques ad-hoc ; pas de `spatial/field/core/physical_bounds.py`. |

**Écarts assumés :**
- `HydroModPyConfig` conserve un `from_toml` impératif avec dispatcher — post-v0.4.
- `FlowConfig` hérite toujours de `ProcessSpatialConfig` et n'a pas migré vers pint (dette F01 tracée).
- Suffixe `Schema` encore porté par 31 classes dans 6 fichiers.
- `Profile(IntEnum)` non introduit : `PROFILES` dict suffit à l'implémentation courante.

**Manquants :**
- `hydromodpy/core/config/base.py::HydroModelBase` (suivi `v0.5-config-hydromodelbase`).
- `to_toml(profile=...)` via `tomlkit` (suivi `v0.5-toml-roundtrip`).
- `TimeseriesVariableConfig` factorisation (suivi `v0.5-timeseries-refactor`).
- `Forcing` discriminated union + `PHYSICAL_BOUNDS` central (suivi `v0.5-forcing-union` et `v0.5-physical-bounds`).

---

## Écarts globaux assumés (décisions architecture)

_À compiler après les 14 vérifications._

---

## Manquants résiduels (à traiter post-v0.4)

_À compiler après les 14 vérifications._

---

## Conclusion

_À renseigner après synthèse._
