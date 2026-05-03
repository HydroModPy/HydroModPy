# Audit des illustrations de la documentation

Date: 2026-05-03

Ce document fait le point sur la couverture visuelle de la documentation
Read the Docs et propose une strategie d'illustration plus systematique.

## Synthese

La documentation HydroModPy ne manque pas d'images au sens strict. Elle manque
surtout d'une strategie de repartition des images entre les pages.

Les assets existent deja en grand nombre, en particulier dans:

- `docs/readthedocs/source/_static/capability_gallery/`
- `docs/readthedocs/source/_static/workflows/`
- `examples/projects/09_capability_gallery/`
- `examples/projects/09_comparison_workflow/outputs/`

Le probleme principal est ailleurs:

- les images sont tres concentrees dans la capability gallery et quelques pages
  de workflows;
- les pages scientifiques longues, surtout autour de MODFLOW, restent trop
  textuelles;
- les pages de prise en main n'utilisent pas assez les figures deja generees;
- les pages d'architecture ont beaucoup de diagrammes UML, mais peu de vues
  synthetiques pour lecteur non specialiste;
- il n'existe pas encore de contrat editorial disant quel type de page doit
  avoir quel type d'illustration.

## Mesure rapide

Inventaire realise sur `docs/readthedocs/source`, en excluant les pages
generees de l'API et les pages de cas auto-generees de la capability gallery.

| Indicateur | Valeur |
| --- | ---: |
| Pages `.rst` totales | 455 |
| Pages manuelles hors API/cas generes | 210 |
| Pages de contenu manuel ou longues landing pages | 175 |
| Pages manuelles avec au moins une illustration | 47 |

Repartition par grande section:

| Section | Pages manuelles | Pages illustrees | Illustrations |
| --- | ---: | ---: | ---: |
| `architecture` | 74 | 27 | 53 |
| `scientific` | 78 | 11 | 30 |
| `getting_started` | 12 | 4 | 9 |
| `user_guide` | 24 | 5 | 14 |
| `api` | 12 | 0 | 0 |

Lecture de ces chiffres:

- `architecture` est la section la plus diagrammee, mais avec une forte
  dominance UML.
- `scientific` est sous-illustree par rapport a sa densite conceptuelle.
- `getting_started` et `user_guide` sont les endroits ou une illustration
  donne le plus de valeur immediate aux nouveaux lecteurs.
- `api` peut raisonnablement rester peu illustree, sauf pour les pages
  d'entree de module.

Assets statiques disponibles dans `docs/readthedocs/source/_static`:

| Type | Nombre |
| --- | ---: |
| PNG | 284 |
| JSON | 108 |
| CSV | 34 |
| SVG | 5 |

Par dossier:

| Dossier | Fichiers |
| --- | ---: |
| `capability_gallery` | 408 |
| `workflows` | 24 |
| `concepts` | 3 |

Conclusion pratique: il faut d'abord mieux reutiliser et organiser les assets
existants avant de produire massivement de nouvelles images.

## Pages longues sans illustration

Ces pages sont prioritaires car elles demandent un effort de lecture eleve sans
point d'appui visuel.

Priorite haute:

- `docs/readthedocs/source/scientific/solvers/modflow-package-semantics-and-boundary-conditions.rst`
- `docs/readthedocs/source/scientific/solvers/modflow-governing-equation-and-cvfd-formulation.rst`
- `docs/readthedocs/source/scientific/solvers/worked-modflow-case-linearized-unconfined-recharge-periodic-1d.rst`
- `docs/readthedocs/source/scientific/solvers/worked-modflow-case-linearized-unconfined-drainage-1d.rst`
- `docs/readthedocs/source/scientific/solvers/worked-modflow-case-dupuit-fixed-head-1d.rst`
- `docs/readthedocs/source/getting_started/read-real-basin-run.rst`
- `docs/readthedocs/source/user_guide/results-and-exports.rst`
- `docs/readthedocs/source/user_guide/solver-process-map.rst`
- `docs/readthedocs/source/user_guide/data/retrieval-workflow.rst`

Priorite moyenne:

- `docs/readthedocs/source/scientific/calibration/calibration-methods.rst`
- `docs/readthedocs/source/scientific/foundations/groundwater-flow-problem-definition.rst`
- `docs/readthedocs/source/scientific/solvers/field-to-cell-parameter-transfer.rst`
- `docs/readthedocs/source/scientific/solvers/meshes-and-numerical-methods.rst`
- `docs/readthedocs/source/scientific/solvers/flow/modflow/modflow6.rst`
- `docs/readthedocs/source/scientific/solvers/flow/modflow/modflownwt.rst`
- `docs/readthedocs/source/user_guide/capability-matrix.rst`

