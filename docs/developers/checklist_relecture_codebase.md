# Checklist de relecture du code

Ce document est un compagnon operationnel de `parcours_relecture_codebase.md`. Il est pense pour une relecture reelle du depot : on coche, on note, on identifie les risques, puis on produit une synthese courte.

## Mode d'emploi

- Utiliser cette checklist pendant la lecture, pas apres coup.
- Ne pas essayer de tout cocher en une seule session.
- Produire une note courte par passage : constats, questions, risques.
- Marquer les sujets a approfondir plutot que de bloquer trop tot sur un detail.

## Niveaux de profondeur

### Relecture express

- [ ] J'ai compris l'objectif general du depot.
- [ ] J'ai repere les points d'entree principaux.
- [ ] J'ai identifie les zones coeur et les zones satellites.
- [ ] J'ai une premiere liste de 5 a 10 questions techniques.

### Relecture standard

- [ ] J'ai suivi au moins un flux executable de bout en bout.
- [ ] J'ai relu les couches coeur du depot.
- [ ] J'ai identifie les contrats implicites importants.
- [ ] J'ai une vue sur la couverture tests et validation.
- [ ] J'ai une synthese ecrite en une page.

### Relecture approfondie

- [ ] J'ai compare au moins deux parcours d'execution differents.
- [ ] J'ai inspecte les abstractions entre processus et solveurs.
- [ ] J'ai analyse les points numeriquement sensibles.
- [ ] J'ai releve les dettes structurelles avec priorisation.
- [ ] J'ai propose des ameliorations concretes et defendables.

## Preparation

- [ ] J'ai lu `README.md`.
- [ ] J'ai lu `ARCHITECTURE.md`.
- [ ] J'ai lu `docs/developers/CLI.md`.
- [ ] J'ai ouvert `hydromodpy/__main__.py`.
- [ ] J'ai repere les packages principaux dans `hydromodpy/`.
- [ ] J'ai repere les principaux launchers dans `launchers/`.
- [ ] J'ai note les dossiers a ne pas confondre avec le coeur actif : wrappers de compatibilite, annex, binaire, docs generees.

## Passage 1 - Vue systeme

- [ ] Je peux expliquer en 5 lignes ce que fait HydroModPy.
- [ ] Je peux distinguer bibliotheque, launchers, tests, validation et exemples.
- [ ] Je sais ou commence un run pilote par TOML.
- [ ] Je sais ou se trouvent les principales sorties.
- [ ] Je peux nommer les grandes couches : donnees, spatial, process, solveur, simulation, analyse.

Livrable attendu :

- [ ] Une carte rapide des couches du depot.

## Passage 2 - Points d'entree et execution

- [ ] J'ai lu `launchers/process_simulation/launcher.py`.
- [ ] J'ai parcouru `launchers/method_comparison/`.
- [ ] J'ai parcouru `launchers/model_calibration/`.
- [ ] J'ai parcouru `launchers/mesh_catchment/`.
- [ ] J'ai ouvert au moins un projet sous `examples/projects/`.
- [ ] J'ai suivi la chaine config -> runtime -> execution -> sorties.
- [ ] J'ai repere les objets pivots du run.

Questions a trancher :

- [ ] Comment les entrees TOML sont-elles resolues en objets ?
- [ ] Ou se fait l'aiguillage entre cas d'usage et backends ?
- [ ] Quelles parties relevent de l'orchestration et non du coeur metier ?

Livrable attendu :

- [ ] Un schema simple du flux d'execution principal.

## Passage 3 - Infrastructure coeur

- [ ] J'ai lu `hydromodpy/core/config/`.
- [ ] J'ai lu `hydromodpy/core/workspace/`.
- [ ] J'ai lu `hydromodpy/core/state/`.
- [ ] J'ai parcouru `hydromodpy/core/time/`.
- [ ] J'ai repere les utilitaires transverses de `hydromodpy/core/tools/`.
- [ ] J'ai lu `hydromodpy/simulation/`.
- [ ] J'ai distingue planification, adaptation, execution et forcing.

Questions a trancher :

