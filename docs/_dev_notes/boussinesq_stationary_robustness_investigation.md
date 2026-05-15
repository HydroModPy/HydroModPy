# Investigation de robustesse stationnaire Boussinesq

Date : 2026-05-15

Statut : investigation basée sur l'inspection du code local, les artefacts de
campagnes naturelles existants, un nouveau point d'accroche de diagnostic d'échec stationnaire
couvert par test unitaire, et une matrice stationnaire bas niveau ciblée sur des
bundles de maillage naturel déjà générés. Aucun workflow complet
géographique/maillage n'a été relancé.

## Résumé exécutif

Les échecs Boussinesq naturels difficiles actuellement observés sont dominés par
le solveur stationnaire auxiliaire utilisé pour construire l'état initial, et non
par le sous-découpage transitoire mensuel. La signature répétée est :

- `flow_regime = "steady"` ;
- `runtime_problem_kind = "steady_head_balance"` ;
- PETSc `SNES_DIVERGED_LINE_SEARCH`, parfois `SNES_DIVERGED_MAX_IT` ;
- `total_periods = 0` ou absence de diagnostics de période transitoire ;
- `substep_diagnostic_count = 0`.

Augmenter `vi_substeps_per_period` ou `ts_vi_steps_per_period` ne peut pas
résoudre ces échecs quand aucun pas transitoire n'est atteint. Le prochain patch
de production doit se concentrer sur l'initialisation stationnaire robuste et sur
des fichiers persistants de post-mortem stationnaire.

Cette passe ajoute un écrivain de diagnostics non invasif pour les solveurs
stationnaires en échec :

- `stationary_failure_summary.json` ;
- `stationary_failure_cells_top_residual.csv` ;
- `stationary_failure_active_set_summary.csv` ;
- `stationary_failure_field_stats.json`.

La matrice de méthodes modifie l'hypothèse initiale. `regularized_partition`
converge souvent comme solveur stationnaire autonome, mais
`regularized -> clipped head -> VI` n'améliore pas de manière fiable le chemin de
Newton vers la VI cible et peut même faire échouer un voisin où le VI direct
converge. Sur les cas compacts `site_01_k_high`, les deux chemins de récupération
qui réussissent sont le pseudo-transitoire VI et la continuation drainage. Sur le
cas plus grand `site_02_network`, ni le pseudo-transitoire VI ni les continuations
simples recharge/drainage ne suffisent.

## Contexte

Les cas stationnaires Boussinesq naturels sont difficiles parce que l'opérateur
non linéaire change de régime sur les deux obstacles :

- obstacle inférieur : `h >= z_bottom` ;
- obstacle supérieur ou seuil de drainage :
  `h <= z_top` ou `q_drain = C max(h - z_top, 0)` ;
- transmissivité : `T(h) = K * saturated_thickness(h)`.

Près de `z_bottom`, la transmissivité peut devenir très faible et le jacobien
devient mal conditionné. Près de `z_top`, l'ensemble actif peut changer
brutalement. Les forts K, les cellules petites ou irrégulières, et les transitions
dures drainage/obstacle amplifient cette difficulté.

Un échec stationnaire est différent d'un échec transitoire. Dans un échec
d'initialisation stationnaire, l'exécution n'est pas encore entrée dans la boucle des
périodes de contrainte. Dans un échec transitoire, un état stationnaire peut déjà
être disponible et l'échec est alors lié à une période ou à un sous-pas.

## Architecture inspectée

Fichiers principaux inspectés :

- `hydromodpy/solver/boussinesq/boussinesq.py` ;
- `hydromodpy/solver/boussinesq/drivers/steady.py` ;
- `hydromodpy/solver/boussinesq/drivers/transient.py` ;
- `hydromodpy/solver/boussinesq/runtime_contract.py` ;
- `hydromodpy/solver/boussinesq/runtime_selection.py` ;
- `hydromodpy/solver/boussinesq/methods/catalog.py` ;
- `hydromodpy/solver/boussinesq/engines/catalog.py` ;
- `hydromodpy/solver/boussinesq/runtimes/petsc_vi_obstacle.py` ;
- `hydromodpy/solver/boussinesq/runtimes/petsc_ts_vi_obstacle.py` ;
- `hydromodpy/solver/boussinesq/runtimes/petsc_partition.py` ;
- `hydromodpy/solver/boussinesq/runtimes/petsc_mixed.py` ;
- `hydromodpy/solver/boussinesq/runtimes/scipy_sparse.py` ;
- `hydromodpy/solver/boussinesq/runtimes/local.py` ;
- `hydromodpy/solver/steady_initial_conditions.py` ;
- écrivains de diagnostics VI/TS existants.

Points clés :

1. Les exécutions Boussinesq transitoires avec `flow.ic.type = "steady_state"`
   appellent `_run_steady_state_initialization()` avant le pilote transitoire.
2. Cet assistant bascule temporairement le régime d'écoulement en `steady`,
   applique la recharge moyenne, peut remplacer `ts_vi_obstacle` par
   `regularized_partition`, lance le runtime stationnaire, puis restaure la
   configuration transitoire originale.
3. `regularized_partition` dispose de runtimes stationnaires dans `local`,
   `scipy_sparse` et `petsc_partition`.
4. `vi_obstacle` dispose d'un runtime stationnaire PETSc SNESVI.
5. `ts_vi_obstacle` est transitoire uniquement ; il n'a pas de runtime
   stationnaire.
6. `complementarity` dispose d'un runtime stationnaire mixte PETSc, mais retourne
   actuellement des diagnostics beaucoup moins détaillés que le runtime VI
   obstacle.
7. Les résumés runtime sont écrits dans `_boussinesq_summary.json` ; les
   diagnostics agrégés VI/TS en CSV/JSON sont écrits après le post-traitement.

## Cas investigués

Les cas principaux proviennent de :

- `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/` ;
- `examples/projects/10_testbed_workflow/outputs/boussinesq_petsc_vi_regression_testbed/` ;
- `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_network_site_candidates_testbed/` ;
- `docs/_dev_notes/diagnostics/boussinesq_failing_cases_inventory.md` ;
- `docs/_dev_notes/boussinesq_modflow_natural_method_discrepancy_report.md`.

