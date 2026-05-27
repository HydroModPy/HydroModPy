# Integration HydroModPy dans AquiFR

Statut : brouillon de cadrage.

Source principale : compte rendu de reunion HydroModPy / AquiFR du 2026-05-27.

## Objectif

Preparer l'integration de HydroModPy comme modele appele par AquiFR.

Le document sert a separer:

- ce qui est compris du fonctionnement AquiFR;
- ce que HydroModPy doit exposer;
- les fichiers AquiFR a renseigner;
- les points ouverts a traiter avant implementation.

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

### Lot 0 - lecture du code AquiFR

Objectif: remplacer les hypotheses du compte rendu par un contrat verifie.

Actions:

1. Lire le driver general AquiFR.
2. Lire un driver modele existant, en priorite EauDyssee.
3. Lire `Data/applications.py`.
4. Lire la structure d'un repertoire `Applications/<application>`.
5. Relever le format exact de `working_directory_<modelname>`.
6. Relever la convention de `var_dim` pour les variables renvoyees.

Livrable: completer ce document avec les chemins exacts, signatures de
fonctions et formats de fichiers.

### Lot 1 - contrat d'application HydroModPy

Objectif: decrire une application HydroModPy minimale compatible AquiFR.

Actions:

1. Choisir le code modele HydroModPy.
2. Definir le schema minimal d'un repertoire application HydroModPy.
3. Definir les champs a ajouter dans `Data/applications.py`.
4. Produire un exemple d'application HydroModPy de test.
5. Produire le CSV `working_directory_<modelname>` correspondant.

### Lot 2 - driver minimal

Objectif: lancer une application HydroModPy depuis le driver AquiFR sans encore
chercher a couvrir tous les cas.

Actions:

1. Initialiser HydroModPy depuis le repertoire application.
2. Recevoir un pas de forcage.
3. Lancer un pas de temps ou une sequence courte.
4. Renvoyer une sortie minimale, probablement `qdeb` si c'est bien la variable
   cible prioritaire.
5. Verifier la taille et l'ordre du vecteur renvoye.

### Lot 3 - sorties et validation

Objectif: rendre le couplage testable.

Actions:

1. Ajouter des tests de taille de vecteur par application.
2. Ajouter des tests d'unites et de signe pour les variables renvoyees.
3. Comparer les sorties standalone HydroModPy et mode AquiFR sur un cas simple.
4. Verifier le comportement multi-applications.
5. Documenter les limites du premier lot.

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