- [ ] Les objets de config ont-ils des responsabilites nettes ?
- [ ] Le cycle de vie d'un run est-il explicite ?
- [ ] L'etat de runtime est-il lisible ou diffuse ?
- [ ] Les chemins workspace et output sont-ils centralises proprement ?

Red flags :

- [ ] Etat modifie a de nombreux endroits sans contrat clair.
- [ ] Resolution de chemins diffuse ou dupliquee.
- [ ] Couplage fort entre orchestration et logique metier.

## Passage 4 - Domaine spatial et donnees

- [ ] J'ai parcouru `hydromodpy/spatial/domain/`.
- [ ] J'ai parcouru `hydromodpy/spatial/field/`.
- [ ] J'ai parcouru `hydromodpy/spatial/geographic/`.
- [ ] J'ai parcouru `hydromodpy/spatial/mesh/`.
- [ ] J'ai parcouru `hydromodpy/data/` au moins par familles de variables.
- [ ] J'ai regarde `hydromodpy/watershed/`.
- [ ] J'ai repere les objets qui representent le bassin, le maillage et les champs.

Questions a trancher :

- [ ] Comment une donnee source devient-elle un objet interne exploitable ?
- [ ] Ou sont les contrats entre formats source et representations Python ?
- [ ] Quelles familles de donnees ont le plus de logique metier ?
- [ ] Quelles zones pilotent la qualite du maillage et du domaine calcule ?

Red flags :

- [ ] Meme concept represente par trop d'objets sans frontiere claire.
- [ ] Contrats de donnees implicites ou faiblement valides.
- [ ] Conversion raster / vecteur / mesh difficile a suivre.

Livrable attendu :

- [ ] Une carte des objets spatiaux et de leurs transformations.

## Passage 5 - Processus physiques

- [ ] J'ai parcouru `hydromodpy/process/flow/`.
- [ ] J'ai parcouru `hydromodpy/process/forcing/`.
- [ ] J'ai parcouru `hydromodpy/process/hydrology/`.
- [ ] J'ai parcouru `hydromodpy/process/transport/`.
- [ ] J'ai identifie les abstractions de `hydromodpy/process/prototype/`.

Questions a trancher :

- [ ] Quelles sont les entrees et sorties contractuelles d'un processus ?
- [ ] Qu'est-ce qui est solver-agnostic et qu'est-ce qui est backend-specifique ?
- [ ] Les hypotheses physiques importantes sont-elles explicites ?
- [ ] Les forcages et conditions aux limites sont-ils modelises proprement ?

Red flags :

- [ ] Logique de solveur qui fuit dans les objets de processus.
- [ ] Contrats d'unites ou conventions non explicites.
- [ ] Processus differents qui partagent du code sans abstraction claire.

## Passage 6 - Solveurs et algorithmes

- [ ] J'ai parcouru `hydromodpy/solver/prototype/`.
- [ ] J'ai parcouru `hydromodpy/solver/modflow_common/`.
- [ ] J'ai compare `hydromodpy/solver/modflow_nwt/` et `hydromodpy/solver/modflow6/`.
- [ ] J'ai parcouru `hydromodpy/solver/boussinesq/`.
- [ ] J'ai repere le role de `hydromodpy/solver/utils/`.
- [ ] J'ai repere les adaptations de maillage ou de format vers les solveurs.

Questions a trancher :

- [ ] Quel est le contrat minimal entre runtime et solveur ?
- [ ] Quelles hypotheses numeriques sont critiques ?
- [ ] Quels parametres changent le comportement ou la stabilite ?
- [ ] Comment les differents solveurs restent-ils alignes fonctionnellement ?
- [ ] Ou se trouvent les zones les plus couteuses en calcul ou les plus fragiles ?

Verification algorithmique :

- [ ] Je peux nommer l'inconnue principale du solveur ou du schema.
- [ ] Je peux expliquer les principales conditions aux limites.
- [ ] Je peux decrire les sources, puits et forcages.
- [ ] Je peux citer les cas limites evidents.
- [ ] Je sais quels tests ou validations encadrent ce comportement.

Red flags :

