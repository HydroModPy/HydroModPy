# Integration HydroModPy dans AquiFR

Statut : brouillon de cadrage.

Sources principales :

- compte rendu de reunion HydroModPy / AquiFR du 2026-05-18;
- compte rendu de reunion HydroModPy / AquiFR du 2026-05-27;
- fiche d'integration d'une nouvelle application dans AquiFR.

## Objectif

Preparer l'integration de HydroModPy comme modele appele par AquiFR.

Le document sert a separer:

- ce qui est compris du fonctionnement AquiFR;
- ce que HydroModPy doit exposer;
- les fichiers AquiFR a renseigner;
- les points ouverts a traiter avant implementation.

Objectif complementaire cote HydroModPy: prevoir aussi comment les resultats
AquiFR pourront etre integres ou relus dans HydroModPy, au-dela du seul sens
HydroModPy vers AquiFR.

## Perimetre vise

L'integration doit permettre a AquiFR de lancer HydroModPy en mode couple,
sur une ou plusieurs applications, avec:

- une entree decrivant les applications HydroModPy;
- un repertoire par application;
- un driver AquiFR specifique au modele HydroModPy;
- la reception des forcages;
- la selection des mailles utiles pour l'application;
- l'execution d'un pas de temps HydroModPy;
- le renvoi des sorties sous forme de vecteurs au format attendu par AquiFR.

Le mode standalone HydroModPy doit rester disponible. Le driver AquiFR ne doit
pas devenir le chemin unique de lancement du modele.

## Concepts AquiFR retenus

### Modele et applications

AquiFR distingue le modele et ses applications.

Un modele peut avoir plusieurs applications. La repartition MPI se fait au
niveau des applications: il peut y avoir un rang MPI par application. Ce point
doit rester configurable, car un rang par application n'est pas toujours optimal
pour les petits domaines.

### Cycle journalier et communication MPI

Le driver general AquiFR est code en Python et communique avec les modeles via
MPI, notamment `mpi4py`. Les modeles existants sont principalement en Fortran,
mais un modele Python est possible.

Le pas de temps de simulation est journalier. A chaque iteration:

1. le driver recupere les forcages du jour;
2. il les envoie aux modeles;
3. chaque modele avance sa simulation;
4. chaque modele renvoie ses resultats au driver;
5. le driver transmet les sorties au pre/post-traitement.

Entre deux iterations, un modele ne doit pas necessairement s'arreter puis
redemarrer. Il peut rester en pause, en attente des forcages du jour suivant.

AquiFR permet aussi d'arreter une simulation a un temps donne puis de la
reprendre depuis l'etat final. Le contrat HydroModPy-AquiFR doit donc couvrir
le maintien en memoire entre deux jours et la persistence d'etat pour reprise.

### Fichier `working_directory_<modelname>`

Le fichier CSV `working_directory_<modelname>` decrit les applications d'un
modele. Il contient notamment le nombre de cellules souterraines et le nombre de
cellules riviere par application.

Point retenu: un fichier par modele contient toutes les applications de ce
modele.

### Indices d'agregation

Apres lecture des nombres de mailles, AquiFR calcule des indices. Ces indices
servent a regrouper, a la fin d'un pas de temps, les resultats des applications
dans un vecteur unique par variable avant envoi au `pre_postproc`.

HydroModPy doit donc etre capable de produire ses sorties par application, puis
de les exposer dans l'ordre attendu par ces indices.

### Parametres globaux et parametres modele

Les parametres lus dans `options.nam` sont des parametres generaux de
simulation. Tous ne sont pas transmis a tous les modeles.

Les parametres propres a HydroModPy doivent etre portes par le sous-repertoire
de chaque application. Cela permet d'eviter de surcharger `options.nam` avec des
options specifiques au modele.

## Variables et dimensions AquiFR

AquiFR s'appuie notamment sur les modules Python `apyfr` et `aquifr_modules`.
Dans `aquifr_modules`, le dictionnaire `var_dim` associe les variables simulees
a leurs dimensions.

