# Rapport de test: champ MODFLOW 6 comme condition initiale Boussinesq

Date: 2026-05-15

Statut: investigation ciblée. Le comportement par défaut de HydroModPy n'est
pas modifié. Le test ajoute seulement des méthodes explicites dans le script
d'investigation stationnaire.

## Résumé exécutif

Utiliser un champ MODFLOW 6 comme condition initiale Boussinesq n'est pas une
stratégie systématiquement robuste dans l'état actuel.

Le champ MF6 peut être utile comme warm start transitoire sur plusieurs cas:

- `site_01_k_high / drain_0`, `drain_0.01`, `drain_0.1`;
- `site_02_k_low / drain_0`, `drain_0.01`.

Mais il ne récupère pas les cas critiques:

- `site_02_k_base / drain_0`;
- `site_02_k_base / drain_0.01`;
- `site_02_k_base / drain_0.1`;
- `site_02_k_high / drain_0`;
- `site_02_network`.

Le solveur VI Boussinesq final depuis le champ MF6 retombe souvent dans le même
mauvais bassin quasi sec, avec beaucoup de cellules sur l'obstacle inférieur et
un résidu élevé. La stratégie peut donc aider à démarrer un transitoire dans
certains cas, mais elle ne fournit pas encore une initialisation stationnaire
Boussinesq fiable.

Point important: les runs existants ne conservent pas clairement le champ MF6
permanent auxiliaire comme artefact exploitable. Les tests ci-dessous utilisent
donc le dernier champ de charge MF6 stocké dans le Zarr de référence quand
`_steady_state_initial_conditions.npz` n'est pas présent. Une relance MF6
`site_01_k_high` a bien exécuté l'initialisation stationnaire auxiliaire, mais
l'artefact permanent n'est pas resté disponible dans le workspace final.

## Méthodes testées

Deux méthodes explicites ont été ajoutées au script:

| méthode | rôle |
|---|---|
| `mf6_warm_bmin_floor_0p10` | projette le champ MF6 sur le maillage Boussinesq, clippe aux bornes, puis teste directement un probe transitoire Boussinesq avec `b_min=0.10 m` |
| `mf6_warm_bmin_floor_0p10_then_vi` | utilise le même champ MF6 comme guess initial, puis lance un solve VI stationnaire Boussinesq avec `b_min=0.10 m` |

Les cellules MF6 non finies sont remplacées par `z_bottom` avant clipping. Quand
le nombre de cellules diffère, le champ est projeté par plus proche centroïde.

## Résultats

| cas | MF6 warm seul: transitoire `b_min` | MF6 warm -> VI | résidu VI final | lecture |
|---|---:|---:|---:|---|
| `site_01_k_high / drain_0` | oui | oui | `4.70e-7` | utile, mais pas meilleur que `b_min` direct |
| `site_01_k_high / drain_0.1` | oui | non | `1.65e-4` | le warm start démarre le transitoire mais ne donne pas le stationnaire |
| `site_01_k_high / drain_0.01` | oui | non | `1.65e-4` | le VI final est dégradé par ce chemin |
| `site_02_k_low / drain_0` | oui | non | `1.87` | le warm start démarre, mais le VI final tombe dans le mauvais bassin |
| `site_02_k_low / drain_0.01` | oui | non | `0.139` | probe transitoire OK, stationnaire non atteint |
| `site_02_k_base / drain_0` | non | non | `9.32` | échec massif inchangé |
| `site_02_k_base / drain_0.01` | non | non | `0.139` | échec stationnaire et probe modèle non robuste |
| `site_02_k_base / drain_0.1` | non | non | `1.39` | échec malgré champ MF6 proche conceptuellement |
| `site_02_k_high / drain_0` | non | non | `36.7` | échec massif |
| `site_02_network` | non | non | `9.32` | moins bon que le chemin `b_min=0.10 + TSPSEUDO -> VI` précédemment réussi |

## Interprétation

