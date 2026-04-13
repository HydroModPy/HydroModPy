# Perspective de developpement: site 3D de Ploemeur

Statut : note de cadrage initiale a partir des elements de contexte disponibles.

## Objet du document

Cette note resume les caracteristiques du modele 3D de Ploemeur, son usage
actuel, ses limites, et une trajectoire de migration possible vers la nouvelle
version d'HydroModPy.

Le site cible couvre environ `10 km x 10 km x 500 m`.

## Question scientifique centrale

Le point scientifique le plus structurant semble etre le role hydraulique de la
zone de contact pegmatitique entre micaschistes et granites. Cette zone de
contact doit etre consideree comme un objet geologique majeur du modele, au
moins au meme niveau que les lithologies principales, les alterites de surface
et les grandes failles.

## Geometrie geologique de reference

Le modele geologique provient de GOCAD et est exporte sur une grille 3D
reguliere.

Les objets geologiques mentionnes a ce stade sont les suivants :

- un niveau d'alterites proche de la surface, sur environ `20 m` d'epaisseur ;
- cinq lithologies au total ;
- une zone de contact pegmatitique entre micaschistes et granites, d'une
  epaisseur de l'ordre de `50 m` ;
- un pendage initial de cette zone d'environ `30 degres` vers le nord ;
- une geometrie qui devient ensuite quasi verticale au bout de quelques
  kilometres ;
- deux grandes failles `N20`, chacune d'une largeur de l'ordre de `50 m`,
  recoupant le site.

## Proprietes hydrauliques

Les proprietes hydrauliques habillent la geologie, avec un accent particulier
sur :

- la conductivite hydraulique ;
- l'anisotropie hydraulique ;
- le contraste de comportement entre lithologies ;
- le role specifique des micaschistes et de la zone de contact.

Autrement dit, la geologie n'est pas seulement descriptive : elle sert de
support direct au parametrage hydraulique du modele.

## Discretisation et cout de calcul

Le modele actuel repose sur :

- une maille horizontale de `25 m x 25 m` ;
- une discretisation verticale evolutive avec la profondeur ;
- un maillage de l'ordre de `2 a 3 millions` de mailles ;
- une grille reguliere en plan, adaptee en profondeur.

En simulation permanente :

- un calcul MODFLOW prend environ une dizaine de minutes ;
- les calculs de particules MODPATH sont plus rapides.

Il n'y a pas encore de simulation transitoire a ce stade.

## Usage actuel du modele

Le modele est aujourd'hui utilise principalement pour :

- des simulations en regime permanent ;
- une calibration sur les niveaux piezometriques en permanent ;
- une calibration visuelle sur les debits ;
- un ajustement leger sur le debit.

Un point important ressort deja : beaucoup de jeux de parametres produisent des
charges voisines. Cela suggere un probleme classique de non-unicite, ou au
moins une sensibilite limitee des charges seules pour discriminer les modeles.

## Sensibilite et limites actuelles

Les limites actuelles peuvent etre formulees ainsi :

- l'analyse de sensibilite montre que plusieurs modeles conduisent a des
  charges proches ;
- le permanent seul ne suffit probablement pas pour contraindre finement les
  parametres ;
- l'usage du transitoire pourrait aider a aller plus loin dans la
  discrimination des hypotheses hydrauliques ;
- les couts de post-traitement peuvent devenir importants quand le nombre de
  particules augmente fortement.

## Post-traitement particulaire

Le post-traitement des trajectoires de particules repose sur PMPATH, comme
alternative pratique a FloPy pour certaines analyses de trajectoires. FloPy a
ete debranche sur ce volet.

Points de vigilance :

- PMPATH genere des fichiers de sortie dans la chaine `modflow_nwt` ;
- pour `10 millions` de particules, ce sont surtout les sorties qui prennent de
  la place disque et du temps ;
- il existe deja des metriques de post-traitement permettant d'analyser les
  trajectoires, ce qui constitue un acquis important a conserver dans la
  migration.

## Trajectoire de migration vers la nouvelle version d'HydroModPy

La migration parait devoir se faire en deux temps.

### Etape 1 - porter le modele sur une grille reguliere

La premiere etape devrait consister a reproduire au plus pres le modele actuel,
sans changer sa logique geometrique :

- conserver l'entree geologique issue de GOCAD sur grille reguliere ;
- conserver une discretisation structuree en plan ;
- reconstruire le mapping geologie -> proprietes hydrauliques ;
- representer explicitement les alterites, les cinq lithologies, la zone de
  contact et les failles ;
- remettre en priorite les cas permanents, la calibration piezometrique et la
  chaine particulaire existante.

L'objectif de cette etape est de retrouver un cas de reference robuste avant
de changer de type de maillage.

### Etape 2 - passer a un maillage irregulier

Une deuxieme etape pourra ensuite viser un maillage irregulier, si cela apporte
un gain net sur la representation des objets geologiques structurants :

- meilleure representation geometrique du contact pegmatitique ;
- meilleure representation des failles `N20` ;
- raffinement local plus efficace ;
- reduction possible du cout global a precision equivalente.

Cette deuxieme etape n'a de sens que si l'etape reguliere a deja stabilise :

- les conventions de geometrie ;
- le parametrage hydraulique ;
- les observables de calibration ;
- la chaine de post-traitement des trajectoires.

## Priorites techniques recommandees

Ordre de priorite propose :

1. definir un cas de reference Ploemeur sur grille reguliere dans la nouvelle
   architecture ;
2. formaliser le schema des unites geologiques et des proprietes hydrauliques ;
3. garantir la reprise des sorties permanentes et des sorties de trajectoires ;
4. encapsuler les metriques PMPATH pour ne pas dependre du chemin historique
   FloPy ;
5. ouvrir ensuite un chantier transitoire ;
6. n'aborder le maillage irregulier qu'apres validation du cas structure.

## Resume executif

Le modele de Ploemeur est un modele 3D structure, dense, geologiquement riche,
et deja operationnel en permanent. Son coeur scientifique semble etre le role
hydraulique de la zone de contact pegmatitique, en interaction avec les
micaschistes, les alterites superficielles et deux grandes failles `N20`.

Pour la nouvelle version d'HydroModPy, la bonne strategie semble etre de
porter d'abord fidelement ce modele sur une grille reguliere, puis seulement
dans un second temps de viser un maillage irregulier et un passage au
transitoire.
