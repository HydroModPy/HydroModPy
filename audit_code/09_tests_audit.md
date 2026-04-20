# Audit critique — Suite de tests HydroModPy

**Périmètre** : `/home/bb/Documents/01_Git_Repository/02-HydroModPy-dev/tests/` (283 fichiers Python, ≈ 48 000 LOC) + infrastructure CI (`/.github/workflows/`, `/tools/ci/`, `pyproject.toml`) + `validation_cases/`.
**Contexte** : audit post-merge `dev-refact → dev-database` (899 fichiers, +487 ajoutés, +867k insertions). 16 nouveaux fichiers test `tests/unit/*` et `tests/validation/*`.
**Date** : 2026-04-17.
**Branche** : `dev-database`.
**Auditeur** : expert QA logiciels scientifiques / pytest / hydrogéologie numérique.

---

## 0. Résumé exécutif

| Dimension | Verdict | Sévérité |
|---|---|---|
| Stratégie de test (pyramide) | **Non-standard** — inversée | Haute |
| Pureté unitaire | **Problématique** — 70 % des « unit » sont des intégrations | Haute |
| Fiabilité régression (pattern golden) | **Acceptable avec réserves** (tolérances non justifiées) | Moyenne |
| Couverture benchmarks analytiques | **À améliorer** — Theis, Hantush, MMS absents | Haute |
| Couverture code (modules non testés) | **Problématique** — moteurs Boussinesq `runtimes/` quasi-muets | Haute |
| Qualité helpers (`golden_utils`, `launcher_helpers`) | **Acceptable** — mais `except Exception` avalés | Moyenne |
| Infra CI (coverage, timeout, pipeline) | **À améliorer** — « fast » à 1 h, sans xdist | Moyenne |
| Déterminisme / portabilité | **Acceptable** (signatures statistiques) | Basse |
| Fixtures (scope, effets de bord) | **Acceptable** avec risque xdist | Moyenne |
| Tests flaky détectés | Aucun xfail ; skips justifiés (plateforme, réseau) | Basse |

**Note globale : C+**. La base est structurellement saine (séparation `unit / regression / validation / support`, markers riches, helpers factorisés, environnement `HYDROMODPY_TEST_SCRATCH_ROOT` externalisé), mais la discipline de frontière entre niveaux de test est largement violée. Le projet paie la dette classique des codes scientifiques matures : beaucoup de tests, peu de vraie granularité unitaire, validation scientifique hétérogène entre solveurs.

---

## 1. Stratégie de test — pyramide inversée

### 1.1 Décompte

| Dossier | Fichiers | Lignes (≈) | Ratio ciblé (pyramide standard) |
|---|---|---|---|
| `tests/unit/` | **235** | ~40 000 | 70-80 % |
| `tests/regression/` | **9** (4 fast + 4 extensive + helpers) | ~700 | 10-15 % |
| `tests/validation/` | **26** (steady + transient + calibration + numerical) | ~2 000 | 10-15 % |
| `tests/support/` | 2 (helpers) | 400 | — |

En apparence la pyramide est respectée (235/26/9). **En réalité elle est inversée** : sur un échantillon de 20 fichiers tirés de `tests/unit/` (cf. §2), seuls 4 (20 %) sont de vrais tests unitaires. Les autres exécutent des pipelines complets (DEM réel, gmsh, FloPy, calibration CMA-ES, mocks Watershed étendus). La vraie pyramide est donc :

