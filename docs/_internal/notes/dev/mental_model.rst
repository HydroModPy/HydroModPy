Vue d'ensemble et choix de conception
=====================================

Ce document complete :doc:`glossary <glossary>`. Le glossaire donne des
definitions courtes. Ici, l'objectif est different :

- donner une vision d'ensemble du systeme,
- expliquer pourquoi certains decoupages existent,
- montrer quelles frontieres de responsabilite il faut garder en tete,
- orienter vers les bons documents quand on veut aller plus loin.

Ce n'est pas un document de reference exhaustive. C'est une carte
commentee du systeme.

Liens utiles :
:doc:`glossary <glossary>`,
:doc:`CLI <cli>`,
:doc:`databases_and_workflows <storage>`,
:doc:`simulation_catalog_architecture <storage>`,
:doc:`calibration_guide <calibration_guide>`,
../readthedocs/source/architecture/overview/code-reading-guide.rst,
../readthedocs/source/architecture/simulation/toml-to-solver-walkthrough.rst.

Vision en un coup d'oeil
------------------------

Le chemin principal, cote execution, est :

.. code-block:: text

   TOML
   -> workflow
   -> Project
   -> SimulationPlanner
   -> SimulationPlan (ProcessRun...)
   -> Pipeline / SimulationRunner
   -> SolverAdapter
   -> solveur concret
   -> SimulationCatalog
   -> Run

Le chemin principal, cote donnees d'entree, est :

.. code-block:: text

   TOML
   -> DataLoadPlan
   -> Variable
   -> Manager
   -> Source
   -> DataCatalogDuckDB
   -> objets runtime

Le premier chemin repond a la question :
"comment une configuration devient-elle un resultat ?"

Le second repond a la question :
"d'ou viennent les donnees utilisees par cette execution ?"

Pourquoi autant d'objets
------------------------

La reponse courte est simple : HydroModPy essaye de separer des problemes
qui evoluent a des vitesses differentes.

Exemples :

- la forme du TOML change a un certain rythme,
- la logique d'orchestration change a un autre rythme,
- les solveurs concrets changent encore autrement,
- les donnees d'entree et leurs fournisseurs changent aussi,
- la lecture aval des resultats suit encore un autre cycle.

Si tout est melange dans quelques grosses classes, chaque evolution
fragilise le reste. Le decoupage actuel cherche surtout a limiter cette
propagation.

Pourquoi ``Project`` existe
---------------------------

``Project`` joue le role de facade.

Ce choix permet trois choses :

1. Donner un point d'entree simple a l'utilisateur Python.
2. Garder un langage commun entre CLI, notebooks et scripts.
3. Cacher une execution interne plus complexe sans imposer au lecteur de
   comprendre tout le systeme d'un coup.

Sans cette facade, l'utilisateur devrait manipuler directement des objets
de planification, de pipeline, de stockage et de solveur. Ce serait trop
bas niveau pour l'usage courant.

En pratique :

- ``Project`` n'est pas le solveur,
- ``Project`` n'est pas le pipeline,
- ``Project`` ne remplace pas les objets internes,
- ``Project`` les compose.

Pourquoi distinguer ``workflow``, ``SimulationPlan`` et ``Pipeline``
--------------------------------------------------------------------

Ces trois mots sont proches, mais ils ne repondent pas a la meme question.

``workflow``
~~~~~~~~~~~~

Question :
"quel grand mode d'execution l'utilisateur demande-t-il ?"

Exemples :
``simulation``, ``overview``, ``mesh``, ``calibration``, ``batch``.

``SimulationPlan``
~~~~~~~~~~~~~~~~~~

Question :
"quelles unites doivent tourner, dans quel ordre logique ?"

Le plan reste declaratif et immuable. Il exprime le "quoi".

``Pipeline``
~~~~~~~~~~~~

Question :
"comment l'execution technique avance-t-elle et comment propage-t-on l'etat ?"

Le pipeline exprime le "comment".

Pourquoi cette separation est utile
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Si on melange ces trois niveaux :

- on confond intention utilisateur et mecanique interne,
- on rend la reprise, le checkpointing et le debug plus difficiles,
- on accroche trop fortement le CLI a l'implementation courante,
- on rend les tests plus fragiles.

Regle pratique :

- ``workflow`` = intention utilisateur
- ``SimulationPlan`` = plan logique
- ``Pipeline`` = enchainement technique

Pourquoi distinguer ``ProcessRun`` et ``Run``
---------------------------------------------

Cette distinction est indispensable.

``ProcessRun``
~~~~~~~~~~~~~~

C'est une unite planifiee avant execution. Elle represente quelque chose
qui doit etre fait.

Exemple :
``flow_main::modflow6``

``Run``
~~~~~~~

