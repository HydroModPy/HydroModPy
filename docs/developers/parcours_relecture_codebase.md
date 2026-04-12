# Parcours de relecture du code et inventaire du depot

Ce document propose une facon de relire HydroModPy de maniere large mais efficace, sans passer ligne par ligne sur tout le depot. L'objectif est de construire une carte mentale fiable du systeme, de reperer les zones critiques, puis de decider ou approfondir.

Les tailles ci-dessous sont des ordres de grandeur observes le 2026-04-12 par comptage recursif de fichiers. Elles servent a prioriser la lecture, pas a faire autorite.

Checklist compagnon : [checklist_relecture_codebase.md](checklist_relecture_codebase.md)

## Principe general

- Relire par flux, couches et responsabilites, pas par fichiers pris au hasard.
- Commencer par les points d'entree et les parcours executables avant les details internes.
- Pour chaque zone, noter le role, les entrees/sorties, les invariants, les dependances et les tests.
- Approfondir seulement les zones coeur, fragiles ou numeriquement sensibles.
- Finir par une synthese courte : ce que fait la zone, comment elle se connecte, ce qui est solide, ce qui merite une reprise.

## Parcours conseille

### 1. Vue d'ensemble du produit

Commencer par :

- `README.md`
- `ARCHITECTURE.md`
- `docs/developers/CLI.md`
- `hydromodpy/__main__.py`

Questions a traiter d'abord :

- Quels sont les usages cibles du depot ?
- Quels sont les principaux points d'entree utilisateur ?
- Quelle est la difference entre bibliotheque, launcher, simulation et cas de validation ?
- Ou sont les couches stables, et ou sont les couches d'orchestration ?

### 2. Parcours executables et points d'entree

Lire ensuite les lanceurs et les exemples qui montrent comment le code "vit" :

- `launchers/process_simulation/`
- `launchers/method_comparison/`
- `launchers/model_calibration/`
- `launchers/mesh_catchment/`
- `examples/projects/`

Objectif :

- voir comment un fichier TOML ou un projet devient une execution,
- identifier les objets pivots du runtime,
- reperer les transitions entre config, chargement de donnees, construction spatiale, solveurs et sorties.

### 3. Infrastructure coeur

Avant d'entrer dans les algorithmes, lire les briques de base :

- `hydromodpy/core/`
- `hydromodpy/simulation/`

Points a comprendre :

- gestion de configuration,
- workspace et chemins,
- etat d'execution,
- fenetre temporelle,
- planification et orchestration de l'execution.

### 4. Domaine spatial et donnees

Ensuite, passer par la representation du terrain et des entrees :

- `hydromodpy/spatial/`
- `hydromodpy/data/`
- `hydromodpy/watershed/`

Questions utiles :

- comment le bassin, les rasters, les maillages et les champs sont construits,
- comment les donnees hydro, geo, piezo, climat, etc. sont normalisees,
- ou se trouvent les contrats entre donnees sources et objets internes.

### 5. Processus physiques et solveurs

C'est la zone a relire avec le plus de soin technique :

- `hydromodpy/process/`
- `hydromodpy/solver/`

Ici, il faut verifier :

- la separation entre processus physiques et backend numerique,
- les contrats d'entree/sortie entre runtime et solveur,
- les hypotheses numeriques,
- les cas limites,
- les divergences entre solveurs `boussinesq`, `modflow_nwt` et `modflow6`.

### 6. Analyse, sorties et exploitation

Une fois le calcul compris, terminer par :

- `hydromodpy/analysis/`
- `docs/readthedocs/`

Objectif :

- comprendre comment les sorties deviennent figures, tableaux, NetCDF, series temporelles et rapports,
- verifier si les interfaces de post-traitement reutilisent proprement les objets de simulation,
- identifier ce qui est coeur produit versus support documentaire.

### 7. Verifications et ancrages scientifiques

Finir la relecture par les preuves et garde-fous :

- `tests/unit/`
- `tests/regression/`
- `tests/validation/`
- `validation_cases/`

Ce passage sert a verifier :

- ce qui est reellement protege par des tests,
- quels comportements sont consideres comme contractuels,
- quelles parties ont une validation numerique ou analytique explicite,
- quels pans du depot sont moins couverts que leur criticite ne le demanderait.

## Methode de lecture par module

Pour chaque module ou dossier important, produire une fiche de lecture courte avec les rubriques suivantes :

- Responsabilite : a quoi sert exactement cette zone ?
- Entrees : que recoit-elle comme config, objets, fichiers ou arrays ?
- Sorties : que produit-elle sur disque, en memoire ou pour le module suivant ?
- Invariants : quelles hypothese doivent rester vraies ?
- Dependances : de quels modules ou backends depend-elle ?
- Points chauds : quelles fonctions ou classes portent la logique critique ?
- Tests : quels tests protegent ce comportement ?
- Risques : dette, couplage, duplication, zone floue, contrat implicite.

Un bon resultat de lecture tient souvent en 5 a 10 lignes par zone. Si une lecture produit une page complete sans structure, elle est probablement trop basse dans le detail.

## Grille de revue

### Organisation

- La responsabilite du module est-elle nette ?
- Le nommage des packages, classes et fonctions est-il coherent ?
- Les couches sont-elles respectees ou contournees ?
- Y a-t-il des packages de compatibilite a ne pas confondre avec le coeur actif ?

### Flux de donnees

- L'origine des donnees est-elle explicite ?
- Les transformations sont-elles lisibles d'un bout a l'autre ?
- Les objets pivots sont-ils stables ou trop polymorphes ?
- Les entrees/sorties disque sont-elles bien delimitees ?

### Algorithmes

