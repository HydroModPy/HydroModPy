# Audit et proposition pour un laboratoire regional

## Besoin vise

Le besoin exprime ici n'est pas seulement de refaire des batches de maillage. Il s'agit de disposer d'un cadre reproductible pour explorer des cas complexes sur plusieurs bassins d'une meme region, avec des regroupements stables par familles de sites, puis de faire tourner dessus des questions de robustesse, de sensibilite, de comparaison de solveurs ou de scenarios.

En pratique, on cherche un niveau d'organisation au-dessus du "cas unique" et au-dessus du "batch technique mono-objectif", sans recreer une pile parallele complete.

## Ce qui existe deja dans le depot

### 1. Une preselection regionale multi-bassins existe deja

La brique la plus structurante est `hydromodpy_annex/preprocess/catchment_identification_scan/`.

Ce workflow sait deja :

- scanner un MNT regional,
- produire une table multi-exutoires,
- delimiter plusieurs bassins,
- filtrer par surface cible,
- utiliser des familles de selection deja utiles pour une logique de laboratoire :
  - `all_min_area`,
  - `headwater_target`,
  - `scan_global`,
  - filtrage implicite par ordre de Strahler dans les configs de scenario.

Les configs versionnees montrent deja un echantillonnage regional par familles et echelles :

- `config_s3_10km2.toml`
- `config_headwater_100km2.toml`
- `config_s3_100km2.toml`
- `config_1000km2.toml`

Le point important : la logique "aller chercher plusieurs bassins dans une zone regionale selon une politique explicite" existe deja. C'est le premier pilier du laboratoire.

### 2. Le batch maillage est deja factorise comme une boucle sur des sites

Le launcher `launchers/mesh_catchment/` fournit deja une execution batch sur une table d'exutoires.

Le pattern est propre :

- le batch ne reimplemente pas un moteur different ;
- il derive un sous-workspace par `outlet_id` ;
- il reutilise le runtime mono-catchment ;
- il ecrit un manifest CSV incremental ;
- il supporte `continue_on_error` ;
- il verifie la couverture raster avant de lancer la boucle.

Autrement dit, le depot sait deja executer un meme protocole sur une liste de sites.

Le contrat de reporting existe aussi deja via :

- `launchers/mesh_catchment/batch_reporting.py`
- `launchers/mesh_catchment_batch_manifest.csv`
- `tests/unit/launchers/test_mesh_catchment_batch.py`

Le deuxieme pilier du laboratoire existe donc deja : un moteur batch par site, robuste, manifest-driven, et testable.

### 3. La notion de familles repetables de sites existe deja

Le travail fait pour les maillages ne se limite pas a produire plusieurs sorties. Il a deja introduit une structuration conceptuelle utile pour un laboratoire regional :

- `examples/mesh_gallery/`
- `tools/doc_gallery/import_mesh_bundle.py`
- `tools/doc_gallery/sync_mesh_catchment_runs.py`
- `docs/readthedocs/source/capability_gallery/mesh.rst`

Cette chaine formalise deja :

- des familles de cas,
- des echelles,
- des variantes,
- des sites repetes dans une meme famille,
- un manifest de provenance,
- des vues regionales,
- une projection documentaire stable.

Les champs `case_family_key`, `case_family_label`, `site_tabs_group_key`, `site_tabs_order` montrent qu'une logique de "cluster documentaire" est deja en place, au moins pour les maillages.

Le troisieme pilier existe donc aussi : une facon stable de regrouper plusieurs sites sous une meme famille regionale.

### 4. La robustesse mono-site multi-variantes existe deja

Le launcher `launchers/method_comparison/` apporte la brique complementaire pour un laboratoire :

- plusieurs variantes sur un meme site,
- memes observables,
- metriques agregables,
- figures comparatives,
- manifest JSON,
- rapport Markdown.

Il couvre deja des questions tres proches du besoin :

- comparaison de solveurs,
- comparaison de backends,
- comparaison de scenarios,
- comparaison sur mesh partage ou non,
- extraction d'observables `point`, `outlet` et `map`.

Exemples utiles :

- `run_method_comparison_headwater_100km2_outlet_2_backends.toml`
- `run_method_comparison_headwater_100km2_outlet_2_mf6_transient_scenarios.toml`

Le quatrieme pilier existe donc : une facon propre de tester la robustesse ou les differences de comportement sur un site donne.

### 5. Une couche "campagne" transverse existe deja

Le dossier `examples/projects/launcher_simulation/realistic_campaign/` est tres important pour la generalisation.

Il apporte deja :

- un inventaire de cas multi-familles,
- un runner sequentiel,
- des filtres par `tier`, `scale`, `launcher`, `region`, `tags`,
- un rapport JSON de campagne,
- une separation saine entre orchestration et launchers metier.