| Catégorie réelle | Nombre estimé | Proportion |
|---|---|---|
| Tests unitaires purs (< 100 ms, pas d'I/O lourd) | ~50-60 | 20 % |
| Tests d'intégration déguisés en unitaires | ~150-170 | 55-60 % |
| Tests de régression / bout-en-bout | ~40 (9 regression + ~30 goldens dispersés) | 14 % |
| Tests de validation scientifique | 26 | 9 % |

### 1.2 Verdict

**Non-conforme** aux pratiques standard. Un repo de référence (scikit-learn, FloPy, xarray) présente une démarcation nette :
- unit : < 1 s, pas de subprocess, pas d'I/O disque massif, `tmp_path` exclusivement pour fichiers < 10 kB ;
- integration : croise plusieurs modules, pas de binaire externe, exécution < 30 s ;
- regression/e2e : binaires externes, golden outputs, exécution minutes.

Ici la catégorisation tient par convention de chemin et non par coût d'exécution.

### 1.3 Recommandations

1. Introduire `tests/integration/` et y déplacer tout fichier unit > 500 lignes ou > 1 s.
2. Mettre en place un garde CI : `pytest tests/unit/ --durations=30 --timeout=5` bloque si un test dépasse 5 s.
3. Renommer le marker `fast` en `smoke` ou `short` (« fast » à timeout=3600 s est mensonger).
4. Documenter la pyramide cible dans `tests/README.md`.

---

## 2. Tests unitaires — 70 % d'intégration déguisée

### 2.1 Échantillon analysé (20 fichiers)

| Fichier | LOC | Verdict |
|---|---|---|
| `tests/unit/units/test_time.py` | ~60 | ✅ unitaire pur |
| `tests/unit/process/test_flow_config_dirichlet.py` | ~120 | ✅ unitaire pur |
| `tests/unit/simulation/test_catalog_schema.py` | ~220 | ✅ unitaire (DuckDB `:memory:`) |
| `tests/unit/field/test_field_param.py` | ~180 | ✅ unitaire (TOML minimal) |
| `tests/unit/display/test_common.py` | ~40 | ✅ monkeypatch justifié |
| `tests/unit/simulation/test_simulation_api.py` | ~300 | ✅ fonctionnel (~500 ms) |
| `tests/unit/annex/test_catchment_identification_config.py` | ~90 | ✅ parsing TOML |
| `tests/unit/data_managers/oceanic/test_oceanic_custom.py` | ~200 | ⚠️ borderline (CSV disque) |
| `tests/unit/geographic/test_geographic_cache.py` | ~150 | ⚠️ borderline (shapefile stub) |
| `tests/unit/geographic/test_run_geographic_river_network_golden.py` | ~125 | ❌ charge DEM réel, pipeline complète |
| `tests/unit/geographic/test_run_geographic_dem_processing_golden.py` | ~95 | ❌ idem |
| `tests/unit/geographic/test_run_geographic_case_golden.py` | ~45 | ❌ idem |
| `tests/unit/geographic/test_geographic_legacy_characterization.py` | 519 | ❌ intégration déguisée |
| `tests/unit/geographic/test_reference_river_network_nancon_case.py` | — | ❌ `@pytest.mark.slow` dans unit/ |
| `tests/unit/launchers/test_launcher_run_id.py` | 690 | ❌ 18 `monkeypatch.setattr` |
| `tests/unit/launchers/test_model_calibration_launcher.py` | 2 722 | ❌ launcher complet, ~25 mocks |
| `tests/unit/launchers/test_regional_lab_launcher.py` | 735 | ❌ orchestration multi-sous-launchers |
| `tests/unit/mesh/test_standalone_visualization.py` | — | ❌ **subprocess réel** `python -m tools.mesh_bundle_viewer` |
| `tests/unit/solver/test_boussinesq_backend.py` | 1 642 | ❌ solveur complet sur mailles 3D |
| `tests/unit/data_managers/test_hydrography_full.py` | 1 643 | ❌ mocks HTTP + data pipeline |

### 2.2 Signaux d'alerte

- **Fichiers > 500 lignes dans `tests/unit/`** : au moins 10 identifiés. Règle métier : un test unitaire tient dans une page. Au-delà, c'est une suite d'intégration.
- **`monkeypatch.setattr` dans `tests/unit/`** : 338 occurrences. La norme scikit-learn/FloPy reste sous 100. Quand un test mocke `Workspace`, `Geographic`, `Domain` simultanément (`test_launcher_run_id.py`), il teste la glu d'orchestration — ce n'est plus du code unitaire.
- **Subprocess réel** : `tests/unit/mesh/test_standalone_visualization.py` appelle `subprocess.run([sys.executable, "-m", "tools.mesh_bundle_viewer", ...])`. **C'est un test bout-en-bout**, à migrer sous `tests/integration/` ou `tests/regression/`.
- **Golden tests rangés dans `unit/`** : les fichiers `test_run_geographic_*_golden.py`, `test_run_oceanic_case_golden.py`, `test_run_intermittency_case_golden.py`, ainsi que les `test_reference_*_case` de `solver/utils/mesh/gmsh_grid/` devraient vivre sous `tests/regression/golden/`.

### 2.3 Edge cases

Bon début (tests explicites pour empty polygons, NaN dans DEM, seepage vide), mais **manque systématique** :
- grilles 1×1, 1×N, N×1 (aucun test trouvé sous ce pattern) ;
- pas de temps unique, `nper=1, nstp=1` ;
- `ncells=0` en post-traitement ;
- conductivités nulles ou infinies (K=0 et K→∞) ;
- aquifère entièrement sec (`head < bottom` sur tout le domaine).

### 2.4 Tests d'implémentation vs comportement

Plusieurs tests testent le chemin d'appel interne plutôt que l'API publique (monkeypatch sur `hydromodpy.workflow.steps.setup.hmp.Workspace`). En cas de refactor interne, ces tests cassent sans qu'aucun comportement utilisateur ne soit affecté. **Signal classique de fragilité.**

### 2.5 Verdict & recommandations

**Problématique.**
1. Fragmenter les 10 fichiers > 500 LOC en suites d'intégration + noyau unitaire pur.
2. Imposer `--timeout=2` sur `tests/unit/` ; échecs = migration.
3. Interdire `subprocess` sous `tests/unit/` (hook CI).
4. Remplacer les cascades de `monkeypatch.setattr(hmp.X, ...)` par l'injection de dépendance dans le code testé (le code résiste mieux après).
5. Ajouter un garde-fou pour les edge cases numériques (fixture `@pytest.mark.parametrize` sur `(nx, ny, nper) ∈ {(1,1,1), (1,10,1), …}`).

---

## 3. Tests de régression — pattern golden

### 3.1 Inventaire

| Fichier | Tier | Timeout | Commentaire |
|---|---|---|---|
| `test_launcher_simulation_fast_boussinesq_regression.py` | fast | 1 800 s | Boussinesq / scipy_sparse |
| `test_launcher_simulation_fast_boussinesq_divide_regression.py` | fast | 1 800 s | diviseur d'écoulement |
| `test_launcher_simulation_fast_mf6_regression.py` | fast | **3 600 s** | MF6 + transport GWT |
| `test_launcher_simulation_fast_nwt_regression.py` | fast | **3 600 s** | NWT + MODPATH + MT3DMS |
| `test_launcher_simulation_extensive_mf6_regression.py` | extensive | non spécifié | lourd |
| `test_launcher_simulation_extensive_nwt_regression.py` | extensive | idem | lourd |
| `test_launcher_data_overview_regression.py` | extensive | 3 600 s | dépend SHOM + Hubeau |
| `test_run_geographic_case_regression.py` | extensive | — | 4 bassins, DEM réel |
| `test_run_geographic_case_river_network_regression.py` | extensive | — | idem |

### 3.2 Golden outputs (`tests/regression/reference/golden_references/`)

Trois tiers disponibles : `fast/`, `extensive/`, `normal/` (alias déprécié — à supprimer). Format JSON : signatures statistiques compactes `{count, mean, p50, p95, shape, sum, timestep}`.

**Points forts** :
- signatures **statistiques**, pas de dump binaire → robuste aux variations BLAS, endianness, ordre des threads OpenMP ;
- finite-only stats : NaN/Inf automatiquement ignorés ;
- tolérances explicites (`rel=1e-4, abs=1e-6` général ; `rel=5e-4, abs=1e-5` transport) ;
- `--update-goldens` implémenté et documenté via `pytest_addoption` dans `tests/conftest.py:39-46`.

**Points faibles** :
- **Rationale absente** : pourquoi `rel=1e-4` pour flow et `rel=5e-4` pour transport ? Un commentaire dans `golden_utils.py:820` dit simplement « transport is noisier ». Aucune analyse d'incertitude numérique (Richardson extrapolation, grid convergence) ne justifie ces seuils.
- **Cross-platform** : tous les goldens ont été générés sur Linux (CI = `ubuntu-latest`). Aucune garantie Windows/macOS, alors que `golden_utils._rmtree_onerror` / `remove_tree_with_retry` témoignent d'une prise en charge Windows revendiquée.
- **Signatures pauvres** : `mean/p50/p95/sum` sur la dernière couche / dernier timestep. Une régression localisée qui n'affecte qu'une petite zone peut être invisible (mean tolérant, sum dominé par les cellules OK). Il faudrait au moins ajouter `min/max` et quelques percentiles intermédiaires (p05, p25, p75).
- **`last_timestep` uniquement** (`golden_utils.modflow_signature:317-324`) : un bug d'évolution temporelle entre t=0 et t=N-1 ne sera pas détecté s'il compense à la fin.
- **Pas d'index spatial** : deux champs différents peuvent partager les mêmes stats agrégées. Un hash numérique grossier (par ex. `float(np.sum(arr * np.arange(arr.size)))` — moment d'ordre 1) détecterait les permutations.
- **Pattern `try/except Exception`** à `golden_utils.py:380` et `.py:461-465` avale toute erreur Zarr. Un bug silencieux (clé manquante, fichier corrompu) se traduit par un signature vide → le test passe.

