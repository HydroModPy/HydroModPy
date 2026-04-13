# Profiling calibration 2026-04-13

Profiling cible sur le cas:

- `calibration_twin_linearized_recharge_step_modflow6`
- solveur: `modflow6`
- régime: transitoire
- paramètres calibrés: `K_global_factor`, `Sy_global`

Méthodes profilées:

- `simplex`
- `da_mh_gp`

Artefacts bruts:

- `reporting/calibration_profiling_2026-04-13/transient_k_sy__simplex.prof`
- `reporting/calibration_profiling_2026-04-13/transient_k_sy__simplex_pstats.txt`
- `reporting/calibration_profiling_2026-04-13/transient_k_sy__simplex_summary.json`
- `reporting/calibration_profiling_2026-04-13/transient_k_sy__da_mh_gp.prof`
- `reporting/calibration_profiling_2026-04-13/transient_k_sy__da_mh_gp_pstats.txt`
- `reporting/calibration_profiling_2026-04-13/transient_k_sy__da_mh_gp_summary.json`

## Conclusion directe

Le temps de calibration part principalement dans trois zones:

1. l'ecriture du modele MF6 via FloPy (`write_simulation`)
2. la selection/canonicalisation des sorties calibration
3. seulement ensuite l'execution effective de `mf6.exe`

Autrement dit, le bucket actuel `simulation_time_seconds` est trop large si on veut comprendre ou part le temps. Il melange:

- `pre_processing`
- `write_simulation`
- `run_simulation`
- `post_processing`

et masque le fait que l'ecriture des fichiers solveur coute plus cher que l'execution du solveur lui-meme sur ce cas.

## Resultats `simplex`

Resume haut niveau:

- temps total calibration: `112.65 s`
- preparation de session initiale: `0.96 s`
- runtime candidat estime: `111.51 s`
- overhead algorithmique hors candidats: `1.14 s`
- evaluations: `23`

Temps moyen par candidat:

- total candidat: `4.85 s`
- actualisation parametres: `0.009 s`
- preparation launcher: `0.045 s`
- patch runtime: `0.001 s`
- simulation: `3.37 s`
- selection sorties: `1.43 s`
- construction objectif: `0.0001 s`
- calcul objectif: `0.0011 s`

Hotspots fonctions, temps cumule:

- `launchers/process_simulation/launcher.py:325(run_prepared)` -> `81.15 s`
- `hydromodpy/simulation/adapters/flow/modflow_common.py:131(run_flow_model)` -> `80.96 s`
- `hydromodpy/solver/modflow6/modflow6.py:1483(processing)` -> `64.86 s`
- `flopy/mf6/mfsimbase.py:1697(write_simulation)` -> `50.89 s`
- `launchers/model_calibration/output_selection.py:744(select_candidate_outputs_from_selectors)` -> `34.11 s`
- `launchers/model_calibration/output_selection.py:267(_coordinates_from_solver_mesh)` -> `32.25 s`
- `hydromodpy/solver/modflow_common/solver_mesh.py:112(cell_centroids)` -> `32.18 s`
- `flopy/mf6/mfsimbase.py:1803(run_simulation)` -> `13.97 s`
- `hydromodpy/solver/modflow6/modflow6.py:1270(pre_processing)` -> `8.09 s`
- `hydromodpy/solver/modflow6/modflow6.py:2242(post_processing)` -> `6.42 s`

Lecture:

- `write_simulation`: environ `45%` du temps total calibration
- `output_selection` + canonicalisation: environ `30%`
- `run_simulation` / `run_model`: environ `12%`
- le reste est partage entre `pre_processing`, `post_processing` et overhead marginal

## Resultats `da_mh_gp`

Resume haut niveau:

- temps total calibration: `130.90 s`
- preparation de session initiale: `0.81 s`
- runtime candidat estime: `129.80 s`
- overhead algorithmique hors candidats: `1.09 s`
- evaluations: `26`

Temps moyen par candidat:

