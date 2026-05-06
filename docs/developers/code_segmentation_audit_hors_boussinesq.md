# Audit segmentation hors Boussinesq

Date: 2026-05-06.

Ce document reprend l'audit de segmentation du code en excluant les
implementations internes a `hydromodpy/solver/boussinesq/`, mais en gardant les
effets de bord que ces travaux produisent dans les couches hors Boussinesq.

Commandes utilisees pour le rafraichissement:

```powershell
git status --short
python -m pytest tests/unit/architecture/test_layer_matrix.py -q
python -m pytest tests/unit/config/test_config_location.py tests/unit/config/test_no_legacy_config_imports.py -q
python -m tools.audit.build_graph hydromodpy meta_review_output
rg -n "hydromodpy\.master_config|from hydromodpy\.master_config|import hydromodpy\.master_config" -S .
```

Resultat des gates cibles du 2026-05-06:

- `test_layer_matrix.py`: `4 passed`.
- `test_config_location.py` + `test_no_legacy_config_imports.py`: `9 passed`.
- graphe d'import: `2914` arretes scannees.
- la recherche `master_config` ne trouve plus que la documentation d'audit et
  les tests qui verifient l'absence de l'ancien package.

## Verdict court

La segmentation active tient pour le gate d'architecture. Il ne reste qu'une
tolerance dans `layer_matrix.yaml`: `cli -> <root>`, liee a la facade publique.
Les arretes `data -> spatial`, `results -> spatial`, `calibration -> results`,
`analysis -> display` et `analysis -> physics` sont maintenant des choix de
developpement explicites, pas des problemes a faire remonter comme dettes de
segmentation.

Les fronts restants sont surtout semantiques, pas des violations de matrice:
les options PETSc VI encore exposees dans le contrat generique `flow`, le
contrat de diagnostics solveur encore exprime comme noms de fichiers fixes,
quelques modules d'analyse/resultats tres volumineux, et les nombreux
`cases/`/`examples/` embarques dans les packages applicatifs.

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

### Clos - References `master_config`

Etat du 2026-05-06: le package `hydromodpy.master_config` est supprime, et les
references utilisateur stale ont ete nettoyees. La recherche large:

```powershell
rg -n "hydromodpy\.master_config|from hydromodpy\.master_config|import hydromodpy\.master_config" -S .
```

ne retourne plus que:

- ce document, qui conserve l'historique de migration;
- les tests de configuration qui verifient explicitement que l'ancien package
  n'est plus importable ou reference dans le code actif.

Cette finding n'est donc plus un chantier de segmentation ouvert.

### P1 - `analysis/comparison` ne doit pas importer le solveur

Etat du 2026-05-06: la tolerance `analysis -> solver` a ete supprimee. Les noms
d'artefacts diagnostics VI/TS VI vivent maintenant dans
`hydromodpy.core.solver_diagnostics`, et `analysis/comparison/runtime.py`
utilise le provider `_solver_protocol` pour les sections de solveurs
distribues.

Avant cette coupe, `analysis/comparison/runtime.py` et
`analysis/comparison/exports.py` importaient directement des constantes depuis:

```text
hydromodpy.solver.boussinesq.runtimes.vi_obstacle_diagnostics
hydromodpy.solver.boussinesq.runtimes.ts_vi_obstacle_diagnostics
```

Direction restante:

- garder `analysis` sur des artefacts persistes et des contrats neutres;
- a terme, remplacer les noms fixes par un manifest par run du type
  `solver_diagnostics = [{kind, label, files, summary}]`.

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

## Snapshot de segmentation - 2026-05-06

### Gate de matrice

Le gate `tests/unit/architecture/test_layer_matrix.py` passe avec `4 passed`.
La matrice ne contient plus qu'une tolerance:

```text
cli -> root    1 import    CLI dispatch delegates to public Project facade
```

Import exact:

```text
hydromodpy/cli/commands/run.py:128 -> hydromodpy.workflow_dispatch
```

Lecture: cette arrete garde `hmp run` branche sur l'adaptateur public de
dispatch. Elle peut rester documentee tant que le package `cli` reste la surface
utilisateur et que l'adaptateur concret reste hors du package `workflow`.

### Arretes maintenant assumees

Ces arretes sont autorisees dans la matrice et ne doivent plus remonter comme
problemes de segmentation:

```text
data -> spatial          7 imports
results -> spatial       4 imports
calibration -> results   3 imports
analysis -> display      1 import
analysis -> physics      2 imports
```

