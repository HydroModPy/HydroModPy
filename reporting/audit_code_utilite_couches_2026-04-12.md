# Audit du code utile, des couches et de l'exposition publique

Date: 2026-04-12

## Perimetre

Cet audit repond a deux questions:

1. quel code parait reellement utile au produit;
2. comment rendre plus lisible la separation entre noyau, workflow, I/O, visualisation et legacy.

Le point clef est le suivant: le depot ne donne pas l'impression d'etre rempli de code gratuit. Le probleme principal est plutot un probleme de **cadrage**: du code utile existe, mais une partie importante de ce code est rangee dans des couches qui ne disent pas clairement leur role.

## Methode

L'audit combine quatre angles:

- lecture de l'architecture cible dans `ARCHITECTURE.md`;
- lecture de la surface publique et des wrappers de compatibilite;
- lecture de modules representatifs dans `hydromodpy/`, `launchers/` et `hydromodpy/solver/utils/mesh/gmsh_grid/`;
- reutilisation des comptages deja produits dans `reports/code_lines/`.

Fichiers de preuve principaux utilises:

- `ARCHITECTURE.md`
- `pyproject.toml`
- `hydromodpy/__init__.py`
- `hydromodpy/simulation/planning/planner.py`
- `launchers/process_simulation/launcher.py`
- `launchers/model_calibration/runtime.py`
- `launchers/model_calibration/property_arrays.py`
- `hydromodpy/analysis/calibration/core/engine.py`
- `hydromodpy/config/__init__.py`
- `hydromodpy/modeling/__init__.py`
- `hydromodpy/watershed/watershed.py`
- `hydromodpy/data/runtime_loader.py`
- `hydromodpy/solver/compatibility.py`
- `hydromodpy/solver/utils/mesh/gmsh_grid/zone_meshing/conformal.py`
- `hydromodpy/solver/utils/mesh/gmsh_grid/catchment_mesh_bundle.py`
- `hydromodpy/solver/utils/mesh/gmsh_grid/interactive_3d_viewer.py`
- `hydromodpy/solver/utils/mesh/gmsh_grid/cases/review_cases.py`

## Resume executif

Conclusion courte:

- le depot contient surtout du code utile;
- le probleme dominant n'est pas "code inutile", mais "code utile melange";
- les couches **workflow** et **legacy** sont exposees au meme niveau que le noyau;
- `launchers/` porte encore une part importante d'orchestration reelle;
- certains sous-ensembles, surtout `solver/utils/mesh/gmsh_grid`, melangent algorithmes, I/O, visualisation et cas de revue.

Le bon axe d'amelioration n'est donc pas une chasse au volume, mais une **taxonomie plus explicite** et une **surface publique plus etroite**.

## Signaux quantitatifs

D'apres `reports/code_lines/code_lines_by_top_folder_head.csv`:

| Dossier | Lignes source non vides |
|---|---:|
| `hydromodpy` | 103718 |
| `tests` | 35853 |
| `examples_legacy` | 20254 |
| `validation_cases` | 16459 |
| `launchers` | 9815 |
| `tools` | 5712 |
| `examples` | 2290 |
| `hydromodpy_annex` | 1735 |

D'apres `reports/code_lines/code_lines_by_language_head.csv`:

| Langage | Lignes source non vides |
|---|---:|
| Python | 195926 |
| Jupyter Notebook | 5355 |
| Shell | 249 |
| PowerShell | 217 |

Lecture utile:

- le noyau `hydromodpy/` est bien dominant;
- `launchers/` est assez gros pour ne pas etre traite comme simple detail de CLI;
- `tests`, `validation_cases`, `examples_legacy` et `tools` representent une masse importante de code de support, de preuve et de migration.

## Findings

### 1. La frontiere d'architecture annoncee n'est pas la frontiere reelle

`ARCHITECTURE.md` pose une regle nette:

`launcher -> simulation -> objets metier`

et presente `simulation/` comme couche d'orchestration.

Dans le code, `hydromodpy/simulation/planning/planner.py` reste tres propre et relativement etroit. En revanche, `launchers/process_simulation/launcher.py` importe, compose et pilote encore une partie significative du workflow reel: chargement, support spatial, preparation de maillage, execution et post-traitement.

Diagnostic:

- `simulation/` ressemble a une couche canonique en devenir;
- `launchers/process_simulation/` contient encore de l'orchestration utile qui devrait vivre dans une couche workflow plus clairement nommee.

### 2. `launchers/model_calibration` est un workflow, pas juste du glue code

Le coeur algorithmique de calibration est correctement place dans `hydromodpy/analysis/calibration/core/engine.py`.

Mais `launchers/model_calibration/runtime.py`, `output_selection.py`, `property_arrays.py` et `reporting.py` ne sont pas de simples wrappers CLI:

- ils preparent des sessions de calibration;
- ils resolvent des contrats de sortie;
- ils branchent des supports hydrauliques et des bundles de maillage;
- ils definissent un workflow reproductible.

Diagnostic:

- ce code est utile et metier;
- il est simplement classe sous `launchers/` alors qu'il correspond a une couche `workflow` ou `workflows/calibration`.

### 3. Le package public expose canonique, workflow et legacy au meme niveau

Trois signaux convergent:

- `pyproject.toml` embarque `hydromodpy*` et `launchers*`;
- `hydromodpy/__init__.py` exporte une surface large;
- plusieurs modules servent explicitement de compatibilite:
  - `hydromodpy/config/__init__.py`
  - `hydromodpy/modeling/__init__.py`
  - `hydromodpy/analysis/display/orchestration.py`

`hydromodpy/watershed/watershed.py` ajoute une couche historique encore preservee pour notebooks et regressions.

Diagnostic:

- en interne, cela aide la migration;
- en externe, cela brouille la lecture de l'API recommandee;
- l'utilisateur ne voit pas nettement ce qui est canonique, ce qui est workflow, et ce qui est legacy.

### 4. `solver/utils/mesh/gmsh_grid` melange quatre familles de responsabilites

Dans le meme sous-arbre coexistent:

- un noyau algorithmique de maillage conforme:
  - `hydromodpy/solver/utils/mesh/gmsh_grid/zone_meshing/conformal.py`
- un connecteur d'echange et de bundle:
  - `hydromodpy/solver/utils/mesh/gmsh_grid/catchment_mesh_bundle.py`
- de la visualisation QA:
  - `hydromodpy/solver/utils/mesh/gmsh_grid/interactive_3d_viewer.py`
- des cas de revue manuelle:
  - `hydromodpy/solver/utils/mesh/gmsh_grid/cases/review_cases.py`

Diagnostic:

- ce sous-ensemble est riche et utile;
- il est cependant classe sous `utils`, ce qui devient trompeur;
- c'est aujourd'hui la zone la moins lisible du depot du point de vue des couches.

### 5. Une partie importante du depot est du code utile de support, pas du noyau produit

`tests/`, `validation_cases/`, `examples/`, `examples_legacy/` et `tools/` ne doivent pas etre lus comme du "gras architectural".

Ils servent a:

- prouver un comportement;
- reproduire des cas;
- documenter des usages;
- supporter une migration;
- generer des artefacts et du reporting.

Diagnostic:

- ce code est utile;
- mais utile comme preuve, documentation executable et outillage;
- il ne faut pas le melanger mentalement avec les algorithmes fondamentaux.

## Ce qui est reellement utile

### 1. Noyau produit

Code utile, central, a maintenir comme coeur canonique:

- `hydromodpy/process/`
- le coeur de `hydromodpy/solver/`
- `hydromodpy/analysis/calibration/core/`
- une partie de `hydromodpy/spatial/`

### 2. Workflow et orchestration

Code utile, necessaire aux executions reproductibles, mais a etiqueter comme tel:

- `hydromodpy/simulation/`
- `launchers/process_simulation/`
- `launchers/model_calibration/`
- `launchers/method_comparison/`
- `hydromodpy/data/runtime_loader.py`
- `hydromodpy/solver/compatibility.py`

### 3. I/O, persistence et contrats de donnees

Code utile de bordure technique:

- `hydromodpy/core/config/`
- `hydromodpy/core/workspace/`
- parties I/O de `hydromodpy/data/`
- readers/writers de maillages et bundles
- export de rapports et de sorties

### 4. Visualisation et reporting

Code utile d'exploitation, d'inspection et de communication:

- `hydromodpy/analysis/display/`
- `hydromodpy/analysis/postprocess/`
- viewers et plotting specialises
- reporting dans certains launchers

### 5. Legacy et compatibilite

Code utile a court et moyen terme, mais qui ne doit pas definir la face publique principale:

- `hydromodpy/config/`
- `hydromodpy/modeling/`
- `hydromodpy/watershed/`
- wrappers de compatibilite disperses

### 6. Support, preuve et documentation executable

Code utile mais non canonique:

- `tests/`
- `validation_cases/`
- `examples/`
- `examples_legacy/`
- `tools/`

## Taxonomie recommandee

La nomenclature la plus parlante, en interne comme en externe, est la suivante:

| Categorie | Sens | Exposition souhaitee |
|---|---|---|
| `core` | algorithmes et objets metier stables | publique |
| `workflows` | orchestration reproductible et protocoles | publique mais separee du noyau |
| `io` | lecture, ecriture, import/export, registry | publique ciblee |
| `display` | visualisation et reporting | publique ciblee |
| `compat` ou `legacy` | maintien de surface historique | publique mais explicitement depreciee |
| `cases` | validation et revue | non canonique |