Dimensions mentionnees:

- `sou`: mailles des couches souterraines;
- `sur`: sous-ensemble des mailles souterraines presentes en surface, utile
  pour la piezometrie;
- `riv`: mailles de riviere. Dans EauDyssee, `riv = sou`, mais ce n'est pas une
  regle generale;
- `qnr`: echange nappe-riviere, avec conventions variables selon les modeles;
- `qdeb`: debordement, avec conventions variables selon les modeles.

Variables AquiFR mentionnees:

- `h`: charge ou piezometrie;
- `q`: debit riviere;
- `qnr`: echange nappe-riviere;
- `qdeb`: debordement.

Point a confirmer pour HydroModPy: le compte rendu indique que le debordement
peut etre renvoye, mais pas `qnr`. Il faut verifier si `h` est attendu,
optionnel ou hors perimetre pour le premier lot.

## Architecture AquiFR retenue

L'architecture AquiFR mentionnee dans les comptes rendus est la suivante:

- un dossier `driver`, contenant le script principal, le script de lecture des
  forcages et le script de pre/post-traitement;
- un dossier par modele;
- un dossier `Applications`, contenant les aquiferes ou applications;
- des modules Python communs, notamment `apyfr` et `aquifr_modules`.

Le pre/post-traitement enregistre les variables, notamment en NetCDF.

Chaque modele porte son propre reseau hydrologique. Le format de grille depend
de l'application; le cas le plus simple a gerer est la grille cartesienne en
Lambert 2 etendue. Pour HydroModPy, cela implique de documenter explicitement
le passage entre les supports internes HydroModPy et les supports attendus par
AquiFR.

## Contraintes code, compilation et bibliotheques

Le compte rendu du 2026-05-18 indique qu'il n'est pas possible d'utiliser
directement un executable MODFLOW dans AquiFR pour des raisons de securite. Le
chemin a etudier passe donc par le code source du modele.

Pour HydroModPy, cela ouvre deux sujets distincts:

- comment appeler HydroModPy depuis le driver AquiFR;
- comment fournir ou compiler les backends necessaires a HydroModPy dans
  l'environnement AquiFR.

Un repertoire modele dedie est attendu cote AquiFR. Le code du modele ou de
l'interface vivrait dans ce repertoire, tandis que les parametres, fichiers
d'etat et donnees propres a chaque application resteraient dans
`Applications/<application>`.

Une reflexion existe cote AquiFR sur les conflits de bibliotheques. Cote
HydroModPy, il faut produire une liste des bibliotheques utilisees avec leurs
versions, en distinguant:

- dependances Python pures;
- dependances geospatiales;
- dependances MPI;
- dependances solveur;
- dependances optionnelles de documentation ou de visualisation qui ne doivent
  pas forcement entrer dans l'environnement AquiFR.

## Acces et methode de travail

Le code AquiFR est accessible sur SourceSup Renater:

```text
https://sourcesup.renater.fr/projects/aqui-fr/
```

Methode retenue:

1. travailler sur un fork AquiFR;
2. cloner ce fork en local;
3. faire la mise en place dans ce fork;
4. separer les modifications AquiFR des modifications HydroModPy;
5. documenter les interfaces des deux cotes.

Acces a tester ou confirmer:

- SourceSup Renater: indique comme OK dans le compte rendu du 2026-05-18;
- FTP des forcages;
- extranet AquiFR.

Deux grandes etapes de travail ont ete identifiees:

1. verifier la communication avec les drivers et les interfaces MPI;
2. etudier les contraintes de compilation et fournir la liste des bibliotheques
   HydroModPy avec numeros de version.

## Fichiers AquiFR a renseigner

### `Data/applications.py`

Ajouter HydroModPy dans `Data/applications.py` avec les informations utilisees
par AquiFR pour chaque application:

- nom de l'application;
- nombre de couches souterraines;
- nombre de cellules souterraines;
- autres champs requis par le driver general.

