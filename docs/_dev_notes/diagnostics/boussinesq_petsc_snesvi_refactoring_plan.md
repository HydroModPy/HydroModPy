# Plan de refactoring Boussinesq vers PETSc SNESVI seul

Date : 2026-05-11

## 1. Conclusion courte

Oui, garder uniquement le schema PETSc SNESVI sous WSL simplifierait
nettement le code Boussinesq.

La simplification la plus forte n'est pas seulement "PETSc au lieu de SciPy".
Elle vient du choix plus strict suivant :

- backend unique : PETSc sous Linux/WSL ;
- formulation unique : head-only obstacle ;
- solveur non lineaire unique : PETSc SNESVI ;
- fermeture de surface unique : obstacle direct `z_bottom <= h <= z_top`,
  avec reconstruction des reactions de surface et de fond apres convergence.

Avec cette cible, une grande partie du code actuel devient soit supprimable,
soit reducible a des constantes. Le coeur a garder reste le maillage, la
resolution des forcages, l'assemblage physique de base, le driver
steady/transient, l'export d'etat et les diagnostics utiles.

Mise a jour d'implementation, 2026-05-12 : une premiere campagne preparatoire
PETSc direct `vi_obstacle` a ete ajoutee sans lancer le refactoring destructif.
Elle sert a verrouiller le comportement multi-bassins avant suppression des
anciens chemins Boussinesq.

## 2. Decision a confirmer avant execution

Il y a deux niveaux possibles.

| Niveau | Cible | Simplification | Risque |
| --- | --- | --- | --- |
| PETSc seul | garder `petsc_partition`, `petsc_mixed`, `petsc_vi_obstacle`, eventuellement `petsc_ts_vi_obstacle` | supprime les chemins `local`, `scipy`, `scipy_sparse`, mais conserve la taxonomie methodes/engines | faible a moyen |
| PETSc SNESVI seul | garder uniquement le runtime SNESVI obstacle, idealement `petsc_vi_obstacle.py` | supprime presque toute la selection backend/methode et la plupart des Jacobiennes alternatives | moyen, surtout pour les cas transitoires actuellement valides avec `ts_vi_obstacle` |

Le plan ci-dessous cible le second niveau : PETSc SNESVI seul.

Point important : `petsc_vi_obstacle.py` supporte steady et transient via
Backward Euler et substeps internes. `petsc_ts_vi_obstacle.py` supporte
seulement le transient via PETSc TS + SNESVI. Si l'objectif est un seul chemin
pour steady et transient, la cible naturelle est donc `petsc_vi_obstacle.py`.
Si l'on veut absolument conserver PETSc TS pour les transitoires, garder
`petsc_ts_vi_obstacle.py` comme option "phase 2 bis", mais la simplification
sera moins nette.

## 3. Inventaire actuel

Les axes de selection actuels sont :

- `flow.runtime_backend` dans `hydromodpy/physics/flow/flow_config.py` :
  `local`, `scipy`, `scipy_sparse`, `petsc` ;
- `flow.surface_interaction_model` :
  `auto`, `regularized_partition`, `complementarity`, `vi_obstacle`,
  `ts_vi_obstacle` ;
- `methods/catalog.py` :
  mappe les fermetures de surface vers des familles physiques ;
- `engines/catalog.py` :
  mappe les methodes vers les modules runtime ;
- `runtime_selection.py` :
  importe dynamiquement le module runtime final.

Cette architecture est propre pour comparer des methodes. Elle devient
surabstraite si une seule methode de production est conservee.

Ordres de grandeur du code Boussinesq actuellement concernes :

| Zone | Fichiers principaux | Lignes environ |
| --- | --- | ---: |
| runtimes non SNESVI ou alternatifs | `local.py`, `scipy_dense.py`, `scipy_sparse.py`, `petsc_partition.py`, `petsc_mixed.py`, helpers associes | 1900 a 2500 |
| PETSc TS VI optionnel | `petsc_ts_vi_obstacle.py`, `ts_vi_obstacle_diagnostics.py` | 950 |
| selection methodes/engines | `methods/catalog.py`, `engines/catalog.py`, `runtime_selection.py`, formulations multiples | 350 a 450 |
| Jacobiennes alternatives | `jacobian/fd.py`, `jacobian/partition_triplets.py`, fonctions dense/partition dans `semianalytic.py` | 400 a 550 |
| config et tests de variantes | `flow_config.py`, `flow_runtime_config.py`, tests et validation cases | variable |

Conclusion pratique : le refactoring peut retirer environ 3150 a 4230 lignes
physiques dans `hydromodpy/solver/boussinesq` par suppression directe, selon
que `petsc_ts_vi_obstacle.py` est conserve ou non. En lignes non vides et non
commentaires, cela correspond a environ 2785 a 3750 lignes. Une fois les
indirections et les tests de variantes contractes, la reduction fonctionnelle
attendue de la partie Boussinesq est plutot de l'ordre de 35 a 40 %.

Il ne faut pas promettre la suppression de SciPy comme dependance globale :
SciPy reste utilise ailleurs dans HydroModPy.

## 4. Ce qui doit rester

Ces couches restent utiles meme avec PETSc SNESVI seul :

- `hydromodpy/solver/boussinesq/mesh.py` :
  vue maillage solver, geometrie, connectivite, proprietes hydrauliques ;
- `hydromodpy/solver/boussinesq/flow_to_boussinesq_adapter.py` :
  pont entre Flow/Domain/maillage runtime et `BoussinesqMesh` ;
- `hydromodpy/solver/boussinesq/forcing/` et `forcing_resolution.py` :
  recharge, puits, Dirichlet, drainage, conditions initiales ;
- `hydromodpy/solver/boussinesq/drivers/steady.py` et `drivers/transient.py` :
  orchestration des periodes et construction des historiques ;
- `hydromodpy/solver/boussinesq/core/state.py`,
  `drivers/state.py`, `export_payload.py` :
  etat accepte, historiques, payload `_boussinesq_state_history.npz` ;
- `hydromodpy/solver/boussinesq/assembly/fluxes.py`,
  `assembly/inputs.py`, `assembly/residuals.py` :
  bilan volumes finis, flux internes, contraintes de charge prescrite,
  stockage, drainage ;
- `hydromodpy/solver/boussinesq/jacobian/operator_triplets.py`,
  `jacobian/common.py`, partie base de `jacobian/semianalytic.py` :
  Jacobienne sparse de base utilisee par SNESVI ;
- `hydromodpy/solver/boussinesq/runtimes/petsc_common.py`,
  `runtimes/execution_common.py`, `runtimes/vi_bounds.py`,
  `runtimes/petsc_vi_obstacle.py` :
  coeur PETSc SNESVI.

## 5. Ce qui devient supprimable avec PETSc SNESVI seul

### 5.1 Runtimes

Supprimer :

- `hydromodpy/solver/boussinesq/runtimes/local.py`
- `hydromodpy/solver/boussinesq/runtimes/scipy_dense.py`
- `hydromodpy/solver/boussinesq/runtimes/scipy_sparse.py`
- `hydromodpy/solver/boussinesq/runtimes/newton_common.py`
- `hydromodpy/solver/boussinesq/runtimes/head_only_common.py`
- `hydromodpy/solver/boussinesq/runtimes/partition_utils.py`
- `hydromodpy/solver/boussinesq/runtimes/petsc_partition.py`
- `hydromodpy/solver/boussinesq/runtimes/petsc_mixed.py`
- `hydromodpy/solver/boussinesq/runtimes/petsc_mixed_common.py`

Supprimer aussi, si la cible stricte exclut PETSc TS :

- `hydromodpy/solver/boussinesq/runtimes/petsc_ts_vi_obstacle.py`
- `hydromodpy/solver/boussinesq/runtimes/ts_vi_obstacle_diagnostics.py`

Garder :

- `petsc_vi_obstacle.py`
- `petsc_common.py`
- `execution_common.py`
- `vi_bounds.py`
- `vi_obstacle_diagnostics.py`

### 5.2 Methodes, engines et formulations

Remplacer la taxonomie par une cible fixe.

Supprimer ou reduire fortement :

- `hydromodpy/solver/boussinesq/methods/catalog.py`
- `hydromodpy/solver/boussinesq/engines/catalog.py`
- `hydromodpy/solver/boussinesq/runtime_selection.py`
- `hydromodpy/solver/boussinesq/formulations/head_only_regularized_partition.py`
- `hydromodpy/solver/boussinesq/formulations/mixed_complementarity.py`

Garder eventuellement une petite constante :

```python
BOUSSINESQ_RUNTIME_ENGINE_ID = "petsc_vi_obstacle_snes"
BOUSSINESQ_SURFACE_MODEL = "vi_obstacle"
BOUSSINESQ_FORMULATION = "head_only_vi_obstacle"
```

Cette constante peut vivre dans `solver_contract.py` ou un petit
`runtime_metadata.py`. Il n'y a plus besoin d'import dynamique.

