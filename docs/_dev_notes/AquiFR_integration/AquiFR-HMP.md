
# 1 - Fonctionnement de MPI

MPI4PY est une interface Python de MPI (Message Passing Interface), une bibliothèque standard utilisée pour le calcul parallèle distribué sur des clusters ou des machines multi-processeurs.

L’objectif de MPI est de permettre à plusieurs processus indépendants de communiquer entre eux afin de répartir des calculs lourds.

## 1.1 Principe général de MPI
Dans MPI, un programme est exécuté simultanément par plusieurs processus.

Chaque processus possède :
- un identifiant appelé "rank",
- une mémoire indépendante,
- son propre flux d’exécution.

Tous les processus appartiennent généralement au communicateur global.

## 1.2 Concepts importants
### Communicateur
Un communicateur est un groupe de processus capables de communiquer entre eux. Exemple :
```
comm = MPI.COMM_WORLD
```

### Rank
Chaque processus possède un identifiant unique : ```rank = comm.Get_rank()```

### Size
Nombre total de processus : ```size = comm.Get_size()```

## 1.3 Communications MPI
### Send
Permet d’envoyer des données à un autre processus.
Exemple : ```comm.Send(data, dest=2, tag=20)```
- dest = le rank du destinataire
- tag = identifiant du message (choisit par les dev, permet au processus qui reçoit de recevoir le bon message)

### Recv
Permet de recevoir des données.
Exemple : ```comm.Recv(buffer, source=2, tag=20)```

### Barrier
Synchronisation globale.
Tous les processus attendent que les autres aient atteint ce point.
```comm.Barrier()```

### Gather
Collecte des données provenant de tous les processus.
Exemple : ```comm.Gather(local_data, global_data, root=0)```

## 1.4 MPI4PY
MPI4PY est une bibliothèque Python qui permet d’utiliser MPI depuis Python.

Exemple minimal MPI4PY :
```
from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

print(f"Bonjour depuis le rank {rank}/{size}")
```

Exécution :
```mpirun -n 4 python script.py```

## 1.5 MPI dans Aqui-FR
Dans le code fourni, le rank 0 correspond au driver et les autres ranks exécutent différents modèles hydrologiques. MPI sert à synchroniser et échanger les données de forçage et les résultats.

# 2 - Fonctionnement du code AquiFR
Le fichier principal est un driver MPI servant à orchestrer une simulation hydrogéologique. Il coordonne plusieurs modèles ainsi qu'un module de post-traitement.

Le programme :
1. lit les paramètres
2. lit les forçages météo
3. envoie les données aux modèles
4. récupère les résultats
5. synchronise l’ensemble

## 2.1 Initialisation MPI
Le programme récupère le communicateur global, le nombre total de processus, le rank courant et vérifie qu’il est exécuté uniquement par le rank 0.

## 2.2 Identification des applications
Chaque processus MPI correspond à un type d’application.
Codes utilisés :
- 0 : driver principal
- 1 : post-traitement
- 2..n : modèles :
  - 2 : Eaudyssee
  - 3 : Marthe
  - 4 : Eros
  - 5 : CTRIP

Le driver récupère tous les ranks et construit les listes :
- rank_odic
- rank_mart
- rank_eros
- rank_trip

## 2.3 Lecture des dimensions des modèles
Des fichiers csv *working_directory_\<modelname\>* décrivent le nombre de cellules souterraines et le nombre de cellules rivière pour les applications de chaque modèle.

Le programme calcule des indices d'après ces données.

## 2.4 Lecture des options de simulation

Le programme lit les options définies dans le fichier d'options :
- la date de début
- le nombre de périodes
- la durée des périodes
- le pas de temps SURFEX

Le nombre total de pas de temps est égal à la somme des durées des périodes.

## 2.5 Lecture des forçages

Le programme lit le drainage et le suissellement dans les fichiers de forçages.

## 2.6 Boucle temporelle principale

La boucle :
```
for kstep in range(nb_pastp)
```
correspond aux jours simulés.

À chaque pas :
1. lecture des forçages
2. envoi aux modèles
3. calcul des modèles
4. récupération des résultats
5. envoi au pre_post-traitement
6. synchronisation

## 2.7 Distribution des données

Le driver envoie les forçages via MPI : ```comm.Send(...)```
Chaque type de donnée possède un tag MPI (20, 21, 22, 30, etc)

## 2.8 Réception des résultats

Les modèles renvoient :
- h : charge/piézométrie
- q : débit rivière
et éventuellement : 
- qnr : échange nappe-rivière
- qdeb : débordement

