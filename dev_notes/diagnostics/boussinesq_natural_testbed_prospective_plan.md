# Boussinesq/MODFLOW6 Natural Regional-Lab Testbed Prospective Plan

Etat au 2026-05-10.

Ce document decrit le plan prospectif pour passer des comparaisons
synthetiques deja implementees vers des comparaisons naturelles
Boussinesq/MODFLOW 6 sur une liste de bassins versants. La partie
synthetique est dans l'implementation. La partie naturelle releve plus
precisement d'une logique `regional lab`: selection regionale de sites,
stratification geologique et execution repetee sur un catalogue. Elle reste un
plan de deploiement a valider avant de lancer une campagne complete.

## Positionnement

Le naturel doit reutiliser le mecanisme testbed/comparison existant, pas creer
un second workflow parallele. Dans cette acception, `regional lab` decrit la
maniere de construire, filtrer et documenter le catalogue regional. `testbed`
reste le moteur generique d'execution, de delegation vers `comparison` et de
synthese des resultats.

Le chemin cible est:

```text
regional lab: selection/stratification de sites
  -> catalogue de sites CSV
  -> workflow = "testbed"
  -> un workflow = "comparison" genere par site
  -> deux simulations ordinaires MF6/Boussinesq par comparaison
  -> generation du maillage par mesh_catchment dans chaque simulation
  -> pages HTML de comparaison et page HTML de synthese testbed
```

Il ne faut pas utiliser de maillages existants comme entrees. Les maillages
doivent etre regeneres par le chemin classique de simulation, a partir des
coordonnees d'exutoire, du MNT, de l'hydrographie, de la geologie et des
parametres de maillage.

## Reutilisation attendue

Le chantier naturel doit s'appuyer sur les briques deja disponibles:

| Besoin | Brique reutilisee | Role |
| --- | --- | --- |
| Selection regionale | catalogue regional explicite | Fixe les sites, les classes de surface, les classes geologiques et les tags de selection. |
| Boucle sur une liste de sites | `workflow = "testbed"` avec catalogue CSV | Cree une variante par ligne de catalogue active. |
| Comparaison MF6/Boussinesq | `workflow = "comparison"` | Materilise les deux simulations et lance les extractions communes. |
| Parametres communs de campagne | `comparison.base_simulation_overlay` | Injecte les choix physiques et de maillage communs aux deux solveurs. |
| Parametres propres aux solveurs | `comparison.simulation.overlay` | Configure MODFLOW 6 et Boussinesq sans dupliquer la simulation de base. |
| Maillage naturel | `mesh_catchment` | Regenere le maillage colle aux rivieres et aux interfaces geologiques. |
| Pages HTML par cas | rapport web de comparaison | Montre contexte, observables, cartes et bilans comparables. |
| Page HTML de synthese | `generate_testbed_web_report.py` | Agrege les liens vers les cas et les indicateurs de campagne. |

La seule extension generique acceptable, si elle manque encore, est une
amelioration reusable du workflow testbed, du rapport HTML ou de la production
du catalogue regional. Il ne faut pas ajouter de script specifique "natural
launcher" qui ferait une boucle a cote du testbed.

## Organisation des fichiers

Organisation proposee:

```text
examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/
  README.md
  natural_regional_lab_sites.csv
  natural_regional_lab.toml
  natural_10km2_sites.csv
  natural_10km2_mf6_bouss_testbed.toml
  natural_100km2_mf6_bouss_testbed.toml
  natural_n3_mesh_sensitivity_mf6_bouss_testbed.toml
  compare_natural_10km2_mf6_bouss_base.toml
  compare_natural_100km2_mf6_bouss_base.toml
  compare_natural_n3_mesh_sensitivity_mf6_bouss_base.toml
  base_site_01_mf6_bouss_transient.toml
  inputs/
    k_tables/
      geology_K_brgm_reference.csv
```

Responsabilites:

| Fichier | Contenu attendu |
| --- | --- |
| `natural_regional_lab_sites.csv` | Catalogue regional unifie: sites N1, sites N2, ancres N3, classes de surface, familles geologiques, tags, provenance et chemins de configurations generees. |
| `natural_regional_lab.toml` | Inventaire regional-lab: selectionne les sites et les recettes N1/N2/N3, sans executer directement de boucle specifique. |
| `natural_10km2_mf6_bouss_testbed.toml` | Testbed N1: filtre les sites `n1_10km2` et genere une comparaison par site. |
| `natural_100km2_mf6_bouss_testbed.toml` | Testbed N2: filtre les sites `n2_100km2` et genere une comparaison par site. |
| `natural_n3_mesh_sensitivity_mf6_bouss_testbed.toml` | Testbed N3: filtre les ancres `n3_anchor` et genere les variantes coarse/reference/refined. |
| `compare_natural_10km2_mf6_bouss_base.toml` | Configuration commune de comparaison N1: methodes numeriques, observables, rendu HTML, parametres naturels communs injectes dans les simulations. |
| `compare_natural_100km2_mf6_bouss_base.toml` | Surcharge N2 de la base N1: snapping, buffer, seuil riviere, resolution raster et maillage plus grands. |
| `compare_natural_n3_mesh_sensitivity_mf6_bouss_base.toml` | Base N3: herite des methodes communes et laisse les regles de testbed porter les variantes de maillage. |
| `base_site_01_mf6_bouss_transient.toml` | Base physique: MNT, hydrographie, geologie, recharge, domaine, K, conditions initiales, fenetre temporelle. |
| `inputs/k_tables/geology_K_brgm_reference.csv` | Table de conductivites hydrauliques heterogenes documentee et versionnee. |

Le testbed TOML doit rester court. Les parametres qui ne changent pas d'un site
a l'autre doivent aller dans la base de comparaison ou dans la base de
simulation. Le CSV doit rester un catalogue de sites et de selection regionale,
pas un fichier de configuration hydraulique detaillee.

## Representation HTML

Les pages naturelles doivent reprendre la logique simplifiee stabilisee sur le
synthetique:

- une page de synthese large, lisible, avec un lien direct vers chaque page de
  comparaison;
- un seul tableau principal de campagne, avec le cas, les temps de calcul MF6
  et Boussinesq, les ecarts moyens de charge et les diagnostics de bilan utiles;
- pas de tableau de metriques brut quand les metriques sont deja representees
  dans le tableau principal;
- une page de comparaison par site centree sur le contexte, les methodes,
  quelques cartes et les figures de resultats comparables;
- pour les resultats, priorite aux charges, profondeurs de nappe, stockage
  global et entrees/sorties globales comparables;
- eviter les flux natifs non homogenises si les deux solveurs ne produisent pas
  exactement la meme grandeur.

La page naturelle doit aussi expliquer que le site provient d'un catalogue et
que le maillage est regenere par la simulation. Ce bloc d'explication doit etre
generique afin de pouvoir servir a d'autres testbeds catalogues.

## Selection des sites naturels

La premiere campagne naturelle doit rester raisonnable mais significative:

| Lot | Objectif | Nombre de sites | Surface cible | Role |
| --- | --- | ---: | ---: | --- |
| N1 | Lot naturel 10 km2 | 8 a 10 | environ 10 km2 | Comparaison rapide, bassins assez petits pour iterer, stratifies selon l'heterogeneite geologique et les classes de K. |
| N2 | Lot naturel 100 km2 | 8 a 10 | environ 100 km2 | Meme logique geologique que N1, mais avec bassins plus integrateurs, reseaux hydrographiques plus developpes et cout numerique plus representatif. |
| N3 | Robustesse maillage/discretisation | 2 a 4 sites issus de N1/N2, chacun avec 2 a 3 variantes | 10 et 100 km2 | Distinguer les ecarts de solveurs des effets de maillage, de discretisation temporelle, de snapping hydrographique ou de resolution des interfaces geologiques. |

N3 n'est donc pas une troisieme campagne geologique principale. C'est un lot
de controle construit apres N1 et N2, sur quelques sites representatifs, pour
tester si les conclusions de comparaison changent quand on raffine le maillage,
modifie legerement les contraintes geologie/rivieres ou harmonise davantage la
discretisation temporelle.

