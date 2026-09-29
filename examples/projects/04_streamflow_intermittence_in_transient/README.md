# Exemple 04 : intermittence des écoulements du Nançon

Le bassin du Nançon (Ille-et-Vilaine), simulé avec MODFLOW 6. L'exemple montre
comment le réseau de suintements s'étend en hiver et se rétracte en été, et
comment K et Sy se calent sur le réseau cartographié et sur le débit jaugé.

## Les fichiers, dans l'ordre

Chaque étape hérite d'une autre (`base_config`) et n'écrit que ce qui change. L'étape 3 est
une variante de l'étape 2 sur données d'API ; l'étape 4 repart des données locales de l'étape 2.

1. `step1_minimal.toml` : permanent, MNT local, un K, une recharge moyenne.
2. `step2_local_data.toml` : ajoute le réseau cartographié et la station, en fichiers locaux.
3. `step3_api_data.toml` : les mêmes données, prises aux API BD Topage et Hub'Eau.
4. `step4_transient.toml` : transitoire mensuel 2000-2002, recharge et ruissellement observés.
5. `step5_export.toml` : la vitrine des exports, un bloc `[[export]]` par format.

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
hmp calibrate run_calibration.toml --check
hmp calibrate run_calibration.toml --list-phases
hmp run run_calibration.toml        # idem pour les autres fichiers de calage
hmp export nancon_step5_export --list
```

L'étape 3 lit BD Topage et Hub'Eau : il faut un accès réseau au premier lancement, les
réponses sont ensuite en cache ; de même pour `run_calibration_bdtopage.toml` et
`run_calibration_api_daily.toml`. Le calage composite et le calage BD Topage durent
chacun environ une heure.

## Où sont les sorties

Chaque fichier dessine ses figures et écrit ses exports. L'étape 1 déclare trois exports,
les étapes 2 à 4 en héritent et en ajoutent (`[[export__append]]`), l'étape 5 repart
d'une liste vide (`export__delete`). Les fichiers de calage écrivent les exports de
`project.toml` pour chaque run promu ; celui sur API a les siens, datés de 2019.

- figures : `runs/<nom>/figures/`
- exports : `share/<nom>/`

`<nom>` est le nom du run : le `[simulation] name` du fichier lancé, par exemple
`nancon_step5_export`, suivi du nom de la phase pour un calage en plusieurs phases.