| cas | config/artefact source | n_cells | régime K | drainage | type de maillage | échec connu | statut |
|---|---|---:|---|---|---|---|---|
| `site_01_k_base / bouss_tri_irregular_drain_001` | matrice drainage/K | 1250 | base | 0.01 | triangulaire contraint | aucun | contrôle convergé |
| `site_01_k_high / bouss_tri_irregular_drain_00` | matrice drainage/K | 1250 | high | 0 | triangulaire contraint | line search VI stationnaire | échec |
| `site_01_k_high / bouss_tri_irregular_drain_001` | matrice drainage/K | 1250 | high | 0.01 | triangulaire contraint | proche de l'échec | convergé |
| `site_01_k_high / bouss_tri_irregular_drain_01` | matrice drainage/K | 1250 | high | 0.1 | triangulaire contraint | line search VI stationnaire | échec |
| `site_02_k_low / bouss_tri_irregular_drain_00` | matrice drainage/K | 13234 | low | 0 | triangulaire contraint | line search VI stationnaire | échec |
| `site_02_k_low / bouss_tri_irregular_drain_001` | matrice drainage/K | 13210-13234 | low | 0.01 | triangulaire contraint | proche de l'échec | convergé |
| `site_02_k_base / bouss_tri_irregular_drain_00` | matrice drainage/K | 13258 | base | 0 | triangulaire contraint | line search VI stationnaire | échec |
| `site_02_k_base / bouss_tri_irregular_drain_001` | matrice drainage/K | 13214 | base | 0.01 | triangulaire contraint | line search VI stationnaire | échec |
| `site_02_k_high / bouss_tri_irregular_drain_00` | matrice drainage/K | 13260 | high | 0 | triangulaire contraint | line search VI stationnaire | échec |
| `site_02_k_high / bouss_tri_irregular_drain_001` | matrice drainage/K | 13230 | high | 0.01 | triangulaire contraint | line search VI stationnaire | échec |
| `site_02_natural_network_site_candidates / bouss_unstructured_same_mesh` | candidats réseau | 13244 | base/naturel | défaut scénario | triangulaire contraint | line search régularisé stationnaire | échec |
| `headwater_100km2_outlet_2 / bouss_unstructured_same_mesh` | candidats réseau | 4216 | naturel | défaut scénario | triangulaire contraint | max iterations régularisé stationnaire | échec |
| `site_01_k10_natural / bouss_candidate` | sensibilité PETSc VI | 1250 | K x10 | défaut scénario | triangulaire contraint | line search VI stationnaire | échec |
| `site_01_k10_regularized_petsc / bouss_candidate` | sensibilité PETSc VI | 1250 | K x10 | défaut scénario | triangulaire contraint | max iterations transitoire après stationnaire réussi | échec plus tard |

Observation additionnelle dans les scratchs cachés :
`site_01_k_base / bouss_tri_uniform_rivers_drain_00` présente aussi un échec VI
stationnaire par line search, avec un résidu d'environ `6.71e-4`. Il n'était pas
dans le premier inventaire des cas en échec parce que les métriques directes
same-mesh ne l'utilisaient pas comme ligne de comparaison principale.

## Méthodes testées

Une matrice bas niveau ciblée a été lancée avec :

- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_method_matrix.py` ;
- les configs TOML générées existantes et les dossiers
  `mesh/mesh_catchment_bundle` existants ;
- des appels directs aux runtimes, pas le workflow launcher complet ;
- les valeurs homogènes `K` et `Sy` lues dans chaque TOML généré ;
- la recharge synthétique moyenne convertie de `mm/day` vers `m/s` ;
- la conductance de drainage cible lue dans chaque TOML généré ;
- `runtime_max_iterations = 240`, `runtime_tol_residual_inf = 1e-6`,
  `runtime_tol_state_update_inf = 1e-6`, `regularization_radius = 0.05`.

Cette matrice reproduit les échecs VI directs compacts de `site_01_k_high` et
l'échec PETSc régularisé de `site_02_network`. Elle révèle aussi une divergence
version/chemin : avec le code courant, le VI direct bas niveau converge pour
`site_02_k_low / bouss_tri_irregular_drain_00`, alors que l'ancien artefact
échouait. L'ancien résidu est reproduit par `petsc_regularized_then_vi`; ce cas
est donc conservé comme signal de sensibilité au chemin plutôt que comme échec VI
direct du code courant.

### 1. Newton/SNES stationnaire direct

Les solveurs stationnaires PETSc directs sont le chemin d'échec des cas naturels
difficiles. Les échecs VI obstacle rapportent systématiquement
`SNES_DIVERGED_LINE_SEARCH`. Les échecs PETSc régularisés stationnaires observés
dans les artefacts de candidats réseau rapportent soit `SNES_DIVERGED_LINE_SEARCH`,
soit `SNES_DIVERGED_MAX_IT`.

### 2. `regularized_partition`

Résultats observés :

- `petsc_partition_snes` peut échouer en stationnaire sur les candidats réseau
  (`site_02_natural_network_site_candidates`, résidu d'environ `8.0e-5` ;
  `headwater_100km2_outlet_2`, résidu d'environ `1.63e-4`).
- `site_01_k10_regularized_petsc` atteint un bon résidu stationnaire
  (`~1.35e-8`) mais échoue ensuite en transitoire avec `SNES_DIVERGED_MAX_IT`.
- `site_01_k10_regularized_scipy_sparse` est terminé dans les artefacts de
  sensibilité existants.

Interprétation : la régularisation est utile comme candidate d'initialisation,
mais le runtime PETSc partition peut lui-même atteindre des limites stationnaires
de recherche linéaire ou de nombre maximal d'itérations sur certains maillages naturels.

### 3. VI obstacle stationnaire

La matrice naturelle principalement en échec utilise `petsc_vi_obstacle_snes`
avec `surface_interaction_model = "vi_obstacle"`. Les cas en échec n'ont aucun
diagnostic de sous-pas transitoire. Les cas voisins convergés terminent 24
périodes sans violation de borne VI dans les résumés exportés.

### 4. Complémentarité/mixte

L'artefact de sensibilité existant `site_01_k10_complementarity_petsc` est terminé
et donne une RMSE de charge finale presque identique à `regularized` scipy sparse
et TS VI (`~14.70 m`). Cela montre que la complémentarité peut être viable sur au
moins un cas naturel K10, mais ne prouve pas encore qu'elle soit un meilleur
initialiseur que la régularisation.

### 5. Regularized -> VI

Ce chemin a été exécuté dans le script d'investigation avec des pré-initialisations
PETSc régularisé et scipy sparse régularisé. Résultat : non robuste. Sur
`site_01_k_high`, le solveur régularisé de pré-initialisation peut converger, mais le VI
cible qui suit échoue encore avec `SNES_DIVERGED_LINE_SEARCH`. Sur le contrôle
`drain_001`, le VI direct converge mais `petsc_regularized_then_vi` échoue. Les
solveurs régularisés sont donc utiles pour le diagnostic et comme champs IC
candidats, mais ne doivent pas être promus comme solution de repli principale sans stratégie
de chemin supplémentaire.

### 6. Pseudo-transitoire VI

Un prototype a été testé dans le script d'investigation en appelant de manière
répétée `petsc_vi_obstacle.solve_transient_step()` avec forçage stationnaire
constant et un calendrier de pseudo-temps croissant :

```text
dtau = 1, 3, 10, 30, 100, 365, 3650 days
```

Après ce chemin pseudo-transitoire, un solveur VI stationnaire cible final est
lancé. Cela réussit sur les variantes compactes `site_01_k_high` et sur le cas de
sensibilité au chemin `site_02_k_low` avec le code courant. Cela échoue sur
`site_02_network`.

### 7. Continuation recharge/drainage

La continuation recharge a été testée avec des lambdas fixes :

```text
lambda = 0, 0.1, 0.25, 0.5, 0.75, 1.0
```

Elle n'améliore pas les cas difficiles testés. Elle échoue souvent immédiatement
ou sur une recherche linéaire proche de la convergence.

La continuation drainage a été testée depuis une conductance facile
`0.01 m2/s` vers la cible. Elle réussit sur les cas compacts
`site_01_k_high / drain_00` et `site_01_k_high / drain_01`, ainsi que sur le
chemin `site_02_k_low / drain_00` avec le code courant. Elle échoue sur
`site_02_network` au stade intermédiaire `0.01 m2/s`.

### 8. Régularisation contrôlée

Aucune nouvelle régularisation contrôlée des seuils n'a été introduite. La
première étape recommandée est d'utiliser le `regularization_radius` existant
uniquement comme chemin d'initialisation, puis de résoudre la formulation VI
cible.

## Options PETSc utilisées

D'après l'inspection du code et les diagnostics exportés :

| runtime | non linéaire | KSP | PC | shift | notes |
|---|---|---|---|---|---|
| `petsc_vi_obstacle_snes` | SNESVI `vinewtonrsls` | `preonly` | `lu` | non nul, `1e-10` dans le code | résidu VI projeté ; bornes issues de `z_bottom/z_top`, borne supérieure relaxée quand le drainage est positif |
| `petsc_ts_vi_obstacle` | TS `beuler` + SNESVI `vinewtonrsls` | `preonly` | `lu` | non nul, `1e-10` dans le code | transitoire uniquement ; défaut `ts_vi_steps_per_period = 4` |
| `petsc_partition_snes` | SNES `newtonls`, recherche linéaire `bt` | `preonly` dans le chemin direct courant | `lu` | non nul, `1e-10` dans le code | partition régularisée |
| `petsc_mixed_complementarity_snes` | SNES `newtonls`, équations Fischer-Burmeister | `preonly` | `lu` | non nul, `1e-10` dans le code | mixte `h, q_ex, q_dry` |

Les résumés VI terminés exportés ont souvent `factor_shift_type = null`, parce
que les diagnostics précédents ne persistaient pas de manière fiable la requête
PETSc du factor shift. Le chemin de code positionne bien ce shift.

## Tableau de synthèse des résultats

Résultats complets exploitables par machine :

- `docs/_dev_notes/diagnostics/boussinesq_stationary_method_matrix_combined/stationary_method_matrix.csv` ;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_method_matrix_combined/stationary_method_matrix.json`.

