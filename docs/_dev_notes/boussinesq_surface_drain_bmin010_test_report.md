# Rapport des tests Boussinesq `b_min = 0.10 m` avec drainage de surface explicite

Date: 2026-05-15

Statut: investigation numerique ciblee. Le comportement par defaut du solveur
n'est pas modifie. Les tests explorent une fermeture de surface plus proche du
DRN MODFLOW 6: pas d'obstacle superieur dur, mais un drainage explicite
`q_drain = C max(h - z_top, 0)`, combine avec une epaisseur saturee effective
minimale `b_min = 0.10 m`.

## Resume executif

La fermeture `b_min = 0.10 m + drainage de surface explicite` est la piste la
plus robuste observee jusqu'ici sur les cas stationnaires naturels testes.

Le resultat le plus fort est le suivant: avec une conductance tres faible
`C = 1e-4 m2/s`, le VI stationnaire direct converge sur tous les cas testes et
le court probe transitoire avec le meme modele regularise converge aussi.

Mais cette robustesse a un cout: `C = 1e-4 m2/s` laisse parfois des charges tres
au-dessus de la surface, avec des maxima de l'ordre de `50-60 m` sur `site_02`.
Cette variante doit donc etre lue comme une regularisation numerique robuste, pas
comme une fermeture de surface hydrologiquement neutre.

Pour `site_02_k_base` et `site_02_network`, des conductances beaucoup plus
fortes passent aussi (`1e-3`, `1e-2`, `1e-1 m2/s`) et reduisent fortement le
depassement de surface. Pour `site_02_k_high`, ces conductances fortes echouent
encore: le seul chemin robuste teste est faible, `C = 1e-4` en VI direct ou
`C = 2e-4` via `TSPSEUDO -> VI`.

Conclusion operationnelle: il existe une strategie qui passe systematiquement
sur l'echantillon teste, mais elle n'est pas encore une strategie physique
systematique. La strategie la plus defensive est:

1. `b_min = 0.10 m`;
2. fermeture de surface DRN-like, sans obstacle superieur dur;
3. essai VI direct;
4. secours `TSPSEUDO -> VI`;
5. balayage de conductance documente, car le comportement n'est pas monotone.

## Fermeture testee

La fermeture testee differe de l'obstacle superieur strict:

| composant | obstacle strict | fermeture DRN-like testee |
|---|---|---|
| borne basse | `h >= z_bottom` | conservee |
| borne haute | `h <= z_top` si drainage nul | relachee si `C > 0` |
| sortie surface | obstacle/complementarite | `q_drain = C max(h - z_top, 0)` |
| transmissivite | `K clip(h-z_bottom, 0, H)` | `K max(physical_thickness, 0.10 m)` |

Cette fermeture est plus proche de MODFLOW 6 DRN parce que l'exces de charge au
dessus de la surface est evacue par une conductance, au lieu d'etre interdit par
une contrainte dure.

## Methodes testees

Les methodes ajoutees au script de matrice sont experimentales:

- `surface_drain_0p0001_bmin_floor_0p10_vi`;
- `surface_drain_0p0002_bmin_floor_0p10_vi`;
- `surface_drain_0p0005_bmin_floor_0p10_vi`;
- `surface_drain_0p001_bmin_floor_0p10_vi`;
- `surface_drain_0p01_bmin_floor_0p10_vi`;
- `surface_drain_0p1_bmin_floor_0p10_vi`;
- variantes `..._tspseudo_then_vi`;
- `surface_drain_continuation_bmin_floor_0p10_to_0p1_vi`.

Chaque succes est controle par:

- convergence stationnaire;
- residu stationnaire du meme modele regularise;
- probe transitoire court avec le meme `b_min` et la meme conductance.

## Screening `C = 1e-4 m2/s`

| cas | statut | residu | probe transitoire | max `h-z_top` m | p95 `h-z_top` m | lecture |
|---|---:|---:|---:|---:|---:|---|
| `site_01_k_low / drain_0` | OK | `3.29e-8` | OK | `9.55` | `4.17` | robuste, surface tres relachee |
| `site_01_k_base / drain_0` | OK | `2.13e-7` | OK | `12.27` | `5.29` | robuste, surface tres relachee |
| `site_01_k_base uniform rivers / drain_0` | OK | `8.64e-11` | OK | `14.22` | `10.49` | robuste numeriquement, fort depassement |
| `site_01_k_high / drain_0` | OK | `2.05e-7` | OK | `10.95` | `7.12` | robuste |
| `site_02_k_low / drain_0` | OK | `1.73e-7` | OK | `39.09` | `1.99` | robuste, max local eleve |
| `site_02_k_base / drain_0` | OK | `7.93e-8` | OK | `53.49` | `2.38` | robuste, max local eleve |
| `site_02_k_high / drain_0` | OK | `5.16e-8` | OK | `59.04` | `3.83` | robuste, mais tres relache |
| `site_02_network` | OK | `3.88e-8` | OK | `53.49` | `2.36` | robuste |

