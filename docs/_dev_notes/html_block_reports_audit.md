# Audit - production HTML par blocs

Date: 2026-05-24

Note 2026-05-26: les chemins `hydromodpy/spatial/site_selection/html_report.py`,
`plan_report.py`, `report_blocks.py`, `figures.py` et `reporting.py` cites dans
les sections historiques ont ete remplaces par le sous-package
`hydromodpy/spatial/site_selection/reports/` (`html.py`, `plan.py`,
`blocks.py`, `figures.py`). Le contenu de fond du chantier
HTML reste valable, mais les chemins plats ne sont plus les chemins courants.

Ce document reprend le chantier de production de rapports HTML par blocs. Il
vise a clarifier ce qui existe deja, ce qui reste disperse dans des templates
HTML specifiques, et comment reprendre la migration sans perdre le fil.

## Resume court

Le chantier a maintenant depasse le stade du simple audit. Le socle commun
existe et plusieurs producteurs HTML l'utilisent deja:

- `ReportBlock`, `ReportMetric`, `ReportFigure`, `ReportTable` et `ReportLink`
  decrivent les blocs reutilisables;
- `write_report_page(...)` produit les vues globales `compact`, `standard` et
  `audit`;
- `write_report_page_with_block_variants(...)` produit une vue ou le niveau de
  detail est choisi bloc par bloc;
- l'overview, la site-selection et le rapport calibration reseau/transitoire
  passent par la superstructure commune;
- l'exemple Nancon avec vraies figures produit maintenant une page par blocs et
  les vues globales;
- les figures requises manquantes sont visibles sous forme de placeholder au
  lieu d'etre masquees silencieusement.

Le chantier n'est pas totalement ferme:

- tous les producteurs ne proposent pas encore la selection de niveau bloc par
  bloc;
- le rapport testbed volumineux reste hors migration;
- `network_transient/sections.py` reste present pour compatibilite de tests et
  de helpers, meme si le rendu final passe par les blocs;
- il faut encore faire une revue visuelle humaine et stabiliser une courte
  documentation "comment creer un rapport HTML par blocs".

## Validation plug-and-play au 2026-05-24

Objectif teste: prendre un autre site que Nancon, changer seulement le TOML,
et verifier que la chaine produit les donnees, les figures et les HTML.

Configuration testee:

```text
examples/projects/17_site_selection_workflow/configs/corse_hydrometry_preview_block_probe.toml
```

La configuration ne fixe plus de `data_root` explicite et ne pointe pas vers un
DEM prepare a la main. Elle demande:

- un territoire Corse;
- cinq stations hydrometriques Hub'Eau;
- un DEM IGN Geoplateforme BD ALTI 25 m;
- une production HTML de revue.

Commandes relancees:

```powershell
python -m hydromodpy dev config check examples\projects\17_site_selection_workflow\configs\corse_hydrometry_preview_block_probe.toml
python -m hydromodpy run examples\projects\17_site_selection_workflow\configs\corse_hydrometry_preview_block_probe.toml --dry-run --no-lock
python -m hydromodpy run examples\projects\17_site_selection_workflow\configs\corse_hydrometry_preview_block_probe.toml --no-lock
```

Resultat:

```text
selection_id: corse_hydrometry_preview_block_probe_v2
candidates: 5
selected: 4
rejected: 1
```

Sortie principale:

```text
examples/projects/17_site_selection_workflow/outputs/corse_hydrometry_preview_block_probe_v2/review/index.html
```

Verification HTML:

- 7 groupes de blocs;
- 7 boutons `Compact`;
- 7 boutons `Standard`;
- 7 boutons `Audit`;
- 7 variantes `compact`;
- 7 variantes `standard`;
- 7 variantes `audit`;
- script de bascule par bloc present;
- `site_selection_map.png` produit dans le dossier `review`.

Le manifest expose maintenant le `data_root` effectivement utilise:

```text
examples/projects/17_site_selection_workflow/outputs/corse_hydrometry_preview_block_probe_v2/data
```

Le DEM traite utilise par le run est egalement sous ce dossier de sortie:

```text
examples/projects/17_site_selection_workflow/outputs/corse_hydrometry_preview_block_probe_v2/data/dem/processed/
```

Corrections de code realisees pour rendre ce test autonome:

- le cache DuckDB legacy est adopte meme si `schema_migrations` est vide mais
  que les tables attendues existent;
- le workflow site-selection utilise par defaut `output_root/data` quand le
  TOML ne fournit pas de `data_root`;
- l'extraction du DEM IGN cree le dossier parent avant de deplacer l'archive
  extraite, ce qui corrige le cas Windows ou `shutil.move` echouait avec
  `WinError 3`;
- les erreurs de chargement DEM et hydrometrie remontent maintenant le
  `data_root` et la section TOML a verifier;
- le manifest site-selection garde `workspace_root` et `data_root` dans le bloc
  `input`;
- le generateur Nancon a vraies figures accepte maintenant des chemins et
  libelles en arguments CLI, ce qui reduit le codage en dur.

Tests relances apres ces corrections:

```text
tests/unit/data_managers/test_catalog_extended.py
tests/unit/data_managers/test_geoplateforme_dem_downloader.py
tests/unit/data_managers/test_dem_manager.py
tests/unit/site_selection/test_data_layers.py
tests/unit/site_selection/test_build.py
  34 passed

tests/unit/display/test_report_blocks_html.py
tests/unit/site_selection/test_manifest_report.py
tests/unit/site_selection/test_workflow_plan.py
tests/unit/site_selection/test_synthetic_spatial_review.py
  23 passed

tests/unit/site_selection/test_manifest_report.py
tests/unit/site_selection/test_workflow_plan.py
tests/unit/site_selection/test_build.py
  23 passed
```

Limites restantes:

- le test complet du depot n'a pas ete relance;
- le run Corse signale encore des warnings hydrologiques locaux sur le DEM
  traite, mais ils ne bloquent pas la production des sorties;
