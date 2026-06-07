# Proposition de cas transport naturels homogenes

Date : 2026-05-14

Statut : proposition basee sur l'inspection des exemples locaux du repository.
Le visuel controle reste dans `examples/projects/13_transport_mf6_gwt_disv_visual_guard`.
Les tests rapides de non-regression restent sans HTML.

## Objectif

Le prochain palier transport doit passer de cas rectangles controles a des
supports naturels, mais en gardant une physique homogene pour ne pas melanger
trop de sources d'ecart avant le refactoring.

Definition proposee d'un cas naturel homogene :

- domaine, topographie, hydrographie et maillage naturels ou site-like ;
- `K` homogene ;
- porosite homogene ;
- diffusion/dispersion constante ;
- transport conservatif dans un premier temps ;
- source simple : pulse interne, pulse amont, ou source locale constante ;
- verification par signatures numeriques et par page HTML manuelle, pas par
  comparaison analytique stricte.

## Piste 1 deja renforcee

Le fichier de tests rapides
`tests/unit/examples/test_transport_mf6_gwt_disv_visual_guard.py` ne depend plus
du rendu HTML. Il construit des cas compacts en memoire et verifie :

- maillage triangulaire DISV perturbe ;
- pulse interne homogene avec reference analytique gaussienne ;
- source amont constante avec reference Ogata-Banks ;
- pulse amont fini comme difference de deux fronts Ogata-Banks ;
- conservation de masse approximative avant sortie aval ;
- variantes Peclet bas et haut ;
- cas heterogenes `K x5` pour verifier que le Peclet varie avec `K`.

La reference compacte est :

- `tests/unit/examples/golden/transport_visual_guard_fast_signatures.json`.

## Inventaire local utile

### `examples/projects/02_nancon_watershed`

Cas Nancon maintenu comme exemple end-to-end. Il contient des runs NWT
transitoires, calibration K, API Python et comparaison reseau hydrographique.
C'est le meilleur candidat naturel homogene court parce qu'il est deja le bassin
de reference du repository.

Usage transport propose :

- homogene `K`, porosite, diffusion ;
- injection locale ou pulse amont dans une zone de tete ;
- suivi de la concentration vers le reseau et l'exutoire ;
- premiere cible apres les tests analytiques.

### `examples/projects/11_nancon_network_physical_benchmark`

Benchmark Nancon plus propre que les anciens runs, avec contrat physique explicite
et comparaison MF6/Boussinesq. Il isole deja une question reseau/drainage.

Usage transport propose :

- reutiliser le support MF6/DISV ou la logique de diagnostic reseau ;
- ajouter un transport conservatif homogene sur le meme domaine ;
- mesurer breakthrough vers les cellules drainantes et l'exutoire reseau.

### `examples/projects/12_calibration_network_transient_b0`

Prototype B0 sur `site_05`, avec verite MF6, reseau de drainage et decharge
transitoire. Ce n'est pas un benchmark transport, mais le contrat de scoring et
les sorties reseau sont proches des besoins transport.

Usage transport propose :

- candidat naturel homogene "site_05 controlled small catchment" ;
- utile apres Nancon, pour connecter concentration, reseau et calibration ;
- a garder comme cas de validation fonctionnelle, pas comme premier cas de
  refactoring.

### `examples/projects/07_mesh_gallery`

Source la plus utile pour des supports naturels versionnes sans relancer tout le
workflow geographique. Les bundles contiennent `mesh_2d.msh`, `cells.csv`,
`edges.csv`, `nodes.csv`, `metadata.json` et `mesh_summary.json`.

Candidats prioritaires :

| candidat | chemin | interet |
|---|---|---|
| 10 km2 rivers-only outlet 1 | `07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_rivers_only_buffer30` | petit, maillage naturel structure par les rivieres, bon premier cas naturel homogene |
| 10 km2 geology+rivers outlet 1 | `07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30` | meme famille avec interfaces geologiques dans le maillage mais `K` force homogene |
| 100 km2 headwater outlet 2 | `07_mesh_gallery/100km2/mesh_headwater_100km2_outlet_2_geology_rivers_buffer30` | support deja repris ailleurs, environ 4216 cellules dans le bundle inspecte, bon cas P1 |
| 100 km2 s3 outlet 25 | `07_mesh_gallery/100km2/mesh_s3_100km2_outlet_25_geology_rivers_buffer30` | site naturel candidat dans les testbeds regionaux |

Les variantes `1000km2` sont a repousser : elles testent surtout la taille et la
robustesse workflow, pas le noyau transport.

### `examples/projects/09_capability_gallery`