- [ ] Hypotheses mathematiques non documentees.
- [ ] Cas limites absents des tests.
- [ ] Duplication importante entre backends.
- [ ] Conversions implicites d'unites ou de conventions numeriques.

Livrable attendu :

- [ ] Une note par solveur : role, contrat, risques, tests associes.

## Passage 7 - Analyse, sorties et reporting

- [ ] J'ai parcouru `hydromodpy/analysis/display/`.
- [ ] J'ai parcouru `hydromodpy/analysis/postprocess/`.
- [ ] J'ai repere la place de `hydromodpy/analysis/calibration/`.
- [ ] J'ai verifie le lien entre sorties de run et outils d'analyse.
- [ ] J'ai regarde si les objets de reporting reutilisent proprement le runtime.

Questions a trancher :

- [ ] Les sorties sont-elles structurees de maniere coherente ?
- [ ] Les formats de sortie sont-ils stables et testables ?
- [ ] Le code d'analyse est-il separable du code d'execution ?

## Passage 8 - Tests, regression et validation

- [ ] J'ai parcouru `tests/unit/`.
- [ ] J'ai parcouru `tests/regression/`.
- [ ] J'ai parcouru `tests/validation/`.
- [ ] J'ai parcouru `validation_cases/`.
- [ ] J'ai repere les marqueurs de tests et leur usage via `hmp test`.
- [ ] J'ai identifie quelles zones critiques sont bien protegees.
- [ ] J'ai identifie quelles zones critiques semblent peu couvertes.

Questions a trancher :

- [ ] Les tests unitaires couvrent-ils les contrats utiles ou seulement des details locaux ?
- [ ] Les regressions protegent-elles les workflows officiels ?
- [ ] Les validations scientifiques sont-elles reliees explicitement aux solveurs concernes ?
- [ ] Les cas de reference sont-ils faciles a relancer et a comprendre ?

Red flags :

- [ ] Gros volume de tests mais faible couverture des zones sensibles.
- [ ] Validation scientifique isolee du code de production.
- [ ] Scenarios regression tres relies a des artefacts opaques.

Livrable attendu :

- [ ] Une carte simple de confiance : fort, moyen, faible par grande zone.

## Checklist par module

A reutiliser pour n'importe quel dossier ou sous-package :

- [ ] Je peux resumer la responsabilite du module en une phrase.
- [ ] Je connais ses entrees principales.
- [ ] Je connais ses sorties principales.
- [ ] Je sais de quels modules il depend.
- [ ] Je sais quels modules dependent de lui.
- [ ] J'ai repere 1 a 3 classes ou fonctions pivots.
- [ ] J'ai trouve les tests les plus pertinents.
- [ ] J'ai note les conventions implicites a surveiller.
- [ ] J'ai note les points a approfondir plus tard.

## Questions transverses a garder ouvertes

- [ ] Quels packages sont actifs et lesquels sont surtout des facades de compatibilite ?
- [ ] Quelle est la vraie frontiere entre coeur stable et orchestration de cas d'usage ?
- [ ] Quels objets servent de pivot entre donnees, spatial, process et solveur ?
- [ ] Quels points du depot ont la plus forte sensibilite scientifique ou numerique ?
- [ ] Quelles zones cumulent complexite, faible couverture et fort impact metier ?

## Synthese finale

Quand la relecture est terminee, verifier que je peux repondre clairement a ces questions :

- [ ] Que fait HydroModPy en pratique ?
- [ ] Comment un run traverse-t-il les couches du depot ?
- [ ] Quelles sont les 5 zones les plus critiques du code ?
- [ ] Quelles sont les 5 zones les plus claires et robustes ?
- [ ] Quelles sont les 3 dettes techniques les plus importantes ?
- [ ] Quelles ameliorations auraient le meilleur ratio impact / effort ?

## Trame de compte-rendu

Copier-coller possible pour une note de synthese :

```md
# Relecture HydroModPy

## 1. Vue d'ensemble
- Role du depot :
- Flux principal :
- Points d'entree :

## 2. Zones solides
- 

## 3. Zones sensibles
- 

## 4. Questions ouvertes
- 

## 5. Priorites de travail
- Court terme :
- Moyen terme :
- Long terme :
```