- le generateur Nancon a vraies figures reste un exemple specialisation Nancon:
  les libelles et chemins principaux sont configurables, mais les liens
  d'artefacts de calibration et certains fallbacks restent orientes Nancon;
- le rapport testbed n'est pas encore migre vers la superstructure commune.

## Relance site-selection multi-cas

Mise a jour: relance des cas site-selection apres migration HTML par blocs.

Toutes les configurations de `examples/projects/17_site_selection_workflow/configs`
passent le controle:

```powershell
python -m hydromodpy dev config check <config.toml>
```

Cas relances completement et HTML produits:

| Cas | Selection | Rejet | HTML |
| --- | ---: | ---: | --- |
| Bretagne small DEM | 7 | 0 | `outputs/bretagne_hydrometry_50_500_small_v1/review/index.html` |
| Bretagne small BD Topage | 7 | 0 | `outputs/bretagne_hydrometry_50_500_small_bdtopage_v1/review/index.html` |
| Corse hydrometrie | 4 | 1 | `outputs/corse_hydrometry_preview_block_probe_v2/review/index.html` |
| Corse surface | 3 | 2 | `outputs/corse_surface_probe_v1/review/index.html` |
| AURA surface | 20 | 0 | `outputs/aura_area_only_v1/review/index.html` |

Verification des cinq HTML:

- `review/index.html` present;
- `review/site_selection_map.png` present;
- 7 groupes de blocs;
- 7 boutons `Compact`;
- 7 boutons `Standard`;
- 7 boutons `Audit`.

Cas non valide dans cette relance:

- `aura_hydrometry_preview_v1` possede une ancienne sortie HTML globale, mais
  le run actuel n'a pas abouti dans la fenetre de temps disponible. Sa
  configuration utilise `request_extent = "territory"` pour la preparation
  hydrologique, ce qui rend le preview trop lourd. Pour en faire un vrai cas de
  demonstration rapide, il faut le rapprocher du pattern Corse/Bretagne:
  `request_extent = "outlets"` pour la delimitation et
  `map_background_extent = "territory"` pour la carte.

Travaux site-selection restants:

- rendre `auvergne_rhone_alpes_hydrometry_preview.toml` vraiment preview;
- decider si les gros inventaires regionaux doivent etre des exemples
  interactifs ou des jobs longs/nightly;
- ajouter un smoke test optionnel qui verifie, pour les exemples courts, la
  presence des variantes par bloc dans le HTML;
- mettre a jour le README avec la distinction `preview` / `regional full`;
- faire une revue visuelle des cartes produites, notamment lisibilite des
  bassins et symboles station.

## Etat courant au 2026-05-24

### Socle commun

Etat: operationnel.

Fichiers principaux:

```text
hydromodpy/display/report_blocks/model.py
hydromodpy/display/report_blocks/html.py
```

Capacites disponibles:

- blocs avec `block_id`, titre, niveau, statut, metriques, figures, tables,
  liens et warnings;
- ancres HTML par bloc et sommaire automatique;
- navigation globale entre `compact`, `standard`, `audit` et `Par bloc`;
- bascule de niveau bloc par bloc avec boutons `Compact`, `Standard`, `Audit`;
- persistence locale du choix par bloc via `localStorage`;
- figures PNG embarquables ou liees comme fichiers;
- placeholder explicite pour figures requises absentes;
- tables cle-valeur via `key_value_table(...)`;
- liens d'artefacts via `ReportLink`.

### Site-selection

Etat: migre et relance.

Fichiers:

```text
hydromodpy/spatial/site_selection/report_blocks.py
hydromodpy/spatial/site_selection/html_report.py
hydromodpy/spatial/site_selection/plan_report.py
```

Le rapport execute Bretagne a ete regenere:

```text
examples/projects/17_site_selection_workflow/outputs/bretagne_hydrometry_50_500_small_bdtopage_rerun_v1/review/index.html
examples/projects/17_site_selection_workflow/outputs/bretagne_hydrometry_50_500_small_bdtopage_rerun_v1/review/compact/index.html
examples/projects/17_site_selection_workflow/outputs/bretagne_hydrometry_50_500_small_bdtopage_rerun_v1/review/standard/index.html
examples/projects/17_site_selection_workflow/outputs/bretagne_hydrometry_50_500_small_bdtopage_rerun_v1/review/audit/index.html
```

Verification HTML:

- 7 groupes de blocs;
- 7 boutons `Compact`;
- 7 boutons `Standard`;
- 7 boutons `Audit`;
- script de bascule par bloc present;
- carte `site_selection_map.png` toujours referencee et embarquee.

Blocs presents:

```text
selection-identity
selection-strategy
selection-map
selected-sites
rejected-sites
criteria-components
artifact-links
```

### Nancon avec vraies figures

Etat: exemple fonctionnel, non synthetique, relance.

Generateur:

```text
examples/projects/16_nancon_natural_calibration/build_nancon_real_figures_report.py
```

Sorties:

```text
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/web/index.html
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/web_review/compact/index.html
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/web_review/standard/index.html
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/web_review/audit/index.html
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/web_review/by_block/index.html
```

Verification HTML de `by_block/index.html`:

- 6 groupes de blocs;
- 6 boutons `Compact`;
- 6 boutons `Standard`;
- 6 boutons `Audit`;
- script de bascule par bloc present;
- aucune occurrence de `Canut` dans le HTML genere.

Blocs presents:

```text
site-context
spatial-context
hydrographic-network
forcing-flux-context
simulation-outputs
artifacts
```

La separation demandee est appliquee:

- le bloc `Flux, debit observe et forcages` ne contient plus de figure ni de
  metrique simulee;
- les figures observe/simule et les metriques de simulation sont dans
  `Sorties simulation Nancon NWT`;
- le bloc flux reste donc disponible avant lancement de modele.

### Tests relances le 2026-05-24

Commande:

```powershell
python -m pytest -o addopts="" tests\unit\display\test_report_blocks_html.py tests\unit\site_selection\test_manifest_report.py tests\unit\site_selection\test_workflow_plan.py tests\unit\site_selection\test_synthetic_spatial_review.py -q
```

Resultat:

```text
22 passed
```

Controles supplementaires:

- `git diff --check` sur les fichiers touches: OK;
- controle ASCII sur les fichiers Python touches: OK;
- compilation du generateur Nancon: OK.

Les sections suivantes conservent l'audit historique et le plan de migration
ayant servi a la reprise.

## Vocabulaire

### Superstructure

La superstructure est le squelette commun de la page HTML. Elle ne connait pas
la science du rapport. Elle gere seulement:

- le `<html>`, le `<head>`, le style CSS commun et le `<main>`;
- le titre de page et le sous-titre;
- la navigation entre niveaux de detail;
- l'ordre d'affichage des blocs;
- le rendu standard des metriques, figures, tables et warnings;
- le comportement quand une figure requise est manquante;
- les liens relatifs entre `web/index.html` et les artefacts.

Dans le code actuel, cette superstructure est:

```text
hydromodpy/display/report_blocks/html.py
```

Les fonctions centrales sont:

```text
write_report_page(...)
render_report_page(...)
```

### Bloc

Un bloc est une unite logique de rapport. Il ne doit pas etre pense comme une
section HTML arbitraire, mais comme un morceau de sens metier:

- identite du workflow;
- caracterisation du site;
- contexte spatial;
- inventaire des donnees;
- observations disponibles;
- reseau hydrographique;
- forcages et flux;
- maillage;
- solveur;
- fonction objectif;
- classement des candidats;
- artefacts.

Dans le code actuel, un bloc est decrit par:

```text
ReportBlock(
    block_id=...,
    title=...,
    level=...,
    status=...,
    lead=...,
    metrics=(...),
    figures=(...),
    tables=(...),
    warnings=(...),
)
```

Le modele est dans:

```text
hydromodpy/display/report_blocks/model.py
```

### Adaptateur de workflow

Un adaptateur transforme l'etat d'un workflow HydroModPy en liste de
`ReportBlock`. Il contient la logique metier, mais pas le HTML bas niveau.

Exemple deja implemente:

```text
hydromodpy/display/overview/web.py

DataOverviewState
  -> build_overview_blocks(...)
  -> list[ReportBlock]
  -> write_report_page(...)
  -> web/index.html
```

## Pipeline cible

Le pipeline cible devrait etre le meme pour tous les rapports:

```text
etat workflow / manifest / resultats
  -> figures et artefacts produits
  -> build_<workflow>_report_blocks(...)
  -> write_report_page(...)
  -> web/index.html
```

Le point important est que la superstructure HTML reste unique. Chaque domaine
ne fournit que ses blocs.

## Ce qui est deja fait

### 1. Modele generique de blocs

Fichier:

```text
hydromodpy/display/report_blocks/model.py
```

Objets disponibles:

- `ReportMetric`: une valeur labellee, avec unite et note optionnelle;
- `ReportFigure`: une figure attendue, requise ou optionnelle;
- `ReportTable`: une table plate;
- `ReportBlock`: un bloc complet compose de metriques, figures, tables et
  warnings.

Niveaux de detail:

- `compact`;
- `standard`;
- `audit`.

Statuts de blocs:

- `available`;
- `partial`;
- `empty`;
- `not_applicable`.

Limite actuelle: le modele ne connait pas encore les liens explicites, les
ancres, la table des matieres, les groupes de blocs, ni les relations vers les
artefacts sources. On peut contourner une partie de cela avec des tables, mais
ce n'est pas encore propre.

### 2. Rendu HTML commun

Fichier:

```text
hydromodpy/display/report_blocks/html.py
```

Fonctions:

- `write_report_page(...)`;
- `render_report_page(...)`.

Ce rendu sait afficher:

- l'en-tete de page;
- une navigation `compact / standard / audit`;
- les metriques;
- les figures;
- les tables;
- les warnings.

Evolution reprise dans ce chantier:

- les figures requises absentes affichent maintenant un placeholder;
- les figures optionnelles absentes restent masquees.

Test associe:

```text
tests/unit/display/test_report_blocks_html.py
```

### 3. Premier adaptateur: overview

Fichier:

```text
hydromodpy/display/overview/web.py
```

Fonctions principales:

```text
write_overview_web_report(...)
write_overview_review_web_reports(...)
build_overview_blocks(...)
```

Blocs overview actuels:

| Bloc | Role | Niveau actuel |
| --- | --- | --- |
| `workflow_header` | Identite workflow, bassin, periode, workspace | `compact` |
| `spatial_context` | Localisation, surface, CRS, cartes contexte | `compact/standard/audit` |
| `data_inventory` | Familles de donnees chargees ou demandees | `standard/audit` |
| `observation_inventory` | Stations et chroniques observees | `standard/audit` |
| `forcing_context` | Recharge et pompages | `compact/standard/audit` |
| `artifact_links` | Liste des chemins de sortie | `audit` |

Sorties:

```text
web/index.html
web_review/compact/index.html
web_review/standard/index.html
web_review/audit/index.html
```

La production `web_review` est activee par:

```text
HMP_OVERVIEW_HTML_REVIEW_LEVELS=1
```

Tests associes:

```text
tests/unit/display/test_overview_web_blocks.py
```

## Ce qui n'est pas encore migre

### Site selection

Fichiers:

```text
hydromodpy/spatial/site_selection/html_report.py
hydromodpy/spatial/site_selection/plan_report.py
```

Etat:

- les deux rapports produisent bien des HTML;
- les donnees sont deja structurees dans des manifestes;
- mais chaque fichier contient son propre template HTML, son propre CSS et sa
  propre logique de rendu.

Pourquoi c'est un bon candidat de migration:

- le rapport "plan" est simple: strategie, territoire, DEM, hydrologie,
  criteres, sorties prevues;
