# Inventaire des tests d'intercomparaison

Date: `2026-04-14`

## Perimetre retenu

Dans ce depot, j'appelle **test d'intercomparaison** un test ou un script qui compare
plusieurs solveurs, backends ou methodes sur un meme cas.

Je separe volontairement :

- les **intercomparaisons scientifiques automatisees**,
- la **couverture unitaire de soutien** autour de ces scenarios,
- les **tests de l'infrastructure generique d'intercomparaison**,
- les **benchmarks d'intercomparaison en calibration**,
- les **scripts d'intercomparaison non ou peu testes**.

## 1. Intercomparaisons scientifiques automatisees

Ce sont les cas les plus proches d'un "vrai" inventaire de tests d'intercomparaison
au sens scientifique.

### 1.1 Comparaisons PETSc/Boussinesq sur cas numeriques

| Fichier | Nature | Portee |
| --- | --- | --- |
| `tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py` | `1` test parametre, `4` executions | Compare `petsc_partition` et `petsc` sur le cas numerique transitoire d'overflow de versant, avec variantes de forcage (`strong`, `alternating`). |
| `tests/validation/numerical/steady/test_boussinesq_headwater_100km2_petsc.py` | `1` test parametre, `2` executions | Compare les deux fermetures de surface PETSc (`regularized_partition` vs `complementarity`) sur un bassin reel `headwater_100km2` en regime stationnaire. |
| `tests/validation/numerical/transient/test_boussinesq_headwater_100km2_petsc_transient.py` | `3` tests, dont `1` parametre | Compare les deux fermetures PETSc sur cas reel transitoire, puis verifie qu'elles se distinguent bien sur des forcages `cycling recharge`, homogenes et heterogenes. |

### 1.2 Resume

- `3` fichiers de validation numerique d'intercomparaison
- `5` fonctions de test
- `10` executions pytest effectives en tenant compte des parametrisations
- contraintes d'environnement :
  - Linux uniquement pour les cas PETSc,
  - `petsc4py` requis,
  - plusieurs tests sont marques `slow`

## 2. Couverture unitaire de soutien des scenarios d'intercomparaison

Ces tests ne valident pas le phenomene physique bout en bout, mais securisent les
outils et les cas utilises par les intercomparaisons.

| Fichier | Nombre de tests | Role principal |
| --- | ---: | --- |
| `tests/unit/validation/test_hillslope_pulse_overflow_case.py` | `10` | Contrat du cas `boussinesq_hillslope_recharge_pulse_overflow_1d` : presets, diagnostics, selection de snapshots, gestion du solveur de comparaison. |
| `tests/unit/validation_cases/test_boussinesq_hillslope_overflow_multi_solver.py` | `5` | Contrat du runner multi-solveur `run_multi_solver_case.py` : normalisation des solveurs, exports CSV, presets de contexte. |
| `tests/unit/tools/test_investigate_surface_interaction_hillslope_transient.py` | `8` | Contrat du script d'investigation transitoire multi-solveur avec drainage de surface. |
| `tests/unit/tools/test_investigate_linux_nwt_boussinesq_transient.py` | `2` | Contrat du benchmark Linux `MODFLOW-NWT` vs variantes `Boussinesq`. |
| `tests/unit/tools/test_investigate_sloping_substratum_transient.py` | `3` | Contrat geometrique du cas transitoire a substratum incline. |

Resume :

- `5` fichiers
- `28` tests unitaires de soutien

## 3. Infrastructure generique d'intercomparaison

Le depot contient un moteur generique dedie aux comparaisons solveur/maillage :
`launchers/method_comparison`.

### 3.1 Tests principaux

| Fichier | Nombre de tests | Role principal |
| --- | ---: | --- |
| `tests/unit/launchers/test_method_comparison_launcher.py` | `24` | Couvre la configuration, l'extraction d'observables, les sorties CSV/JSON/Markdown, les figures, les flux d'exutoire, les cartes, le mode reuse, les metriques et le dispatch CLI `launchers method-comparison`. |

### 3.2 Tests satellites

| Fichier | Nombre de tests relies | Role principal |
| --- | ---: | --- |
| `tests/unit/launchers/test_hmp_simulation_cli.py` | `1` | Verifie le dispatch `hmp compare` vers `MethodComparisonLauncher`. |
| `tests/unit/launchers/test_regional_lab_launcher.py` | `1` | Verifie l'extraction d'artefacts enfants produits par un `method_comparison`. |
| `tests/unit/launchers/test_realistic_campaign_runner.py` | `1` | Verifie le chargement de la config `run_method_comparison_headwater_100km2_outlet_2_mf6_transient_scenarios.toml`. |

### 3.3 Configurations d'exemple explicitement couvertes

Le test `test_example_method_comparison_configs_load` charge explicitement les
configurations suivantes :

- `run_method_comparison_mf6_vs_nwt_same_regular_mesh.toml`
- `run_method_comparison_mf6_vs_nwt_different_meshes.toml`
- `run_method_comparison_mf6_vs_nwt_different_meshes_demonstrative.toml`
- `run_method_comparison_example12_multi_method_moderate.toml`
- `run_method_comparison_example12_fast_shared_mesh.toml`
- `run_method_comparison_example12_extensive_mf6_vs_nwt.toml`
- `run_method_comparison_headwater_100km2_outlet_2_backends.toml`
- `run_method_comparison_headwater_100km2_outlet_2_transient_pulsed_recharge_backends.toml`
- `run_method_comparison_headwater_100km2_outlet_2_transient_cycling_recharge_heterogeneous_backends.toml`

