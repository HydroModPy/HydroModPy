Empaquetage conda-forge
=======================

Contexte : HydroModPy est publié sur PyPI et embarque des binaires
upstream (exécutables MODFLOW) dans ``bin/``. Cela requiert un traitement
particulier pour contourner les contrôles standards de conda et les
restrictions réseau CI.

1. Structure du dépôt
---------------------

Dans le fork ``staged-recipes`` :

- Dossier : ``recipes/hydromodpy/``
- Fichiers requis :

  - ``meta.yaml`` (définition du paquet)
  - ``conda_build_config.yaml`` (matrice de build)

2. Configuration de ``meta.yaml``
---------------------------------

Source
~~~~~~

- Utiliser ``url`` pointant vers le ``.tar.gz`` PyPI.
- Renseigner le ``sha256``.
- Ne pas utiliser ``git_url``.

Traitement des binaires
~~~~~~~~~~~~~~~~~~~~~~~

Le paquet embarque des exécutables pré-compilés (``mf6``, ``mfnwt``, ``mp6``,
``mt3dusgs``) dans ``bin/``. Le build conda standard tente de patcher les
RPATH et de vérifier les liens système (``libc``), ce qui fait échouer le
build.

- ``binary_relocation: false`` : conda ne modifie pas les exécutables.
- ``missing_dso_whitelist: - "*"`` : le linter ignore ``OverLinkingError``.

Dépendances et conformité linter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Version Python : ``skip: true # [py<311]`` dans ``build``. Ne pas pinner
  dans ``host`` ou ``run``, simplement lister ``python``.
- Syntaxe : ``python >=3.11`` (pas d'espace après l'opérateur).
- Matplotlib : dépendre de ``matplotlib-base`` pour éviter les lourdes
  dépendances Qt.
- Licence : ``LICENSE`` à la racine de l'archive, pas ``../LICENSE``.

Tests
~~~~~

HydroModPy dépend de ``whitebox-workflows`` et non du legacy ``whitebox``.
Aucun téléchargement de binaire ni injection de ``WBT_PATH`` n'est
nécessaire à l'import.

Commande de test recommandée :

.. code-block:: text

   python -c "import hydromodpy; print(hydromodpy.__version__)"

3. Matrice de build (``conda_build_config.yaml``)
-------------------------------------------------

La configuration standard échoue sur Windows et macOS à cause d'un
pinning Python ambigu. Il faut définir la matrice via ``zip_keys`` :

.. code-block:: yaml

   python:
     - 3.11.* *_cpython
     - 3.12.* *_cpython
     - 3.13.* *_cp313
   is_python_min:
     - true
     - false
     - false
   zip_keys:
     - - python
       - is_python_min
   channel_targets:
     - conda-forge main

4. Validation locale
--------------------

Toujours valider localement avant de pousser.

.. code-block:: text

   conda mambabuild recipes/hydromodpy -c conda-forge
   conda create -n test-env --use-local hydromodpy

5. Soumission
-------------

1. Forker ``conda-forge/staged-recipes``.
2. Pousser ``recipes/hydromodpy`` sur une nouvelle branche.
3. Ouvrir une Pull Request contre ``main``.
4. Justifier les binaires dans un commentaire : les exécutables MODFLOW
   sont vendus pour garantir un fonctionnement out-of-the-box, ce qui
   impose ``binary_relocation: false`` et ``missing_dso_whitelist``.
5. Déclencher la review python :
   ``@conda-forge-admin, please ping conda-forge/help-python``.

6. Maintenance (feedstock)
--------------------------

- Une fois mergé, ``hydromodpy-feedstock`` est créé automatiquement.
- Le bot conda-forge détecte les releases PyPI et ouvre des PR sur le
  feedstock.
- Workflow : vérifier version et hash dans la PR du bot, puis merger.