Le schema exact doit etre releve dans le depot AquiFR avant implementation.

### `Applications/<application>`

Ajouter un repertoire par application HydroModPy.

Chaque repertoire doit contenir:

- les options propres a l'application;
- les fichiers d'etat initial;
- les donnees necessaires au lancement HydroModPy;
- les eventuels fichiers de correspondance mailles / variables.

L'etat initial depend de la periode de calibration de l'application. Le compte
rendu precise qu'il n'y a pas d'homogeneite imposee pour cette periode.

### Code modele a quatre caracteres

AquiFR semble utiliser un code court pour nommer certains repertoires ou
fichiers. Il faut choisir un code de quatre caracteres pour HydroModPy.

Propositions a discuter:

- `HMPY`;
- `HYMP`;
- `HDMP`.

## Driver AquiFR pour HydroModPy

AquiFR utilise un driver general et un driver par modele. Le driver modele
choisit le mode d'execution:

- mode standalone: lancement du modele hors AquiFR;
- mode AquiFR: communication avec AquiFR.

Pour HydroModPy, le driver AquiFR doit au minimum assurer:

1. l'initialisation de l'application HydroModPy;
2. la lecture ou construction du mapping de mailles attendu par AquiFR;
3. la reception des forcages pour le pas de temps courant;
4. la conversion des forcages vers les entrees HydroModPy;
5. l'appel du solveur HydroModPy;
6. l'extraction des sorties a renvoyer;
7. la mise en vecteur des sorties dans l'ordre attendu par AquiFR.

Exemple a inspecter cote AquiFR: EauDyssee, notamment le code situe dans
`src/mysrc`.

## Forcages

Les forcages SAFRAN sont fournis sur grilles regulieres. Ce n'est pas bloquant
pour HydroModPy meme si ses grilles ne sont pas regulieres, car HydroModPy
dispose deja de filtres pour convertir les grilles SAFRAN / SURFEX vers ses
supports.

Travail a formaliser:

- identifier les variables de forcage recues d'AquiFR;
- documenter les unites et conventions temporelles;
- definir le passage grille reguliere vers maillage HydroModPy;
- verifier si la conversion doit etre faite dans AquiFR, dans le driver, ou dans
  HydroModPy.

## Strategie d'implementation proposee

Cette section reprend la fiche d'integration d'une nouvelle application AquiFR
et la transpose a HydroModPy. Les chemins exacts doivent etre verifies dans le
depot AquiFR avant implementation.

### Palier 0 - lecture du code AquiFR

Objectif: remplacer les hypotheses du compte rendu par un contrat verifie.

Actions:

1. Cloner le fork AquiFR localement.
2. Verifier les acces SourceSup, FTP forcages et extranet AquiFR.
3. Lire le driver general AquiFR.
4. Lire les scripts de lecture des forcages.
5. Lire le pre/post-traitement et la production NetCDF.
6. Lire un driver modele existant, en priorite EauDyssee.
7. Lire `Data/python_scripts/applications.py`.
8. Lire la structure d'un repertoire `Applications/<application>`.
9. Relever le format exact de `working_directory_<modelname>`.
10. Relever la convention de `var_dim` pour les variables renvoyees.
11. Relever les imports requis dans `LIB/python_modules/aquifr_modules/`.
12. Produire la liste des dependances HydroModPy avec versions.

Livrable: completer ce document avec les chemins exacts, signatures de
fonctions et formats de fichiers.

### Palier 1 - donnees d'application dans `Data/`

Objectif: declarer une application HydroModPy dans les entrees AquiFR.

#### `Data/python_scripts/applications.py`

Ajouter l'application dans la section du modele HydroModPy.

Informations a fournir pour chaque application:

- nombre de couches hydrogeologiques;
- nombre total de pixels des couches souterraines;
- nombre de pixels par sous-couche;
- nom de chaque sous-couche;
- nombre de pixels riviere si l'application porte un reseau riviere.