C'est une vue en lecture sur un resultat deja persiste.

Exemple :
un handle qui expose ``timeseries()``, ``field()``, ``budget()``, ``plot()``.

Pourquoi cette separation existe
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Le systeme a besoin d'une notion "avant execution" et d'une notion
"apres persistence".

Si on utilise le meme mot pour les deux :

- les discussions de debug deviennent confuses,
- les identifiants deviennent ambigus,
- les frontieres entre orchestration et analyse aval disparaissent.

Pourquoi ``SimulationRunner`` et ``SolverAdapter``
--------------------------------------------------

Le solveur concret ne doit pas etre appele directement par les couches
hautes a chaque fois.

``SimulationRunner`` parcourt les ``ProcessRun`` dans l'ordre resolu. Le
``SolverAdapter`` enregistre sert d'adaptateur entre :

- un ``ProcessRun`` generique,
- un contexte runtime commun,
- et une implementation concrete comme MODFLOW-NWT, MODFLOW 6 ou
  Boussinesq.

Ce choix permet :

- de garder un langage commun cote orchestration,
- d'isoler les particularites de chaque backend,
- de limiter l'impact des changements d'API d'un solveur,
- de tester les couches hautes sans importer toute la mecanique interne
  d'un backend.

Pourquoi deux catalogues
------------------------

HydroModPy a besoin de deux memoires persistantes qui ne jouent pas le
meme role.

``DataCatalogDuckDB``
~~~~~~~~~~~~~~~~~~~~~

Memoire des donnees d'entree :

- ce qui a ete telecharge,
- ce qui a ete lu depuis du custom,
- ce qui peut etre reutilise sans recharger la source.

``SimulationCatalog``
~~~~~~~~~~~~~~~~~~~~~

Memoire des sorties de simulation :

- metadonnees de runs,
- parametres,
- metriques,
- provenance,
- pointeurs vers les artefacts persistants.

Pourquoi ne pas tout fusionner
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parce que la logique de vie n'est pas la meme.

Les donnees d'entree sont souvent partagees entre plusieurs runs. Les
sorties de simulation appartiennent a des executions particulières.

Si on fusionne les deux niveaux :

- les responsabilites se brouillent,
- la provenance devient plus dure a raisonner,
- la reutilisation du cache d'entree perd en clarte.

Le vrai lien entre les deux n'est pas l'identite, mais la provenance.

Pourquoi ``Variable``, ``Manager``, ``Source``
----------------------------------------------

Ce triplet repond a trois questions differentes.

Variable
~~~~~~~~

"Quel type de donnee veut-on ?"

Exemples :
DEM, hydrographie, piezometrie, hydrometrie, geologie.

Manager
~~~~~~~

"Quelle logique applique-t-on pour charger cette variable ?"

Le manager orchestre :

- la lecture de config,
- la resolution spatiale ou temporelle,
- les appels aux fournisseurs,
- le cache,
- la normalisation du resultat.

Source
~~~~~~

"D'ou vient la donnee concrete ?"

Exemples :
API, fichier custom, source interne specialisee.

Pourquoi ce decoupage est utile
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Il permet de changer un fournisseur sans reposer toute la logique metier,
ou de faire evoluer la logique de chargement sans renommer les concepts
scientifiques.

Autrement dit :

- la ``Variable`` porte le sens,
- la ``Source`` porte l'origine,
- le ``Manager`` porte la politique de chargement.

Pourquoi les identifiants sont multiples
----------------------------------------

C'est un point de friction classique, mais la multiplicite des identifiants
repond a des besoins differents.

``sim_id``
~~~~~~~~~~

Identifie un resultat persiste dans le ``SimulationCatalog``.

Question couverte :
"quel objet persiste suis-je en train de relire ?"

``simulation.run_id``
~~~~~~~~~~~~~~~~~~~~~

Identifiant logique lie a la configuration et aux sorties de travail.

Question couverte :
"comment ce run etait-il nomme du point de vue de la config ?"

``ProcessRun.id``
~~~~~~~~~~~~~~~~~

Identifiant d'une unite planifiee interne.

Question couverte :
"quelle brique de planification ou de dependance suis-je en train de suivre ?"

Pourquoi ne pas tout reduire a un seul identifiant
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parce que l'unicite totale simplifierait un cas, mais compliquerait les
autres :

- persistence,
- reprise,
- orchestration multi-process,
- lecture humaine,
- traces de debug.

La bonne pratique est donc de toujours qualifier l'identifiant dans la
discussion.

Ce que cette architecture essaye d'optimiser
--------------------------------------------

Les choix actuels optimisent surtout :

- la separabilite des responsabilites,
- la relisibilite en debug,
- la possibilite de changer un backend sans tout casser,
- la reutilisation de donnees d'entree,
- la comparaison aval entre runs,
- l'ajout progressif de nouveaux workflows.

