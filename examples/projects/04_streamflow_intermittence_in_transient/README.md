# Exemple 04 : intermittence des écoulements du Nançon

Le bassin du Nançon (Ille-et-Vilaine), simulé avec MODFLOW 6. L'exemple montre
comment le réseau de suintements s'étend en hiver et se rétracte en été, et
comment K et Sy se calent sur le réseau cartographié et sur le débit jaugé.

## Les fichiers, dans l'ordre

Chaque étape hérite de la précédente (`base_config`) et n'écrit que ce qui change.

1. `step1_minimal.toml` : permanent, MNT local, un K, une recharge moyenne.
2. `step2_local_data.toml` : ajoute le réseau cartographié et la station, en fichiers locaux.
3. `step3_api_data.toml` : les mêmes données, prises aux API BD Topage et Hub'Eau.
4. `step4_transient.toml` : transitoire mensuel 2000-2002, recharge et ruissellement observés.
5. `step5_export.toml` : exporte les résultats, un bloc `[[export]]` par format.

Autour des étapes :

- `project.toml` : le modèle de référence, figé, avec toutes les figures.
- `run_daily.toml` : le même modèle au pas journalier.
- `run_calibration.toml` : calage de K puis Sy par le protocole publié.
- `run_calibration_by_hand.toml` : le même calage, écrit en deux phases.
- `run_calibration_composite.toml` : K et Sy ensemble, réseau et hydrogramme pondérés.

## Commandes

Depuis ce dossier, après `pip install hydromodpy` :

```bash
hmp run step1_minimal.toml          # puis step2 à step5
hmp calibrate run_calibration.toml --check
hmp calibrate run_calibration.toml --list-phases
hmp run run_calibration.toml        # idem pour les deux autres fichiers de calage
hmp export nancon_step5_export --list
```

Les étapes 3 à 5 lisent BD Topage et Hub'Eau : il faut un accès réseau au premier lancement,
les réponses sont ensuite en cache. Le calage composite dure environ une heure.

## Où sont les sorties

- figures : `runs/<nom>/figures/`
- exports : `share/<nom>/`

`<nom>` est le `[simulation] name` du fichier lancé, par exemple `nancon_step5_export`.