Matrice compacte de succès issue de la relance stationnaire ciblée :

| méthode | `s01 high d00` | `s01 high d01` | `s01 high d001` | `s02 low d00` | `s02 network` |
|---|---:|---:|---:|---:|---:|
| `vi_obstacle` | échec `1.12e-3` | échec `1.65e-4` | ok `1.06e-9` | ok `9.26e-7` | échec `9.27` |
| `petsc_regularized` | ok `3.58e-7` | ok `5.11e-8` | ok `1.38e-9` | ok `5.79e-8` | échec `8.00e-5` |
| `scipy_sparse_regularized` | ok `1.59e-7` | ok `4.21e-7` | échec `1.50e-3` | non lancé | échec `6.57e-4` |
| `complementarity` | échec `1.00e-2` | échec `1.55e-3` | échec `3.49e-4` | non lancé | non lancé |
| `petsc_regularized_then_vi` | échec `6.85e-4` | échec `1.71e-4` | échec `1.66e-4` | échec `1.87` | échec au solveur de pré-initialisation |
| `scipy_sparse_regularized_then_vi` | échec `5.75e-4` | échec `1.67e-4` | échec au solveur de pré-initialisation | non lancé | non lancé |
| `complementarity_then_vi` | échec au solveur de pré-initialisation | échec au solveur de pré-initialisation | échec au solveur de pré-initialisation | non lancé | non lancé |
| `pseudo_transient_vi_then_steady_vi` | ok `1.26e-7` | ok `2.25e-8` | ok `6.79e-8` | ok `4.50e-7` | échec `9.30` |
| `recharge_continuation_vi` | échec `9.62e-3` | échec `1.34e-6` | échec `3.19e-8` | non lancé | échec `9.28` |
| `drainage_continuation_vi` | ok `3.90e-10` | ok `5.30e-9` | ok `1.06e-9` | ok `3.10e-7` | échec `1.39e-1` |

Lignes détaillées sélectionnées :

| cas | méthode | convergé | résidu | raison | iter | top actif | bottom actif | IC utilisable | note |
|---|---|---|---:|---|---:|---:|---:|---|---|
| `site_01_k_high / drain_00` | `vi_obstacle` | non | `1.122e-3` | recherche linéaire | 27 | 0 | 820 | non | reproduit l'échec connu |
| `site_01_k_high / drain_00` | `petsc_regularized` | oui | `3.576e-7` | convergé | 139 | 10 | 85 | oui, régularisé seulement | pas la VI cible |
| `site_01_k_high / drain_00` | `petsc_regularized_then_vi` | non | `6.846e-4` | recherche linéaire | 6 | 0 | 820 | non | la pré-initialisation ne corrige pas la VI |
| `site_01_k_high / drain_00` | `pseudo_transient_vi_then_steady_vi` | oui | `1.256e-7` | convergé | 0 final | 32 | 72 | oui | meilleure récupération compacte |
| `site_01_k_high / drain_00` | `drainage_continuation_vi` | oui | `3.896e-10` | convergé | 12 | 32 | 72 | oui | meilleure récupération compacte |
| `site_01_k_high / drain_001` | `vi_obstacle` | oui | `1.059e-9` | convergé | 31 | 0 | 67 | oui | le contrôle direct réussit |
| `site_01_k_high / drain_001` | `petsc_regularized_then_vi` | non | `1.658e-4` | recherche linéaire | 8 | 0 | 820 | non | la pré-initialisation régularisée dégrade le chemin |
| `site_02_k_low / drain_00` | `vi_obstacle` | oui | `9.257e-7` | convergé | 22 | 1599 | 19 | oui | le chemin direct du code courant diffère de l'ancien artefact |
| `site_02_k_low / drain_00` | `petsc_regularized_then_vi` | non | `1.866` | recherche linéaire | 2 | 2 | 12855 | non | reproduit l'ancien résidu d'échec |
| `site_02_network` | `petsc_regularized` | non | `7.999e-5` | recherche linéaire | 111 | 0 | 114 | non | reproduit l'échec régularisé connu |
| `site_02_network` | `vi_obstacle` | non | `9.275` | recherche linéaire | 4 | 2 | 12865 | non | VI direct beaucoup plus mauvais |
| `site_02_network` | `pseudo_transient_vi_then_steady_vi` | non | `9.301` | recherche linéaire | 20 | 2528 | 3 | non | le pseudo-pas échoue |
| `site_02_network` | `drainage_continuation_vi` | non | `1.391e-1` | recherche linéaire | 7 | 0 | 12865 | non | échec au stade de drainage facile |