Le depot a donc deja commence a sortir d'une logique "cas isole" vers une logique "campagne d'exploration".

Le point fort de cette brique : elle ne remplace pas les launchers, elle les orchestre.

## Diagnostic

### Ce qui est deja mature

- La selection regionale initiale de bassins.
- Le batch par sites pour le maillage.
- Les manifests de sortie.
- Le regroupement en familles repetables.
- La comparaison de variantes sur un site.
- Une premiere couche transverse de campagne.

### Ce qui manque pour un vrai laboratoire regional

- Il n'existe pas encore d'objet central "site de laboratoire".
- Il n'existe pas encore d'objet central "cluster regional".
- Le passage scan regional -> liste de sites -> campagnes reste partiellement manuel.
- `realistic_campaign` orchestre des cas deja enumeres a la main ; il ne sait pas encore etendre automatiquement une recette sur un catalogue de sites.
- `realistic_campaign` reste un runner sequentiel simple ; c'est un bon noyau V1, mais pas encore une vraie couche de production regionale.
- Les manifests restent separes par etape :
  - scan regional,
  - batch maillage,
  - comparaison de methodes,
  - campagne de simulation.
- Il n'existe pas encore de table unique regroupant les descripteurs utiles d'un site :
  - echelle,
  - famille de selection,
  - ordre de Strahler,
  - aire,
  - complexite du maillage,
  - fragmentation geologique,
  - statut des runs,
  - chemins vers bundles et rapports.
- Il n'existe pas encore de synthese agregee a l'echelle d'un cluster :
  - taux d'echec,
  - temps de calcul,
  - dispersion des metriques,
  - sensibilite aux variantes,
  - familles de sites les plus fragiles.

### Conclusion d'audit

Le depot ne part pas de zero. Au contraire, presque toutes les briques necessaires existent deja, mais elles sont encore empilees en chaine outillage plutot qu'unifiees en un meme objet de travail.

La bonne generalisation n'est donc pas "creer un nouveau mega-launcher". La bonne generalisation est de relier proprement les briques existantes autour d'un contrat commun de site et de cluster.

## Proposition de generalisation

### Principe

Generaliser ce qui a ete fait pour les maillages en introduisant un "laboratoire regional" comme couche d'orchestration et de metadata, pas comme nouveau moteur numerique.

Le principe propose :

- le site est l'unite atomique d'execution ;
- le cluster est l'unite regionale d'analyse ;
- la recette est l'unite de protocole ;
- les launchers existants restent les moteurs d'execution.

### Recommandation structurante

S'appuyer sur `realistic_campaign/` comme noyau d'orchestration transverse, puis lui ajouter une capacite d'expansion automatique depuis un catalogue de sites.

Cela evite :

- de dupliquer la logique d'execution,
- de recreer un batch special simulation,
- d'avoir une nouvelle famille de configs a maintenir en parallele.

## Contrat minimal propose

### 1. Un catalogue canonique de sites

Introduire un artefact central du type `site_catalog.csv` ou `site_catalog.jsonl`.

Colonnes minimales recommandees :

- `site_id`
- `region_id`
- `cluster_id`
- `outlet_id`
- `x_outlet_m`
- `y_outlet_m`
- `basin_area_km2`
- `scale_bucket`
- `selection_family`
- `strahler_order`
- `tags`
- `mesh_bundle_dir`
- `mesh_summary_json`
- `anchors_file`
- `status_mesh`
- `status_simulation`
- `status_comparison`

Ce catalogue doit etre produit a partir du scan regional, puis enrichi progressivement apres maillage et apres simulation.

### 2. Une logique de cluster explicite

Le cluster ne doit pas etre une boite noire statistique en V1. Il vaut mieux commencer par des clusters deterministes et lisibles.

Clusters recommandes en premiere version :

- par echelle : `10km2`, `100km2`, `1000km2`
- par famille de selection : `headwater`, `s3`, `all_min_area`
- par region de travail
- par classe de complexite maillage
- par classe de fragmentation geologique

La bonne logique est en deux temps :

- clustering amont a faible cout, base sur le scan regional ;
- reclassement aval plus riche, base sur `mesh_summary.json`.

Exemples de descripteurs deja disponibles ou faciles a deriver :

- `basin_area_km2`
- ordre de Strahler
- nombre de cellules
- nombre d'aretes riviere
- nombre d'interfaces geologiques
- surface du domaine
- indicateurs QA du maillage

### 3. Une campagne parametrable par cluster

Au lieu d'enumerer tous les cas a la main, la campagne doit pouvoir dire :

