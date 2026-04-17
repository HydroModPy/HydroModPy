# Audit des tests

Date: `2026-04-17`

## Methode

Les mesures ci-dessous ont ete faites dans un **worktree propre sur `HEAD`**
pour ne pas melanger l'audit avec les changements locaux en cours.

Constats de base sur l'etat mesure :

- import simple `hydromodpy` : `~9.37 s`
- collecte globale `tests/unit tests/regression tests/validation` :
  - `1639` tests collectes
  - `23` erreurs de collecte
  - `41.73 s` de collecte
- les erreurs de collecte ne sont pas un probleme de perf :
  - elles viennent surtout de la resolution `launchers.*`
  - elles bloquent aujourd'hui `tests/unit/launchers/*`
  - elles bloquent aussi la validation calibration et une partie des validations numeriques PETSc

## Mesures clefs

### 1. Unit collectable

Commande mesuree :

```powershell
python -m pytest tests/unit/annex tests/unit/backends tests/unit/calibration tests/unit/config tests/unit/data_managers tests/unit/display tests/unit/domain tests/unit/field tests/unit/geographic tests/unit/geographic_synthethic tests/unit/hydrology tests/unit/mesh tests/unit/postprocess tests/unit/process tests/unit/regression tests/unit/simulation tests/unit/solver tests/unit/tools tests/unit/units tests/unit/validation_cases tests/unit/test_docs_dependencies.py tests/unit/test_hmp_regression_cli.py tests/unit/test_pytest_timing_distribution.py -q
```

Resultat :

- `1446` passes, `11` skips
- `160.69 s` mur
- mediane par test : `0.003 s`
- `p99 = 1.83 s`
- max = `15.39 s`

Lecture :

- la suite `unit` n'est **pas globalement lente**
- le temps est concentre sur peu de tests
- la bonne strategie est donc **de mieux marquer les outliers**, pas de refondre toute la suite

Top tests lents observes :

| Test | Duree |
| --- | ---: |
| `tests/unit/geographic/test_reference_river_network_nancon_case.py::test_run_reference_river_network_nancon_case` | `15.39 s` |
| `tests/unit/data_managers/water_quality/test_loaders_api_wq_integration.py::test_piezometer_quality_real_api` | `12.42 s` |
| `tests/unit/geographic/test_run_geographic_case_golden.py::test_run_geographic_case_metrics_golden` | `8.98 s` |
| `tests/unit/solver/utils/mesh/gmsh_grid/test_comparison_cartesian_vs_gmsh_2d_case.py::test_comparison_cartesian_vs_gmsh_2d_non_regression` | `6.06 s` |

Top modules par temps cumule :

| Module | Tests | Total |
| --- | ---: | ---: |
| `tests/unit/tools/test_doc_gallery_extensions.py` | `21` | `16.10 s` |
| `tests/unit/geographic/test_reference_river_network_nancon_case.py` | `1` | `15.39 s` |
| `tests/unit/data_managers/water_quality/test_loaders_api_wq_integration.py` | `2` | `13.22 s` |
| `tests/unit/geographic/test_run_geographic_case_golden.py` | `1` | `8.98 s` |
| `tests/unit/solver/utils/mesh/gmsh_grid/test_reference_2d_geology_conformal_case.py` | `32` | `8.20 s` |
| `tests/unit/display/test_suites.py` | `9` | `8.06 s` |

### 2. Validation analytique stationnaire

Commande mesuree :

```powershell
python -m pytest tests/validation/analytical/steady -q
```

Resultat :

- `51` passes, `2` skips
- `334.39 s`
- moyenne par test : `6.42 s`
- mediane : `7.18 s`

Lecture :

- ce bloc est **homogenement couteux**
- le probleme n'est pas un unique outlier
- si on veut un `daily` court, il faut **selectionner moins de cas**, pas seulement optimiser un test

Modules les plus couteux :

| Module | Tests | Total |
| --- | ---: | ---: |
| `test_boussinesq_divide_fixed_head_piecewise_k_1d.py` | `4` | `29.73 s` |
| `test_boussinesq_sloping_substratum_uniform_recharge_1d.py` | `4` | `28.88 s` |
| `test_boussinesq_uniform_recharge_piecewise_k_1d.py` | `4` | `26.26 s` |
| `test_linearized_unconfined_hillslope_drainage_1d.py` | `3` | `24.87 s` |
| `test_boussinesq_fixed_head_piecewise_k_1d.py` | `4` | `24.43 s` |

### 3. Validation analytique transitoire

Commande mesuree :

```powershell
python -m pytest tests/validation/analytical/transient -q
```

Resultat :

- `25` passes
- `188.47 s`
- moyenne par test : `7.37 s`
- max = `45.64 s`

Lecture :

- ici il y a **un vrai outlier**
- le cas `late_time_unconfined_pumping_2d` cote `boussinesq` ecrase la distribution

Top modules par temps cumule :

| Module | Tests | Total |
| --- | ---: | ---: |
| `test_late_time_unconfined_pumping_2d.py` | `3` | `68.29 s` |
| `test_brutsaert_recession_linearized_deep_1d.py` | `3` | `19.04 s` |
| `test_brutsaert_recession_boussinesq_thin_1d.py` | `3` | `18.01 s` |
| `test_linearized_unconfined_recharge_periodic_1d.py` | `3` | `17.78 s` |