- L'objectif mathematique ou physique est-il formule clairement ?
- Les hypotheses sont-elles codees explicitement ou implicites ?
- Les cas limites et valeurs aberrantes sont-ils traites ?
- La complexite et le cout memoire sont-ils raisonnables ?
- Le contrat numerique est-il teste contre des references ?

### Robustesse

- Les erreurs sont-elles signalees assez tot ?
- Les validations de config sont-elles suffisantes ?
- Les chemins de reprise, cache ou resume sont-ils coherents ?
- Les adaptations entre solveurs restent-elles fiables quand on change de backend ?

### Qualite de maintenance

- Le code est-il factorise au bon niveau ?
- Existe-t-il des duplications entre backends, launchers ou workflows ?
- La documentation executable suit-elle le code reel ?
- Les tests protegent-ils les zones les plus risqueees plutot que les plus faciles ?

## Inventaire des grandes parties du code

### Noyau `hydromodpy/`

| Zone | Approx. nb fichiers | Role principal | Sous-zones marquantes |
| --- | ---: | --- | --- |
| `hydromodpy/data/` | 709 | Chargement, normalisation et contrats de donnees metier | `climatic`, `geology`, `hydrography`, `hydrometry`, `intermittency`, `piezometry`, `registry`, `variables` |
| `hydromodpy/solver/` | 620 | Solveurs numeriques et outillage associe | `boussinesq`, `modflow_common`, `modflow_nwt`, `modflow6`, `prototype`, `utils` |
| `hydromodpy/analysis/` | 595 | Post-traitement, affichage, calibration et reporting | `calibration`, `display`, `postprocess` |
| `hydromodpy/spatial/` | 371 | Representation spatiale du domaine et des supports numeriques | `domain`, `field`, `geographic`, `mesh` |
| `hydromodpy/process/` | 261 | Processus physiques et contrats de runtime metier | `flow`, `forcing`, `hydrology`, `prototype`, `transport` |
| `hydromodpy/core/` | 153 | Infrastructure transverse du package | `backends`, `config`, `state`, `time`, `tools`, `units`, `workspace` |
| `hydromodpy/simulation/` | 83 | Orchestration runtime entre config, processus et solveurs | `adapters`, `execution`, `forcing`, `planning` |
| `hydromodpy/watershed/` | 15 | Facade historique orientee `Watershed` et runtime associe | `watershed.py`, `hydraulic.py` |
| `hydromodpy/config/` | 5 | Wrapper de compatibilite vers `hydromodpy.core.config` | `__init__.py`, `__main__.py` |
| `hydromodpy/modeling/` | 2 | Facade de compatibilite pour imports historiques | redirections vers solveurs et postprocess |

### Dossiers satellites importants

| Zone | Approx. nb fichiers | Role principal | Comment la lire |
| --- | ---: | --- | --- |
| `launchers/` | 146 | Orchestrateurs orientes cas d'usage | lire comme points d'entree metier et non comme coeur algorithmique |
| `tests/unit/` | 857 | Contrats locaux et comportement unitaire | bon point d'entree pour comprendre les API reelles |
| `tests/regression/` | 201 | Non-regression sur workflows et sorties | utile pour voir les scenarios officiellement supportes |
| `tests/validation/` | 111 | Validation scientifique et numerique | prioritaire pour juger la confiance sur les solveurs |
| `validation_cases/` | 686 | Cas analytiques et numeriques partageables | lire comme documentation executable des hypotheses |
| `examples/` | variable | Projets et jeux de donnees demonstratifs | utile pour suivre un flux complet sans lire tout le code |
| `hydromodpy_annex/` | variable | Outils annexes non coeur package | a lire apres le noyau, pour ne pas melanger generique et specifique |
| `tools/` | variable | Scripts de support, CI, generation de docs | utile pour comprendre l'outillage du depot |
| `bin/` | variable | Executables externes embarques | ne pas confondre avec la logique Python du projet |

## Points chauds a prioriser

Si le temps est limite, prioriser cet ordre :

1. `hydromodpy/solver/`
2. `hydromodpy/data/`
3. `hydromodpy/process/`
4. `hydromodpy/spatial/`
5. `hydromodpy/simulation/`
6. `launchers/`
7. `tests/validation/` puis `tests/regression/`

Raison :

- `solver` concentre la sensibilite numerique et les divergences de backend,
- `data` concentre les contrats d'entree et les nombreux cas metier,
- `process` tient les abstractions physiques qui doivent rester coherentes quel que soit le solveur,
- `spatial` conditionne la qualite du domaine calcule,
- `simulation` et `launchers` montrent comment tout s'assemble reellement.

## Parcours court en 6 sessions

### Session 1

- `README.md`
- `ARCHITECTURE.md`
- `docs/developers/CLI.md`
- `hydromodpy/__main__.py`

### Session 2

- `launchers/process_simulation/`
- `launchers/method_comparison/`
- un ou deux projets dans `examples/projects/`

### Session 3

- `hydromodpy/core/`
- `hydromodpy/simulation/`

### Session 4

- `hydromodpy/spatial/`
- `hydromodpy/data/`
- `hydromodpy/watershed/`

### Session 5

- `hydromodpy/process/`
- `hydromodpy/solver/`

### Session 6

- `hydromodpy/analysis/`
- `tests/unit/`
- `tests/regression/`
- `tests/validation/`
- `validation_cases/`

## Livrable recommande apres relecture

La synthese finale peut tenir en une page avec quatre sections :

- Ce que fait HydroModPy et ses principaux flux.
- Comment le depot est structure en couches et en points d'entree.
- Quelles sont les zones critiques ou les plus complexes.
- Quelles ameliorations auraient le meilleur ratio impact / effort.

Si cette synthese est difficile a ecrire, cela signale en general qu'il manque encore une comprehension des interfaces entre couches, plus qu'une connaissance du detail des fichiers.
