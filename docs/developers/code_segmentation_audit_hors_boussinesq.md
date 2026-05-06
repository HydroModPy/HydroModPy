# Audit segmentation hors Boussinesq

Date: 2026-05-05.

Ce document reprend l'audit de segmentation du code en excluant les
implementations internes a `hydromodpy/solver/boussinesq/`, mais en gardant les
effets de bord que ces travaux produisent dans les couches hors Boussinesq.

Commandes utilisees:

```powershell
git status --short
python -m pytest tests/unit/architecture/test_layer_matrix.py tests/unit/config/test_config_location.py -q
python -m pytest tests/unit/config/test_no_legacy_config_imports.py -q
```

Resultat des gates cibles:

- `test_layer_matrix.py` + `test_config_location.py`: `11 passed`.
- `test_no_legacy_config_imports.py`: `2 passed`.

## Verdict court

La segmentation active tient pour les gates unitaires cibles, mais elle reste
dans un etat de transition. Les fronts a traiter en premier ne sont pas dans le
solveur Boussinesq lui-meme: ce sont les references publiques obsoletees, les
diagnostics solveur qui remontent dans `analysis`, et les options PETSc VI
exposees dans le contrat generique `flow`.

Le bon decoupage a conserver est:

- `core`: protocoles, etat minimal, aucun import applicatif.
- `config`: racine applicative `HydroModPyConfig`.
- `physics`: contrat domaine/processus, sans logique backend.
- `simulation`: planification et execution par protocoles.
- `solver/modflow6`, `solver/modflow_nwt`, `solver/modflow_common`: backends
  concrets et mutualisation MODFLOW limitee.
- `results`: vues de lecture et API de resultats, pas d'orchestration.
- `analysis`: post-traitements, comparaison et testbeds, a partir des sorties
  persistees.
- `workflow`: dispatch et composition des launchers.
- `cli`: surface utilisateur.

## Chantiers deja engages

1. **Relocalisation config**
   - `hydromodpy.config` devient la racine canonique.
   - `hydromodpy.master_config` est supprime dans l'arbre de travail.
   - `_bootstrap.py`, `_lazy.py`, les tests config et la matrice de couches ont
     ete ajustes.

2. **Durcissement de la matrice d'architecture**
   - `master_config` sort de `layer_matrix.yaml`.
   - `tools/audit/build_graph.py` et `test_layer_matrix.py` ne comptent plus un
     dossier comme couche s'il n'a pas de `__init__.py`.
   - Cela evite de traiter les vieux dossiers `__pycache__` comme des packages.

3. **Comparaison de simulations**
   - `analysis/comparison` ajoute des exports, rapports et index de diagnostics
     VI obstacle.
   - Les TOML Nancon PETSc VI sont ajoutes dans
     `examples/projects/09_comparison_workflow/`.

4. **API rerun**
   - `Run.rerun()` est retire de `results/run.py`.
   - L'orchestration passe cote `Project.rerun(...)`, ce qui est plus coherent:
     `Run` reste une vue de lecture, `Project` lance les workflows.

5. **Testbed NWT petits bassins**
   - Nouveau cas `examples/projects/10_testbed_workflow/`.
   - Le testbed reste une couche d'orchestration: il genere des TOML enfants,
     lance le workflow standard, puis lit le catalogue.

6. **Travaux Boussinesq PETSc VI**
   - Exclu du present audit pour les fichiers internes au solveur.
   - A surveiller car plusieurs options et diagnostics remontent dans les
     couches `physics` et `analysis`.

## Findings prioritaires

### P0 - References `master_config` encore presentes hors code teste

Le package `hydromodpy.master_config` est supprime, et les tests le confirment.
Il reste pourtant des references hors perimetre du test
`test_no_legacy_config_imports.py`:

```text
pyproject.toml
CONTRIBUTING.md
examples/projects/02_nancon_watershed/run_full_python.py
examples/projects/02_nancon_watershed/run_cellular.py
```

Risque: packaging, coverage, lint et exemples utilisateur peuvent pointer vers
un module retire alors que les gates unitaires passent.

Action recommandee:

- remplacer les imports d'exemples par `from hydromodpy.config import
  HydroModPyConfig`;
- retirer `hydromodpy.master_config` de la configuration coverage;
- retirer l'ignore Ruff du fichier supprime;
- mettre a jour la matrice dans `CONTRIBUTING.md`;
- etendre le test anti-import legacy a `examples/**/*.py`, `pyproject.toml` et
  les documents de dev non archives.

### P1 - `analysis/comparison` importe des details Boussinesq

`analysis/comparison/runtime.py` et `analysis/comparison/exports.py` importent
directement des constantes depuis:

```text
hydromodpy.solver.boussinesq.runtimes.vi_obstacle_diagnostics
hydromodpy.solver.boussinesq.runtimes.ts_vi_obstacle_diagnostics
```

La tolerance `analysis -> solver` permet au gate de passer, mais ce n'est pas
une frontiere stable. La comparaison doit consommer des artefacts persistes et
des manifests, pas connaitre les modules de runtime d'un solveur precis.

Action recommandee:

- court terme: garder la tolerance tant que le diagnostic PETSc VI est en
  stabilisation;
- ensuite: faire produire par chaque run un bloc neutre du type
  `solver_diagnostics = [{kind, label, files, summary}]`;
- faire copier et reporter ces artefacts par `analysis/comparison` sans import
  du solveur;
- ne garder dans `analysis` que des noms de `kind`, pas des chemins de modules
  Boussinesq.

### P1 - Options PETSc VI exposees dans `FlowConfig`

`hydromodpy/physics/flow/flow_config.py` contient maintenant des champs
backend-specifiques:

```text
vi_substeps_per_period
vi_substep_on_failure
vi_max_adaptive_substeps
ts_vi_steps_per_period
ts_vi_adapt
ts_vi_dt_min_fraction
ts_vi_dt_max_fraction
ts_vi_type
ts_vi_snes_type
```

Risque: `physics.flow` devient le parking d'options d'un runtime Boussinesq
experimental. Le contrat `flow` est consomme aussi par MODFLOW-NWT et MODFLOW 6.

Action recommandee:

- accepter temporairement ces champs en `Profile.DEV` pour ne pas bloquer le
  diagnostic;
- deplacer ensuite les options sous un contrat runtime namespaced, par exemple
  `[solver.boussinesq.vi_obstacle]` ou une section dediee Boussinesq;
- garder dans `FlowConfig` seulement le choix scientifique generique, ou un
  identifiant de fermeture stable si necessaire.

### P1 - Le testbed NWT est utile, mais pas encore dynamique

`examples/projects/10_testbed_workflow/nwt_small_catchment_flux_testbed.toml`
repete trois variantes de sites a la main, alors que
`site_tables/armorican_demo_sites.csv` existe. La doc le note deja.

Ce n'est pas une dette critique: le testbed ne depend pas des internals NWT et
passe par le workflow standard. Mais si ce motif devient recurrent, la copie
manuelle des variantes deviendra le mauvais contrat utilisateur.

Action recommandee:

- soit ajouter au testbed un expand de catalogue de sites;
- soit faire porter les campagnes multi-sites par `regional_lab` / `batch`;
- garder le generateur HTML comme outil d'exemple tant que les besoins de rendu
  ne sont pas stabilises.

### P1 - Migration `Run.rerun` vers `Project.rerun`

Le deplacement est sain pour la segmentation: `results.Run` ne lance plus de
workflow. Le risque est seulement API/documentation.

Action recommandee:

- chercher les usages de `run.rerun(` dans docs et exemples;
- documenter `Project.rerun(run, ...)` comme remplacement;
- ajouter un test d'absence ou un message de migration si l'API publique avait
  deja ete publiee.

### P2 - Dossiers fantomes et couverture des audits

`hydromodpy/pipeline/` ne contient plus de sources Python, seulement des caches.
Le scanner l'ignore correctement car il exige `__init__.py`.

Action recommandee:

- nettoyer les caches hors Git quand l'environnement le permet;
- garder la regle `__init__.py` dans le scanner, elle evite les faux packages.

## Arretes tolerees a surveiller

Arretes non conformes encore documentees par `layer_matrix.yaml`:

```text
analysis -> display   comparison exports reuse plot mesh loading
analysis -> physics   history contract
analysis -> solver    comparison runtime resolves solver families
calibration -> results catalog read at planning time
data -> spatial       geology field bridging
results -> spatial    results stores spatial indices
```

Priorite de resorption:

1. `analysis -> solver`, car elle encode des details Boussinesq dans la couche
   de comparaison.
2. `data -> spatial`, si la geologie continue a grossir comme pont entre
   managers de donnees et champs spatiaux.
3. `results -> spatial`, si les roles geographiques continuent a s'etendre dans
   l'API `Run` au lieu de passer par un contrat neutre.

## Extension hors chantiers en cours

Cette section exclut les chantiers deja listes plus haut: relocalisation
`config`, comparaison PETSc VI, testbed NWT, migration `Project.rerun`, et
fichiers internes au solveur Boussinesq. Elle regarde les coutures qui
resteront apres fermeture de ces travaux.

### E1 - `data` fabrique encore des objets `spatial`

Deux points concrets portent la tolerance `data -> spatial`:

```text
hydromodpy/data/loader.py:316
hydromodpy/data/variables/hydrography/manager.py:22
hydromodpy/data/variables/hydrography/manager.py:52
```

Le premier construit un `GeologyField` depuis un `FieldRecord`. Le second
importe les noms canoniques du reseau hydrographique depuis `spatial`, puis
instancie le backend Whitebox de delineation dans le manager hydrographie.

Lecture: ce n'est pas un bug immediat. C'est le residu d'un modele ou les
managers de donnees font aussi une partie de la preparation spatiale. Le risque
apparaitra si de nouvelles variables suivent le meme chemin: chaque manager
deviendra a la fois fetch/cache, reprojection, rasterisation et construction de
support runtime.

Direction propre:

- laisser `data` produire des `LoadResult`, `FieldRecord`, fichiers et
  metadonnees;
- mettre les noms de fichiers/roles hydrographiques dans un contrat neutre
  (`core.contracts` ou `data.contracts`) si `data` doit les connaitre;
- deplacer la materialisation `FieldRecord -> GeologyField` et les appels
  `spatial.delineation` dans une etape `workflow` ou un binder `spatial`;
- garder les imports actuels tant que la surface geologie/hydrographie n'est
  pas en chantier, mais ne pas les dupliquer ailleurs.

### E2 - `results.Run` contient encore du vocabulaire geospatial

`Run` est deja redevenu plus propre avec le retrait de `Run.rerun()`. Le calcul
`simulated_active_network_distance_metrics()` a aussi ete replace dans
`results.views`, ce qui supprime l'arrete `results -> analysis`. Il reste des
helpers qui importent `spatial`:

```text
hydromodpy/results/run.py:570
hydromodpy/results/run.py:588
hydromodpy/results/run.py:610
hydromodpy/results/run.py:630
```

Ces methodes servent les roles de reseau hydrographique.

Lecture: les methodes de lecture de features geographiques sont acceptables sur
`Run`, car elles exposent du contenu persiste. La dette restante est plus fine:
`results` connait encore le vocabulaire canonique defini dans `spatial`.

Direction propre:

- garder sur `Run` les lectures simples: `geographic(...)`, `field(...)`,
  `timeseries(...)`, `budget(...)`;
- extraire le vocabulaire des roles hydrographiques dans un contrat neutre si
  `results` et `spatial` doivent continuer a le partager.

### E3 - `workflow` ne depend plus directement de la facade `Project`

Le dispatch public qui doit instancier `Project` a ete deplace vers:

```text
hydromodpy/workflow_dispatch.py
```

`hydromodpy/workflow/dispatch.py` garde la resolution du champ `workflow` et
les launchers internes qui ne passent pas par la facade racine. Le sweep ne type
plus son argument en `Project`: il consomme un protocole minimal local
(`SweepProject`) qui expose seulement `run(...)`.

Lecture: la direction principale est maintenant correcte. `Project` et les
entrees publiques (`hmp run`, `hmp.run`) appellent le workflow; le package
`workflow` ne reinstancie plus la facade utilisateur. Le provider testbed est
injecte depuis `_bootstrap.py`, ce qui garde `analysis.testbed` decouple du
workflow et de `Project`.

Dette restante: le module racine `workflow_dispatch.py` reste un adaptateur de
compatibilite autour de `Project`. C'est acceptable tant qu'il reste hors du
package `workflow`.

### E4 - Calibration ne depend plus directement de `Project`

La promotion historique `calibration.runners.trial.promote_trial(...)` passe
maintenant par un provider:

```text
hydromodpy/calibration/runners/contracts.py
hydromodpy/calibration_dispatch.py
```

`calibration` garde la logique d'objectif, de parametres, de traces et de
selection du meilleur run. Le provider concret qui instancie `Project` est
enregistre par `_bootstrap.py`, au niveau racine.

Lecture: le couplage a l'orchestration reste normal, car la calibration doit
produire de vraies simulations. La direction de dependance est maintenant plus
propre: `calibration` consomme un contrat de promotion au lieu d'importer la
facade publique.

### E5 - Les `cases/` et `examples/` embarques brouillent le signal production

Hors Boussinesq, l'arbre contient beaucoup de scripts de demonstration dans les
packages applicatifs:

```text
hydromodpy/spatial/mesh/gmsh_grid/cases      31 fichiers Python, 7343 lignes
hydromodpy/spatial/mesh/cartesian_grid/examples 10 fichiers Python, 2364 lignes
hydromodpy/calibration/cases                  3 fichiers Python, 1828 lignes
hydromodpy/spatial/field/cases                6 fichiers Python, 1139 lignes
hydromodpy/spatial/domain/cases               4 fichiers Python, 1061 lignes
```

Lecture: ces scripts sont utiles pour docs, galeries et caracterisation, mais
ils gonflent artificiellement les couches de production et peuvent tirer des
imports qui ne representent pas le contrat runtime.

Direction propre:

- conserver `calibration.cases` seulement si c'est une API publique de
  benchmarks;
- deplacer les gros cas de demonstration spatiale vers `examples/`,
  `validation_cases/` ou `tools/`;
- si le deplacement est trop couteux, declarer explicitement dans le scanner et
  la doc que `hydromodpy/**/cases/**` et `hydromodpy/**/examples/**` sont des
  entrypoints de demonstration, pas du code de couche.

### E6 - Les gros modules a surveiller ne sont pas tous des problemes de couche

Top modules hors Boussinesq par taille observee:

```text
hydromodpy/analysis/comparison/runtime.py      2725 lignes
hydromodpy/analysis/comparison/exports.py      2584 lignes
hydromodpy/cli/commands/manage.py              1350 lignes
hydromodpy/solver/modflow6/modflow6.py         1316 lignes
hydromodpy/results/catalog/writes.py           1137 lignes
hydromodpy/results/run.py                      1017 lignes
hydromodpy/data/registry/catalog_duckdb.py      995 lignes
hydromodpy/physics/flow/flow_config.py          941 lignes
hydromodpy/workflow/steps/prepare_solver.py     830 lignes
```

Lecture: la taille seule n'est pas une violation. Elle indique seulement ou les
responsabilites risquent de se melanger lors de la prochaine feature.

Priorites hors chantiers actifs:

- `cli/commands/manage.py`: scinder par sous-commandes si de nouvelles commandes
  de gestion arrivent.
- `solver/modflow6/modflow6.py`: scinder seulement quand MF6 LAK/DISV avance;
  eviter une factorisation speculative.
- `results/catalog/writes.py` et `data/registry/catalog_duckdb.py`: garder des
  tests de schema/ecriture, puis extraire par famille de tables seulement si la
  logique d'ecriture continue a grossir.
- `workflow/steps/prepare_solver.py`: surveiller car c'est une zone
  d'assemblage transversale; elle doit rester orchestration, pas logique
  backend.

### E7 - Le decoupage MODFLOW commun est globalement sain

`solver/modflow_common/` reste petit par rapport aux backends:

```text
solver/modflow_common: 1961 lignes
solver/modflow6:       6145 lignes
solver/modflow_nwt:    6157 lignes
```

Lecture: c'est coherent avec `nwt_sunset_plan.md`. La bonne strategie reste de
mutualiser les contrats vraiment communs, mais de ne pas chercher a faire une
abstraction MODFLOW parfaite tant que NWT est voue au retrait.

Direction propre:

- ne pas ouvrir de chantier de deduplication NWT/MF6;
- mettre les nouvelles capacites cote MF6;
- maintenir `modflow_common` comme boite a outils explicite, pas comme backend
  abstrait complet.

## Decision de segmentation proposee

Pour les travaux hors Boussinesq, ne pas ouvrir de refactor large maintenant.
Le chemin le plus robuste est:

1. fermer les references stale `master_config`;
2. stabiliser les diagnostics PETSc VI, puis les convertir en artefacts
   solver-agnostiques;
3. renamespacer les options runtime Boussinesq hors du contrat `FlowConfig`;
4. garder NWT local et sans nouvelle mutualisation lourde, conforme au plan de
   retrait NWT;
5. formaliser le testbed multi-sites seulement si le cas NWT est rejoue sur un
   vrai catalogue.