Top tests lents observes :

| Test | Duree |
| --- | ---: |
| `late_time_unconfined_pumping_2d[boussinesq]` | `45.64 s` |
| `late_time_unconfined_pumping_2d[modflow6]` | `14.74 s` |
| `linearized_unconfined_recharge_periodic_1d[modflow6]` | `8.85 s` |

## 4. Regression

### Fast

Commande mesuree :

```powershell
python -m pytest tests/regression/fast -q
```

Resultat :

- `4` passes
- `42.83 s`

Details :

| Test | Duree |
| --- | ---: |
| `fast_mf6` | `14.90 s` |
| `fast_nwt` | `13.45 s` |
| `fast_boussinesq` | `5.72 s` |
| `fast_boussinesq_divide` | `5.54 s` |

### Extensive

Commande mesuree :

```powershell
python -m pytest tests/regression/extensive -q
```

Resultat :

- `4` tests lances
- `223.59 s`
- `2` passes, `2` fails

Les echecs observes ne sont pas des echecs de temps :

- `test_launcher_data_overview_data_only_regression`
  - echec environnement/stack graphique
  - `ultraplot` absent puis `matplotlib` refuse `hspace`
- `test_launcher_simulation_extensive_nwt_regression`
  - echec decoding `utf-8` sur sortie sous-processus NWT

Temps observes malgre tout :

| Test | Duree |
| --- | ---: |
| `test_launcher_simulation_extensive_mf6_regression` | `143.80 s` |
| `test_run_geographic_case_regression_suite` | `47.89 s` |
| `test_launcher_data_overview_data_only_regression` | `18.51 s` |
| `test_launcher_simulation_extensive_nwt_regression` | `8.80 s` |

## Actions retenues

### Deja appliquees dans ce tour

1. **Support `unit --fast` / `unit --slow` dans `hmp test`**
   - `hmp test unit --fast` lance `-m "not slow and not integration"`
   - `hmp test unit --slow` lance `-m "slow or integration"`

2. **Marquage explicite des tests unitaires qui doivent plutot vivre en nightly**
   - API reelle Hub'Eau : `integration + slow`
   - galerie documentaire et calibration gallery : `slow`

3. **Dedoublement du plus gros outlier de validation transitoire**
   - `late_time_unconfined_pumping_2d`
   - `modflownwt` + `modflow6` passent en `fast`
   - `boussinesq` reste en `slow`

### Proposition de decoupage daily / nightly

#### Daily cible

```powershell
hmp test unit --fast
hmp test regression --fast
hmp test validation --fast
```

Lecture :

- `unit --fast` retire les API reelles, les grosses generations de galerie et les unitaires geografiques deja marques `slow`
- `regression --fast` reste a `~43 s`
- `validation --fast` gagne maintenant le sous-cas `late_time_unconfined_pumping_2d` pour `modflownwt` et `modflow6` sans trainer le `boussinesq` a `45 s`

#### Nightly cible

```powershell
hmp test unit --slow
hmp test regression --extensive
hmp test validation --slow
```

Ajouter ensuite, une fois la collecte reparée :

```powershell
python -m pytest tests/validation/calibration -q
python -m pytest tests/validation/numerical -q
```

## Reductions de temps encore possibles

1. **Reparer la collecte `launchers.*`**
   - gain principal : arreter de payer `~42 s` de collecte globale avec `23` erreurs
   - prerequis pour reintegrer calibration et numerique dans un vrai profil nightly stable

2. **Reduire le cout d'import de `hydromodpy`**
   - `~9.37 s` pour un simple import est trop haut
   - cela penalise directement les tests CLI, la collecte et les sous-processus
   - un allegerissement des imports en racine ferait gagner du temps partout

3. **Scinder davantage la validation analytique stationnaire**
   - aujourd'hui le bloc `steady` est regulierement entre `5` et `9 s` par execution
   - si un `daily` doit rester tres court, il faut un sous-ensemble smoke dedie
   - bon candidat : `1` cas par famille physique + `1` solveur de reference

4. **Sortir les tests API reelles du chemin standard**
   - ils sont deja `integration`
   - le marquage `slow` permet maintenant de les enlever naturellement du daily
   - si besoin, on peut aller plus loin et leur reserver un job reseau dedie

5. **Traiter la regression extensive comme strict nightly**
   - `~224 s` pour `4` tests seulement
   - `1` test MF6 a lui seul vaut `~144 s`
   - ce bloc ne doit pas polluer un feedback de PR rapide

## Conclusion operationnelle

Le depot a deja presque toute la taxonomie necessaire (`fast`, `slow`, `extensive`, `integration`).
Le vrai manque etait surtout :

- un meilleur marquage de quelques unitaires tres couteux,
- un decoupage plus fin du plus gros outlier transitoire,
- un moyen simple d'executer `unit` en mode rapide ou lent.

Apres ces changements, le premier decoupage raisonnable est :

- `daily` = `unit --fast` + `regression --fast` + `validation --fast`
- `nightly` = `unit --slow` + `regression --extensive` + `validation --slow`

Le prochain vrai chantier n'est plus le marquage, mais la **reparation de la collecte `launchers.*`** et l'**allegement de l'import racine**.