## Résultats détaillés

### Site 01

`site_01_k_base` est un contrôle utile : les variantes VI obstacle triangulaires
contraintes avec drain `0`, `0.01` et `0.1` convergent toutes dans la matrice
same-mesh directe exportée. `site_01_k_high` est le premier cas compact difficile.
Il échoue à drain `0` et `0.1`, mais converge à `0.01`. C'est donc le premier
cas cible pour la continuation drainage et l'initialisation pseudo-transitoire.

La nouvelle matrice précise cette interprétation. Pour `site_01_k_high`, les
solveurs PETSc régularisé et scipy sparse directs convergent, mais utiliser ces
charges comme pré-initialisation VI après clipping échoue encore. Même sur le contrôle
convergé `drain_001`, `petsc_regularized_then_vi` échoue alors que le VI direct
réussit. Le problème n'est donc pas seulement de « trouver n'importe quel champ
stationnaire lisse » ; le chemin de Newton vers l'ensemble actif VI cible compte.

L'ensemble actif des cas VI K high en échec est dominé par la violation ou
l'activation de l'obstacle inférieur : environ 820 cellules sur 1250 sont
actives au fond ou sous le fond dans l'état diagnostiqué en échec. Les cellules
au plus fort résidu pour `site_01_k_high / drain_00 / vi_obstacle` sont des
cellules libres avec une épaisseur saturée complète, par exemple :

| cellule | aire m2 | h-z_top m | h-z_bottom m | résidu | état |
|---:|---:|---:|---:|---:|---|
| 520 | 11394 | `-9.19` | `20.81` | `-1.12e-3` | libre |
| 63 | 14300 | `-2.21` | `27.79` | `-9.29e-4` | libre |
| 335 | 11702 | `-2.25` | `27.75` | `-5.86e-4` | libre |

Cela est cohérent avec un problème global d'ensemble actif ou de conditionnement,
pas seulement avec une petite cellule isolée.

### Site 02

Les artefacts existants montrent que `site_02` est beaucoup plus difficile. Même
K low échouait historiquement à drain `0` et `0.1`, et seul le drain intermédiaire
`0.01` convergeait dans la matrice triangulaire contrainte. À K base et K high,
le drain `0.01` échouait aussi. Les états stationnaires en échec ont environ
12 800 cellules actives au fond sur environ 13 200 cellules. Le plus fort résidu
observé est `site_02_k_high / bouss_tri_irregular_drain_00`, avec un résidu
d'environ `33.7`.

La relance ciblée a trouvé une divergence importante : avec le code courant et
un appel bas niveau direct depuis `z_top`, `site_02_k_low / drain_00` converge.
En revanche, `petsc_regularized_then_vi` échoue avec un résidu `1.866`, ce qui
correspond à l'ordre de grandeur de l'ancien échec. L'ancien échec reste donc
utile, mais doit être utilisé comme régression de sensibilité au chemin plutôt
que comme preuve que le VI direct courant ne peut pas converger.

L'interprétation est que `site_02` combine activation quasi sèche de l'obstacle
inférieur, grand nombre de cellules, irrégularité de maillage naturel et raideur
liée à K/drainage. Il ne doit pas être le premier cas de développement pour un
nouvel algorithme ; il doit servir de cas de stress après validation du chemin
sur `site_01`.

### Candidats réseau

Deux résumés cachés dans les scratchs montrent des échecs stationnaires avec
`regularized_partition`, et non avec VI :

- `site_02_natural_network_site_candidates / bouss_unstructured_same_mesh` ;
- `headwater_100km2_outlet_2_natural_network_site_candidates / bouss_unstructured_same_mesh`.

C'est important parce que la régularisation seule n'est pas un remède universel.
Elle peut aider comme pré-initialisation, mais nécessite aussi des diagnostics et une
logique de solution de repli.

La relance ciblée reproduit l'échec PETSc régularisé `site_02_network` :
`7.999e-5`, 111 itérations, `SNES_DIVERGED_LINE_SEARCH`. Sur le même cas, le VI
direct échoue avec un résidu `9.275`, le pseudo-transitoire VI échoue au premier
pseudo-pas, la continuation recharge échoue à lambda `0`, et la continuation
drainage échoue au premier stade de drainage facile (`0.01 m2/s`) avec un résidu
`0.139`.

Les fichiers de diagnostic montrent deux formes d'échec différentes sur le même
maillage :

| méthode | top actif | bottom actif | cellules sous le fond | violation basse max | interprétation |
|---|---:|---:|---:|---:|---|
| `petsc_regularized` | 8386 | 114 | 113 | `32.3 m` | le chemin régularisé bloque avec beaucoup de cellules près du toit et une petite queue sèche |
| `vi_obstacle` | 2 | 12865 | 12865 | `69.6 m` | la recherche linéaire VI cible s'effondre vers un échec dominé par l'obstacle inférieur |

Les cellules de plus fort résidu pour le VI réseau incluent deux cellules
au-dessus de l'obstacle supérieur avec de forts résidus positifs, puis de
nombreuses cellules libres avec des résidus modérés. Par exemple, la cellule 3855
a `h-z_top = 13.83 m` et un résidu `9.27`, tandis que la cellule 440 a
`h-z_top = 11.73 m` et un résidu `8.02`.

### Sensibilité K10

Les artefacts de sensibilité K10 constituent l'indice le plus fort en faveur d'un
initialiseur par étapes :

- le VI direct K10 échoue en recherche linéaire stationnaire ;
- `regularized` scipy sparse termine ;
- `complementarity` PETSc termine ;
- TS VI PETSc termine ;
- `regularized` PETSc obtient un bon résidu stationnaire mais échoue ensuite en
  transitoire.

Les RMSE finales des méthodes K10 terminées sont presque identiques. Le choix de
méthode relève donc davantage de la robustesse et de l'initialisation que d'une
modification du résultat scientifique cible.

## Implémentation de diagnostic ajoutée

Nouveau fichier :

- `hydromodpy/solver/boussinesq/runtimes/stationary_failure_diagnostics.py`

Fichiers mis à jour :