Ces informations doivent etre extraites des supports GIS fournis pour
l'application ou des supports HydroModPy equivalents.

#### `Data/grid_files/`

Creer les fichiers de grille attendus par AquiFR:

- `zone_sou_proj`;
- `zone_riv_proj`, si l'application porte des mailles riviere.

Format attendu a confirmer, d'apres la fiche:

```text
X, Y, dim_pix, ID_couche
```

Les coordonnees `X` et `Y` sont celles du centroide du pixel. Le champ
`dim_pix` decrit la taille de pixel. `ID_couche` identifie la couche ou
sous-couche hydrogeologique.

Action recommandee: creer un script dedie de type
`Create_<model>_grid_files.py`. Pour HydroModPy, un nom provisoire serait
`Create_hmpy_grid_files.py`.

Point important: `zone_sou_proj` et `zone_riv_proj` doivent exister avant
d'executer les scripts de generation AquiFR.

#### Chaine de generation `Data/python_scripts/`

Une fois les fichiers `zone_*_proj` crees, executer les scripts AquiFR dans
l'ordre suivant:

1. `create_aquifr_shapefiles.py`;
2. `create_aquifr_surfmasks_from_grass.py`;
3. `export_aquifr_surfmasks_from_grass.py`;
4. `create_aquifr_outlines_from_grass.py`;
5. `get_surfmask_from_sqlite.py`;
6. `create_aquifr_grid_files_nc.py`;
7. `get_surfex_to_app_correspondance.py`;
8. `create_aquifr_db.py`.

La fiche signale que `create_aquifr_outlines_from_grass.py` peut produire une
erreur non resolue tout en creant effectivement `zone_outline`. Ce comportement
doit etre verifie sur l'environnement AquiFR courant.

Points de vigilance:

- completer les listes `applis` avec l'application HydroModPy dans les scripts
  qui les portent;
- verifier les chemins d'acces aux librairies;
- verifier les chemins GRASS, utilise par plusieurs scripts;
- documenter la projection utilisee, souvent `L2E`.

#### `Data/sqlite/`

Apres creation de `aqui_fr.db`, executer:

```text
convert_to_csv.py
```

Livrable du palier 1:

- application declaree;
- fichiers `zone_sou_proj` et eventuellement `zone_riv_proj`;
- base `aqui_fr.db` regeneree;
- exports CSV regeneres.

### Palier 2 - repertoire `Applications/<application>`

Objectif: fournir a AquiFR un dossier application HydroModPy exploitable.

Copier ou creer un repertoire application, en respectant la nomenclature des
autres applications AquiFR. Pour HydroModPy, ce repertoire doit rester le point
d'entree des parametres propres au modele.

Contenu minimal propose pour HydroModPy:

- configuration HydroModPy de l'application;
- etat initial ou pointeur vers un etat initial;
- fichiers de mapping mailles AquiFR vers support HydroModPy;
- sous-dossier `Output/` pour les sorties produites pendant l'execution;
- sous-dossier ou liens vers les fichiers de restart si AquiFR les attend.

Regle de prudence issue de la fiche: ne pas renommer les fichiers fournis par
une application si le modele les consomme deja sous cette architecture. Pour
HydroModPy, cela signifie qu'il faut stabiliser tres tot une nomenclature
d'application et eviter de multiplier les alias.

#### Initialisation et restarts

La fiche EauDyssee signale que certains fichiers d'initialisation peuvent etre
requis par le driver AquiFR meme quand les fichiers d'instruction indiquent
qu'une initialisation n'est pas demandee par le module.

Equivalent HydroModPy a definir:

- quels fichiers d'etat initial sont obligatoires pour le driver AquiFR;
- quels fichiers sont seulement propres a HydroModPy;
- comment produire un premier etat initial si aucun restart n'est disponible;
- ou copier les etats finaux pour une relance longue.

#### Sorties

Creer un sous-dossier `Output/` dans l'application si le driver AquiFR attend
des fichiers de sortie locaux pendant l'execution.

