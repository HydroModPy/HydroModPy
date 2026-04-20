# Audit critique — Suite de tests HydroModPy

**Perimetre audite :** `tests/` (unit, regression, validation, support), `tests/conftest.py`, infrastructure golden/helpers, workflow CI (`.github/workflows/coverage.yml`).

**Contexte :** HydroModPy est un code scientifique Python 3.11–3.13 pour modelisation hydrogeologique de bassins (FloPy, gmsh, whitebox-workflows). Le referentiel de qualite applique ici est celui de l'ecosysteme scientifique Python (FloPy, xarray, scikit-learn, pandas) et les bonnes pratiques pytest/pytest-xdist.

**Verdict global :** infrastructure de regression **solide** (`golden_utils.py` mature), tests de validation analytique **corrects** en couverture, mais une faille structurelle grave : **la pyramide des tests est inversee**. Les 209 fichiers classes sous `tests/unit/` sont massivement des tests d'integration deguises (I/O disque, subprocess, binaires externes). La couverture unitaire reelle est tres faible sur les modules centraux (`core/`, `data/`, `spatial/`, `workflow/`, `analysis/`). Les tests les plus gros atteignent 2700 lignes — anti-pattern majeur.

---

## Resume des chiffres

| Indicateur | Valeur | Reference industrie | Verdict |
|---|---|---|---|
| Fichiers de test total | 268 | — | — |
| LoC test total | ~49 000 | — | — |
| Fichiers `tests/unit/*` | 209 | >> regression (pyramide) | Trompeur (voir §2) |
| Fichiers `tests/regression/` | 13 (dont 9 vrais tests) | ~5–10 % du total | Acceptable |
| Fichiers `tests/validation/` | 41 (dont 34 tests) | ~5–15 % du total | Bon |
| Tests unitaires >500 lignes | 20+ | <5 % des fichiers | **Problematique** |
| Plus gros test | 2722 lignes (`test_model_calibration_launcher.py`) | <300 recommande | **Non-standard** |
| Utilisation de `tmp_path` | 110 fichiers | — | Fort signal d'integration I/O |
| Utilisation de `unittest.mock` | 4 fichiers seulement | — | **Tres faible** |
| Imports `gmsh`/`flopy` en `tests/unit/` | 2 fichiers | 0 attendu | Leak d'integration |
| `subprocess.run` dans tests | 16 fichiers | 0 en unitaire | **Anti-pattern** |
| Coverage CI | `coverage run` sur `tests/unit/` | Tolere en CI | Acceptable |
| Timeout CI | unit=10 min, regression=30 min | Regression irrealiste | **Probleme** |
| Modules CI testes | master, dev-refact, dev-data, dev-database | — | OK |
| Branche courante dans CI | `dev-database` : OUI | — | OK (CLAUDE.md obsolete) |

---

## 1. Strategie de test — Pyramide inversee

### 1.1 Decoupage unit/regression/validation

**Description.** Trois tiers pytest formellement separes :

- `tests/unit/` (209 fichiers) : suppose teste les composants isoles.
- `tests/regression/fast|extensive/` (9 fichiers) : golden-file signatures sur runs complets via `hmp run`.
- `tests/validation/{analytical,numerical,calibration}` (34 fichiers) : confrontation a des benchmarks analytiques.

Le decoupage **fast / extensive / validation** est assigne par `pytest_collection_modifyitems()` (`tests/conftest.py:82-98`) via le nom du dossier — correct, standard.

**Verdict : conforme sur la nomenclature, non conforme sur le contenu.**

**Justification.**

- La pyramide classique (Cohn 2009, standards industrie) veut beaucoup d'unitaires rapides, peu de e2e lents. Ici la proportion **annoncee** est 209/9/34, saine. Mais la **realite** est inverse :
  - `tests/unit/launchers/test_model_calibration_launcher.py` : 2722 LoC, execute des workflows complets via `ModelCalibrationLauncher`.
  - `tests/unit/data_managers/test_hydrography_full.py` : 1643 LoC, mock HTTP + I/O disque geopandas/SHP/GPKG.
  - `tests/unit/solver/utils/mesh/gmsh_grid/test_reference_2d_geology_conformal_case.py` : 1664 LoC, importe `gmsh` et genere des maillages 3D.
  - `tests/unit/solver/test_boussinesq_backend.py` : 1642 LoC, resout des systemes lineaires reels.
- Le compteur `grep pytest.mark.slow` = 25 fichiers, la plupart sous `tests/unit/` — un test veritablement "unitaire" ne devrait JAMAIS etre marque `slow`.
- `subprocess.run` apparait dans 16 fichiers, dont certains sous `tests/unit/` (exemple : appels via `run_hmp_cli` ou lance de `hmp test regression`).

**Recommandation.**

1. Creer un repertoire `tests/integration/` dedie et **y deplacer** tous les fichiers `tests/unit/*` qui :
   - font de l'I/O reseau (SHOM, HTTP) ;
   - lancent un subprocess ou un binaire MODFLOW ;
   - importent `gmsh`, `flopy`, `rasterio`, `geopandas` en module top-level ;
   - depassent 300 lignes.
2. Exemples a migrer en priorite : `data_managers/test_hydrography_full.py`, `data_managers/test_climatic_managers.py` (742 LoC), tous les `launchers/test_*_launcher.py`, `solver/utils/mesh/gmsh_grid/*`.
3. Ce qui reste dans `tests/unit/` doit viser **<200 ms par test**, **0 subprocess**, **aucun binaire externe**, **aucun I/O reseau**.

### 1.2 Ratio e2e / integration / unit

**Description.** Estime a partir du temps cumule et des patterns : ~5 % unitaires stricts / ~70 % integration / ~25 % e2e regression+validation.

**Verdict : non conforme.** L'ecosysteme Python scientifique (xarray, pandas, scikit-learn) garde >80 % de vraies unites a <1 s, avec mocks systematiques pour les couches lourdes.

**Recommandation.** Cible long terme : 80 % pure unit / 15 % integration / 5 % e2e. Les pipelines MODFLOW/gmsh ne justifient pas 2000 lignes de "unit" test.