### 5.3 Jacobiennes

Supprimer :

- `hydromodpy/solver/boussinesq/jacobian/fd.py`
- `hydromodpy/solver/boussinesq/jacobian/partition_triplets.py`

Simplifier :

- `hydromodpy/solver/boussinesq/jacobian/semianalytic.py` :
  ne garder que `build_sparse_semianalytic_base_jacobian_triplets`.
  Retirer :
  - `build_sparse_semianalytic_regularized_partition_jacobian_triplets`
  - `build_dense_semianalytic_regularized_partition_jacobian`
  - import de `partition_triplets`
  - import de `concatenate_triplets` si plus utilise.

### 5.4 Assemblage

Le runtime SNESVI appelle actuellement les assembleurs
`assemble_*_residual_with_saturation_excess` avec `q_ex = 0`, puis reconstruit
les reactions d'obstacle apres convergence.

Actions recommandees :

- garder une fonction explicite du type `assemble_steady_obstacle_residual`
  et `assemble_transient_obstacle_residual` ;
- faire de `saturation_excess_rate_m_s` une entree explicite, souvent zero ;
- supprimer la logique automatique de regularized partition dans
  `assembly/surface.py`, ou la conserver uniquement dans un module archive si
  l'on veut garder une reference numerique ;
- retirer les assembleurs sans `saturation_excess_rate_m_s` s'ils ne sont plus
  appeles ;
- garder `BoussinesqAssembly.saturation_excess_rate_m_s` et
  `dry_deficit_rate_m_s`, car ce sont les champs exportes apres reaction.

### 5.5 Configuration Flow

Dans `hydromodpy/physics/flow/flow_config.py` :

- rendre `runtime_backend` inutile pour Boussinesq, avec valeur canonique
  `petsc` ;
- rendre `surface_interaction_model` inutile, avec valeur canonique
  `vi_obstacle` ;
- supprimer les valeurs `local`, `scipy`, `scipy_sparse`,
  `regularized_partition`, `complementarity`, `ts_vi_obstacle` de la validation
  cible ;
- garder pendant une phase de migration un normaliseur qui accepte les anciens
  champs mais :
  - emet un warning ;
  - reecrit vers `petsc` et `vi_obstacle` ;
  - echoue si l'ancien champ demandait explicitement une methode qui ne doit
    plus etre supportee.

Dans `hydromodpy/physics/flow/flow_runtime_config.py` :

- supprimer `backend` et `surface_model`, ou les rendre informatifs ;
- garder :
  - `max_iterations`
  - `tol_residual_inf`
  - `tol_state_update_inf`
  - `vi_substeps_per_period`
  - `vi_substep_on_failure`
  - `vi_max_adaptive_substeps`
- supprimer les champs `ts_vi_*` si PETSc TS est retire.

### 5.6 Contrat solver

Dans `hydromodpy/solver/boussinesq/solver_contract.py` :

- remplacer `resolve_solver_contract` par une construction directe ;
- supprimer `runtime_backend_name`, `resolve_surface_interaction_model`,
  `resolve_runtime_backend` ;
- retirer le cas special `scipy_sparse` dans `build_runtime_options` ;
- centraliser `assert_supported_runtime_subset` pour eviter le doublon avec
  `Boussinesq._assert_supported_runtime_subset`.

Dans `hydromodpy/solver/boussinesq/boussinesq.py` :

- supprimer `_runtime_backend_name`, `_surface_interaction_model`,
  `_runtime_backend` ;
- supprimer `_assert_runtime_mesh_size_supported`, car le chemin dense disparait ;
- faire importer directement `petsc_vi_obstacle` via une petite facade runtime ;
- simplifier `post_processing` pour n'ecrire que les diagnostics VI conserves ;
- remplacer toute logique de surface model par la constante canonique.

### 5.7 Diagnostics, exports et comparaison

Garder les exports generiques Boussinesq :

- `_boussinesq_state_history.npz`
- `_boussinesq_summary.json`
- groupe Zarr `boussinesq_state`
- budgets et observables Boussinesq.

Simplifier les branches de diagnostics :

- garder `vi_obstacle_*` ;
- supprimer `ts_vi_obstacle_*` si PETSc TS est retire ;
- supprimer les libelles et chemins special-cases pour :
  - `regularized_partition`
  - `complementarity`
  - `petsc_partition`
  - `scipy_sparse`.

Fichiers a auditer :

- `hydromodpy/analysis/comparison/runtime.py`
- `hydromodpy/analysis/comparison/exports.py`
- `hydromodpy/analysis/comparison/output_pipeline.py`
- `hydromodpy/analysis/comparison/reporting.py`
- `hydromodpy/analysis/comparison/experiment_launcher.py`
- `hydromodpy/analysis/comparison/web/sections.py`
- `validation_cases/shared/boussinesq_plotting.py`

Compatibilite conseillee : les lecteurs peuvent continuer a lire les anciens
artefacts si les fichiers existent, mais les nouveaux runs ne doivent plus en
produire.

## 6. Plan par phases

### Phase 0 : figer la cible

Objectif : eviter de refactorer deux fois.

Decisions :

1. Cible unique : `petsc_vi_obstacle.py` pour steady et transient.
2. WSL/Linux obligatoire pour executer Boussinesq.
3. Les anciens backends ne sont plus des options de production.
4. Les anciens resultats restent lisibles si possible, mais pas regeneres.
5. Avant toute suppression, figer une suite de non-regression PETSc qui capture
   le comportement actuel des chemins utiles et des chemins a remplacer.

Sortie attendue :

- une note de decision courte ;
- un changelog interne indiquant la rupture de compatibilite.
- un rapport de baseline PETSc WSL avec les tests, versions PETSc/petsc4py,
  options PETSc et tolerances numeriques retenues.

### Phase 1 : ajouter le chemin canonique sans suppression massive

Objectif : rendre le chemin cible explicite avant de retirer l'ancien.

Taches :

1. Ajouter une facade runtime directe, par exemple
   `hydromodpy/solver/boussinesq/runtimes/petsc_snesvi.py`, qui reexporte
   `solve_steady_problem` et `solve_transient_step` depuis
   `petsc_vi_obstacle.py`.
2. Modifier `solver_contract.py` pour retourner toujours la cible canonique.
3. Modifier `runtime_summary.py` pour emettre des metadonnees fixes :
   `runtime_backend = "petsc"`,
   `runtime_engine_id = "petsc_vi_obstacle_snes"`,
   `surface_interaction_model_resolved = "vi_obstacle"`.
4. Conserver temporairement `runtime_selection.py`, mais ne plus l'appeler dans
   le driver.

Validation :

```bash
bash install/enter_wsl_dev.sh --headless -- python -m pytest \
  tests/unit/solver/test_boussinesq_method_catalog.py \
  tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py \
  -q
```

Le test de catalogue doit probablement etre adapte pour verifier la constante
canonique plutot que plusieurs routes.

### Phase 2 : contracter la configuration

Objectif : que les TOML n'aient plus a choisir le backend Boussinesq.

Taches :

1. Mettre `runtime_backend = "petsc"` comme valeur canonique interne.
2. Mettre `surface_interaction_model = "vi_obstacle"` comme valeur canonique
   interne.
3. Ajouter un warning de migration pour les anciens tokens.
4. Supprimer ou cacher les champs `ts_vi_*` si PETSc TS est retire.
5. Mettre a jour les schemas, exemples dynamiques et tests de TOML.

Fichiers :

- `hydromodpy/physics/flow/flow_config.py`
- `hydromodpy/physics/flow/flow_runtime_config.py`
- `tests/unit/config/test_toml_loader.py`
- `tests/unit/physics/test_flow_config_dirichlet.py`
- les TOML dans `examples/projects/10_testbed_workflow/`
- les TOML dans `examples/projects/11_nancon_network_physical_benchmark/`
- les `config_boussinesq.toml` sous `validation_cases/`

Validation :

```bash
python -m pytest tests/unit/config/test_toml_loader.py tests/unit/physics -q
```

Ces tests peuvent tourner hors WSL s'ils ne lancent pas PETSc.

### Phase 3 : supprimer les runtimes alternatifs

Objectif : retirer le volume de code principal.

Taches :

1. Supprimer les runtimes non SNESVI listes en section 5.1.
2. Supprimer les imports devenus orphelins.
3. Supprimer les variantes de tests qui parametrent `petsc_partition`,
   `petsc`, `scipy_sparse`, `boussinesq` local.
4. Adapter `tools/ci/run_boussinesq_petsc_smoke.sh` pour ne tester que
   SNESVI.
5. Supprimer ou redefinir `tools/ci/run_boussinesq_linux_smoke.sh`.

Validation WSL :

```bash
bash install/enter_wsl_dev.sh --headless -- bash tools/ci/run_boussinesq_petsc_smoke.sh
```

### Phase 4 : simplifier methodes, engines et selection

