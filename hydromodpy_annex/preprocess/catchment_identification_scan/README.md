# Extraction des bassins versants >= seuil a partir d'un MNT

## Objectif

Identifier automatiquement, a partir d'un MNT projete en metres:

- tous les bassins versants d'aire >= seuil
- les coordonnees des exutoires
- les polygones des bassins

Produits de sortie:

- un GeoPackage contenant:
  - `bassins_5km2` (dans la config par defaut)
  - `exutoires_5km2` (dans la config par defaut)
- un CSV listant les exutoires.

Le workflow est fourni au format case runnable (`run_*.py` + config TOML), coherent
avec le style des scripts de lancement HydroModPy.

## Dossier

Ce dossier contient:

- `run_catchment_identification_case.py`: script de lancement principal
- `config_headwater_100km2.toml`: cas headwater autour de 100 km2
- `config_s3_10km2.toml`: cas ordre de Strahler 3 autour de 10 km2 (fenetre 5-20 km2)
- `config_1000km2.toml`: cas autour de 1000 km2
- `config_s3_100km2.toml`: cas ordre de Strahler 3 autour de 100 km2 (config par defaut)
- `config.py`: chargement/validation de la configuration
- `workflow.py`: logique de traitement geospatial
- `diagnostic_plots.py`: generation des figures de controle

## Principe du workflow

1. (optionnel) decoupe du MNT par un polygone de region
2. correction hydrologique du MNT (`fill` ou `breach`)
3. calcul D8 de la direction d'ecoulement
4. calcul D8 de l'accumulation (en nombre de cellules, non log)
5. detection des exutoires candidats selon le mode choisi:
   - `border`: uniquement sur la bordure du domaine
   - `scan_global`: scan tuile du MNT complet (max locaux + distance minimale)
6. delineation multi-bassins a partir des exutoires
7. filtrage des bassins `>= accumulation_area_km2`
8. (optionnel) selection `headwater_target`: bassins de tete (ordre de Strahler de 1 a `headwater_max_strahler_order`), proches de la taille cible et quasi non recouvrants
9. export GeoPackage + CSV

## Parametres TOML principaux

Section: `[catchment_identification_scan]`

- `launcher_script`: chemin du script de lancement (trace explicite du run)
- `dem_path`: chemin vers le MNT
- `region_polygon_path` (optionnel): limite de la zone d'etude
- `output_dir`: dossier de sortie, de preference sous `~/HydroModPy/catchment_identification_scan`
- `accumulation_area_km2`: seuil de surface d'accumulation (ex: `100.0`)
- Sur le jeu de donnees par defaut fourni ici, une valeur de `5.0` km2 fonctionne.
- `outlet_selection_mode`: `"border"` ou `"scan_global"`
- `scan_tile_size_km`: taille de tuile pour `scan_global`
- `scan_max_outlets_per_tile`: nombre max d'exutoires retenus par tuile
- `scan_min_outlet_spacing_km`: distance minimale entre exutoires retenus
- `scan_max_total_outlets`: plafond global d'exutoires pour limiter le temps de calcul
- `basin_selection_mode`: `"all_min_area"` ou `"headwater_target"`
- `headwater_max_strahler_order`: ordre de Strahler max conserve en mode `headwater_target`
- `headwater_min_target_ratio`: ratio minimum strict (ex: `0.5` pour interdire les bassins < 50% de la cible)
- `target_area_tolerance_ratio`: tolerance relative autour de `accumulation_area_km2` (mode `headwater_target`)
- `max_basin_overlap_ratio`: recouvrement max autorise entre bassins retenus (mode `headwater_target`)
- `dem_correction`: `"fill"` ou `"breach"`
- `snap_dist`: distance de snapping des exutoires (m)
- `gpkg_name`, `basins_layer`, `outlets_layer`, `outlets_csv_name`
- `save_diagnostic_figures`: active/desactive l'export des figures de controle
- `figures_dir_name`: nom du dossier des figures sous `output_dir`

Comportement par defaut:

- si `output_dir` est omis, les resultats partent maintenant vers `~/HydroModPy/catchment_identification_scan/<nom_config>`
- un `output_dir` relatif commencant par `outputs/` est redirige vers `~/HydroModPy/catchment_identification_scan/...`
- les cles inconnues dans `[catchment_identification_scan]` sont refusees.

## Lancement

Depuis la racine du repo:

```bash
python -m hydromodpy_annex.preprocess.catchment_identification_scan.run_catchment_identification_case --config hydromodpy_annex/preprocess/catchment_identification_scan/config_s3_100km2.toml
```

## Notes donnees

- Le MNT doit etre dans un CRS projete en metres (ex: EPSG:2154).
- Si `region_polygon_path` est renseigne, le polygone est reprojete vers le CRS du MNT avant decoupe.
- La couche de sortie `bassins_5km2` contient l'aire du bassin et les attributs de l'exutoire associe (config par defaut).
- Le script affiche une progression en pourcentage (etapes macro du workflow).
- Figures de controle exportees (si activees): vue spatiale, accumulation/seuil, coherence aire exutoire vs bassin, histogramme des surfaces.
- Si le seuil est trop eleve, le script indique maintenant la valeur max atteignable (`max_accumulation_area_km2`) pour aider au reglage.
- En mode `headwater_target`, le script impose des exutoires de tete (ordre de Strahler <= `headwater_max_strahler_order`), applique une borne basse stricte via `headwater_min_target_ratio`, favorise des bassins proches de la taille cible et elimine les recouvrements forts.
