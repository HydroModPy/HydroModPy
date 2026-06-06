# Etat actuel de l'implementation - `site_selection`

Date: 2026-05-27

Ce document decrit ce qui existe aujourd'hui dans `site_selection`, les
fonctionnalites disponibles et la maniere generale dont elles sont realisees.
Il ne sert pas de plan de chantier et ne liste pas les details internes de
refactorisation.

Documents associes:

- doctrine metier finale:
  `docs/_dev_notes/site_selection_final_business_doctrine.md`;
- contrat court terme:
  `docs/_dev_notes/site_selection_short_term_contract.md`;
- limites et contrat de sortie du package:
  `hydromodpy/spatial/site_selection/README.md`;
- prochaine etape proposee:
  `docs/_dev_notes/site_selection_next_step_candidate_selection.md`;
- plan long historique:
  `docs/_dev_notes/legacy/site_selection_tool_implementation_plan.md`.

## Role du workflow

`site_selection` est un workflow amont. Il prepare une campagne de modelisation
en produisant un catalogue de bassins candidats, des decisions de selection ou
de rejet, et les preuves qui expliquent ces decisions.

Il ne lance pas de simulation, ne construit pas de matrice `site x recipe`, ne
calibre pas de modele et ne remplace pas `regional_lab`. Le transfert vers les
workflows aval se fait par les catalogues exportes et par le
`site_selection_manifest.json`.

La separation actuelle est:

```text
site_selection choisit et documente les bassins
regional_lab filtre des sites deja selectionnes et les croise avec des recettes
testbed execute des variantes numeriques
comparison compare les sorties
calibration ajuste des parametres
```

## Fonctionnalites disponibles

### Planification

Le workflow sait valider une configuration TOML, resoudre le profil effectif,
decrire les donnees attendues et produire un rapport de plan. Ce mode ne
selectionne pas de site; il sert a relire la strategie, le territoire, les
entrees et les sorties prevues avant de lancer un calcul.

Commandes disponibles:

```bash
hmp site-selection plan CONFIG
hmp site-selection plan CONFIG --write-manifest --write-report
```

### Selection depuis bassins deja delimites

Un CSV de bassins ou de sites deja delimites peut etre relu pour appliquer les
criteres `site_selection` et regenerer les sorties officielles. Ce chemin sert
aux fixtures, catalogues figes et reprises de campagnes existantes.

Commande disponible:

```bash
hmp site-selection select-catchments CONFIG CATCHMENTS_CSV
```

### Selection hydrometrique

Le profil `gauged_downstream_station` est supporte. Dans ce cas, une station de
debit fournit l'exutoire candidat aval. Le workflow charge les stations via les
gestionnaires de donnees existants, normalise les points d'observation, place
les exutoires sur le support spatial attendu, delimite les bassins puis evalue
les criteres configures.

Deux strategies de placement d'exutoire existent:

- snap direct sur l'accumulation DEM;
- projection optionnelle sur BD Topage ou un reseau de reference custom, puis
  snap local sur le DEM.

BD Topage est utilise comme aide de localisation. La delimitation du bassin
reste faite avec les produits de flux issus du DEM.

Commandes disponibles:

```bash
hmp site-selection build-observed CONFIG
hmp run CONFIG
```

avec:

```toml
[workflow]
mode = "site_selection"

[site_selection.input]
mode = "hydrometry"
```

### Selection par surface

Le profil `area_only` est supporte. Il selectionne des bassins selon une plage
ou une cible de surface. Les autres familles de criteres peuvent etre exportees
comme information, mais elles ne pilotent pas ce profil court terme sauf
configuration explicite.

Deux entrees sont disponibles:

- `delineated_catchments`, pour appliquer les criteres a un inventaire deja
  delimite;
- `dem_area_target`, pour generer un nombre borne de candidats depuis le DEM
  autour d'une surface cible, les delimiter, puis garder les meilleurs sites
  non redondants.

Exemple de configuration maintenue:

```text
examples/projects/17_site_selection_workflow/configs/calvados_non_jauge_dem_10bassins_100km2.toml
```

### Criteres et preuves

Les familles de criteres disponibles sont:

- surface de bassin;
- distance station-exutoire, longueur de chronique et coherence station/bassin;
- influence hydrologique declaree dans les metadonnees de station
  hydrometrique;
