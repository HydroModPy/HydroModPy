# Feuille de route - migration progressive `launchers` -> `workflows`

Date: 2026-04-12

## But

Clarifier la separation entre:

- `launcher`: point d'entree mince;
- `workflow`: logique de run reutilisable;
- `core`: calculs et objets metier.

Cette feuille de route est volontairement pragmatique: **elle ne demande pas d'arreter les travaux en cours**.

## Reponse courte a la question de pilotage

### Faut-il dissocier `workflow` et `launcher` ?

Oui, progressivement.

La cible est:

- `launcher` = interface d'entree utilisateur;
- `workflow` = orchestration de run reutilisable depuis CLI, scripts, tests et batchs.

### Faut-il tout arreter pour faire cette modification ?

Non.

La bonne strategie est:

- ne pas geler le noyau;
- ne pas lancer de refonte globale immediate;
- changer la direction des nouveaux developpements;
- migrer l'existant par opportunite.

## Regle de conduite immediate

A partir de maintenant, la regle simple est:

1. **nouvelle logique de run** -> aller dans `workflow`, pas dans `launcher`;
2. **nouveau code CLI / parsing / point d'entree** -> peut rester dans `launcher`;
3. **ancien launcher touche pour bugfix ou extension** -> deplacer seulement la partie d'orchestration utile si le cout reste raisonnable;
4. **legacy** -> ne pas l'etendre comme surface normale.

## Ce que cela change au quotidien

### Tu peux continuer normalement si tu travailles sur:

- `hydromodpy/process/`
- `hydromodpy/solver/`
- `hydromodpy/spatial/`
- `hydromodpy/analysis/calibration/core/`
- tests, validation, documentation, examples

Dans ces zones, il n'y a aucune raison de suspendre le travail.

### Tu adaptes seulement la direction si tu travailles sur:

- `launchers/process_simulation/`
- `launchers/model_calibration/`
- `launchers/method_comparison/`
- parties runtime de `hydromodpy/data/`

Ici, la regle devient:

- si tu ajoutes une nouvelle etape de workflow, cree-la hors du launcher;
- si tu corriges un launcher, corrige d'abord, puis extrais si c'est peu risqué;
- ne recree pas de nouvelle logique metier de run dans `launchers/`.

## Cible structurelle

Une cible simple et lisible serait:

```text
hydromodpy/
  workflows/
    simulation/
    calibration/
    method_comparison/

launchers/
  simulation/            # wrappers CLI / compat
  model_calibration/     # wrappers CLI / compat
  method_comparison/     # wrappers CLI / compat
```

Ou, si on veut garder la structure actuelle pendant un temps:

```text
hydromodpy/
  workflows/
    simulation.py
    calibration.py
    method_comparison.py

launchers/
  ...                    # appelle hydromodpy.workflows.*
```

Le point important n'est pas le format exact. Le point important est de rendre visible la difference entre:

- ce qui **pilote** un run;
- ce qui **entre** dans le systeme.

## Phases recommandees

## Phase 1 - Sans casser l'existant

Objectif: changer la direction des nouveaux developpements.

Actions:

- creer le namespace `hydromodpy.workflows`;
- documenter la regle "nouvelle orchestration hors `launchers/`";
- garder `launchers/` comme facade stable;
- ne pas casser les imports ni les commandes existantes.

Critere de fin:

- un nouveau workflow peut etre ajoute sans enrichir `launchers/` en logique metier.

## Phase 2 - Extraction opportuniste

Objectif: profiter des travaux courants pour sortir l'orchestration utile.

Actions:

- a chaque modification importante d'un launcher, extraire la logique reusable;
- laisser dans le launcher:
  - parsing utilisateur;
  - resolution d'entree;
  - appel du workflow;
  - messages CLI;
- deplacer hors du launcher:
  - preparation de session;
  - planification des etapes;
  - couplage entre briques;
  - contrats de sortie de run.

Critere de fin:

- les launchers deviennent significativement plus minces;
- les workflows deviennent appelables depuis tests et scripts sans passer par la CLI.

## Phase 3 - Consolidation

Objectif: rendre la structure evidente pour tout le monde.

Actions:

- documenter les workflows comme couche officielle;
- faire de `launchers/` une couche de compatibilite ou de CLI pure;
- reduire progressivement les reexports historiques.

Critere de fin:

- un nouvel arrivant comprend en lisant l'arborescence ou mettre:
  - le calcul;
  - le workflow;
  - la CLI.

## Priorites concretes dans ce depot

### Priorite 1 - `launchers/model_calibration`

Pourquoi:

- c'est deja un vrai workflow;
- la preparation de session et les contrats de sortie sont riches;
- la separation coeur algo / protocole de run y est assez naturelle.

Cible:

- `analysis.calibration.core` reste coeur algorithmique;
- la preparation de run et l'orchestration vont dans `hydromodpy.workflows.calibration`.

### Priorite 2 - `launchers/process_simulation`

Pourquoi:

- il porte encore beaucoup d'orchestration;
- c'est un point central de lecture de l'architecture.

Cible:

- `hydromodpy.simulation` ou `hydromodpy.workflows.simulation` devient le vrai pilote;
- le launcher devient une facade d'entree.

### Priorite 3 - `launchers/method_comparison`

Pourquoi:

- le workflow est deja identifiable;
- il se prete bien a une extraction propre.

### Priorite 4 - zones de bordure runtime

En particulier:

- `hydromodpy/data/runtime_loader.py`
- `hydromodpy/solver/compatibility.py`

Ces modules sont utiles, mais doivent etre lus comme couche workflow/adapters plutot que comme noyau.

## Ce qu'il ne faut pas faire

### 1. Pas de refactoring global en une fois

Risque:

- bruit massif;
- conflits avec les travaux en cours;
- baisse temporaire de productivite;
- dette de migration inutile.

### 2. Ne pas bloquer les evolutions metier du noyau

Le noyau ne doit pas attendre une refonte d'organisation pour avancer.

### 3. Ne pas deplacer pour deplacer

On ne deplace pas juste pour faire joli.

On deplace quand l'un des gains suivants est reel:

- meilleure reusabilite;
- meilleure testabilite;
- meilleure lisibilite;
- reduction d'un couplage ambigu.

## Regle de decision simple

Quand tu touches un module, pose-toi trois questions:

1. est-ce de la logique d'entree utilisateur ?
2. est-ce de la logique de run reutilisable ?
3. est-ce du calcul metier ?

Puis classe:

| Reponse | Destination |
|---|---|
| entree utilisateur | `launcher` |
| logique de run reutilisable | `workflow` |
| calcul / objets metier | `core` |

## Check-list pour les prochains changements

Avant d'ajouter du code dans `launchers/`, verifier:

- est-ce seulement du parsing ou de la CLI ?
- ce code devra-t-il etre reutilise depuis un test ou un script Python ?
- ce code assemble-t-il plusieurs briques metier ?
- ce code prepare-t-il un run reproductible ?

Si la reponse a l'une des trois dernieres questions est oui, il faut privilegier `workflow`.

## Recommandation de gouvernance

La meilleure discipline d'equipe serait la suivante:

- pas d'arret des travaux en cours;
- pas de chantier monolithique;
- adoption immediate d'une nouvelle regle de placement;
- extraction opportuniste lors des travaux deja prevus.

En version tres simple:

**on ne stoppe pas la machine pour changer les etiquettes des portes; on change les etiquettes au fil des passages, en commencant par les portes les plus confuses.**

## Livrable de decision

Si tu veux transformer cette feuille de route en decision equipe, la version la plus courte est:

1. on ne bloque aucun travail en cours;
2. tout nouveau code d'orchestration va dans `workflows`;
3. `launchers` reste transitoirement la facade d'entree;
4. l'existant migre progressivement par opportunite.