Objectif : retirer la taxonomie devenue inutile.

Taches :

1. Remplacer les tests de catalogue par des tests de contrat canonique.
2. Supprimer `methods/catalog.py` et `engines/catalog.py`, ou les reduire a une
   constante si cela limite le nombre d'edits.
3. Supprimer `runtime_selection.py` si plus aucun import ne l'utilise.
4. Supprimer les formulations `regularized_partition` et
   `mixed_complementarity`.
5. Mettre a jour `hydromodpy/solver/boussinesq/README.md`.

Commande de garde :

```bash
rg -n "resolve_runtime_backend|resolve_engine_spec|resolve_method_spec|regularized_partition|mixed_complementarity|scipy_sparse|petsc_partition" hydromodpy tests validation_cases examples
```

La commande doit ne retourner que de la documentation historique ou des tests
de migration volontairement conserves.

### Phase 5 : simplifier Jacobiennes et assemblage

Objectif : ne garder que la Jacobienne sparse de base SNESVI.

Taches :

1. Supprimer `jacobian/fd.py`.
2. Supprimer `jacobian/partition_triplets.py`.
3. Reduire `jacobian/semianalytic.py` a
   `build_sparse_semianalytic_base_jacobian_triplets`.
4. Renommer les assembleurs utilises par SNESVI pour clarifier leur role :
   `assemble_steady_obstacle_residual`,
   `assemble_transient_obstacle_residual`.
5. Retirer la surface regularisee automatique de l'assemblage actif.
6. Garder les champs exportes `saturation_excess_rate_m_s` et
   `dry_deficit_rate_m_s`.

Tests unitaires a conserver ou creer :

- flux interne sur mini maillage ;
- contrainte Dirichlet par cellule ;
- bornes VI `z_bottom`, `z_top` ;
- reaction de surface et reaction de fond reconstruites ;
- Jacobienne sparse PETSc : structure CSR non vide et indices valides.

Ces tests d'assemblage doivent rester executables sans PETSc quand ils ne
creent pas de SNES.

### Phase 6 : remettre a plat les validations

Objectif : une matrice de validation plus petite mais plus solide.

Conserver comme smoke WSL minimal :

1. Dupuit fixed head steady, SNESVI.
2. Hillslope interception steady, SNESVI.
3. Linearized recharge step transient, SNESVI.
4. Linearized boundary step transient, SNESVI.
5. Headwater 100 km2 transient, SNESVI.
6. Un cas de sechage et rehumectation testant l'obstacle bas.

Adapter ou supprimer :

- `tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py`
  doit perdre les parametres `petsc_partition` et `petsc_complementarity`.
- `tests/validation/numerical/transient/test_boussinesq_drying_petsc.py`
  doit tester `petsc_vi_obstacle` au lieu d'importer `petsc_mixed`.
- `tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py`
  doit tester le seul solver canonique.
- `tests/validation/numerical/steady/test_boussinesq_headwater_100km2_petsc.py`
  doit perdre la comparaison partition/complementarity.
- `tests/validation/numerical/transient/test_boussinesq_headwater_100km2_petsc_transient.py`
  doit comparer des metriques de run, pas des variantes PETSc.
- `validation_cases/numerical/transient/boussinesq_hillslope_recharge_pulse_overflow_1d/`
  doit remplacer les labels `petsc_partition`, `petsc`, `scipy_sparse` par un
  solver canonique.

### Phase 7 : nettoyer les exemples et docs

Objectif : l'utilisateur ne voie plus d'options mortes.

Taches :

1. Mettre a jour les TOML pour supprimer les champs optionnels ou les fixer a
   la cible canonique pendant la transition.
2. Mettre a jour :
   - `hydromodpy/solver/boussinesq/README.md`
   - `docs/_dev_notes/diagnostics/boussinesq_linux_ci.md`
   - `docs/_dev_notes/diagnostics/boussinesq_petsc_vs_marcais_2017.md`
   - les README de validation cases.
3. Ajouter une section "Boussinesq requires WSL/Linux + PETSc" dans les docs
   d'installation si elle n'est pas deja assez visible.
4. Remplacer les textes UI/reporting qui parlent de comparaison entre
   complementarity, partition et TS VI.

### Phase 8 : suppression finale et garde anti-regression

Objectif : eviter qu'un ancien chemin revienne par accident.

Ajouter des tests de garde :

- aucun import vers `scipy_dense`, `scipy_sparse`, `local`, `petsc_partition`,
  `petsc_mixed` ;
- aucun TOML d'exemple ne declare `surface_interaction_model` hors
  `vi_obstacle` ;
- les nouveaux summaries Boussinesq contiennent toujours :
  - `runtime_backend = "petsc"`
  - `runtime_engine_id = "petsc_vi_obstacle_snes"`
  - `surface_interaction_model_resolved = "vi_obstacle"`.

Commandes :

```bash
rg -n "scipy_sparse|scipy_dense|runtime_backend = \"local\"|petsc_partition|petsc_mixed|complementarity|regularized_partition|ts_vi_obstacle" hydromodpy tests validation_cases examples
```

Les seules occurrences acceptees doivent etre :

- notes historiques ;
- warnings de migration ;
- tests qui verifient explicitement le rejet ou la normalisation d'anciens
  tokens.

## 7. Risques techniques

1. Les tests Windows perdront un solveur Boussinesq executable localement.
   Mitigation : conserver des tests d'assemblage purs Python et marquer tout
   lancement solveur Boussinesq en `pytest.mark.petsc`.
2. Les cas transitoires recents semblent souvent valides avec
   `ts_vi_obstacle`. Si `petsc_ts_vi_obstacle.py` est supprime, il faut d'abord
   prouver que `petsc_vi_obstacle.py` avec substeps couvre ces cas.
3. Les anciens rapports de comparaison peuvent contenir des diagnostics
   `ts_vi_obstacle_*` ou des libelles `petsc_partition`. Les lecteurs doivent
   rester tolerants pendant une phase de migration.
4. Les options PETSc deviennent le seul levier de robustesse. Il faudra donc
   documenter clairement les tolerances, substeps et reglages SNES/KSP.
5. Le nom public `boussinesq` doit rester stable. On peut retirer les variantes
   internes sans changer `solver.solver_engine = "boussinesq"`.

## 8. Ordre recommande

1. Prouver que `petsc_vi_obstacle.py` passe les cas transitoires que l'on veut
   garder.
2. Faire la contraction de contrat sans supprimer les anciens fichiers.
3. Adapter les tests et le smoke WSL.
4. Supprimer les runtimes alternatifs.
5. Supprimer methodes/engines.
6. Simplifier Jacobiennes/assemblage.
7. Nettoyer docs, exemples, rapports.

Cet ordre limite les gros diffs difficiles a deboguer. Le point bloquant est
le premier : si le transient SNESVI direct ne remplace pas proprement TS VI,
il vaut mieux garder provisoirement deux runtimes SNESVI (`vi_obstacle` steady
et `ts_vi_obstacle` transient) puis refaire une seconde passe plus tard.

## 9. Chiffrage detaille de la reduction

Les chiffres ci-dessous mesurent uniquement le package
`hydromodpy/solver/boussinesq` au moment de l'analyse. Ils ne comptent pas les
tests, les exemples, les notes de diagnostic, ni les cas de validation.

| Mesure | Total actuel | Suppression directe si TS VI conserve | Part | Suppression directe si SNESVI direct seul | Part |
| --- | ---: | ---: | ---: | ---: | ---: |
| Lignes physiques Python | 13089 | 3159 | 24.1 % | 4229 | 32.3 % |
| Lignes non vides et non commentaires | 11572 | 2786 | 24.1 % | 3751 | 32.4 % |

Interpretation :

- minimum credible si l'on garde `petsc_ts_vi_obstacle.py` pour les
  transitoires : environ 24 % du package Boussinesq solver ;
- cible stricte "un seul runtime SNESVI direct" : environ 32 % de suppression
  immediate dans le package solver ;
- cible apres simplification des contrats, tests et diagnostics restants :
  environ 35 a 40 % de reduction fonctionnelle de la partie Boussinesq ;
- il est possible que le gain depasse 40 % si les anciens rapports, les
  comparaisons multi-methodes et les TOML historiques sont migres sans couche
  de compatibilite longue duree.

### 9.1 Detail des suppressions directes

| Famille supprimable | Fichiers inclus | Lignes physiques |
| --- | --- | ---: |
| Runtimes locaux/SciPy et helpers Newton | `local.py`, `scipy_dense.py`, `scipy_sparse.py`, `newton_common.py`, `head_only_common.py` | 1015 |
| PETSc regularized partition | `petsc_partition.py`, `partition_utils.py`, `jacobian/partition_triplets.py`, `formulations/head_only_regularized_partition.py` | 498 |
| PETSc mixed complementarity | `petsc_mixed.py`, `petsc_mixed_common.py`, `formulations/mixed_complementarity.py` | 880 |
| PETSc TS VI optionnel | `petsc_ts_vi_obstacle.py`, `ts_vi_obstacle_diagnostics.py` | 1070 |
| Catalogues de selection | `runtime_selection.py`, `methods/catalog.py`, `engines/catalog.py` | 464 |
| Jacobienne differences finies | `jacobian/fd.py` | 302 |
| Total strict | toutes les lignes ci-dessus | 4229 |