---

## 2. Tests unitaires — Verites et fictions

### 2.1 Carte des sous-dossiers `tests/unit/`

| Sous-dossier | Fichiers | Plus gros test | Nature reelle | Verdict |
|---|---|---|---|---|
| `launchers/` | 14 | 2722 LoC | Integration bout-en-bout | **e2e maquille** |
| `solver/utils/mesh/gmsh_grid/` | 48 | 1664 LoC | Maillage gmsh reel | **integration** |
| `data_managers/` | 21 | 1643 LoC | I/O CSV/SHP + mock HTTP | integration |
| `simulation/` | 21 | 998 LoC (boussinesq) | DB DuckDB in-memory + adapters | mixte |
| `geographic/` | 16 | ~520 LoC | Whitebox, rasters, SHP | integration |
| `display/` | 8 | 565 LoC | matplotlib + store Zarr | integration |
| `calibration/` | 6 | 604 LoC | workflows pymc/optim | integration |
| `postprocess/` | 6 | — | NetCDF, Zarr | integration |
| `units/` | 5 | — | **vrai unitaire** (pint) | conforme |
| `config/` | 1 | — | TOML loader | conforme |
| `process/` | 4 | — | configs flow | conforme |
| `field/` | 5 | 518 LoC | field_param avec mesh | mixte |
| `domain/` | 3 | — | pur dataclass | conforme |
| `tools/` | 8 | — | doc gallery scripts | utilitaire |
| `mesh/` | 7 | — | VTU I/O, plotting | integration |
| `hydrology/` | 1 | — | un seul import test | degenere |
| `backends/` | 1 | — | whitebox init | integration |
| `annex/` | 3 | — | catchment ID | integration |
| `regression/` | 1 | — | teste `golden_utils` | meta-test |
| `validation/` | 7 | — | teste runtime validation | meta-test |
| `validation_cases/` | 1 | — | multi-solver | e2e |
| `geographic_synthethic/` | 1 | — | un seul test synthetique | degenere (typo : **devrait etre `geographic_synthetic`**) |

**Note : typo.** `tests/unit/geographic_synthethic/` contient une faute ("synthethic" au lieu de "synthetic"). A corriger.

### 2.2 Isolement et I/O

**Verdict : probleme structurel.**

- `tmp_path` utilise dans 110/209 fichiers : plus d'un test sur deux ecrit sur disque.
- `monkeypatch` ou `patch` utilise dans 68 fichiers mais `unittest.mock.MagicMock` seulement dans 4. Les "mocks" sont principalement des `monkeypatch.setenv` ou `setattr` — pas d'isolation de dependance.
- `tests/conftest.py:61-79` fait un `monkeypatch.chdir(scratch_cwd)` automatique pour tous les tests gmsh_grid. Ce hack indique clairement que **ces tests ne sont pas isoles** : ils polluent le CWD.