- je prends tel cluster,
- je garde N sites representatifs,
- je deroule telle recette,
- je collecte les manifests et les metriques.

Autrement dit, il faut passer de :

- "liste de cas statique"

a :

- "recette x selection de sites".

### 4. Une recette de laboratoire reutilisable

Une recette de laboratoire pourrait combiner plusieurs etapes deja existantes :

1. maillage de reference ;
2. simulation de reference ;
3. variantes de robustesse ;
4. comparaison inter-variantes ;
5. synthese par cluster.

Exemples de recettes :

- robustesse maillage
- robustesse solver/backend
- robustesse forcages
- robustesse heterogeneites geologiques
- robustesse conditions aux limites

## Architecture cible recommandee

### Etape A - Selection regionale

Reutiliser `catchment_identification_scan` pour produire la population initiale de sites.

Sortie cible :

- table d'exutoires,
- polygones de bassins,
- diagnostic regional,
- premier `site_catalog` initialise.

### Etape B - Enrichissement maillage

Reutiliser `mesh_catchment_batch` pour produire les maillages des sites selectionnes.

Sortie cible :

- bundles maillage,
- `mesh_catchment_batch_manifest.csv`,
- enrichissement du `site_catalog` avec metriques de maillage et chemins utiles.

### Etape C - Campagne de simulation et comparaison

Etendre `realistic_campaign` pour qu'il sache etendre une recette sur un ensemble de sites selectionnes depuis le catalogue.

Exemples de selection :

- tous les sites d'un cluster,
- 5 sites par cluster,
- seulement les sites ayant un maillage valide,
- seulement les sites "complexes".

### Etape D - Synthese regionale

Ajouter une couche d'agregation finale qui consolide :

- manifests de batch maillage,
- manifests de comparaison,
- rapports de campagne,
- metriques de performance et de robustesse.

Livrables cibles :

- un rapport regional JSON ou CSV,
- un rapport Markdown par cluster,
- quelques figures de synthese,
- une liste de cas a promouvoir dans la capability gallery.

## Positionnement propose des briques

### Ce qui doit rester tel quel

- `catchment_identification_scan`
- `mesh_catchment`
- `method_comparison`
- `tools/doc_gallery`

### Ce qui doit devenir la base de generalisation

- `examples/projects/launcher_simulation/realistic_campaign/`

### Ce qu'il faut ajouter

- un catalogue canonique de sites,
- une logique de clusters,
- une expansion automatique des campagnes par site,
- une consolidation des metriques a l'echelle regionale.

## Pourquoi cette approche est preferable

Elle capitalise sur l'existant le plus solide :

- le scan regional fait deja la selection,
- le batch maillage fait deja la boucle par site,
- `method_comparison` fait deja la robustesse mono-site,
- `realistic_campaign` fait deja l'orchestration multi-cas.

Elle limite aussi le risque de dispersion :

- un seul moteur d'execution par usage,
- une seule couche transverse de campagne,
- une seule source de verite pour les sites,
- une seule logique de cluster partagee entre maillage, simulation et comparaison.

## Feuille de route recommandee

### Phase 1 - Generalisation legere

- creer le `site_catalog` a partir des sorties du scan regional ;
- ajouter un script d'enrichissement depuis les manifests maillage ;
- etendre `realistic_campaign` avec une expansion simple par `site_catalog`.

Resultat attendu :

- on peut lancer une meme recette sur un groupe de sites sans enumerer chaque cas a la main.

### Phase 2 - Laboratoire regional exploitable

- ajouter les `cluster_id` et les descripteurs de complexite ;
- consolider les metriques de comparaison et de robustesse ;
- produire un rapport par cluster et un rapport global.

Resultat attendu :

- on sait dire quelles familles de sites sont robustes, fragiles, couteuses ou atypiques.

### Phase 3 - Boucle de curation

- choisir les cas les plus representatifs ou les plus interessants ;
- publier seulement une petite partie dans la capability gallery ;
- garder le laboratoire comme espace d'exploration plus large.

Resultat attendu :

- la gallery reste curatee,
- le laboratoire reste l'espace d'investigation systematique.

## Recommendation finale

La generalisation la plus defendable est :

1. ne pas repartir d'un outil "maillage only" ;
2. prendre `realistic_campaign` comme point d'ancrage transverse ;
3. lui ajouter un catalogue de sites issu du scan regional ;
4. utiliser les familles et clusters comme unite d'analyse ;
5. laisser les launchers actuels faire le travail metier.

En une phrase : le "laboratoire regional" doit etre pense comme une couche de selection, metadata, orchestration et synthese au-dessus des briques deja en place, pas comme une nouvelle filiere technique concurrente.