Le gain "TS VI conserve" retire tout sauf la ligne PETSc TS VI optionnel :
`4229 - 1070 = 3159` lignes physiques.

### 9.2 Repartition actuelle du package Boussinesq

Cette repartition explique pourquoi le gain se concentre dans les runtimes.

| Dossier | Fichiers | Lignes physiques |
| --- | ---: | ---: |
| `runtimes` | 17 | 5057 |
| racine `boussinesq` | 14 | 2911 |
| `assembly` | 8 | 1190 |
| `jacobian` | 6 | 1052 |
| `forcing` | 7 | 946 |
| `drivers` | 5 | 747 |
| `extractors` | 2 | 343 |
| `methods` | 2 | 181 |
| `adapters` | 2 | 153 |
| `engines` | 2 | 148 |
| `formulations` | 5 | 143 |
| `core` | 2 | 115 |
| `discretization` | 3 | 103 |

Les dossiers `assembly`, `forcing`, `drivers`, `core`, `extractors` et
`discretization` doivent rester en grande partie. Ils representent la physique,
les donnees et les sorties, pas les variantes numeriques.

## 10. Cartographie des dependances a nettoyer

La suppression des variantes ne touche pas seulement
`hydromodpy/solver/boussinesq`. Plusieurs couches exposent encore les choix
historiques.

### 10.1 Configuration Flow

Fichiers principaux :

- `hydromodpy/physics/flow/flow_config.py`
- `hydromodpy/physics/flow/flow_runtime_config.py`

Etat actuel :

- `runtime_backend` accepte `local`, `scipy`, `scipy_sparse`, `petsc` ;
- `surface_interaction_model` accepte `auto`, `regularized_partition`,
  `complementarity`, `vi_obstacle`, `ts_vi_obstacle` ;
- les validateurs normalisent et documentent ces choix.

Cible :

- garder `solver_engine = "boussinesq"` comme API stable ;
- rendre `runtime_backend` inutile pour Boussinesq, ou le garder seulement
  comme champ de compatibilite cache/deprecie ;
- rendre `surface_interaction_model` inutile, ou limiter temporairement a
  `auto` et `vi_obstacle` ;
- emettre un warning de migration si un ancien TOML declare `local`, `scipy`,
  `scipy_sparse`, `regularized_partition`, `complementarity` ou
  `ts_vi_obstacle`.

Decision de compatibilite recommandee :

1. Phase courte : accepter les anciens tokens et les mapper vers PETSc SNESVI
   avec warning explicite.
2. Phase stricte : refuser les anciens tokens avec message d'erreur clair.
3. Phase finale : retirer les champs des templates et de la documentation
   utilisateur.

### 10.2 Selection runtime/methode/engine

Fichiers principaux :

- `hydromodpy/solver/boussinesq/runtime_selection.py`
- `hydromodpy/solver/boussinesq/methods/catalog.py`
- `hydromodpy/solver/boussinesq/engines/catalog.py`

Etat actuel :

- le code resout d'abord une methode physique ;
- puis il resout un moteur numerique ;
- puis il importe dynamiquement le module runtime.

Cible :

- remplacer cette chaine par une resolution directe vers
  `runtimes/petsc_vi_obstacle.py` ;
- conserver une petite structure de metadata runtime uniquement si les exports
  et les rapports en ont besoin ;
- supprimer les catalogues des que les tests de migration passent.

Option transitoire :

- garder `resolve_runtime_backend(...)`, mais le transformer en adaptateur
  mince qui ignore les anciens choix apres validation/migration ;
- retourner toujours :
  - `name = "petsc"`
  - `engine_id = "petsc_vi_obstacle_snes"`
  - `runtime_formulation = "head_only_vi_obstacle"`
  - `surface_interaction_model_resolved = "vi_obstacle"`.

### 10.3 Analyse, comparaison et rapports

Fichiers a auditer :

- `hydromodpy/analysis/comparison/experiment_launcher.py`
- `hydromodpy/analysis/comparison/exports.py`
- `hydromodpy/analysis/comparison/output_pipeline.py`
- `hydromodpy/analysis/comparison/reporting.py`
- `hydromodpy/analysis/comparison/runtime.py`
- `hydromodpy/analysis/comparison/web/sections.py`

Points observes :

- `experiment_launcher.py` indexe des artefacts
  `boussinesq_ts_vi_obstacle_diagnostics` avec prefixe
  `ts_vi_obstacle_` ;
- les rapports et pages web peuvent afficher les libelles des variantes ;
- les anciens outputs doivent rester lisibles si l'on veut comparer avec des
  runs deja produits.

Cible :

- pour les nouveaux runs, ne produire que les diagnostics VI obstacle
  canoniques ;
- garder les lecteurs tolerants aux anciens artefacts pendant une periode de
  migration ;
- eviter de supprimer la lecture d'anciens JSON/CSV tant que les outputs dans
  `examples/projects/10_testbed_workflow/outputs` servent encore de reference.

### 10.4 Validation cases et exemples

Fichiers et dossiers importants :

- `validation_cases/shared/boussinesq_analytical_runtime.py`
- `validation_cases/shared/boussinesq_plotting.py`
- `tests/validation/analytical/`
- `tests/validation/numerical/`
- `examples/projects/09_comparison_workflow/`
- `examples/projects/10_testbed_workflow/boussinesq/`
- `examples/projects/11_nancon_network_physical_benchmark/`

Etat actuel notable :

- les cas analytiques steady utilisent deja `vi_obstacle` par defaut ;
- les cas analytiques transient utilisent encore `ts_vi_obstacle` par defaut ;
- beaucoup de TOML de validation declarent explicitement
  `runtime_backend` et `surface_interaction_model` ;
- les cas naturels et heterogenes du testbed utilisent `ts_vi_obstacle` pour
  les transitoires.

Cible :

- basculer le default transient de `ts_vi_obstacle` vers `vi_obstacle` apres
  validation ;
- remplacer les comparaisons "partition versus complementarity" par des tests
  d'acceptation du runtime canonique ;
- conserver quelques anciens TOML uniquement comme fixtures de migration, pas
  comme exemples recommandes.

## 11. Risque principal : supprimer PETSc TS VI

Le choix le plus structurant est la suppression ou non de
`petsc_ts_vi_obstacle.py`.

Arguments pour supprimer TS VI :

- `petsc_vi_obstacle.py` supporte deja steady et transient ;
- il contient deja une logique de substeps fixes/adaptatifs par periode ;
- il utilise directement `SNES.setVariableBounds(...)`, comme la cible
  SNESVI ;
- il evite une seconde pile PETSc avec `TS`, `TSAdapt`, raisons de convergence
  TS et diagnostics dedies ;
- il permet un seul chemin de debug pour steady et transient.

Arguments pour le garder temporairement :

- les cas transitoires analytiques utilisent actuellement
  `petsc_ts_vi_obstacle` comme reference PETSc VI ;
- les exemples naturels/heterogenes recents declarent
  `surface_interaction_model = "ts_vi_obstacle"` ;
- le test unitaire existant ne prouve l'equivalence TS VI versus SNESVI direct
  que sur un cas mono-cellule ;
- PETSc TS peut avoir des details de pilotage temporel differents meme en
  Backward Euler a pas fixe.

Conclusion :

- ne pas supprimer TS VI dans le premier commit de refactoring ;
- d'abord ajouter une matrice de validation directe
  `petsc_vi_obstacle` transient ;
- supprimer TS VI seulement si les tests ci-dessous passent avec des marges
  stables.

### 11.1 Tests a ajouter avant suppression TS VI

1. Cas analytique recharge step 1D :
   - ancien test : `petsc_ts_vi_obstacle` ;
   - nouveau test : `petsc_vi_obstacle` avec substeps explicites ;
   - critere : meme tolerance de profil que le test TS VI actuel.
2. Cas analytique boundary step 1D :
   - meme remplacement ;
   - verifier aussi les historiques aux temps intermediaires.
3. Cas hillslope recharge pulse overflow :
   - remplacer les variantes `petsc_partition` et `petsc_complementarity`
     par un cas canonical SNESVI ;
   - verifier head RMSE, activation surface, bilan d'eau.
4. Cas headwater 100 km2 pulsed/cycling :
   - valider que le seuil de surface s'active et se desactive aux periodes
     attendues ;
   - comparer le comportement a la branche complementarity, pas a partition,
     car les tests actuels indiquent que partition peut rester active apres
     les pulses secs.
