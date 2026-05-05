Glossaire
=========

Vocabulaire canonique HydroModPy. Ce document fait foi en cas de conflit
de nommage. Le but n'est pas de tout expliquer : il donne des definitions
courtes, les relations entre objets, et des points d'entree pour aller plus
loin.

Liens utiles :
:doc:`mental_model_and_design_choices <mental_model>`,
:doc:`design_patterns <design_patterns>`,
:doc:`CLI <cli>`,
:doc:`simulation_catalog_architecture <storage>`,
:doc:`databases_and_workflows <storage>`,
:doc:`calibration_guide <calibration_guide>`,
../readthedocs/source/architecture/overview/code-reading-guide.rst,
../../tests/README.md.

Carte rapide
------------

Lecture mentale recommandee :

.. code-block:: text

   TOML
   -> workflow
   -> Project
   -> SimulationPlan (ProcessRun...)
   -> Pipeline (Step, PipelineState)
   -> SimulationRunner
   -> SolverAdapter
   -> SimulationCatalog
   -> Run

En parallele, les donnees d'entree suivent plutot ce chemin :

.. code-block:: text

   TOML
   -> DataLoadPlan
   -> Variable
   -> Manager
   -> Source
   -> DataCatalogDuckDB

Du TOML au Run
--------------

Quand on lit ou debogue HydroModPy, le parcours le plus utile est :

1. Le TOML declare un ``workflow = "..."`` et une configuration.
2. Le CLI ou l'API charge cette configuration et choisit le bon mode
   d'execution.
3. ``Project`` sert de facade programmatique : il prepare, execute, ingere
   et persiste.
4. ``SimulationPlanner`` transforme le declaratif en ``SimulationPlan``
   compose de ``ProcessRun``.
5. Le ``Pipeline`` fait avancer l'execution technique et transporte un
   ``PipelineState`` entre ses ``Step``.
6. ``SimulationRunner`` parcourt les ``ProcessRun`` et choisit le ``SolverAdapter``
   qui appelle le solveur concret.
7. Les sorties sont persistees dans le ``SimulationCatalog``.
8. L'utilisateur relit ensuite les resultats via un ``Run``.

Si la question est "comment un TOML devient un resultat ?", suivre cet
ordre de lecture :

- ``hydromodpy/cli/commands/run.py``
- ``hydromodpy/workflow/dispatch.py``
- ``hydromodpy/project.py``
- ``hydromodpy/simulation/planning/``
- ``hydromodpy/workflow/``
- ``hydromodpy/solver/base/``
- ``hydromodpy/results/``

Objets de facade
----------------

Workspace
~~~~~~~~~

Repertoire racine de travail. Il heberge le stockage des resultats, le
cache de donnees d'entree et, selon le layout scaffold, des dossiers comme
``data/``, ``simulations/``, ``projects/``.

Module : ``hydromodpy.core.workspace.workspace.Workspace``.

Relation :

- un ``Workspace`` heberge un ``SimulationCatalog``
- plusieurs ``Project`` peuvent y ecrire

Project
~~~~~~~

Facade programmatique utilisateur. Construit depuis un TOML ou une config,
prepare l'execution, lance un run et retourne un ``Run``.

Module : ``hydromodpy.project.Project``, expose comme ``hmp.Project``.

Relation :

- lit la config utilisateur
- travaille dans un ``Workspace``
- ecrit dans le ``SimulationCatalog``
- retourne un ``Run``

Attention :

- ``Project`` designe l'objet Python
- ce n'est ni le ``workflow``, ni le ``Pipeline``
- le mot "projet" comme dossier ou label de workspace reste contextuel

Run
~~~

Vue en lecture sur un resultat persiste. Un ``Run`` n'est pas le solveur en
train de tourner : c'est le handle qui permet de lire metadonnees, champs,
series temporelles, budgets, metriques et figures.

Module : ``hydromodpy.results.run.Run``, expose comme ``hmp.Run``.

Relation :

- est retourne par ``project.run(...)``
- peut etre recupere via ``catalog[sim_id]``, ``catalog.best(...)`` ou
  ``SimulationGroup``
- recharge ses donnees via le ``SimulationCatalog``

SimulationCatalog
~~~~~~~~~~~~~~~~~

Catalogue de sortie du workspace. C'est le registre central des simulations
persistees.

Module : ``hydromodpy.results.catalog.SimulationCatalog``, expose aussi comme
``hmp.Catalog`` dans l'API publique.

Relation :