**Recommandation.** Suivre la regle de FloPy/scikit-learn :
- Un test unitaire n'ecrit pas sur disque sauf si il teste explicitement l'I/O.
- Utiliser `pyfakefs` ou `io.BytesIO`/`io.StringIO` pour simuler le FS.
- Les solveurs MODFLOW-NWT doivent etre mockes en unitaire (on teste la construction des paquets, pas l'execution du binaire).

### 2.3 Edge cases

**Verdict : quasi-absent.**

- Aucune suite dediee "bords de domaine" : pas de test grille 1x1, pas de test domaine vide, pas de test `NaN`/`Inf` systematique.
- Quelques tests isoles : `geographic/test_catchment_from_point.py` (rejet point vide), `field/test_geology_field.py` (une valeur homogeneisee). Rien de structurant.
- Edge cases hydrogeologiques typiquement absents :
  - proprietes K nulles (cellule inactive pure) ;
  - mailles avec elevation de toit < elevation de base (inversion) ;
  - pas de temps unique en transient ;
  - recharge negative ;
  - drain au-dessus du MNT (devrait erroriser) ;
  - ocean a marnage nul.
- Seul l'extracteur de statistiques fait attention aux non-finis (`golden_utils.array_stats()` ligne 249 : `finite = arr[np.isfinite(arr)]`), mais rien ne teste que le code **produit** des NaN dans les bons cas.

**Recommandation.** Ajouter une suite `tests/unit/edge_cases/` avec parametrize explicite :
```python
@pytest.mark.parametrize("shape", [(1, 1), (1, 100), (100, 1), (2, 2)])
@pytest.mark.parametrize("values", ["all_nan", "all_zero", "mixed_nan", "negative"])
```
et `hypothesis` pour property-based testing sur les conversions d'unites et les operations de maillage.

### 2.4 Duplications et code monstre

**Verdict : **a ameliorer**.**

- Les 14 fichiers `tests/unit/launchers/` cumulent >7000 LoC avec des patterns de setup TOML quasi-identiques. Comparer `test_model_calibration_launcher.py` (2722), `test_method_comparison_launcher.py` (1574), `test_mesh_catchment_launcher.py` (1302), `test_regional_lab_launcher.py` (735) : tous reecrivent leur propre config TOML minimal. **Factorisation triviale** via fixtures partagees dans un `launchers/conftest.py` (absent).
- `tests/unit/data_managers/test_hydrography_full.py:1-80` documente 20+ "sections" dans un seul fichier — anti-pattern : a eclater en modules `test_hydrography_config.py`, `test_hydrography_osm.py`, `test_hydrography_catalog.py` (certains existent deja mais coexistent avec le monolithe).
- Les fixtures `sample_hydro_dir`, `sample_piezo_dir`, `sample_wq_dir` (`tests/unit/data_managers/conftest.py:19-88`) dupliquent **90 % de code** : memes colonnes, memes dates, memes CRS. Factoriser dans une helper `_make_station_csv_dir(name, variable, unit, values)`.

---

## 3. Tests de regression — Golden references

### 3.1 Infrastructure (`golden_utils.py`, 1104 lignes)

**Verdict : solide mais surdimensionne.**

Points forts :

- Strategie statistiques compactes `(count, mean, p50, p95, shape, sum)` — standard de l'industrie pour des codes numeriques (ex. FloPy utilise la meme approche).
- Tolerances documentees : `rel=1e-4, abs=1e-6` pour flow, `rel=5e-4, abs=1e-5` pour transport (`golden_utils.py:820-828`). Choix coherent : transport advection-dispersion est plus bruyant.
- Dispatch tiered (`resolve_tiered_golden_file`, ligne 150-165) : fast/extensive physiquement separes, pas de collision.
- `assert_required_executables()` (ligne 642-690) skip proprement si binaires MODFLOW absents — **bonne pratique**, evite faux positifs CI.
- `require_url_available()` (ligne 693-718) skip si SHOM/HTTP indisponible — evite flakiness reseau.
- `remove_tree_with_retry()` (ligne 90-123) : gestion des verrous Windows, retries avec backoff, test dedie (`tests/unit/regression/test_golden_utils.py`).

Points faibles :

| Probleme | Ligne | Gravite | Remediation |
|---|---|---|---|
| `run_legacy_example_script()` = 144 lignes de wrapper inline via `python -c` | 957-1100 | **grave** | Dead code a supprimer : le README dit "Legacy folders are no longer part of the active test workflow". |
| `store_field_signature()` balaie les timesteps par `for t in range(10000)` puis `try/except` | 456-466 | moyen | Remplacer par `store.list_timesteps(sim_id, variable)` ou equivalent. `range(10000)` est un smell. |
| `except (KeyError, IndexError, Exception)` attrape `Exception` generique | 461, 380 | grave | Rattraper explicitement `zarr.errors.BoundsCheckError` et `KeyError` seuls. L'Exception generique cache des bugs. |
| `collect_store_modpath_signatures` : `except (KeyError, Exception): pass` | 380-381 | grave | Memes remarques : **swallow silencieux d'exceptions generiques**. |
| Determinisme de `sum` sur float sans `np.kahan_sum` | 269 | faible | Sur grands arrays, `sum` accumule des erreurs d'arrondi dependantes de l'ordre. Prefere `float(np.sum(arr.astype('float64'), dtype='float64'))` ou Kahan. |
| `resolve_tiered_golden_file` parse `test_file` parts en set, puis teste `"extensive" in parts` | 163-164 | faible | Collision possible si un chemin contient `extensive` fortuitement (non critique ici mais fragile). |
| Pas de gel de `platform.python_version()` dans les goldens | — | moyen | En cas de changement de Python/numpy, la difference cache peut etre ignoree. Ajouter un champ `_metadata.python_version` dans le JSON. |

### 3.2 Deterministe cross-platform ?

**Verdict : acceptable.**

- La tolerance `rel=1e-4, abs=1e-6` couvre les differences BLAS/Windows vs Linux typiques.
- `array_stats()` filtre `np.isfinite` — les `NaN` n'explosent pas la comparaison.
- Mais : **endianness non testee**. Si les `.npy` sont ecrits en little-endian et lus sur une machine big-endian (peu probable mais non trivial), rien ne le detecterait. En pratique le risque est nul pour du x86/ARM moderne, mais la doc devrait le dire.
- **Ordre non deterministe** : les `sum` sur des arrays volumineux dependent de l'ordre d'accumulation (reproduction BLAS multi-thread). `configure_whitebox_single_thread()` existe pour ca dans `tests/support/whitebox.py` mais n'est applique **qu'aux tests Whitebox**. Pour MODFLOW-NWT et surtout PETSc, aucune forcage `OMP_NUM_THREADS=1`. **C'est une bombe a retardement** pour flakiness.

**Recommandation.** Ajouter dans `tests/conftest.py:24-36` un `os.environ.setdefault("OMP_NUM_THREADS", "1")` + `MKL_NUM_THREADS=1` global pour garantir la reproductibilite des sommes.

### 3.3 `coverage_runner.py` — bug SystemExit

**Verdict : l'implementation actuelle est CORRECTE.** L'instruction de l'utilisateur mentionne un bug SystemExit non capture — je ne le confirme pas apres lecture.

**Analyse ligne par ligne (`tests/regression/coverage_runner.py:32-45`) :**

```python
except SystemExit as exc:
    if exc.code != 0:
        import traceback
        print(..., file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    raise                    # <-- preserve le code de sortie vers CI
except BaseException:
    import traceback
    traceback.print_exc(file=sys.stderr)
    raise
finally:
    cov.stop()
    cov.save()
```

- Le `raise` final preserve le code de sortie non nul, donc CI detecte bien l'echec.
- Le `finally` garantit que `cov.save()` s'execute meme si le script appele `sys.exit(1)`.
- **Mais** : le `except BaseException` attrape `KeyboardInterrupt` et `SystemExit` (redondant car `SystemExit` deja attrapee plus haut). En Python, `SystemExit` est `BaseException`, pas `Exception`. La premiere clause `except SystemExit` matche d'abord, donc OK — mais la logique est confuse. Le **vrai smell** : le `import traceback` a l'interieur d'except (x2) pour eviter un import tardif en cas de panique tres grave. Pratique defensive acceptable, documentation utile absente.

**Ce qui manquerait :** un test unitaire sur `coverage_runner.py` lui-meme (verifier que le code de sortie est preserve). Actuellement le wrapper n'a aucun test dedie.

### 3.4 Tests de regression (9 fichiers)

**Verdict : correct mais minces.**

- Chaque test est 15-30 lignes, delegue a `run_launcher_simulation_*_regression()`. Pattern DRY respecte.
- `tests/regression/launcher_simulation_helpers.py` centralise 334 lignes de setup — acceptable.
- **Couverture scenarios :**
  - `fast/boussinesq` (flow simple)
  - `fast/boussinesq_divide` (ligne de partage)
  - `fast/mf6` (MODFLOW 6)
  - `fast/nwt` (MODFLOW-NWT + MODPATH)
  - `extensive/mf6`, `extensive/nwt` (avec MT3DMS/transport)
  - `extensive/data_overview`
  - `extensive/run_geographic_case_{metrics, river_network}`
- **Manquant :**
  - Aucun test de regression batch (`analysis/batch/`) alors que c'est un workflow de production.
  - Aucun test de regression sur les exporters (`results/exporters/{netcdf,shapefile,vtu,geotiff,csv}.py`) — 5 formats d'export non regresses.
  - Aucun test de regression sur la calibration (seulement des tests analytiques "twin").
- **Timeouts** : 1800–7200 secondes. Tres generaux. Sur CI 30 min (voir `coverage.yml:69`), un `extensive` de 7200 s depassera le timeout CI. Soit le CI ne les execute pas, soit il est regulierement interrompu.

### 3.5 Golden files et update

**Verdict : acceptable mais pas assez documente.**

- 11 fichiers JSON dans `tests/regression/reference/golden_references/{fast,extensive,normal}/`.
- Tier `normal/` subsiste avec 2 fichiers (`launcher_simulation_normal_*`) mais plus aucun test ne les cite (dead references ?). **A supprimer.**
- Processus `--update-goldens` correctement document dans `tests/regression/README.md`. Option declaree ligne 41-46 de `conftest.py`.
- **Ce qui manque** : aucun mecanisme de verification que l'update a ete **revu** (ex. en CI, echouer si `git diff` sur les goldens est produit par un commit non approuve explicitement). C'est un garde-fou classique : les goldens doivent etre mis a jour volontairement, pas par accident.

---

## 4. Tests de validation — Benchmarks analytiques

### 4.1 Panorama

**Verdict : tres bonne couverture analytique, standard du domaine.**

| Benchmark | Type | Fichier | LoC | Solveurs testes | Verdict |
|---|---|---|---|---|---|
| Dupuit fixed-head 1D | steady | `analytical/steady/test_dupuit_fixed_head_1d.py` | 56 | NWT, MF6, Boussinesq | **standard** |
| Dupuit divide river 1D | steady | idem | 56 | — | standard |
| Dupuit uniform recharge 1D | steady | idem | 56 | — | standard |
| Dupuit circular island 2D | steady | idem | 64 | — | standard |
| Dupuit fixed-head PETSc 1D | steady | idem | 61 | PETSc | bon |
| Boussinesq piecewise K 1D | steady | 4 variantes | 52-53 | Boussinesq | bon |
| Boussinesq circular island 2D | steady | idem | 64 | — | bon |
| Boussinesq hillslope interception | steady | idem | 52 | — | bon |
| Linearized unconfined drainage | steady | idem | 53-65 | — | bon |
| Brutsaert recession | transient | idem | 68 | — | **excellent** (reference classique) |
| Boussinesq hillslope recharge step | transient | idem | 71 | — | bon |
| Late-time unconfined pumping 2D | transient | idem | 72 | — | Theis-like, approche Neuman (verifier) |
| Linearized unconfined boundary/recharge step/periodic | transient | idem | 66-69 | — | bon |
| Headwater 100 km² PETSc | numerical | steady + transient | 133 + 261 | PETSc only | solide |
| Hillslope pulse overflow PETSc | numerical transient | 79 | — | bon |
| Twin experiments calibration | calibration | 5 fichiers | 52-77 | MF6 | bon |

**Points forts :**

- Le trio "NWT / MF6 / Boussinesq" est systematiquement teste via `parametrize` — excellent.
- Brutsaert recession : presence de la reference historique incontournable en hydrogeologie de versant (Brutsaert & Nieber 1977, Bogaart 2013).
- Les tolerances sont chargees depuis un fichier externe (`comparison.tolerances`, voir `test_dupuit_fixed_head_1d.py:42`) — pas de magic numbers dans les tests.
- Helpers de metrique (`rmse`, `max_abs_error`, `mean_along_axis`, `max_std_along_axis` dans `validation_cases/shared/metrics.py`) — reutilises partout.

**Manques critiques :**

- **Aucun Theis transient classique.** Theis (1935) est LE benchmark de reference pour le pompage transitoire en nappe captive. Son absence est surprenante pour un code de modelisation hydrogeologique. Le fichier `test_late_time_unconfined_pumping_2d.py` touche un regime asymptotique mais pas le cas Theis pur.
- **Aucun Hantush-Jacob** (aquifer semi-captif avec drainance). Classique MODFLOW — absent.
- **Aucun test de convergence en maillage** (grid refinement study). Les benchmarks MODFLOW standards (MacDonald & Harbaugh, McWhorter & Sunada, Zheng & Wang) incluent typiquement une etude h/2, h/4 pour estimer l'ordre de convergence. Ici la tolerance est absolue, pas relative a la finesse de maillage.
- **Aucun test MMS (Method of Manufactured Solutions).** MMS est la reference moderne pour verifier un code numerique (Roache, Oberkampf & Roy). Pour un code "scientifique", l'absence de MMS est un manque severe.
- **Aucun test de bilan de masse** explicit : le code a un champ `mass_balance` dans DuckDB mais aucun test ne verifie que `|inflow - outflow - dstorage| < eps`. Critique : c'est la verification N°1 d'un solveur MODFLOW.
- **Aucun test de symetrie/invariance.** Ex. rotation d'un cas 1D dans 2D -> meme resultat. Standard en validation numerique.

**Recommandation prioritaire.** Ajouter :
1. Theis transient (analytique).
2. Hantush-Jacob semi-captif.
3. Un MMS simple pour Dupuit 2D.
4. Un test de bilan de masse pour chaque solveur (NWT, MF6, Boussinesq) : `|sum(flux_in) - sum(flux_out) - sum(dstorage)| / sum(|flux|) < 1e-6`.
5. Un test de convergence en maillage (L2 error ~ h^1 ou h^2 selon le schema).

### 4.2 Criteres de convergence

**Verdict : satisfaisant, documente partiellement.**

- `assert_metric_below()` (`tests/validation/helpers/assertions.py:6`) est minimaliste : 7 lignes, un seul assert. Bien nomme, bien ecrit.
- Les tolerances viennent de `tolerances.yaml`/`tolerances.toml` (voir `load_case_tolerances` dans `validation_cases/shared/loaders.py`). Externe, reviewable.
- **Manquant** : aucune justification scientifique des tolerances. Pourquoi 1e-4 et pas 1e-6 ? Pas de commentaire du type "tolerance choisie pour absorber variance BLAS multi-thread + precision float32 MODFLOW".

---

## 5. Couverture de code

### 5.1 Configuration coverage CI

**Verdict : acceptable, avec trous.**

`.github/workflows/coverage.yml:44-45` :

```yaml
coverage run --rcfile=/dev/null \
  --include="hydromodpy/*" \
  --omit="hydromodpy/**/cases/*,hydromodpy/**/examples/*,hydromodpy/calibration_legacy/*,hydromodpy/calibration2/*"
```

- Exclusion de `cases/` et `examples/` : OK (ce sont des scripts).
- Exclusion de `calibration_legacy/` et `calibration2/` : **signal de dette technique**. `calibration2` est probablement la nouvelle implementation en cours, non encore stabilisee. A clarifier.
- Pas de seuil `fail_under=` : **la couverture peut regresser silencieusement**. A ajouter : `coverage report --fail-under=70`.
- `fail_ci_if_error: false` sur Codecov : la perte de rapport Codecov n'echoue pas le CI. OK, mais couple au point precedent, le controle qualite est laxiste.

### 5.2 Modules sans tests unitaires directs

D'apres la carte source/tests :

| Module source | Fichiers | Tests directs | Couverture reelle |
|---|---|---|---|
| `hydromodpy/analysis/` | 135 | 0 (dossier `tests/unit/analysis/` absent) | indirecte via regression |
| `hydromodpy/core/` | 41 | 1 (`unit/config/test_toml_loader.py`) + 5 `unit/units/` | partielle |
| `hydromodpy/data/` | 170 | 21 `unit/data_managers/` (integration) | partielle |
| `hydromodpy/spatial/` | 90 | 16 `unit/geographic/` + 5 `unit/field/` + 3 `unit/domain/` + 7 `unit/mesh/` = 31 | bonne sur fragments |
| `hydromodpy/results/` | 18 | couverts via `unit/simulation/` (21) | bonne |
| `hydromodpy/simulation/` | 39 | 21 | bonne |
| `hydromodpy/solver/` | 180 | 53 (mais 48 dans gmsh_grid !) | maillage OK, solveurs faible |
| `hydromodpy/process/` | 58 | 4 | **tres faible** |
| `hydromodpy/workflow/` | 14 | 0 (aucun dossier `tests/unit/workflow/`) | **zero** |
| `hydromodpy/runners/` | 12 | 1 (`test_hmp_regression_cli.py`) | **tres faible** |
| `hydromodpy/watershed/` | 5 | 0 | **zero** |

**Verdict : plusieurs modules critiques non ou sous-testes.**

Les modules **sans tests unitaires directs** :

1. `hydromodpy/workflow/` (14 fichiers) — orchestration pipeline. Aucun test.
2. `hydromodpy/watershed/` (5 fichiers) — classe Watershed utilisee dans le wrapper legacy. Aucun test.
3. `hydromodpy/analysis/` (135 fichiers) — le plus gros sous-module, contient batch/calibration/comparison/display/postprocess. Aucun test `tests/unit/analysis/`.
4. `hydromodpy/process/` (58 fichiers, incl. `flow/`, `transport/`, `forcing/`, `hydrology/`, `base/`) — seulement 4 tests unitaires de config.

Chemin critique non teste detectable : `hydromodpy/simulation/planning/` (resolution de plan immuable), `hydromodpy/simulation/execution/` (orchestrateur `SimulationRunner`). Ce sont le cœur de la logique d'execution. Les tests `tests/unit/simulation/` se concentrent sur le catalogue et les adapters, pas sur le planner lui-meme.

**Recommandation.** Prioriser la couverture de :
- `hydromodpy/simulation/planning/planner.py` : test unitaire que `SimulationPlanner.plan(config)` retourne un plan frozen attendu, avec mocks sur solveurs.
- `hydromodpy/process/flow/` et `hydromodpy/process/transport/` : tests de configuration et de dispatch vers adapter.
- `hydromodpy/workflow/steps/` : chaque step doit avoir un test unitaire avec contextes mockes.
- `hydromodpy/results/catalog.py` : tests CRUD directs sur DuckDB in-memory.

### 5.3 Observations sur `coverage_runner.py`

**Verdict : OK.** Contrairement a ce que suggere l'instruction, le `SystemExit` est bien re-raised. Le vrai probleme est ailleurs : **absence de test pour le runner lui-meme**.

---

## 6. Fixtures — Scopes et effets de bord

### 6.1 Inventaire

| Fixture | Fichier | Scope | Remarques |
|---|---|---|---|
| `update_goldens` | `conftest.py:49` | session | OK |
| `hydromodpy_test_scratch_root` | `conftest.py:55` | session | OK |
| `_redirect_repo_root_cwd_for_gmsh_grid_tests` | `conftest.py:61` | function, autouse | **Hack** : ne s'applique qu'a un sous-dossier, mais est **autouse** donc execute pour TOUS les tests (effet `return` si non match). Cout marginal mais anti-pattern. |
| `tmp_data_dir` | `data_managers/conftest.py:14` | function (implicite) | Wrapper trivial sur `tmp_path` — **dead code**, a supprimer. |
| `sample_hydro_dir` | idem:20 | function | OK mais duplique avec `sample_piezo_dir` et `sample_wq_dir` |
| `sample_piezo_dir` | idem:44 | function | duplique |
| `sample_wq_dir` | idem:68 | function | duplique |
| `project_period` | idem:92 | function | Devrait etre scope `session` : c'est un tuple immuable hardcode. |
| `validation_cases_root` | `validation/conftest.py:14` | session | OK |

### 6.2 Effets de bord

**Verdict : globalement bien isole mais quelques zones grises.**

- **Nettoyage scratch.** `pytest_sessionfinish` (`conftest.py:101-113`) supprime `_TEST_SCRATCH_ROOT` **uniquement sur le controleur xdist** (ligne 107 : `if is_xdist_worker: return`). Correct : evite les races avec `shutil.rmtree`.
- **Collision tmpdir.** `HYDROMODPY_TEST_SCRATCH_ROOT` fixe globalement (`conftest.py:32`) implique que deux sessions pytest concurrentes **sur la meme machine** partagent le meme scratch et se sabotent mutuellement. A documenter ou a randomiser (`mkdtemp` par session).
- **DB partagee.** Tests `test_simulation_api.py`, `test_catalog_import_export.py` utilisent probablement un `catalog` module-scoped — verification necessaire, mais le pattern DuckDB en memoire (`:memory:`) est sain s'il est applique.
- **Binaires MODFLOW partages en bin/linux/**. Les tests manipulent les permissions via `ensure_platform_executable()` — `chmod +x` persistant au repo. Non-reversible sur clone fraiche. Anti-pattern : devrait copier le binaire dans un scratch tmp_path et `chmod` la copie.

### 6.3 Parallelisabilite (`pytest-xdist`)

**Verdict : bonne.**

- `tmp_path` isolation native.
- Scratch externe via env.
- `pytest_sessionfinish` xdist-aware.
- Mais : **tests qui modifient `os.chdir` via `monkeypatch.chdir()`** (ex. gmsh_grid) — OK avec xdist car chaque worker a son CWD, mais impose une fixture autouse qui s'execute pour chaque test.

---

## 7. Infrastructure — `golden_utils` et `launcher_simulation_helpers`

### 7.1 `golden_utils.py` (1104 LoC)

**Verdict : acceptable, mais surdimensionne.**

- 28 fonctions dont 7 sont de petits wrappers a une ligne (`load_json_payload`, `load_golden_reference`, `collect_modflow_signatures`, `collect_modpath_signatures`, `collect_npz_signatures`, `collect_json_signatures`, `resolve_first_model_workspace`). **Plusieurs auraient pu etre inlines.**
- `run_legacy_example_script` (142 LoC de string inline Python) est **dead code** : le README affirme que le legacy n'est plus teste. A supprimer completement. Gain : ~150 lignes nettes.
- `run_example_script` vs `run_hmp_cli` : 80 % de logique dupliquee (setup env, coverage wrapper, subprocess.run, assert returncode). A factoriser.
- **Duplication entre `array_signature` (ligne 260) et `modflow_signature` (ligne 304)** : les deux produisent `{count, mean, p50, p95, shape, sum}`. Diff : `modflow_signature` charge un dict npy et ajoute `timestep/available_timesteps`. Refactorer : `modflow_signature = array_signature(last_timestep_array) | {"timestep": ..., "available_timesteps": ...}`.
- **Duplication entre `store_field_signature` (ligne 449) et `modflow_signature`** : meme stats, juste source de donnees differente (Zarr vs npy). Meme refactor.
- `_assert_json_signature_value` (ligne 590-621) : dispatch manuel sur types Python, fragile. Utiliser `numbers.Real` et `collections.abc`.

### 7.2 `launcher_simulation_helpers.py` (334 LoC)

**Verdict : acceptable.**

- Constantes bien nommees (`MODFLOW_OUTPUT_NAMES`, `BOUSSINESQ_SUMMARY_KEYS`, etc.).
- Deux fonctions principales (`run_launcher_simulation_regression`, `run_launcher_simulation_boussinesq_regression`) : 70 + 80 LoC, lisibles.
- `_ensure_local_oceanic_seed_csv` et `_ensure_custom_format_files` font de l'I/O reseau SHOM. **Mal place** : appartient a `tests/support/oceanic_fixtures.py` ou une fixture session-scope, pas a un helper de regression. Et si le reseau est indisponible, tous les tests SHOM-dependants skippent — pattern acceptable mais rend la suite "environnementale".
- Dependances sur `validation_cases.shared.*` : le code test depend de code qui n'est pas dans `tests/` — acceptable mais couple fortement.

### 7.3 Les helpers sont-ils testes ?

**Verdict : partiellement.**

- `tests/unit/regression/test_golden_utils.py` (100 LoC) teste UNIQUEMENT `resolve_tiered_results_dir` avec deux variantes Windows-lock. C'est 2 tests pour 1104 lignes de helpers. **Couverture de helpers < 5 %.**
- `array_stats`, `array_signature`, `modflow_signature`, `assert_stats`, `assert_modflow_signatures`, `assert_json_signatures`, `store_field_signature` : **aucun test direct**.
- Meta-test manquant critique : que `assert_stats` **echoue** quand les stats divergent. Sans ce test, un bug dans l'assertion passerait silencieusement (les regressions ne seraient plus detectees).

**Recommandation forte.** Ajouter `tests/unit/regression/test_signatures.py` couvrant :
- `array_stats(all_nan)`, `array_stats(empty)`, `array_stats(single_value)`.
- `array_signature(integer_array)` -> verifier conversion float.
- `assert_stats(equal)` -> ne leve pas.
- `assert_stats(diverge_at_rel_1e-3)` -> leve.
- `assert_modflow_signatures(missing_key)` -> leve.

---

## 8. CI — Pipeline et fiabilite

### 8.1 Configuration actuelle

**Verdict : basique, avec plusieurs problemes.**

- **Un seul OS :** `ubuntu-latest`. Le code cible Windows + Linux + macOS (voir `assert_required_executables` dans `golden_utils.py:658-674`). **La CI ne valide jamais Windows ni macOS.**
- **Une seule version Python :** 3.12. La pyproject dit 3.11-3.13. **Pas de matrix.**
- **Timeout unit 10 min :** raisonnable pour 209 fichiers si vraiment unitaires. En realite avec les tests monstres (`test_model_calibration_launcher.py` seul peut prendre des minutes), **risque de timeout**.
- **Timeout regression 30 min :** alors que les tests internes ont `timeout=7200` (2h). **Mismatch flagrant**. Les tests extensive sont de fait **impossibles** a executer entierement en CI. Verifier si la CI ne les execute que via `-m "regression and fast"` implicite.

Le job regression execute `tests/regression/fast/ tests/regression/extensive/` (ligne 102-103) **sans filter**, donc extensive est bien execute. Avec 30 min de timeout et 4 tests extensive a 7200s chacun, **la CI doit echouer regulierement par timeout**.

### 8.2 Flakiness detectable

**Verdict : risques identifies, non controles.**

Sources de flakiness connues :

1. **SHOM HTTP** : `require_url_available()` skip les tests si reseau down — OK mais la couverture apparente diminue silencieusement.
2. **Thread non determinisme** : absence de `OMP_NUM_THREADS=1` global (voir §3.2).
3. **Windows file locks** : deja geres par `remove_tree_with_retry()`, mais le CI n'est pas Windows donc pas de pratique reelle.
4. **Dependance binaires `bin/linux/mfnwt`** : executable dans le repo, sensible a `chmod +x`. `ensure_platform_executable` normalise, mais peut echouer sur un clone fraiche avec permissions bizarres.
5. **`range(10000)` dans `store_field_signature`** : perf degradee si Zarr genere des exceptions couteuses sur les OOB.

Aucun pytest-repeat/pytest-rerunfailures configure — **pas de protection contre la flakiness**.

**Recommandation.**
- Matrix OS × Python : `[ubuntu, windows, macos]` × `[3.11, 3.12, 3.13]`.
- Ajouter `pytest-timeout` global avec override par marker (fast: 300s, slow: 1800s, extensive: 7200s).
- Ajouter `OMP_NUM_THREADS=1` dans le CI env.
- Introduire `pytest --rerun-fails=1` pour un minimum de resilience.
- Ajouter un job dedie `validation` qui run `pytest -m "validation and fast"` sur CI (actuellement pas de job validation, seulement unit + regression).

### 8.3 `linux-boussinesq.yml`

Non lu en detail mais presence signalee (`.github/workflows/linux-boussinesq.yml`). Probablement un job dedie au solveur Boussinesq Rust/PETSc. A auditer separement.

---

## 9. Recapitulatif — Tableau des verdicts

| Dimension | Verdict | Justification | Recommandation cle |
|---|---|---|---|
| Decoupage 3 tiers | **conforme** (nomenclature) | fast/extensive/validation ok | — |
| Contenu des "unit tests" | **problematique** | tests monstres, I/O, subprocess | Creer `tests/integration/` et migrer |
| Isolement unitaires | **a ameliorer** | 110/209 fichiers ecrivent sur disque | Mocker I/O ; pyfakefs |
| Edge cases | **absent** | rares, non-systematiques | Suite dediee + hypothesis |
| Regression golden | **conforme** | stats compactes, tolerances, skip binaires | Garder |
| `golden_utils.py` | **acceptable** | surdimensionne, `run_legacy_example_script` dead | Retrait legacy, factoriser |
| `coverage_runner.py` | **conforme** | SystemExit bien re-raised | Ajouter test unitaire dedie |
| Determinisme | **a ameliorer** | pas de `OMP_NUM_THREADS=1` global | Fixer dans conftest |
| Validation analytique | **conforme** | Dupuit/Boussinesq/Brutsaert couverts | Ajouter Theis, Hantush, MMS |
| Bilan de masse | **absent** | pas de verification explicite | Critique — ajouter |
| Couverture `analysis/` | **problematique** | 135 fichiers, 0 test direct | Creer `tests/unit/analysis/` |
| Couverture `workflow/` | **problematique** | 0 test | Idem |
| Couverture `process/` | **a ameliorer** | 4 tests pour 58 fichiers | Idem |
| Fixtures | **acceptable** | scopes corrects, duplication mineure | Factoriser `sample_*_dir` |
| Parallelisme xdist | **conforme** | scratch externe, sessionfinish xdist-aware | Documenter collisions concurrent |
| CI OS/Python matrix | **non conforme** | 1 OS, 1 version | Matrix 3x3 |
| CI timeouts | **problematique** | regression 30 min vs tests 7200s | Augmenter ou filtrer `-m fast` |
| Flakiness controlee | **absent** | aucun rerun, pas de thread pin | pytest-rerunfailures, OMP=1 |
| Tests monstres | **a ameliorer** | 2722 LoC dans un fichier | Decouper par theme |
| Duplication | **a ameliorer** | 14 launchers dupliquent setup TOML | `launchers/conftest.py` partage |
| Dead code | **a ameliorer** | `run_legacy_example_script`, tier `normal/` | Supprimer |
| Tests du tests | **a ameliorer** | `golden_utils` teste a 5 % | Tests de signatures |
| Documentation tests | **a ameliorer** | pas de justification tolerances | Commenter pourquoi `1e-4` |

---

## 10. Recommandations priorisees — Top 5 des tests manquants les plus critiques

### #1 — Test de bilan de masse par solveur (CRITIQUE)

**Pourquoi :** c'est la verification N°1 d'un code MODFLOW. Sans elle, on ne peut pas certifier que les inflows/outflows/dstorage s'equilibrent. Ici la table `mass_balance` existe dans DuckDB (voir CLAUDE.md) mais **aucun test** ne verifie sa coherence.

**Ou :** `tests/validation/numerical/test_mass_balance_<solver>.py` pour NWT, MF6, Boussinesq.

**Assertion :**
```python
inflow = total_recharge + total_well_in + total_bc_in
outflow = total_drain + total_well_out + total_bc_out
delta_storage = storage_end - storage_start
assert abs(inflow - outflow - delta_storage) / max(abs(inflow), 1.0) < 1e-6
```

### #2 — Tests unitaires `hydromodpy/simulation/planning/` et `execution/`

**Pourquoi :** c'est le cœur de l'orchestration (`SimulationPlanner`, `SimulationRunner`, `SimulationPlan` frozen). Actuellement seuls les adapters et le catalogue sont testes.

**Ou :** `tests/unit/simulation/test_planner.py`, `test_runner.py`.

**Contenu :**
- `SimulationPlanner.plan(config_minimal)` -> retourne un `SimulationPlan` frozen avec la bonne sequence `ProcessRun`.
- `SimulationPlanner.plan(config_with_transport)` -> inclut l'adapter transport.
- Rejet d'un config invalide (process manquant, solveur non registre).
- Determinisme : meme config -> meme plan.

### #3 — Test Theis transient analytique (CRITIQUE)

**Pourquoi :** benchmark de reference historique en hydrogeologie (Theis 1935). Son absence est anormale pour un code qui se veut rigoureux. Permet de valider la reponse transitoire au pompage en nappe captive.

**Ou :** `tests/validation/analytical/transient/test_theis_pumping_well_2d.py`.

**Assertion :**
- Solution analytique : `s(r, t) = (Q / 4πT) * W(u)` avec `u = r²S/(4Tt)`.
- Parametrer Q, T, S, r, t.
- Comparer drawdown numerique vs analytique, RMSE <1%.

### #4 — Tests unitaires `hydromodpy/workflow/`

**Pourquoi :** 14 fichiers, 0 test. Le pipeline compose les etapes. Un bug dans une step casse tous les runners.

**Ou :** `tests/unit/workflow/test_pipelines.py`, `test_steps_*.py`.

**Contenu :**
- Chaque step avec contexte mocke : inputs -> outputs conformes au contrat.
- Composition : `Pipeline(step1, step2, step3).run(ctx)` produit le bon `ctx` final.
- Gestion d'erreur : une step qui leve propage correctement.

### #5 — Tests de convergence en maillage (MMS ou grid refinement)

**Pourquoi :** les benchmarks analytiques actuels utilisent une tolerance absolue. Un test de convergence verifie que l'erreur diminue avec `h` a l'ordre attendu (typiquement 1 pour un schema VF cell-centered, 2 pour elements finis Lagrange P1). C'est ce qui distingue un code "qui marche" d'un code **verifie** au sens Oberkampf & Roy.

**Ou :** `tests/validation/analytical/convergence/test_dupuit_grid_convergence.py`.

**Contenu :**
- Lancer Dupuit 1D sur 3 resolutions : h, h/2, h/4.
- Mesurer erreur L2 vs solution analytique.
- Asserter `log(e_h) - log(e_h/2) ≈ order` avec `order=1.0 ± 0.2` (ou 2.0 selon schema).

---

## 11. Annexe — Problemes mineurs mais a corriger

1. **Typo repertoire :** `tests/unit/geographic_synthethic/` -> `geographic_synthetic`.
2. **Tier mort :** `tests/regression/reference/golden_references/normal/` — deux JSON orphelins, plus reference par aucun test. A supprimer.
3. **Dead code :** `run_legacy_example_script()` dans `golden_utils.py:957-1100`. Le README confirme que le legacy n'est plus teste.
4. **Wrapper inutile :** `tmp_data_dir` fixture (`data_managers/conftest.py:14`) = `tmp_path` redirecteur, supprimable.
5. **Wrapper inutile :** `resolve_first_model_workspace` (`golden_utils.py:772`) — "Backward-compatible wrapper" appele potentiellement nulle part. Verifier et supprimer si dead.
6. **`try/except` trop genereux :** `except (KeyError, IndexError, Exception): pass` (`golden_utils.py:380`) masque les vrais bugs.
7. **Magic range :** `for t in range(10000)` dans `store_field_signature()` — remplacer par une API metadata.
8. **`pytest_ignore_collect` vide :** `conftest.py:115-120` retourne toujours `False`. **Dead hook**, a supprimer.
9. **`_path_has_suffix_parts` helper private** : utilise une seule fois. Inliner.
10. **`scope="module"` manquant** : `project_period` et `validation_cases_root` peuvent etre `session` (immuables).
11. **README timing distribution :** `tests/README_timing_distribution.md` (1122 octets) — documentation orpheline, a consolider avec `tests/regression/README.md`.
12. **Marker `integration` peu utilise :** seulement 2 occurrences. Soit l'adopter systematiquement, soit le retirer.

---

## 12. Conclusion

L'infrastructure de regression de HydroModPy (`golden_utils.py`) est **professionnelle et conforme aux bonnes pratiques** de l'ecosysteme scientifique Python. Les tests de validation analytique couvrent les benchmarks historiques pertinents (Dupuit, Brutsaert, Boussinesq lineaire) et exploitent correctement `pytest.parametrize` pour tester plusieurs solveurs.

En revanche, la **pyramide des tests est inversee** : `tests/unit/` contient majoritairement des tests d'integration lourds (>500 lignes, I/O reseau, subprocess, binaires). Les modules centraux `workflow/`, `analysis/`, `process/`, `runners/`, `watershed/` sont **tres faiblement couverts en tests unitaires directs**. Des verifications critiques en hydrogeologie manquent : **bilan de masse**, **Theis transient**, **Hantush**, **MMS**, **convergence en maillage**.

Le pipeline CI est **sous-dimensionne** : un seul OS, une seule version Python, timeouts incoherents avec les tests declares, aucun controle de flakiness. Les tests de regression "extensive" avec `timeout=7200s` (dans le code) ne sont de fait pas executables dans un CI de 30 min.

**Priorites d'action immediates (4 semaines) :**
1. Ajouter un job CI `validation --fast` + matrix OS.
2. Ajouter `OMP_NUM_THREADS=1` global dans `tests/conftest.py`.
3. Creer `tests/integration/` et deplacer les tests monstres.
4. Ajouter les tests de bilan de masse pour les 3 solveurs.
5. Supprimer `run_legacy_example_script` et tier `normal/`.

**Priorites moyen terme (3 mois) :**
- Theis, Hantush, MMS, convergence.
- Tests unitaires pour `workflow/`, `process/flow`, `simulation/planning`.
- Decouper les tests >500 lignes.
- Factoriser les fixtures launchers.

Score global **7/10** : base solide, ecart structurel majeur a resorber sur la pyramide de test.