Cas particulier:

- `docs/readthedocs/source/getting_started/workspace-layout.rst` est long et
  sans illustration. Une figure `workspace -> project -> run -> store -> exports`
  serait plus efficace que du texte supplementaire.

## Pages longues avec seulement une illustration

Ces pages ne sont pas vides visuellement, mais elles n'ont pas encore assez de
supports pour leur ambition scientifique:

- `docs/readthedocs/source/scientific/hydrology/recharge-and-surface-exchange-semantics.rst`
- `docs/readthedocs/source/scientific/solvers/modflow6-vs-modflownwt-scientific-comparison.rst`
- `docs/readthedocs/source/scientific/solvers/mesh-and-discretization-strategies.rst`
- `docs/readthedocs/source/getting_started/comparison-output-reading-order.rst`
- `docs/readthedocs/source/scientific/solvers/vertical-representation-and-storage-assumptions.rst`

## Pages deja bien illustrees

Ces pages peuvent servir de reference de style:

- `docs/readthedocs/source/scientific/hydrology/simulated-active-network.rst`
- `docs/readthedocs/source/scientific/streams_and_seepage/conceptual-model.rst`
- `docs/readthedocs/source/scientific/streams_and_seepage/nancon-k-sweep-results.rst`
- `docs/readthedocs/source/user_guide/workflows/simulation.rst`
- `docs/readthedocs/source/user_guide/workflows/calibration.rst`
- `docs/readthedocs/source/getting_started/simulation-walkthrough.rst`
- `docs/readthedocs/source/getting_started/comparison-workflow.rst`
- `docs/readthedocs/source/capability_gallery/cases/nancon_transient_nwt.rst`

Elles montrent trois usages efficaces:

- expliquer un pipeline avec un diagramme;
- publier des resultats numeriques stables;
- guider le lecteur dans un ordre de lecture des sorties.

## Typologie d'illustrations a adopter

### 1. Cartes mentales de section

Objectif: repondre rapidement a "ou suis-je dans la documentation ?"

Usage recommande:

- pages landing de `scientific`;
- pages landing de `user_guide`;
- pages familles comme `MODFLOW Flow Family`;
- pages architecture overview.

Format:

- PlantUML si le schema est un graphe de concepts ou de responsabilites;
- SVG si le schema doit etre plus pedagogique et plus stable visuellement.

Exemples a creer:

- `TOML -> schema -> process -> solver -> result store -> figures`;
- `field -> mesh/cell transfer -> solver package -> output field`;
- `basin data -> forcing -> MODFLOW packages -> diagnostics`.

### 2. Schemas scientifiques conceptuels

Objectif: expliquer un mecanisme physique ou numerique avant les equations.

Usage recommande:

- equations MODFLOW;
- CVFD/DISV;
- recharge, EVT, drainage;
- storage confine/libre;
- seepage et active network.

Format:

- SVG ou PNG genere par script;
- eviter UML pour les schemas physiques.

Exemples a creer:

- cellule CVFD avec flux face par face, stockage, recharge, EVT, drainage;
- profil vertical `head`, `top`, `bottom`, surface EVT, extinction depth;
- bassin avec entree recharge, perte EVT, sortie drainage, hydrogramme.

### 3. Figures de resultats

Objectif: montrer ce que produit vraiment une simulation.

Usage recommande:

- worked cases;
- pages de prise en main;
- pages de comparaison;
- pages `results-and-exports`.

Format:

- PNG versionnes dans `_static`;
- source de generation conservee dans `examples/projects/09_capability_gallery`
  ou un manifest equivalent.

Figures types:

- hydrogramme;
- budget cumule;
- carte piezometrique;
- profondeur de nappe;
- flux de drainage;
- overlay reseau hydrographique observe/simule;
- panneau multi-run de sensibilite.

### 4. Inventaires visuels des donnees disponibles

Objectif: montrer au lecteur ce qu'il peut extraire, pas seulement ce qui est
affiche dans une page.

Usage recommande:

- `read-real-basin-run`;
- `results-and-exports`;
- documentation API projet/run;
- pages capability gallery.

Format:

- tableau compact;
- petit schema `catalog -> run -> fields/timeseries/budgets/geometries/metrics`;
- eventuellement captures de dataframe uniquement si elles sont stables.

Exemple pour Nancon:

- entrees de provenance: ETP, recharge, debit observe, runoff;
- geometries: bassin, buffer, contour, reseau reference, reseau genere;
- rasters: DEM, fill;
- champs solver: head;
- champs derives: water table elevation/depth, accumulation flux, outflow drain,
  seepage areas;