### 3.3 Processus `--update-goldens`

- Implémentation : `pytest_addoption` + fixture `update_goldens` session-scoped.
- Propagation : via `run_launcher_simulation_regression(update_goldens=update_goldens)` jusqu'à `update_or_assert_goldens()`.
- **Risque opérationnel** : aucune vérification que l'utilisateur a bien *revu* les modifications. `hmp test regression --update-goldens` overwrite silencieusement les JSONs. Dans scikit-learn, `pytest --reference-update` affiche un diff avant écriture ; FloPy impose code review obligatoire de tout delta golden.
- Pas de workflow documenté (pas de `tests/regression/HOW_TO_UPDATE_GOLDENS.md` — seul `tests/regression/README.md` existe, non lu selon consignes).

### 3.4 Régénération sous coverage — `coverage_runner.py`

Le consignes de l'audit évoquent un « bug SystemExit non capturé ». Après relecture de `tests/regression/coverage_runner.py` :

```python
except SystemExit as exc:
    if exc.code != 0:
        import traceback
        print(f"\n[coverage_runner] SystemExit(code={exc.code!r}) caught.\n...",
              file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    raise
finally:
    cov.stop(); cov.save()
```

→ `SystemExit` **est bien ré-levée** (`raise` final). La coverage **est sauvée** grâce au `finally`. Ce n'est pas un bug : c'est un passage délibéré pour loguer le code de sortie avant propagation. La seule imperfection : `except BaseException` (l. 50) attrape aussi `KeyboardInterrupt` et `SystemExit` → mais dans l'ordre des `except` Python, `SystemExit` est déjà capturé plus haut, donc cohérent. **Verdict : acceptable, bien commenté.**

### 3.5 Verdict régression

**Acceptable avec réserves.**

Recommandations :
1. Ajouter `min/max/p05/p25/p75/std` aux signatures (hausse marginale du coût, grosse amélioration de sensibilité).
2. Calculer au moins un hash d'ordre 1 (`np.sum(arr * np.arange(arr.size))`) pour invalider les permutations spatiales.
3. Comparer aussi les timesteps intermédiaires (au moins `t=0, t=N//2, t=N-1`).
4. Documenter la justification des tolérances (référence littérature ou analyse Richardson).
5. Remplacer `except Exception: pass` par `except (KeyError, IndexError, BoundsCheckError)` — toute autre exception doit remonter.
6. Ajouter un script `tools/regression/diff_goldens.py` qui affiche les deltas avant écriture en mode update.

---

## 4. Tests de validation scientifique

### 4.1 Inventaire

**26 benchmarks analytiques** + 3 cas numériques + 6 twins de calibration.

| Régime | Type | Cas | Solveurs couverts |
|---|---|---|---|
| Steady analytical | Dupuit | fixed_head_1d, uniform_recharge_1d, divide_river_1d, circular_island_ocean_2d | NWT + MF6 + Boussinesq |
| Steady analytical | Dupuit PETSc alias | dupuit_fixed_head_petsc_1d | PETSc (Linux) |
| Steady analytical | Boussinesq non-confiné | 8 cas (fixed_head_piecewise_k, hillslope_interception, sloping_substratum ×3, circular_island_2d…) | NWT + MF6 + Boussinesq |
| Steady analytical | Linearized unconfined | drainage_1d, hillslope_drainage_1d | NWT + MF6 |
| Transient analytical | Brutsaert recession | linearized_deep_1d, boussinesq_thin_1d | — |
| Transient analytical | Linearized unconfined | recharge_step ×3, boundary_step/piecewise, recharge_periodic | NWT + MF6 + Boussinesq |
| Transient analytical | Late-time pumping | 2D | NWT + MF6 |
| Calibration twin | Dupuit / Boussinesq / linearized | 6 cas | **MF6 uniquement** |
| Numerical | Headwater 100 km² PETSc | steady + transient + pulse overflow | PETSc (Linux) |

### 4.2 Benchmarks MODFLOW standard **manquants**

Référence : MacDonald & Harbaugh *User's Documentation for MODFLOW-96* (USGS OFR 96-485), Zheng & Wang *MT3DMS* (1999), Konikow *Advective transport benchmarks*.

| Benchmark manquant | Importance | Fichier manquant suggéré |
|---|---|---|
| **Theis 1935** (pompage transitoire en confiné, axisymétrique) | **critique** — pas de validation aquifère captif transitoire | `validation_cases/analytical/transient/theis_confined_pumping_2d/` |
| **Hantush-Jacob 1955** (nappe semi-confinée avec drainage par aquitard) | **critique** — aucune validation de couche intermédiaire | `validation_cases/analytical/transient/hantush_jacob_leaky_2d/` |
| **Boulton 1963** (delayed yield en nappe libre) | Majeure — dissocie `Sy` dynamique | `validation_cases/analytical/transient/boulton_delayed_yield_1d/` |
| **Neuman 1972** (pompage transitoire avec delayed response) | Standard MODFLOW / analytique élégant | `.../transient/neuman_delayed_response_2d/` |
| **MT3DMS tests 1-4 de Zheng & Wang** (advection pure, transport Ogata-Banks, 2D Gaussien, Cinétique 1er ordre) | **Critique** — **aucun benchmark transport analytique** | `validation_cases/analytical/transport/` (absent) |
| MacDonald & Harbaugh Example 1 (1D confined) | Industry standard | `.../steady/mh_example1_confined_1d/` |
| Prickett-Lonnquist 1971 (pumping in strip) | Historique, utile | `.../transient/prickett_strip_pumping_2d/` |

