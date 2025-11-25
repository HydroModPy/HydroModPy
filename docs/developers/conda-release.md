# Publication Conda de `hydromodpy`

Ce guide détaille toutes les étapes pour construire localement la recette Conda, la tester, publier sur un canal personnel (équivalent à un *TestPyPI*) puis proposer l’intégration sur conda-forge.

## 1. Pré-requis

- Installer une distribution Conda supportant `conda-forge` (Mambaforge/Miniforge recommandée).
- Dans un environnement de travail, installer les outils nécessaires :

```bash
mamba install -n base conda-build boa anaconda-client conda-forge-pinning
```

`boa` (alias `conda mambabuild`) accélère les builds. Adapter avec `conda build` si `mamba` n’est pas disponible.

## 2. Construire la recette locale

La recette est définie dans `conda.recipe/`. Elle s’appuie sur le code source du dépôt actuel (`source: path: ..`).

```bash
cd /chemin/vers/97-HydroModPy-dev-python-upgrade
conda mambabuild conda.recipe -c conda-forge
```

Cette commande construira la variante `noarch` pour chaque version de Python listée dans `conda.recipe/conda_build_config.yaml` (3.11 à 3.13). Les paquets `.tar.bz2` apparaîtront dans `$(conda info --base)/conda-bld/noarch/`.

## 3. Tester le paquet construit

```bash
conda create -n hydromodpy-conda-test python=3.11 --yes
conda activate hydromodpy-conda-test
conda install hydromodpy --use-local -c conda-forge --yes
python - <<'PY'
import hydromodpy
import importlib
importlib.import_module("hydromodpy.watershed")
print("HydroModPy version:", hydromodpy.__version__)
PY
```

`--use-local` pointe sur le dépôt `conda-bld`. Adapter la version de Python et exécuter quelques scripts/fichiers du dossier `examples/` pour vérifier le comportement réel.

## 4. Publier sur un canal Anaconda « test »

1. Créer (une fois) le canal sur https://anaconda.org/ en choisissant éventuellement un *label* `test`.
2. Connectez-vous : `anaconda login`.
3. Téléversez les builds :

```bash
anaconda upload -l test $(conda info --base)/conda-bld/noarch/hydromodpy-*.tar.bz2
```

4. Partagez le canal : `conda config --add channels <utilisateur>/test`. Les utilisateurs et CI peuvent ainsi installer via `conda install -c <utilisateur>/test -c conda-forge hydromodpy`.

## 5. Préparer la soumission conda-forge

1. Fork `https://github.com/conda-forge/staged-recipes` et créez une branche `hydromodpy`.
2. Copiez `conda.recipe/` dans `recipes/hydromodpy/`, mais modifiez la section `source` pour utiliser l’archive PyPI officielle :

```yaml
source:
  url: https://pypi.io/packages/source/h/hydromodpy/hydromodpy-{{ version }}.tar.gz
  sha256: <empreinte à récupérer avec `pip download hydromodpy=={{ version }}` + `openssl sha256`>
```

3. Ajustez la section `about` pour ne plus lire `pyproject.toml` (remplacer les variables Jinja par des littéraux) et vérifiez que la liste `recipe-maintainers` correspond aux comptes GitHub.
4. Ouvrez la Pull Request ; la CI de `staged-recipes` construira pour Linux/macOS/Windows et validera les dépendances Python 3.11–3.13 définies dans `conda_build_config.yaml`.
5. Après fusion, un dépôt `hydromodpy-feedstock` sera créé dans l’organisation `conda-forge`. Les futures sorties se gèrent en ouvrant des PR sur ce feedstock (mise à jour de `meta.yaml`, relance `conda-smithy rerender`).