- indexe les ``Run``
- pointe vers les artefacts stockes sur disque
- sert de point d'entree pour comparer, lister, relire et exporter

DataCatalogDuckDB
~~~~~~~~~~~~~~~~~

Cache d'entree des donnees chargees depuis des sources externes ou des
fichiers custom.

Module : ``hydromodpy.data.registry.catalog_duckdb.DataCatalogDuckDB``.

Relation :

- est utilise par les ``Manager``
- n'est pas le catalogue de resultats

Ne pas confondre :

- ``SimulationCatalog`` = sorties de simulation
- ``DataCatalogDuckDB`` = cache d'entree

SolverAdapter
~~~~~~~~~~~~~

Interface Protocol qui lie une paire ``(process_type, solver_name)`` à un
solveur concret. Module : ``hydromodpy.solver.base.protocol``. Contrat
structurel : trois ClassVars (``process_type``, ``solver_name``, ``requires``)
plus trois methods (``validate``, ``execute``, ``cleanup``) qu'un adaptateur
doit exposer pour passer ``isinstance(obj, SolverAdapter)``.

SimulationGroup
~~~~~~~~~~~~~~~

Vue de groupe sur plusieurs ``Run``, utile pour comparer plusieurs
simulations ensemble.

Module : ``hydromodpy.results.simulation_group.SimulationGroup``.

Relation :

- contient plusieurs ``Run``
- est retourne par certaines operations de sweep ou de comparaison

Aller plus loin :
:doc:`simulation_catalog_architecture <storage>`,
:doc:`databases_and_workflows <storage>`.

Planification et execution
--------------------------

workflow
~~~~~~~~

Mode d'execution declare dans le TOML ou resolu par le CLI :
``simulation``, ``calibration``, ``batch``, ``overview``, ``mesh``, ``comparison``,
``comparison``.

Reference :

- voir :doc:`CLI <cli>`
- implementation dans ``hydromodpy/workflow/dispatch.py``

Important :

- ``workflow`` designe le mode utilisateur
- ce n'est pas synonyme de ``Pipeline``

SimulationPlan
~~~~~~~~~~~~~~

Plan immuable d'execution produit a partir de la configuration
declarative.

Module : ``hydromodpy.simulation.planning.plan.SimulationPlan``.

Relation :

- est construit par ``SimulationPlanner``
- contient une liste ordonnee de ``ProcessRun``

ProcessRun
~~~~~~~~~~

Unite planifiee concrète dans un ``SimulationPlan``, generalement une paire
``(process_id, solver)``.

Module : ``hydromodpy.simulation.planning.plan.ProcessRun``.

Relation :

- appartient a un ``SimulationPlan``
- sera execute par ``SimulationRunner``

Attention :

- ``ProcessRun`` n'est pas un ``Run``
- ``ProcessRun`` = unite planifiee
- ``Run`` = resultat persiste relisible

Pipeline
~~~~~~~~

Sequence ordonnee d'etapes techniques qui fait avancer l'execution.

Module : ``hydromodpy.workflow.runner.Pipeline``.

Relation :

- orchestre des ``Step``
- transporte un ``PipelineState``

Step
~~~~

Contrat canonique d'une etape du pipeline. Un ``Step`` prend un
``PipelineState`` en entree et renvoie un nouvel etat en sortie.

Module : ``hydromodpy.workflow.internals.step.Step``.

Note :

- d'anciens textes parlent de ``PipelineStep``
- dans le code actuel, le nom de reference est ``Step``

PipelineState
~~~~~~~~~~~~~

Etat immutable qui circule entre les ``Step``. Il porte un ``run_id``,
un index d'etape, un nom d'etape, un temps ecoule, et un payload ``data``.

Module : ``hydromodpy.workflow.internals.state.PipelineState``.

Relation :

- est consomme par un ``Step``
- est remplace par un nouvel etat a chaque etape

SimulationRunner
~~~~~~~~~~~~~~~~

Orchestrateur runtime qui parcourt les ``ProcessRun`` et delegue chaque run
au ``SolverAdapter`` enregistre.

Module : ``hydromodpy.simulation.execution.runner.SimulationRunner``.

Relation :

- execute le ``SimulationPlan`` dans l'ordre resolu
- recupere le bon ``SolverAdapter`` depuis le registre
- stocke les modeles produits dans l'etat runtime

Backend
~~~~~~~

Moteur concret choisi au runtime. Toujours le qualifier.

Exemples :

- backend de solveur : MODFLOW-NWT, MODFLOW 6, Boussinesq, ou des couches
  plus basses comme ``flopy``, ``scipy``, ``petsc``