Cette table est la meilleure evidence de robustesse numerique. Elle montre aussi
la limite principale: la conductance est suffisamment faible pour permettre des
depassements de surface importants. Ces depassements peuvent etre acceptables
comme regularisation d'initialisation, mais ils doivent etre quantifies avant une
promotion en modele de production.

## Conductances plus fortes

### `site_02_k_base`

| conductance `C` | methode | statut | residu | max `h-z_top` m | p95 `h-z_top` m | probe |
|---:|---|---:|---:|---:|---:|---:|
| `1e-4` | VI direct | OK | `7.93e-8` | `53.49` | `2.38` | OK |
| `5e-4` | VI direct | OK | `2.72e-9` | `36.09` | `0.47` | OK |
| `1e-3` | VI direct | OK | `6.30e-9` | `26.52` | `0.22` | OK |
| `1e-2` | VI direct | OK | `1.35e-7` | `6.30` | `0.00` | OK |
| `1e-1` | VI direct | OK | `4.46e-9` | `0.65` | `0.00` | OK |

`site_02_k_base` est le meilleur cas pour la fermeture DRN-like. Une conductance
forte proche d'une fermeture MODFLOW 6 de drainage passe et limite fortement les
depassements de surface.

### `site_02_network`

| conductance `C` | methode | statut | residu | max `h-z_top` m | p95 `h-z_top` m | probe |
|---:|---|---:|---:|---:|---:|---:|
| `1e-4` | VI direct | OK | `3.88e-8` | `53.49` | `2.36` | OK |
| `2e-4` | VI direct | OK | `7.83e-8` | `46.63` | `1.21` | OK |
| `1e-3` | VI direct | OK | `4.46e-8` | `26.52` | `0.22` | OK |
| `1e-2` | VI direct | OK | `2.43e-7` | `5.40` | `0.00` | OK |
| `1e-1` | VI direct | OK | `7.52e-9` | `0.61` | `0.00` | OK |

Ce cas etait difficile avec les formulations precedentes. La fermeture DRN-like
le rend robuste sur toute la plage testee.

### `site_02_k_high`

| conductance `C` | methode | statut | residu | max `h-z_top` m | p95 `h-z_top` m | probe |
|---:|---|---:|---:|---:|---:|---:|
| `1e-4` | VI direct | OK | `5.16e-8` | `59.04` | `3.83` | OK |
| `1e-4` | `TSPSEUDO -> VI` | OK | `3.80e-9` | `59.05` | `3.84` | OK |
| `2e-4` | VI direct | echec | `2.68e-3` | `13.92` | `0.00` | echec |
| `2e-4` | `TSPSEUDO -> VI` | OK | `4.00e-9` | `54.65` | `1.92` | OK |
| `5e-4` | VI direct | echec | `6.86e-3` | `13.92` | `0.00` | echec |
| `5e-4` | `TSPSEUDO -> VI` | echec | `6.86e-3` | `13.92` | `0.00` | echec |
| `1e-3` | VI direct | echec | `1.38e-2` | `13.92` | `0.00` | echec |
| `1e-2` | VI direct | echec | `1.39e-1` | `13.92` | `0.00` | echec |
| `1e-1` | VI direct | echec | `1.39` | `13.92` | `0.00` | echec |

`site_02_k_high` reste le verrou. La fermeture DRN-like aide, mais seulement si
la conductance reste tres faible ou si `TSPSEUDO -> VI` est utilise a `2e-4`.
Les conductances plus fortes retombent dans un mauvais bassin quasi sec avec
environ `12885` cellules actives au fond.

## Continuation de conductance

La continuation simple:

```text
C = 1e-4, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2, 1e-1
```

n'est pas une solution generale.

| cas | dernier stade atteint | residu | lecture |
|---|---:|---:|---|
| `site_01_k_high` | echec a `5e-3` | `1.65e-4` | proche mais non converge |
| `site_02_k_base` | echec a `2e-4` | `2.68e-3` | echec de chemin, alors que `5e-4` direct converge |
| `site_02_k_high` | echec a `5e-4` | `3.84e-5` | proche, mais pas assez robuste |

Le point important est que le comportement n'est pas monotone. Par exemple,
`site_02_k_base` echoue sur la continuation a `2e-4`, mais converge directement
a `5e-4`, `1e-3`, `1e-2` et `1e-1`. Le probleme est donc autant un probleme de
bassin numerique qu'un probleme de valeur physique de conductance.

## Comparaison des champs converges

Quand VI direct et `TSPSEUDO -> VI` convergent pour le meme cas et la meme
conductance, les champs de charge sont tres proches:

| cas | conductance | RMSE entre chemins | p95 abs | max abs |
|---|---:|---:|---:|---:|
| `site_01_k_high` | `5e-4` | `6.4e-5 m` | `9.8e-5 m` | `1.6e-3 m` |
| `site_01_k_high` | `1e-3` | `1.1e-5 m` | `1.6e-6 m` | `3.0e-4 m` |
| `site_02_k_base` | `5e-4` | `4.1e-6 m` | `2.7e-7 m` | `3.6e-4 m` |
| `site_02_k_base` | `1e-3` | `9.8e-7 m` | `9.4e-8 m` | `4.4e-5 m` |
| `site_02_k_high` | `1e-4` | `2.1e-2 m` | `1.6e-2 m` | `1.18 m` |