- le rapport execute a deja des tables naturelles: sites retenus, sites
  rejetes, decisions, composants de criteres, evidence d'observation;
- la carte de controle peut devenir un `ReportFigure`;
- les liens d'artefacts peuvent devenir un bloc `artifact_links`.

Blocs cibles proposes:

| Bloc cible | Contenu |
| --- | --- |
| `selection_identity` | selection_id, date, mode, output_root |
| `selection_strategy` | principe, profil, mode candidats, observation principale |
| `territory_context` | region, departement, bbox, couches contexte |
| `dem_and_hydrology` | source DEM, resolution, correction DEM, flow algorithm |
| `selection_criteria` | ruleset, hard reject, warning, soft score |
| `selection_map` | carte de controle |
| `selected_sites` | table des sites retenus |
| `rejected_sites` | table des sites rejetes |
| `observation_evidence` | evidence hydrometrie, piezometrie, contexte |
| `artifact_links` | manifestes, CSV, JSONL, PNG |

### Calibration reseau/transitoire

Fichiers:

```text
hydromodpy/calibration/reporting/network_transient_html.py
hydromodpy/calibration/reporting/network_transient/sections.py
```

Etat:

- les figures et les artefacts sont bien generes;
- le rapport a deja des sections logiques:
  - probleme de calibration;
  - configuration spatiale et temporelle;
  - recharge imposee;
  - contexte bassin et permanent cible;
  - fonction objectif;
  - cartes de drainage;
  - chroniques de flux;
- mais `sections.py` construit encore une page HTML complete avec CSS propre;
- les metriques sont rendues sous forme de fragments HTML maison.

Blocs cibles proposes:

| Bloc cible | Contenu |
| --- | --- |
| `calibration_problem` | parametres calibres, equation objectif, contrat artefacts |
| `candidate_ranking` | meilleur candidat, cible, echecs, J minimum |
| `site_characterization` | site_id, cellules, periode, CRS si disponible |
| `forcing_flux_context` | recharge, Q steady, Q moyen, chroniques |
| `hydrographic_network` | masque reseau, longueur, distance, cartes drainage |
| `objective_landscape` | cartes objectif, coupes 1D, score table |
| `artifact_links` | package truth, score table, manifest, figures |

Point favorable: la generation des figures est deja separee du rendu HTML. On
peut donc migrer le rendu sans refaire les figures.

### Testbeds et syntheses

Fichier principal:

```text
examples/projects/10_testbed_workflow/reporting/generate_testbed_web_report.py
```

Etat:

- le rapport fonctionne;
- il est volumineux et specialise;
- il agrege beaucoup de cas, matrices et comparaisons.

Recommandation:

- ne pas commencer par ce fichier;
- attendre que `site_selection` et `network_transient` aient stabilise le
  contrat de blocs;
- ensuite extraire des blocs de type `testbed_summary`, `case_matrix`,
  `comparison_links`, `metric_table`.

### Markdown vers HTML

Fichier:

```text
tools/render_markdown_report_html.py
```

Etat:

- c'est un outil de consultation locale pour un Markdown donne;
- il n'est pas prioritaire pour la migration par blocs;
- il peut rester separe, car il transforme un document texte existant et non un
  etat de workflow structure.

## Correspondance avec les blocs metier attendus

Tu te souvenais de blocs par unite logique de code: caracterisation de site,
contexte, flux, reseau hydrographique, etc. Voici ou ils existent aujourd'hui.

| Bloc metier attendu | Etat actuel | Commentaire |
| --- | --- | --- |
| Caracterisation du site | Partiel dans `spatial_context` et calibration | A rendre explicite avec `site_characterization` |
| Contexte spatial | Present dans overview | A reutiliser dans site-selection |
| Inventaire des donnees | Present dans overview | Bon premier modele |
| Observations | Present dans overview, custom dans site-selection | A uniformiser |
| Reseau hydrographique | Partiel, pas de bloc dedie | A creer comme bloc central |
| Flux / forcages | Present dans `forcing_context`, custom dans calibration | A unifier sous `forcing_flux_context` |
| Maillage | Absent du socle overview | Present ailleurs sous forme de figures ou metadata |
| Solveur | Absent du socle overview | A ajouter pour rapports simulation/calibration |
| Calibration / objectif | Custom dans network transient | A migrer en blocs |
| Artefacts | Present dans overview audit | A generaliser |

Le trou principal est donc le reseau hydrographique comme bloc explicite. Il
apparait aujourd'hui soit comme carte dans `spatial_context`, soit comme cartes
de drainage dans le rapport calibration, mais il n'a pas encore son contrat
dedie.

## Architecture cible proposee

### Regle 1 - Un seul renderer HTML

Tous les rapports devraient finir par:

```python
write_report_page(
    output_path=...,
    title=...,
    subtitle=...,
    blocks=blocks,
    current_level=...,
    level_links=...,
)
```

Les modules metier ne devraient plus construire eux-memes:

- `<html>`;
- `<style>`;
- `<section>`;
- grilles CSS;
- cartes de metriques HTML maison.

### Regle 2 - Des adaptateurs par domaine

Chaque domaine garde sa logique pres de son code metier, mais retourne des
`ReportBlock`.

Proposition:

```text
hydromodpy/display/report_blocks/
  model.py
  html.py

hydromodpy/display/overview/web.py
  build_overview_blocks(...)

hydromodpy/spatial/site_selection/report_blocks.py
  build_site_selection_plan_blocks(...)
  build_site_selection_result_blocks(...)

hydromodpy/calibration/reporting/network_transient/blocks.py
  build_network_transient_blocks(...)
```

### Regle 3 - Les blocs doivent etre nommes par sens metier

Eviter les noms bases sur la mise en page:

```text
panel_1
wide_grid
left_column
summary_card
```

Preferer:

```text
site_characterization
hydrographic_network
forcing_flux_context
candidate_ranking
objective_landscape
artifact_links
```

### Regle 4 - Les niveaux de detail filtrent le contenu

La meme famille de blocs peut exister en trois niveaux:

