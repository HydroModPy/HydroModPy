# Architecture cible — Suite de tests HydroModPy

**Document** : `architecture_cible/09_tests_ideaux.md`
**Date** : 2026-04-18
**Auteur** : Expert QA logiciels de simulation numérique (références : pytest, hypothesis, FloPy, xarray, scikit-learn, OpenFOAM `testHarness`, TOUGH2-EOS suite, FEFLOW QA protocol, DOE V&V 10-2006, ASME V&V 20-2009).
**Portée** : définir la suite de tests cible — compacte, rapide, fiable — qui donne confiance sans devenir un fardeau. Rupture assumée avec l'existant (283 fichiers, ≈ 48 000 LOC), pas un patch.
**Sources** : audits `audit_code/09_tests_audit.md` et transverses (01-11). Docs cibles `01_structure_packages.md` (packages), `02_config_pydantic.md` (Pydantic), `03_data_contracts.md` (contrats données), `04_storage_ideal.md` (catalog/Zarr), `05_solver_contracts.md` (Protocol solveurs), `06_pipeline_execution.md` (runner), `07_calibration.md`, `08_postprocess_display.md`.

> **Légende des tags**
> `[NOUVEAU]` n'existe pas · `[RENOMME]` existe sous un autre nom · `[REFACTORE]` existe mais doit changer · `[CONSERVE]` existe et reste tel quel · `[SUPPRIME]` à retirer.

> **Objectif opérationnel** : un développeur fait `hmp test unit` → **45 s** en série, **15 s** avec `-n auto`. Un reviewer PR voit la suite `hmp test smoke` passer en **3 min** sur laptop, **2 min** en CI. Un responsable scientifique lance `hmp test validation` la nuit et reçoit un rapport d'ordre de convergence. **Chaque test qui tombe pointe directement la cause** — pas une pyramide d'abstractions à démêler.

---

## Table des matières