Le driver utilise ```comm.Recv(...)``` pour reconstruire les tableaux globaux.

## 2.9 Post-traitement et synchronisation

Le driver envoie ensuite les résultats au processus de post-traitement, puis attend une synchronisation globale.
Cela garantit que toutes les sorties sont écrites et que tous les modèles sont synchronisés.

# 3 - Contraintes pour intégrer un nouveau modèle

## 3.1 Compatibilité MPI
Le modèle doit posséder une interface qui puisse utiliser MPI, posséder un rank MPI et communiquer via Send/Recv.
Le modèle doit être capable de recevoir des données, et de renvoyer ses résultats.
Le modèle (ou son interface) devra également respecter les convention aquiFR pour les tags à utiliser, les variables à recevoir et envoyer.

## 3.2 Gestion des dimensions
Le modèle doit définir :
- nombre de cellules souterraines
- nombre de cellules rivière
- taille des tableaux échangés

Ces informations sont lues par le driver dans un csv appelé *working_directory_\<modelname\>*.

## 3.3 Compatibilité temporelle
Le modèle doit fonctionner avec le même pas de temps pour être synchronisable avec les autres modèles (une journée).
Il doit accepter un appel à chaque pas de temps et une exécution incrémentale.

## 3.4 Variables de forçage compatibles
Le modèle doit être capable d’utiliser les forçages fournis (voir lesquels).

## 3.5 Variables de sortie standardisées
Le modèle doit renvoyer des tableaux compatibles avec le driver et le post-traitement (exemples : niveaux d'eau, débits, échanges nappe-rivière).

## 3.6 Structure typique d’un modèle
Un modèle intégré doit suivre ce schéma :

1. Initialisation MPI
2. Réception des paramètres
3. Boucle temporelle
4. Réception des forçages
5. Calcul physique
6. Envoi des résultats
7. Synchronisation

# 4 - Structure d'HydroModPy
## 4.1 Entrées
HydroModPy prend en entrée un fichier de configuration au format TOML ou JSON contenant l’ensemble des paramètres nécessaires à la simulation. Ce fichier définit notamment les dates de simulation, le pas de temps, les paramètres physiques, les chemins vers les fichiers de données, les options numériques, les options à activer.

HydroModPy utilise également un dossier */data* contenant différentes données nécessaires au calcul (données climatiques, géologiques, maillages, paramètres hydrauliques)
Les formats de données peuvent varier : CSV, NetCDF, GeoTIFF, fichiers binaires, fichiers texte

## 4.2 Sorties
HydroModPy produit plusieurs types de données de sortie permettant l’analyse des simulations hydrologiques et hydrogéologiques.
Les résultats peuvent être écrits sous différents formats.

## 4.3 Lancement
HydroModPy peut être exécuté de plusieurs façons :
- En ligne de commande :
  ```hydromodpy run config.toml```

- Depuis Python, en utilisant hmp comme une bibliothèque :
  ```
  import hydromodpy as hmp
  model = hmp.Model("config.toml")
  model.run()
  ```

Le lancement depuis Python permettra le couplage avec d'autres outils pour l'intégration dans AquiFR.

# 5 - Interfaçage
L’intégration d’HydroModPy dans AquiFR nécessite le développement d’une surcouche d’interfaçage entre les deux systèmes, pour jouer le rôle d'adaptateur entre l’architecture MPI d’AquiFR et le fonctionnement interne d’HydroModPy.

## 5.1 Gestion MPI
L'interface devra échanger avec le processus MPI principal afin de gérer l’attribution du rank MPI, la réception des données envoyées par le driver, l’envoi des résultats vers le driver et la synchronisation MPI.

## 5.2 Conversion des paramètres AquiFR
AquiFR utilise des fichiers de configuration de type *options.nam*.
L’interface devra donc lire les paramètres AquiFR, extraire les informations utiles et convertir ces paramètres vers un format compatible HydroModPy (JSON ou TOML).

## 5.3 Gestion des données d’entrée
L’interface devra convertir les données reçues depuis AquiFR vers les structures utilisées par HydroModPy.
Ces données se trouveront dans le répertoire Applications

## 5.4 Exécution d’HydroModPy
Une fois les données préparées, l’interface lance HydroModPy pour effectuer le calcul du pas de temps courant.

## 5.5 Récupération des résultats
Après le calcul, l’interface récupère les variables produites par HydroModPy afin de les transmettre au driver AquiFR.
Les principales variables concernées sont : niveaux d’eau, débits, éventuellement échanges nappe-rivière.

Les résultats doivent être remis sous forme de tableaux MPI compatibles, envoyés avec les tags MPI appropriés.