Contient des sorties versionnees issues de runs plus lourds, notamment
`headwater_100km2_outlet_2_mf6_transient_reference`. C'est utile pour retrouver
un contexte visuel et un cas de reference ancien, mais ce n'est pas le bon endroit
pour developper un nouveau workflow.

Usage transport propose :

- utiliser comme source d'inspiration et comparaison de rendu ;
- ne pas y ajouter de nouveau cas transport.

### `examples/projects/10_testbed_workflow`

Ne pas y ajouter le nouveau developpement transport, mais utiliser les tables de
sites comme catalogue.

Sources utiles :

- `natural_10km2_sites.csv` : sites `site_01` a `site_08` ;
- `natural_network_site_candidates_sites.csv` : inclut `site_01`, `site_02`,
  `site_03`, `site_05`, `headwater_100km2_outlet_2`,
  `s3_100km2_outlet_25` ;
- `natural_petsc_vi_regression_sites.csv` : sites de stress Boussinesq deja
  identifies.

Priorite transport homogene :

1. `site_01` ou `site_05` pour un petit 10 km2 lisible ;
2. `site_02` seulement ensuite, car deja associe a des difficultes Boussinesq ;
3. `headwater_100km2_outlet_2` comme premier 100 km2 ;
4. `s3_100km2_outlet_25` comme second 100 km2 plus ramifie.

### `examples/projects/06_vire_selune`

Cas plus grands, avec Vire et Selune. Les configs indiquent des bassins autour de
`1258 km2` pour Vire et `367 km2` pour Selune, et des runs MF6/NWT. Bon candidat
long terme, mais trop gros pour commencer le refactoring transport.

Usage transport propose :

- P2 seulement ;
- `K` homogene force, meme si les configs steady irregular peuvent utiliser une
  table K geologique demonstration ;
- utile pour tester transport sur grand domaine et temps longs.

### `examples/projects/03_canut_watershed`

Projet ancien/generate avec config tres complete. Il peut servir a retrouver un
site historique, mais il n'est pas le premier choix car le contrat courant est
moins clair que Nancon, mesh gallery et testbed naturel.

Usage transport propose :

- candidat de resurrection si l'on veut couvrir un ancien workflow ;
- pas avant les cas Nancon et mesh-gallery.

### `examples/projects/03_groundwater_1d`

Cas analytique 1D ancien/oriente calibration. Utile conceptuellement, mais il ne
sert pas de cas naturel. Il reste plutot une source d'idees pour tests analytiques
compacts.

## Sequence recommandee

### P0 : cas naturels homogenes sans nouvelle complexite

1. Creer un nouvel exemple separe, par exemple :

   `examples/projects/14_transport_natural_homogeneous_visual_guard/`

2. Commencer par deux cas seulement :

   - `nancon_homogeneous_internal_pulse` depuis `02_nancon_watershed` ou
     `11_nancon_network_physical_benchmark` ;
   - `mesh_gallery_10km2_rivers_only_homogeneous_pulse` depuis le bundle
     `07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_rivers_only_buffer30`.

3. Forcer :

   - `K` homogene ;
   - porosite homogene ;
   - diffusion constante ;
   - pas de reaction ;
   - injection simple et documentee.

4. Sorties HTML :

   - domaine naturel ;
   - mesh ;
   - topographie/charge/flux ;
   - Peclet cellule ;
   - source transport ;
   - cartes de concentration ;
   - breakthrough sur sondes et cellules drainantes ;
   - masse, centre, largeur.

### P1 : supports naturels plus proches des workflows existants

1. Ajouter `site_01` ou `site_05` depuis les tables du testbed naturel.
2. Ajouter `headwater_100km2_outlet_2` depuis le bundle mesh-gallery.
3. Ajouter un scenario source amont constant en plus du pulse interne.
4. Construire une reference numerique homogene stable, pas une reference
   analytique.

### P2 : cas grands ou historiques

1. `Selune` puis `Vire`, avec `K` homogene force.
2. `site_02` et autres cas Boussinesq difficiles comme stress transport.
3. `Canut` uniquement si l'on veut explicitement couvrir les anciens workflows.

## Position avant refactoring

Avant de refactorer le code transport principal, il est suffisant d'avoir :

- tests rapides analytiques et signatures compactes : deja en place ;
- un exemple visuel controle DISV : `13_transport_mf6_gwt_disv_visual_guard` ;
- un exemple naturel homogene P0 a creer, idealement Nancon + un bundle
  mesh-gallery 10 km2.

Il n'est pas necessaire d'ajouter les grands cas Vire/Selune ou les sites
Boussinesq difficiles avant le premier refactoring. Ils doivent venir comme
stress tests apres stabilisation du noyau.