Le champ MF6 n'est pas une solution Boussinesq. Les différences de formulation
restent importantes:

- MF6 utilise DISV/NPF/STO/DRN et XT3D sur les maillages non structurés;
- les cas Boussinesq testés ici utilisent parfois `drain_0`, alors que le champ
  MF6 disponible vient souvent de `mf6_tri_irregular_drain_01`;
- les cellules sèches ou inactives MF6 doivent être interprétées avant injection
  dans Boussinesq;
- plusieurs cas `site_02` nécessitent une projection spatiale par centroïde, pas
  un transfert cellule à cellule exact.

La conclusion numérique est donc claire: le champ MF6 peut être un bon champ
initial au sens "pas transitoire possible" sur certains cas, mais il ne corrige
pas le problème d'ensemble actif du solveur stationnaire Boussinesq. Quand le VI
final échoue, il échoue avec la signature connue: résidu fort, recherche
linéaire ou itérations maximales, et grand nombre de cellules au fond.

## Réponse à la question

Prendre MODFLOW 6 en permanent comme condition initiale pourrait être utile comme
outil opérationnel de warm start, mais les tests actuels ne soutiennent pas
l'idée que cela fonctionne systématiquement.

Pour en faire une vraie piste de production, il faudrait d'abord:

1. persister explicitement le champ MF6 stationnaire auxiliaire dans le workspace
   ou le Zarr, au lieu de dépendre du dernier champ transitoire stocké;
2. définir une projection documentée MF6 -> Boussinesq, avec traitement des
   cellules sèches;
3. tester séparément "démarrage transitoire direct" et "contrôle stationnaire
   Boussinesq final";
4. conserver `b_min=0.10 m` et les diagnostics d'échec, car le warm start seul ne
   suffit pas sur `site_02_base/high`.

## Commandes exécutées

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method mf6_warm_bmin_floor_0p10 --method mf6_warm_bmin_floor_0p10_then_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_mf6_warm_start_probe_site01 --probe-dt-days 30"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --case site_01_k_high__bouss_tri_irregular_drain_01 --case site_01_k_high__bouss_tri_irregular_drain_001 --case site_02_k_low__bouss_tri_irregular_drain_00 --case site_02_k_low__bouss_tri_irregular_drain_001 --case site_02_k_base__bouss_tri_irregular_drain_00 --case site_02_k_base__bouss_tri_irregular_drain_001 --case site_02_k_base__bouss_tri_irregular_drain_01 --case site_02_k_high__bouss_tri_irregular_drain_00 --case site_02_network__bouss_unstructured_same_mesh --method mf6_warm_bmin_floor_0p10 --method mf6_warm_bmin_floor_0p10_then_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_mf6_warm_start_probe --probe-dt-days 30"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_02_k_high__bouss_tri_irregular_drain_00 --method mf6_warm_bmin_floor_0p10 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_mf6_warm_start_probe_site02_high_warm_only --probe-dt-days 30"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_best_candidate_matrix.py --case site_02_k_high__bouss_tri_irregular_drain_00 --method mf6_warm_bmin_floor_0p10_then_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_mf6_warm_start_probe_site02_high_then_vi --probe-dt-days 30"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m hydromodpy run examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/comparisons/site_01_k_high_natural_drainage_k_mesh_matrix/_generated_configs/mf6_tri_irregular_drain_01.toml"
```

## Artefacts

- `docs/_dev_notes/diagnostics/boussinesq_stationary_mf6_warm_start_probe/`
- `docs/_dev_notes/diagnostics/boussinesq_stationary_mf6_warm_start_probe_site01/`
- `docs/_dev_notes/diagnostics/boussinesq_stationary_mf6_warm_start_probe_site02_high_warm_only/`
- `docs/_dev_notes/diagnostics/boussinesq_stationary_mf6_warm_start_probe_site02_high_then_vi/`
- `docs/_dev_notes/boussinesq_mf6_warm_start_initial_condition_probe.md`