5. Cas naturel 10 km2 et synthetic patchy :
   - convertir une selection reduite de TOML `ts_vi_obstacle` vers
     `vi_obstacle` ;
   - verifier convergence, bornes et budgets sur WSL.

### 11.2 Criteres d'acceptation transient

Un cas transient SNESVI direct peut remplacer TS VI si, pour chaque periode :

- `converged == true` ;
- `vi_bounds_max_violation_m <= 1e-8` ou tolerance existante equivalente ;
- le residu projete/interieur reste dans la tolerance de solveur ;
- aucune cellule libre ne sort de `z_bottom <= h <= z_top` hors tolerance ;
- les volumes de reaction surface/fond restent coherents avec le bilan ;
- les nombres de substeps utilises restent raisonnables et documentes ;
- les outputs web et NPZ restent exploitables par la comparaison existante.

Pour les cas de reference, ajouter aussi :

- RMSE et max error sur `head_m` aux temps de comparaison ;
- erreur de volume cumulee ;
- nombre de cellules surface/fond actives ;
- comparaison qualitative des periodes d'activation/deactivation.

## 12. Tests a modifier ou supprimer

### 12.1 Tests unitaires

| Fichier | Action recommandee |
| --- | --- |
| `tests/unit/solver/test_boussinesq_method_catalog.py` | Supprimer apres contraction de `methods`/`engines`; remplacer par un test unique de resolution canonique si l'adaptateur reste public. |
| `tests/unit/solver/test_boussinesq_initial_conditions.py` | Remplacer les assertions sur `regularized_partition`/`ts_vi_obstacle` par `vi_obstacle` ou par tests de migration d'anciens tokens. |
| `tests/unit/solver/test_partition_triplets.py` | Garder les tests d'operator triplets generiques; supprimer les tests de surface regularized partition. |
| `tests/unit/solver/test_petsc_mixed_double_obstacle.py` | Supprimer avec `petsc_mixed.py`; transferer seulement les idees de reaction/bornes si utiles au runtime VI. |
| `tests/unit/solver/test_petsc_ts_vi_obstacle.py` | Garder temporairement pour prouver l'equivalence; supprimer avec TS VI. |
| `tests/unit/solver/test_petsc_vi_obstacle.py` | Devenir le test central du runtime Boussinesq PETSc. Ajouter les cas de substeps transient. |

### 12.2 Tests de validation

| Zone | Action recommandee |
| --- | --- |
| `tests/validation/analytical/steady` | Garder les references analytiques; supprimer les parametrisations partition/complementarity. |
| `tests/validation/analytical/transient` | Ajouter `petsc_vi_obstacle` comme chemin principal; supprimer `petsc_ts_vi_obstacle` seulement apres equivalence. |
| `tests/validation/numerical/steady` | Convertir les tests 100 km2 vers un seul cas canonique SNESVI. |
| `tests/validation/numerical/transient` | Remplacer les comparaisons partition/complementarity par tests de comportement physique du runtime unique. |
| tests Windows natifs | Ne pas lancer le solveur Boussinesq PETSc; garder uniquement assemblage/config pure Python. |

### 12.3 Tests de garde apres suppression

Ajouter un test qui echoue si les anciens tokens reviennent dans le code
operationnel :

```bash
rg -n "petsc_partition|petsc_mixed|scipy_sparse|scipy_dense|regularized_partition|complementarity|ts_vi_obstacle" hydromodpy tests validation_cases examples
```

Les occurrences restantes doivent etre classees dans une allow-list :

- notes historiques ;
- fixtures de migration ;
- lecteurs tolerants d'anciens outputs ;
- changelog ou diagnostics internes.

### 12.4 Tests de non-regression a ajouter avant refactoring

Oui : il faut ajouter ou au minimum figer des tests de non-regression avant de
supprimer les variantes. Le but n'est pas de sanctuariser toute l'ancienne
architecture, mais de rendre explicite ce que le refactoring doit preserver :
convergence, contraintes VI, bilans, profils analytiques et comportement
transitoire.

Principe :

- ajouter les tests avant les suppressions ;
- executer toute la suite PETSc sous WSL/Linux et conserver le resultat comme
  baseline ;
- ne pas rendre les tests fragiles aux details PETSc non essentiels comme le
  nombre exact d'iterations si les residus, bornes et budgets sont bons ;
- separer les invariants durs des comparaisons numeriques tolerantes.

Invariants durs a verifier pour chaque run PETSc conserve :

- `runtime_backend == "petsc"` ;
- le runtime attendu est rapporte correctement ;
- `converged == true` ;
- aucune violation de borne VI hors tolerance ;
- pas de NaN/Inf dans `head_m`, reactions, flux et historiques ;
- les tableaux exportes gardent la meme taille, le meme nombre de periodes et
  le meme mapping cellule/temps ;
- les budgets ferment dans une tolerance explicite.

Comparaisons numeriques tolerantes a ajouter :

- norme L2/RMSE et max error sur `head_m` ;
- min/max/moyenne de charge finale ;
- volume cumule recharge, drainage, surface reaction, bottom reaction ;
- nombre de cellules actives en surface et au fond ;
- dates/periodes d'activation de la contrainte de surface ;
- pour les cas analytiques, erreur par rapport a la solution de reference.

### 12.5 Suite PETSc minimale a figer

| Niveau | Tests actuels a utiliser comme base | Ce qu'ils verrouillent |
| --- | --- | --- |
| Unit VI direct | `tests/unit/solver/test_petsc_vi_obstacle.py` | Bornes SNESVI, signe du residu projete, diagnostics, reactions surface/fond. |
| Unit TS VI | `tests/unit/solver/test_petsc_ts_vi_obstacle.py` | Comportement TS VI courant et equivalence mono-cellule avec VI direct substeppe. |
| Analytique steady | `tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py` | Reference Dupuit et comportement steady PETSc VI. |
| Analytique transient | `tests/validation/analytical/transient/test_linearized_unconfined_recharge_step_1d.py` et `test_linearized_unconfined_boundary_step_1d.py` | Reference transitoire actuellement portee par TS VI. |
| Numerique steady | `tests/validation/numerical/steady/test_boussinesq_headwater_100km2_petsc.py` | Cas bassin reel steady, convergence des variantes PETSc actuelles. |
| Numerique transient | `tests/validation/numerical/transient/test_boussinesq_headwater_100km2_petsc_transient.py` | Pulses, cycling, heterogeneite et activation/desactivation de surface. |
| Overflow/drying | `tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py` et `test_boussinesq_drying_petsc.py` | Saturation de surface, debordement et obstacle inferieur. |

Commande de baseline WSL recommandee :

```bash
python -m pytest -m petsc \
  tests/unit/solver/test_petsc_vi_obstacle.py \
  tests/unit/solver/test_petsc_ts_vi_obstacle.py \
  tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py \
  tests/validation/analytical/transient/test_linearized_unconfined_recharge_step_1d.py \
  tests/validation/analytical/transient/test_linearized_unconfined_boundary_step_1d.py \
  tests/validation/numerical/steady/test_boussinesq_headwater_100km2_petsc.py \
  tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py \
  tests/validation/numerical/transient/test_boussinesq_headwater_100km2_petsc_transient.py \
  tests/validation/numerical/transient/test_boussinesq_drying_petsc.py \
  -q
```

Si la commande est trop longue pour le cycle quotidien, la couper en deux
niveaux :

```bash
# smoke avant chaque commit
python -m pytest -m petsc \
  tests/unit/solver/test_petsc_vi_obstacle.py \
  tests/unit/solver/test_petsc_ts_vi_obstacle.py \
  tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py \
  tests/validation/analytical/transient/test_linearized_unconfined_recharge_step_1d.py \
  -q

# extensive avant suppression de runtime
python -m pytest -m "petsc and (validation or regression or extensive)" \
  tests/validation/analytical \
  tests/validation/numerical \
  -q
```

### 12.6 Baselines a materialiser

Pour preparer proprement le refactoring, ajouter un petit jeu de baselines
committees, idealement sous :

```text
tests/validation/fixtures/boussinesq_petsc_regression/
```

Format recommande :

- un JSON compact par scenario avec metadata :
  - nom du scenario ;
  - solver/runtime ;
  - version Python, PETSc, petsc4py si disponible ;
  - options PETSc effectives ;
  - nombre de cellules/periodes ;
  - tolerances de comparaison ;
- un NPZ pour les tableaux numeriques utiles quand le scenario est petit ;
- pour les gros cas, eviter de committer tout l'output web, stocker seulement
  des signatures numeriques robustes.

Exemple de contenu JSON attendu :

```json
{
  "scenario": "dupuit_fixed_head_1d_petsc_vi_obstacle",
  "runtime_engine_id": "petsc_vi_obstacle_snes",
  "n_cells": 100,
  "n_periods": 1,
  "head_final_min_m": 10.0,
  "head_final_max_m": 12.0,
  "head_reference_rmse_m": 1e-6,
  "vi_bounds_max_violation_m": 0.0,
  "water_budget_abs_error_m3": 1e-8
}
```