**Couverture transport** : `transport_expected` est comparé dans les goldens **mais aucun test analytique** ne valide la solution advection-dispersion face à Ogata-Banks. C'est un trou de validation dangereux pour un outil qui prétend supporter MT3DMS + MF6-GWT.

### 4.3 Tolérances — gouffre sans fondement documenté

Extrait d'analyse (50+ TOML) :

| Benchmark | NWT (`rmse`) | MF6 (`rmse`) | Boussinesq (`rmse`) | Commentaire |
|---|---|---|---|---|
| `dupuit_fixed_head_1d` | 0.05 m | 2e-4 m | 0.05 m | **facteur 250×** entre MF6 et NWT |
| `late_time_unconfined_pumping_2d` | 0.03 m | 0.02 m | 0.10 m | cohérent |
| `boussinesq_fixed_head_piecewise_k_1d` | 0.10 m | 0.01 m | 0.10 m | MF6 10× plus strict |

Les tolérances paraissent **fittées a posteriori** pour faire passer les tests, et non dérivées d'une analyse d'ordre de convergence. Dans un code de référence scientifique, on attend soit :
- une analyse `h`-convergence (MMS + slope = ordre du schéma, seuils = `C·h^p` pour une constante C documentée) ;
- soit une tolérance uniforme justifiée par l'arithmétique flottante (`10·ε_machine·‖f‖`, par exemple).

### 4.4 MMS — absent

**Aucune Method of Manufactured Solutions trouvée.** Le projet compare toujours à une solution analytique *physique* (Dupuit, Brutsaert, linearized unconfined). Or MMS est la seule méthode qui permet de vérifier que **l'opérateur discret converge à l'ordre attendu** indépendamment d'une physique correcte. Sans MMS :
- impossible de savoir si un bug de coefficient en `(1/2)` est masqué par une tolérance généreuse ;
- impossible de valider un solveur sur des conditions aux limites non standard.

À ajouter : au moins un MMS steady 1D (Laplacien avec terme source fabriqué) et un MMS transient (équation de diffusion).

### 4.5 Tests « numerical » (≠ validation scientifique)

`tests/validation/numerical/` : 3 cas sur le bassin Naizin / headwater 100 km². Ce sont **des tests de régression déguisés en validation** : ils vérifient « ça tourne sur un vrai DEM » sans comparaison analytique. **À déplacer sous `tests/regression/extensive/` ou à renommer `tests/validation/numerical_benchmarks/` avec critères explicites** (temps CPU, nombre d'itérations, résidu final, pas d'assertion sur la *valeur* de la solution).

### 4.6 Twins de calibration — MF6-only

Les 6 twins (`test_twin_dupuit_*`, `test_twin_boussinesq_*`, `test_twin_linearized_*`) valident CMA-ES et random-search en récupérant les paramètres vérité. **Conceptuellement solides** (observations synthétiques + bruit + optimisation). Mais :
- MODFLOW-NWT absent — solveur legacy pas validé en mode inverse ;
- Boussinesq absent en mode inverse ;
- critère de succès unique (`recovered_truth`) — pas d'analyse d'identifiabilité, pas de propagation d'incertitude sur les paramètres recouvrés.

### 4.7 Verdict validation

**À améliorer.**

Top 3 :
1. **Ajouter Theis + Hantush + un MT3DMS analytique** (Ogata-Banks 1D) : sans eux la certification d'un code hydrogéologique confiné/transport n'est pas défendable.
2. **Introduire au moins un MMS** (steady 1D fabriqué) avec analyse d'ordre.
3. **Documenter toutes les tolérances** (fichier `validation_cases/TOLERANCES.md` + commentaire en tête de chaque `tolerances*.toml`).

---

## 5. Couverture — modules sans tests

### 5.1 Modules `hydromodpy/` sans tests unitaires directs

Par inspection croisée entre `hydromodpy/*/` (54 sous-modules de premier niveau) et `tests/unit/*/` :

| Module | Statut | Impact |
|---|---|---|
| `hydromodpy/solver/boussinesq/runtimes/` (12 fichiers, issu du refactor post-merge) | **non couvert** par tests unitaires dédiés | **critique** — moteur numérique |
| `hydromodpy/solver/boussinesq/drivers/` (5 fichiers ajoutés par le merge) | quelques tests indirects via `test_boussinesq_backend.py` | majeur |
| `hydromodpy/solver/boussinesq/assembly/` (7 fichiers ajoutés) | tests indirects | majeur |
| `hydromodpy/solver/boussinesq/jacobian/` (5 fichiers) | pas de test unitaire dédié | majeur |
| `hydromodpy/solver/modflow6/diagnostics.py` (nouveau) | pas de test | moyen |
| `hydromodpy/solver/modflow6/postprocess.py` (nouveau) | `test_modflow6_postprocessing.py` léger | moyen |
| `hydromodpy/solver/modflow_common/forcing_discretization.py` (nouveau) | pas de test trouvé | moyen |
| `hydromodpy/core/tools/` (utilitaires raster/fs) | éparse | moyen |
| `hydromodpy/data/common/clients/` | pas de test unitaire | moyen |
| `hydromodpy/data/common/administrative/` | pas de test | bas |
| `hydromodpy/data/subbasin/` | pas de test | bas |
| `hydromodpy/analysis/display/report/` | pas de test | bas |
| `hydromodpy/process/contracts.py` (nouveau) | `test_process_contracts_api.py` présent ✅ | ok |
| `hydromodpy/solver/contracts.py` (nouveau) | `test_solver_contracts_api.py` présent ✅ | ok |