- `hydromodpy/core/solver_diagnostics.py` ;
- `hydromodpy/solver/boussinesq/drivers/steady.py` ;
- `tests/unit/solver/test_boussinesq_stationary_failure_diagnostics.py`.

En cas d'échec stationnaire, `run_steady_runtime()` écrit maintenant :

- `stationary_failure_summary.json` ;
- `stationary_failure_cells_top_residual.csv` ;
- `stationary_failure_active_set_summary.csv` ;
- `stationary_failure_field_stats.json`.

L'écrivain enregistre les métadonnées SNES/KSP/PETSc disponibles, le résidu
final, le résidu projeté par rapport aux bornes physiques, les violations
charge/fond/toit, les comptes d'états actifs, les statistiques K/aire, les
quantiles d'épaisseur saturée/transmissivité, le drainage et les totaux de
réactions surface/fond reconstruits. Le CSV par cellule liste les cellules au
plus fort résidu avec l'identifiant de cellule, le centroïde, l'aire, K, les
bornes z, h, les résidus, l'état actif, l'épaisseur, la transmissivité, le débit
de drainage, les réactions et le nombre de voisins.

Les champs indisponibles sans refactorisation plus large sont laissés vides/null,
comme demandé. Le point d'accroche est appliqué au mieux pour le diagnostic uniquement ; il ne
modifie pas le succès du solveur et ne masque pas la raison de divergence
originale.

## Interprétation hydrologique

Le mode d'échec principal observé est la dominance de l'obstacle inférieur.
Beaucoup de cas en échec ont la plupart des cellules à ou près de `z_bottom`.
Cela pointe vers un problème stationnaire dur de séchage/réhumidification, où
Newton ne trouve pas de pas de descente après changement de l'ensemble actif.

Le drainage reste important. `site_01_k_high` réussit à drain `0.01` mais échoue
à `0` et `0.1`, ce qui suggère un chemin numériquement favorable étroit entre
l'obstacle dur et le drainage explicite fort. Sur `site_02`, ce pont ne suffit
pas à K base/high.

Un K élevé augmente la raideur parce que les flux internes transmissifs deviennent
plus grands. La qualité et le support du maillage comptent aussi : l'analyse
same-mesh précédente a montré que passer de triangles contraints
géologie/rivières à des triangles quasi uniformes river-only peut changer la RMSE
d'un ordre de grandeur, pour Boussinesq comme pour MF6.

## Chemin d'implémentation recommandé

P0 :

1. Conserver les nouveaux diagnostics d'échec stationnaire et relancer un cas
   naturel en échec depuis WSL/Linux pour persister de vrais fichiers
   `stationary_failure_*`.
2. Implémenter l'initialisation pseudo-transitoire VI comme option expérimentale
   explicite, suivie d'un contrôle final du résidu et des bornes de la VI
   stationnaire cible.
3. Implémenter la continuation drainage comme option expérimentale explicite, en
   partant d'une conductance facile comme `0.01 m2/s` et en terminant à la
   conductance cible.
4. Appliquer d'abord les deux chemins à `site_01_k_high / drain 0` et
   `site_01_k_high / drain 0.1`.

P1 :

1. Conserver `regularized_partition` comme candidat d'initialisation et chemin de
   diagnostic, mais ne pas supposer que `regularized -> VI` est une solution de repli
   robuste. La nouvelle matrice montre des échecs répétés de cette séquence.
2. Ajouter une bissection adaptative à la continuation drainage avant d'essayer
   une continuation K ou recharge plus large.
3. Ajouter des diagnostics CSV par étape pour les chemins pseudo-transitoire et
   continuation : étape pseudo/continuation, valeur du paramètre, résidu,
   comptes actifs, violations de bornes, raison SNES.

P2 :

1. Ajouter une continuation K pour les cas K high.
2. Évaluer la complémentarité comme initialiseur uniquement si le
   pseudo-transitoire et la continuation drainage ne couvrent pas les cas
   compacts.
3. Ajouter une régularisation contrôlée des seuils uniquement comme logique
   temporaire d'initialisation, jamais comme modèle cible final non documenté.

## Risques restants

- Une solution régularisée n'est pas la solution VI cible finale sauf si elle est
  suivie par un solveur VI cible.
- Les chemins de continuation et pseudo-transitoires peuvent être dépendants du
  chemin ; le résidu final cible et l'ensemble actif doivent toujours être
  vérifiés.
- PETSc régularisé peut aussi échouer en mode stationnaire sur les candidats
  réseau.
- La complémentarité peut être plus coûteuse et plus mal conditionnée sur les cas
  plus grands.
- L'environnement Windows courant peut inspecter les artefacts et lancer les
  tests unitaires, mais les relances naturelles PETSc nécessitent WSL/Linux.
- Les anciens artefacts de workflow complet n'incluent pas de fichiers
  cellwise top-residual. Les relances bas niveau ciblées incluent maintenant des
  fichiers `stationary_failure_*`, mais elles ne remplacent pas une relance du
  chemin launcher complet après implémentation d'un initialiseur de production.

## Commandes exécutées

Inspection du code et des artefacts :

```powershell
rg "steady_state_initial" -n hydromodpy tests examples docs
rg "runtime_backend|surface_interaction_model|steady_state" -n examples/projects/10_testbed_workflow/boussinesq/natural_geology_k docs/_dev_notes
rg --hidden --no-ignore --files examples/projects/10_testbed_workflow/outputs -g "*_boussinesq_summary.json"
rg --files examples/projects/10_testbed_workflow/outputs -g "*vi_obstacle*diagnostics*.csv" -g "*vi_obstacle*_summary.json"
Get-Content hydromodpy/solver/boussinesq/boussinesq.py
Get-Content hydromodpy/solver/boussinesq/drivers/steady.py
Get-Content hydromodpy/solver/boussinesq/runtimes/petsc_vi_obstacle.py
Get-Content hydromodpy/solver/boussinesq/runtimes/petsc_ts_vi_obstacle.py
Get-Content hydromodpy/solver/boussinesq/runtimes/petsc_partition.py
Get-Content hydromodpy/solver/boussinesq/runtimes/petsc_mixed.py
Get-Content hydromodpy/solver/steady_initial_conditions.py
```

Vérification de disponibilité WSL/PETSc :

```powershell
wsl -e bash -lc 'uname -a'
wsl -e bash -lc 'test -x /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python --version || true'
@'
import petsc4py
print("petsc4py ok")
'@ | wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -"
```

Matrice stationnaire ciblée :