Les valeurs ci-dessus sont illustratives : les vraies valeurs doivent etre
generees par les tests actuels sous WSL.

### 12.7 Tests preparatoires a ecrire

Ajouter avant suppression :

1. un test `petsc_vi_obstacle` transient sur recharge step 1D, en parallele du
   test TS VI existant ;
2. un test `petsc_vi_obstacle` transient sur boundary step 1D ;
3. un test d'equivalence TS VI versus VI direct sur un petit maillage
   multi-cellules, pas seulement mono-cellule ;
4. un test de lecture tolerant des anciens summaries `ts_vi_obstacle_*` si les
   anciens outputs web restent dans les exemples ;
5. un test de migration TOML :
   - ancien `surface_interaction_model = "ts_vi_obstacle"` ;
   - ancien `surface_interaction_model = "complementarity"` ;
   - ancien `surface_interaction_model = "regularized_partition"` ;
   - comportement attendu : warning + resolution vers la cible, ou erreur
     explicite selon la phase choisie ;
6. un test de garde qui verifie que le solveur Boussinesq PETSc n'est jamais
   lance sous Windows natif sans `petsc4py`.

### 12.8 Politique de tolerance

Ne pas comparer strictement :

- le nombre exact d'iterations SNES/KSP ;
- les raisons PETSc detaillees si plusieurs raisons positives signifient
  convergence acceptable ;
- l'ordre exact des cles JSON non contractuelles ;
- les chemins absolus dans les artefacts.

Comparer strictement :

- presence des champs contractuels ;
- dimensions des tableaux ;
- absence de NaN/Inf ;
- respect des bornes VI ;
- signe des reactions aux bornes ;
- conservation du nombre de periodes et des temps de sortie.

Comparer avec tolerance :

- `head_m` ;
- flux et volumes cumules ;
- residus ;
- budgets ;
- reactions surface/fond ;
- diagnostics agreges.

Tolerance de depart recommandee :

- analytique 1D : garder les tolerances existantes des tests ;
- petits tests unitaires : `1e-10` a `1e-8` selon grandeur ;
- cas bassin reel : `1e-6` a `1e-5` m pour les charges, a ajuster selon le
  niveau de bruit PETSc observe ;
- budgets : tolerance relative plus tolerance absolue, pour eviter les faux
  positifs sur volumes tres petits.

### 12.9 Critere de passage avant la premiere suppression

Ne supprimer aucun runtime tant que les conditions suivantes ne sont pas vraies :

- la suite smoke PETSc passe sous WSL ;
- les deux cas analytiques transient ont un equivalent `petsc_vi_obstacle` ;
- les outputs historiques `ts_vi_obstacle` restent lisibles ou sont declares
  hors support ;
- les anciens TOML critiques ont une politique de migration testee ;
- le comportement actuel des variantes PETSc a supprimer est capture dans un
  test, une baseline ou une note de decision.

## 13. Plan de refactoring par commits

### Commit 1 : figer le contrat cible

Objectif :

- documenter que Boussinesq production = PETSc SNESVI sous WSL/Linux ;
- ajouter une constante runtime canonique ;
- centraliser les metadata :
  - `runtime_backend = "petsc"`
  - `runtime_engine_id = "petsc_vi_obstacle_snes"`
  - `runtime_formulation = "head_only_vi_obstacle"`
  - `surface_interaction_model_resolved = "vi_obstacle"`.

Changements :

- ajouter un helper court dans le package Boussinesq, par exemple
  `canonical_runtime.py`, ou simplifier directement `runtime_selection.py` ;
- ne supprimer aucun ancien fichier dans ce commit.

Verification :

```bash
pytest tests/unit/solver/test_boussinesq_method_catalog.py tests/unit/solver/test_petsc_vi_obstacle.py
```

### Commit 2 : valider `petsc_vi_obstacle` transient

Objectif :

- prouver que SNESVI direct avec substeps remplace TS VI sur les cas que l'on
  veut garder.

Changements :

- ajouter les cas analytiques transient `petsc_vi_obstacle` ;
- convertir un petit cas numerique transient ;
- conserver TS VI comme reference pendant ce commit.

Verification WSL :

```bash
pytest -m petsc tests/unit/solver/test_petsc_vi_obstacle.py tests/unit/solver/test_petsc_ts_vi_obstacle.py
pytest -m petsc tests/validation/analytical/transient
```

### Commit 3 : contracter la configuration Flow

Objectif :

- retirer les choix utilisateur non productifs des nouveaux templates ;
- garder une compatibilite lisible pour les anciens TOML.

Changements :

- `runtime_backend` devient implicite pour Boussinesq ;
- `surface_interaction_model` devient implicite ou limite a
  `auto`/`vi_obstacle` ;
- les anciens tokens produisent warnings ou erreurs selon la politique choisie ;
- les fixtures TOML de migration sont isolees.

Verification :

```bash
pytest tests/unit/solver/test_boussinesq_initial_conditions.py
rg -n "surface_interaction_model = \"(regularized_partition|complementarity|ts_vi_obstacle)\"" examples validation_cases
```

### Commit 4 : supprimer les runtimes non PETSc et les catalogues

Objectif :

- supprimer le gros de l'ancien arbre de variantes.

Changements :

- supprimer `local.py`, `scipy_dense.py`, `scipy_sparse.py` ;
- supprimer `newton_common.py`, `head_only_common.py` si plus importes ;
- supprimer `methods/catalog.py`, `engines/catalog.py` ou les reduire a un
  shim temporaire ;
- simplifier `runtime_selection.py`.

Verification :

```bash
pytest tests/unit/solver
rg -n "scipy_dense|scipy_sparse|runtime_backend = \"local\"" hydromodpy tests validation_cases examples
```

### Commit 5 : supprimer partition et mixed complementarity

Objectif :

- retirer les deux formulations historiques concurrentes.

Changements :

- supprimer `petsc_partition.py`, `partition_utils.py`,
  `jacobian/partition_triplets.py` ;
- supprimer `petsc_mixed.py`, `petsc_mixed_common.py`,
  `formulations/mixed_complementarity.py` ;
- simplifier les diagnostics de surface autour des reactions obstacle ;
- adapter les validations steady/numerical.

Verification WSL :

```bash
pytest -m petsc tests/validation/analytical/steady tests/validation/numerical/steady
pytest -m petsc tests/validation/numerical/transient
```

### Commit 6 : supprimer TS VI ou le garder comme phase 2 bis

Condition pour supprimer :

- les tests de la section 11 passent ;
- les cas naturels/heterogenes choisis convergent en `petsc_vi_obstacle` ;
- les budgets et les bornes sont stables.

Si la condition est remplie :

- supprimer `petsc_ts_vi_obstacle.py` ;
- supprimer `ts_vi_obstacle_diagnostics.py` ;
- migrer les derniers TOML `ts_vi_obstacle` vers `vi_obstacle` ;
- retirer l'index d'artefacts TS VI des nouveaux runs.

Si la condition n'est pas remplie :

- garder `petsc_ts_vi_obstacle.py` comme seul runtime transient provisoire ;
- appliquer quand meme les commits 3 a 5 ;
- la reduction reste autour de 24 % dans le package solver et conserve une
  architecture beaucoup plus simple que l'actuelle.

### Commit 7 : nettoyer exemples, docs et rapports

Objectif :

- eviter que l'ancienne taxonomie soit encore visible comme choix recommande.

Changements :

- mettre a jour les TOML dans `examples/projects/10_testbed_workflow` ;
- mettre a jour les README Boussinesq et diagnostics ;
- remplacer les libelles "partition/complementarity/TS VI" par "PETSc SNESVI"
  dans les nouveaux rapports ;
- garder les anciens libelles uniquement dans les lecteurs d'outputs
  historiques.

Verification :

```bash
rg -n "regularized_partition|complementarity|ts_vi_obstacle|petsc_partition|petsc_mixed" docs examples validation_cases hydromodpy
```

## 14. Impact sur les TOML et l'experience utilisateur

Avant :

```toml
[physics.flow]
runtime_backend = "petsc"
surface_interaction_model = "ts_vi_obstacle"
```

Apres cible stricte :

```toml
[physics.flow]
# plus de choix runtime Boussinesq expose
```

Ou, pendant migration :

```toml
[physics.flow]
surface_interaction_model = "vi_obstacle"
```

Regle recommandee :

- les nouveaux exemples ne declarent plus `runtime_backend` ;
- les nouveaux exemples ne declarent plus `surface_interaction_model` sauf si
  l'on veut montrer explicitement la migration ;
- les anciens TOML restent executables pendant une periode courte si le cout
  de compatibilite est faible ;
- tout run Boussinesq qui necessite PETSc indique clairement WSL/Linux dans le
  message d'erreur si execute sous Windows natif.