Pour HydroModPy, il faut decider si les resultats transitoires passent:

- uniquement par les vecteurs renvoyes a AquiFR;
- aussi par des fichiers `Output/`;
- ou par le catalogue HydroModPy, en plus du contrat AquiFR.

Livrable du palier 2:

- une application HydroModPy chargeable par AquiFR;
- un etat initial explicite;
- un dossier `Output/` ou une justification si HydroModPy n'en a pas besoin;
- une convention de restart documentee.

### Palier 3 - modules Python AquiFR

Objectif: enregistrer HydroModPy dans la couche Python AquiFR.

Dans `LIB/python_modules/aquifr_modules/`, completer `aquilib.py` avec
l'application HydroModPy a integrer, en respectant la nomenclature existante et
la bonne section de modele.

Verifier aussi:

- la declaration du modele HydroModPy;
- la declaration de ses applications;
- la coherence avec `var_dim`;
- les imports necessaires au driver HydroModPy.

Livrable du palier 3:

- HydroModPy visible dans les modules Python AquiFR;
- application resolue par nom;
- dimensions des variables coherentes avec les fichiers de grille.

### Palier 4 - driver minimal HydroModPy-AquiFR

Objectif: lancer une application HydroModPy depuis le driver AquiFR sans encore
chercher a couvrir tous les cas.

Actions:

1. Initialiser HydroModPy depuis le repertoire application.
2. Recevoir un pas de forcage.
3. Convertir les forcages vers les entrees HydroModPy.
4. Lancer un pas de temps ou une sequence courte.
5. Renvoyer une sortie minimale, probablement `qdeb` si c'est bien la variable
   cible prioritaire.
6. Verifier la taille et l'ordre du vecteur renvoye.

Livrable du palier 4:

- run court executable;
- sortie vectorisee conforme au nombre de mailles attendu;
- logs suffisants pour diagnostiquer lecture d'entrees et ecriture de sorties.

Le premier test technique peut etre limite a la communication driver-modele et
aux interfaces MPI. Il doit verifier que HydroModPy peut rester vivant entre
deux pas journaliers, recevoir un nouveau forcage et repartir depuis son etat
courant sans redemarrage complet.

### Palier 5 - runs longs et validation

Objectif: rendre le couplage testable et preparer une reanalyse longue.

Actions:

1. Faire des essais de run en verifiant que les fichiers d'entree sont lus.
2. Verifier que les sorties ont le bon format.
3. Verifier que les fichiers de restart se completent au fur et a mesure.
4. Lancer une simulation longue de reference, par exemple `1958` a `2013` si ce
   protocole reste celui d'AquiFR.
5. Copier les fichiers d'initialisation depuis le restart final vers le restart
   initial de la nouvelle reanalyse.
6. Relancer une grande reanalyse de `1958` a aujourd'hui.
7. Comparer les sorties standalone HydroModPy et mode AquiFR sur un cas simple.
8. Verifier le comportement multi-applications.
9. Verifier qu'une simulation peut etre arretee puis reprise depuis son etat
   final.
10. Documenter comment les resultats AquiFR peuvent etre integres ou relus dans
   HydroModPy.
11. Documenter les limites du premier lot.

Livrable du palier 5:

- rapport de validation;
- protocole de spin-up / restart;
- liste des variables et conventions validees;
- liste des limites residuelles.

## Exemple identifie: `mod_zone` sur `proj`

Cette section garde volontairement les noms generiques de la fiche AquiFR.
Pour HydroModPy, `mod` sera remplace par le code modele retenu, par exemple
`HMPY`, et `proj` sera souvent `L2E`.

### Nommage

Exemple generique:

- modele: `mod`;
- application: `mod_zone`;
- projection: `proj`;
- fichiers grille: `zone_sou_proj`, `zone_riv_proj`.

Exemple transpose HydroModPy, si le code modele retenu est `HMPY`:

- modele: `hmpy`;
- application: `hmpy_zone`;
- projection: `L2E`;
- fichiers grille: `zone_sou_L2E`, `zone_riv_L2E`.

Le choix `L2E` est coherent avec l'indication que la grille cartesienne en
Lambert 2 etendue est le cas le plus simple a traiter dans AquiFR.

### Arborescence cible minimale

```text
Data/
  grid_files/
    zone_sou_proj
    zone_riv_proj
  python_scripts/
    applications.py
    Create_mod_grid_files.py
  sqlite/
    aqui_fr.db
    convert_to_csv.py

Applications/
  mod_zone/
    project.toml
    initial_state/
    mapping/
    Output/
    RESTARTS/

LIB/
  python_modules/
    aquifr_modules/
      aquilib.py
```

### Exemple de contenu `zone_sou_proj`

Format indicatif a confirmer dans AquiFR:

```csv
X,Y,dim_pix,ID_couche
352500.0,6812500.0,8000,1
360500.0,6812500.0,8000,1
352500.0,6804500.0,8000,2
```

### Exemple de contenu `zone_riv_proj`

Si HydroModPy porte un support riviere separe:

```csv
X,Y,dim_pix,ID_couche
352500.0,6812500.0,8000,1
360500.0,6812500.0,8000,1
```

Si HydroModPy n'a pas de support riviere separe dans le premier lot, il faut
decider explicitement si:

- `zone_riv_proj` est absent;
- `zone_riv_proj` est vide;
- `riv` est pris egal a `sou`;
- un mapping riviere derive est produit.

Cette decision doit etre coherente avec `var_dim` et avec la taille des
vecteurs renvoyes a AquiFR.

### Exemple de checklist pour `mod_zone`

1. Ajouter `mod_zone` dans `Data/python_scripts/applications.py`.
2. Produire `Data/grid_files/zone_sou_proj`.
3. Produire `Data/grid_files/zone_riv_proj` ou documenter son absence.
4. Ajouter `mod_zone` aux listes `applis` des scripts AquiFR requis.
5. Executer la chaine `Data/python_scripts/` dans l'ordre documente.
6. Convertir `aqui_fr.db` vers CSV avec `Data/sqlite/convert_to_csv.py`.
7. Creer `Applications/mod_zone/`.
8. Ajouter la configuration HydroModPy dans ce dossier.
9. Ajouter les etats initiaux ou la procedure de creation du premier etat.
10. Creer `Applications/mod_zone/Output/`.
11. Declarer `mod_zone` dans `LIB/python_modules/aquifr_modules/aquilib.py`.
12. Lancer un run court et verifier la lecture des entrees.
13. Verifier le format et la taille des sorties.
14. Verifier la production ou la mise a jour des restarts.

## Points ouverts

1. Quelle version ou quel backend MODFLOW HydroModPy doit exposer dans AquiFR?
2. Quel code quatre caracteres retenir pour HydroModPy?
3. Quelles variables HydroModPy doivent etre renvoyees dans le premier lot:
   `qdeb` seulement, `h`, autre chose?
4. `riv` doit-il etre egal a `sou` pour HydroModPy, ou faut-il un mapping
   riviere separe?
5. Ou doit vivre le mapping SAFRAN / SURFEX vers mailles HydroModPy:
   AquiFR, driver HydroModPy-AquiFR, ou coeur HydroModPy?
6. Le driver doit-il etre integre dans le depot AquiFR, dans HydroModPy, ou
   maintenu comme couche d'integration separee?
7. Quel niveau de compatibilite est attendu avec les sorties existantes du
   catalogue HydroModPy?
8. Quel cas minimal servira de test d'acceptation?

## Definition provisoire de "fait"

Un premier lot d'integration peut etre considere comme fait si:

1. AquiFR voit HydroModPy comme un modele declare.
2. Au moins une application HydroModPy est decrite dans les fichiers AquiFR.
3. Le driver HydroModPy-AquiFR charge l'application.
4. Un pas de forcage est converti vers HydroModPy.
5. Une sortie HydroModPy est renvoyee sous forme de vecteur de taille correcte.
6. Le meme cas reste lancable en standalone HydroModPy.
7. Les points non couverts sont listes explicitement dans une note de validation.

## Bilan courant et chemin vers la cloture

### Ce qui est deja clarifie

Le cadrage a deja permis de stabiliser plusieurs points structurants:

1. AquiFR se pilote par un driver Python general et des drivers par modele.
2. La communication modele se fait via MPI, avec un cycle journalier.
3. Le bon niveau de parallelisation est l'application, pas seulement le modele.
4. Les applications d'un meme modele sont decrites dans un
   `working_directory_<modelname>` commun.
5. Les sorties de chaque application sont re-agregees dans des vecteurs par
   variable, avec des indices calcules apres lecture des tailles de mailles.
6. Les parametres generaux restent dans `options.nam`; les parametres propres a
   HydroModPy doivent vivre dans le repertoire de chaque application.
7. Les variables et dimensions critiques sont identifiees: `h`, `q`, `qnr`,
   `qdeb`, sur dimensions `sou`, `sur`, `riv` ou conventions propres.
8. Le premier perimetre HydroModPy semble devoir privilegier le debordement
   `qdeb`; `qnr` est indique comme hors perimetre initial a ce stade.
9. La grille cartesienne Lambert 2 etendue est le chemin le plus simple pour un
   premier lot.
10. Les forcages SAFRAN / SURFEX sur grilles regulieres ne sont pas un blocage
    conceptuel, car HydroModPy sait deja faire des conversions vers ses
    supports.
11. Le mode standalone HydroModPy doit rester un chemin de lancement valide.
12. L'integration d'un executable MODFLOW est contrainte par la securite; il
    faut instruire le chemin code source / compilation.

### Ce qui a ete produit cote HydroModPy

Le chantier a produit un document de cadrage unique qui consolide:

- les enseignements des reunions du 2026-05-18 et du 2026-05-27;
- les concepts AquiFR utiles a l'integration;
- les fichiers AquiFR a renseigner;
- une strategie en paliers de `0` a `5`;
- une premiere definition du "fait";
- les points ouverts a trancher avant implementation.

Ce travail reste un cadrage documentaire. Il ne remplace pas encore une lecture
du depot AquiFR ni un prototype d'interface MPI.

### Reste a faire avant implementation

Les actions suivantes doivent etre fermees avant d'ecrire le driver definitif:

1. Cloner le fork AquiFR localement et relever les chemins exacts.
2. Verifier les acces encore ouverts: FTP forcages et extranet AquiFR.
3. Lire le driver general, le pre/post-traitement et un driver modele existant,
   en priorite EauDyssee dans `src/mysrc`.
4. Relever le schema exact de `working_directory_<modelname>`.
5. Relever le schema exact de `Data/python_scripts/applications.py`.
6. Relever les signatures attendues cote driver modele: initialisation, pas de
   temps, sortie, restart.
7. Relever les conventions `var_dim` dans `aquifr_modules`.
8. Choisir le code modele a quatre caracteres, probablement `HMPY` sauf
   contrainte AquiFR.
9. Decider le cas minimal d'acceptation: application, grille, periode courte,
   variable sortie.
10. Decider la version ou le backend MODFLOW a integrer avec Luca.
11. Produire l'inventaire des dependances HydroModPy avec versions et les
    classer par criticite pour AquiFR.
12. Decider le lieu du driver d'integration: depot AquiFR, depot HydroModPy ou
    couche separee.

### Paliers restants jusqu'a cloture

#### Palier A - verification du contrat AquiFR

Objectif: remplacer les hypotheses par des contrats releves dans le code.

Sorties attendues:

- tableau des fichiers AquiFR a modifier;
- signatures du driver modele;
- formats exacts des fichiers de grille et de `working_directory_<modelname>`;
- liste des variables sorties vraiment attendues pour le lot 1;
- note sur la gestion restart / reprise.