Etat implemente au 2026-05-10:

- N1 selectionne 8 sites 10 km2 depuis `natural_regional_lab_sites.csv`;
- N2 selectionne 9 sites 100 km2 candidats;
- N3 selectionne 3 ancres: deux sites 10 km2 et un site 100 km2, avec trois
  variantes de maillage par ancre;
- les sites N2 proviennent pour l'instant du criblage mesh-gallery 100 km2.
  Les coordonnees sont utilisees comme provenance de selection de site, pas
  comme maillage d'entree.

Pour chaque site, il faut verifier:

- delimitation correcte du bassin;
- hydrographie presente et exploitable;
- geologie couverte par la table K;
- maillage valide, sans cellules topographiques incoherentes;
- temps de calcul acceptable pour MF6 et Boussinesq;
- observables comparables disponibles dans les deux simulations.

## Conductivites hydrauliques

Le prototype peut rester mecanique avec une table de demonstration, mais la
campagne naturelle de reference doit utiliser une table dediee et documentee.

Exigences minimales pour la table K:

- une cle stable par unite geologique ou hydrogeologique;
- une valeur K en unite explicite, par exemple `m/s`;
- une colonne de provenance ou de justification;
- une distinction claire entre valeur par defaut, valeur estimee et valeur
  issue d'une reference;
- une note README indiquant la source BRGM ou hydrogeologique utilisee.

Le changement de table K doit etre une modification de donnees/configuration,
pas un changement de code.

## Conditions initiales, recharge et temps

La base de simulation naturelle doit porter les choix communs:

- fenetre temporelle;
- chronique de recharge;
- strategie de condition initiale;
- parametres de stockage;
- bornes physiques pour Boussinesq;
- absence de drainage Cauchy Boussinesq tant que le cas 1 strict est vise.

La strategie recommandee pour comparer proprement est:

1. calculer ou declarer une condition initiale hydraulique coherente avec une
   recharge moyenne;
2. executer ensuite la chronique transitoire;
3. exposer explicitement dans les pages HTML la provenance de la recharge et de
   la condition initiale;
4. reporter les memes grandeurs comparables pour les deux methodes.

## Criteres de passage

Avant d'etendre la campagne, les jalons doivent etre:

1. dry-run testbed complet: tous les sites actifs generent un TOML de
   comparaison valide;
2. execution complete d'un site pilote;
3. verification HTML du site pilote;
4. execution N1 sur 8 a 10 sites 10 km2;
5. audit des echecs de maillage, de convergence et de comparabilite des sorties;
6. execution N2 sur 8 a 10 sites 100 km2;
7. construction N3 sur un sous-ensemble N1/N2 pour tester la sensibilite au
   maillage et a la discretisation.

Pour rester lisible, les sorties naturelles sont stockees sous:

```text
examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/
  _generated_configs/
  comparisons/
  web_synthesis/

examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n2_100km2_testbed/
  _generated_configs/
  comparisons/
  web_synthesis/

examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n3_mesh_sensitivity_testbed/
  _generated_configs/
  comparisons/
  web_synthesis/

examples/projects/10_testbed_workflow/outputs/boussinesq_natural_regional_lab/
  regional_lab_plan.json
  regional_lab_report.json
  regional_lab_site_inventory.csv
  regional_lab_case_matrix.csv
```

Chaque testbed conserve aussi les artefacts generiques:

```text
  testbed_cases.csv
  testbed_manifest.json
  testbed_metrics.csv
  testbed_report.md
```

## Points de nettoyage restants

Les points suivants ne bloquent pas le passage au naturel, mais doivent rester
visibles:

- le synthetique a encore un script de synthese historique dedie; il fonctionne,
  mais son comportement doit converger progressivement vers le rapport HTML
  generique de testbed;
- le naturel ne doit pas ajouter de script equivalent;
- les donnees de demonstration K ne sont pas suffisantes pour une campagne
  scientifique;
- les criteres de comparaison doivent rester physiques: ecarts de charge en m,
  pourcentages normalises sur amplitude utile, volumes normalises sur recharge
  ou surface, et diagnostics de fermeture de bilan.