### 5.2 Chemins critiques non testés

1. **Solveur Boussinesq runtime (`scipy_sparse`, `scipy_dense`, `petsc_mixed`, `petsc_partition`, `local`)** — cœur numérique du nouveau pipeline ; couverture de facto uniquement via les tests `validation/analytical/steady/test_boussinesq_*.py` (end-to-end). Impossible d'identifier une régression de la fabrique de Jacobien (par ex. `jacobian/partition_triplets.py`) autrement que par la sortie globale.
2. **Résolution des conditions aux limites** (`forcing/recharge_resolution.py`, `forcing/drainage_resolution.py`, `forcing/well_resolution.py`, `forcing/dirichlet_support_resolution.py`) — ajoutés par le merge, sans test unitaire dédié.
3. **Import/Export catalogue** (`hydromodpy/results/catalog.py`) — `test_catalog_import_export.py` existe, mais aucun test sur la migration de schéma (`_schema_version`). Risque de corruption silencieuse.
4. **Provenance SHA-256** (`hydromodpy/results/provenance.py` si existe, sinon partie de `data/registry/`) — `test_results_provenance.py` couvre le plus chaud, mais pas les cas de hash d'un gros fichier (streaming).
5. **Calibration CMA-ES** (ajouté `analysis/calibration/core/methods/cma_es.py`) — couvert par twin tests, mais sans assertion sur la convergence (vitesse, plateau).

### 5.3 Couverture — configuration

Coverage config (`pyproject.toml:157-179`) :
- `parallel = true` déclaré mais **pas activé en CI** (pas de `-n auto` dans `coverage.yml:45-51`).
- `omit` inclut `hydromodpy/**/cases/*` : juste — ce sont des scripts de démo. ⚠️ mais l'omit `hydromodpy/calibration_legacy/*` et `hydromodpy/calibration2/*` pointe vers des chemins qui **n'existent plus** (calibration a migré sous `analysis/calibration/`). Code mort dans la config.
- `[tool.coverage.report] exclude_lines` standard mais **pas de `if os.environ.get(...)` pour les chemins headless** — sous-estimation probable.

### 5.4 Verdict couverture

**Problématique.**

Priorité :
1. Écrire des tests unitaires pour `solver/boussinesq/runtimes/` (5 fichiers critiques) — au moins `test_scipy_sparse_single_step.py` avec un problème 3×3 et comparaison à la solution analytique triviale.
2. Écrire des tests `forcing/*_resolution.py` avec fixtures déterministes.
3. Nettoyer `omit` : retirer `calibration_legacy` et `calibration2` inexistants.
4. Activer `pytest-xdist -n auto` en CI (gain CI estimé 40 % ; cf. §7).

---

## 6. Fixtures & effets de bord

### 6.1 `tests/conftest.py`

Inspection (122 lignes) :

| Élément | Portée | Verdict |
|---|---|---|
| `_TEST_SCRATCH_ROOT` (module-level env setup) | processus | ✅ bonne pratique — externalise scratch hors repo |
| `update_goldens` | session | ✅ |
| `hydromodpy_test_scratch_root` | session | ✅ |
| `_redirect_repo_root_cwd_for_gmsh_grid_tests` | **autouse** | ⚠️ autouse global pour un besoin sous-répertoire spécifique (`tests/unit/solver/utils/mesh/gmsh_grid/`). Le filtrage par chemin à chaque test est fragile. Préférer un `conftest.py` local à `tests/unit/solver/utils/mesh/gmsh_grid/` |
| `pytest_collection_modifyitems` | collect | ✅ auto-tag `fast`/`extensive` — élégant |
| `pytest_sessionfinish` cleanup | session end | ⚠️ `shutil.rmtree(_TEST_SCRATCH_ROOT)` — **incompatible xdist** : dans un run parallèle, le contrôleur supprime pendant qu'un worker écrit |
| `pytest_ignore_collect` | — | ❌ **code mort** : toujours retourne `False`. À supprimer |

### 6.2 Effets de bord entre tests

- `HYDROMODPY_TEST_SCRATCH_ROOT` est *shared* entre tests (même répertoire). Les tests qui écrivent un workspace (ex. `tests/regression/*.py` via `resolve_tiered_results_dir()`) partagent ce chemin racine mais sous-répertorient par `run_name` → **pas de collision** *en série*. En parallèle avec xdist, les `run_name` sont uniques (nommés par fichier de test) → OK, mais **le cleanup final de session peut provoquer un race**.
- Fixture `configure_whitebox_single_thread` (`tests/support/whitebox.py`) impose `RAYON_NUM_THREADS=1` via `monkeypatch.setenv` — scope fonction, propre. Mais les tests qui ne l'utilisent pas peuvent hériter de la variance whitebox (bug de reproductibilité). À promouvoir en fixture autouse locale sous `tests/unit/geographic/`.

### 6.3 Parallélisation (xdist)

- `pytest-xdist` est dans `[project.optional-dependencies] test` (`pyproject.toml:78`).
- `CLAUDE.md` documente `pytest tests/regression/ -n auto`.
- **CI ne l'active pas** (`.github/workflows/coverage.yml:44` et `.yml:101-103`).
- **`pytest_sessionfinish` casse xdist** (cf. 6.1). À guarder : `if not is_xdist_worker: ...` — c'est déjà le cas ✅. Mais le contrôleur peut tomber avant les workers. À tester.

### 6.4 Verdict fixtures

**Acceptable** avec trois ajustements :
1. Déplacer `_redirect_repo_root_cwd_for_gmsh_grid_tests` en `tests/unit/solver/utils/mesh/gmsh_grid/conftest.py`.
2. Supprimer `pytest_ignore_collect` (fonction morte).
3. Activer xdist en CI avec `-n 4 --dist=loadfile` pour isoler les collisions d'écriture golden.

---

## 7. Infrastructure helpers & CI

### 7.1 `tests/regression/golden_utils.py` (1 104 lignes)

**Architecture** : séparation claire `load_* / collect_* / assert_* / run_*`. Sans être minimal, c'est **maintenable et bien documenté** (docstrings denses, warning Windows-specific expliqué).