Critere de passage: HydroModPy sait quelles fonctions et quels fichiers il doit
fournir, sans hypothese non verifiee sur le depot AquiFR.

#### Palier B - prototype de communication

Objectif: prouver qu'un processus HydroModPy peut etre initialise, rester
vivant entre deux pas journaliers, recevoir des forcages et renvoyer un vecteur.

Sorties attendues:

- driver minimal ou maquette MPI;
- un cas factice ou tres petit;
- verification de taille et d'ordre du vecteur renvoye;
- logs d'initialisation, pas de temps et fermeture.

Critere de passage: un run court MPI passe sans redemarrer HydroModPy entre
deux jours.

#### Palier C - application minimale

Objectif: declarer une vraie application HydroModPy dans AquiFR.

Sorties attendues:

- entree dans `Data/python_scripts/applications.py`;
- fichiers `zone_sou_*` et, si necessaire, `zone_riv_*`;
- repertoire `Applications/<application>`;
- configuration HydroModPy de l'application;
- etat initial ou procedure de generation d'etat initial;
- mapping forcages / mailles / sorties.

Critere de passage: AquiFR voit l'application, charge ses dimensions et accepte
le repertoire application.

#### Palier D - couplage fonctionnel court

Objectif: faire tourner quelques jours avec forcages reels ou fixture courte.

Sorties attendues:

- conversion des forcages vers HydroModPy;
- execution d'un pas ou d'une courte sequence;
- sortie `qdeb` vectorisee, et autres variables si retenues;
- ecriture des fichiers de sortie ou de restart necessaires;
- comparaison minimale avec le mode standalone HydroModPy.

Critere de passage: le meme cas est reproductible en mode AquiFR et en mode
standalone sur une periode courte.

#### Palier E - validation longue et documentation

Objectif: fermer le lot d'integration.

Sorties attendues:

- run long de reference ou protocole de spin-up valide;
- test arret / reprise depuis l'etat final;
- rapport de validation des variables et conventions;
- inventaire des limites du lot 1;
- procedure pour relire ou integrer les resultats AquiFR dans HydroModPy;
- documentation d'exploitation pour relancer le cas.

Critere de cloture: l'integration est reproductible, documentee, et les limites
residuelles sont explicites.

### Decisions a prendre

Les decisions suivantes conditionnent directement la cloture:

1. Code modele: `HMPY`, `HYMP`, `HDMP` ou autre contrainte AquiFR.
2. Application pilote: nom, domaine, projection, taille, periode courte.
3. Backend modele: version MODFLOW / code source / mode de compilation.
4. Variable lot 1: `qdeb` seul ou ajout de `h` / `q`.
5. Support riviere: `riv = sou`, mapping separe ou hors perimetre initial.
6. Driver: emplacement du code et responsabilite de maintenance.
7. Forcages: conversion dans AquiFR, dans le driver ou dans HydroModPy.
8. Resultats AquiFR vers HydroModPy: format lu, niveau de persistence et usage
   attendu.

### Definition de cloture proposee

Le chantier peut etre clos pour un premier lot si:

1. Les acces SourceSup, FTP et extranet sont verifies ou documentes comme
   bloques.
2. Le contrat AquiFR est releve depuis le code, pas seulement depuis les CR.
3. Une application HydroModPy minimale est declaree cote AquiFR.
4. Le driver HydroModPy-AquiFR passe un test MPI court.
5. Les forcages d'un pas journalier sont convertis et appliques.
6. Au moins une variable sortie, prioritairement `qdeb`, est renvoyee au bon
   format vectoriel.
7. La reprise depuis un etat final est testee ou documentee comme limite.
8. Le cas reste executable en standalone HydroModPy.
9. Les dependances et contraintes de compilation sont listees avec versions.
10. Une note de validation de lot 1 decrit ce qui est couvert et ce qui ne l'est
    pas.