Une dixieme configuration orientee campagne est testee a part :

- `run_method_comparison_headwater_100km2_outlet_2_mf6_transient_scenarios.toml`

Resume :

- `27` tests relies a l'infrastructure `method_comparison`
- couverture large de l'outillage, mais pas de validation scientifique bout en bout

## 4. Intercomparaisons de calibration

Ce ne sont pas des comparaisons de solveurs, mais des **intercomparaisons de
methodes d'inversion** sur un meme benchmark `same-solver twin`.

### 4.1 Tests de validation calibration

| Fichier | Regime | Nature |
| --- | --- | --- |
| `tests/validation/calibration/test_twin_dupuit_fixed_head_modflow6.py` | steady | benchmark de reference rapide sur `dupuit_fixed_head_1d` |
| `tests/validation/calibration/test_twin_dupuit_fixed_head_posterior_modflow6.py` | steady | benchmark oriente distribution/posterior |
| `tests/validation/calibration/test_twin_dupuit_fixed_head_mesh_perturbed_modflow6.py` | steady | benchmark avec verite et calibration sur maillages perturbes |
| `tests/validation/calibration/test_twin_dupuit_fixed_head_noisy_modflow6.py` | steady | benchmark bruite |
| `tests/validation/calibration/test_twin_linearized_recharge_step_modflow6.py` | transient | benchmark `K + Sy` multi-observable |
| `tests/validation/calibration/test_twin_linearized_recharge_step_noisy_modflow6.py` | transient | variante bruitee du benchmark transitoire |
| `tests/validation/calibration/test_twin_boussinesq_fixed_head_piecewise_k_modflow6.py` | steady | benchmark zone `piecewise K` |

Resume :

- `7` fichiers
- `7` tests de validation calibration
- objectif : comparer plusieurs methodes de calibration sur une meme verite
  synthetique, pas plusieurs solveurs

### 4.2 Support documentation

Le rendu de la page documentaire d'intercomparaison calibration est couvert par :

- `tests/unit/tools/test_doc_gallery_calibration_cases.py`
  - test cle : `test_build_calibration_intercomparison_page_renders_rows`

## 5. Scripts et workflows d'intercomparaison non ou peu testes

Ces scripts existent clairement comme outils d'intercomparaison, mais ils ne
sont pas couverts par des tests bout en bout dedies.

| Script | Type |
| --- | --- |
| `tools/validation_compare_simple_cases.py` | rapport solveur-a-solveur sur cas analytiques simples (`MODFLOW-NWT`, `MODFLOW 6`, `Boussinesq`) |
| `tools/validation_compare_transient_simple_cases.py` | rapport solveur-a-solveur sur cas analytiques transitoires simples |
| `tools/investigate_surface_interaction_hillslope_transient.py` | investigation transitoire multi-solveur avec drainage de surface |
| `tools/investigate_linux_nwt_boussinesq_transient.py` | benchmark Linux `MODFLOW-NWT` vs `Boussinesq` local/PETSc |
| `tools/investigate_sloping_substratum_transient.py` | intercomparaison transitoire sur substratum incline |
| `validation_cases/numerical/transient/boussinesq_hillslope_recharge_pulse_overflow_1d/run_multi_solver_case.py` | runner multi-solveur dedie au cas d'overflow de versant |

Observation :

- plusieurs de ces scripts ont des tests unitaires sur leurs briques internes,
  mais pas de campagne pytest bout en bout qui execute la comparaison complete ;
- en pratique, le dossier `out/` montre qu'ils ont deja ete lances manuellement
  ou en smoke test.

## 6. Artefacts d'intercomparaison deja presents dans `out/`

Examples visibles au moment de l'inventaire :

- `out/linux_nwt_bouss_4m4m6m_20260414`
- `out/sih_sloping_substratum_10deg_20260414`
- `out/boussinesq_hillslope_overflow_multi_linux_windows_context_20260414`
- `out/vscs_20260412`
- `out/vtcs_20260412`

Ces dossiers confirment que le depot contient non seulement les tests et
scripts, mais aussi des executions recentes d'intercomparaison.

## 7. Conclusion operationnelle

Si on retient le **perimetre strict** des tests d'intercomparaison scientifiques
automatises, l'inventaire actuel est :

- `3` fichiers de validation numerique
- `5` fonctions de test
- `10` executions parametrisees

Si on retient le **perimetre large** incluant l'outillage, la calibration et la
couverture unitaire associee, l'ecosysteme d'intercomparaison couvre :

- `3` fichiers de validation numerique d'intercomparaison
- `5` fichiers unitaires de soutien scientifique
- `4` fichiers de tests relies au launcher `method_comparison`
- `7` fichiers de validation calibration
- plusieurs scripts d'intercomparaison hors pytest bout en bout

Point d'attention principal :

- le depot dispose d'une bonne base d'outillage d'intercomparaison,
  mais les workflows `tools/validation_compare_*` et `tools/investigate_*`
  restent surtout des scripts operatoires ou exploratoires plutot que des tests
  automatises end-to-end.