## 15. Ce qu'il ne faut pas supprimer

Meme avec un runtime unique, conserver :

- le solveur public `solver_engine = "boussinesq"` ;
- les structures de maillage et adaptateurs Flow vers Boussinesq ;
- les forcages et conditions aux limites ;
- les drivers steady/transient ;
- l'historique `_boussinesq_state_history.npz` ;
- les exports de head, budget, reactions et diagnostics utiles ;
- les lecteurs tolerants d'anciens outputs si ces outputs restent dans les
  exemples ou servent aux comparaisons ;
- les tests d'assemblage purs Python pour garder un minimum de couverture hors
  WSL.

SciPy ne doit pas etre retire globalement du projet dans ce refactoring. La
question ici est seulement la suppression des runtimes SciPy Boussinesq.

## 16. Estimation finale de proportion

Reponse courte a la question "de quelle proportion la partie Boussinesq serait
reduite ?" :

- environ 24 % du package `hydromodpy/solver/boussinesq` si l'on garde PETSc
  TS VI pour le transient ;
- environ 32 % par suppression directe si l'on garde uniquement
  `petsc_vi_obstacle.py` ;
- environ 35 a 40 % en reduction fonctionnelle realiste apres nettoyage des
  contrats, tests, exemples et diagnostics de variantes ;
- potentiellement un peu plus de 40 % si l'on accepte de retirer rapidement les
  compatibilites historiques et les anciens artefacts de comparaison.

La valeur prudente a annoncer est donc : **un tiers du code Boussinesq solver
en suppression directe, et probablement autour de 40 % de simplification
effective de la surface Boussinesq**.

## 17. Recommandation mise a jour

La strategie la plus sure est :

1. Figer d'abord une baseline PETSc WSL de non-regression.
2. Prendre `petsc_vi_obstacle.py` comme cible canonique.
3. Ne pas supprimer TS VI avant d'avoir prouve les transitoires.
4. Supprimer d'abord les variantes qui n'ont plus de raison de production :
   `local`, `scipy_dense`, `scipy_sparse`, `petsc_partition`,
   `petsc_mixed`.
5. Contracter ensuite la configuration et les catalogues.
6. Finir par TS VI et les diagnostics historiques.

Cette sequence donne deja la majorite du gain sans prendre le risque de casser
les cas transitoires naturels. Le seul vrai blocage technique est l'equivalence
pratique entre `petsc_ts_vi_obstacle` et `petsc_vi_obstacle` avec substeps sur
les cas transient de validation.

## 18. Premiere passe preparatoire lancee

Etat : demarre, sans refactoring ni suppression.

Tests et verrous ajoutes :

- alias de validation `petsc_vi_obstacle` pour les deux cas analytiques
  transitoires :
  - recharge step 1D ;
  - boundary step 1D ;
- tests PETSc marques `@pytest.mark.petsc` pour executer ces deux cas avec
  `surface_interaction_model = "vi_obstacle"` et `vi_substeps_per_period = 4` ;
- metadata de shape ajoutees pour `petsc_vi_obstacle` sur ces deux cas ;
- tolerances dediees `tolerances_petsc_vi_obstacle.toml`, initialement alignees
  sur les tolerances TS VI existantes ;
- test unitaire pur Python qui verifie que l'alias `petsc_vi_obstacle` route
  bien vers `runtime_backend = "petsc"` et
  `surface_interaction_model = "vi_obstacle"` ;
- test unitaire pur Python qui verifie que les runtimes analytiques transient
  posent bien `vi_substeps_per_period = 4` sans options TS ;
- test PETSc multi-cellules qui compare `petsc_ts_vi_obstacle` a
  `petsc_vi_obstacle` substeppe sur une ligne de trois cellules.

Commandes locales executees sous Windows :

```bash
python -m pytest tests/unit/validation/test_linearized_unconfined_petsc_vi_alias.py -q
```

Resultat : `4 passed`.

```bash
python -m pytest \
  tests/unit/solver/test_petsc_ts_vi_obstacle.py::test_ts_vi_matches_manual_vi_substeps_on_three_cell_line \
  tests/validation/analytical/transient/test_linearized_unconfined_recharge_step_1d.py::test_linearized_unconfined_recharge_step_1d_petsc_vi_obstacle_matches_reference_profiles \
  tests/validation/analytical/transient/test_linearized_unconfined_boundary_step_1d.py::test_linearized_unconfined_boundary_step_1d_petsc_vi_obstacle_matches_reference_profiles \
  -q
```

Resultat local Windows : `3 skipped`, attendu car les tests PETSc sont
Linux/WSL + petsc4py.

```bash
python -m ruff check \
  validation_cases/analytical/transient/linearized_unconfined_recharge_step_1d/comparison.py \
  validation_cases/analytical/transient/linearized_unconfined_boundary_step_1d/comparison.py \
  validation_cases/analytical/transient/linearized_unconfined_recharge_step_1d/runtime_boussinesq.py \
  validation_cases/analytical/transient/linearized_unconfined_boundary_step_1d/runtime_boussinesq.py \
  tests/unit/validation/test_linearized_unconfined_petsc_vi_alias.py \
  tests/unit/solver/test_petsc_ts_vi_obstacle.py \
  tests/validation/analytical/transient/test_linearized_unconfined_recharge_step_1d.py \
  tests/validation/analytical/transient/test_linearized_unconfined_boundary_step_1d.py
```

Resultat : `All checks passed`.

Prochaine verification a faire sous WSL :

```bash
python -m pytest -m petsc \
  tests/unit/solver/test_petsc_vi_obstacle.py \
  tests/unit/solver/test_petsc_ts_vi_obstacle.py \
  tests/validation/analytical/transient/test_linearized_unconfined_recharge_step_1d.py::test_linearized_unconfined_recharge_step_1d_petsc_vi_obstacle_matches_reference_profiles \
  tests/validation/analytical/transient/test_linearized_unconfined_boundary_step_1d.py::test_linearized_unconfined_boundary_step_1d_petsc_vi_obstacle_matches_reference_profiles \
  -q
```

Cette passe ne modifie pas encore la selection de production. Elle prepare
seulement les verrous necessaires pour evaluer si `petsc_vi_obstacle` peut
remplacer TS VI en transient.

## 19. Baseline WSL hydromodpy-wsl

Date : 2026-05-12

Environnement :

- distribution WSL : `Ubuntu-22.04` ;
- environnement Conda : `/home/dreuzy/miniforge3/envs/hydromodpy-wsl` ;
- Python : `3.13.12` ;
- petsc4py : `3.24.6` ;
- PETSc : `3.24.6` ;
- ruff : `0.15.12`, installe dans `hydromodpy-wsl` le 2026-05-12 ;
- repo execute depuis `/mnt/c/codes/HydroModPy`.

### 19.1 Smoke PETSc preparatoire

Commande :

```bash
python -m pytest -m petsc \
  tests/unit/solver/test_petsc_vi_obstacle.py \
  tests/unit/solver/test_petsc_ts_vi_obstacle.py \
  tests/validation/analytical/transient/test_linearized_unconfined_recharge_step_1d.py::test_linearized_unconfined_recharge_step_1d_petsc_vi_obstacle_matches_reference_profiles \
  tests/validation/analytical/transient/test_linearized_unconfined_boundary_step_1d.py::test_linearized_unconfined_boundary_step_1d_petsc_vi_obstacle_matches_reference_profiles \
  -q
```

Resultat WSL : `9 passed, 3 deselected`.

### 19.2 Suite analytique PETSc elargie

Commande :

```bash
python -m pytest -m petsc \
  tests/unit/solver/test_petsc_vi_obstacle.py \
  tests/unit/solver/test_petsc_ts_vi_obstacle.py \
  tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py \
  tests/validation/analytical/transient/test_linearized_unconfined_recharge_step_1d.py \
  tests/validation/analytical/transient/test_linearized_unconfined_boundary_step_1d.py \
  -q
```

Resultat WSL : `16 passed, 9 deselected`.

Cette passe valide :

- les tests unitaires PETSc VI direct ;
- les tests unitaires PETSc TS VI ;
- l'equivalence TS VI versus VI direct substeppe sur mono-cellule et
  trois cellules ;
- Dupuit steady PETSc ;
- les deux cas analytiques transitoires avec TS VI existant et VI direct
  ajoute.

### 19.3 Suite numerique PETSc existante

Commande :

```bash
python -m pytest -m petsc \
  tests/validation/numerical/steady/test_boussinesq_headwater_100km2_petsc.py \
  tests/validation/numerical/transient/test_boussinesq_hillslope_recharge_pulse_overflow_petsc.py \
  tests/validation/numerical/transient/test_boussinesq_headwater_100km2_petsc_transient.py \
  tests/validation/numerical/transient/test_boussinesq_drying_petsc.py \
  -q
```

Resultat WSL : `6 passed, 6 skipped`.

Les skips viennent des fixtures headwater 100 km2 absentes dans ce checkout :