Ils n'optimisent pas toujours :

- la simplicite immediate pour un nouveau lecteur,
- l'uniformite parfaite de tous les sous-systemes,
- la reduction maximale du nombre de concepts.

C'est un compromis. Il faut l'assumer explicitement dans la documentation.

Diagrammes qui vaudraient vraiment le coup
------------------------------------------

Tous les diagrammes UML ne se valent pas. Pour cette zone du systeme, les
plus utiles seraient :

1. Diagramme de contexte / composants "TOML -> Run"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Type :
component diagram

But :
donner en un coup d'oeil les grandes boites :

- TOML
- CLI / API
- Project
- planners
- pipeline
- solver runners
- catalogues
- Run

Valeur :
ideal pour orienter un nouveau lecteur avant tout detail.

2. Diagramme de sequence "une execution simple"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Type :
sequence diagram

But :
montrer une execution nominale :

``hmp run`` -> ``Project`` -> ``SimulationPlanner`` -> ``Pipeline`` ->
``SimulationRunner`` -> ``SolverAdapter`` -> solveur -> ``SimulationCatalog`` -> ``Run``

Valeur :
ideal pour relier les objets du glossaire a une histoire concrete.

3. Diagramme statique des objets de facade
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Type :
class diagram leger ou component diagram statique

But :
montrer les relations entre :

- ``Workspace``
- ``Project``
- ``SimulationCatalog``
- ``Run``
- ``SimulationGroup``
- ``DataCatalogDuckDB``

Valeur :
ideal pour comprendre qui heberge quoi et qui lit quoi.

4. Diagramme "Variable / Manager / Source / cache"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Type :
component diagram ou sequence diagram court

But :
montrer le trajet d'une donnee d'entree depuis la config jusqu'au cache et
au runtime.

Valeur :
ideal pour les discussions sur les API de donnees et le pre-processing.

5. Diagramme des identifiants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Type :
schema graphique simple, pas forcement UML strict

But :
montrer visuellement la difference entre :

- ``sim_id``
- ``simulation.run_id``
- ``ProcessRun.id``

Valeur :
tres forte, parce que c'est un point de confusion recurrent et qu'un schema
simple clarifie mieux qu'un long paragraphe.

Ou mettre ces diagrammes
------------------------

Bon point d'atterrissage :

- pages publiees RTD sous
  ``docs/source/architecture/overview/``
- sources PlantUML sous un sous-dossier ``diagrams/``
- ce document reste la partie narrative et justifie les choix

Schema recommande :

- le diagramme publie dans RTD
- la source ``.wsd`` versionnee
- un court texte sous le diagramme : "ce que ce schema explique" et
  "ce qu'il n'explique pas"

Itineraires de lecture
----------------------

Si la question est :
"comment un TOML devient-il un resultat ?"

Lire :

1. :doc:`glossary <glossary>`
2. :doc:`CLI <cli>`
3. ../readthedocs/source/architecture/simulation/toml-to-solver-walkthrough.rst
4. :doc:`simulation_catalog_architecture <storage>`

Si la question est :
"ou vivent les donnees et pourquoi deux bases ?"

Lire :

1. :doc:`glossary <glossary>`
2. :doc:`databases_and_workflows <storage>`
3. :doc:`simulation_catalog_architecture <storage>`

Si la question est :
"pourquoi autant de couches entre plan, pipeline et solveur ?"

Lire :

1. :doc:`glossary <glossary>`
2. ../readthedocs/source/architecture/overview/code-reading-guide.rst
3. ../readthedocs/source/architecture/simulation/toml-to-solver-walkthrough.rst
4. ``hydromodpy/simulation/README.md``

Limites et zones de transition
------------------------------

Le systeme reel n'est pas parfaitement homogene. Il faut le dire.

Exemples :

- certains documents anciens parlent encore de ``SolverAdapter``,
- le mot ``PipelineStep`` survit dans quelques textes alors que le code
  courant parle surtout de ``Step``,
- le pattern ``BaseVariableManager`` couvre une grande partie des variables,
  mais pas toutes avec le meme degre d'uniformite,
- plusieurs couches historiques et plus recentes coexistent parfois.

Ce n'est pas une raison pour gommer ces tensions dans la doc. Au contraire,
les bonnes pages d'architecture doivent les nommer clairement.

Resume
------

Le decoupage central de HydroModPy repose sur une idee simple :

- facade simple pour l'utilisateur,
- planification explicite,
- execution technique separee,
- adaptation isolee des solveurs,
- stockage clair des entrees et des sorties,
- lecture aval stabilisee via ``Run``.

Le glossaire doit nommer les objets.

Ce document doit expliquer pourquoi ils existent.
