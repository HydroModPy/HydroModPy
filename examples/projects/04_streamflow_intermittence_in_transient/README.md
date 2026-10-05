# Exemple 04 : intermittence des écoulements du Nançon

Le bassin du Nançon (Ille-et-Vilaine), simulé avec MODFLOW 6. L'exemple montre
comment le réseau de suintements s'étend en hiver et se rétracte en été, et
comment K et Sy se calent sur le réseau cartographié et sur le débit jaugé.

## Les fichiers, dans l'ordre

Chaque étape hérite d'une autre (`base_config`) et n'écrit que ce qui change. L'étape 3 est
une variante de l'étape 2 sur données d'API ; l'étape 4 repart des données locales de
l'étape 2 ; l'étape 6 repart de `project.toml`.

1. `step1_minimal.toml` : permanent, MNT local, un K, une recharge moyenne.
2. `step2_local_data.toml` : ajoute le réseau cartographié et la station, en fichiers locaux.
3. `step3_api_data.toml` : les mêmes données, prises aux API BD Topage et Hub'Eau.
4. `step4_transient.toml` : transitoire mensuel 2000-2002, recharge et ruissellement observés.
5. `step5_export.toml` : la vitrine des exports, un bloc `[[export]]` par format.
6. `step6_soil_reservoir.toml` : journalier 2015-2020, la recharge calculée par un réservoir
   sol à partir de la pluie et de l'ETP SIM2 ; l'ETP que le sol n'a pas satisfaite est prise
   à la nappe.

Autour des étapes :

- `project.toml` : le modèle de référence, figé, avec toutes les figures.
- `run_daily.toml` : le même modèle au pas journalier.
- `run_calibration.toml` : calage de K puis Sy par le protocole publié.
- `run_calibration_by_hand.toml` : le même calage, écrit en deux phases.
- `run_calibration_composite.toml` : K et Sy ensemble, réseau et hydrogramme pondérés.
- `run_calibration_bdtopage.toml` : le calage en deux phases sur BD Topage. K sur les deux
  bornes de l'extension, le réseau permanent et le réseau complet, puis Sy sur le débit.
- `run_calibration_api_daily.toml` : tout par API sauf le MNT (BD Topage, Hub'Eau, SIM2),
  journalier 2015-2020. K prend cinq valeurs fixées, chaque run est gardé avec ses figures.

## Commandes

Depuis ce dossier, après `pip install hydromodpy` :

```bash
hmp run step1_minimal.toml          # puis step2 à step5
hmp run step6_soil_reservoir.toml --until load_data   # le sol seul : bilan en mm/an, aucun run écrit
hmp calibrate run_calibration.toml --check
hmp calibrate run_calibration.toml --list-phases
hmp run run_calibration.toml        # idem pour les autres fichiers de calage
hmp export nancon_step5_export --list
```

L'étape 3 lit BD Topage et Hub'Eau : il faut un accès réseau au premier lancement, les
réponses sont ensuite en cache ; de même pour `run_calibration_bdtopage.toml`,
`run_calibration_api_daily.toml` et `step6_soil_reservoir.toml` (pluie et ETP SIM2). Le
calage composite et le calage BD Topage durent chacun environ une heure.

## Depuis Python

Les mêmes fichiers se pilotent depuis un script. Chaque script retrouve le projet à
partir de son propre emplacement : il se lance depuis n'importe quel dossier, et se
parcourt cellule par cellule (`# %%`) dans Spyder ou VS Code.

1. `py1_run_and_plot.py` : lance `step4_transient.toml` avec `hmp.run`, puis trace une
   figure maison, la surface suintante du bassin face au débit.
2. `py2_edit_parameters.py` : charge `project.toml` en objet Python, change K et Sy,
   lance la variante et la compare à la référence.
3. `py3_read_exports.py` : refait une figure à partir des seuls fichiers de `share/`
   (GeoPackage, GeoTIFF, CSV, NetCDF), sans importer HydroModPy. Il lui faut les exports
   de `step5_export.toml`.
4. `py4_sweep_k.py` : cinq valeurs de K sur un même `Project`, qui ne construit le
   maillage qu'une fois. Le débit ne départage pas les K, la surface suintante si.
5. `py5_catalog.py` : ouvre le catalogue du projet, compare les scores des runs,
   redessine une figure du catalogue à d'autres dates et exporte un état que le TOML ne
   demandait pas.
6. `py6_monthly_maps.py` : les douze mois de 2002 sur une planche et les 36 mois en GIF,
   la nappe affleurante dessinée cellule par cellule.

Les scripts 5 et 6 lisent le run de `project.toml` sans le relancer : `hmp run
project.toml` d'abord, ou `py2_edit_parameters.py`, qui le lance.

## Où sont les sorties

Chaque fichier dessine ses figures et écrit ses exports. L'étape 1 déclare trois exports,
les étapes 2 à 4 en héritent et en ajoutent (`[[export__append]]`), l'étape 5 repart
d'une liste vide (`export__delete`). Les fichiers de calage écrivent les exports de
`project.toml` pour chaque run promu ; celui sur API a les siens, datés de 2019.

- figures : `runs/<nom>/figures/`
- exports : `share/<nom>/`
- figures des scripts qui comparent plusieurs runs : `share/figures/`

`<nom>` est le nom du run : le `[simulation] name` du fichier lancé, par exemple
`nancon_step5_export`, suivi du nom de la phase pour un calage en plusieurs phases.