`data -> spatial` est assume parce que la couche `data` materialise certains
produits spatiaux pendant la sequence metier `charger -> materialiser ->
exposer dans loaded_data`. Trois imports appartiennent au chemin actif
(`data/loader.py`, `data/variables/hydrography/manager.py`) et quatre a un cas
embarque `data/variables/geology/cases/`.

`results -> spatial` est assume pour conserver l'API utilisateur de `Run` sur
les reseaux hydrographiques persistants:

```python
run.hydrographic_network("reference")
run.hydrographic_network_comparison(...)
```

`calibration -> results` est assume parce que la calibration pilote, trace,
promeut et relit des simulations persistees via le catalogue de resultats.

`analysis -> display` est assume parce que les workflows d'analyse peuvent
produire des artefacts visuels, tandis que l'implementation du rendu reste dans
`display`.

`analysis -> physics` est assume pour le contrat d'historique temporel:

```text
hydromodpy/analysis/comparison/exports.py:29
hydromodpy/analysis/comparison/runtime.py:39
```

Ces imports pointent vers `hydromodpy.physics.flow.history_contract`. Le contrat
decrit l'alignement `t0..tN` pour les snapshots et `dt1..dtN` pour les periodes.
Ce n'est ni un import de solveur, ni une dependance a une implementation
physique concrete; c'est le contrat metier commun qui evite de reconstruire
localement la regle temporelle dans `analysis`.

### Arretes resorbees

Le graphe courant confirme les coupes suivantes:

```text
analysis -> solver       0 import
results -> analysis      0 import
workflow -> root         0 import
calibration -> root      0 import
```

Lecture: les chantiers precedents ont bien ramene les dependances publiques
vers des adaptateurs racine (`workflow_dispatch.py`, `calibration_dispatch.py`)
ou vers des contrats neutres (`core.solver_diagnostics`).

### Coutures sensibles restantes

Ces points ne violent pas la matrice, mais restent les zones a surveiller dans
les prochains travaux:

1. `physics.flow.FlowConfig` porte encore des options PETSc VI tres proches du
   backend Boussinesq. C'est la principale dette semantique restante hors
   solveur Boussinesq interne.
2. `core.solver_diagnostics` supprime l'import `analysis -> solver`, mais garde
   des noms d'artefacts fixes. L'etape plus propre sera un manifest ecrit par
   chaque run et lu par `analysis`.
3. `calibration.metrics` importe encore `hydromodpy.solver.base.registry` pour
   resoudre l'adaptateur actif. C'est autorise par la matrice, mais un provider
   injecte comme pour la promotion de trial serait plus homogene si ce code
   grossit.
4. Les modules `analysis/comparison/runtime.py` et `exports.py` restent tres
   volumineux. Ce n'est pas une violation de couche, mais le prochain ajout
   important devrait etre l'occasion d'extraire par responsabilite.
5. Les nombreux `cases/` et `examples/` sous `hydromodpy/` brouillent le signal
   production dans les audits. Ils doivent rester clairement consideres comme
   entrypoints de demonstration.

## Plan d'action - etape 1: geler l'etat cible

Avant de supprimer une nouvelle tolerance, il faut figer l'etat de depart. Le
but n'est pas de refaire tout l'audit: il s'agit de produire une photographie
reproductible des dependances restantes, puis de choisir une seule arrete a
resorber.

Commandes de cadrage:

```powershell
python -m tools.audit.build_graph hydromodpy meta_review_output
python -m pytest tests/unit/architecture/test_layer_matrix.py -q
rg -n "analysis -> solver|data -> spatial|results -> spatial|calibration -> results" docs tests hydromodpy
```

Snapshot du 2026-05-06:

- graphe d'import: 2914 arretes scannees;
- test de matrice: `4 passed`;
- tolerances retirees: `simulation -> solver`, `analysis -> solver`, puis
  `analysis -> physics`;
- choix assumes: `data -> spatial`, `results -> spatial`,
  `calibration -> results`, `analysis -> display`, `analysis -> physics`;
- tolerance restante: `cli -> root`.

Livrables attendus:

- la liste exacte des tolerances encore presentes dans
  `tests/unit/architecture/layer_matrix.yaml`;
- le graphe d'import courant produit par `tools.audit.build_graph`;
- une decision explicite pour chaque arrete: supprimer maintenant, garder
  temporairement, ou documenter comme dependance structurelle assumee;
- un seul objectif de coupe pour l'etape suivante.

Decision par arrete:

- `results -> spatial`: garder comme choix de developpement; l'API utilisateur
  de `Run` reste prioritaire.
- `calibration -> results`: garder comme choix de developpement; la calibration
  orchestre des simulations persistees.