- piezometrie;
- influence anthropique depuis couches vectorielles normalisees;
- geologie depuis couches polygonales;
- recouvrement ou emboitement entre bassins candidats;
- selection spatiale finale: limite globale, distance minimale entre exutoires
  et quota grille optionnel;
- echecs structurels de delimitation.

Les criteres produisent des composants auditables. Les preuves station,
piezometre, influence et geologie peuvent aussi etre normalisees en
`EvidenceRecord`. Les decisions finales et les composants de criteres sont
convertis en `DecisionRecord` avec des statuts lisibles: `ACCEPT`, `WARNING`,
`REJECT` ou `NEUTRAL`.

L'absence d'une couche d'influence ne rejette pas un site par defaut. Un rejet
pour influence vient seulement d'une preuve explicite et d'une configuration qui
la rend bloquante.

Doctrine metier court terme:

- le profil `area_only` rejette sur surface, echec de delimitation et regles
  spatiales explicitement configurees;
- le profil `gauged_downstream_station` peut rejeter une station uniquement si
  une preuve d'influence explicite existe dans les champs metier ou dans une
  couche d'influence croisee avec le bassin;
- pour Hub'Eau hydrometrie, les champs explicites sont
  `influence_generale_site` et `influence_locale_station`;
- les metadonnees absentes ou inconnues restent neutres avec
  `unknown_policy = "neutral"`;
- les mots-cles trouves dans les commentaires de station sont des alertes de
  revue, pas des preuves suffisantes pour un rejet dur;
- en l'absence de provider ROE/BNPE branche, `station_influence` reste un
  filtre qualite de station et ne prouve pas l'absence d'ouvrage en amont.

### Rapports et cartes

Le workflow peut produire une page HTML statique de revue. Cette page est
derivee du manifest et des artefacts declares; elle n'est pas une deuxieme
source de verite.

Le rapport affiche:

- le resume du run;
- la strategie et le profil effectif;
- les sites retenus et rejetes;
- les raisons de decision;
- les liens vers les artefacts;
- une carte PNG de controle avec bassins, exutoires, observations et couches de
  contexte disponibles.

Commande disponible:

```bash
hmp site-selection report SITE_SELECTION_MANIFEST
```

## Comment c'est realise

La sequence commune d'un run complet est:

```text
configuration -> donnees -> candidats -> produits DEM -> delimitation
-> annotations -> selection -> sorties -> manifest/rapport
```

Depuis la refonte de structure, le package spatial n'est plus organise en
fichiers plats a la racine. Les anciens modules `candidate_outlets.py`,
`selection.py`, `exports.py`, `manifest.py`, `html_report.py`,
`plan_report.py` et `reporting.py` ont ete supprimes. Les imports internes
doivent viser les sous-packages `candidates`, `config`, `domain`,
`evaluation`, `evidence`, `hydrology`, `outputs`, `pipelines` et `reports`.
La facade `hydromodpy.spatial.site_selection` reste volontairement courte:
points d'entree de workflow, manifest et rendu de rapport.

### Configuration

Les configurations sont validees par les modeles `SiteSelectionConfig`. Elles
portent le territoire, le mode d'entree, la strategie, les criteres, les options
de sortie et les couches de contexte.

Le profil expose dans les sorties est `strategy.effective_profile`. Dans le
contrat courant, les profils maintenus doivent etre declares explicitement dans
le TOML.

- `area_only`;
- `gauged_downstream_station`.

### Donnees

Le workflow ne duplique pas les clients fournisseurs. Les donnees externes sont
resolues par les couches existantes:

- les stations hydrometriques passent par les data managers et sont transmises
  comme points d'observation normalises;
- le DEM est declare sous `[data.dem]`, charge ou assemble par le gestionnaire
  de donnees, puis transmis au workflow spatial;
- les territoires francais peuvent etre resolus par regions ou departements
  administratifs;
- les couches geologie, piezometrie, influence et contexte sont des fichiers
  vectoriels configures.

Par defaut, les donnees lourdes restent dans le workspace utilisateur ou dans le
cache de donnees, pas dans les exemples versionnes.

Politique de versionnement des donnees d'exemple:

- les fixtures legeres, stables et explicites peuvent rester versionnees;
- les donnees fournisseur rechargees depuis un service externe doivent rester
  dans le cache/workspace, sauf besoin de fixture clairement documente;