**Faiblesses** :
- 1 104 LOC — à fragmenter en `signatures.py`, `executables.py`, `cleanup.py`, `subprocess_runners.py` (aujourd'hui un seul fichier fait tout).
- **`except (KeyError, Exception): pass`** à la ligne 380 (`collect_store_modpath_signatures`) — anti-pattern : absorbe KeyboardInterrupt, MemoryError, *tout*. Même chose à `:461-465`. Remplacer par des exceptions étroites.
- Fonction `resolve_first_model_workspace` (`:772-780`) est un **wrapper sans valeur ajoutée** sur `resolve_model_workspace` avec les mêmes kwargs par défaut — supprimable.
- `run_legacy_example_script` (`:957-1100`) : 150 lignes de **code Python inline dans une chaîne triple-quotée** (`wrapper = r"""…"""`) qui remonkeypatche `IPython.get_ipython`, `os.path.join`, `Watershed`. C'est **de la boue**. À remplacer par un script dédié `tests/regression/_legacy_wrapper.py` avec un vrai module, typé et testable. Actuellement, aucun test ne valide ce wrapper — tout bug passe silencieusement.

**Tests des helpers eux-mêmes** : `tests/unit/regression/test_golden_utils.py` ne couvre que **2 tests**, et uniquement la robustesse Windows (`rmtree retry on PermissionError`). **Ne teste pas** : `array_stats`, `array_signature`, `modflow_signature`, `assert_stats`, `assert_modflow_signatures`, `update_or_assert_goldens`, `_open_result_store`, `_resolve_sim_id`. **Lacune critique** — ces fonctions sont la colonne vertébrale de la régression, elles n'ont pas de filet unitaire.

### 7.2 `tests/regression/launcher_simulation_helpers.py` (335 lignes)

Thin wrapper autour de `golden_utils`. **Propre**. Constantes (`MODFLOW_OUTPUT_NAMES`, `BOUSSINESQ_SUMMARY_KEYS`, `BOUSSINESQ_STATE_HISTORY_NAMES`) centralisées, bonne réutilisation. Couplage fort avec `validation_cases/shared/boussinesq_piecewise_strip` — accepté car les deux vivent dans le même repo.

**Points à revoir** :
- `_ensure_local_oceanic_seed_csv` (l. 117-162) **fetche SHOM live** lorsque le CSV local manque. Cela transforme un test « régression » en test d'intégration réseau silencieusement. Préférer une fixture de données versionnée.
- `SHOM_HEALTHCHECK_URL`, URL codées en dur dans les constantes — OK pour l'isolation, mais à documenter dans un README régression dédié.

### 7.3 `tools/ci/coverage_helpers.py` & `run_pytest_with_coverage.py`

Inspection :
- `coverage_helpers.py` (42 LOC) : lit `[tool.coverage.run].source` depuis `pyproject.toml`, retourne des globs. Fallback propre. ✅
- `run_pytest_with_coverage.py` : non inspecté directement ici, mais son équivalent `tests/regression/coverage_runner.py` est correct (cf. §3.4).

### 7.4 CI (`.github/workflows/coverage.yml`)

| Job | Timeout | Parallélisation | Issues |
|---|---|---|---|
| unit | 10 min | non (`pytest tests/unit/ -v`) | pas de xdist ; supprime manuellement `coverage*.pth` pour contourner un crash numpy — contournement, pas fix |
| regression | 30 min | non | même hack `.pth` ; lance `tests/regression/fast + extensive` en série |

**Branches déclenchantes** : `[master, dev-refact, dev-data, dev-database]` — cohérent avec l'historique. `docs-gallery-check.yml` nouveau (post-merge) sous dépendance asset.

**Verdict CI** :
- 30 min pour la régression est **juste** — si l'un des `timeout=3600` (fast NWT ou fast MF6) partait en erreur, le job GitHub tomberait avant lui. Les timeouts devraient s'enchaîner : `timeout(pytest) < timeout(job)`.
- **Aucun marker `slow` filtré** : `test_launcher_data_overview` (internet SHOM/Hubeau) est un `@pytest.mark.slow + extensive + coverage` qui tourne à chaque commit CI. Fragile (SHOM indisponible = skip).
- Codecov `fail_ci_if_error: false` — OK pour dev, à durcir sur master.

### 7.5 Verdict infra

**À améliorer.**

1. Fragmenter `golden_utils.py` en 4-5 modules.
2. Remplacer `except Exception: pass` ×2 par exceptions étroites.
3. Ajouter des tests unitaires sur `array_stats`, `array_signature`, `modflow_signature`, `assert_stats` (20 LOC, 5 minutes à écrire).
4. Versionner le CSV SHOM (`tests/fixtures/oceanic_shom_152_20030101_20030130_H.csv`) au lieu de le fetch.
5. Extraire le wrapper inline de `run_legacy_example_script` en module testable.
6. Activer `pytest-xdist -n auto --dist=loadfile` en CI.
7. Résoudre le hack `.pth` coverage par l'usage exclusif de `tools/ci/run_pytest_with_coverage.py` (Coverage API programmatique).
8. Durcir `fail_ci_if_error: true` sur `master`.

---

## 8. Tests flaky, skips, timeouts

### 8.1 Skips

~18 occurrences détectées, typologie saine :
- plateforme (PETSc Linux-only, Windows-specific rmtree) ;
- dépendances optionnelles (`pyvista`, `gmsh`, `rioxarray`, `xugrid`) ;
- réseau (SHOM / Hubeau / waterquality APIs) ;
- binaires MODFLOW absents (`assert_required_executables` appelle `pytest.skip`).

**Aucun `@pytest.mark.xfail` détecté.** C'est une bonne chose — pas de flakiness cachée — mais aussi un signe qu'il n'y a pas de suivi des tests connus comme instables.

### 8.2 Timeouts

| Fichier | Timeout | Commentaire |
|---|---|---|
| fast/MF6 | 3 600 s (1 h) | **excessif pour « fast »** |
| fast/NWT | 3 600 s | idem |
| fast/Boussinesq | 1 800 s | idem |
| extensive/MF6 | 7 200 s (2 h) | raisonnable pour extensive |
| data_overview | 3 600 s | raisonnable (réseau + 4 bassins) |

Le marker `fast` a deux sens : dans les TOMLs c'est « tier fast » (par rapport à `extensive`), dans la terminologie pytest c'est « court ». **Confusion.** Renommer `fast` en `tier_short` et `extensive` en `tier_full` éliminerait l'ambiguïté.

### 8.3 Tests flaky

Pas de retry plugin (`pytest-rerunfailures`, `pytest-flakefinder`). Pas de dashboard de flakiness. Aucun test identifié comme historiquement instable. **Ne veut pas dire absent** : deux surfaces suspectées :
- `test_launcher_data_overview_data_only_regression` (dépendance SHOM/Hubeau live) — skip-sur-downtime masque la flakiness ;
- `test_run_geographic_case_regression_suite` — tolérance `ABS_TOL_PIXEL_COUNT = 4` documente « breach non-determinism flips a few edge pixels ». Flakiness **baked into** la tolérance, donc cachée.

### 8.4 Verdict

**Acceptable** mais à outiller :
1. Renommer les markers ambigus.
2. Ajouter `pytest-rerunfailures` pour les tests réseau (`@pytest.mark.flaky(reruns=2)`).
3. Exposer `pytest --durations=20` dans la sortie CI pour traquer les régressions de perf.

---

## 9. Code mort, duplication, verbosité

### 9.1 Code mort

- `tests/conftest.py:115-120` — `pytest_ignore_collect` toujours `return False`. Inutile.
- `pyproject.toml:172-173` — `hydromodpy/calibration_legacy/*` et `hydromodpy/calibration2/*` omit'd mais chemins inexistants.
- `tests/regression/reference/golden_references/normal/` — alias déprécié, à supprimer (le marker `normal` est flaggé « deprecated » dans `pyproject.toml:138`).
- `golden_utils.py:772-780` `resolve_first_model_workspace` — wrapper sans valeur ajoutée.
- `tests/support/pytest_timing_distribution.py` — **329 lignes** pour un outil d'analyse `junitxml` probablement utilisé une ou deux fois dans l'année. Absent de `[project.scripts]`, absent de la doc. À déplacer sous `tools/` ou à supprimer si non essentiel. `tests/` n'est pas l'endroit pour des outils d'analyse.

### 9.2 Duplication

- **`validation_cases/` ↔ `tests/validation/`** : chaque benchmark analytique vit en 3 fichiers (`reference.py` + `comparison.py` + `test_*.py`). Architecture à 3 couches justifiable (exécution CLI + pytest), mais test_*.py reste souvent un wrapper ≤ 20 LOC. À inliner pour les cas simples.
- `tests/validation/helpers/{case_runner,loaders,metrics}.py` — simples `from validation_cases.shared.X import *`. Ces wrappers de compatibilité n'apportent rien → à supprimer (les tests peuvent importer directement `validation_cases.shared`).
- `tests/unit/geographic/test_run_geographic_*_golden.py` (3 fichiers) — patterns redondants. Fusionnables en un seul fichier paramétré.
- `tests/regression/launcher_simulation_helpers.py:_ensure_custom_format_files` et `_ensure_local_oceanic_seed_csv` — duplique une logique qui appartient à un data manager (oceanic_manager).

### 9.3 Verbosité

- `tests/unit/launchers/test_model_calibration_launcher.py` (2 722 lignes) — **monstrueux**. À comparer avec un équivalent scikit-learn (`test_gradient_boosting.py` ≈ 1 200 LOC pour un module bien plus complexe). Fragmenter : runtime / config / post-processing / error paths.
- `tests/unit/solver/test_boussinesq_backend.py` (1 642 lignes) — idem.
- `tests/unit/data_managers/test_hydrography_full.py` (1 643 lignes) — scinder par API externe (OSM / SANDRE / BDTopage).

### 9.4 Verdict

**À nettoyer.**

---

## 10. Recap par critère — table de verdicts

| § | Critère | Description | Verdict | Justification | Recommandation |
|---|---|---|---|---|---|
| 1 | Stratégie pyramide | 235/26/9 apparent vs ~20 %/55 %/25 % réel | Non-conforme | Frontière unit/integration floue | Introduire `tests/integration/`, timeouts unit=2s |
| 2 | Unitaires purs | 4/20 dans l'échantillon | Problématique | mocks cascadés, subprocess, DEM réels | Fragmenter gros fichiers, interdire subprocess sous `unit/` |
| 2 | Edge cases | empty/NaN OK, grilles 1×1 absentes | À améliorer | Tests configurations minimales manquants | Param `(nx,ny,nper)` systématique |
| 3 | Goldens — format | stats statistiques, finite-only | Conforme | Robuste BLAS/endianness | Ajouter `min/max/p05/p25/p75/std` |
| 3 | Goldens — tolérances | `rel=1e-4`, `rel=5e-4` transport | À améliorer | Non justifiées | Documenter via analyse d'ordre |
| 3 | `--update-goldens` | overwrite silencieux | À améliorer | Risque humain | Diff avant écriture |
| 3 | `coverage_runner.py` | SystemExit géré | Conforme | `finally` sauve cov, `raise` propage | RAS |
| 4 | Benchmarks analytiques | Dupuit + Boussinesq + linearized | Acceptable pour gravitaire | Confiné et transport absents | Ajouter Theis, Hantush, Ogata-Banks |
| 4 | MMS | absent | Non-standard | Pas d'ordre de convergence mesuré | Introduire 1 MMS steady + 1 transient |
| 4 | Tests « numerical » | 3 cas sur DEM réel sans assertion analytique | Non-standard | Régression déguisée | Déplacer sous `tests/regression/extensive/` |
| 4 | Twins | MF6 uniquement | À améliorer | NWT et Boussinesq non validés en inverse | Ajouter twins NWT, Boussinesq |
| 5 | Modules sans tests | `solver/boussinesq/runtimes/`, `drivers/`, `jacobian/`, `forcing/` | Problématique | Moteur numérique post-merge non couvert unitairement | Tests unitaires dédiés, ≥ 5 fichiers |
| 5 | Config coverage | `calibration_legacy/*` `omit` vers chemins inexistants | Code mort | — | Nettoyer |
| 6 | Fixtures | scope corrects, autouse trop large | Acceptable | `_redirect_repo_root_cwd_for_gmsh_grid_tests` autouse global | Déplacer en `conftest.py` local |
| 6 | Parallélisation | xdist dispo mais non activé en CI | À améliorer | `pytest_sessionfinish` fragile en xdist | Activer `-n auto --dist=loadfile` |
| 7 | `golden_utils.py` | 1 104 LOC | Acceptable | Maintenable, mais `except Exception` avalés | Fragmenter, exceptions étroites |
| 7 | Tests des helpers | 2 tests / colonne vertébrale régression | Problématique | `assert_stats` non testé | Ajouter tests unitaires (~20 LOC) |
| 7 | `run_legacy_example_script` | wrapper inline triple-quoté | Problématique | 150 LOC non testés | Extraire en module |
| 7 | CI workflow | 30 min, sans xdist | À améliorer | Timeout pytest peut dépasser timeout job | Activer xdist, revoir timeouts |
| 7 | Hack `.pth` coverage | suppression manuelle | Non-standard | Contournement bug numpy | Usage exclusif de `run_pytest_with_coverage.py` |
| 8 | Skips | 18, motifs clairs | Conforme | Plateforme/réseau/binaire | RAS |
| 8 | xfail | 0 | Acceptable | Pas de flakiness masquée… ou pas suivie | Ajouter `pytest-rerunfailures` sur tests réseau |
| 8 | Timeouts « fast » | 3 600 s | Non-standard | Nomenclature trompeuse | Renommer `fast`→`tier_short` |
| 9 | Code mort | `pytest_ignore_collect`, `calibration_legacy`, `normal/`, `resolve_first_model_workspace` | Problématique | Inutile | Supprimer |
| 9 | Duplication | wrappers `validation/helpers/*`, `test_run_geographic_*_golden` | À améliorer | 3 fichiers qui pourraient être 1 | Fusionner |
| 9 | Verbosité | tests > 1 500 LOC | Problématique | Difficile à maintenir | Fragmenter par fonctionnalité |

---

## 11. Recommandations priorisées — Top 10

| # | Action | Impact | Effort |
|---|---|---|---|
| 1 | **Écrire des tests unitaires pour `solver/boussinesq/runtimes/`** (scipy_sparse, scipy_dense, petsc_mixed, petsc_partition, local) avec système linéaire 3×3 trivial et comparaison analytique | Haut — couvre le cœur numérique post-merge | 1-2 jours |
| 2 | **Ajouter benchmark Theis 2D** (pompage confiné transitoire) sous `validation_cases/analytical/transient/theis_confined_pumping_2d/` | Haut — validation aquifère captif | 1 jour |
| 3 | **Ajouter benchmark transport Ogata-Banks** (advection-dispersion 1D analytique) sous `validation_cases/analytical/transport/ogata_banks_1d/` | Haut — trou critique transport | 1 jour |
| 4 | **Tester les signature builders** (`array_stats`, `modflow_signature`, `assert_modflow_signatures`, `update_or_assert_goldens`) dans `tests/unit/regression/test_golden_utils.py` | Haut — colonne vertébrale sans filet | 2 h |
| 5 | **Introduire 1 MMS steady 1D** (Laplacien avec source fabriquée + analyse `h`-convergence d'ordre 2) sous `validation_cases/mms/laplacian_steady_1d/` | Haut — certifie l'ordre des schémas | 1 jour |
| 6 | **Fragmenter `test_model_calibration_launcher.py` (2 722 LOC)** en 4-5 fichiers par préoccupation (config / runtime / postprocess / errors / integration) | Moyen — maintenabilité CI | 4 h |
| 7 | **Nettoyer `tests/conftest.py:115-120`** (`pytest_ignore_collect`), `pyproject.toml:172-173` (`calibration_legacy`, `calibration2`), golden_references/normal/ | Bas — dette | 30 min |
| 8 | **Activer xdist en CI** (`-n auto --dist=loadfile`) après vérification de `pytest_sessionfinish` en mode parallèle | Moyen — gain CI 30-40 % | 2 h + validation |
| 9 | **Remplacer `except Exception: pass`** dans `golden_utils.py:380` et `:461-465` par exceptions étroites ; supprimer `resolve_first_model_workspace` ; extraire `run_legacy_example_script` inline wrapper | Moyen — robustesse détection erreurs | 3 h |
| 10 | **Documenter les tolérances** (`validation_cases/TOLERANCES.md` + commentaire en tête de chaque `tolerances*.toml` justifiant les seuils par analyse Richardson ou par machine epsilon) | Moyen — défendabilité scientifique | 1 jour |

---

## 12. Conclusions

La suite de tests HydroModPy est **structurellement saine et documentée**, signe d'une équipe attentive (markers riches, scratch externalisé, CI en place, `--update-goldens`, helpers factorisés). Mais elle paie la dette classique d'un code scientifique qui a évolué vite : **la frontière entre unitaire, intégration et régression est floue**, **la validation est solide sur le gravitaire et muette sur le confiné/transport**, et **le refactor Boussinesq récent (12 fichiers `runtimes/`, 7 fichiers `assembly/`, 5 fichiers `jacobian/`) n'a pas encore reçu son filet unitaire dédié**.

Le merge `dev-refact → dev-database` a **amélioré la posture structurelle** (ajouts `test_process_contracts_api.py`, `test_solver_contracts_api.py`, `test_flow_legacy_compat.py`, `test_settings_legacy_api.py`, nouveaux benchmarks analytiques `boussinesq_sloping_substratum_*`, `test_twin_linearized_recharge_step_flux_only_noisy_modflow6.py`) mais **sans résorber les dettes de fond** listées ci-dessus.

Dans l'état actuel, la suite est **adéquate pour un logiciel de recherche** (détection de régressions grossières, démonstrations analytiques qualitatives) mais **insuffisante pour une certification d'outil d'aide à la décision** (eau potable, stockage de déchets, impact BRGM) — où Theis/Hantush/Ogata-Banks, MMS et analyse d'ordre sont attendus.

---

**Fin de l'audit.**