- total candidat: `4.99 s`
- actualisation parametres: `0.009 s`
- preparation launcher: `0.031 s`
- patch runtime: `0.001 s`
- simulation: `3.42 s`
- selection sorties: `1.54 s`
- construction objectif: `0.0002 s`
- calcul objectif: `0.0009 s`

Hotspots fonctions, temps cumule:

- `launchers/process_simulation/launcher.py:325(run_prepared)` -> `92.32 s`
- `hydromodpy/simulation/adapters/flow/modflow_common.py:131(run_flow_model)` -> `92.10 s`
- `hydromodpy/solver/modflow6/modflow6.py:1483(processing)` -> `72.71 s`
- `flopy/mf6/mfsimbase.py:1697(write_simulation)` -> `57.80 s`
- `launchers/model_calibration/output_selection.py:744(select_candidate_outputs_from_selectors)` -> `41.46 s`
- `launchers/model_calibration/output_selection.py:267(_coordinates_from_solver_mesh)` -> `39.17 s`
- `hydromodpy/solver/modflow_common/solver_mesh.py:112(cell_centroids)` -> `39.09 s`
- `flopy/mf6/mfsimbase.py:1803(run_simulation)` -> `14.91 s`
- `hydromodpy/solver/modflow6/modflow6.py:1270(pre_processing)` -> `9.33 s`
- `hydromodpy/solver/modflow6/modflow6.py:2242(post_processing)` -> `8.18 s`

Lecture:

- `write_simulation`: environ `44%` du temps total calibration
- `output_selection` + canonicalisation: environ `32%`
- `run_simulation` / `run_model`: environ `11%`
- overhead statistique `da_mh_gp`: faible sur ce cas, autour de `1.1 s` total

## Reponse a la question "ou est passe le temps de simulation ?"

Le temps est surtout passe ici:

1. `flopy.mf6.mfsimbase.write_simulation`
2. `launchers.model_calibration.output_selection.canonicalize_run_outputs`
3. `hydromodpy.solver.modflow_common.solver_mesh.cell_centroids`
4. `flopy.mf6.mfsimbase.run_simulation`

Donc:

- ce n'est pas principalement `mf6.exe`
- ce n'est pas non plus la methode de calibration elle-meme
- le cout majeur est Python/FloPy autour du solveur et la reconstruction des sorties

## Interpretation technique

### 1. Le bucket `simulation_time_seconds` est trop agrege

Il inclut actuellement tout `launcher.run_prepared()`:

- `pre_processing`
- `write_simulation`
- `run_simulation`
- `post_processing`

Pour ce cas, `write_simulation` coute nettement plus que `run_simulation`.

### 2. Le bucket `output_selection_time_seconds` cache un tres gros cout geometrique

La majeure partie de `output_selection` part dans:

- `_coordinates_from_solver_mesh`
- `solver_mesh.cell_centroids`

Ce n'est donc pas vraiment le calcul de l'objectif qui coute, mais la reconstruction repetee des coordonnees/cellules pour extraire les observables.

### 3. L'overhead de la methode statistique n'est pas le vrai probleme ici

Sur `da_mh_gp`, l'overhead algorithmique hors runtime candidat est autour de `1 s` au total. Le goulot n'est donc pas la MCMC elle-meme sur ce cas, mais toujours le cout des runs candidats et de leur lecture.

## Priorites d'optimisation

1. Eclater `simulation_time_seconds` en sous-phases explicites:
   - `solver_pre_processing`
   - `solver_write_input`
   - `solver_external_run`
   - `solver_post_processing`
2. Factoriser/cache les coordonnees cellules et le mapping de selection dans `output_selection`
3. Eviter autant que possible la reecriture complete FloPy/MF6 a chaque candidat

## Chemins utiles

Profilage brut:

- `reporting/calibration_profiling_2026-04-13/`

Benchmarks produits pendant ce profilage:

- `C:\\results\\HydromodPy\\validation\\validation_calibration_twin\\ct_6157bfb793_1137340e`
- `C:\\results\\HydromodPy\\validation\\validation_calibration_twin\\ct_6157bfb793_2844ba3f`