Cela indique que, quand les solveurs atteignent le meme bassin, le chemin
numerique ne change presque pas le champ utile. Les differences importantes
apparaissent surtout lorsque l'un des chemins tombe dans le mauvais bassin sec.

## Interpretation

La fermeture DRN-like ameliore la situation pour une raison simple: elle supprime
le choc numerique de l'obstacle superieur dur. Au lieu d'imposer `h <= z_top`, le
solveur peut depasser la surface et evacuer l'exces via une loi lineaire. Cette
loi donne a Newton une pente continue dans une zone qui etait auparavant dominee
par un changement brutal d'ensemble actif.

Le verrou restant est `site_02_k_high`. A forte conductance, le solveur revient
vers un etat quasi sec non admissible: beaucoup de cellules au fond, residu fort
et probe transitoire en echec. Ce n'est pas un equilibre sec physique; c'est un
mauvais bassin numerique.

## Recommandation

La strategie la plus robuste observee est:

```text
b_min = 0.10 m
surface drainage DRN-like
C initial = 1e-4 m2/s
VI direct
if needed: TSPSEUDO -> VI
```

Pour une production hydrologiquement plus defendable, il faut toutefois chercher
la plus grande conductance qui converge avec des depassements de surface
acceptables. Sur les cas testes:

- `site_02_k_base` et `site_02_network`: `C = 1e-2` ou `1e-1 m2/s` sont
  nettement meilleurs que `1e-4`;
- `site_02_k_high`: `C = 1e-4` ou `2e-4` avec `TSPSEUDO -> VI` restent les seuls
  chemins robustes observes.

Il ne faut donc pas promouvoir une conductance unique forte comme solution
systematique. La piste a promouvoir est plutot un algorithme de robustesse:

1. essayer une conductance cible forte;
2. si echec, descendre la conductance;
3. accepter explicitement que la fermeture devient plus regularisante;
4. reporter les depassements de surface et les flux de drainage.

## Commandes executees

Screening initial `site_02`:

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_02_k_base__bouss_tri_irregular_drain_00 --case site_02_k_high__bouss_tri_irregular_drain_00 --case site_02_network__bouss_unstructured_same_mesh --method surface_drain_0p001_bmin_floor_0p10_vi --method surface_drain_0p01_bmin_floor_0p10_vi --method surface_drain_0p1_bmin_floor_0p10_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_probe --probe-dt-days 30"
```

Screening robuste `C = 1e-4`:

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_01_k_low__bouss_tri_irregular_drain_00 --case site_01_k_base__bouss_tri_irregular_drain_00 --case site_01_k_base__bouss_tri_uniform_rivers_drain_00 --case site_01_k_high__bouss_tri_irregular_drain_00 --case site_02_k_low__bouss_tri_irregular_drain_00 --case site_02_k_base__bouss_tri_irregular_drain_00 --case site_02_k_high__bouss_tri_irregular_drain_00 --case site_02_network__bouss_unstructured_same_mesh --method surface_drain_0p0001_bmin_floor_0p10_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_c0001_screening --probe-dt-days 30"
```

Tests de seuil `site_02_k_high`:

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_02_k_high__bouss_tri_irregular_drain_00 --method surface_drain_0p0001_bmin_floor_0p10_vi --method surface_drain_0p001_bmin_floor_0p10_tspseudo_then_vi --method surface_drain_0p0001_bmin_floor_0p10_tspseudo_then_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_probe_site02_high_extra --probe-dt-days 30"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_02_k_high__bouss_tri_irregular_drain_00 --method surface_drain_0p0002_bmin_floor_0p10_vi --method surface_drain_0p0005_bmin_floor_0p10_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_probe_site02_high_threshold --probe-dt-days 30"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_02_k_high__bouss_tri_irregular_drain_00 --method surface_drain_0p0002_bmin_floor_0p10_tspseudo_then_vi --method surface_drain_0p0005_bmin_floor_0p10_tspseudo_then_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_probe_site02_high_threshold_tspseudo --probe-dt-days 30"
```

Continuation:

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --case site_02_k_base__bouss_tri_irregular_drain_00 --case site_02_k_high__bouss_tri_irregular_drain_00 --method surface_drain_continuation_bmin_floor_0p10_to_0p1_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_continuation --probe-dt-days 30"
```

## Artefacts

- `docs/_dev_notes/boussinesq_surface_drain_bmin010_test_report.md`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_summary.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_probe/`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_c0001_screening/`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_probe_site02_high_extra/`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_probe_site02_high_threshold/`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_probe_site02_high_threshold_tspseudo/`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_c0002_screening/`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_c0002_tspseudo_recovery/`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_continuation/`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_surface_drain_bmin010_threshold_completion/`.
