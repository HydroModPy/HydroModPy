Ce fichier est destiné aux utilisateurs souhaitant tester HydroModPy avant le 28 septembre, date à laquelle il sera possible d'installer HydroModPy sans cloner le dépôt Git, via la commande `pip install hydromodpy` (actuellement non disponible).

Ne lancez que les fichiers `stepX_XXX.toml`.

1. Si vous utilisez Anaconda/Miniconda/Mamba, créez un environnement :
   `conda create -n XXX python=3.13`
2. Dans un terminal, activez-le :
   `conda activate XXX`
3. Placez-vous à la racine du dépôt, puis :
   `pip install -e .`

HydroModPy est installé en mode développeur :D

4. Déplacez-vous dans le dossier `examples/projects/04_streamflow_intermittence_in_transient`.
5. Depuis le terminal, vous pouvez maintenant exécuter chacun des scripts via :
   `hmp run XXX.toml`

Comme expliqué durant la présentation, le fichier `step5_export.toml` est encore soumis à réflexion quant à la forme d'appel pour l'export des résultats, pour avoir une interface utilisateur, via le TOML, plus pratique et agréable.

Les fichiers exportés par le step5 se trouvent dans le dossier `share`, et les figures dans `run/NOM_DE_LA_SIMULATION/figures`.