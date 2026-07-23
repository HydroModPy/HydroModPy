# CR Réunion HydroModPy - AquiFR 18/05/2026

Plusieurs pistes/objectifs :

- partir de ce qui est fait ajd, définir besoins de spécification 
- résultats aquifr => pouvoir les intégrer dans hmp

#### Spécificités algorithmiques côté AquiFR

Il existe plusieurs modèles et plusieurs applications.

Le code est composé d'un driver général, codé en python, qui communique avec les modèles via mpi (mpi4py). Les modèles sont essentiellement codés en fortran mais c'est possible en python aussi.

Le pas de temps des simulation est journalier.
A chaque itération, le driver récupère les forçages du jour, les envoie à tous les modèles, chaque modèle fait tourner sa simulation et renvoie les résultats au driver.
Entre 2 itérations, un modèle n'a pas à s'arrêter pour redémarrer ensuite, il est en pause, en attente des forçages du jour suivants.

Il est aussi possible d'arrêter la simulation à un temps et la reprendre à partir de l'état final.

Un modèle renvoie : les charges piézométriques sur la grille, les débits, et éventuellement des échanges nappes-rivières, des débordements

Le format de grille dépend de l'application, le plus simple à gérer est la grille cartésienne (Lambert 2 étendue).

Chaque modèle a son réseau hydrologique.

Archi du code :
- Un dossier driver : contient script principal, script qui lit les forçages, et script de pre/post-proc (fait l'enregistrement des variables en netcdf)
- Un dossier par modèle
- Un dossier Applications avec tous les aquifères

Pour intégrer modflow, il est impossible d'utiliser l'exécutable (question de sécurité) donc il faudra pouvoir le recompiler à partir du code source.
Il faudra un répertoire modflow avec le code du modèle. Le reste (paramètres etc.) sera dans le dossier Applications.

Bibliothèques :
Possibilité de conflits, réflexion en cours à ce sujet côté aquifr.
**Côté hmp : faire une liste des bibliothèques qu'on utilise**

#### Méthode de travail

On a accès au code de la plateforme sur git (il faut un compte renater)
**https://sourcesup.renater.fr/projects/aqui-fr/**

**2 grandes étapes :**
- s'assurer qu'on peut communiquer avec les drivers, faire les interfaces mpi etc. (avec l'exécutable modflow)
- regarder quels sont les travaux sur l'aspect compilation (donner nos bibliothèques avec numéros de version)

Travailler sur un fork, cloner en local et faire notre mise en place ici.

Il existe des forçages disponibles sur ftp (**accès à tester**)

Accès à tester : sourcesup.renater (ok), ftp, extranet aquiFR

#### prochaine réunion
27 mai à 10h