- `analysis -> display`: garder comme choix de developpement; les analyses
  peuvent produire des figures en deleguant le rendu a `display`.
- `analysis -> physics`: garder comme choix de developpement; l'analyse reutilise
  le contrat metier d'historique temporel `t0..tN` / `dt1..dtN`.
- `cli -> root`: garder comme facade utilisateur assumee.

Decision actuelle: `analysis -> solver` est coupe. `data -> spatial`,
`results -> spatial`, `calibration -> results`, `analysis -> display` et
`analysis -> physics` deviennent des choix de developpement assumes. Le prochain
travail eventuel ne doit plus rouvrir ces arretes; il doit plutot porter sur la
tolerance `cli -> root` ou sur les coutures semantiques listees dans le snapshot
approfondi.

Critere de sortie:

- la photographie de depart est a jour;
- les tests d'architecture passent encore;
- la prochaine coupe a un perimetre unique et nomme.

## Plan d'action - etape 2: couper `analysis -> solver` - realise

Objectif realise: supprimer les 5 imports `analysis -> solver` observes le
2026-05-06, sans changer le comportement des exports de comparaison.

Imports a supprimer:

```text
hydromodpy/analysis/comparison/exports.py:22
hydromodpy/analysis/comparison/exports.py:27
hydromodpy/analysis/comparison/runtime.py:33
hydromodpy/analysis/comparison/runtime.py:38
hydromodpy/analysis/comparison/runtime.py:165
```

Ils correspondent a deux problemes differents.

### 2A - Remplacer le lookup direct du registre solveur

`analysis/comparison/runtime.py` importe encore `hydromodpy.solver.base.registry`
dans `_candidate_solver_sections(...)`. Le meme besoin est deja traite plus
proprement dans `analysis/comparison/runtime_mesh.py`, via
`analysis.comparison._solver_protocol` et le provider enregistre par
`_bootstrap.py`.

Action:

- remplacer la copie locale de `_candidate_solver_sections(...)` dans
  `runtime.py` par le provider deja utilise par `runtime_mesh.py`;
- garder la resolution des sections solveur derriere
  `get_solver_registry_provider()`;
- verifier que `analysis` n'importe plus `solver.base.registry`.

Critere de sortie 2A:

- `rg -n "hydromodpy\\.solver\\.base\\.registry" hydromodpy/analysis` ne
  retourne rien;
- les tests de comparaison qui resolvent une forme structuree continuent de
  passer.

Etat: fait.

### 2B - Sortir les noms d'artefacts diagnostics du solveur

`exports.py` et `runtime.py` importent les noms de fichiers:

```text
vi_obstacle_runtime_summary.json
vi_obstacle_period_diagnostics.csv
vi_obstacle_substep_diagnostics.csv
ts_vi_obstacle_runtime_summary.json
ts_vi_obstacle_period_diagnostics.csv
ts_vi_obstacle_step_diagnostics.csv
```

Ces noms sont aujourd'hui definis dans les modules runtime Boussinesq, puis
relus par `analysis/comparison`. Cela force la couche de comparaison a connaitre
le package du solveur.

Action minimale recommandee:

- contrat neutre cree dans `hydromodpy/core/solver_diagnostics.py` avec les
  noms d'artefacts et, si utile, un petit descripteur par famille de diagnostic;
- faire importer ce contrat par le solveur Boussinesq et par
  `analysis/comparison`;
- laisser les fonctions de construction/ecriture detaillees dans le solveur;
- ne pas deplacer la logique scientifique des diagnostics, seulement le contrat
  de nommage des artefacts persistables.

Alternative plus ambitieuse, a garder pour plus tard:

- faire ecrire un manifest `solver_diagnostics_manifest.json` par chaque run;
- faire lire ce manifest par `analysis` au lieu de connaitre des noms de
  fichiers fixes.

Critere de sortie 2B:

- `rg -n "hydromodpy\\.solver" hydromodpy/analysis/comparison` ne retourne plus
  d'import solveur;
- les exports VI obstacle et TS VI obstacle retrouvent les memes fichiers
  qu'avant;
- les tests solveur continuent de verifier le contenu des diagnostics, pas la
  couche `analysis`.

Etat: fait pour les noms d'artefacts. Le manifest par run reste une evolution
ulterieure.

### 2C - Durcir la matrice

Une fois 2A et 2B terminees:

- retirer la tolerance `{src: analysis, tgt: solver}` de
  `tests/unit/architecture/layer_matrix.yaml`;
- retirer la ligne correspondante de `docs/developers/architecture.md`;
- relancer le graphe d'import.

Etat: fait; `analysis -> solver` vaut 0.

Commandes de validation:

```powershell
python -m pytest tests/unit/architecture/test_layer_matrix.py -q
python -m pytest tests/unit/launchers/test_comparison_launcher.py -k "diagnostics or obstacle" -q
python -m pytest tests/unit/launchers/test_simulation_comparison_launcher.py -q
python -m pytest tests/unit/solver/test_petsc_vi_obstacle.py tests/unit/solver/test_petsc_ts_vi_obstacle.py -q
python -m tools.audit.build_graph hydromodpy meta_review_output
```

Definition de fini:

- `analysis -> solver` vaut 0 dans le graphe d'import;
- la tolerance est supprimee de la matrice;
- aucun export de comparaison ne perd les diagnostics Boussinesq existants;
- aucune autre arrete (`data -> spatial`, `results -> spatial`, etc.) n'est
  modifiee dans ce chantier.

## Extension hors chantiers en cours

Cette section exclut les chantiers deja listes plus haut: relocalisation
`config`, comparaison PETSc VI, testbed NWT, migration `Project.rerun`, et
fichiers internes au solveur Boussinesq. Elle regarde les coutures qui
resteront apres fermeture de ces travaux.

### E1 - `data` materialise certains objets `spatial` par choix

Ces points ne sont plus classes comme probleme de segmentation:

```text
hydromodpy/data/loader.py:316
hydromodpy/data/variables/hydrography/manager.py:22
hydromodpy/data/variables/hydrography/manager.py:52
```

Le premier construit un `GeologyField` depuis un `FieldRecord`. Le second
importe les noms canoniques du reseau hydrographique depuis `spatial`, puis
instancie le backend Whitebox de delineation dans le manager hydrographie.

Lecture: la succession metier reste plus lisible si le chargement des donnees
peut materialiser directement certains produits spatiaux attendus dans
`loaded_data`. Cette decision evite d'eparpiller la logique `charger ->
materialiser -> exposer` dans plusieurs couches. Les imports actuels sont donc
un choix explicite, pas une dette a resorber.

### E2 - `results.Run` expose volontairement une API hydrographique pratique

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

Lecture: ce choix est assume. Les methodes de lecture et de comparaison de
features geographiques sont utiles sur `Run`, car elles exposent directement du
contenu persiste avec une API utilisateur simple:

```python
run.hydrographic_network("reference")
run.hydrographic_network_comparison(...)
```

On privilegie ici l'ergonomie de lecture des resultats plutot qu'une frontiere
plus stricte ou `Run` ne connaitrait que des noms de tables bruts. Cette arrete
ne doit plus remonter comme probleme de segmentation.

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
packages applicatifs. Snapshot du 2026-05-06:

```text
hydromodpy/spatial/mesh/gmsh_grid/cases          31 fichiers Python, 6479 lignes
hydromodpy/spatial/mesh/cartesian_grid/examples  10 fichiers Python, 2024 lignes
hydromodpy/calibration/cases                      3 fichiers Python, 1592 lignes
hydromodpy/spatial/field/cases                    6 fichiers Python, 972 lignes
hydromodpy/spatial/domain/cases                   4 fichiers Python, 928 lignes
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

Top modules hors Boussinesq par taille observee le 2026-05-06:

```text
hydromodpy/analysis/comparison/runtime.py       2432 lignes
hydromodpy/analysis/comparison/exports.py       2404 lignes
hydromodpy/cli/commands/manage.py               1247 lignes
hydromodpy/solver/modflow6/modflow6.py          1200 lignes
hydromodpy/results/catalog/writes.py            1069 lignes
hydromodpy/analysis/comparison/visuals_render_series.py 918 lignes
hydromodpy/data/registry/catalog_duckdb.py       895 lignes
hydromodpy/results/run.py                        880 lignes
hydromodpy/physics/flow/flow_config.py           871 lignes
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

`solver/modflow_common/` reste petit par rapport aux backends. Snapshot du
2026-05-06:

```text
solver/modflow_common: 1605 lignes
solver/modflow6:       5426 lignes
solver/modflow_nwt:    5262 lignes
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

1. garder les choix de developpement explicites dans la matrice et ne plus les
   retraiter comme dettes;
2. renamespacer les options runtime Boussinesq hors du contrat `FlowConfig`;
3. convertir les diagnostics solveur fixes en manifest persiste par run;
4. surveiller `calibration.metrics -> solver.registry` si la calibration RAM
   continue a grossir;
5. garder NWT local et sans nouvelle mutualisation lourde, conforme au plan de
   retrait NWT;
6. formaliser le testbed multi-sites seulement si le cas NWT est rejoue sur un
   vrai catalogue.

