# Perspective site 3D de Ploémeur

Statut : note de cadrage. Ce document résume les caractéristiques du
modèle 3D de Ploémeur, son usage actuel, ses limites et une trajectoire
de portage vers la version courante d'HydroModPy.

Liens : [nwt_sunset_plan.md](nwt_sunset_plan.md),
[modflow6_gmsh_disv_development_perspective.md](modflow6_gmsh_disv_development_perspective.md),
[gmsh_conformal_meshing.md](gmsh_conformal_meshing.md).

## Périmètre

Site couvrant environ `10 km x 10 km x 500 m`.

## Question scientifique centrale

Le rôle hydraulique de la zone de contact pegmatitique entre
micaschistes et granites. Cet objet géologique est au moins aussi
structurant que les lithologies principales, les altérites de surface et
les grandes failles.

## Géométrie géologique de référence

Modèle géologique issu de GOCAD, exporté sur grille 3D régulière.

Objets géologiques actuellement représentés :

- niveau d'altérites proche de la surface, environ `20 m` d'épaisseur ;
- cinq lithologies au total ;
- zone de contact pegmatitique entre micaschistes et granites,
  épaisseur d'environ `50 m` ;
- pendage initial d'environ `30 degrés` vers le nord, puis
  quasi vertical au-delà de quelques kilomètres ;
- deux grandes failles `N20` de largeur de l'ordre de `50 m`.

## Propriétés hydrauliques

Les propriétés habillent la géologie, avec un accent sur :

- la conductivité hydraulique ;
- l'anisotropie hydraulique ;
- le contraste entre lithologies ;
- le rôle spécifique des micaschistes et de la zone de contact.

La géologie sert de support direct au paramétrage.

## Discrétisation et coût de calcul

- maille horizontale `25 m x 25 m` ;
- discrétisation verticale évolutive en profondeur ;
- environ `2 à 3 millions` de mailles ;
- grille régulière en plan, adaptée verticalement.

En régime permanent : un calcul MODFLOW prend environ dix minutes. Les
calculs de particules MODPATH sont plus rapides. Pas de transitoire à ce
stade.

## Usage actuel

- simulations en régime permanent ;
- calibration sur niveaux piézométriques en permanent ;
- calibration visuelle sur les débits ;
- ajustement léger sur le débit.

Constat important : beaucoup de jeux de paramètres produisent des charges
voisines. Problème classique de non-unicité, ou sensibilité limitée des
charges seules pour discriminer les modèles.

## Limites actuelles

- plusieurs modèles conduisent à des charges proches ;
- le régime permanent seul ne suffit pas à contraindre finement les
  paramètres ;
- le transitoire pourrait aider à discriminer les hypothèses ;
- les coûts de post-traitement explosent avec le nombre de particules.

## Post-traitement particulaire

PMPATH est utilisé comme alternative à FloPy pour certaines analyses
de trajectoires. FloPy est débranché sur ce volet.

Points de vigilance :

- PMPATH génère ses sorties dans la chaîne `modflow_nwt` ;
- pour `10 millions` de particules, les sorties pèsent en disque et en
  temps ;
- des métriques de post-traitement existent déjà : à conserver dans la
  migration.

## Trajectoire de migration

Deux étapes.

### Étape 1 : portage sur grille régulière

Reproduire au plus près le modèle actuel sans changer sa logique
géométrique :

- conserver l'entrée géologique GOCAD sur grille régulière ;
- conserver une discrétisation structurée en plan ;
- reconstruire le mapping géologie vers propriétés hydrauliques ;
- représenter explicitement altérites, cinq lithologies, zone de
  contact et failles ;
- prioriser le permanent, la calibration piézométrique et la chaîne
  particulaire existante.

Objectif : retrouver un cas de référence robuste avant de changer de
type de maillage.

## Étape 2 : maillage irrégulier

Passer à un maillage irrégulier si cela apporte un gain net :

- meilleure représentation du contact pegmatitique ;
- meilleure représentation des failles `N20` ;
- raffinement local plus efficace ;
- réduction possible du coût à précision équivalente.

Cette étape n'a de sens qu'après stabilisation des conventions
géométriques, du paramétrage, des observables et du post-traitement.

## Priorités techniques

1. définir un cas de référence Ploémeur sur grille régulière dans
   l'architecture courante ;
2. formaliser le schéma des unités géologiques et des propriétés
   hydrauliques ;
3. garantir la reprise des sorties permanentes et des sorties de
   trajectoires ;
4. encapsuler les métriques PMPATH pour ne pas dépendre du chemin FloPy
   historique ;
5. ouvrir un chantier transitoire ;
6. n'aborder le maillage irrégulier qu'après validation du cas
   structuré.

## Résumé exécutif

Modèle 3D structuré, dense, géologiquement riche, opérationnel en
permanent. Cœur scientifique : rôle hydraulique de la zone de contact
pegmatitique, en interaction avec les micaschistes, les altérites
superficielles et deux grandes failles `N20`. Stratégie de migration :
porter d'abord fidèlement sur grille régulière, puis viser maillage
irrégulier et transitoire dans un second temps.
