# Audit des couches - version pedagogique

Date: 2026-04-12

Ce document reformule `audit_code_utilite_couches_2026-04-12.md` avec un objectif simple:

- expliquer ce que veut dire l'audit;
- montrer ce qui pose probleme;
- proposer une lecture simple du depot.

## L'idee en une phrase

Le depot ne semble pas rempli de code inutile.

Le vrai sujet est plutot celui-ci:

**du code utile existe, mais il n'est pas range de facon assez lisible entre le noyau, les workflows, l'I/O, la visualisation et le legacy.**

## Comment lire le depot simplement

On peut lire le projet comme une machine avec 6 zones.

| Zone | Question simple | Ce qu'on y met |
|---|---|---|
| `core` | "qu'est-ce qui calcule vraiment ?" | solveurs, processus physiques, coeur calibration |
| `workflows` | "qu'est-ce qui pilote un run complet ?" | simulation, calibration, method comparison |
| `io` | "qu'est-ce qui lit et ecrit ?" | config, workspace, loaders, readers, writers |
| `display` | "qu'est-ce qui montre les resultats ?" | plots, postprocess, reporting, viewers |
| `legacy` | "qu'est-ce qu'on garde pour ne pas casser l'ancien ?" | compatibilite, anciens namespaces, objets historiques |
| `support` | "qu'est-ce qui prouve, documente ou aide a maintenir ?" | tests, validation_cases, examples, tools |

## Ce que dit l'audit, sans jargon

### 1. Le moteur principal est la

Le coeur utile du produit est bien dans `hydromodpy/`.

En particulier:

- `hydromodpy/process/`
- le coeur de `hydromodpy/solver/`
- `hydromodpy/analysis/calibration/core/`

Ce sont les endroits ou vivent les calculs et les objets metier.

### 2. Les "launchers" ne sont pas seulement des boutons de lancement

Le nom `launchers/` laisse penser a une couche mince qui ferait juste:

- lire un fichier,
- appeler le bon module,
- lancer l'execution.

Mais dans les faits, une partie de `launchers/` fait plus que cela:

- prepare les runs;
- assemble des briques;
- choisit des contrats de sortie;
- pilote un workflow complet.

Donc l'audit dit:

**ce code est utile, mais il devrait s'appeler "workflow" plutot que "launcher".**

### 3. Le public voit trop de choses au meme niveau

Aujourd'hui, si on regarde la surface publique, on voit melanges:

- le noyau;
- des workflows;
- des couches historiques;
- des wrappers de compatibilite.

Le probleme n'est pas que ces morceaux existent.
Le probleme est qu'ils sont exposes presque au meme rang.

Pour un nouvel utilisateur, cela brouille la reponse a trois questions:

- quel est le point d'entree normal ?
- quel est le point d'entree historique ?
- quel est le point d'entree de workflow ?

### 4. Certaines zones techniques melangent trop de roles

Le meilleur exemple est `hydromodpy/solver/utils/mesh/gmsh_grid/`.

Dans cette meme zone, on trouve:

- des algorithmes de maillage;
- de l'echange de donnees;
- de la visualisation interactive;
- des cas de revue.

Tout cela est utile, mais ce n'est pas la meme chose.

L'audit dit donc:

**il faut separer ce qui calcule, ce qui exporte, ce qui visualise et ce qui sert a la revue.**

## Le diagnostic en tableau

| Question | Reponse courte |
|---|---|
| Le code ecrit est-il globalement utile ? | Oui, plutot oui. |
| Le probleme principal est-il le volume ? | Non. |
| Le probleme principal est-il le classement ? | Oui. |
| Le noyau est-il identifiable ? | Oui, mais il est entoure de couches trop visibles. |
| Les launchers sont-ils de simples wrappers ? | Non, pas toujours. |
| Le legacy doit-il disparaitre tout de suite ? | Non. Il faut surtout l'isoler symboliquement et techniquement. |

## Ce qu'il faut comprendre en priorite

### Ce que je te propose de garder comme lecture mentale

1. `core` = ce qui fait les calculs
2. `workflows` = ce qui organise un run reproductible
3. `io` = ce qui lit et ecrit
4. `display` = ce qui montre
5. `legacy` = ce qu'on garde pour compatibilite
6. `support` = ce qui teste, valide, documente

### Ce que je te propose de changer

Pas forcement le code tout de suite.

D'abord, il faut changer la facon de **nommer** et **exposer** les couches:

- rendre `workflows` visible comme couche a part;
- rendre `legacy` explicite;
- reduire la surface publique par defaut;
- ne plus laisser croire que `launchers/` est juste de la CLI.

## Lecture par dossiers

| Dossier / zone | Comment le lire aujourd'hui | Comment il faudrait le lire |
|---|---|---|
| `hydromodpy/process` | coeur metier | coeur metier |
| `hydromodpy/solver` | coeur + utilitaires divers | coeur solveur, avec sous-zones plus nettes |
| `hydromodpy/simulation` | embryon de workflow canonique | workflow canonique |
| `launchers/process_simulation` | launcher | workflow de simulation a migrer |
| `launchers/model_calibration` | launcher | workflow de calibration |
| `launchers/method_comparison` | launcher | workflow de comparaison |
| `hydromodpy/data` | data + un peu d'orchestration | I/O et adapters, plus clairement separes |
| `hydromodpy/analysis/display` | visualisation | visualisation |
| `hydromodpy/config` | package standard | compat / legacy |
| `hydromodpy/modeling` | package standard | compat / legacy |
| `hydromodpy/watershed` | package standard | legacy historique |
| `tests`, `validation_cases`, `examples`, `tools` | volume du depot | support, preuve, documentation executable |

## Cible simple

La cible peut se resumer comme suit:

| Niveau | Contenu |
|---|---|
| API publique courte | quelques imports canoniques dans `hydromodpy` |
| Workflows explicites | `hydromodpy.workflows.simulation`, `hydromodpy.workflows.calibration`, `hydromodpy.workflows.method_comparison` |
| Noyau | `process`, `solver`, `spatial`, `analysis.calibration.core` |
| Bordure technique | `io`, `workspace`, `config loaders`, readers/writers |
| Visualisation | `display`, `postprocess`, reporting |
| Compatibilite | `hydromodpy.compat` ou `hydromodpy.legacy` |

## Pourquoi c'est utile

Si cette separation devient lisible:

- un nouvel arrivant comprend plus vite ou coder;
- un utilisateur externe sait quels imports sont canoniques;
- le legacy reste supporte sans polluer la lecture du noyau;
- les workflows deviennent des objets de premier rang, au lieu d'etre caches sous `launchers/`.

## Visualisation associee

Voir le schema:

- `reporting/audit_code_utilite_couches_schema_2026-04-12.svg`

## Si je le reformule encore plus simplement

Aujourd'hui, le depot ressemble a une maison ou:

- la salle des machines existe bien;
- la salle de controle existe bien;
- le garage des anciennes pieces existe bien;
- mais les portes sont mal etiquetees.

La proposition n'est pas de demolir la maison.
La proposition est de **renommer les portes, isoler le legacy, et faire apparaitre les workflows comme une vraie piece du systeme**.