```powershell
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_method_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method vi_obstacle --method petsc_regularized --method scipy_sparse_regularized --method complementarity --method petsc_regularized_then_vi --method pseudo_transient_vi_then_steady_vi --method recharge_continuation_vi --method drainage_continuation_vi"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_method_matrix.py"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_method_matrix.py --case site_02_k_low__bouss_tri_irregular_drain_00 --method vi_obstacle --method petsc_regularized --method petsc_regularized_then_vi --method pseudo_transient_vi_then_steady_vi --method drainage_continuation_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_method_matrix_site02_low"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_method_matrix.py --case site_02_network__bouss_unstructured_same_mesh --method petsc_regularized --method scipy_sparse_regularized --method vi_obstacle --method pseudo_transient_vi_then_steady_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_method_matrix_network_site02"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_method_matrix.py --case site_02_network__bouss_unstructured_same_mesh --method drainage_continuation_vi --method recharge_continuation_vi --method petsc_regularized_then_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_method_matrix_network_site02_continuation"
```

Tests exécutés :

```powershell
python -m pytest -o addopts='' tests/unit/solver/test_boussinesq_stationary_failure_diagnostics.py -q
python -m pytest -o addopts='' tests/unit/solver/test_petsc_vi_obstacle.py -q
python -m pytest -o addopts='' tests/unit/solver/test_petsc_ts_vi_obstacle.py -q
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest -o addopts='' tests/unit/solver/test_petsc_vi_obstacle.py -q"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest -o addopts='' tests/unit/solver/test_petsc_ts_vi_obstacle.py -q"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest -o addopts='' tests/unit/solver/test_boussinesq_stationary_failure_diagnostics.py -q"
python -m ruff format hydromodpy/core/solver_diagnostics.py hydromodpy/solver/boussinesq/drivers/steady.py hydromodpy/solver/boussinesq/runtimes/stationary_failure_diagnostics.py tests/unit/solver/test_boussinesq_stationary_failure_diagnostics.py
python -m ruff check hydromodpy/core/solver_diagnostics.py hydromodpy/solver/boussinesq/drivers/steady.py hydromodpy/solver/boussinesq/runtimes/stationary_failure_diagnostics.py tests/unit/solver/test_boussinesq_stationary_failure_diagnostics.py
python -m ruff format --check hydromodpy/core/solver_diagnostics.py hydromodpy/solver/boussinesq/drivers/steady.py hydromodpy/solver/boussinesq/runtimes/stationary_failure_diagnostics.py tests/unit/solver/test_boussinesq_stationary_failure_diagnostics.py
git diff --check
```

Résultat :

```text
Windows:
- diagnostics stationnaires : 1 passed
- PETSc VI obstacle : 3 passed, 3 skipped
- PETSc TS VI obstacle : 4 skipped

WSL/PETSc:
- PETSc VI obstacle : 6 passed
- PETSc TS VI obstacle : 4 passed
- diagnostics stationnaires : 1 passed

Lint/format:
- ruff format appliqué aux fichiers Python modifiés
- ruff check : all checks passed
- ruff format --check : 4 files already formatted
- git diff --check : pas d'erreur d'espaces
```

## Fichiers de sortie

Produits ou modifiés dans cette passe :