- `compact`: ce qu'il faut pour comprendre en 30 secondes;
- `standard`: rapport normal lisible;
- `audit`: chemins, manifestes, diagnostics, sources, warnings complets.

Exemple:

| Bloc | Compact | Standard | Audit |
| --- | --- | --- | --- |
| `site_characterization` | bassin, surface, periode | + CRS, exutoire, methode bassin | + chemins sources |
| `hydrographic_network` | carte principale | + metriques distance/longueur | + fichiers masque/distance |
| `forcing_flux_context` | recharge moyenne, Q moyen | + chroniques | + sources et fenetres |
| `artifact_links` | masque | masque | liste complete |

## Manques techniques du socle

Le socle actuel suffit pour overview, mais il faudra probablement l'etendre.

### A ajouter probablement

1. Ancres par bloc

Chaque bloc devrait rendre:

```html
<section id="hydrographic_network">
```

Cela permettra une table des matieres et des liens directs.

2. Table des matieres

La superstructure peut construire une navigation a partir de `block_id` et
`title`.

3. Liens et artefacts

Aujourd'hui on encode les chemins dans des tables. Un type explicite serait plus
propre:

```text
ReportLink(label, path, kind)
```

4. Tables cle-valeur

Beaucoup de rapports ont des listes de type `dt/dd`. On peut les rendre comme
des `ReportTable`, mais un petit helper `key_value_table(...)` eviterait la
duplication.

5. Statut visible

`status="partial"` ou `status="empty"` existe dans le modele, mais le rendu ne
met pas encore clairement ces statuts en avant.

6. Contrat de bloc testable

Chaque adaptateur devrait avoir un test qui verifie:

- les `block_id` attendus;
- les blocs absents quand non applicables;
- les figures requises;
- les niveaux `compact`, `standard`, `audit`.

## Plan de reprise recommande

### Etape 1 - Stabiliser le socle

Objectif: rendre `ReportBlock` assez expressif pour migrer un deuxieme rapport.

Actions:

- ajouter des ancres HTML par `block_id`;
- ajouter une table des matieres simple;
- ajouter un helper pour tables cle-valeur;
- rendre les statuts `partial` et `empty` visibles;
- garder le rendu 100% statique et sans dependance JS.

Tests:

```powershell
python -m pytest -o addopts="" tests/unit/display/test_report_blocks_html.py -q
python -m pytest -o addopts="" tests/unit/display/test_overview_web_blocks.py -q
```

### Etape 2 - Migrer le rapport plan-only de site-selection

Pourquoi celui-ci d'abord:

- pas de grosse figure obligatoire;
- pas de resultats candidats;
- donnees dans un seul manifest JSON;
- template actuel assez court.

Action cible:

```text
render_site_selection_plan_html_report(...)
  -> build_site_selection_plan_blocks(...)
  -> write_report_page(...)
```

Blocs minimaux:

- `selection_identity`;
- `selection_strategy`;
- `territory_context`;
- `dem_and_hydrology`;
- `selection_criteria`;
- `planned_outputs`;
- `artifact_links`.

### Etape 3 - Migrer le rapport execute de site-selection

Action cible:

```text
render_site_selection_html_report(...)
  -> build_site_selection_result_blocks(...)
  -> write_report_page(...)
```

Blocs minimaux:

- blocs du plan;
- `selection_map`;
- `selected_sites`;
- `rejected_sites`;
- `observation_evidence`;
- `criteria_components`.

### Etape 4 - Rendre le reseau hydrographique explicite dans overview

Aujourd'hui, le reseau hydrographique observe est une figure optionnelle dans
`spatial_context`. Ce n'est pas assez clair.

Action cible:

- creer `_hydrographic_network_block(...)`;
- y mettre carte, source, nombre d'objets si disponible, warning si absent mais
  demande;
- garder `spatial_context` pour l'emprise, le CRS et le bassin.

### Etape 5 - Migrer calibration reseau/transitoire

Objectif: garder la generation de figures actuelle, mais remplacer le HTML
maison par des blocs.

Action cible:

```text
build_network_transient_html(...)
  -> inspect artefacts
  -> generate figures
  -> build_network_transient_blocks(...)
  -> write_report_page(...)
```

Blocs minimaux:

- `calibration_problem`;
- `candidate_ranking`;
- `site_characterization`;
- `forcing_flux_context`;
- `hydrographic_network`;
- `objective_landscape`;
- `artifact_links`.

### Etape 6 - Seulement ensuite: testbed web synthesis

Ce rapport est trop gros pour servir de premiere migration. Il doit venir apres
stabilisation du modele.

## Verification deja faite

Tests lances pendant la reprise:

```text
tests/unit/display/test_report_blocks_html.py
  1 passed

tests/unit/display/test_overview_web_blocks.py
  3 passed
```

Tests HTML plus larges lances dans l'audit precedent:

```text
tests/unit/calibration/test_network_transient_html_reporting.py
  7 passed

tests/unit/calibration/test_network_transient_html_sections_behavior.py
  5 passed

tests/unit/calibration/test_network_transient_html_helpers.py
  13 passed

tests/unit/site_selection/test_manifest_report.py
  6 passed

tests/unit/analysis/test_testbed_web_report.py
  1 passed
```

## Decision proposee

Pour reprendre efficacement:

1. Ne pas commencer par le rapport de calibration complet.
2. Migrer d'abord `site_selection_plan_html_report` vers `ReportBlock`.
3. Ajouter les ancres et la table des matieres dans la superstructure.
4. Ensuite migrer le rapport site-selection execute.
5. Ensuite seulement decouper le rapport calibration reseau/transitoire en
   blocs metier, en reutilisant ses figures existantes.

Cette sequence permet de solidifier la superstructure sur un cas simple, puis
de l'appliquer a un cas avec carte et tables, avant de toucher au rapport de
calibration plus scientifique.

## Plan d'action operationnel

Ce plan transforme la decision ci-dessus en lots de travail courts. Chaque lot
doit laisser le depot dans un etat testable.