- budgets: constant head, drains, ET, recharge, storage, faces;
- series temporelles: debit simule bassin, debit observe station;
- metriques: hydrographic overlap, active-network diagnostics, performance
  hydrologique.

### 5. Panneaux comparatifs multi-simulation

Objectif: documenter un choix scientifique ou une sensibilite, pas seulement un
cas isole.

Usage recommande:

- effet EVT;
- effet conductivite;
- MF6 vs NWT;
- XT3D on/off;
- maillage structure vs DISV/Gmsh;
- methodes de calibration.

Format:

- grille 2x2 ou 3x2;
- meme bassin, meme periode, meme echelle de couleur;
- differences absolues ou relatives si l'effet est subtil.

## Priorites proposees

### P0: rendre visibles les sorties et le cas Nancon

Objectif: corriger le manque le plus visible pour un lecteur.

Actions:

- Ajouter directement dans `getting_started/read-real-basin-run.rst` trois a
  cinq figures Nancon deja disponibles:
  - contexte hydrographique;
  - overlay reseau observe/simule;
  - piezometrie;
  - hydrogramme;
  - budget.
- Ajouter un schema compact de l'inventaire recuperable:
  `Run -> fields / timeseries / budgets / geometries / metrics`.
- Faire de `read-real-basin-run` une vraie page "voici ce que je peux lire",
  pas seulement une page de renvoi vers la galerie.

### P0: documenter l'effet EVT par plusieurs simulations

Objectif: rendre visible la question scientifique "que change l'activation de
EVT ?"

Mini-etude recommandee:

| Run | Intention |
| --- | --- |
| No EVT | reference sans perte evapotranspirative explicite |
| Baseline EVT | activation actuelle `active_sinks_sources = ["recharge", "etp"]` |
| Shallow EVT | extinction plus faible ou surface plus proche |
| Deep EVT | extinction plus profonde |

Sorties a publier dans cet ordre:

1. budget `et` et `drains`;
2. hydrogramme exutoire;
3. moyenne bassin de `watertable_depth`;
4. cartes de difference `watertable_depth`, `outflow_drain`, `seepage_areas`;
5. overlay reseau observe/simule seulement apres les diagnostics hydrologiques.

Pourquoi cet ordre: si on commence par l'overlay de reseau, on risque de cacher
le mecanisme principal. L'effet EVT se lit d'abord dans la partition du bilan
hydrique, puis dans la dynamique de nappe, puis dans les sorties de surface.

### P0: illustrer MODFLOW comme chaine de traduction

Objectif: passer de "texte sur MODFLOW" a "HydroModPy traduit des choix en
packages MODFLOW".

Pages a traiter:

- `scientific/solvers/flow/modflow-family.rst`
- `scientific/solvers/modflow-package-semantics-and-boundary-conditions.rst`
- `scientific/solvers/modflow-governing-equation-and-cvfd-formulation.rst`
- `scientific/solvers/modflow6-vs-modflownwt-scientific-comparison.rst`

Figures recommandees:

- carte de famille: `common concepts -> MF6 path -> NWT path -> comparisons`;
- cellule bilan MODFLOW: stockage, conductances, RCH, EVT, DRN;
- schema package stack HydroModPy: `Flow contract -> RCH/EVT/DRN/STO/NPF/TDIS`;
- decision tree `MF6 vs NWT`;
- tableau visuel `HydroModPy parameter -> FloPy/MODFLOW package -> output to inspect`.

### P1: rendre les exports et resultats visibles

Objectif: montrer le contenu du workspace au lieu de seulement l'expliquer.

Pages:

- `user_guide/results-and-exports.rst`
- `getting_started/workspace-layout.rst`
- `user_guide/data/retrieval-workflow.rst`

Figures recommandees:

- schema `workspace.duckdb + run store + zarr/netcdf/csv/png`;
- exemple de lecture `catalog -> run -> field/timeseries/budget`;
- matrice `donnee -> API -> figure possible -> format export`.

### P1: renforcer les worked cases analytiques

Objectif: rendre les cas de verification plus lisibles.

Pages:

- Dupuit 1D;
- recharge periodique 1D;
- drainage 1D.

Figures recommandees:

- schema du domaine et des conditions aux limites;
- courbe analytique vs numerique;
- erreur ou indicateur de convergence;
- tableau minimal des hypotheses.

### P2: harmoniser architecture et user guide

Objectif: eviter que les diagrammes UML soient reserves aux developpeurs.

Actions:

- Ajouter sur les landing pages architecture des "cartes de lecture" plus
  simples que les classes UML.
- Ajouter sur `user_guide/index.rst` une figure de navigation:
  `concepts -> workflows -> results -> gallery`.
