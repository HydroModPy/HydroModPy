# Intégration d'HydroModPy dans AquiFR
Ce document suit l'intégration d'HydroModPy dans AquiFR. Pour l'instant, il indique les étapes à suivre les informations requises/manquantes pour les réaliser. 

## 1. - Ajout d'une application HydroModPy dans AquiFR

Une première étape consiste à ajouter parmi les applications d'AquiFR un des sites d'HydroModPy. Le site choisi pour cette étape est le Nançon (projet *02_nancon_watershed*).
Les étapes à suivre pour intégrer une nouvelle application sont décrites dans la fiche *AquiFR_PROC_ADD_NEW_V2.odt*.

### 1.1 - */Data*
#### 1.1.1 - */Data/python_scripts/applications.py*

Dans ce script, un élément correspondant au Nançon a été (partiellement) ajouté au dictionnaire :
```
# Application HydroModPy
# -----
app = 'Nancon'
Applications_dict[app] = {
        'name': app,
        'code': app.lower(),
        #'nb_layers' : ?,
        #'nb_cells': ?,
        #'dx_min' : ?,
        #'nb_rivcells': ?,
        'model': 'HMPY',
        'appdir': '{0}/Application/{1}'.format(AQUIFRDIR, app.lower()),
        'spatial_ref': 'L93'#,
        #'aquifers': {'nb_layers' : ?,
        #             'names': [?],
        #             'nb_cells': [?],
        #             'type': [?],
        #             }
        }
```
Les informations manquantes sont :
- nombre de couches hydrogéologiques
- nombre de cellules
- dx minimal
- nombre de cellules rivières
- type de grille
- Pour chaque couche :
  - nom
  - nombre de cellules
  - type (aquifère ou NULL)

**Question : De quels fichiers extraire ces informations ?**

#### 1.1.2 - */Data/grid_files*

Deux fichiers doivent être créés dans ce répertoire :
- *nancon_sou_L93* qui indique pour chaque cellule sous-terraine : les coordonnées x, y du centroïde, la dimension de la cellule, l'identifiant de la couche
- *nancon_riv_L93* qui indique pour chaque cellule rivière : les coordonnées x, y du centroïde, la dimension de la cellule, l'identifiant de la couche
On fera un script *create_hmpy_grid_files.py* qui extraie les info et rédige les deux fichiers.

**Question : De quels fichiers extraire ces informations ?**

#### 1.1.3 - */Data/python_scripts*
(en attente des fichers *nancon_sou_L93* et *nancon_riv_L93*)

#### 1.1.4 - */Data/sqlite*
(en attente de l'étape 1.3)

### 1.2 - Dossier dans */Applications*

Le sous-répertoire */Applications/hmpy_nancon* a été ajouté ici. Il contient :
- le fichier *project.TOML* de la simulation
- tous (?) les fichiers contenus dans le dossier */Data* de HMP et utilisés dans cette simulation :
  - etp_sim2_5347fa22_20000101_20251231.nc
  - DEM_armorican_massif.tif
  - runoff_custom_NANCON_20000101_20021231_M.csv
  - recharge_custom_NANCON_20000101_20021231_M.csv
  - hydrometry_custom_NANCON_19820201_20220125_D.csv

**Questions :**

- Pour la géologie, le TOML indique :
  ```
  [[data.geology.sources]]
  source = "brgm_1m"
  ```
  **Il existe plusieurs fichiers *examples\data\geology\geology_brgm_1m_\*\*\*.gpkg*. Lesquels sont nécessaires pour cette application ?**

- Pour l'hydrographie, le TOML indique :
  ```
  [[data.hydrography.sources]]
  source = "bdtopage"
  ```
  **Il existe plusieurs fichiers *examples\data\hydrography\bdtopage_\*\*\*.gpkg*. Lesquels sont nécessaires pour cette application ?**

### 1.3 - *LIB/python_modules/aquifr_modules/aquilib.py*

Pour compléter ce script, on a besoin des mêmes informations que dans la partie 1.1.

## 2. - Ajout d'un driver minimal HydroModPy
L'objectif de cette étape est de pouvoir lancer une application HydroModPy depuis le driver AquiFR sans encore chercher a couvrir tous les cas, pour faire le branchement entre les deux.

### 2.1 - Création du dossier HydroModPy
Comme chaque modèle, HydroModPy devra avoir un dossier à la racine du projet contenant le code du modèle et un driver qui fera la communication avec le driver général AquiFR.

#### 2.1.1 - Code ModFlow
Le dossier devra contenir les modèles HydroModPy (ModFlow). Comme on ne peut pas fournir directement les exécutables pour des questions de sécurité, il faudra fournir le code pour qu'il soit recompiler puis utilisé comme binaire.

#### 2.1.2 - Driver HydroModPy
Le dossier devrai contenir un driver capable de faire le lien entre HydroModPy et le driver AquiFR.
Celui-ci devra notamment :
- Déterminer si HydroModPy est lancé depuis AquiFR ou en version standalone
- Etablir la communication MPI avec le driver AquiFR
- Recevoir les forçages d'AquiFR et les transmettre à HydroModPy dans un format recevable
- Faire tourner un pas de temps journalier
- Convertir les données produites par HydroModPy dans le format attendu par AquiFR : un vecteur pour le débit et un vecteur pour la hauteur d'eau.

### 2.2 - Modification du driver AquiFR
Le fichier *Driver/aquifr_driver.py* est le driver principal d'AquiFR. Il monitore la communication MPI et la synchronisation des modèles. Il faudra donc ajouter HydroModPy aux modèles traités dans ce code. 
