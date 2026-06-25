# CR Réunion HydroModPy - AquiFR 27/05/2026

**Pourquoi on a une liste de rang MPI par modèle et pas un seul rang ?**
Il faut distinguer les modèles des applications. Pour un modèle, il y a plusieurs applications. Et 1 rang MPI par application. Il est donc possible d'avoir un processeur par application mais il faut voir si c'est optimal. (Exemple : Eros a 24 aquiferes sur un seul processeur car trop petits pour être sur un processeur chacun)

**Des fichiers csv *working_directory_\<modelname\>* décrivent le nombre de cellules souterraines et le nombre de cellules rivière pour les applications de chaque modèle. Est-ce que c'est un fichier par modèle qui contient toutes les applications ?**
Oui.

**Après la lecture des nombres de mailles, des indices sont calculés. A quoi servent-ils ?**
A la fin d'un pas de temps, on reçoit les résultats des modèles et on les envoie au pre_postproc regroupées dans un unique vecteur par variable. Les indices permettent que les données soient agrégées dans ce vecteur par application.

**Pourquoi tous les modèles ne reçoivent pas les mêmes paramètres ? Est-ce qu'on pourrait ajouter des paramètres spécifiques à notre modèle qui serait envoyé seulement à celui-ci ?**
Les paramètres lus dans *options.nam* sont les paramètres de la simulation, tous ne sont pas transmis à tous les modèles mais ce sont les paramètres généraux de la simulation. Les paramètres propres à notre modèle peuvent être définis dans le sous-répertoire de chaque application.

**A quoi correspondent les noms de variables renvoyées par les modèles ?**
h : charge/piézométrie
q : débit rivière
qnr : échange nappe-rivière
qdeb : débordement
Pour nous, seulement le débordement peut être renvoyé mais pas qnr.

---
Deux modules Pyhton : apyfr et aquifr_modules
Dans aquifr_modules, un dictionnaire ```var_dim``` permet de préciser quelles variables vont être simulées et sur quells dimensions. Les dimensions : 
- ```sou``` : mailles des couches sous-terraines
- ```sur``` : mailles des couches sous-terraines qui se retrouven à la surface (donc sous-ensemble de ```sou```) -> permettent de sélectionner celles qu'on va utiliser pour la piézométrie
- ```riv``` : mailles de rivière (dépend des modèles, dans EauDyssée ```riv```=```sou```)
- ```qnr``` et ```qdeb``` sont aussi utilisées de manières différentes selon les modèles (Marthe != EauDyssée par exemple)

---
Il y a le driver général et un driver pour chaque modèle qui va déterminer quelle version on utilise :
- version standalone pour lancer le modèle hors AquiFR
- version AquiFR : ce qu'on va devoir mettre en place pour communiquer entre notre modèle et AquiFR et qui va permettre de recevoir les forçages, récupérer les mailles qui nous intéressent parmi toute la France et envoyer les résultats à chaque pas de temps. Il faudra aussi mettre ces résultats sous forme de vecteur.
Dans EauDyssée par exemple, ça se fait dans le code qui se trouve dans *src/mysrc*.

---
**Fichier *Data/appications.py* :** définit, pour chaque application, des variables qui seront utilisées ensuite dans tout le code (nom de l'appli, nombre de couches sous-terraines, nombre de cellules(= mailles sous-terraines))

**Répertoire *Applications* :** il faudra ajouter un répertoire par application qu'on aura avec notre modèle. Si possible trouver un code de 4 caractères pour notre modèle pour le nommage des répertoires. 
Chaque application contient les options, fichiers d'états initiaux, etc.
Etat initial : correspond à l'état initial en focntion de la période de calibration choisie pour notre application, pas d'homomgénéité imposée pour cette préiode.

---
Les forçages safran sont sur des grilles régulières. Ce n'est pas un problème pour nous même si nos grilles ne sont pas régulières (filtres pour convertir grilles safran-surfex dans HydroModPy).

---
Quelle version de modflow on intègre ? Voir avec Luca.

---
##### Date de prochaine réunion
09/06/2026 14h