- `docs/_dev_notes/boussinesq_stationary_robustness_investigation.md` ;
- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_method_matrix.py` ;
- `hydromodpy/solver/boussinesq/runtimes/stationary_failure_diagnostics.py` ;
- `hydromodpy/solver/boussinesq/drivers/steady.py` ;
- `hydromodpy/core/solver_diagnostics.py` ;
- `tests/unit/solver/test_boussinesq_stationary_failure_diagnostics.py`.

Sorties de matrice ciblée :

- `docs/_dev_notes/diagnostics/boussinesq_stationary_method_matrix/stationary_method_matrix.csv` ;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_method_matrix_site02_low/stationary_method_matrix.csv` ;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_method_matrix_network_site02/stationary_method_matrix.csv` ;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_method_matrix_network_site02_continuation/stationary_method_matrix.csv` ;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_method_matrix_combined/stationary_method_matrix.csv` ;
- fichiers `.json` correspondants dans les mêmes dossiers ;
- dossiers par échec sous chaque dossier de sortie de matrice, par exemple
  `docs/_dev_notes/diagnostics/boussinesq_stationary_method_matrix/diagnostics/site_01_k_high__bouss_tri_irregular_drain_00/vi_obstacle/`.

Les futures relances naturelles produiront, dans chaque dossier de solveur
Boussinesq en échec :

- `stationary_failure_summary.json` ;
- `stationary_failure_cells_top_residual.csv` ;
- `stationary_failure_active_set_summary.csv` ;
- `stationary_failure_field_stats.json`.

Artefacts existants utilisés :

- `*/_boussinesq_summary.json` ;
- `*__vi_obstacle_runtime_summary.json` ;
- `*__vi_obstacle_period_diagnostics.csv` ;
- `*__vi_obstacle_substep_diagnostics.csv` ;
- `*__ts_vi_obstacle_runtime_summary.json` ;
- `examples/projects/10_testbed_workflow/outputs/boussinesq_natural_drainage_k_mesh_matrix_testbed/web_synthesis/same_mesh_direct_metrics.csv`.

## Recommandations finales

Recommandation P0 : ne pas commencer par régler les sous-pas transitoires.
Conserver les diagnostics stationnaires, puis implémenter le pseudo-transitoire
VI et la continuation drainage comme initialiseurs stationnaires expérimentaux
explicites, avec un contrôle final par VI stationnaire cible.

Recommandation P1 : conserver `regularized_partition` comme diagnostic et
générateur possible de champ de charge candidat, mais ne pas s'appuyer sur
`regularized -> VI` comme solution de repli par défaut. La matrice ciblée montre que ce
chemin échoue de manière répétée sur les cas compacts.

Recommandation P2 : évaluer la complémentarité comme initialiseur de repli
uniquement après implémentation du pseudo-transitoire et de la continuation
drainage avec contrôle adaptatif des pas, et mesure sur `site_01_k_high`,
`site_01_k10` et un cas de stress `site_02`.

## Mise a jour 2026-05-15: bilan apres les tests `b_min = 0.10 m`

Une deuxieme passe ciblee a teste une option plus pragmatique que les
continuations vers le modele strict: conserver en permanence une epaisseur
saturee minimale de `0.10 m` dans le modele Boussinesq, puis verifier que le
champ stationnaire peut demarrer un court transitoire avec le meme modele
regularise.

Le rapport detaille correspondant est:

- `docs/_dev_notes/boussinesq_bmin010_drain_zero_test_report.md`.

La piste de charge imposee a l'exutoire a ete retiree du code et des rapports.
Elle avait ete testee comme condition aval experimentale, mais elle ne
recuperait pas les echecs principaux et degradant `site_02_network`; elle ne fait
donc plus partie du bilan recommande.

### Synthese des resultats `b_min = 0.10 m`

| cas | drainage | meilleur chemin | resultat | lecture |
|---|---:|---|---|---|
| `site_01_k_low` | 0 | VI direct | succes, residu `2.88e-9` | robuste |
| `site_01_k_base` | 0 | VI direct | succes, residu `1.72e-7` | robuste |
| `site_01_k_high` | 0 | VI direct | succes, residu `1.42e-8` | robuste |
| `site_02_k_low` | 0 | VI direct | succes, residu `1.62e-9` | robuste |
| `site_02_network` | scenario reseau | `TSPSEUDO -> VI` | succes, residu `6.65e-8` | TSPSEUDO indispensable |
| `site_01_k_base` uniforme rivieres | 0 | aucun | echec proche, residu `3.14e-4` | maillage/support defavorable |
| `site_02_k_base` | 0 | aucun | echec massif, residu `9.28` | drainage nul trop dur |
| `site_02_k_high` | 0 | aucun | echec massif, residu `33.7` | K fort + drainage nul trop raide |

Quand VI direct et `TSPSEUDO -> VI` convergent tous les deux, les champs de
charge sont pratiquement identiques. Sur `site_01_k_low`, la RMSE entre les deux
chemins est d'environ `1.0e-5 m`; sur `site_02_k_low`, elle est d'environ
`2.6e-7 m`. Cela suggere que le chemin numerique ne change pas le champ utile
tant qu'il converge vers le meme bassin.

Quand un chemin echoue, il echoue souvent vers un champ quasi sec global:
`site_02_k_base` et `site_02_k_high` gardent environ `12880` cellules actives au
fond ou sous le fond sur environ `13200` cellules. Ces echecs ne sont donc pas
des echecs "proches" qu'un simple ajout d'iterations ou de sous-pas devrait
resoudre.

### Role du drainage faible

Le contraste le plus operationnel concerne `site_02_k_base`:

| configuration | meilleur residu | probe transitoire | lecture |
|---|---:|---|---|
| `b_min=0.10 m`, `drain_0` | `9.28` | non | echec massif |
| `b_min=0.10 m`, `drain_0.01` | `4.75e-7` | oui | robuste |
| `b_min=0.10 m`, `drain_0.1` | `1.35e-7` | oui | robuste |

Le drainage nul reste donc utile comme stress test, mais il n'est pas le meilleur
choix si l'objectif prioritaire est une initialisation naturelle robuste.

### Bilan actualise

Le meilleur chemin pratique actuel est:

1. utiliser explicitement le modele regularise `b_min = 0.10 m`;
2. essayer d'abord le VI stationnaire direct;
3. si le VI direct echoue, essayer `TSPSEUDO -> VI` avec le meme `b_min`;
4. si `drain_0` echoue massivement, tester un drainage explicite faible
   (`0.01 m2/s`) plutot que d'empiler des iterations;
5. valider systematiquement par un probe transitoire utilisant le meme
   `b_min`.

Ce bilan change legerement les recommandations initiales. Le pseudo-transitoire
reste utile, mais il ne doit pas etre impose systematiquement: sur plusieurs cas
compacts, le VI direct converge alors que TSPSEUDO tombe dans un mauvais bassin.
La vraie option candidate production est plutot `b_min=0.10 m` comme
regularisation assumee, avec `TSPSEUDO -> VI` en secours et drainage faible pour
les cas naturels `site_02` les plus raides.

## Mise a jour 2026-05-15: equilibre sec et interpretation de `b_min`

Une passe complementaire a isole le cas recharge nulle. Elle ajoute un helper
experimental de detection de l'equilibre sec, un court-circuit stationnaire pour
les cas secs evidents sans entree positive, et un probe synthetique des flux de
film induits par un plancher d'epaisseur effective:

- `hydromodpy/solver/boussinesq/runtimes/dry_equilibrium.py`;
- `hydromodpy/solver/boussinesq/runtimes/petsc_vi_obstacle.py`;
- `tests/unit/solver/test_boussinesq_dry_equilibrium.py`;
- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_dry_equilibrium_probe.py`;
- `docs/_dev_notes/boussinesq_dry_equilibrium_and_bmin.md`.

Le point mathematique important est que `h = z_bottom` est une solution VI
admissible en recharge nulle si le residu sur la borne inferieure respecte
`R >= 0`. Ce n'est pas une solution classique `R = 0` partout. Les nouveaux
diagnostics permettent donc de distinguer un aquifere sec admissible d'un mauvais
bassin quasi sec non convergent.

La distinction `b_min` est maintenant explicite:

- `physical_saturated_thickness` decrit l'etat hydrologique reel;
- `effective_saturated_thickness` decrit la regularisation numerique utilisee
  pour la transmissivite.

Sur fond plat, `b_min = 0.10 m` ne cree pas de flux si `h = z_bottom` est
constant. Sur fond incline, il cree un flux de film proportionnel a
`K * b_min * pente_h`. Dans le probe synthetique avec `K = 1e-5 m/s`,
`b_min = 0.10 m` produit environ `1e-7 m3/s` pour une pente `0.1 m/m` et
`1e-6 m3/s` pour une pente `1 m/m`.

Ce resultat ne disqualifie pas `b_min = 0.10 m` comme regularisation robuste, mais
il interdit de le presenter comme hydrologiquement neutre sans quantifier ces
flux sur les maillages naturels. Les echecs `site_02_k_base/high / drain_0`
restent des mauvais bassins quasi secs: beaucoup de cellules sont au fond, mais
le residu VI reste trop grand pour etre lu comme un equilibre sec admissible.

## Mise a jour 2026-05-15: bilan apres retrait de la borne `z_bottom + b_min`

La variante qui deplacait la borne basse VI vers `z_bottom + b_min` a ete
retiree des scripts d'investigation. On conserve donc la contrainte physique:

```text
h >= z_bottom
```

Le bilan reste que le plancher `b_min = 0.10 m` doit etre compris comme une
regularisation numerique de la transmissivite effective, pas comme une epaisseur
saturee physique minimale. Les diagnostics doivent continuer a distinguer:

- `physical_saturated_thickness`, qui peut etre nulle;
- `effective_saturated_thickness`, qui peut etre bornee par `b_min`.

Il n'existe pas encore de strategie qui fonctionne systematiquement sur tous les
cas naturels testes. Le meilleur chemin pratique actuel est conditionnel:

| situation | chemin le plus robuste observe | statut |
|---|---|---|
| cas compacts ou moderes (`site_01`, `site_02_k_low`) | VI direct avec `b_min=0.10 m` | robuste sur les cas testes |
| `site_02_network` | `b_min=0.10 m` avec `TSPSEUDO -> VI` | robuste sur ce cas precis |
| `site_02_k_base/high` avec `drain_0` | aucun chemin teste ne converge proprement | echec massif |
| `site_02_k_base` avec drainage faible | `b_min=0.10 m` et drainage explicite `0.01` ou `0.1 m2/s` | robuste sur les tests disponibles |