- Ajouter une vignette resultat sur chaque page de workflow majeure.

## Contrat editorial propose

Chaque page narrative devrait respecter au moins une de ces regles:

- Page de prise en main: au moins une figure dans le premier tiers de la page.
- Page scientifique longue: un schema conceptuel avant ou juste apres les
  equations.
- Worked case: une figure du setup, une figure de resultat, une figure ou table
  de validation/diagnostic.
- Page d'architecture: un diagramme d'orientation puis, si necessaire, UML plus
  detaille.
- Page d'exports/resultats: un inventaire visuel des objets recuperables.

Regle anti-decoration:

- une illustration doit repondre a une question explicite;
- la legende doit dire comment lire la figure;
- les echelles, unites, supports spatiaux et periode temporelle doivent etre
  visibles quand la figure est numerique;
- toute figure de resultat doit avoir une source de generation identifiable.

## Organisation des assets

La structure actuelle est bonne pour les galeries, mais elle doit etre etendue
aux figures transversales.

Proposition:

```text
docs/readthedocs/source/_static/
  capability_gallery/       # cas generes et manifests existants
  workflows/                # figures pedagogiques de workflows
  concepts/                 # schemas scientifiques SVG/PNG
  scientific/
    modflow/
    evt_sensitivity/
    analytical_cases/
  architecture/
    overview/
```

Regles de nommage:

- prefixe de domaine: `modflow_`, `evt_`, `workspace_`, `run_inventory_`;
- suffixe de role: `_concept`, `_pipeline`, `_comparison`, `_result_panel`;
- pas de noms generiques comme `figure1.png`.

## Outillage a ajouter

### Audit automatique

Un premier outil read-only existe maintenant dans
`tools/docs_visual_audit.py`. Il:

- compte les pages longues sans `figure`, `image` ou `uml`;
- ignore `api/generated` et `capability_gallery/cases`;
- produit une table Markdown;
- peut etre lance manuellement avant une passe documentaire.

Commande:

```bash
python tools/docs_visual_audit.py
```

Ce n'est pas forcement un test bloquant. Un rapport non bloquant est plus utile
tant que la documentation est en transition.

### Panneaux multi-run

Etendre `tools/doc_gallery` ou ajouter un outil voisin pour publier des panels
comparatifs:

- plusieurs runs;
- une meme variable;
- memes echelles;
- exports PNG + JSON de provenance.

Cas cible prioritaire:

- `nancon_evt_sensitivity`.

### Captures/inventaires API

Ajouter un script de generation d'inventaire pour un run:

```text
run_inventory.json
run_inventory.rst
run_inventory_panel.png ou .svg
```

Il doit lister:

- fields;
- timeseries;
- budgets;
- geometries;
- metrics;
- provenance inputs;
- figures disponibles.

## Plan de travail propose

### Phase 1: reutiliser les figures existantes

Effort faible, impact fort.

1. Inserer les figures Nancon dans `read-real-basin-run`.
2. Inserer les figures Nancon pertinentes dans le worked case EVT/NWT.
3. Ajouter une figure de flux dans `results-and-exports`.
4. Ajouter une carte de lecture dans `modflow-family`.

### Phase 2: creer les schemas scientifiques manquants

Effort moyen.

1. Cellule bilan MODFLOW/CVFD.
2. Profil EVT.
3. Package stack RCH/EVT/DRN/STO/NPF.
4. Schema workspace/catalog/run store.
5. Schemas des trois worked cases analytiques.

### Phase 3: produire les panels de resultats manquants

Effort plus eleve car il faut executer ou figer plusieurs simulations.

1. Sensibilite EVT Nancon.
2. MF6 vs NWT sur support comparable.
3. Analytical cases avec courbes numerique/analytique.
4. Methodes XT3D/DISV quand le contexte scientifique le justifie.

### Phase 4: rendre l'audit recurrent

Effort faible.

1. Ajouter `tools/docs_visual_audit.py`.
2. Documenter les regles dans `docs/developers/README.md`.
3. Eventuellement ajouter un job non bloquant dans la CI documentaire.

## Critere de reussite

La documentation sera vraiment amelioree quand un lecteur pourra, en moins de
deux minutes:

- voir comment un TOML devient une simulation;
- voir quelles donnees un run contient;
- voir quelles figures prouvent qu'une simulation a fonctionne;
- comprendre ce que change une option MODFLOW importante;
- retrouver la page qui va plus loin sans lire tout le manuel.

L'objectif n'est donc pas "plus d'images partout". L'objectif est une chaine
visuelle stable:

```text
concept -> configuration -> execution -> sorties -> diagnostic -> decision
```