- `examples/projects/launcher_simulation/run_headwater_100km2_outlet_2_boussinesq_petsc_partition_mesh_input.toml`
- `examples/projects/launcher_simulation/run_headwater_100km2_outlet_2_boussinesq_petsc_mesh_input.toml`
- `tests/validation/fixtures/petsc_headwater_100km2/run_headwater_100km2_outlet_2_boussinesq_petsc_partition_transient_pulsed_recharge.toml`
- `tests/validation/fixtures/petsc_headwater_100km2/run_headwater_100km2_outlet_2_boussinesq_petsc_transient_pulsed_recharge.toml`
- `tests/validation/fixtures/petsc_headwater_100km2/run_headwater_100km2_outlet_2_boussinesq_petsc_partition_transient_cycling_recharge.toml`
- `tests/validation/fixtures/petsc_headwater_100km2/run_headwater_100km2_outlet_2_boussinesq_petsc_transient_cycling_recharge.toml`
- `tests/validation/fixtures/petsc_headwater_100km2/run_headwater_100km2_outlet_2_boussinesq_petsc_partition_transient_cycling_recharge_heterogeneous.toml`
- `tests/validation/fixtures/petsc_headwater_100km2/run_headwater_100km2_outlet_2_boussinesq_petsc_transient_cycling_recharge_heterogeneous.toml`

Action recommandee : restaurer ou regenerer ces fixtures si l'on veut une
baseline numerique headwater complete avant suppression de variantes. Les tests
disponibles, notamment hillslope overflow et drying, passent deja.

### 19.4 Unitaires purs WSL

Commande :

```bash
python -m pytest tests/unit/validation/test_linearized_unconfined_petsc_vi_alias.py -q
```

Resultat WSL : `4 passed`.

### 19.5 Lint

`ruff` a ete installe dans `hydromodpy-wsl` :

```bash
python -m pip install ruff
python -m ruff --version
```

Resultat : `ruff 0.15.12`.

Commande Ruff WSL :

```bash
python -m ruff check \
  validation_cases/analytical/transient/linearized_unconfined_recharge_step_1d/comparison.py \
  validation_cases/analytical/transient/linearized_unconfined_boundary_step_1d/comparison.py \
  validation_cases/analytical/transient/linearized_unconfined_recharge_step_1d/runtime_boussinesq.py \
  validation_cases/analytical/transient/linearized_unconfined_boundary_step_1d/runtime_boussinesq.py \
  tests/unit/validation/test_linearized_unconfined_petsc_vi_alias.py \
  tests/unit/solver/test_petsc_ts_vi_obstacle.py \
  tests/validation/analytical/transient/test_linearized_unconfined_recharge_step_1d.py \
  tests/validation/analytical/transient/test_linearized_unconfined_boundary_step_1d.py
```

Resultat WSL : `All checks passed`.

Le warning WSL `your 131072x1 screen size is bogus` apparait a chaque commande
mais n'a pas affecte les tests.

## 20. Campagne preparatoire implementee : PETSc direct `vi_obstacle`

Date : 2026-05-12

Objectif : remplacer les anciennes fixtures headwater 100 km2 restaurees depuis
`launcher_simulation` par une campagne propre, generee par la logique actuelle
`testbed` / `comparison`, et centree sur le runtime Boussinesq qui doit rester.

Fichiers ajoutes :

- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/compare_natural_mf6_bouss_petsc_vi_base.toml`
- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/natural_petsc_vi_regression_sites.csv`
- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/natural_petsc_vi_regression_testbed.toml`
- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_natural_petsc_vi_regression_chain.py`
- `tests/unit/launchers/test_boussinesq_petsc_vi_regression_testbed.py`
- `tests/unit/comparison/test_boussinesq_petsc_vi_web_sections.py`

Sites couverts par le catalogue preparatoire :

| Site | Taille | Famille |
| --- | --- | --- |
| `site_01` | 10 km2 | headwater |
| `site_03` | 10 km2 | headwater |
| `site_08` | 10 km2 | headwater |
| `headwater_100km2_outlet_2` | 100 km2 | headwater |
| `headwater_100km2_outlet_4` | 100 km2 | headwater |
| `s3_100km2_outlet_25` | 100 km2 | Strahler 3 |

Contrat Boussinesq impose par la base de comparaison :

```toml
[comparison.simulation.overlay.flow]
runtime_backend = "petsc"
surface_interaction_model = "vi_obstacle"
vi_substeps_per_period = 4
vi_substep_on_failure = true
vi_max_adaptive_substeps = 32
```

Ce contrat exclut volontairement :

- `runtime_backend = "scipy_sparse"` ;
- `surface_interaction_model = "regularized_partition"` ;
- `surface_interaction_model = "complementarity"` ;
- `surface_interaction_model = "ts_vi_obstacle"` ;
- les options `ts_vi_*` dans la configuration Boussinesq cible.

La campagne conserve MF6 comme reference de comparaison afin de garder les
rapports HTML existants : cartes, metriques, differences, tableaux de runtime
et diagnostics. La simplification porte uniquement sur le candidat
Boussinesq.

Commandes WSL :

```bash
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_natural_petsc_vi_regression_chain.py \
  --plan-only
```

```bash
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_natural_petsc_vi_regression_chain.py \
  --sites site_03 headwater_100km2_outlet_2
```

Sorties HTML attendues :

- comparaison par site :
  `examples/projects/10_testbed_workflow/outputs/boussinesq_petsc_vi_regression_testbed/comparisons/<site>_natural_<scale>_mf6_bouss_petsc_vi/web/index.html` ;
- synthese :
  `examples/projects/10_testbed_workflow/outputs/boussinesq_petsc_vi_regression_testbed/web_synthesis/index.html`.

Tests ajoutes :

- materialisation de 6 comparaisons multi-tailles sans execution ;
- verification que le candidat Boussinesq genere reste `petsc` +
  `vi_obstacle` ;
- verification des reglages 100 km2 : timeout, raster, snap/buffer, seuil
  reseau hydrographique, tailles de maille ;
- verification du libelle HTML direct PETSc SNESVI pour `vi_obstacle`.

Validation locale initiale :

```text
python -m pytest tests/unit/launchers/test_boussinesq_petsc_vi_regression_testbed.py tests/unit/comparison/test_boussinesq_petsc_vi_web_sections.py -q
5 passed

python -m ruff check hydromodpy/analysis/comparison/web/sections.py tests/unit/launchers/test_boussinesq_petsc_vi_regression_testbed.py tests/unit/comparison/test_boussinesq_petsc_vi_web_sections.py examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_natural_petsc_vi_regression_chain.py
All checks passed
```

Validation WSL `hydromodpy-wsl` effectuee :

```text
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_natural_petsc_vi_regression_chain.py \
  --plan-only

Plan materialized: 6 variants
```

```text
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest \
  tests/unit/launchers/test_boussinesq_petsc_vi_regression_testbed.py \
  tests/unit/comparison/test_boussinesq_petsc_vi_web_sections.py \
  -q

5 passed
```

```text
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest -m petsc \
  tests/unit/solver/test_petsc_vi_obstacle.py \
  tests/validation/analytical/steady/test_dupuit_fixed_head_petsc_1d.py \
  tests/validation/analytical/transient/test_linearized_unconfined_recharge_step_1d.py::test_linearized_unconfined_recharge_step_1d_petsc_vi_obstacle_matches_reference_profiles \
  tests/validation/analytical/transient/test_linearized_unconfined_boundary_step_1d.py::test_linearized_unconfined_boundary_step_1d_petsc_vi_obstacle_matches_reference_profiles \
  -q

8 passed, 3 deselected
```

```text
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_natural_petsc_vi_regression_chain.py \
  --html-only

Wrote 7 HTML files under outputs/boussinesq_petsc_vi_regression_testbed/web_synthesis
```

Limite constatee : les simulations naturelles completes ne peuvent pas etre
executees dans ce checkout tant que les donnees regionales attendues par
`base_site_01_mf6_bouss_transient.toml` ne sont pas presentes sous `data/`
(`DEM_armorican_massif.tif`, `regional_stream_network.shp`, `GEO1M.shp`,
`geology_K_dummy_demo.csv`). Le plan, les TOML generes, le HTML de synthese
et les tests PETSc analytiques sont cependant valides.

Ce qui reste avant suppression effective des anciens chemins :

1. restaurer ou monter les donnees regionales sous `data/` ;
2. executer sous WSL au moins `site_03` et `headwater_100km2_outlet_2` avec
   la nouvelle chaine ;
3. inspecter les deux rapports HTML et les diagnostics
   `vi_obstacle_runtime_summary.json` ;
4. elargir ensuite a tous les 6 sites si le temps de calcul est acceptable ;
5. convertir ou deprecie les anciennes validations 100 km2 sautees, pour
   qu'elles pointent vers cette campagne au lieu de `launcher_simulation`.