- backend de delineation : Whitebox CLI ou Whitebox Workflows
- backend d'affichage : matplotlib, pyvista

CheckpointStore
~~~~~~~~~~~~~~~

Stockage des checkpoints du pipeline pour reprendre apres interruption.

Module : ``hydromodpy.workflow.internals.checkpoint.CheckpointStore``.

StepsLedger
~~~~~~~~~~~

Journal DuckDB des executions d'etapes.

Module : ``hydromodpy.workflow.internals.ledger.StepsLedger``.

DerivedRegistry
~~~~~~~~~~~~~~~

Registre ordonne des calculs derives appliques apres extraction.

Module : ``hydromodpy.workflow.internals.derived.DerivedRegistry``.

Aller plus loin :
:doc:`CLI <cli>`,
../../hydromodpy/simulation/README.md,
../readthedocs/source/architecture/overview/code-reading-guide.rst.

Donnees d'entree
----------------

Variable
~~~~~~~~

Type de donnee metier chargee en entree : ``dem``, ``geology``, ``hydrometry``,
``piezometry``, ``hydrography``, ``recharge``, etc.

En pratique, chaque variable a au minimum :

- une config de variable
- un manager
- zero, une ou plusieurs sources

Manager
~~~~~~~

Orchestrateur de chargement d'une variable. Il lit la config, interroge les
sources utiles, applique la logique de cache et produit un resultat
normalise.

Le depot suit majoritairement un pattern ``BaseVariableManager`` /
``BaseFieldManager``, mais toutes les variables ne sont pas encore
strictement homogenes.

Source
~~~~~~

Fournisseur concret de donnees pour une variable. Une source peut etre une
API, un fichier custom, ou un connecteur specialise.

Module de reference :
``hydromodpy.data.sources``.

Relation :

- une ``Variable`` est chargee par un ``Manager``
- un ``Manager`` peut appeler plusieurs ``Source``
- une ``Source`` peut etre enregistree via ``register_source``

DataLoadPlan
~~~~~~~~~~~~

Plan immuable de chargement des donnees d'entree.

Module : ``hydromodpy.data.plan.DataLoadPlan``.

Relation :

- est l'equivalent "donnees" du ``SimulationPlan``
- guide les managers a invoquer avant execution

Aller plus loin :
:doc:`databases_and_workflows <storage>`,
../../hydromodpy/data/README.md.

Identifiants a ne pas confondre
-------------------------------

sim_id
~~~~~~

Identifiant technique du resultat persiste dans le ``SimulationCatalog``.
C'est l'identifiant que porte un ``Run``.

Usage typique :

- ``catalog[sim_id]``
- ``run.sim_id``

simulation.run_id
~~~~~~~~~~~~~~~~~

Identifiant logique de run porte par la configuration de simulation.
Il sert surtout a nommer des executions ou des sorties de travail.

Usage typique :

- derive du nom du TOML si absent
- visible dans la config et dans certaines sorties scratch

ProcessRun.id
~~~~~~~~~~~~~

Identifiant d'une unite planifiee dans un ``SimulationPlan``, en pratique
souvent de la forme ``<process_id>::<solver>``.

Resume :

- ``sim_id`` = resultat persiste
- ``simulation.run_id`` = identifiant logique de la config
- ``ProcessRun.id`` = unite planifiee interne

Visibilite de configuration
---------------------------

Profile
~~~~~~~

Nom canonique : ``Profile`` (IntEnum). Module :
``hydromodpy.core.config_kit.profile.Profile``. Trois niveaux :

Niveaux :

- ``Profile.USER`` : surface utilisateur
- ``Profile.DEV`` : reglages de debug, backends, cache, tolerances
- ``Profile.EXPERT`` : details internes ou avances

Relation :

- pilote la generation de TOML
- pilote aussi certains schemas et formulaires

Aller plus loin :
:doc:`frontend_hooks <frontend_hooks>`,
:doc:`schema_evolution <schema_evolution>`.

Hygiene de nommage
------------------

- Ne pas introduire de nouvel alias pour un concept deja liste ici.
- Tout nouveau terme important doit etre ajoute ici avant de se diffuser.
- Ne pas utiliser ``workflow`` comme synonyme de ``Pipeline``.
- Ne pas utiliser ``Run`` comme synonyme de ``ProcessRun``.
- Ne pas utiliser ``catalog`` seul quand l'ambiguite entre entrees et
  sorties est possible.
- Si un terme est en transition, noter explicitement l'ancien nom et le
  nom courant.