La conclusion operationnelle est donc:

1. garder `h >= z_bottom`;
2. utiliser `b_min=0.10 m` comme option explicite de robustesse numerique;
3. essayer d'abord le VI direct;
4. essayer `TSPSEUDO -> VI` seulement si le VI direct echoue;
5. si `drain_0` donne un echec massif sur `site_02`, tester un drainage faible
   plutot que d'augmenter seulement les iterations ou les sous-pas;
6. continuer a documenter les echecs comme des echecs, car aucune sequence
   actuelle ne couvre tous les couples site/K/drainage.

## Mise a jour 2026-05-15: essai d'un champ MODFLOW 6 comme warm start

Une passe supplementaire a teste l'idee d'utiliser un champ MODFLOW 6 comme
condition initiale Boussinesq, avec le modele Boussinesq regularise
`b_min = 0.10 m`. Le rapport detaille est:

- `docs/_dev_notes/boussinesq_mf6_warm_start_initial_condition_probe.md`.

Les artefacts MF6 disponibles ne conservent pas clairement le champ permanent
auxiliaire comme fichier directement reutilisable. Les tests utilisent donc le
dernier champ de charge MF6 stocke dans le Zarr de reference quand
`_steady_state_initial_conditions.npz` est absent. Ce point limite la conclusion:
l'essai teste un warm start MF6 de reference disponible, pas encore une vraie
interface production "MF6 permanent -> Boussinesq".

Resultat principal: la strategie n'est pas systematique.

| cas | champ MF6 direct comme base transitoire `b_min=0.10` | MF6 -> VI `b_min=0.10` | lecture |
|---|---:|---:|---|
| `site_01_k_high / drain_0` | oui | oui, residu `4.70e-7` | utile mais pas meilleur que `b_min` direct |
| `site_01_k_high / drain_0.1` | oui | non, residu `1.65e-4` | demarrage transitoire possible, stationnaire non |
| `site_02_k_low / drain_0` | oui | non, residu `1.87` | le VI final retombe dans le mauvais bassin |
| `site_02_k_low / drain_0.01` | oui | non, residu `0.139` | warm start transitoire seulement |
| `site_02_k_base / drain_0` | non | non, residu `9.32` | echec massif inchange |
| `site_02_k_base / drain_0.01` | non | non, residu `0.139` | pas robuste |
| `site_02_k_base / drain_0.1` | non | non, residu `1.39` | pas robuste |
| `site_02_k_high / drain_0` | non | non, residu `36.7` | echec massif |
| `site_02_network` | non | non, residu `9.32` | moins bon que `b_min=0.10 + TSPSEUDO -> VI` |

Conclusion actualisee: MODFLOW 6 peut fournir un champ initial utile pour
certains probes transitoires, mais il ne corrige pas le probleme stationnaire
Boussinesq dominant. Sur les cas difficiles, le solveur VI final retombe encore
dans un etat quasi sec non admissible. La strategie ne doit donc pas etre promue
comme solution robuste principale.

Si cette piste est poursuivie, il faut d'abord persister explicitement le champ
MF6 stationnaire auxiliaire, documenter la projection MF6 -> Boussinesq et
continuer a separer deux validations: demarrage transitoire direct et controle
stationnaire Boussinesq final.

## Mise a jour 2026-05-15: fermeture de surface DRN-like avec `b_min = 0.10 m`

Une nouvelle passe a teste une fermeture de surface plus proche de MODFLOW 6:
conserver la borne basse physique `h >= z_bottom`, relacher la borne superieure
quand une conductance de drainage est positive, et utiliser:

```text
q_drain = C max(h - z_top, 0)
```

avec `b_min = 0.10 m` dans la transmissivite effective. Le rapport detaille est:

- `docs/_dev_notes/boussinesq_surface_drain_bmin010_test_report.md`.

Cette piste est la plus robuste observee jusqu'ici. Avec `C = 1e-4 m2/s`, le VI
stationnaire direct converge sur tous les cas testes, et le probe transitoire
court avec le meme modele regularise converge aussi:

| cas | statut `C=1e-4` | residu | lecture |
|---|---:|---:|---|
| `site_01_k_low / drain_0` | OK | `3.29e-8` | robuste |
| `site_01_k_base / drain_0` | OK | `2.13e-7` | robuste |
| `site_01_k_base uniform rivers / drain_0` | OK | `8.64e-11` | robuste numeriquement |
| `site_01_k_high / drain_0` | OK | `2.05e-7` | robuste |
| `site_02_k_low / drain_0` | OK | `1.73e-7` | robuste |
| `site_02_k_base / drain_0` | OK | `7.93e-8` | robuste |
| `site_02_k_high / drain_0` | OK | `5.16e-8` | robuste numeriquement |
| `site_02_network` | OK | `3.88e-8` | robuste |

La limite principale est hydrologique: `C = 1e-4 m2/s` est tres faible et laisse
des charges parfois tres au-dessus de la surface. Sur `site_02_k_high`, le
maximum `h - z_top` atteint environ `59 m` et le p95 environ `3.8 m`. Cette
fermeture est donc robuste, mais elle doit etre presentee comme une regularisation
de surface tres souple, pas comme une fermeture physique neutre.

Pour `site_02_k_base` et `site_02_network`, des conductances plus fortes passent
aussi et reduisent fortement les depassements:

| cas | conductance robuste testee | effet |
|---|---:|---|
| `site_02_k_base` | `1e-3`, `1e-2`, `1e-1 m2/s` | convergence et depassement maximum reduit jusqu'a `0.65 m` a `1e-1` |
| `site_02_network` | `1e-3`, `1e-2`, `1e-1 m2/s` | convergence et depassement maximum reduit jusqu'a `0.61 m` a `1e-1` |
| `site_02_k_high` | `1e-4` direct ou `2e-4` avec `TSPSEUDO -> VI` | convergence, mais charges encore tres hautes localement |

`site_02_k_high` reste le cas verrou. Les conductances fortes `1e-3`, `1e-2` et
`1e-1 m2/s` echouent encore avec des residus de `1.38e-2`, `1.39e-1` et `1.39`.
La continuation simple de conductance n'est pas une solution generale: elle
echoue a `5e-3` sur `site_01_k_high`, a `2e-4` sur `site_02_k_base` et a
`5e-4` sur `site_02_k_high`.

Le bilan actualise devient donc:

1. aucune strategie strictement physique et forte en drainage ne passe encore
   tous les cas;
2. `b_min=0.10 m + drainage de surface DRN-like tres faible` est la premiere
   strategie numerique qui passe tout l'echantillon teste;
3. pour une production, il faut chercher la plus grande conductance robuste par
   cas ou par famille de cas, et reporter explicitement les depassements
   `h-z_top`;
4. `site_02_k_high` reste le stress test principal avant promotion.
