# Inventaire des cas Boussinesq en echec a conserver

Date: 2026-05-14

Statut: inventaire operationnel issu des artefacts locaux presents dans le depot. Le but est de figer les cas Boussinesq qui buggent actuellement pour en faire une base de tests de robustesse. Les cas ci-dessous ne doivent pas etre supprimes ou "nettoyes" sans etre remplaces par un test equivalent.

## Sources

- Rapport de synthese: `docs/_dev_notes/boussinesq_modflow_natural_method_discrepancy_report.md`.
- Matrice drainage/K/maillage: `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/`.
- Sensibilites PETSc VI: `examples/projects/10_testbed_workflow/outputs/boussinesq_petsc_vi_regression_testbed/sensitivity_runs/`.
- Configs sources: `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/`.

## Echecs numeriques principaux

Ces cas echouent cote Boussinesq et constituent la base prioritaire de regression. Le motif dominant est une non-convergence du solveur non lineaire sur l'initialisation stationnaire, avant les periodes transitoires: `flow_regime = steady`, `runtime_problem_kind = steady_head_balance`, `SNES_DIVERGED_LINE_SEARCH`, `total_periods = 0`.

| Campagne | Cas | Simulation Boussinesq | K | Drainage / maillage | Motif | Residu inf. |
|---|---|---|---|---|---|---:|
| drainage/K/mesh | `site_01_k_high` | `bouss_tri_irregular_drain_00` | `2e-4 m/s` | drain `0`, tri contraint | `SNES_DIVERGED_LINE_SEARCH` | `1.12e-3` |
| drainage/K/mesh | `site_01_k_high` | `bouss_tri_irregular_drain_01` | `2e-4 m/s` | drain `0.1`, tri contraint | `SNES_DIVERGED_LINE_SEARCH` | `1.65e-4` |
| drainage/K/mesh | `site_01_k_high` | `bouss_tri_uniform_rivers_drain_01` | `2e-4 m/s` | drain `0.1`, tri quasi uniforme rivieres | `SNES_DIVERGED_LINE_SEARCH` | `2.98e-4` |
| drainage/K/mesh | `site_02_k_low` | `bouss_tri_irregular_drain_00` | `1e-5 m/s` | drain `0`, tri contraint | `SNES_DIVERGED_LINE_SEARCH` | `1.87` |
| drainage/K/mesh | `site_02_k_low` | `bouss_tri_irregular_drain_01` | `1e-5 m/s` | drain `0.1`, tri contraint | `SNES_DIVERGED_LINE_SEARCH` | `1.39` |
| drainage/K/mesh | `site_02_k_base` | `bouss_tri_irregular_drain_00` | `5e-5 m/s` | drain `0`, tri contraint | `SNES_DIVERGED_LINE_SEARCH` | `9.28` |
| drainage/K/mesh | `site_02_k_base` | `bouss_tri_irregular_drain_001` | `5e-5 m/s` | drain `0.01`, tri contraint | `SNES_DIVERGED_LINE_SEARCH` | `1.39e-1` |
| drainage/K/mesh | `site_02_k_base` | `bouss_tri_irregular_drain_01` | `5e-5 m/s` | drain `0.1`, tri contraint | `SNES_DIVERGED_LINE_SEARCH` | `1.39` |
| drainage/K/mesh | `site_02_k_high` | `bouss_tri_irregular_drain_00` | `2e-4 m/s` | drain `0`, tri contraint | `SNES_DIVERGED_LINE_SEARCH` | `33.7` |
| drainage/K/mesh | `site_02_k_high` | `bouss_tri_irregular_drain_001` | `2e-4 m/s` | drain `0.01`, tri contraint | `SNES_DIVERGED_LINE_SEARCH` | `1.39e-1` |
| drainage/K/mesh | `site_02_k_high` | `bouss_tri_irregular_drain_01` | `2e-4 m/s` | drain `0.1`, tri contraint | `SNES_DIVERGED_LINE_SEARCH` | `1.39` |
| drainage/K/mesh | `site_02_k_high` | `bouss_tri_uniform_rivers_drain_01` | `2e-4 m/s` | drain `0.1`, tri quasi uniforme rivieres | `SNES_DIVERGED_LINE_SEARCH` | `1.30` |
| PETSc VI sensibilite | `site_01_k10_natural_10km2_mf6_bouss_petsc_vi` | `bouss_candidate` | K multiplie par 10 | PETSc `vi_obstacle`, tri contraint | `SNES_DIVERGED_LINE_SEARCH` | `1.65e-4` |
| PETSc VI sensibilite | `site_01_k10_regularized_petsc_natural_10km2_mf6_bouss` | `bouss_candidate` | K multiplie par 10 | PETSc `regularized_partition`, tri contraint | `SNES_DIVERGED_MAX_IT` en transitoire | `1.57e-5` |

## Cas d'infrastructure a isoler

| Campagne | Cas | Simulation | Statut | Lecture |
|---|---|---|---|---|
| drainage/K/mesh | `site_01_k_low` | `bouss_tri_irregular_drain_00` | `failed` | Echec DuckDB: verrou concurrent sur `outputs/nwt_small_catchment_flux/data_cache/cache.duckdb`. A garder comme trace de campagne, mais ce n'est pas un bug numerique Boussinesq tant qu'il n'est pas reproduit avec un catalogue propre. |