0. [Principes directeurs](#0-principes-directeurs)
1. [Pyramide cible et budgets de temps](#1-pyramide-cible)
2. [Arborescence `tests/` cible](#2-arborescence-cible)
3. [Les 20 tests unitaires critiques](#3-tests-unitaires-critiques)
4. [Les 5 scénarios d'intégration essentiels](#4-integration)
5. [Benchmarks analytiques et MMS](#5-validation-scientifique)
6. [Golden files — maintenir ou remplacer ?](#6-golden-files)
7. [Infrastructure pytest (conftest, markers, fixtures)](#7-infrastructure-pytest)
8. [Pipeline CI — fast / full / nightly](#8-pipeline-ci)
9. [Plan de dégraissage — supprimer 50 % sans perdre confiance](#9-degraissage)
10. [Comparaison aux projets de référence](#10-comparaison-reference)
11. [Tableau de migration actuel → cible](#11-migration)

---

## 0. Principes directeurs

| # | Principe | Conséquence pratique |
|---|---|---|
| 1 | **Chaque niveau a un budget temps contractuel** | `unit ≤ 200 ms`, `integration ≤ 5 s`, `validation` illimité mais hors CI rapide. Timeout enforced par `conftest.py`, pas par politesse. |
| 2 | **Un test = une cause probable** | Si un test tombe, il doit pointer un fichier source précis. Les tests de bout-en-bout qui explosent 6 modules à la fois sont bannis de `unit/`. |
| 3 | **Unit = pur, sans I/O, sans solveur, sans subprocess** | Le test importe une classe, la construit, vérifie une sortie. Pas de DEM réel, pas de gmsh, pas de FloPy, pas d'appel binaire. Règle mécanique, validée par hook CI. |
| 4 | **Integration = fixtures déterministes, pas de réseau, solveurs embarqués only** | Pipeline complet mais sur mini-maille (20×20, 2 timesteps) avec données fixtures. Réseau et gros DEM → `validation/` ou `regression/`. |
| 5 | **Validation = science, pas régression** | Comparaison à une solution analytique ou MMS, avec critère d'ordre documenté. Un test validation sans rationale numérique est un test régression mal rangé. |
| 6 | **Pas de golden sans justification** | Chaque tolérance est liée à une référence (Richardson, `h`-convergence, machine ε) dans un header de fichier. Pas de chiffre magique. |
| 7 | **Déterminisme explicite** | Tout test stochastique fixe `random_state=0`. Tout test appelant whitebox/numpy multi-thread force un thread. Tout test temporel fixe `TZ=UTC`. |
| 8 | **Fixtures hiérarchiques, scope explicite** | `session` pour données coûteuses en lecture seule, `module` pour configs, `function` par défaut. Pas de `autouse` global pour un besoin local. |
| 9 | **Paramétrage > copier-coller** | Les N tests « pareils sauf 2 paramètres » sont fusionnés en un `@pytest.mark.parametrize`. Gain maintenance ×5. |
| 10 | **CI = stratégie de blocage graduée** | PR bloquée si `unit+smoke` tombe (2 min). Warning mais pas de blocage si `validation weekly` régresse de 1 %. L'effort CI est proportionnel au risque. |
| 11 | **Les tests sont du code** | Refactoring, revue, DRY, limite de lignes. Un fichier de test > 400 LOC déclenche une alerte lint. |
| 12 | **Un test, un nom lisible** | `test_<what>_<under_which_condition>_<expected_outcome>`. Fini `test_launcher_simulation_fast_mf6_regression`. |
| 13 | **Hypothesis pour les propriétés** | Les conversions d'unités, sérialisations, calculs de métriques, contrats de solveurs se prêtent à des tests de propriétés. Un `@given(floats())` remplace 30 cas manuels. |
| 14 | **Golden compact, pas binaire** | Signatures statistiques enrichies (min, p05, p25, p50, p75, p95, max, std, sum, moment_1) — pas de dump de tableaux. |
| 15 | **Pas de tests d'implémentation** | On teste les contrats publics (API `hmp.Simulation`, `SolverPlugin.run`), pas les chemins d'appel internes. Si le code interne bouge, les tests ne doivent pas tomber. |

### 0.1 Ce qui change par rapport à l'existant

| Défaut actuel (audit §) | Fix cible | Section |
|---|---|---|
| 235 fichiers `unit/` dont ~170 sont de l'intégration (§1-2) | **80 fichiers `unit/` stricts**, `integration/` introduit (§4) | §1, §2, §9 |
| `fast` à timeout 3 600 s (§8.2) | Renommé `smoke` (≤ 3 min) vs `fast` (≤ 30 s unit) | §7, §8 |
| `monkeypatch.setattr` × 338 (§2) | ≤ 100, par injection de dépendance (§0) | §3, §9 |
| Subprocess réel dans `unit/` (§2.2) | Interdit par hook ; tests déplacés en `e2e/` | §7.2 |
| Goldens 4 stats / last timestep (§3.2) | Signature enrichie 10 stats × 3 timesteps (§6) | §6 |
| Tolérances golden non documentées (§4.3) | Fichier `TOLERANCES.md` + header par TOML (§6.4) | §6 |
| Pas de MMS, pas de Theis, pas de Hantush, pas d'Ogata-Banks (§4.2-4.4) | 3 benchmarks obligatoires + 2 MMS | §5 |
| `golden_utils.py` 1 104 LOC (§7.1) | Scindé en 4 modules ≤ 300 LOC chacun | §6.3 |
| `pytest_sessionfinish` casse xdist (§6.1) | Retiré ; tmp_path gère seul | §7.1 |
| `tests/unit/launchers/test_model_calibration_launcher.py` 2 722 LOC (§9.3) | Supprimé (lanceur legacy), remplacé par 3 tests intégration sur l'engine | §9 |
| Pas de xdist CI (§6.3) | `-n auto --dist=loadfile` par défaut | §8 |
| Coverage config pointe vers modules inexistants (§5.3) | Nettoyée, matche `hydromodpy/` réel | §8.3 |

---

<a id="1-pyramide-cible"></a>
## 1. Pyramide cible et budgets de temps

### 1.1 Ratios

| Niveau | Ratio cible | # fichiers | # tests | Budget par test | Budget total | Quand |
|---|---|---|---|---|---|---|
| **unit** | 75 % | ~80 | ~600 | ≤ 200 ms (médiane ≤ 30 ms) | ≤ 45 s en série, ≤ 15 s avec `-n auto` | À chaque sauvegarde (IDE) |
| **integration** | 17 % | ~18 | ~80 | ≤ 5 s | ≤ 3 min | Pré-commit / PR |
| **validation** | 6 % | ~12 | ~40 | ≤ 60 s | ≤ 30 min | Nightly / release |
| **e2e** | 2 % | ~5 | ~10 | ≤ 10 min | ≤ 1 h | Nightly / release |

**Comptage vs existant** : on passe de **~283 fichiers, 48 000 LOC** à **~115 fichiers, ~18 000 LOC**. Réduction 60 % en fichiers, 62 % en lignes. La couverture de code *fonctionnelle* progresse (cf. §9.4) parce qu'on rend testables les bons chemins (`solver/boussinesq/runtimes/*`, `forcing/*_resolution.py`, etc.), au lieu de dupliquer des tests d'orchestration.

### 1.2 Budgets contractuels

Les budgets sont **appliqués automatiquement** par un hook `pytest_collection_modifyitems` (`tests/conftest.py`) qui force les marqueurs timeout. Un test qui dépasse son budget est un bug :

```python
# tests/conftest.py (extrait)
_BUDGETS = {
    "unit":        2.0,   # pytest-timeout, hard limit
    "integration": 8.0,
    "validation":  120.0,
    "e2e":         900.0,
}
```

Le médian est 10× plus strict que le hard limit. La CI affiche `--durations=20` à chaque job et un warning dès qu'un test médian franchit 100 ms en `unit/`.

### 1.3 Marqueurs pytest — pour de bon cette fois

| Marqueur | Sens | Scope CI |
|---|---|---|
| `unit` | auto-ajouté par chemin `tests/unit/` | toujours |
| `integration` | auto-ajouté par chemin `tests/integration/` | PR + push master |
| `validation` | auto-ajouté par chemin `tests/validation/` | nightly + release |
| `e2e` | auto-ajouté par chemin `tests/e2e/` | nightly + release |
| `smoke` | sous-ensemble rapide (unit + integration ≤ 500 ms) | pré-commit hook |
| `slow` | override : test qui a besoin de > budget (doit justifier) | skippé par défaut en `unit` |
| `nwt`, `mf6`, `boussinesq`, `petsc` | solveur ciblé | `-m nwt` pour itérer |
| `network` | requiert accès réseau (SHOM/Hubeau/OSM) | skippé en CI par défaut |
| `binary` | requiert binaire externe (`mfnwt`, `mf6`) | skippé si `shutil.which(...)` None |
| `gpu`, `mpi`, `petsc` | capacités matérielles | skippé selon environnement |

**Supprimés** : `fast`, `extensive`, `normal`, `analytical`, `steady`, `transient`, `coverage` — redondants ou mensongers (cf. audit §8.2).

---

<a id="2-arborescence-cible"></a>
## 2. Arborescence `tests/` cible

```
tests/
├── conftest.py                     # racine : 80 LOC max, markers auto, scratch root
├── pytest.ini                      # [NOUVEAU] sort de pyproject.toml pour clarté
├── README.md                       # 1 page : comment lancer, comment écrire
├── TOLERANCES.md                   # [NOUVEAU] justification de tous les seuils
│
├── _helpers/                       # [RENOMMÉ depuis tests/support/] — helpers PYTEST-LOCAL
│   ├── __init__.py
│   ├── fixtures_mesh.py            # mini-maillages UGRID (3×3, 10×10, circulaire)
│   ├── fixtures_catalog.py         # catalog in-memory + simulations synthétiques
│   ├── fixtures_config.py          # TOML minimaux, HydroModPyConfig instanciés
│   ├── fixtures_data.py            # DEMs procéduraux, piezos synthétiques
│   ├── strategies.py               # stratégies Hypothesis réutilisables
│   ├── signatures.py               # [RENOMMÉ depuis regression/golden_utils.py]
│   └── assertions.py               # assert_close_stats, assert_convergence_order
│
├── unit/                           # ~80 fichiers, ~600 tests, < 45 s
│   ├── core/                       # config Pydantic, units, tools, state
│   │   ├── test_config_validation.py
│   │   ├── test_units_conversion.py
│   │   └── test_state_context.py
│   ├── data/                       # contracts, planner, manager, provenance
│   │   ├── test_data_contracts.py
│   │   ├── test_data_planner.py
│   │   └── test_provenance_hash.py
│   ├── spatial/                    # mesh UGRID, field, domain
│   │   ├── test_mesh_topology.py
│   │   ├── test_field_param_resolve.py
│   │   └── test_zone_resolution.py
│   ├── process/                    # flow/transport config + IC
│   │   ├── test_flow_config.py
│   │   ├── test_flow_initial_conditions.py
│   │   └── test_transport_config.py
│   ├── solver/
│   │   ├── test_plugin_registry.py           # [NOUVEAU] doc 05
│   │   ├── test_capabilities_matching.py
│   │   ├── test_forcing_resolution.py        # [NOUVEAU] bouche trou audit §5
│   │   ├── boussinesq/
│   │   │   ├── test_assembly_triplets.py     # [NOUVEAU]
│   │   │   ├── test_jacobian_partition.py    # [NOUVEAU]
│   │   │   ├── test_runtime_scipy_sparse.py  # [NOUVEAU] 3×3 analytique
│   │   │   └── test_smoothing.py             # [CONSERVE]
│   │   ├── modflow6/
│   │   │   ├── test_boundary_conditions.py
│   │   │   └── test_time_grid_contract.py
│   │   └── modflow_nwt/
│   │       └── test_executables.py
│   ├── results/                    # catalog, Zarr, metrics, derived
│   │   ├── test_catalog_schema.py
│   │   ├── test_catalog_crud.py
│   │   ├── test_zarr_layout.py
│   │   ├── test_metrics_nse_kge.py            # [NOUVEAU]
│   │   ├── test_derived_watertable.py
│   │   └── test_signatures_statistical.py     # [NOUVEAU] remplace test_golden_utils
│   ├── simulation/                 # planner, runner, context
│   │   ├── test_simulation_plan.py
│   │   ├── test_simulation_runner_dry.py
│   │   └── test_simulation_api_surface.py
│   └── analysis/
│       ├── test_calibration_engine.py
│       ├── test_comparison_pivot.py
│       └── test_display_protocol.py
│
├── integration/                    # [NOUVEAU] ~18 fichiers, ~80 tests, < 3 min
│   ├── conftest.py                 # fixtures workspace + mini-catalog
│   ├── test_config_to_run_nwt_mini.py
│   ├── test_config_to_run_mf6_mini.py
│   ├── test_config_to_run_boussinesq_mini.py
│   ├── test_data_pipeline_hydrometry.py
│   ├── test_data_pipeline_piezometry.py
│   ├── test_catalog_import_export_roundtrip.py
│   ├── test_calibration_cma_es_twin_mini.py
│   ├── test_comparison_multi_solver.py
│   ├── test_display_headless_export.py
│   └── test_mesh_pipeline_gmsh.py
│
├── validation/                     # ~12 fichiers, ~40 tests, < 30 min
│   ├── conftest.py                 # fixture loader analytique
│   ├── analytical/
│   │   ├── steady/
│   │   │   ├── test_dupuit_fixed_head_1d.py
│   │   │   ├── test_dupuit_recharge_1d.py
│   │   │   ├── test_theis_steady_confined_2d.py   # [NOUVEAU] couvre confiné
│   │   │   └── test_circular_island_2d.py
│   │   └── transient/
│   │       ├── test_theis_confined_pumping_2d.py  # [NOUVEAU] audit §4.2
│   │       ├── test_hantush_jacob_leaky_2d.py     # [NOUVEAU]
│   │       ├── test_ogata_banks_transport_1d.py   # [NOUVEAU] transport
│   │       └── test_brutsaert_recession.py
│   ├── mms/
│   │   ├── test_mms_laplacian_steady_1d.py        # [NOUVEAU] ordre 2 attendu
│   │   └── test_mms_diffusion_transient_1d.py     # [NOUVEAU] ordre 1 en t, 2 en x
│   └── twins/
│       ├── test_twin_calibration_nwt.py           # étend MF6-only
│       └── test_twin_calibration_boussinesq.py
│
└── e2e/                            # [NOUVEAU] ~5 fichiers, < 1 h
    ├── test_real_watershed_nancon.py          # 1 bassin, pipeline complet
    ├── test_cli_hmp_run_full_toml.py          # subprocess légal ici
    ├── test_cli_hmp_export_package.py
    ├── test_cli_hmp_display.py
    └── test_large_batch_regional_lab.py
```

### 2.1 Éliminations assumées

| Directory actuel | Devient | Raison |
|---|---|---|
| `tests/regression/` | fusionné dans `validation/` + `e2e/` | La notion « régression » chevauche validation/e2e ; les goldens deviennent une *technique* (§6), pas un répertoire. |
| `tests/unit/launchers/` (2 722 + 735 + 690 LOC) | supprimé, l'engine est testé dans `tests/unit/analysis/` et `tests/integration/` | Les launchers sont des shells ≤ 30 LOC (doc 01). On teste l'engine, pas la glu. |
| `tests/unit/geographic_synthethic/` | fusionné dans `tests/unit/spatial/` et `tests/integration/` | Doublon de `geographic/`. |
| `tests/unit/validation/` et `tests/unit/validation_cases/` | déplacés dans `tests/validation/` | Ces tests font tourner des benchmarks — ils n'ont rien à faire dans `unit/`. |
| `tests/support/pytest_timing_distribution.py` (329 LOC) | `tools/ci/timing_distribution.py` | Outil d'analyse, pas une fixture. |
| `tests/regression/reference/golden_references/normal/` | supprimé | Alias déprécié documenté par l'audit §9.1. |

---

<a id="3-tests-unitaires-critiques"></a>
## 3. Les 20 tests unitaires critiques

Ces 20 tests forment le **noyau** : si tous passent, on a une confiance élevée que la glu des modules n'est pas cassée. Chacun doit tenir en **≤ 50 LOC**, s'exécuter en **≤ 100 ms**, n'utiliser ni I/O disque autre que `tmp_path`, ni réseau, ni subprocess, ni solveur binaire. Tous les tests mentionnés dans cette section sont `[NOUVEAU]` sauf mention contraire (plusieurs existent partiellement mais avec un périmètre trop large — cf. §9).

### 3.1 Layer **config / Pydantic**

#### Test 1 — `test_hydromodpycfg_forbids_extra_fields`
**Fichier** : `tests/unit/core/test_config_validation.py`
**Ce qu'on teste** : `HydroModPyConfig(**{"unknown": 42, **valid_dict})` lève `ValidationError` avec un message mentionnant le champ inconnu.
**Inputs** : TOML minimal valide (workspace + simulation) + 3 clés parasites (`unknwon`, `typo_field`, `simulation__wrong`).
**Attendu** : `ValidationError` sur les trois, `pytest.raises` + `match=r"unknown"` .
**Fixture** : `minimal_hydromodpy_config` (module-scoped dict).
**Statut** : `[NOUVEAU]` — règle imposée par `ConfigDict(extra="forbid")` partout (audit `02_core_config.md`).

#### Test 2 — `test_param_level_filters_user_profile_template`
**Fichier** : `tests/unit/core/test_config_validation.py`
**Ce qu'on teste** : `HydroModPyConfig.generate_template(profile="user")` ne contient aucun champ annoté `ParamLevel.EXPERT`.
**Inputs** : les 3 profils `user`, `dev`, `expert`.
**Attendu** : `user ⊂ dev ⊂ expert` (sous-ensemble strict), vérifié par set comparison.
**Fixture** : aucune (introspection Pydantic).
**Statut** : `[NOUVEAU]`.

#### Test 3 — `test_toml_roundtrip_preserves_semantic_content`
**Fichier** : `tests/unit/core/test_config_validation.py`
**Ce qu'on teste** : `loads(dumps(cfg)) == cfg` pour `HydroModPyConfig` sérialisé en TOML.
**Inputs** : 5 configs représentatives (flow NWT steady, flow MF6 transient, calibration, batch, overview).
**Attendu** : égalité après `model_dump(mode="python")` (pas de drift d'unités, pas de None introduit).
**Fixture** : `@pytest.mark.parametrize("config_kind", ["nwt_steady", "mf6_transient", ...])` pointant sur 5 TOMLs dans `_helpers/configs/`.
**Statut** : `[NOUVEAU]`.

```python
# Squelette — tests/unit/core/test_config_validation.py
import pytest
from pydantic import ValidationError
from hydromodpy.core.config import HydroModPyConfig

class TestConfigValidation:
    def test_hydromodpycfg_forbids_extra_fields(self, minimal_hydromodpy_config):
        bad = {**minimal_hydromodpy_config, "unknwon": 42}
        with pytest.raises(ValidationError, match=r"unknwon"):
            HydroModPyConfig(**bad)

    @pytest.mark.parametrize("profile", ["user", "dev", "expert"])
    def test_template_respects_param_level(self, profile):
        tmpl = HydroModPyConfig.generate_template(profile=profile)
        # Invariant vérifiable par introspection de FieldInfo.json_schema_extra
        ...
```

### 3.2 Layer **units**

#### Test 4 — `test_unit_registry_rejects_ambiguous_labels`
**Fichier** : `tests/unit/core/test_units_conversion.py`
**Ce qu'on teste** : toute tentative d'enregistrer un alias ambigu (`"m3/s"` vs `"m³/s"` canonique) est rejetée.
**Inputs** : `UnitRegistry.register("m3/s", canonical="m³/s")` et tentatives doublons.
**Attendu** : `UnitAliasConflict` sur 2e enregistrement.
**Fixture** : aucune.
**Statut** : `[NOUVEAU]`.

#### Test 5 — `test_unit_conversion_propagates_via_hypothesis`
**Fichier** : `tests/unit/core/test_units_conversion.py`
**Ce qu'on teste** : `convert(x, a, b)` puis `convert(y, b, a)` retourne `x` à ε près, pour toutes paires d'unités compatibles.
**Inputs** : `@given(st.floats(1e-12, 1e12), st.sampled_from(UNIT_PAIRS))`.
**Attendu** : `math.isclose(x, y, rel_tol=1e-12)`.
**Fixture** : Hypothesis profile `ci` (100 exemples).
**Statut** : `[NOUVEAU]` — remplace `test_time.py` actuel qui ne teste qu'un cas.

### 3.3 Layer **data contracts / planner**

#### Test 6 — `test_data_planner_infers_geology_from_zone_ids`
**Fichier** : `tests/unit/data/test_data_planner.py`
**Ce qu'on teste** : `DataManagersPlanner.resolve(config)` avec `domain.zone_ids=["geology"]` planifie le manager geology même sans `[data.geology]` explicite (règle CLAUDE.md).
**Inputs** : config minimal sans section data, avec zone `geology`.
**Attendu** : `plan.managers` contient `GeologyManager`, `plan.inferred` contient `"geology"`.
**Fixture** : `minimal_hydromodpy_config` + override.
**Statut** : `[NOUVEAU]` — couvre explicitement l'inférence, vraie fonctionnalité métier.

#### Test 7 — `test_data_planner_strict_mode_raises_on_implicit_inference`
**Fichier** : `tests/unit/data/test_data_planner.py`
**Ce qu'on teste** : en mode `data.inference_mode="strict"`, l'inférence d'un manager non déclaré lève `ImplicitInferenceError`.
**Inputs** : même config que test 6 + `inference_mode="strict"`.
**Attendu** : `pytest.raises(ImplicitInferenceError, match="geology")`.
**Statut** : `[NOUVEAU]`.

#### Test 8 — `test_provenance_hash_is_deterministic_and_cross_platform`
**Fichier** : `tests/unit/data/test_provenance_hash.py`
**Ce qu'on teste** : `provenance_hash(bytes)` = SHA-256 ; `provenance_hash_stream(path)` donne le même résultat en 3 coups de 1 MB.
**Inputs** : fichier de 10 MB généré en `tmp_path` (contenu reproductible, `bytes(range(256)) * 40_960`).
**Attendu** : hash égal à une constante hexadécimale hardcodée.
**Fixture** : `tmp_path`.
**Statut** : `[NOUVEAU]` — bouche trou audit §5.2 (streaming non testé).

### 3.4 Layer **spatial / mesh UGRID**

#### Test 9 — `test_mesh_topology_face_node_roundtrip`
**Fichier** : `tests/unit/spatial/test_mesh_topology.py`
**Ce qu'on teste** : à partir d'une grille 3×3 structurée, la conversion `rectilinear_to_ugrid(...) → ugrid_to_rectilinear(...)` est idempotente.
**Inputs** : `RectilinearMesh(dx=[1,1,1], dy=[1,1,1])`.
**Attendu** : égalité `face_node_connectivity`, `nodes_xy`, ordonnée lexicographiquement.
**Fixture** : `mini_rectilinear_3x3`.
**Statut** : `[NOUVEAU]`.

#### Test 10 — `test_mesh_handles_degenerate_shapes_1x1_1xN_Nx1`
**Fichier** : `tests/unit/spatial/test_mesh_topology.py`
**Ce qu'on teste** : les grilles dégénérées `(1,1)`, `(1,10)`, `(10,1)` construisent une `HydroMesh` valide avec nombre de faces/arêtes attendu.
**Inputs** : `@pytest.mark.parametrize("nx,ny", [(1,1), (1,10), (10,1), (1,1,1), (2,3,1)])`.
**Attendu** : `mesh.face_count == nx*ny`, `mesh.edge_count == expected_edges(nx, ny)`.
**Statut** : `[NOUVEAU]` — comble lacune explicite audit §2.3.

#### Test 11 — `test_field_param_resolves_mesh_zones_with_defaults`
**Fichier** : `tests/unit/spatial/test_field_param_resolve.py`
**Ce qu'on teste** : `FieldParam.resolve(mesh)` applique le bon `value` par `zone_id`, et le `default` aux cellules hors zones.
**Inputs** : mesh 10×10, 3 zones polygonales couvrant 30/30/30 cellules (10 orphelines).
**Attendu** : histogramme des valeurs = `{v1: 30, v2: 30, v3: 30, v_default: 10}`.
**Fixture** : `zoned_mesh_10x10`.
**Statut** : `[REFACTORE]` depuis `test_field_param.py` (recadré sur l'API publique).

### 3.5 Layer **process (flow / transport)**

#### Test 12 — `test_flow_config_rejects_incompatible_bcs`
**Fichier** : `tests/unit/process/test_flow_config.py`
**Ce qu'on teste** : un `FlowConfig` avec `active_bc=["stream"]` mais sans `forcing.stream` lève `MissingForcingError` à la validation.
**Inputs** : config avec BC déclarée sans payload correspondant.
**Attendu** : `ValidationError` ou `MissingForcingError` avec le nom BC.
**Fixture** : aucune.
**Statut** : `[REFACTORE]` depuis `test_flow_config_dirichlet.py`.

#### Test 13 — `test_flow_initial_conditions_inline_units_parse`
**Fichier** : `tests/unit/process/test_flow_initial_conditions.py`
**Ce qu'on teste** : `FlowInitialConditions(head="150 m")`, `head="15 m"` et `head=15.0` aboutissent à la même valeur SI.
**Inputs** : strings `"150 m"`, `"15000 mm"`, `150.0` (float implicite m).
**Attendu** : `ic.head_value == 150.0` dans les 3 cas.
**Statut** : `[REFACTORE]` depuis `test_flow_param_inline_units.py`.

### 3.6 Layer **solver — Protocol + Boussinesq assembly**

#### Test 14 — `test_solver_registry_discovers_entry_points`
**Fichier** : `tests/unit/solver/test_plugin_registry.py`
**Ce qu'on teste** : 3 plugins fictifs déclarés via `importlib.metadata.EntryPoint` (stub) sont trouvés par `SolverRegistry.discover()`.
**Inputs** : monkeypatch sur `importlib.metadata.entry_points` pour injecter `DummyPluginA/B/C`.
**Attendu** : `registry.list() == {"dummy_a", "dummy_b", "dummy_c"}`, dispatch `registry.get("dummy_a")` OK.
**Fixture** : `stub_entry_points`.
**Statut** : `[NOUVEAU]` — contrat doc 05 jamais testé.

#### Test 15 — `test_capabilities_mismatch_raises_before_run`
**Fichier** : `tests/unit/solver/test_capabilities_matching.py`
**Ce qu'on teste** : `SimulationPlanner` refuse un plan `transport=True` sur un plugin dont `capabilities.transport is False`.
**Inputs** : plugin stub `nwt_no_transport`, config `[transport]`.
**Attendu** : `IncompatibleCapabilitiesError`, avec listage des capacités manquantes.
**Statut** : `[NOUVEAU]`.

#### Test 16 — `test_boussinesq_jacobian_partition_triplets_3x3`
**Fichier** : `tests/unit/solver/boussinesq/test_jacobian_partition.py`
**Ce qu'on teste** : sur un maillage trivial 3×3 homogène, la fabrique de Jacobien renvoie une matrice CSR pentadiagonale symétrique avec sommes de lignes = 0 (flux conservé).
**Inputs** : `HydroMesh(3,3)`, `K=1`, `Sy=0.1`.
**Attendu** : `J.shape == (9,9)`, `J.nnz == 33` (5×3+3×2+3×2+... selon stencil), `np.allclose(J @ np.ones(9), 0, atol=1e-12)` (somme nulle par conservation).
**Fixture** : `mini_rectilinear_3x3`.
**Statut** : `[NOUVEAU]` — **bouche trou critique** audit §5.1 (runtime Boussinesq jamais testé unitairement).

#### Test 17 — `test_boussinesq_runtime_scipy_sparse_analytical_3x3`
**Fichier** : `tests/unit/solver/boussinesq/test_runtime_scipy_sparse.py`
**Ce qu'on teste** : résoudre `K∇²h = -R` en régime permanent sur un domaine 3×3 avec `h=0` Dirichlet au bord, `R=0` — la solution exacte est `h=0` partout (convergence en 1 itération).
**Inputs** : problème trivial avec solution connue.
**Attendu** : `np.allclose(h_solved, 0, atol=1e-14)`, `n_iter == 1`.
**Statut** : `[NOUVEAU]` — premier verrou unitaire sur le moteur.

### 3.7 Layer **results / catalog / metrics**

#### Test 18 — `test_catalog_schema_version_migration_raises_on_downgrade`
**Fichier** : `tests/unit/results/test_catalog_schema.py`
**Ce qu'on teste** : ouvrir un catalog `_schema_version=5` avec un code qui supporte `_schema_version=3` lève `SchemaVersionTooNewError` (pas un `except Exception` silencieux).
**Inputs** : DuckDB in-memory avec table `_schema_version` forcée à 5.
**Attendu** : exception typée, message explicite.
**Fixture** : `in_memory_catalog`.
**Statut** : `[REFACTORE]` depuis `test_catalog_schema.py` (ajoute la branche downgrade).

#### Test 19 — `test_metric_nse_kge_hypothesis_properties`
**Fichier** : `tests/unit/results/test_metrics_nse_kge.py`
**Ce qu'on teste** : propriétés mathématiques des métriques (NSE, KGE, KGE', RMSE, PBIAS) :
- NSE(x, x) == 1.0 (identité parfaite)
- NSE(obs, mean(obs)) == 0.0 (le modèle moyenne est la référence)
- KGE décomposé (α, β, r) retrouve KGE classique
- RMSE ≥ 0, nul ssi obs == sim
- toutes sont NaN-safe si len(finite) < 2

**Inputs** : `@given(arrays(float64, shape=(100,), elements=st.floats(-100, 100)))`.
**Attendu** : propriétés vérifiées sur 100 exemples Hypothesis.
**Fixture** : aucune.
**Statut** : `[NOUVEAU]` — pas de test actuel des métriques hors assertion ad-hoc.

```python
# Squelette
from hypothesis import given, strategies as st
import numpy as np
from hydromodpy.results.metrics import nse, kge_2012, rmse

@given(arr=st.lists(st.floats(-100, 100, allow_nan=False), min_size=10, max_size=100))
def test_nse_identity_is_one(arr):
    x = np.asarray(arr)
    assert np.isclose(nse(x, x), 1.0, atol=1e-12)

@given(arr=st.lists(st.floats(-100, 100, allow_nan=False), min_size=10, max_size=100)
       .filter(lambda l: np.std(l) > 1e-6))
def test_nse_mean_predictor_is_zero(arr):
    obs = np.asarray(arr)
    sim = np.full_like(obs, obs.mean())
    assert np.isclose(nse(obs, sim), 0.0, atol=1e-10)
```

### 3.8 Layer **simulation (planner / API)**

#### Test 20 — `test_simulation_plan_is_frozen_and_deterministic`
**Fichier** : `tests/unit/simulation/test_simulation_plan.py`
**Ce qu'on teste** : `SimulationPlan` est `frozen=True` ; 2 appels `SimulationPlanner.build(same_config)` produisent des plans égaux et avec le même `plan_hash`.
**Inputs** : config déterministe.
**Attendu** : `plan_a == plan_b`, `hash(plan_a) == hash(plan_b)`, `pytest.raises(FrozenInstanceError, plan_a.__setattr__, ...)`.
**Statut** : `[NOUVEAU]` — pilier du doc 06 (plan immuable).

### 3.9 Récap : répartition des 20 tests critiques

| Couche | # tests | Fichier unique ou groupé | Pourquoi critique |
|---|---|---|---|
| Config Pydantic | 3 | `core/test_config_validation.py` | Porte d'entrée utilisateur |
| Units | 2 | `core/test_units_conversion.py` | Toute erreur se propage partout |
| Data planner | 3 | `data/test_data_planner.py` + `test_provenance_hash.py` | Hashing + inférence mal testés |
| Mesh | 3 | `spatial/test_mesh_topology.py` + `test_field_param_resolve.py` | Contrats UGRID (doc 03) |
| Process | 2 | `process/test_flow_config.py` + `test_flow_initial_conditions.py` | Forçage mal testé |
| Solver contrat + Boussinesq | 4 | `solver/test_plugin_registry.py`, `test_capabilities_matching.py`, `boussinesq/*` | Moteur numérique post-merge |
| Catalog + metrics | 2 | `results/test_catalog_schema.py` + `test_metrics_nse_kge.py` | Fondation stockage + calibration |
| Simulation plan | 1 | `simulation/test_simulation_plan.py` | Immutabilité du plan |
| **Total** | **20** | ~11 fichiers | |

---

<a id="4-integration"></a>
## 4. Les 5 scénarios d'intégration essentiels

Chaque scénario teste **l'interface entre deux ou trois modules**, sur une mini-maille. Budget **≤ 5 s** par test. Chaque test est un **smoke complet** du chemin : si tous passent, `hmp run` ne peut pas exploser sur un cas trivial. Tous `[NOUVEAU]`.

### 4.1 Scénario 1 — `Config → Run → Results` par solveur (mini)

**Fichiers** :
- `tests/integration/test_config_to_run_nwt_mini.py`
- `tests/integration/test_config_to_run_mf6_mini.py`
- `tests/integration/test_config_to_run_boussinesq_mini.py`

**Objectif** : valider la chaîne complète `TOML → HydroModPyConfig → SimulationPlan → SolverRunner → SimulationCatalog` sur une maille 5×5, 1 couche, 3 timesteps, K homogène, charge Dirichlet bord sud, recharge uniforme.

**Mesh** : `HydroMesh.rectangular(nx=5, ny=5, dx=100, dy=100, nlay=1)` (générée par `_helpers/fixtures_mesh.py`).
**Config** : TOML templaté dans `_helpers/configs/mini_<solver>.toml`.
**Attendu** :
- `simulation.run()` retourne sans exception
- `catalog.simulations.iloc[0].status == "completed"`
- charge finale ∈ [min_bc, max_bc]
- mass balance résiduelle < 1 %
- une clé `head` présente dans le Zarr avec shape `(3, 1, 25)`
- `sim.plot("watertable_map", save=tmp_path / "fig.png")` produit un PNG > 1 KB

**Budget** : 3 s par solveur, 9 s total. À comparer aux **3 600 s** actuels (test régression `fast` NWT/MF6) — facteur ×400.

**Squelette** :

```python
# tests/integration/test_config_to_run_mf6_mini.py
import pytest
from pathlib import Path
import hydromodpy as hmp

@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
def test_mf6_mini_config_to_results(workspace_tmp, mini_mf6_config_path):
    cfg = hmp.load_config(mini_mf6_config_path)
    with hmp.open(workspace_tmp) as catalog:
        sim_id = hmp.run(cfg, workspace=workspace_tmp)
        sim = catalog.simulation(sim_id)
        assert sim.status == "completed"
        head = sim.field("head", timestep=-1)
        assert head.shape == (1, 25)
        mb = sim.mass_balance()
        assert abs(mb["residual_rel"]) < 0.01
```

### 4.2 Scénario 2 — Pipeline de chargement de données

**Fichier** : `tests/integration/test_data_pipeline_hydrometry.py` (+ 1 jumeau piezometry).

**Objectif** : valider `DataLoadPlan → Manager → Cache → Contract`.

**Sources** : fixtures CSV versionnées (pas de réseau) : 30 jours d'une station fictive, 2 variables. Placées sous `_helpers/data_fixtures/hydrometry_mock/`.

**Attendu** :
- `HydrometryManager.load(plan)` retourne un `LoadResult` conforme au contrat (colonnes : `time`, `station_id`, `value`, `unit`).
- Cache DuckDB miroir vérifié (même SHA-256).
- 2ème load depuis cache : pas d'appel manager (fait via fixture `no_http`).
- Si le contrat est violé (colonne manquante injectée), `ContractViolationError` avec champ exact.

**Budget** : 2 s.

### 4.3 Scénario 3 — Round-trip catalog export/import

**Fichier** : `tests/integration/test_catalog_import_export_roundtrip.py`.

**Objectif** : valider que `catalog.export_simulation(sim_id, path)` puis `catalog2.import_simulation(path)` conservent l'intégralité des données (DuckDB tables + Zarr arrays + geographic_features).

**Scénario** :
1. Fixture `sim_with_full_content` : simulation fictive déjà peuplée (head, 3 stations timeseries, 2 metrics, 5 zones geographic_features, provenance).
2. `export_simulation(sim_id, tmp_path / "pkg.hmp")`.
3. Ouvrir un catalog vierge, `import_simulation(tmp_path / "pkg.hmp")`.
4. Comparer toutes les tables (SQL `EXCEPT`) et les Zarr arrays (xr.testing.assert_identical).
5. Vérifier `_schema_version` préservé.

**Budget** : 2 s.

### 4.4 Scénario 4 — Calibration twin mini (CMA-ES)

**Fichier** : `tests/integration/test_calibration_cma_es_twin_mini.py`.

**Objectif** : valider l'interface `calibration engine → solver runner → metrics → catalog_calibration_sessions`.

**Scénario** : problème twin 2D 5×5, 2 paramètres (K, Sy), vérité connue, CMA-ES popsize=8, max 5 iterations. Budget ≤ 4 s (vs 2 722 LOC actuels de `test_model_calibration_launcher.py`).

**Attendu** :
- `calibration_sessions` a 1 ligne, `status="completed"`
- `calibration_iterations` a ≥ 3 lignes
- paramètre recouvré à ±20 % (tolerance large, on teste la plomberie pas la convergence)
- best `sim_id` existe dans `simulations` et est pointable via `session.best_sim_id`

### 4.5 Scénario 5 — Comparaison multi-solveurs + export figures

**Fichier** : `tests/integration/test_comparison_multi_solver.py`.

**Objectif** : valider `SimulationGroup.pivot()`, `compare_figures()`, export PNG/NetCDF, en headless.

**Scénario** : 3 simulations fictives (NWT/MF6/Boussinesq) sur la même config mini, déjà dans le catalog. `group = catalog.find(project="compare_test")`.

**Attendu** :
- `group.pivot("nse", index="station_id", columns="sim_id")` : DataFrame 3 colonnes, 2 stations.
- `group.compare_figure("watertable_map", save_dir=tmp_path)` : 3 PNG + 1 PDF composite.
- `group.export("netcdf", tmp_path / "compare.nc")` : fichier CF-1.11 conforme (vérifié avec `cf-checker` si dispo).

**Budget** : 3 s.

### 4.6 Budget total intégration

| Scénario | Solveurs | Budget |
|---|---|---|
| 1a - NWT mini | NWT | 3 s |
| 1b - MF6 mini | MF6 | 3 s |
| 1c - Boussinesq mini | Boussinesq | 3 s |
| 2 - Data pipeline | — | 2 s × 2 = 4 s |
| 3 - Catalog roundtrip | — | 2 s |
| 4 - Calib twin | MF6 | 4 s |
| 5 - Comparison | — | 3 s |
| Fixtures init (session) | — | ~5 s |
| **Total** | | **~27 s + parallélisation** |

Avec `-n auto` sur 4 workers et `--dist=loadfile` → **~10 s**. Contre les **~45 min** de la suite régression actuelle.

---

<a id="5-validation-scientifique"></a>
## 5. Benchmarks analytiques et MMS

### 5.1 Principe

La validation répond à **une seule question** : *le code résout-il l'équation à l'ordre attendu ?* Pas « ça tourne », pas « la sortie ressemble » — **l'ordre de convergence**.

Trois cas **obligatoires** (cf. audit §4.2, §4.4) + 2 MMS. Chaque cas a une **solution analytique connue** et une **analyse `h`-convergence** intégrée.

### 5.2 Benchmark obligatoire 1 — Theis 1935 (confined transient pumping)

**Fichier** : `tests/validation/analytical/transient/test_theis_confined_pumping_2d.py`
**Statut** : `[NOUVEAU]` — comble le trou critique audit §4.2.

**Problème** : aquifère captif homogène infini, puits unique au centre, débit constant Q, charge initiale uniforme. Solution analytique : `s(r,t) = Q/(4πT) × W(u)` avec `u = r²S/(4Tt)`, `W(u)` fonction de puits (integrale exponentielle).

**Domaine** : 201×201 cellules de 10 m, nettoyage des effets de bord en ignorant les 20 cellules bordières.
**Paramètres** : T=10⁻³ m²/s, S=10⁻⁴, Q=10⁻³ m³/s, durée 1 jour (86 400 s), 100 pas logarithmiques.
**Critère** : à `r ∈ {50, 100, 200, 500}` m et `t ∈ {100 s, 1 h, 1 d}` :
- NSE(s_analytic, s_simulated) > 0.999
- RMSE < T·Q/(50) (tolerance physique, documentée dans header)
- Ordre observé `h`-convergence ≥ 1.9 sur grilles [201, 401, 801]

**Solveurs** : MF6 (natif confiné), NWT (confiné possible via Upw unconfined=False), Boussinesq (skip avec `pytest.skip("unconfined only")`).
**Budget** : 20 s / solveur.

```python
# Squelette
import numpy as np
from scipy.special import exp1  # W(u) = E1(u)

def theis_analytic(r, t, T, S, Q):
    u = r**2 * S / (4 * T * t)
    return Q / (4 * np.pi * T) * exp1(u)

@pytest.mark.validation
@pytest.mark.parametrize("solver", ["mf6", "nwt"])
def test_theis_confined_pumping(solver, tmp_path):
    grid = build_radial_grid(nx=201, ny=201, dx=10)
    sim = run_theis_case(grid, solver=solver, workspace=tmp_path)
    s_sim = sim.field("drawdown", timestep=-1)
    s_ana = theis_analytic(r=grid.radial_dist, t=86400, T=1e-3, S=1e-4, Q=1e-3)
    mask = (grid.radial_dist > 50) & (grid.radial_dist < 500)
    assert nse(s_ana[mask], s_sim[mask]) > 0.999

@pytest.mark.validation
@pytest.mark.slow
def test_theis_convergence_order(tmp_path):
    orders = []
    for nx in [101, 201, 401]:
        err = run_and_measure_error(nx, tmp_path / f"{nx}")
        orders.append((nx, err))
    slope = convergence_slope(orders)
    assert 1.8 < slope < 2.2  # spatial order 2 expected
```

### 5.3 Benchmark obligatoire 2 — Hantush-Jacob 1955 (leaky aquifer)

**Fichier** : `tests/validation/analytical/transient/test_hantush_jacob_leaky_2d.py`
**Statut** : `[NOUVEAU]`.

**Problème** : aquifère captif drainé par un aquitard semi-perméable. Solution : `s(r,t) = Q/(4πT) × W(u, r/B)` avec `B = √(Tb'/K')`.

**Critère** : NSE > 0.99 contre `W(u, r/B)` tabulée (référence Hantush 1964 OFR). Ordre spatial ≥ 1.9.

**Solveurs** : MF6 uniquement (NWT ne gère pas le terme drainage `λ`).
**Budget** : 30 s.

### 5.4 Benchmark obligatoire 3 — Ogata-Banks 1961 (transport 1D advection-dispersion)

**Fichier** : `tests/validation/analytical/transient/test_ogata_banks_transport_1d.py`
**Statut** : `[NOUVEAU]` — bouche **trou critique transport** audit §4.2.

**Problème** : 1D semi-infini, écoulement uniforme `v`, dispersion `D`, injection continue `C₀` à x=0.
Solution : `C(x,t)/C₀ = 0.5·[erfc((x-vt)/(2√(Dt))) + exp(vx/D)·erfc((x+vt)/(2√(Dt)))]`.

**Domaine** : 200 cellules de 1 m, v=0.01 m/s, D=10⁻⁴ m²/s, Péclet local = 100 (advection dominée — test exigeant).
**Critère** : profil à `t=1 h, 6 h, 24 h`, NSE > 0.95, numerical dispersion estimée < 5 % de D physique.
**Solveurs** : MF6-GWT, MT3DMS-via-NWT.
**Budget** : 20 s.

### 5.5 MMS obligatoire 1 — Laplacien stationnaire 1D

**Fichier** : `tests/validation/mms/test_mms_laplacian_steady_1d.py`
**Statut** : `[NOUVEAU]`.

**Problème manufacturé** : on choisit `h(x) = sin(πx/L)`, on injecte `h` dans `K∇²h = -f(x)` et on déduit `f(x) = Kπ²/L² sin(πx/L)`. Le code doit retrouver `h_exact` à l'ordre 2 en `h`-raffinement.

**Grilles** : 10, 20, 40, 80, 160 cellules.
**Critère** : pente log-log `L²(err) vs h` ∈ [1.8, 2.2] (ordre 2 attendu pour FD centered/MF6).

**Solveurs** : MF6, NWT, Boussinesq.

```python
def manufactured_source(x, L, K=1.0):
    return K * (np.pi / L)**2 * np.sin(np.pi * x / L)

def manufactured_exact(x, L):
    return np.sin(np.pi * x / L)

@pytest.mark.validation
@pytest.mark.parametrize("solver", ["mf6", "nwt", "boussinesq"])
def test_mms_laplacian_order_2(solver, tmp_path):
    errors = []
    for n in [10, 20, 40, 80, 160]:
        h = run_mms_1d(n, solver, tmp_path / f"n{n}")
        err = np.linalg.norm(h - manufactured_exact(grid_x(n), L=1.0)) / np.sqrt(n)
        errors.append((1.0 / n, err))
    slope = fit_log_slope(errors)
    assert 1.8 < slope < 2.2, f"{solver}: slope={slope:.3f}"
```

### 5.6 MMS obligatoire 2 — Diffusion transitoire 1D

**Fichier** : `tests/validation/mms/test_mms_diffusion_transient_1d.py`
**Statut** : `[NOUVEAU]`.

**Problème manufacturé** : `h(x,t) = cos(ωt) sin(πx/L)`, on injecte → source analytique.
**Critères** : ordre 2 en `h` (log-log fit), ordre 1 ou 2 en `Δt` selon schéma (Euler implicite vs Crank-Nicolson — docstring du test précise).

### 5.7 Twins de calibration — étendus

**Fichiers** : `tests/validation/twins/test_twin_calibration_{nwt,boussinesq}.py`
**Statut** : `[NOUVEAU]` pour NWT et Boussinesq (MF6 `[CONSERVE]`).

Assertion minimale : `|K_recovered - K_true| / K_true < 0.05` sur un problème Dupuit 1D avec bruit gaussien 5 % sur observations synthétiques.

### 5.8 Tolérances — le fichier `TOLERANCES.md`

**Chemin** : `tests/TOLERANCES.md` (et symlink `validation_cases/TOLERANCES.md`).
**Statut** : `[NOUVEAU]` — résout audit §4.3.

Format :

```markdown
# Tolérances des benchmarks de validation

## Principe
Chaque tolérance est justifiée par l'une des 3 sources suivantes :
1. **Analyse de Richardson** : extrapolation de l'erreur de grille à h → 0.
2. **Machine epsilon** : `10·ε·‖f‖` pour solutions analytiques sans discrétisation.
3. **Reference literature** : tolérance publiée dans un benchmark standardisé
   (ex. MacDonald & Harbaugh 1996, USGS OFR 96-485).

Toute tolérance sans rationale attribuée est un bug de ce fichier.

## Tableau
| Test | Metric | Tolerance | Source | Notes |
|---|---|---|---|---|
| theis_confined_pumping_2d | NSE | > 0.999 | Richardson, K=1 | Grille 201×201 suffisante pour n=2 |
| theis_confined_pumping_2d | RMSE_mm | < 0.5 | 5·ε·(Q·t/T) | … |
| ogata_banks_1d | NSE | > 0.95 | Zheng & Wang 1999 | Péclet 100 borderline |
| mms_laplacian_1d | slope | ∈ [1.8, 2.2] | théorie FD centré ordre 2 | — |
| dupuit_fixed_head_1d_nwt | RMSE | < 0.05 m | N/A | **À REVOIR** — tolérance fittée |
```

**Action immédiate sur l'existant** : annoter les 50 tolerances TOML existantes, marquer « À REVOIR » celles sans rationale (≥ 80 % selon audit §4.3).

---

<a id="6-golden-files"></a>
## 6. Golden files — maintenir ou remplacer ?

### 6.1 Verdict

**On les garde**, mais sous forme **profondément simplifiée**. La richesse des signatures passe avant le nombre de points goldén.

### 6.2 Ce qui change

| Aspect | Actuel (audit §3.2) | Cible |
|---|---|---|
| Stats | `{count, mean, p50, p95, shape, sum, timestep}` dernier pas | `{count, min, p05, p25, p50, p75, p95, max, mean, std, sum, moment_1}` sur `t ∈ {0, N//2, N-1}` |
| Format | JSON par champ | JSON par simulation, indenté, stable (clés triées) |
| Localisation | `tests/regression/reference/golden_references/{fast,extensive,normal}/` | `tests/validation/signatures/{benchmark}/` (près du cas), `tests/e2e/signatures/` |
| Tolérance | `rel=1e-4`, `abs=1e-6` fixes | Par-champ, documentés dans `TOLERANCES.md` |
| Update | `pytest --update-goldens` silencieux | `hmp test goldens update --diff` (affiche le diff, demande confirmation) |
| Hash spatial | absent | `moment_1 = sum(arr * arange(size))` — détecte permutations |
| Sanity hash | absent | SHA-256 du JSON stable, checké en CI (détecte édition manuelle cassée) |

### 6.3 Module cible `tests/_helpers/signatures.py`

**Statut** : `[REFACTORE]` depuis `tests/regression/golden_utils.py` (1 104 LOC). Scindé en 4 fichiers ≤ 300 LOC.

```
_helpers/
├── signatures.py          # array_signature(), modflow_signature(), catalog_signature()
├── signature_io.py        # load_json_signature(), dump_json_signature() avec tri stable
├── signature_assertions.py # assert_signature_matches(), assert_stats_match()
└── signature_cli.py       # interface CLI pour --update-goldens avec diff
```

**API publique** :

```python
# tests/_helpers/signatures.py
from dataclasses import dataclass, asdict
import numpy as np

@dataclass(frozen=True)
class FieldSignature:
    count: int
    min: float; max: float
    p05: float; p25: float; p50: float; p75: float; p95: float
    mean: float; std: float; sum: float
    moment_1: float  # Σ arr[i]·i
    shape: tuple[int, ...]
    dtype: str

    @classmethod
    def from_array(cls, arr: np.ndarray) -> "FieldSignature":
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            return cls(count=0, min=np.nan, max=np.nan, p05=np.nan, p25=np.nan,
                       p50=np.nan, p75=np.nan, p95=np.nan, mean=np.nan, std=np.nan,
                       sum=np.nan, moment_1=np.nan, shape=arr.shape, dtype=str(arr.dtype))
        q = np.quantile(finite, [0.05, 0.25, 0.50, 0.75, 0.95])
        return cls(
            count=int(finite.size),
            min=float(finite.min()), max=float(finite.max()),
            p05=float(q[0]), p25=float(q[1]), p50=float(q[2]), p75=float(q[3]), p95=float(q[4]),
            mean=float(finite.mean()), std=float(finite.std(ddof=0)),
            sum=float(finite.sum()),
            moment_1=float(np.sum(finite * np.arange(finite.size))),
            shape=tuple(arr.shape), dtype=str(arr.dtype),
        )

def assert_signature_matches(
    actual: FieldSignature,
    expected: FieldSignature,
    *,
    rel: float = 1e-4,
    abs_: float = 1e-6,
    fields: tuple[str, ...] = ("min", "p25", "p50", "p75", "max", "mean", "std", "sum", "moment_1"),
) -> None:
    """Raise AssertionError listing ALL mismatching fields, not only the first."""
    mismatches = []
    for f in fields:
        a, e = getattr(actual, f), getattr(expected, f)
        if not np.isclose(a, e, rtol=rel, atol=abs_, equal_nan=True):
            mismatches.append(f"{f}: actual={a:.6g}, expected={e:.6g}")
    if mismatches:
        raise AssertionError("Signature mismatch:\n  " + "\n  ".join(mismatches))
```

### 6.4 CLI d'update

```bash
# Nouveau : affiche les deltas avant écriture
hmp test goldens update --test test_theis_confined_pumping_2d --diff
# Affiche :
#   theis/head_t_last:
#     mean:    actual=1.234e-02, golden=1.233e-02  (Δ=+0.08%)
#     p95:     actual=5.678e-02, golden=5.670e-02  (Δ=+0.14%)
#   [Y]es / [N]o / [e]dit manuellement: y
# Écrit le JSON et git-log la modification avec l'auteur + timestamp
```

**Implémentation** : sous-commande `hmp test goldens update` dans `hydromodpy/runners/test_cli.py` `[NOUVEAU]`, déléguant à `_helpers/signature_cli.py`.

### 6.5 Déterminisme cross-platform

Un golden généré sur Linux doit passer sur macOS et Windows. Pour y arriver :

1. **Single-thread BLAS obligatoire** : fixture autouse `openblas_single_threaded` qui force `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `OMP_NUM_THREADS=1` au début de session.
2. **Seed global** : `conftest.py` pose `np.random.seed(0)`, `random.seed(0)`.
3. **Arithmétique flottante bornée** : tolérance par défaut `rel=1e-8` pour sorties bien-posées (solveurs directs), relâchée à `rel=1e-4` pour itératifs (Newton, CG) — **documenté dans `TOLERANCES.md`**.
4. **Pas de timestamp dans les goldens** : les métadonnées temporelles sont exclues de la signature (`exclude_keys=("created_at", "hostname")`).
5. **Test sanity cross-plateforme** : en CI, un job spécial `goldens_macos` et `goldens_windows` (nightly) exécute `hmp test validation --check-goldens` sans update. Une divergence plateforme-spécifique émet un warning dans le log, pas un fail (à ce stade expérimental). Sera durci après 3 mois de données.

### 6.6 Taille des signatures

| Test | # champs | Taille JSON |
|---|---|---|
| `dupuit_fixed_head_1d_mf6` | 3 champs × 3 timesteps × 12 stats | ~3 KB |
| `theis_confined_pumping_2d_mf6` | 2 champs × 3 ts × 12 stats | ~2 KB |
| `headwater_100km2_pulse` | 8 champs × 3 ts × 12 stats | ~8 KB |

Au total, ≈ 150 KB de goldens versionnés (vs plusieurs MB actuellement). Revue de changement trivial.

---

<a id="7-infrastructure-pytest"></a>
## 7. Infrastructure pytest

### 7.1 `tests/conftest.py` idéal

**Objectif** : ≤ 80 LOC, une responsabilité = scratch root + markers auto.

```python
# tests/conftest.py — version cible (~75 LOC)
"""Racine conftest HydroModPy — minimale, pas d'autouse global ciblé."""
from __future__ import annotations
import os
import random
import tempfile
from pathlib import Path

import numpy as np
import pytest

_SCRATCH = Path(
    os.environ.get("HYDROMODPY_TEST_SCRATCH_ROOT")
    or Path(tempfile.gettempdir()) / "hydromodpy_tests"
).expanduser().resolve()
_SCRATCH.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("HYDROMODPY_TEST_SCRATCH_ROOT", str(_SCRATCH))
os.environ.setdefault("TZ", "UTC")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("RAYON_NUM_THREADS", "1")

_TIMEOUTS = {"unit": 2.0, "integration": 8.0, "validation": 120.0, "e2e": 900.0}
_LAYER_DIRS = {"unit": "unit", "integration": "integration",
               "validation": "validation", "e2e": "e2e"}


def pytest_addoption(parser):
    parser.addoption("--update-goldens", action="store_true", default=False,
                     help="Rewrite validation/e2e signature JSONs after confirmation.")


@pytest.fixture(scope="session")
def update_goldens(request):
    return bool(request.config.getoption("--update-goldens"))


@pytest.fixture(scope="session")
def scratch_root() -> Path:
    return _SCRATCH


@pytest.fixture(autouse=True)
def _deterministic_seeds():
    """Remet les seeds à 0 avant chaque test — cross-test reproducibility."""
    np.random.seed(0)
    random.seed(0)


def pytest_collection_modifyitems(config, items):
    """Auto-tag par chemin + application des timeouts par layer."""
    for item in items:
        for layer, dirname in _LAYER_DIRS.items():
            if dirname in Path(str(item.fspath)).parts:
                item.add_marker(getattr(pytest.mark, layer))
                item.add_marker(pytest.mark.timeout(_TIMEOUTS[layer]))
                break
```

**Ce qui disparaît** (cf. conftest actuel) :
- `_redirect_repo_root_cwd_for_gmsh_grid_tests` autouse global → déplacé dans `tests/integration/mesh/conftest.py` local (cf. audit §6.1).
- `pytest_sessionfinish` `rmtree` → retiré ; `tmp_path_factory` de pytest gère le cleanup atomiquement.
- `pytest_ignore_collect` → supprimé (code mort).

### 7.2 Hook de guard anti-subprocess dans `unit/`

**Statut** : `[NOUVEAU]` — bouche trou audit §2.2.

```python
# tests/unit/conftest.py
import pytest
from unittest import mock

@pytest.fixture(autouse=True)
def _forbid_subprocess_in_unit(request):
    """Fail fast si un test unit/ tente subprocess.run/Popen/call."""
    with mock.patch("subprocess.Popen", side_effect=RuntimeError(
        "subprocess is forbidden in unit/ — move this test to integration/ or e2e/"
    )):
        yield
```

**Effet** : tout test unit/ qui tenterait un `subprocess.run(["mf6"])` échoue immédiatement avec un message actionnable.

### 7.3 Fixtures partagées — `_helpers/fixtures_*.py`

Trois familles, toutes avec **scope explicite** et **déterminisme documenté**.

#### 7.3.1 `_helpers/fixtures_mesh.py`

```python
import pytest
from hydromodpy.spatial import HydroMesh

@pytest.fixture(scope="session")
def mini_rectilinear_3x3() -> HydroMesh:
    """Grille structurée 3×3, dx=dy=1m, 1 couche — pour tests unitaires."""
    return HydroMesh.rectangular(nx=3, ny=3, dx=1.0, dy=1.0, nlay=1)

@pytest.fixture(scope="session")
def mini_rectilinear_5x5_nlay2() -> HydroMesh:
    return HydroMesh.rectangular(nx=5, ny=5, dx=100.0, dy=100.0, nlay=2)

@pytest.fixture(scope="module")
def radial_grid_201(tmp_path_factory) -> HydroMesh:
    """Grille 201×201 pour Theis — lourd, scope module."""
    return HydroMesh.rectangular(nx=201, ny=201, dx=10.0, dy=10.0, nlay=1)

@pytest.fixture(params=[(1, 1), (1, 10), (10, 1), (2, 3), (3, 3)])
def degenerate_mesh(request) -> HydroMesh:
    """Grilles 1D dégénérées pour edge cases (audit §2.3)."""
    nx, ny = request.param
    return HydroMesh.rectangular(nx=nx, ny=ny, dx=1.0, dy=1.0, nlay=1)
```

#### 7.3.2 `_helpers/fixtures_catalog.py`

```python
import pytest
from hydromodpy.results import SimulationCatalog

@pytest.fixture
def in_memory_catalog(tmp_path) -> SimulationCatalog:
    """Catalog DuckDB :memory: (pas de Zarr). Test unitaires de schema."""
    return SimulationCatalog.open(":memory:", create_if_missing=True)

@pytest.fixture
def populated_catalog(tmp_path):
    """Catalog avec 3 sims fictives (NWT/MF6/Boussinesq), 2 timeseries, 1 metric."""
    cat = SimulationCatalog.open(tmp_path / "wsp", create_if_missing=True)
    _seed_three_simulations(cat)
    yield cat
    cat.close()
```

#### 7.3.3 `_helpers/strategies.py` (Hypothesis)

```python
import numpy as np
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

finite_arrays = arrays(
    dtype=np.float64,
    shape=st.integers(10, 200),
    elements=st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False),
)

positive_hk = st.floats(1e-8, 1e2)
valid_porosity = st.floats(0.01, 0.5)
valid_heads_array = arrays(np.float64, shape=(10, 10, 10),
                            elements=st.floats(0.0, 1000.0, allow_nan=False))
```

### 7.4 `pytest.ini` cible

**Statut** : `[NOUVEAU]` — sort de `pyproject.toml` pour lisibilité.

```ini
# tests/pytest.ini
[pytest]
minversion = 8.0
testpaths = tests
pythonpath = .
addopts =
    --strict-markers
    --strict-config
    --tb=short
    --durations=20
    --durations-min=0.1
    -ra
markers =
    unit: tests unitaires purs (≤ 200 ms, pas d'I/O lourd)
    integration: scénarios multi-modules (≤ 5 s)
    validation: benchmarks scientifiques (ordre de convergence)
    e2e: bout-en-bout avec subprocess/binaires (≤ 10 min)
    smoke: sous-ensemble rapide pour pré-commit
    slow: override budget (justifier le marker)
    nwt: MODFLOW-NWT
    mf6: MODFLOW 6
    boussinesq: Boussinesq natif
    petsc: nécessite PETSc
    binary: nécessite un binaire externe
    network: nécessite Internet
    gpu: nécessite GPU
filterwarnings =
    error
    ignore::DeprecationWarning:flopy
    ignore::PendingDeprecationWarning:matplotlib
log_cli = false
log_level = WARNING
xfail_strict = true
```

### 7.5 `hypothesis` profile

```python
# tests/conftest.py (ajout)
from hypothesis import settings, HealthCheck

settings.register_profile("dev", max_examples=50, deadline=1000)
settings.register_profile("ci", max_examples=100, deadline=2000,
                          suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("nightly", max_examples=1000, deadline=10_000)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
```

---

<a id="8-pipeline-ci"></a>
## 8. Pipeline CI

### 8.1 Trois profils, une matrice claire

| Profil | Trigger | Contenu | Budget | Blocant ? |
|---|---|---|---|---|
| `pre-commit` | hook local pré-commit | `pytest -m smoke` (unit + integration ≤ 500 ms) | ≤ 30 s | Oui localement |
| `pr` (push / PR master) | GH Actions | `pytest -m "unit or integration" -n auto --dist=loadfile` | ≤ 5 min | Oui (bloque merge) |
| `nightly` | cron 02:00 UTC | `pytest -m "validation or e2e" --update-goldens=false` | ≤ 1 h | Non-bloquant, alerte Slack |
| `release` | tag `v*` | `pytest` toute la suite, multi-OS (Linux/macOS/Win), multi-Python (3.11/3.12/3.13) | ≤ 3 h | Oui (bloque release) |

### 8.2 Workflow `ci.yml` cible

**Statut** : `[REFACTORE]` depuis `.github/workflows/coverage.yml`.

```yaml
# .github/workflows/ci.yml — version cible
name: ci
on:
  push:
    branches: [master, dev-*]
  pull_request:
    branches: [master]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -e ".[test]"
      - run: pytest --collect-only -q  # smoke collecte, détecte ModuleNotFound précoce

  unit:
    needs: lint
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -e ".[test]"
      - run: pytest tests/unit/ -n auto --dist=loadfile -v

  integration:
    needs: unit
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -e ".[test]"
      - name: Install modflow binaries
        run: |
          python -m flopy.utils.get_modflow ~/bin
          echo "$HOME/bin" >> $GITHUB_PATH
      - run: pytest tests/integration/ -n 4 --dist=loadfile -v

  validation-nightly:
    if: github.event_name == 'schedule' || contains(github.event.head_commit.message, '[validation]')
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -e ".[test]"
      - run: pytest tests/validation/ -v --durations=40

  coverage:
    needs: [unit, integration]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -e ".[test,coverage]"
      - run: pytest tests/unit/ tests/integration/ --cov=hydromodpy --cov-report=xml
      - uses: codecov/codecov-action@v4
        with:
          files: ./coverage.xml
          flags: core
          fail_ci_if_error: true
```

### 8.3 Coverage cible

```toml
# pyproject.toml — section nettoyée
[tool.coverage.run]
source = ["hydromodpy"]
parallel = true
concurrency = ["multiprocessing", "thread"]
omit = [
    "hydromodpy/**/cases/*",
    "hydromodpy/**/_legacy.py",
    "hydromodpy/runners/__main__.py",
    # calibration_legacy/ et calibration2/ SUPPRIMÉS de l'omit (n'existent pas)
]

[tool.coverage.report]
precision = 1
show_missing = true
skip_covered = true
exclude_lines = [
    "pragma: no cover",
    "raise NotImplementedError",
    "if __name__ == \"__main__\":",
    "if TYPE_CHECKING:",
    "\\.\\.\\.",
]
fail_under = 80  # cible post-refonte
```

### 8.4 Détection de dégradation de performance

Ajout d'un job `perf-guard` nightly qui persiste les durées dans un fichier CSV `tests/_perf/timings.csv` et alerte si la médiane d'un test grimpe de +50 % sur 7 jours. Implémentation via `pytest-benchmark` appliqué aux **5 tests d'intégration du §4 seulement** (pas de micro-benchmarks). Statut `[NOUVEAU]`.

---

<a id="9-degraissage"></a>
## 9. Plan de dégraissage — supprimer 50 % sans perdre confiance

### 9.1 Grands gisements

| Cible | Taille | Action | Gain |
|---|---|---|---|
| `tests/unit/launchers/test_model_calibration_launcher.py` | 2 722 LOC | **Suppression totale**. Remplacer par `tests/integration/test_calibration_cma_es_twin_mini.py` (scénario 4, ≤ 100 LOC) + `tests/unit/analysis/test_calibration_engine.py` (≤ 150 LOC). | ~2 500 LOC |
| `tests/unit/launchers/test_regional_lab_launcher.py` | 735 LOC | Suppression. Remplacer par `tests/integration/test_batch_regional.py` (≤ 80 LOC) + unitaire engine. | ~600 LOC |
| `tests/unit/launchers/test_launcher_run_id.py` | 690 LOC | Suppression. Le `run_id` est testé unitairement dans `tests/unit/core/test_state_context.py`. | ~670 LOC |
| `tests/unit/solver/test_boussinesq_backend.py` | 1 642 LOC | Scinder en 4 fichiers `≤ 350 LOC` dans `tests/unit/solver/boussinesq/` (assembly / jacobian / runtime / smoothing). | +500 LOC nets (meilleure couverture), −1 142 ligne lignes dupliquées |
| `tests/unit/data_managers/test_hydrography_full.py` | 1 643 LOC | Scinder par API externe (OSM / SANDRE / BDTopage) + suppression des mocks redondants. Passer en `tests/integration/` pour le pipeline. | ~900 LOC net supprimés |
| `tests/unit/geographic/test_run_geographic_*_golden.py` (×3) | 265 LOC | Fusion en 1 fichier paramétré `tests/e2e/test_geographic_golden.py`. | ~200 LOC |
| `tests/unit/geographic/test_geographic_legacy_characterization.py` | 519 LOC | Suppression (tests d'implémentation legacy — code réécrit dans doc 01). | ~519 LOC |
| `tests/regression/` (9 fichiers) | 700 LOC + goldens | Fusion dans `tests/validation/` et `tests/e2e/`, avec signatures enrichies §6. | −350 LOC net |
| `tests/support/pytest_timing_distribution.py` | 329 LOC | Déplacement dans `tools/ci/` (pas un helper pytest). | ~329 LOC (déplacé) |
| Mocks redondants dans `tests/unit/launchers/*` | ~338 `monkeypatch.setattr` | Remplacement par injection de dépendance dans le code de prod. | −200 mocks |

### 9.2 Critères de suppression

Un test est **candidat à la suppression** si **un ou plusieurs** critères suivants sont vrais :

1. **Fichier > 500 LOC dans `unit/`** → intégration déguisée (audit §2.2). Soit on casse, soit on migre, soit on supprime.
2. **> 5 `monkeypatch.setattr` dans un seul test** → teste la glu d'orchestration, fragile aux refactors.
3. **Utilise `subprocess` dans `unit/`** → migration obligatoire vers `e2e/`.
4. **Charge un DEM réel (> 100 KB)** dans `unit/` → migration vers `integration/` ou `validation/`.
5. **Duplication** : teste une fonctionnalité déjà couverte par un test plus ciblé.
6. **Teste un chemin d'import** (`import foo; assert foo.BAR == 42`) sans valeur comportementale.
7. **Teste un module marqué legacy** (`_legacy.py`, launchers supprimés en doc 01).
8. **`@pytest.mark.skip` permanent sans ticket d'issue** → dead test.

### 9.3 Liste nominative des 130 fichiers à supprimer/fusionner

Produite automatiquement par le script `tools/tests/audit_unit_purity.py` `[NOUVEAU]` :

```python
# tools/tests/audit_unit_purity.py
"""Génère un rapport CSV des tests unit/ candidates à migration/suppression."""
import ast
import csv
from pathlib import Path

UNIT_DIR = Path("tests/unit")

def audit_file(path: Path) -> dict:
    src = path.read_text()
    tree = ast.parse(src)
    return {
        "path": str(path.relative_to(UNIT_DIR.parent)),
        "loc": len(src.splitlines()),
        "n_monkeypatch": src.count("monkeypatch.setattr"),
        "n_mock": src.count(".mock") + src.count("Mock("),
        "has_subprocess": "subprocess" in src,
        "has_file_io": any(k in src for k in ["open(", ".write(", "rioxarray", "shapefile"]),
        "verdict": _verdict(...)
    }
```

Exécuté à l'étape de dégraissage, sortie CSV revue par un humain avant suppression.

### 9.4 Couverture avant/après

| Avant dégraissage | Après dégraissage |
|---|---|
| 48 000 LOC de tests, couverture 62 % (estimée) | ~18 000 LOC, couverture **cible 80 %** |
| 70 % des tests sont des intégrations déguisées | 75 % unit purs, 17 % intégration, 6 % validation, 2 % e2e |
| Durée suite `unit` : ~10 min | **≤ 45 s en série, ≤ 15 s parallèle** |
| `solver/boussinesq/runtimes/` 0 % unitaire | 85 % unitaire (tests 16-17 + assembly + jacobian) |
| Pas de Theis, Hantush, Ogata-Banks, MMS | 3 benchmarks + 2 MMS avec ordres vérifiés |

---

<a id="10-comparaison-reference"></a>
## 10. Comparaison aux projets de référence

| Projet | Ce qu'on reprend | Ce qu'on ne reprend pas |
|---|---|---|
| **FloPy (USGS)** | Organisation `autotest/`, benchmarks MODFLOW historiques (`mh_example1`), fixtures `--modflow` pour détecter binaires | Tests monolithes par exécutable (on préfère fragmentation par contrat) |
| **scikit-learn** | Règle `test_*.py` ≤ 400 LOC, ratio 80/15/5, fixtures hiérarchiques, `filterwarnings=error`, `pytest --durations=20` en CI | Pas de `common/test_estimators.py` meta-test (on a nos Protocols typés) |
| **xarray** | Hypothesis intensive pour IO NetCDF, fixtures `mock_backends`, markers fins (`network`, `zarr`, `netcdf`) | Pas de `contrib/` tests |
| **OpenFOAM `testHarness`** | Concept d'**ordre de convergence mesuré** (pas juste tolérance), cas MMS obligatoires | Formalisme FoamRunner (on reste pythonique) |
| **TOUGH2-EOS test suite** | Benchmarks analytiques tabulés (Theis, Hantush) avec rationale de tolérance | Format de reference TOUGH2 `.dat` (on utilise JSON stable) |
| **FEFLOW QA protocol** | Tests twin de calibration avec vérité synthétique, propagation d'incertitude paramètres | Commerce-grade certification (overkill pour nous à ce stade) |
| **SciPy** | `@pytest.mark.slow`, `@pytest.mark.xfail(condition, reason=...)` systématiquement motivé, tests Hypothesis property-based | Tests Fortran wrapping (hors scope) |
| **NumPy** | `doctest` sur la docstring publique (une fois par module), `assert_allclose` partout plutôt que `==` | Infrastructure build-matrix complexe |
| **pytest lui-même** | `conftest.py` minimal racine + conftest locaux spécialisés, `tmp_path` exclusif (jamais `tmp_path_factory.mktemp` global) | `tox.ini` (on reste sur uv/poetry) |
| **hypothesis** | `strategies` réutilisables dans `_helpers/strategies.py`, profiles `dev/ci/nightly` | `@settings(max_examples=...)` par test (préférer profile global) |
| **ASME V&V 20-2009** | Terminologie : *code verification* (MMS) vs *solution verification* (grid convergence) vs *validation* (comparison to experiment) | Non normatif ici, mais on adopte le vocabulaire dans `TOLERANCES.md` |
| **DOE V&V 10-2006** | Notion de *calculation verification* distincte de *software verification* | — |

**Ce qu'on invente spécifiquement** :
- Signature de champ à **12 stats + moment_1** (spatial ordering hash) — entre le dump binaire (cher, fragile) et les 4 stats (aveugle aux permutations).
- CLI `hmp test goldens update --diff` — inspiré de `hub`'s `git diff`, pas trouvé directement dans les refs.
- Auto-tag par répertoire + timeout par layer — automatise la discipline du budget temps (pytest-timeout ne le fait pas seul).
- `_helpers/` au lieu de `tests/support/` — met en avant le statut : helpers pytest-locaux, pas des modules publics (convention NumPy).

---

<a id="11-migration"></a>
## 11. Tableau de migration actuel → cible

### 11.1 Par fichier / module

| Actuel | Statut | Cible |
|---|---|---|
| `tests/conftest.py` | `[REFACTORE]` | 75 LOC, seeds auto, timeouts par layer, suppression `pytest_ignore_collect` + `pytest_sessionfinish` |
| `tests/support/pytest_timing_distribution.py` | `[RENOMME]` | `tools/ci/timing_distribution.py` |
| `tests/support/whitebox.py` | `[CONSERVE]` | garde, déplacement vers `_helpers/fixtures_data.py` |
| `tests/regression/golden_utils.py` (1104 LOC) | `[REFACTORE]` | scindé : `_helpers/signatures.py`, `signature_io.py`, `signature_assertions.py`, `signature_cli.py` |
| `tests/regression/launcher_simulation_helpers.py` | `[RENOMME]` | `_helpers/run_sim.py`, downscale vers mini-mailles |
| `tests/regression/coverage_runner.py` | `[CONSERVE]` | garde, mais usage restreint au job `release` full |
| `tests/regression/reference/golden_references/normal/` | `[SUPPRIME]` | alias déprécié |
| `tests/regression/reference/golden_references/{fast,extensive}/` | `[REFACTORE]` | reformaté en signatures enrichies §6, déplacé à `tests/validation/signatures/` ou `tests/e2e/signatures/` |
| `tests/unit/launchers/*` | `[SUPPRIME]` | lanceurs = shells ≤ 30 LOC, pas de tests unitaires dédiés ; l'engine est testé ailleurs |
| `tests/unit/solver/test_boussinesq_backend.py` | `[REFACTORE]` | scindé en 4 fichiers `solver/boussinesq/{assembly,jacobian,runtime,smoothing}/` |
| `tests/unit/data_managers/test_hydrography_full.py` | `[REFACTORE]` | scindé par source (OSM / SANDRE / BDTopage), partie pipeline → `tests/integration/` |
| `tests/unit/geographic/test_run_geographic_*_golden.py` (×3) | `[RENOMME]` | fusion en `tests/e2e/test_geographic_pipeline.py` paramétré |
| `tests/unit/geographic/test_geographic_legacy_characterization.py` | `[SUPPRIME]` | tests d'implémentation legacy |
| `tests/unit/mesh/test_standalone_visualization.py` | `[RENOMME]` | déplacé à `tests/e2e/` (utilise subprocess) |
| `tests/unit/process/test_flow_config_dirichlet.py` | `[CONSERVE]` | tel quel, modèle du bon test unit |
| `tests/unit/process/test_process_contracts_api.py` | `[CONSERVE]` | modèle du bon test unit |
| `tests/unit/simulation/test_catalog_schema.py` | `[REFACTORE]` | étendu avec migration tests (`_schema_version` downgrade/upgrade) |
| `tests/unit/units/test_time.py` | `[REFACTORE]` | étendu en `tests/unit/core/test_units_conversion.py` avec Hypothesis |
| `tests/unit/regression/test_golden_utils.py` (2 tests) | `[REFACTORE]` | → `tests/unit/results/test_signatures_statistical.py`, étendu aux `array_stats`, `modflow_signature`, `assert_stats` (audit §7.1) |
| `tests/validation/analytical/{steady,transient}/` | `[REFACTORE]` | renommé à `tests/validation/analytical/`, purge des wrappers `tests/validation/helpers/*` |
| `tests/validation/numerical/` | `[RENOMME]` | déplacé à `tests/e2e/` — ce sont des régressions de bout en bout |
| `tests/validation/helpers/*.py` | `[SUPPRIME]` | wrappers vides, import direct depuis `validation_cases.shared` |
| Benchmarks Theis, Hantush, Ogata-Banks, Boulton, Neuman | `[NOUVEAU]` | §5.2, §5.3, §5.4 |
| MMS Laplacien, diffusion | `[NOUVEAU]` | §5.5, §5.6 |
| `tests/integration/` | `[NOUVEAU]` | répertoire entier, 18 fichiers §4 |
| `tests/e2e/` | `[NOUVEAU]` | répertoire entier, 5 fichiers |
| `tests/TOLERANCES.md` | `[NOUVEAU]` | §5.8 |
| `tests/pytest.ini` | `[NOUVEAU]` | §7.4, sort de `pyproject.toml` |
| `tests/_helpers/` | `[RENOMME]` | depuis `tests/support/` |
| Hook anti-subprocess (`tests/unit/conftest.py`) | `[NOUVEAU]` | §7.2 |
| CLI `hmp test goldens update --diff` | `[NOUVEAU]` | §6.4 |
| Script `tools/tests/audit_unit_purity.py` | `[NOUVEAU]` | §9.3 |

### 11.2 Ordre de bataille (4 sprints)

**Sprint 1 — Fondations (2 semaines)**
1. Créer `tests/_helpers/`, migrer `support/` (§7.3).
2. Refactor `tests/conftest.py` cible (§7.1).
3. Introduire `tests/pytest.ini`, markers propres, suppression `fast/extensive/normal` (§7.4).
4. Hook anti-subprocess `unit/` (§7.2).
5. Scinder `golden_utils.py` en 4 modules signature (§6.3).
6. Écrire les 20 tests unitaires critiques (§3). C'est la **priorité absolue**.

**Sprint 2 — Validation scientifique (2 semaines)**
7. Benchmark Theis (§5.2).
8. Benchmark Ogata-Banks (§5.4).
9. MMS Laplacien (§5.5).
10. Fichier `TOLERANCES.md` peuplé en parallèle (§5.8).

**Sprint 3 — Intégration et nettoyage (2 semaines)**
11. Les 5 scénarios d'intégration (§4).
12. Migration des 3 golden `test_run_geographic_*` vers `tests/e2e/` (§11.1).
13. Suppression `tests/unit/launchers/*` (§9.1).
14. Scission `test_boussinesq_backend.py` (§9.1).
15. CLI `hmp test goldens update --diff` (§6.4).

**Sprint 4 — CI et dégraissage final (1 semaine)**
16. Workflow `ci.yml` cible (§8.2).
17. `pyproject.toml` coverage nettoyé (§8.3).
18. Script `audit_unit_purity.py`, revue humaine, suppressions (§9.3).
19. `TOLERANCES.md` complet, annotation des 50 TOMLs existants.
20. Benchmark Hantush (§5.3), MMS transitoire (§5.6), twins NWT/Boussinesq (§5.7).

**Total** : ~7 semaines à un développeur temps plein, parallélisable à 2-3 personnes sur 3-4 semaines.

### 11.3 Indicateurs de succès

| Indicateur | Valeur actuelle | Cible post-migration |
|---|---|---|
| Durée `pytest tests/unit/` sans `-n` | ~10 min | ≤ 45 s |
| Durée `pytest tests/unit/ -n auto` | ~3 min | ≤ 15 s |
| Durée CI `pr` (unit + integration) | ~30 min | ≤ 5 min |
| LOC de tests | 48 000 | ~18 000 |
| # fichiers tests | 283 | ~115 |
| # `monkeypatch.setattr` | 338 | ≤ 100 |
| # fichiers > 500 LOC | ≥ 10 | 0 |
| # subprocess dans `unit/` | ≥ 1 | 0 |
| Coverage `solver/boussinesq/runtimes/` | ~0 % unit | ≥ 80 % |
| # benchmarks analytiques avec ordre de convergence mesuré | 0 | ≥ 3 (Theis, Ogata-Banks, MMS Laplacien) |
| # tolerances non documentées | ~50 | 0 (tout annoté dans `TOLERANCES.md`) |
| Pyramide apparente vs réelle | 83/9/6 apparent, 20/55/25 réel | 75/17/6/2 (uniform: apparent = réel) |

---

## 12. Conclusion

Cette architecture de tests **inverse la politique actuelle** : on ne multiplie plus les tests, on les **qualifie**. Un test unitaire qui s'exécute en 3 secondes et mocke 5 modules n'est pas un test unitaire — c'est un test d'intégration déguisé qui coûte cher à maintenir et ne détecte pas les vrais bugs.

Les trois leviers structurants :

1. **Budget temps contractuel par layer** (§1.2). Un test qui dépasse son budget est un bug de design du test, pas une fatalité. `unit ≤ 200 ms, integration ≤ 5 s, validation ≤ 60 s`. Enforcement automatique (§7.1).

2. **Signatures enrichies + rationales documentés** (§6, §5.8). On remplace `« mean ≈ 0.123 ± 10⁻⁴ »` sans justification par 12 stats + moment spatial + hash CF, chaque tolérance liée à une source (Richardson, machine epsilon, littérature). `TOLERANCES.md` devient la colonne vertébrale de la validation.

3. **Pyramide réelle vs apparente** (§1.1, §9). On réduit les fichiers `unit/` de 235 à ~80, mais on couvre **plus** de chemins critiques (runtimes Boussinesq, forcing resolution, provenance hash streaming), parce qu'on ne gaspille plus l'effort dans des tests d'orchestration.

Avec les 3 benchmarks analytiques obligatoires (Theis, Hantush, Ogata-Banks) et les 2 MMS, HydroModPy passe du **statut « code de recherche »** à celui de **« candidat certifiable »** — les benchmarks manquants étaient justement ceux qui bloquaient une certification BRGM / ONDE / impact eau potable.

La suite cible — **115 fichiers, 18 000 LOC, 45 s sur laptop** — est **maintenue** avec une fraction du coût actuel et **détecte plus de régressions** grâce à des tests précis plutôt qu'à des avalanches.

---

**Fin du document.**