## Propositions d'amelioration

### A. Clarifier la surface publique

1. Definir une API canonique tres courte dans `hydromodpy/__init__.py`.
2. Sortir les wrappers historiques dans un espace explicite, par exemple:
   - `hydromodpy.compat`
   - ou `hydromodpy.legacy`
3. Marquer `hydromodpy/config`, `hydromodpy/modeling` et `hydromodpy/watershed` comme surfaces de compatibilite, pas comme points d'entree de premier rang.
4. Documenter un tableau simple "imports recommandes / imports toleres / imports legacy".

Effet attendu:

- moins d'ambiguite pour les utilisateurs externes;
- moins de dette d'exposition;
- meilleure lisibilite pour les nouveaux contributeurs.

### B. Sortir les workflows de `launchers/` sans casser la compatibilite

La cible recommandee:

- `hydromodpy.workflows.simulation`
- `hydromodpy.workflows.calibration`
- `hydromodpy.workflows.method_comparison`

`launchers/` peut alors devenir:

- soit un simple point d'entree CLI;
- soit une couche de compatibilite transitoire;
- soit un package mince qui reexporte les workflows pendant la migration.

Effet attendu:

- la couche workflow devient visible comme telle;
- elle n'est plus confondue avec le noyau ni avec la CLI;
- la lecture de l'architecture cible rejoint mieux la realite du code.

### C. Decouper `gmsh_grid` selon les responsabilites

Refactoring recommande a moyen terme:

- `.../mesh/algorithms/zone_meshing`
- `.../mesh/io/exchange`
- `.../mesh/viz/interactive`
- `.../mesh/cases/`

Concretement:

- garder `zone_meshing/` comme noyau algorithmique;
- sortir `catchment_mesh_bundle.py` vers un sous-espace `io` ou `exchange`;
- sortir `interactive_3d_viewer.py` et `extruded_mesh_visualization.py` vers `viz`;
- laisser les cas de revue sous `cases/`.

Effet attendu:

- les couches deviennent lisibles sans ouvrir les fichiers;
- le mot `utils` ne masque plus des briques metier tres differentes.

### D. Distinguer clairement "core calibration" et "workflow calibration"

Structure recommandee:

- `hydromodpy.analysis.calibration.core`
- `hydromodpy.workflows.calibration`

Dans ce schema:

- `engine.py` et les methodes d'optimisation restent dans `core`;
- `runtime.py`, `property_arrays.py`, `output_selection.py` et le reporting de session vont dans `workflows.calibration`.

Effet attendu:

- meilleure separation entre algorithme generique et protocole de run;
- meilleure reusabilite du coeur en script, en notebook et en batch.

### E. Rendre l'exposition legacy visible et gouvernee

Actions recommandees:

1. Ajouter un marquage explicite "legacy" dans les docstrings et la doc.
2. Centraliser la politique de compatibilite dans un document court:
   - surface canonique;
   - surface supportee temporairement;
   - surface deprecable.
3. Ajouter des warnings de deprecation la ou c'est acceptable.
4. Ne plus promouvoir les imports legacy dans les exemples nouveaux.

Effet attendu:

- la compatibilite reste preservee;
- mais elle n'occupe plus le meme rang symbolique que le noyau.

## Plan d'action recommande

### Phase 1 - Lisibilite sans casser l'existant

- documenter la taxonomie `core / workflows / io / display / legacy / cases`;
- ajouter un index d'API publique recommandee;
- reduire les reexports de `hydromodpy/__init__.py`;
- annoter explicitement les modules legacy.

### Phase 2 - Migration structurelle douce

- creer `hydromodpy.workflows.*`;
- rebrancher `launchers/` vers ces nouveaux modules;
- sortir les viewers et bundles hors de `solver/utils/.../gmsh_grid` quand ils ne sont pas algorithmiques.

### Phase 3 - Nettoyage de l'exposition publique

- revoir l'inclusion package de `launchers*`;
- conserver uniquement les wrappers de compatibilite necessaires;
- publier une surface publique courte, stable et defendable.

## Verdict

Le code ecrit est globalement utile. L'audit ne pointe pas une inflation evidente de code sans fonction. En revanche, il pointe un probleme structurel clair:

- du code de workflow utile est encore expose comme si c'etait du noyau;
- du code legacy utile a la migration est encore expose comme si c'etait du canonique;
- certaines zones techniques melangent trop de responsabilites.

La priorite n'est donc pas de supprimer massivement. La priorite est de **renommer, recadrer et re-exposer correctement**.

## Artefact associe

Voir aussi le fichier CSV de synthese:

- `reporting/audit_code_utilite_couches_inventory_2026-04-12.csv`