## Cas voisins convergents a garder comme temoins

Ces cas sont utiles pour verifier qu'un correctif de robustesse ne casse pas les zones deja robustes.

| Campagne | Cas | Simulation | RMSE charge finale | Max abs | Lecture |
|---|---|---|---:|---:|---|
| drainage/K/mesh | `site_01_k_low` | `bouss_tri_irregular_drain_01` | `0.66 m` | `3.61 m` | Temoin faible K, meme maillage contraint, drain `0.1`. |
| drainage/K/mesh | `site_01_k_base` | `bouss_tri_irregular_drain_00` | `0.54 m` | `6.22 m` | Temoin nominal, drain `0`. |
| drainage/K/mesh | `site_01_k_base` | `bouss_tri_irregular_drain_001` | `0.60 m` | `6.22 m` | Temoin nominal, drain `0.01`. |
| drainage/K/mesh | `site_01_k_base` | `bouss_tri_irregular_drain_01` | `0.55 m` | `6.22 m` | Temoin nominal, drain `0.1`. |
| drainage/K/mesh | `site_01_k_high` | `bouss_tri_irregular_drain_001` | `3.43 m` | `13.62 m` | Cas proche de l'echec: K fort mais drain intermediaire convergent. |
| drainage/K/mesh | `site_02_k_low` | `bouss_tri_irregular_drain_001` | `2.45 m` | `28.51 m` | Site 02 difficile, drain intermediaire convergent. |

## Artefacts et commandes de rejeu

Matrice drainage/K/maillage:

```bash
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_natural_drainage_k_mesh_matrix_chain.py \
  --cases site_01_k_high site_02_k_low site_02_k_base site_02_k_high
```

Reutilisation des runs existants pour reconstruire les comparaisons:

```bash
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_natural_drainage_k_mesh_matrix_chain.py \
  --cases site_01_k_high site_02_k_low site_02_k_base site_02_k_high \
  --reuse-runs
```

Sensibilites PETSc VI:

```bash
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_natural_petsc_vi_regression_chain.py \
  --sites site_01
```

Configs generees a conserver:

- `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/_generated_configs/`
- `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/comparisons/*/_generated_configs/`
- `examples/projects/10_testbed_workflow/outputs/boussinesq_petsc_vi_regression_testbed/sensitivity_runs/*/_generated_configs/`

Diagnostics de solveur a conserver:

- `*/workspaces/<simulation>/.solver_scratch/flow_main__boussinesq/_boussinesq_summary.json`
- `*/workspaces/<simulation>/.solver_scratch/flow_main__boussinesq/vi_obstacle_runtime_summary.json`
- `*/workspaces/<simulation>/.solver_scratch/flow_main__boussinesq/vi_obstacle_period_diagnostics.csv`
- `*/workspaces/<simulation>/.solver_scratch/flow_main__boussinesq/vi_obstacle_substep_diagnostics.csv`

## Tests versionnes existants

Les tests deja versionnes couvrent surtout des cas analytiques et quelques cas PETSc Linux. Ils ne couvrent pas encore directement la matrice naturelle ci-dessus comme tests de regression attendus-en-echec.

Collecte cible realisee depuis Windows avec `python -m pytest -o addopts='' --collect-only -q ...`:

- `tests/regression/extensive/intercomparison/test_boussinesq_natural_transient_intercomparison_extensive.py::test_natural_mesh_transient_pulse_mf6_boussinesq_intercomparison_regression`
- `tests/regression/fast/intercomparison/test_solver_intercomparison_fast_regression.py::test_dupuit_irregular_mesh_mf6_boussinesq_intercomparison_regression`
- `tests/validation/numerical/steady/test_boussinesq_headwater_100km2_petsc.py`
- `tests/validation/numerical/transient/test_boussinesq_headwater_100km2_petsc_transient.py`
- `tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py`
- `tests/validation/numerical/transient/test_boussinesq_drying_petsc.py`

Une collecte globale `-m boussinesq` echoue dans l'environnement Windows courant avant la fin a cause de dependances optionnelles manquantes (`xugrid`, `pandera`) et de l'option pytest `--dist=loadgroup` si `pytest-xdist` n'est pas installe.

## Proposition de base de tests

1. Transformer les 12 echecs stationnaires `SNES_DIVERGED_LINE_SEARCH` de la matrice en tests de regression Linux/WSL marques `petsc`, d'abord en `xfail(strict=True)` avec verification du motif et du residu.
2. Ajouter un test distinct pour `site_01_k10_regularized_petsc`, car l'echec est transitoire (`SNES_DIVERGED_MAX_IT`) et ne releve pas du meme mecanisme.
3. Garder au moins trois temoins convergents: `site_01_k_base / drain 0.01`, `site_01_k_high / drain 0.01`, `site_02_k_low / drain 0.01`.
4. Exclure provisoirement `site_01_k_low / drain 0` des tests numeriques tant que l'echec DuckDB n'a pas ete reproduit avec un cache propre.
