CLI
===

Après ``pip install -e .``, deux commandes équivalentes sont disponibles :
``hmp`` et ``hydromodpy``. Le dispatch principal est dans
``hydromodpy/cli/main.py``, les sous-commandes dans
``hydromodpy/cli/commands/``.

Liens : :doc:`glossary <glossary>`,
:doc:`frontend_hooks <frontend_hooks>`,
:doc:`calibration_guide <calibration_guide>`.

Exécution d'un workflow
-----------------------

Point d'entrée unique :

.. code-block:: bash

   hmp run chemin/vers/project.toml

Le TOML doit déclarer un champ ``workflow = "..."`` au premier niveau.
Valeurs reconnues (voir ``hydromodpy/cli/workflows.py``, constante
``KNOWN_WORKFLOWS``) :

.. list-table::
   :header-rows: 1

   * - Valeur
     - Rôle
   * - ``"simulation"``
     - Exécute une simulation : setup, data, mesh, solveur, extraction, export
   * - ``"calibration"``
     - Boucle d'optimisation, exécute N simulations, choisit la meilleure
   * - ``"batch"``
     - Campagne régionale multi-sites, expansion sites × recettes
   * - ``"overview"``
     - Fiche d'identité du bassin (data et géographie, sans solveur)
   * - ``"mesh"``
     - Génération du maillage de bassin uniquement

Exemple minimal de TOML :

.. code-block:: toml

   workflow = "simulation"

   [workspace]
   root = "/chemin/vers/workspace"
   project_root = "."

   [geographic]
   # ...

Si ``workflow`` est absent ou prend une valeur inconnue, la commande
échoue au chargement avec un message explicite. La même contrainte est
appliquée côté Pydantic (``HydroModPyConfig``) afin que les frontaux
(Angular, React) voient le champ comme un enum requis.

Les scripts Python de prototypage ne passent pas par ``hmp run``.
Ils vivent dans l'espace développeur pour garder ``hmp run`` strictement
reproductible depuis une configuration validée :

.. code-block:: bash

   hmp dev run-script prototype_script.py

Génération d'un fichier de configuration
----------------------------------------

.. code-block:: bash

   hmp config template mon_config.toml
   hmp config template mon_config.toml --profile user
   hmp config template --list-modules
   hmp config template --modules flow transport

``--profile`` contrôle la verbosité du TOML produit :

- ``user`` : défauts sûrs, champs minimaux.
- ``dev`` : intermédiaire.
- ``expert`` : tous les champs (défaut).

Voir ``Profile`` dans :doc:`glossary <glossary>`.

Tests
-----

Unitaires
~~~~~~~~~

.. code-block:: bash

   hmp test unit

Régression
~~~~~~~~~~

Tous les tests :

.. code-block:: bash

   hmp test regression

Filtres par vitesse ou famille de solveur :

.. code-block:: bash

   hmp test regression --fast
   hmp test regression --extensive
   hmp test regression --slow
   hmp test regression --nwt
   hmp test regression --mf6

Un test spécifique :

.. code-block:: bash

   hmp test regression launcher_simulation_fast_nwt --fast --nwt
   hmp test regression launcher_simulation_fast_mf6 --fast --mf6
   hmp test regression launcher_simulation_extensive_nwt --extensive --nwt
   hmp test regression launcher_simulation_extensive_mf6 --extensive --mf6

Liste les tests disponibles :

.. code-block:: bash

   hmp test regression --list

Parallélisation (requiert ``pytest-xdist``) :

.. code-block:: bash

   hmp test regression -j auto
   hmp test regression --fast -j 4
   hmp test unit -j auto
   hmp test regression launcher_simulation_extensive_nwt -j 1

Mise à jour des goldens :

.. code-block:: bash

   hmp test regression --update-goldens
   hmp test regression launcher_simulation_fast_mf6 --update-goldens

Validation
~~~~~~~~~~

.. code-block:: bash

   hmp test validation
   hmp test validation --fast
   hmp test validation --steady
   hmp test validation --transient
   hmp test validation --analytical
   hmp test validation --mf6
   hmp test validation --nwt

La cible ``validation`` ajoute automatiquement le marqueur pytest
``validation``, puis les filtres supplémentaires.

Autres commandes
----------------

.. list-table::
   :header-rows: 1

   * - Commande
     - Rôle
   * - ``hmp init [chemin]``
     - Scaffold d'un workspace
   * - ``hmp new <projet>``
     - Créer un nouveau projet dans le workspace
   * - ``hmp doctor``
     - Diagnostic environnement et workspace
   * - ``hmp list``
     - Liste les projets et runs
   * - ``hmp show <sim_id>``
     - Affiche les métadonnées d'un run
   * - ``hmp inspect <sim_id>``
     - Inspection détaillée d'un run
   * - ``hmp rank <project> --metric <name> --top N`` / ``hmp rank <project> --metric <name> --bottom N``
     - Top ou bottom N runs selon métrique
   * - ``hmp compare <sim_a> <sim_b>``
     - Comparaison de deux runs
   * - ``hmp display <config.toml>`` / ``hmp display <sim_id> <figure>``
     - Production des figures
   * - ``hmp export <project> --sim <name> --csv --output <dir>`` / ``hmp export <project> --sim <name> --geotiff --resolution <dx>``
     - Export vers un format externe
   * - ``hmp import <package.hmp>``
     - Import d'un ``.hmp`` dans le workspace
   * - ``hmp delete <sim_id>``
     - Suppression d'un run
   * - ``hmp install-binaries [--subset mf6,mfnwt]``
     - Précharge les binaires solveur dans le cache local
   * - ``hmp schema export``
     - Export JSON Schema (voir :doc:`frontend_hooks <frontend_hooks>`)
   * - ``hmp schema validate-field``
     - Validation partielle d'un champ
   * - ``hmp lock``
     - Verrou workspace
   * - ``hmp data``
     - Gestion du cache d'entrée
   * - ``hmp completion``
     - Génération d'un script de complétion shell

Notes :

- ``--fast`` et ``--extensive`` sélectionnent les tiers de régression,
  ``--slow`` est un filtre par marqueur pytest.
- ``--nwt`` et ``--mf6`` filtrent par famille de solveur.
- ``-j`` est mappé sur ``pytest-xdist -n``. Sans flag, exécution séquentielle.
- ``--normal`` est un alias déprécié de ``--fast``.
- La commande imprime sur stderr l'invocation ``pytest`` réelle avant de
  la lancer.