### Lot 0 - Verrouiller le vocabulaire et le perimetre

Objectif: eviter que "HTML par blocs" designe a la fois le rendu visuel, les
figures, les manifestes et la logique metier.

Actions:

- conserver `ReportBlock` comme contrat central;
- nommer les blocs par sens metier, pas par mise en page;
- garder la generation des figures hors de la superstructure;
- decider que le premier producteur migre apres overview sera
  `site_selection_plan_html_report`.

Fichiers concernes:

```text
docs/_dev_notes/html_block_reports_audit.md
hydromodpy/display/report_blocks/model.py
hydromodpy/display/report_blocks/html.py
```

Definition de fini:

- le vocabulaire `superstructure`, `bloc`, `adaptateur` est documente;
- aucune migration lourde n'est commencee avant stabilisation du socle.

### Lot 1 - Renforcer la superstructure commune

Objectif: rendre le renderer commun suffisant pour un vrai deuxieme rapport.

Actions:

- ajouter `id="{block_id}"` sur chaque `<section>`;
- ajouter une petite table des matieres optionnelle;
- rendre les statuts `partial` et `empty` visuellement explicites;
- ajouter un helper pour construire des tables cle-valeur;
- garder le comportement actuel:
  - figure requise absente = placeholder visible;
  - figure optionnelle absente = masquee.

Fichiers concernes:

```text
hydromodpy/display/report_blocks/model.py
hydromodpy/display/report_blocks/html.py
tests/unit/display/test_report_blocks_html.py
```

Tests:

```powershell
python -m pytest -o addopts="" tests/unit/display/test_report_blocks_html.py -q
python -m pytest -o addopts="" tests/unit/display/test_overview_web_blocks.py -q
```

Definition de fini:

- les pages overview existantes restent stables;
- les blocs ont des ancres;
- un rapport peut exposer sa structure sans template HTML metier.

### Lot 2 - Migrer le rapport plan-only de site-selection

Objectif: migrer un rapport simple vers `ReportBlock` sans toucher au cas
execute complet.

Actions:

- creer un module de blocs site-selection, par exemple:

```text
hydromodpy/spatial/site_selection/report_blocks.py
```

- y implementer:

```text
build_site_selection_plan_blocks(plan, manifest_path, output_root)
```

- modifier `render_site_selection_plan_html_report(...)` pour appeler
  `write_report_page(...)`;
- conserver les donnees et le chemin de sortie actuels.

Blocs minimaux:

- `selection_identity`;
- `selection_strategy`;
- `territory_context`;
- `dem_and_hydrology`;
- `selection_criteria`;
- `planned_outputs`;
- `artifact_links`.

Fichiers concernes:

```text
hydromodpy/spatial/site_selection/plan_report.py
hydromodpy/spatial/site_selection/report_blocks.py
tests/unit/site_selection/test_manifest_report.py
tests/unit/site_selection/test_workflow_plan.py
```

Tests:

```powershell
python -m pytest -o addopts="" tests/unit/site_selection/test_manifest_report.py -q
python -m pytest -o addopts="" tests/unit/site_selection/test_workflow_plan.py -q
```

Definition de fini:

- le chemin `review/index.html` ne change pas;
- les tests site-selection existants passent;
- le HTML plan-only ne contient plus de gros template autonome.

### Lot 3 - Migrer le rapport site-selection execute

Objectif: reutiliser les blocs du plan et ajouter les blocs de resultat.

Actions:

- implementer:

```text
build_site_selection_result_blocks(manifest, artifacts, map_path)
```

- transformer la carte de controle en `ReportFigure`;
- transformer les tables `selected`, `rejected`, `decisions`, `components` et
  `evidence` en `ReportTable`;
- garder la generation de la carte dans
  `render_site_selection_map(...)`.

Blocs supplementaires:

- `selection_map`;
- `selected_sites`;
- `rejected_sites`;
- `selection_decisions`;
- `criteria_components`;
- `observation_evidence`.

Fichiers concernes:

```text
hydromodpy/spatial/site_selection/html_report.py
hydromodpy/spatial/site_selection/report_blocks.py
hydromodpy/spatial/site_selection/figures.py
tests/unit/site_selection/test_manifest_report.py
tests/unit/site_selection/test_synthetic_spatial_review.py
```

Tests:

```powershell
python -m pytest -o addopts="" tests/unit/site_selection/test_manifest_report.py -q
python -m pytest -o addopts="" tests/unit/site_selection/test_synthetic_spatial_review.py -q
```

Definition de fini:

- le rapport execute utilise la meme superstructure que l'overview;
- la carte et les tables restent visibles;
- les liens vers artefacts restent relatifs et ouvrables localement.

### Lot 4 - Extraire un vrai bloc reseau hydrographique dans overview

Objectif: rendre explicite le bloc que le rapport doit montrer sur le reseau,
au lieu de le cacher dans `spatial_context`.

Actions:

- ajouter `_hydrographic_network_block(...)` dans
  `hydromodpy/display/overview/web.py`;
- y placer la figure `map_hydrography_data` quand elle existe;
- ajouter des metriques simples si disponibles:
  - source;
  - nombre d'objets ou de stations liees;
  - periode si applicable;
- ajouter un warning si le reseau est demande mais absent;
- retirer la responsabilite "reseau" de `spatial_context`.

Fichiers concernes:

```text
hydromodpy/display/overview/web.py
tests/unit/display/test_overview_web_blocks.py
```

Tests:

```powershell
python -m pytest -o addopts="" tests/unit/display/test_overview_web_blocks.py -q
python -m pytest -o addopts="" tests/unit/display/test_overview_report_panels.py -q
```

Definition de fini:

- `spatial_context` = emprise, bassin, CRS;
- `hydrographic_network` = reseau observe et diagnostics associes;
- les niveaux `compact`, `standard`, `audit` restent coherents.

### Lot 5 - Migrer le rapport calibration reseau/transitoire