- les sorties de run, rasters assembles, NetCDF, GeoPackage fournisseur et
  lockfiles `hydromodpy.lock` restent hors Git;
- toute donnee fournisseur versionnee doit porter une provenance lisible:
  source, date ou commande de regeneration.

### Candidats

Les candidats peuvent venir de trois sources:

- stations hydrometriques normalisees;
- CSV de bassins ou d'exutoires deja connus;
- generation depuis le DEM pour les modes `dem_area_target` et
  `dem_network_sampling`.

Les candidats portent leur provenance, leurs coordonnees, les informations de
snap et, quand un reseau de reference est utilise, la distance et le statut par
rapport a ce reseau.

### Delimitation et annotations

Les produits de flux DEM sont construits par adaptation des primitives
hydrologiques existantes. Chaque exutoire candidat est ensuite delimite comme
bassin versant amont.

Apres delimitation, le workflow ajoute les annotations disponibles:

- preuves d'observation;
- croisements d'influence;
- croisements geologiques;
- preuves piezometriques.

Ces annotations alimentent les criteres, les exports d'evidence et le rapport.

### Selection

La selection applique les criteres configures et separe les bassins retenus des
bassins rejetes. Les rejets peuvent venir d'un critere metier, d'une surface
hors plage, d'un recouvrement non autorise, d'un quota atteint ou d'un echec de
delimitation. La phase finale peut aussi plafonner le nombre de sites retenus,
imposer une distance minimale entre exutoires et limiter le nombre de sites par
cellule de grille.

La decision finale reste distincte des composants de criteres: les outils aval
peuvent lire directement la decision, tandis qu'un reviewer peut inspecter les
preuves et les avertissements.

### Sorties

Un run complet ecrit le coeur d'audit:

- `site_selection_manifest.json`;
- `criteria_components.jsonl`;
- `site_selection_decisions.csv`;
- `site_selection_decisions.jsonl`;
- `site_selection_evidence.jsonl` quand au moins une preuve normalisee existe.

Les sorties catalogue sont:

- `selected_sites.csv`;
- `rejected_sites.csv`;
- `regional_lab_sites.csv`.

Les sorties spatiales courantes sont:

- `selected_outlets.geojson`;
- `rejected_outlets.geojson`;
- `selected_basins.geojson`;
- `rejected_basins.geojson`;
- `observation_points.geojson` quand des observations geolocalisees existent.

Les sorties de production optionnelles sont:

- `site_selection.gpkg`;
- fichiers GeoParquet par couche disponible;
- couches d'evidence influence, geologie et observation quand elles existent.

Les modes de generation DEM peuvent aussi ecrire:

- `candidate_generation.jsonl`;
- `candidate_outlets.geojson`;
- `generated_dem_network.geojson`.

Quand `[report.html] build_at_end = true`, le run ecrit:

- `review/index.html`;
- `review/site_selection_map.png`.

## Entrees utilisateur

Les commandes CLI disponibles sont:

```bash
hmp site-selection plan CONFIG
hmp site-selection select-catchments CONFIG CATCHMENTS_CSV
hmp site-selection build-observed CONFIG
hmp site-selection build-dem-network CONFIG
hmp site-selection report SITE_SELECTION_MANIFEST
hmp run CONFIG
```

La commande `build-dem-network` expose le chemin autonome
`dem_network_sampling`. Elle est conservee comme capacite de controle et comme
base d'evolution, mais elle ne fait pas partie des deux profils stabilises du
contrat court terme.

`hmp run` utilise le dispatch standard avec:

```toml
[workflow]
mode = "site_selection"
```

## Exemples maintenus

Profil `area_only`:

- `examples/projects/17_site_selection_workflow/configs/calvados_non_jauge_dem_10bassins_100km2.toml`;
- `examples/projects/17_site_selection_workflow/configs/manche_non_jauge_dem_10bassins_100km2.toml`;
- `examples/projects/17_site_selection_workflow/configs/aura_non_jauge_csv_50_150km2.toml`.

Profil `gauged_downstream_station`:

- `examples/projects/17_site_selection_workflow/configs/bretagne_jauge_7stations.toml`;
- `examples/projects/17_site_selection_workflow/configs/finistere_jauge_elorn_dem.toml`;
- `examples/projects/17_site_selection_workflow/configs/aura_jauge_5stations.toml`.

## Validation actuelle

Validation effectuee le 2026-05-26:

- `calvados_non_jauge_dem_10bassins_100km2.toml`: profil effectif `area_only`, 26
  bassins delimites, 10 sites selectionnes, 16 rejetes, manifest valide,
  rapport HTML:
  `examples/projects/17_site_selection_workflow/outputs/calvados_non_jauge_dem_100km2_v1/review/index.html`;
- `bretagne_jauge_7stations.toml`: profil effectif
  `gauged_downstream_station`, 7 stations chargees, 6 candidats apres
  espacement, 6 sites selectionnes, 0 rejete, preuves normalisees ecrites,
  manifest valide, rapport HTML:
  `examples/projects/17_site_selection_workflow/outputs/bretagne_jauge_7stations_v1/review/index.html`;
- sonde Hub'Eau autour de Lecousse/Nancon: l'emprise retourne la station
  `J001401001`, avec `influence_locale_station = 1`; le critere
  `station_influence` en `hard_reject` produit bien un rejet bloquant.

Validation technique associee au meme etat:

- `python -m ruff check hydromodpy/spatial/site_selection hydromodpy/workflow/site_selection.py hydromodpy/cli/commands/site_selection.py tests/unit/site_selection`;
- `python -m pytest tests/unit/site_selection -q`;
- `python -m pytest tests/unit/launchers/test_site_selection_bridge_examples.py -q`.

Ces validations bornent l'etat stable court terme. Les autres modes peuvent
etre utiles, mais ne doivent pas etre traites comme le contrat principal sans
validation dediee.

## Limites actuelles

Les points suivants ne font pas partie de l'implementation stabilisee:

- carte interactive;
- selection autonome generique par `dem_network_sampling` comme capacite metier
  stabilisee;
- selection automatique avancee par sous-bassins, confluences ou ordre de
  Strahler;
- provider ROE pour les obstacles;
- provider BNPE pour les prelevements;
- chargement ADES complet des piezometres;
- qualite eau et intermittence comme criteres fournisseurs;
- schema final public pour toutes les preuves regionales futures;
- execution de simulations depuis `site_selection`.

Ces sujets doivent rester des evolutions separees. Le socle actuel est le
workflow de selection, ses deux profils courts termes, son manifest, ses
catalogues et son dossier d'audit.

## Points actifs extraits du plan archive

Le plan long `docs/_dev_notes/legacy/site_selection_tool_implementation_plan.md`
reste une archive de conception. Il ne doit plus etre utilise comme backlog
ligne par ligne. Les seuls sujets encore actionnables qui en ressortent sont
classes ici, avec leur document de rattachement courant.

| Sujet | Statut courant | Suite a ouvrir |
| --- | --- | --- |
| Export aval `regional_lab` | `regional_lab_sites.csv` est produit et reste le pont maintenu vers les workflows aval. | Ajouter seulement des tests de relecture aval si un nouveau consommateur apparait. |
| Candidats generes depuis DEM | `dem_area_target` est stabilise pour `area_only`; `dem_network_sampling` reste une capacite de controle. | Ouvrir un chantier separe avant toute promesse produit sur confluences, sous-bassins ou ordre de Strahler. |
| Donnees d'influence | `station_influence` exploite les champs Hub'Eau hydrometriques explicites; les couches vectorielles locales peuvent deja fournir des preuves. | Provider ROE/obstacles et BNPE/prelevements a traiter comme providers de donnees separes. |
| Observations piezometriques et assecs | Les preuves piezometriques fichier sont supportees; ADES complet et ONDE ne sont pas branches. | Definir un contrat de preuve avant d'ajouter des clients fournisseurs. |
| Geologie et hydrogeologie | Les couches configurees peuvent alimenter les preuves et le rapport; pas de nomenclature publique finale. | Ouvrir un lot BRGM/BDLISA si la selection doit stratifier par typologie nationale. |
| Rapport de revue | Rapport HTML statique et carte PNG maintenus. | Carte interactive a garder hors contrat court terme. |
| DEM IGN | `site_selection` utilise le provider public `ign_geoplateforme_dem`. | Les residuels Geoplateforme/RGE ALTI sont suivis dans `docs/_dev_notes/dem_ign_legacy_cleanup_report.md`. |

Toute idee du plan archive qui n'entre pas dans ces lignes doit etre traitee
comme historique jusqu'a creation d'une note courte dediee.