Objectif: conserver la production scientifique actuelle, mais remplacer le HTML
fait main par la superstructure commune.

Actions:

- creer:

```text
hydromodpy/calibration/reporting/network_transient/blocks.py
```

- y implementer:

```text
build_network_transient_blocks(
    normalization=...,
    score_rows=...,
    figures=...,
    truth_dir=...,
    score_table=...,
    artifact_report=...,
)
```

- garder `_generate_figures(...)` dans `network_transient_html.py`;
- remplacer `_page(...)` par `write_report_page(...)`;
- garder le manifest `b0_reference_manifest.json`.

Blocs minimaux:

- `calibration_problem`;
- `artifact_contract`;
- `candidate_ranking`;
- `site_characterization`;
- `forcing_flux_context`;
- `hydrographic_network`;
- `objective_landscape`;
- `flow_timeseries`;
- `artifact_links`.

Fichiers concernes:

```text
hydromodpy/calibration/reporting/network_transient_html.py
hydromodpy/calibration/reporting/network_transient/blocks.py
hydromodpy/calibration/reporting/network_transient/sections.py
tests/unit/calibration/test_network_transient_html_reporting.py
tests/unit/calibration/test_network_transient_html_sections_behavior.py
tests/unit/calibration/test_network_transient_html_helpers.py
```

Tests:

```powershell
python -m pytest -o addopts="" tests/unit/calibration/test_network_transient_html_reporting.py -q
python -m pytest -o addopts="" tests/unit/calibration/test_network_transient_html_sections_behavior.py -q
python -m pytest -o addopts="" tests/unit/calibration/test_network_transient_html_helpers.py -q
```

Definition de fini:

- les figures existantes sont toujours generees;
- le manifest de reference reste ecrit;
- le rapport HTML utilise `ReportBlock`;
- les libelles naturels/B0 peuvent etre adaptes bloc par bloc.

### Lot 6 - Nettoyage et convergence

Objectif: reduire les chemins HTML paralleles.

Actions:

- supprimer ou deprecier les helpers HTML metier remplaces;
- documenter le pattern dans une note developpeur courte;
- ajouter un inventaire des producteurs HTML restants;
- decider si le renderer Markdown doit rester separe.

Fichiers concernes:

```text
docs/_dev_notes/html_block_reports_audit.md
hydromodpy/display/report_blocks/
hydromodpy/spatial/site_selection/
hydromodpy/calibration/reporting/network_transient/
tools/render_markdown_report_html.py
```

Definition de fini:

- overview, site-selection et calibration reseau/transitoire partagent la meme
  superstructure;
- les nouveaux rapports savent quel chemin suivre;
- les templates HTML complets dans les modules metier deviennent l'exception.

## Ordre de priorite

Priorite haute:

1. Lot 1 - renforcer la superstructure.
2. Lot 2 - migrer le rapport plan-only site-selection.
3. Lot 3 - migrer le rapport site-selection execute.

Priorite moyenne:

4. Lot 4 - extraire le bloc `hydrographic_network` dans overview.
5. Lot 5 - migrer calibration reseau/transitoire.

Priorite basse:

6. Lot 6 - nettoyage global.
7. Migration des rapports testbed.

## Risques et garde-fous

Risque principal: vouloir migrer tous les rapports en meme temps. Cela rendrait
le diff difficile a verifier et melangerait rendu HTML, science calibration et
site-selection.

Garde-fous:

- un lot = un producteur HTML ou une extension de socle;
- garder les chemins de sortie existants;
- ne pas modifier la generation des figures pendant une migration de rendu;
- ajouter un test de blocs avant de verifier le HTML texte;
- ne pas commencer par `generate_testbed_web_report.py`.

## Avancement de la reprise autonome

Mise a jour: 2026-05-23, apres reprise des lots 1 a 5.

### Fait

- La superstructure `report_blocks` a ete renforcee:
  - ancres HTML par bloc;
  - sommaire automatique;
  - statuts `partial` / `empty` visibles;
  - helper `key_value_table(...)`;
  - liens d'artefacts via `ReportLink`;
  - figures PNG embarquables via `ReportFigure(embed=True)`;
  - placeholder visible pour les figures requises absentes.
- `site_selection_plan_html_report` utilise maintenant `ReportBlock`.
- `site_selection_html_report` utilise maintenant `ReportBlock`.
- Un adaptateur metier site-selection existe:

```text
hydromodpy/spatial/site_selection/report_blocks.py
```

- L'overview possede maintenant un bloc explicite:

```text
hydrographic_network
```

- Le rapport calibration reseau/transitoire utilise maintenant la
  superstructure commune pour le rendu final.
- Un adaptateur metier calibration existe:

```text
hydromodpy/calibration/reporting/network_transient/blocks.py
```

### Tests relances et resultats

```text
tests/unit/display/test_report_blocks_html.py
tests/unit/display/test_overview_web_blocks.py
  5 passed

tests/unit/site_selection/test_manifest_report.py
tests/unit/site_selection/test_workflow_plan.py
  16 passed

tests/unit/calibration/test_network_transient_html_reporting.py
  7 passed

tests/unit/calibration/test_network_transient_html_sections_behavior.py
  5 passed

tests/unit/calibration/test_network_transient_html_helpers.py
  13 passed

tests/unit/site_selection/test_synthetic_spatial_review.py
  2 passed

tests/unit/analysis/test_testbed_web_report.py
  1 passed

examples/projects/16_nancon_natural_calibration/run_synthetic_natural_smoke.py
  OK, rapport ecrit dans %TEMP%/hmp_nancon_natural_smoke_blocks/web/index.html
```

### HTML produits pour verification visuelle

Une passe de generation hors depot a produit les pages suivantes:

```text
%TEMP%/hmp_html_blocks_validation_*/overview/web/index.html
%TEMP%/hmp_html_blocks_validation_*/overview/web_review/compact/index.html
%TEMP%/hmp_html_blocks_validation_*/overview/web_review/standard/index.html
%TEMP%/hmp_html_blocks_validation_*/overview/web_review/audit/index.html
%TEMP%/hmp_html_blocks_validation_*/plan_out/review/index.html
%TEMP%/hmp_html_blocks_validation_*/selection_out/review/index.html
%TEMP%/hmp_nancon_natural_smoke_blocks_user/web/index.html
```

Une passe supplementaire avec figures Nancon reelles a ete ajoutee pour ne pas
confondre validation logicielle et contenu synthetique:

```text
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/web/index.html
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/web_review/compact/index.html
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/web_review/standard/index.html
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/web_review/audit/index.html
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/web_review/by_block/index.html
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/web/figures/
examples/projects/16_nancon_natural_calibration/outputs/nancon_real_figures/nancon_real_figures_report_manifest.json
```

Cette page est generee par:

```powershell
python examples/projects/15_nancon_gauged_context/build_nancon_gauged_context.py
python examples/projects/16_nancon_natural_calibration/build_nancon_real_figures_report.py
```

Elle agrege des figures Nancon existantes et non synthetiques:

- contexte site: carte d'identite observations et inventaire stations;
- contexte spatial: DEM et geologie;
- reseau hydrographique: hydrographie, reference BD Topage, reseau genere,
  differences locales et overlay reseau actif simule;
- flux: debit observe, forcages recharge/runoff, comparaison baseline;
- simulation: carte piezometrique, hydrogramme, bilan en eau.

Limite importante: ce rapport prouve que la superstructure par blocs porte des
figures Nancon reelles, mais il ne constitue pas encore une calibration
naturelle complete avec projection automatique du reseau observe sur maillage et
grille de candidats Nancon scores.

Correction apres revue visuelle:

- la figure `geographic_nancon_identity_card_stats_card.png` de la galerie
  statique contenait encore un libelle `Watershed: Canut` malgre son nom de
  fichier Nancon; le rapport utilise maintenant la figure locale
  `examples/projects/02_nancon_watershed/figures/overview/stats_card.png`;
- le libelle ambigu `Mailles baseline` a ete remplace par
  `Cellules du run de preparation`;
- les vues `compact`, `standard` et `audit` sont generees et reliees depuis la
  page HTML comme dans les autres rapports.
- la vue `compact` ne montre plus les metriques de detail `CRS`,
  `Exutoire X`, `Exutoire Y`, `Fenetre` et `Cellules du run de preparation`;
  ces informations restent en `standard` et `audit`;
- le bloc contexte spatial reprend des figures existantes, sans regeneration:
  `map_regional_context.png` pour la localisation regionale sur DEM et
  `map_dem_context.png` pour le zoom bassin/exutoire.
- le bloc `Flux, debit observe et forcages` ne contient plus de figure ni de
  metrique simulee; il reste disponible avant tout lancement de modele;
- les figures de debit simule ou observe/simule sont maintenant rattachees au
  bloc `Sorties simulation Nancon NWT`, des la vue `compact`, puis conservees
  en `standard` et `audit`;
- le generateur Nancon declare maintenant chaque metrique/table/figure avec un
  niveau minimal (`compact`, `standard`, `audit`) et applique la regle
  monotone `compact <= standard <= audit`;
- une page `by_block` permet de choisir le niveau detail bloc par bloc; le
  choix est gere cote navigateur et conserve en `localStorage`.

Precision systematique:

- pour ce generateur Nancon reel, la monotonie est verifiee automatiquement a
  la generation: tout item present en `compact` doit etre present en
  `standard`, et tout item `standard` doit etre present en `audit`;
- le socle `report_blocks` sait maintenant rendre une page a variantes par
  bloc via `write_report_page_with_block_variants(...)`;
- les autres producteurs HTML deja migres conservent pour l'instant un choix de
  niveau global tant qu'ils ne construisent pas explicitement leurs variantes
  par bloc.

La verification de contenu a confirme:

- presence du `Sommaire`;
- presence des ancres de blocs, par exemple:
  - `id="hydrographic-network"`;
  - `id="selection-strategy"`;
  - `id="selection-map"`;
  - `id="calibration-problem"`;
  - `id="objective-landscape"`;
- image de carte site-selection embarquee en `data:image/png;base64`;
- figures calibration ecrites dans `web/figures`.

Commandes utiles pour reproduire:

```powershell
python -m pytest -o addopts="" tests/unit/display/test_report_blocks_html.py tests/unit/display/test_overview_web_blocks.py -q
python -m pytest -o addopts="" tests/unit/site_selection/test_manifest_report.py tests/unit/site_selection/test_workflow_plan.py tests/unit/site_selection/test_synthetic_spatial_review.py -q
python -m pytest -o addopts="" tests/unit/calibration/test_network_transient_html_reporting.py tests/unit/calibration/test_network_transient_html_sections_behavior.py tests/unit/calibration/test_network_transient_html_helpers.py -q
python examples/projects/16_nancon_natural_calibration/run_synthetic_natural_smoke.py --output-dir $env:TEMP\hmp_nancon_natural_smoke_blocks_user
python examples/projects/15_nancon_gauged_context/build_nancon_gauged_context.py
python examples/projects/16_nancon_natural_calibration/build_nancon_real_figures_report.py
```

### Reste a faire

- Decider si `network_transient/sections.py` doit rester comme compatibilite de
  tests/helpers ou etre progressivement deprecie.
- Reporter la migration de `generate_testbed_web_report.py`: le fichier est
  trop volumineux pour etre migre dans le meme lot.
- Eventuellement ajouter un guide court dans la documentation developpeur:
  "comment creer un rapport HTML par blocs".
- Faire une revue visuelle humaine des pages generees dans `%TEMP%`, notamment:
  - lisibilite du sommaire;
  - densite des metriques;
  - pertinence des libelles du rapport calibration naturel/B0;
  - taille acceptable de la carte site-selection embarquee.
- Appliquer ensuite le meme pattern au rapport testbed, dans un lot separe.
