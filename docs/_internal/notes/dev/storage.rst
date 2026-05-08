Storage architecture
====================

How HydroModPy persists, indexes and reads back its outputs and input cache.
This page merges the four pre-refactor notes about the simulation catalog,
the Parquet lakehouse layout, the concurrency model, and the cache of input data.

Bases de données et workflows
-----------------------------

Document de référence pour comprendre comment HydroModPy persiste,
indexe et relit ses données. Il couvre les deux bases distinctes
(catalogue de sortie et cache d'entrée), leur articulation avec les
workflows et les garanties de cohérence.

Liens :
simulation_catalog_architecture,
parquet_lakehouse_architecture,
parquet_lakehouse_concurrency,
:doc:`schema_evolution <schema_evolution>`,
:doc:`calibration_guide <calibration_guide>`,
:doc:`CLI <cli>`,
:doc:`glossary <glossary>`.

1. Vue d'ensemble
~~~~~~~~~~~~~~~~~

Un workspace HydroModPy contient deux bases indépendantes, chacune
adossée à un fichier DuckDB distinct :

.. list-table::
   :header-rows: 1

   * - Rôle
     - Fichier
     - Code
     - Ce qu'elle contient
   * - Catalogue de sortie
     - ``hydromodpy.duckdb``
     - ``hydromodpy/results/catalog.py``
     - Métadonnées des simulations, paramètres, métriques, provenance, calibration, géographie
   * - Cache d'entrée
     - ``data/cache.duckdb``
     - ``hydromodpy/data/registry/catalog_duckdb.py``
     - Index des données d'entrée (hydrométrie, piézométrie, géologie, climat), artefacts et provenance des fetchs

Les données lourdes ne tiennent pas dans DuckDB. Trois formats
complémentaires sont utilisés :

- **Zarr** (``simulations/<basename>.zarr/``, puis éventuellement
  ``.zarr.zip``) pour les champs spatiaux 3D produits par le solveur
  (charges, budgets, dérivés).
- **Parquet** (``simulations/<basename>.parquet/``) pour les séries temporelles
  append-only, les budgets et bilans de masse, exposés en vues SQL.
- **Fichiers d'entrée** (``data/<variable>/``) bruts (CSV, NetCDF, TIFF)
  référencés par le cache DuckDB.

Disposition physique :

.. code-block:: text

   workspace/
   ├── hydromodpy.duckdb                 # catalogue de sortie
   ├── data/
   │   ├── cache.duckdb                  # cache d'entrée
   │   └── <variable>/                   # fichiers bruts
   │       ├── dem/
   │       ├── geology/
   │       ├── hydrometry/
   │       └── ...
   ├── simulations/
   │   ├── <basename>.zarr/              # champs spatiaux
   │   ├── <basename>.zarr.zip           # Zarr packé après finalize
   │   └── <basename>.parquet/
   │       ├── timeseries.parquet
   │       ├── budgets.parquet
   │       └── mass_balance.parquet
   ├── projects/
   │   └── <nom>/project.toml
   └── configs/                          # TOML utilisateur

2. Catalogue de sortie
~~~~~~~~~~~~~~~~~~~~~~

Code principal :

- ``hydromodpy/results/catalog.py`` : classe ``SimulationCatalog``.
- ``hydromodpy/results/catalog_schema.py`` : DDL (tables, vues, index).
- ``hydromodpy/results/zarr_store.py`` : classe ``SimulationZarr``.
- ``hydromodpy/results/run.py`` : classe ``Run``.
- ``hydromodpy/results/simulation_group.py`` : classe ``SimulationGroup``.
- ``hydromodpy/results/views.py`` : vues catchment-scale calculées à la
  volée.
- ``hydromodpy/core/io/db_retry.py`` : helpers de retry DuckDB.
- ``hydromodpy/results/catalog/storage_paths.py`` : normalisation et
  résolution des noms de fichiers.

2.1. Tables DuckDB
^^^^^^^^^^^^^^^^^^

Toutes les tables sont créées par ``ensure_schema`` sur l'ouverture du
catalogue.

.. list-table::
   :header-rows: 1

   * - Table
     - Rôle
     - Clé primaire
   * - ``simulations``
     - Ligne par run : projet, solveur, maillage, bbox, période, config, timing
     - ``sim_id`` (UUID)
   * - ``parameters``
     - Paramètres homogènes ou par zone
     - ``(sim_id, param_name, zone_id)``
   * - ``metrics``
     - Métriques par station et variable
     - ``(sim_id, station_id, variable, metric_name)``
   * - ``observation_points``
     - Stations projetées sur la grille
     - ``(sim_id, station_id)``
   * - ``provenance``
     - Fingerprints SHA-256 des entrées utilisées
     - composite (sim_id, variable, source_ref)
   * - ``calibration_sessions``
     - Session d'optimisation
     - ``session_id`` (UUID)
   * - ``calibration_iterations``
     - Trace complète des trials
     - ``(session_id, iteration)``
   * - ``geographic_features``
     - Vecteurs vectoriels par simulation
     - ``(sim_id, feature_name)``
   * - ``geographic_metadata``
     - Clé/valeur géographique
     - ``(sim_id, key)``
   * - ``runs_environment``
     - Snapshot env Python et OS au run
     - ``sim_id``
   * - ``tags``
     - Étiquettes libres
     - ``(sim_id, tag)``
   * - ``stations``, ``observations``
     - Référentiel et relevés bruts
     - composites
   * - ``tracked_files``
     - Fichiers d'entrée tracés par simulation
     - ``(sim_id, role, canonical_path)``

Contraintes notables sur ``simulations`` :

- ``status IN ('pending', 'running', 'completed', 'failed', 'aborted')``.
- ``flow_regime IN ('steady', 'transient', 'steady_then_transient')``.
- ``mesh_topology IN ('dis', 'disv', 'disu')``.
- Index unique ``(project, name)``, index sur ``mesh_hash``,
  ``geographic_fingerprint``, ``config_hash``, ``config_source``, ``status``,
  ``created_at``.

2.2. Vues Parquet
^^^^^^^^^^^^^^^^^

Trois vues exposent les rangées haute volumétrie stockées en Parquet par
simulation :

.. list-table::
   :header-rows: 1

   * - Vue
     - Colonnes clés
     - PK logique
   * - ``timeseries``
     - ``sim_id``, ``station_id``, ``variable``, ``datetime``, ``value``, ``unit``, ``qflag``
     - ``(sim_id, station_id, variable, datetime)``
   * - ``budgets``
     - ``sim_id``, ``timestep``, ``zone_id``, ``component``, ``flux_in``, ``flux_out``, ``unit``
     - ``(sim_id, timestep, zone_id, component)``
   * - ``mass_balance``
     - ``sim_id``, ``timestep``, ``total_in``, ``total_out``, ``storage_in``, ``storage_out``, ``percent_error``, ``unit``
     - ``(sim_id, timestep)``

``ensure_parquet_views`` définit deux formes possibles par vue :

- Si au moins un fichier Parquet existe sous
  ``simulations/*.parquet/<vue>.parquet`` : la vue est un
  ``read_parquet(..., union_by_name=true)``.
- Sinon : vue typée vide, pour que ``SELECT ... FROM timeseries`` reste
  valide sur un workspace neuf.

La vue est rafraîchie à la première écriture qui crée un fichier
Parquet, puis à la suppression du dernier fichier.

Les types DuckDB ``UUID`` et ``TIMESTAMPTZ`` round-trippent via l'encodage
natif Parquet. Aucun cast n'est nécessaire côté lecture.

2.3. Vues utilitaires
^^^^^^^^^^^^^^^^^^^^^

``catalog_schema.py`` définit aussi des vues dénormalisées :

- ``v_simulation_summary`` : une ligne par simulation avec NSE, KGE, RMSE,
  R² agrégés.
- ``v_best_per_project`` : meilleure simulation par projet selon NSE.
- ``v_metrics_wide`` : pivot des métriques sur les noms connus (``nse``,
  ``kge``, ``rmse``, ``r2``, ``bias``, ``pbias``, ``mae``, ``mse``).
- ``v_params_wide`` : paramètres pivotés comme MAP.

2.4. Stores Zarr
^^^^^^^^^^^^^^^^

Chaque simulation dispose d'un store Zarr (ou ``.zarr.zip`` après
finalisation) regroupant les champs spatiaux. Groupes racine :

- ``mesh/`` : topologie UGRID (``vertices``, ``face_node_connectivity``,
  ``z_interfaces``, ``surface_top``).
- ``head/`` : charges hydrauliques ``(n_timesteps, n_layers, n_cells)``.
- ``derived/`` : champs dérivés (``watertable_elevation``,
  ``watertable_depth``, ``seepage_areas``, ``accumulation_flux``).
- ``budget/`` : composantes spatiales (recharge, drain, quaq, qstor).
- ``pathlines/`` : trajectoires de particules (optionnel).
- ``geographic/`` : rasters (DEM, géologie) et vecteurs (via Parquet
  sidecar).
- ``forcing/`` : forçages météo stockés pour audit.

Compression : BLOSC-ZSTD ``clevel=3``. Chunking équilibré calculé par
``_balanced_chunks_1d`` et ``_balanced_chunks_2d`` pour viser environ 1 MiB
par chunk.

Conventions : CF-1.11 plus UGRID-1.0 sont déclarés dans les attributs
racines. L'encodage par variable suit ``field_registry.FIELD_REGISTRY``
(``standard_name``, ``units``, ``cell_methods``, ``grid_mapping``, ``shape``).

2.5. Parquet lakehouse
^^^^^^^^^^^^^^^^^^^^^^

Mécanique d'écriture (``_atomic_write_parquet``) :

1. Enregistrer le DataFrame candidat sur la connexion DuckDB sous
   l'alias ``_hmp_insert``.
2. Construire une requête SELECT avec types DuckDB explicites et ordre
   de colonnes déterministe. Si un fichier cible existe déjà, la requête
   fait ``UNION ALL BY NAME`` avec l'existant, puis applique
   ``QUALIFY ROW_NUMBER() OVER (PARTITION BY <PK> ORDER BY priority DESC) = 1``
   pour reproduire la sémantique ``INSERT OR REPLACE``.
3. Écrire via ``COPY (<select>) TO '<target>.tmp' (FORMAT PARQUET)``.
4. Promouvoir le fichier avec ``os.replace``, atomique sous POSIX.
5. Rafraîchir les vues (``ensure_parquet_views``) si c'est le premier
   fichier pour cette vue.
6. Désenregistrer l'alias ``_hmp_insert``.

Un crash entre les étapes 3 et 4 laisse un ``.tmp`` orphelin. Le glob des
vues ne matche que ``*.parquet``, donc l'orphelin n'est pas visible. `hmp
doctor` peut signaler ces orphelins pour nettoyage manuel.

Pour le détail et les raisons (pourquoi Parquet plutôt qu'une table
DuckDB unique, pourquoi pas de partitionnement Hive), voir
parquet_lakehouse_architecture.

2.6. Nommage des fichiers
^^^^^^^^^^^^^^^^^^^^^^^^^

``catalog.storage_paths.build_storage_basename`` construit des basenames
déterministes : ``<project_slug>__<name_slug>__<short_uuid>``.

- ``sanitize_segment`` normalise par NFD + minuscule, garde ``[a-z0-9_-]``,
  tronque à 32 caractères.
- ``short_uuid`` extrait les 8 premiers hex.

Les anciens workspaces peuvent avoir ``storage_basename NULL`` ; dans ce
cas le fallback est l'UUID complet.

2.7. API publique de ``SimulationCatalog``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Les méthodes suivantes sont le point d'entrée côté écriture (toutes
protégées par ``@with_lock_retry``) :

- ``register_simulation(...)`` : crée ou remplace une ligne ``simulations``,
  retourne le ``sim_id``. Options ``on_collision="replace"|"fail"|"version"``.
- ``write_parameters(sim_id, df)`` : remplace les paramètres.
- ``write_metric(sim_id, station_id, variable, metric_name, value, ...)``.
- ``write_timeseries(sim_id, df)`` / ``write_budgets`` / ``write_mass_balances`` :
  voie Parquet atomique.
- ``write_provenance(sim_id, df)`` : enregistre fingerprints.
- ``write_geographic_feature(sim_id, feature_name, gdf)`` : GeoDataFrame
  vers Parquet sidecar dans le Zarr.
- ``write_geographic_metadata(sim_id, key, value)``.
- ``write_geographic_raster(sim_id, name, array, metadata)`` : raster vers
  Zarr ``geographic/<name>``.
- ``finalize(sim_id, ...)`` : ferme proprement, passe ``status`` à
  ``completed``, optionnellement pack le Zarr en ``.zarr.zip``.
- ``delete(sim_id, remove_storage=True)`` : efface la ligne, ses dépendances,
  le Zarr et le répertoire Parquet. Avec ``remove_storage=False``, seuls les
  enregistrements DuckDB sont supprimés.

Côté lecture :

- ``__getitem__(ref)`` : résolution par UUID complet, préfixe (>= 4 hex)
  ou alias unique ``(project, name)``.
- ``find(**filters)`` : retourne un ``SimulationGroup``. Filtres possibles :
  ``project``, ``solver``, ``status``, ``flow_regime``, ``mesh_topology``,
  bornes métriques (``nse_gt=``, ``kge_ge=``, ...), tags.
- ``best(project, metric="nse")`` : meilleur run du projet pour la métrique.
- ``open_zarr(sim_id)`` : retourne un ``SimulationZarr``.
- ``export_package(sim_id, path)`` et ``import_package(path)`` : voir §2.9.

Toutes les méthodes s'utilisent aussi via un context manager :
``with SimulationCatalog(workspace) as catalog: ...`` ferme la connexion
DuckDB proprement.

2.8. ``Run`` et ``SimulationGroup``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``Run`` est un handle en lecture seule renvoyé par
``catalog[sim_id]``, ``catalog.best(...)`` ou par l'itération d'un
``SimulationGroup``. Propriétés et méthodes :

- Métadonnées : ``sim_id``, ``name``, ``project``, ``solver``, ``status``,
  ``n_cells``, ``n_layers``, ``n_timesteps``, ``duration_s``, ``tags``, ``config``.
- Tabulaire : ``parameters``, ``metrics``, ``provenance`` (DataFrames).
- Séries : ``timeseries(variable, station, period=None)``.
- Bilan : ``budget(component, zone_id, period)``, ``mass_balance``.
- Champs spatiaux : ``field(variable, timestep, layer=None)``,
  ``fields(variable)`` (stack), ``at(timestep, layer)`` chainable.
- Maillage : ``mesh`` (dict vertices/connectivité), ``grid`` (métadonnées
  cellulaires).
- Géographie : ``dem``, ``catchment_mask``, ``geographic(feature_name)``,
  ``geographic_raster(name)``.
- Vues à la volée : ``saturated_fraction``, ``drainage_density``,
  ``persistence``, ``catchment_mean``, ``recharge_forcing`` (voir
  ``views.py``).

``SimulationGroup`` expose ``parameters``, ``metrics`` (DataFrames larges),
``compare(metric)``, ``sort_by``, ``best``, ``worst``, ``to_dataframe``,
``to_csv``, ``to_xarray`` (stack multi-simulation). Filtrage via
``group.filter(**criteria)``.

2.9. Format ``.hmp``
^^^^^^^^^^^^^^^^^^^^

``export_package(sim_id, path)`` produit une archive ``tar.zst`` autonome
(code : ``hydromodpy/results/exporters/hmp_package.py``) :

- ``manifest.json`` : version, sim_id, liste de fichiers plus SHA-256 par
  entrée.
- ``catalog_snapshot.duckdb`` : snapshot des lignes pertinentes
  (``simulations``, ``parameters``, ``metrics``, ``provenance``,
  ``geographic_features``, ``geographic_metadata``).
- ``simulation.zarr.zip`` : Zarr packé de façon déterministe.
- ``parquet/`` : ``timeseries.parquet``, ``budgets.parquet``,
  ``mass_balance.parquet`` matérialisés.
- ``geographic/`` : cache raster content-addressable.
- ``README.md`` : résumé généré.

``import_package(path)`` inverse l'opération dans un workspace cible, avec
détection de collision d'UUID (``on_collision="replace"|"fail"|"version"``).

2.10. Exporters supplémentaires
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``hydromodpy/results/exporters/`` contient en plus :

- ``netcdf.py`` : export CF-compliant multi-dim.
- ``csv.py`` : séries temporelles tabulaires.
- ``vtu.py`` : visualisation ParaView.
- ``geotiff.py`` : rasters SIG.
- ``shapefile.py`` : vecteurs SIG.

Chacun expose un point d'entrée ``export_<format>(run, path, ...)``.

3. Cache d'entrée
~~~~~~~~~~~~~~~~~

Code principal :

- ``hydromodpy/data/registry/catalog_duckdb.py`` : classe
  ``DataCatalogDuckDB``.
- ``hydromodpy/data/base_manager.py`` : ``BaseVariableManager``.
- ``hydromodpy/data/variables/<variable>/`` : managers concrets.
- ``hydromodpy/data/planner.py`` : ``DataPlanner``.
- ``hydromodpy/data/plan.py`` : ``DataLoadPlan``.

3.1. Tables DuckDB
^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Table
     - Rôle
   * - ``entries``
     - Index des fichiers cachés : ``variable``, ``source``, ``station_id``, bbox, période, unité, ``file_path``, ``file_mtime``, ``is_custom``, ``fetch_metadata`` (JSON)
   * - ``api_coverage``
     - Couverture spatiale/temporelle connue par fournisseur
   * - ``artifacts``
     - Artefacts construits par run : ``sim_id``, ``variable``, ``artifact_type``, ``path``, ``sha256``, ``size_bytes``
   * - ``provenance``
     - Logs de transformation : ``artifact_id``, ``input_hash``, outil, version, ``parameters_json``
   * - ``stations``
     - Inventaire des stations : ``station_id``, ``variable``, ``source``, lat/lon/z, nom, périodes
   * - ``coverage``
     - Couverture par variable et source (région WKT, période, nombre de stations)
   * - ``failures``
     - Erreurs de fetch : ``variable``, ``source_ref``, ``error_type``, message, horodatage
   * - ``validation_reports``
     - Audit schéma : ``artifact_id``, ``schema_name``, ``passed``, erreurs JSON

Index : ``ix_entries_var_src_station`` sur `(variable, source,
station_id)``, ``ix_entries_bbox`` sur la bbox, ``ix_artifacts_sha256` pour
la déduplication, ``ix_provenance_artifact`` pour le suivi.

3.2. Contrat ``BaseVariableManager``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Une variable par manager. Attributs de classe :

- ``VARIABLE_NAME: str`` : identifiant canonique (``hydrometry``,
  ``piezometry``, ``geology``, ``dem``, ``precipitation``, ``etp``, ...).

Point d'entree public :

.. code-block:: python

   store = DataStore(
       project_extent=(x1, y1, x2, y2),
       project_period=(start, end),
   )
   result = store.load_hydrometry(config)

Contrat manager interne :

- ``load() -> LoadResult`` : itère les sources configurées, déduplique via
  ``catalog``, renvoie un ``LoadResult`` normalisé.
- ``_fetch_from_source(source_cfg)`` : abstrait, implémenté par chaque
  manager concret.

Variables actuellement implémentées (répertoire
``hydromodpy/data/variables/``) : ``dem``, ``etp``, ``geology``, ``humidity``,
``hydrography``, ``hydrometry``, ``intermittency``, ``oceanic``, ``piezometry``,
``precipitation``, ``radiation``, ``recharge``, ``runoff``, ``soil_moisture``,
``temperature``, ``water_quality``, ``wind``, plus un
``timeseries_variable_config.py`` partagé.

3.3. Sources
^^^^^^^^^^^^

Chaque manager délègue à un ou plusieurs ``DataSource``. Les sources
concrètes (Hub'Eau, SIM2, custom file, BRGM) sont enregistrées au niveau
du manager correspondant, via un registre par variable.

Exemples :

- Hub'Eau pour l'hydrométrie et la piézométrie : cache sur `(variable,
  source, station_id, période)`.
- SIM2 / Météo-France (EDR API) pour précipitations, ETP, humidité,
  température, rayonnement.
- Fichiers custom : CSV, NetCDF, GeoTIFF, Shapefile. Dispatch par
  extension.

Le cache déduplique via ``entries.file_path`` plus ``file_mtime``. Les
nouveaux téléchargements écrivent d'abord un fichier sous
``data/<variable>/``, puis insèrent la ligne.

3.4. Planner et plan
^^^^^^^^^^^^^^^^^^^^

`DataPlanner.build(config, domain_zone_ids, domain_support_provider_names,
flow_active_bc, requested_spatial_support_ids, raw_toml)` résout les
managers à activer pour un run. Résultat immuable : ``DataLoadPlan`` avec
``explicit_types``, ``inferred_types``, ``reasons_by_type``.

Règles d'inférence (V3) :

- ``domain.zone_ids`` contient ``geology`` : active ``geology``.
- ``domain.supports`` fournisseur ``geology`` : active ``geology``.
- ``flow.active_bc`` contient ``stream`` : active ``hydrography``.
- ``flow.active_bc`` contient ``ocean`` : active ``oceanic``.

Mode ``inference_mode="strict"`` : toute inférence requiert une section
``[data.<type>]`` explicite (sauf défauts géologie). Mode ``"warn"`` :
inférences autorisées avec log informatif.

4. Interactions entre workflows et bases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Les workflows CLI sont détaillés dans :doc:`CLI <cli>`. Voici leur
interaction avec les deux bases.

4.1. ``simulation``
^^^^^^^^^^^^^^^^^^^

Pipeline standard ``hmp run config.toml`` (workflow implicite ou
``[workflow].mode = "simulation"``), code ``hydromodpy/workflow/pipelines/simulation.py``.

Phase de préparation :

1. ``step_setup`` : initialise le contexte.
2. ``step_spatial_supports(phase="setup")`` : config des supports.
3. ``step_data_loading`` :

   - Ouvre le cache d'entrée en lecture (``DataCatalogDuckDB``).
   - Les managers appellent ``load()``. En miss, téléchargement puis
     insertions dans ``entries``, ``stations``, ``coverage``, parfois
     ``failures``.
4. ``step_spatial_supports(phase="data")`` : branchement données
   chargées.
5. ``step_mesh`` puis ``step_mesh_input`` : construction du maillage.

Phase d'exécution :

6. ``step_open_store`` :

   - Ouvre le catalogue de sortie.
   - ``register_simulation(...)`` en ``@with_lock_retry``.
   - Crée ``simulations/<basename>.zarr/`` via ``SimulationZarr.create``.
7. Boucle solveur : le ``SolverAdapter`` produit ses sorties natives dans
   un scratch dir.
8. ``step_ingest_run_results`` :

   - Zarr : ``write_field`` pour ``head``, ``budget``, ``derived``.
   - Parquet : ``write_timeseries``, ``write_budgets``, ``write_mass_balances``.
   - DuckDB : ``write_parameters``, ``write_metric``,
     ``register_observation_points``.
9. ``step_write_provenance`` : insertion dans ``provenance``.
10. ``step_finalize_store`` : ``finalize(sim_id)`` met ``status='completed'``,
    rafraîchit les vues Parquet, pack optionnel du Zarr.

4.2. ``calibration``
^^^^^^^^^^^^^^^^^^^^

Code ``hydromodpy/calibration/``. Trace complète via
``CalibrationPersistence`` (``persistence.py``).

- ``start_session()`` : ``INSERT INTO calibration_sessions`` en
  ``@with_lock_retry``.
- Pour chaque trial :

  1. L'optimiseur propose un jeu de paramètres.
  2. Si ``params_hash`` est présent dans ``calibration_iterations`` de la
     session courante ou d'une précédente : réutilisation du ``sim_id`` et
     des métriques, ``from_cache=True``.
  3. Sinon, exécution d'une simulation complète (même pipeline qu'en
     §4.1). Les écritures solveur ne sont faites que pour les trials
     promus (``save_runs``).
  4. ``append_iteration()`` insère une ligne dans ``calibration_iterations``
     en ``ON CONFLICT (session_id, iteration) DO UPDATE``, ce qui rend
     l'écriture idempotente.
- Fin de session : passage au statut ``completed``, écriture éventuelle
  d'un rapport HTML.

L'écriture des iterations est sérielle par trial ; le verrou DuckDB est
pris puis relâché par trial. Une session peut donc tourner en parallèle
d'autres lectures sans risque de corruption.

Pour les détails (paramètres, objectifs, optimizers, pièges), voir
:doc:`calibration_guide <calibration_guide>`.

4.3. ``batch``
^^^^^^^^^^^^^^

Campagne régionale : expansion site × recette × solveur. Code
``hydromodpy/analysis/batch/``.

- Sites exécutés en parallèle, un par process.
- Chaque site dispose de son propre ``<basename>.zarr/`` et
  ``<basename>.parquet/``, donc pas de contention disque entre sites.
- Les écritures DuckDB (``register_simulation``, ``write_*``) sont
  sérialisées par le verrou fichier, avec retry exponentiel via
  ``@with_lock_retry``.
- L'agrégation en fin de batch se fait via SQL, sans lock contention
  en lecture.

4.4. ``overview`` et ``mesh``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Workflows d'inspection et de préparation :

- ``overview`` (``workflow/pipelines/overview.py``) : lit le cache d'entrée
  pour vérifier la disponibilité des données, produit un rapport HTML
  ou JSON. **N'écrit rien** dans le catalogue de sortie.
- ``mesh`` (``workflow/pipelines/mesh.py``) : charge les données nécessaires
  au maillage (DEM, géologie si conformité demandée), produit le
  maillage et l'exporte. ``register_simulation(..., status='mesh_only')``
  et écriture Zarr ``mesh/``. **Aucune ligne** dans ``timeseries``,
  ``budgets`` ou ``mass_balance``.

5. Concurrence et robustesse
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Code : ``hydromodpy/core/io/db_retry.py``.

5.1. Verrou DuckDB
^^^^^^^^^^^^^^^^^^

DuckDB prend un verrou de writer unique sur le fichier au ``connect()``.
Perdre la course lève ``duckdb.IOException``.

Politique de retry :

- ``connect_with_retry(db_path, retries=8, backoff=0.05)`` : utilisé par
  ``SimulationCatalog.__init__``. Délais croissants (0.05, 0.1, 0.2, 0.4,
  0.8, 1.6, 3.2, 6.4 secondes, total environ 13 s).
- ``@with_lock_retry(retries=8, backoff=0.05)`` : décore toutes les
  méthodes d'écriture du catalogue (register, write_parameters,
  write_metric, write_provenance, register_observation_points,
  register_tracked_files, write_geographic_feature, finalize, delete,
  plus les trois writers Parquet).

Les lectures ne retentent pas. Un reader qui heurte le verrou lève
immédiatement. Aucun code ne s'appuie aujourd'hui sur des lectures
concurrentes d'écritures.

5.2. Atomicité Parquet
^^^^^^^^^^^^^^^^^^^^^^

Voir §2.5 pour le détail.

- Écriture dans un ``.tmp`` sibling, ``os.replace`` atomique.
- Fusion par ``UNION ALL BY NAME`` plus ``QUALIFY ROW_NUMBER``,
  équivalent à ``INSERT OR REPLACE`` sur la PK.
- Le glob des vues ignore les ``.tmp`` : un crash laisse un orphelin
  inoffensif.

5.3. Scénarios d'échec
^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Étape
     - Effet
     - Récupération
   * - Acquisition du verrou DuckDB
     - Processus tué verrou pris
     - Relance ; le verrou est libéré à la fermeture du processus
   * - ``INSERT`` simulations
     - Row absente ou partielle
     - Relance ; insertion idempotente sur ``sim_id``
   * - Écriture Zarr
     - Chunk incomplet
     - Append-safe ; la relecture renvoie NaN sur les chunks manquants
   * - ``COPY TO .tmp`` Parquet
     - Fichier cible inchangé, ``.tmp`` orphelin
     - Relance ; ``hmp doctor`` signale l'orphelin
   * - ``os.replace``
     - Opération atomique au niveau OS
     - Pas de crash mi-swap possible
   * - Fermeture DuckDB
     - WAL DuckDB rollback automatique
     - Relecture saine

5.4. Commandes de maintenance
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- ``hmp doctor --toml config.toml`` ou ``hmp doctor --workspace PATH`` :

  - Diagnostic de l'environnement (Python, dépendances, solveurs).
  - Vérification du workspace DuckDB (schéma, simulations).
  - Présence des binaires.
  - Détection des Zarr manquants, des orphelins Zarr/Parquet et des ``.parquet.tmp``.

6. Lecture côté Python
~~~~~~~~~~~~~~~~~~~~~~

API publique (voir :doc:`glossary <glossary>` pour les types) :

.. code-block:: python

   import hydromodpy as hmp

   # Ouverture en lecture
   catalog = hmp.open("~/workspace")       # SimulationCatalog

   # Résolution de simulation
   run = catalog["abc12345"]                # préfixe UUID ou UUID complet
   run = catalog.best("canut", metric="nse")

   # Recherche groupée
   group = catalog.find(project="canut", nse_gt=0.7)
   best = group.best("nse")
   worst = group.worst("nse")

   # Accès aux données
   head_t12 = run.field("head", timestep=12)
   q = run.timeseries("discharge", station="__outlet__")
   ts = run.timeseries("head", station="P01", period=("2010-01-01", "2015-01-01"))
   budget = run.budget(component="recharge")
   mb = run.mass_balance

   # Vues catchment-scale (calculées à la volée depuis le Zarr)
   sat = run.saturated_fraction(threshold=0.0)
   dden = run.drainage_density()
   rch = run.recharge_forcing()

   # Géographie
   gdf = run.geographic("stations")
   dem = run.dem
   mask = run.catchment_mask

   # Pivot multi-simulation
   df = group.to_dataframe(
       params=["thickness", "k_brgm"],
       metrics=["nse", "kge"],
   )
   group.to_csv("output.csv")
   da = group.to_xarray("head", dim="sim")

   # Rendu
   run.plot("watertable_map", save_path="~/figures/")

   # Partage entre workspaces
   catalog.export_package(run.sim_id, "~/share/run.hmp")
   catalog.import_package("~/share/other.hmp")

``SimulationCatalog`` est un context manager ; en dehors de ce modèle,
appeler ``catalog.close()`` pour libérer le verrou.

7. Flux récapitulatif
~~~~~~~~~~~~~~~~~~~~~

Diagramme synthétique d'une simulation :

.. code-block:: text

   [TOML config] --> hmp run
       | read
       v
   [data/cache.duckdb] <--- fetch --- [Hub'Eau, SIM2, fichiers custom]
       | load
       v
   [runtime: WorkflowContext]
       | execute
       v
   [solver scratch dir]
       | ingest
       v
   [hydromodpy.duckdb] (metadata)
   [simulations/<basename>.zarr/] (champs)
   [simulations/<basename>.parquet/] (séries)
       | read
       v
   [Run, SimulationGroup, figures, exports]

La séparation en deux bases DuckDB est motivée par l'indépendance des
cycles de vie : le cache d'entrée survit aux simulations et sert
plusieurs runs ; le catalogue de sortie évolue à chaque run. Les deux
peuvent être inspectés indépendamment via ``hmp doctor`` ou directement
en SQL (``duckdb <fichier.duckdb>``).

Parquet lakehouse architecture
------------------------------

This document describes where per-simulation time series, budgets and
mass-balance rows live on disk, how the catalog exposes them as SQL, and
why the refactor chose this layout.

Supersedes the "timeseries / budgets / mass_balance" portions of
``docs/developers/simulation_catalog_architecture.md``.

What moved and what did not
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before the v1 Parquet lakehouse refactor, every per-simulation table sat inside the
workspace-level ``hydromodpy.duckdb`` file:

- ``timeseries``: 70 years of daily rows per station per variable per sim.
- ``budgets``: water budget per (timestep, zone, component) per sim.
- ``mass_balance``: global in/out/percent_error per timestep per sim.

These three tables were the only ones with append-only, high-volume,
per-simulation rows. Keeping them in a single DuckDB file made concurrent
writes impossible (DuckDB holds a single-writer lock per file) and made
the catalog file grow into the multi-gigabyte range on long-running
projects. They are now Parquet files on disk; everything else stays in
DuckDB.

Tables that still live inside ``hydromodpy.duckdb``:

- ``simulations``, ``parameters``, ``metrics``, ``observation_points``,
  ``provenance``, ``geographic_features``, ``geographic_metadata``,
  ``runs_environment``, ``tags``, ``tracked_files``, ``calibration_sessions``,
  ``calibration_iterations``, ``stations``, ``observations``.

On-disk layout
~~~~~~~~~~~~~~

.. code-block:: text

   workspace/
   ├── hydromodpy.duckdb              # metadata only (catalog tables + views)
   ├── data/
   │   ├── cache.duckdb
   │   └── <variable>/
   ├── simulations/
   │   ├── <basename>.zarr/           # spatial fields
   │   ├── <basename>.zarr.zip        # packed Zarr after finalize
   │   └── <basename>.parquet/
   │       ├── timeseries.parquet
   │       ├── budgets.parquet
   │       └── mass_balance.parquet
   └── projects/

The per-simulation basename comes from ``simulations.storage_basename``
(``project_slug__name_slug__short_uuid``). Legacy rows with
``storage_basename NULL`` fall back to the raw UUID. The ``.parquet`` suffix
lets the view glob pick up Parquet files without ever matching a Zarr
directory by accident.

A simulation with no time series (e.g. an overview-only run) has no
``<basename>.parquet/`` directory. The view glob tolerates this.

SQL surface
~~~~~~~~~~~

DuckDB exposes the three data sources as **views** named ``timeseries``,
``budgets``, ``mass_balance``. Code that previously ran
``SELECT * FROM timeseries WHERE sim_id = ?`` keeps working unchanged.

The view is one of two shapes, chosen when the catalog opens:

1. If at least one matching Parquet file exists:

   .. code-block:: sql

      CREATE OR REPLACE VIEW timeseries AS
      SELECT * FROM read_parquet(
          '<workspace>/simulations/*.parquet/timeseries.parquet',
          union_by_name=true
      );

2. If no file exists yet: an empty typed view with the same column set,
   so a fresh workspace still answers ``SELECT * FROM timeseries`` cleanly.

On the first write that creates a Parquet file, the catalog refreshes
the view. After ``delete()`` removes the last sim, the view collapses back
to the empty form.

DuckDB's UUID and ``TIMESTAMPTZ`` types round-trip through Parquet via its
native encoding, so the view columns have the same types as the legacy
SQL tables. No casts are needed on the read path.

Write path
~~~~~~~~~~

``SimulationCatalog.write_timeseries``, ``write_budgets``,
``write_mass_balances`` share a common helper
(``_atomic_write_parquet``) that:

1. Normalises the incoming pandas ``DataFrame`` to a deterministic column
   order and explicit DuckDB types via a `SELECT ... CAST ... FROM
   _hmp_insert` expression.
2. If the target Parquet already exists: unions the existing rows with
   the new ones and keeps the newest per primary key
   (``QUALIFY ROW_NUMBER() OVER (PARTITION BY pk ORDER BY priority DESC) = 1``).
   This matches the old ``INSERT OR REPLACE`` semantics.
3. Writes the result to a sibling ``.tmp`` file via DuckDB's native
   ``COPY (SELECT ...) TO '<path>.tmp' (FORMAT PARQUET)``.
4. Promotes the file with ``os.replace``, which is atomic on POSIX.

A crash mid-write leaves a ``.tmp`` file behind. Because the glob only
matches ``*.parquet``, nothing in the ``.tmp`` file is visible through the
view. The orphan is harmless and ``hmp doctor`` reports it as
``results:parquet_tmp`` for manual cleanup.

Concurrency model
~~~~~~~~~~~~~~~~~

Each per-sim Parquet file lives under its own ``<basename>.parquet/``
directory, so two writers targeting different sims never contend on
disk. They do still share the DuckDB catalog file, which is the
single-writer lock point. ``connect_with_retry`` in
``hydromodpy.core.io.db_retry`` loops with exponential backoff over
``duckdb.IOException`` at connect time, and ``@with_lock_retry`` does the same
on ``execute()`` calls for write methods.

Read-only queries never hit the retry path: a reader that collides with
a writer raises naturally and the caller can retry.

See ``parquet_lakehouse_concurrency.md`` for the failure modes and
matching tests.

Why this layout, not hive-style partitioning
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

DuckDB supports ``hive_partitioning=true`` in ``read_parquet`` if the path
has ``key=value`` directories. We evaluated that but rejected it because:

- The partition column (``sim_id``) is already a column inside each
  Parquet file, so hive path components would duplicate it.
- Naming the per-sim directory ``sim_id=<uuid>`` would add a partition-style
  layer while ``sim_id`` is already a column inside each file. Keeping the
  suffix ``.parquet`` on the simulation basename is enough to disambiguate
  from Zarr.
- At our scale (thousands of sims, not millions) DuckDB's row-group
  statistics in the Parquet footer give enough predicate pushdown on
  ``WHERE sim_id = ?`` that partition pruning by path would not change
  query times noticeably.

If that ever becomes a real bottleneck, moving the layout to
``simulations/sim_id=<uuid>/timeseries.parquet`` is a localized change handled
inside ``_glob_for_view`` and ``StoragePathResolver.parquet_dir_for``.

Concurrency, retry and atomic writes
------------------------------------

This note documents the mechanisms the Parquet lakehouse uses to stay
consistent when multiple processes touch the same workspace.

The DuckDB lock
~~~~~~~~~~~~~~~

DuckDB takes a single-writer lock on the catalog file at ``connect()``
time. Losing the race raises ``duckdb.IOException``. The lock is not
reentrant across processes; within a single process, the connection is
cheap and writes don't re-contend.

Our catalog retries at two places:

- ``connect_with_retry`` (``hydromodpy/core/io/db_retry.py``) loops over
  ``duckdb.connect`` with exponential backoff. Used by
  ``SimulationCatalog.__init__``.
- ``@with_lock_retry()`` wraps every ``SimulationCatalog`` write method
  (register, write_parameters, write_metric, write_provenance,
  register_observation_points, register_tracked_files,
  write_geographic_feature, write_geographic_metadata, finalize, delete
  and the three Parquet writers). Retries on ``duckdb.IOException`` raised
  from ``execute``.

Default backoff is 8 attempts starting at 50 ms, doubling each try. The
total worst-case wait is about 12 seconds, which tolerates the small
overlapping windows that happen during cross-process calls like
``hmp list`` running while ``hmp run`` is committing.

Read-only queries deliberately do **not** retry. A reader that hits a
lock raises immediately and the caller is free to retry at a higher
level. The current codebase has no concurrent reader/writer usage, so
this policy is conservative rather than limiting.

Atomic Parquet writes
~~~~~~~~~~~~~~~~~~~~~

Every Parquet write goes through ``_atomic_write_parquet``:

1. Collect the new rows into an ``insert_df`` pandas DataFrame and
   register it on the DuckDB connection under the alias ``_hmp_insert``.
2. Issue ``COPY (<select>) TO '<target>.tmp' (FORMAT PARQUET)``. If the
   target already exists, the select unions the existing file with
   ``_hmp_insert``, deduplicates on the primary key, and keeps the newer
   row. This mirrors the old ``INSERT OR REPLACE`` semantics.
3. ``os.replace('<target>.tmp', '<target>')``: atomic on POSIX and on
   NTFS when both paths are on the same volume, which they always are
   because the ``.tmp`` is a sibling of the target.
4. Unregister ``_hmp_insert``.
5. If this was the first file for that view, call
   ``ensure_parquet_views`` so the view DDL upgrades from its empty form
   to the ``read_parquet(...)`` form.

The glob used by the view (``simulations/*.parquet/timeseries.parquet``)
never matches the ``.tmp`` file, so a crash between step 2 and step 3
leaves a harmless orphan. ``hmp doctor`` reports the orphan under
``results:parquet_tmp``.

Concurrent writers to different sims
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Because each simulation owns its own ``<basename>.parquet/`` directory, two
writers aimed at two different sims never contend on the Parquet files
themselves. They do share the DuckDB catalog for metadata (the
``simulations`` row, parameter and metric inserts, and the view DDL
refresh), which is why ``connect_with_retry`` matters.

The test in
``tests/unit/results/test_parquet_lakehouse.py::TestConcurrentWrites``
exercises this with 8 worker processes writing 8 distinct sims against
a single workspace and asserts no data loss.

Concurrent writers to the same sim
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Two writers targeting the same ``(sim_id, view)`` both rewrite the same
Parquet file. The order of ``os.replace`` calls determines which write
survives; the loser's rows are lost. This is acceptable because:

- Inside one simulation, writes happen from one extractor run in a
  single process. The calibration loop is strictly serial
  (``hydromodpy/calibration/engine.py``).
- ``write_timeseries`` is idempotent against the same input: two calls
  with the same rows produce the same file, regardless of order.

If a future workflow runs parallel workers that all write against the
same sim, this contract needs revisiting: a per-sim file lock, or a
per-(sim, view) lock, would be the smallest fix.

Failure modes we don't guard against
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Full disk during COPY**: the ``.tmp`` file is partial. The target is
  not promoted. Next run will either retry (if the caller tries again)
  or leave the orphan in place.
- **Power loss between COPY and replace**: same story. The target is
  unchanged; the ``.tmp`` orphan can be removed safely.
- **Process kill mid-COPY**: DuckDB closes the output file as part of
  its COPY handler; if killed, the ``.tmp`` is incomplete. Again, not
  visible through the view.
- **Concurrent catalog migration and ``hmp run`` on the same workspace**:
  undefined. Don't. The catalog lock serialises the two processes at
  ``connect()`` but they can still race on view creation if both start
  within a narrow window. Run migration against a quiesced workspace.

Architecture du Simulation Catalog
----------------------------------

Ce document décrit l'architecture complète du stockage, de l'accès aux
données et de l'API Python pour HydroModPy.

Principe fondamental : la **simulation** est l'entité première. Le concept
de « projet » est un label, pas un dossier. Une seule base DuckDB contient
toutes les simulations du workspace.

Liens : :doc:`glossary <glossary>`,
parquet_lakehouse_architecture,
parquet_lakehouse_concurrency,
:doc:`schema_evolution <schema_evolution>`,
:doc:`calibration_guide <calibration_guide>`.

Note v1 (refactor Parquet lakehouse) : les tables ``timeseries``,
``budgets`` et ``mass_balance`` ne sont plus stockées dans
``hydromodpy.duckdb``. Elles vivent désormais en Parquet par simulation
sous ``simulations/<basename>.parquet/``, exposées comme des vues DuckDB du
même nom afin que le code SQL existant reste valide. ``<basename>`` est le
nom lisible ``<project>__<name>__<shortuuid>`` ; les anciens workspaces qui
utilisent l'UUID brut restent lisibles et peuvent être normalisés
explicitement.

1. Structure physique du workspace
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   workspace/
   ├── hydromodpy.duckdb              # source de verite unique (toutes les simulations)
   ├── data/
   │   ├── cache.duckdb               # cache des donnees d'entree (API + custom index)
   │   └── <variable>/                # fichiers bruts (CSV, NC, TIF)
   │       ├── dem/
   │       ├── geology/
   │       ├── hydrometry/
   │       ├── piezometry/
   │       ├── recharge/
   │       └── ...
   ├── simulations/                   # artefacts par simulation (isolation physique)
   │   ├── <basename-aaa>.zarr/ ou .zarr.zip
   │   ├── <basename-aaa>.parquet/
   │   ├── <basename-bbb>.zarr/ ou .zarr.zip
   │   ├── <basename-bbb>.parquet/
   │   └── ...
   └── configs/                       # TOMLs utilisateur (organisation libre)
       ├── canut/
       │   ├── base.toml
       │   └── run_steady_mf6.toml
       └── nancon/
           ├── base.toml
           └── run_transient_nwt.toml

Apres ``hmp run config.toml`` :

- une ligne est ajoutee dans ``hydromodpy.duckdb``
- un artefact ``simulations/<basename>.zarr/`` est cree, puis peut être packé
  en ``.zarr.zip``
- aucun fichier intermediaire ne persiste sur disque

2. Pourquoi une seule base DuckDB
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

L'architecture precedente utilisait N ``project.duckdb`` (un par projet) plus un
``catalog.duckdb`` (workspace) avec duplication partielle des metadonnees.

Problemes identifies :

- ``simulation_registry`` dans catalog.duckdb etait ecrit mais jamais lu en production
- les requetes cross-projet necessitaient d'ouvrir N stores separement
- la calibration et le batch contournaient le store (JSONL, CSV sur disque)
- pas de table normalisee pour les parametres (impossible de faire du ML directement)

Avec une seule base :

- comparaison inter-simulations = un simple ``WHERE``
- comparaison inter-bassins = un ``GROUP BY project``
- ML/deep learning = une requete SQL retourne un DataFrame pret pour sklearn/pytorch
- pas de duplication, pas d'incoherence entre fichiers

3. Schema DuckDB : hydromodpy.duckdb
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

3.1. simulations
^^^^^^^^^^^^^^^^

Table centrale. Une ligne = un run complet.

.. code-block:: sql

   CREATE TABLE simulations (
       sim_id          UUID PRIMARY KEY,
       name            VARCHAR,
       project         VARCHAR,           -- label libre ("canut", "nancon")
       solver          VARCHAR,           -- modflownwt, modflow6, boussinesq
       solver_category VARCHAR,           -- 'distributed' ou 'integrated'
       flow_regime     VARCHAR,           -- steady ou transient
       n_cells         INTEGER,
       n_layers        INTEGER,
       n_timesteps     INTEGER,
       bbox            DOUBLE[4],
       crs             VARCHAR,
       period_start    VARCHAR,
       period_end      VARCHAR,
       time_unit       VARCHAR,
       status          VARCHAR,           -- running, completed, failed
       duration_s      DOUBLE,
       created_at      TIMESTAMP DEFAULT now(),
       config_toml     JSON,              -- snapshot TOML complete pour reproduction
       config_hash     VARCHAR,           -- SHA-256 (detection doublons)
       zarr_path       VARCHAR,           -- chemin relatif vers le .zarr
       tags            VARCHAR[],
       parent_sim_id   UUID,              -- filiation (rerun, best-of-calibration)
       mesh_hash       VARCHAR,           -- SHA-256 du mesh bundle
       mesh_type       VARCHAR,           -- structured, gmsh_triangular
       notes           VARCHAR
   );

``solver_category`` est derive de ``solver`` :

- ``distributed`` : modflownwt, modflow6 (maillage 3D, multi-couche)
- ``integrated`` : boussinesq (thin-film, mono-couche)

Utilise par le display pipeline pour determiner les figures compatibles.

``parent_sim_id`` permet de tracer la filiation :

- calibration best-run → pointe vers la session
- rerun avec overrides → pointe vers le run original
- NULL = run independant

3.2. parameters
^^^^^^^^^^^^^^^

Table normalisee pour les parametres hydrauliques. Permet les requetes ML directes.

.. code-block:: sql

   CREATE TABLE parameters (
       sim_id          UUID REFERENCES simulations,
       param_name      VARCHAR,           -- K, Sy, Ss, recharge_factor
       zone_id         VARCHAR,           -- NULL si homogene, geology_key sinon
       value           DOUBLE,
       unit            VARCHAR,
       parameterization VARCHAR,          -- homogeneous, geology_mapped, exponential
       PRIMARY KEY (sim_id, param_name, zone_id)
   );

Exemple avec simulation homogene :

.. code-block:: text

   sim_id   | param_name | zone_id | value  | unit | parameterization
   ---------|------------|---------|--------|------|-----------------
   aaa-111  | K          | NULL    | 1.728  | m/d  | homogeneous
   aaa-111  | Sy         | NULL    | 0.05   | -    | homogeneous

Exemple avec parametres par lithologie :

.. code-block:: text

   sim_id   | param_name | zone_id  | value  | unit | parameterization
   ---------|------------|----------|--------|------|-----------------
   bbb-222  | K          | granite  | 0.5    | m/d  | geology_mapped
   bbb-222  | K          | schiste  | 2.0    | m/d  | geology_mapped
   bbb-222  | Sy         | granite  | 0.02   | -    | geology_mapped
   bbb-222  | Sy         | schiste  | 0.08   | -    | geology_mapped

Requete ML typique :

.. code-block:: sql

   SELECT
       s.sim_id, s.solver, s.project, s.n_cells,
       p_k.value AS K, p_sy.value AS Sy,
       m.value AS nse
   FROM simulations s
   JOIN parameters p_k  ON s.sim_id = p_k.sim_id  AND p_k.param_name = 'K' AND p_k.zone_id IS NULL
   JOIN parameters p_sy ON s.sim_id = p_sy.sim_id AND p_sy.param_name = 'Sy' AND p_sy.zone_id IS NULL
   JOIN metrics m       ON s.sim_id = m.sim_id     AND m.metric_name = 'nse'
   WHERE s.status = 'completed';

3.3. timeseries
^^^^^^^^^^^^^^^

Series temporelles ponctuelles (stations d'observation, exutoire).

.. code-block:: sql

   CREATE TABLE timeseries (
       sim_id      UUID REFERENCES simulations,
       station_id  VARCHAR,
       variable    VARCHAR,       -- head, discharge, concentration
       timestamp   TIMESTAMP,
       value       DOUBLE,
       unit        VARCHAR
   );
   CREATE INDEX ix_ts ON timeseries (sim_id, station_id, variable, timestamp);

Volume typique : ~500-5000 lignes par simulation (nombre de stations x nombre de pas de temps).
Avec 1000 simulations : ~5M lignes. DuckDB gere sans probleme.

3.4. budgets
^^^^^^^^^^^^

Bilan hydrique par composante et par zone.

.. code-block:: sql

   CREATE TABLE budgets (
       sim_id      UUID REFERENCES simulations,
       timestep    INTEGER,
       zone_id     VARCHAR,
       component   VARCHAR,       -- recharge, drain, river, wells, storage
       flux_in     DOUBLE,
       flux_out    DOUBLE,
       unit        VARCHAR DEFAULT 'm3/d'
   );

3.5. mass_balance
^^^^^^^^^^^^^^^^^

Bilan de masse global (verification de la conservation).

.. code-block:: sql

   CREATE TABLE mass_balance (
       sim_id        UUID REFERENCES simulations,
       timestep      INTEGER,
       total_in      DOUBLE,
       total_out     DOUBLE,
       storage_in    DOUBLE,
       storage_out   DOUBLE,
       percent_error DOUBLE
   );

3.6. metrics
^^^^^^^^^^^^

Metriques de performance par station d'observation.

.. code-block:: sql

   CREATE TABLE metrics (
       sim_id      UUID REFERENCES simulations,
       station_id  VARCHAR,
       metric_name VARCHAR,       -- nse, kge, rmse, bias, r2, pbias
       value       DOUBLE,
       PRIMARY KEY (sim_id, station_id, metric_name)
   );

3.7. observation_points
^^^^^^^^^^^^^^^^^^^^^^^

Mapping entre stations d'observation et cellules du maillage.

.. code-block:: sql

   CREATE TABLE observation_points (
       sim_id      UUID REFERENCES simulations,
       station_id  VARCHAR,
       x           DOUBLE,
       y           DOUBLE,
       cell_id     INTEGER,
       layer       INTEGER,
       variable    VARCHAR
   );

3.8. provenance
^^^^^^^^^^^^^^^

Empreinte des donnees d'entree pour chaque simulation.
Permet de verifier si les donnees source ont change depuis l'execution.

.. code-block:: sql

   CREATE TABLE provenance (
       sim_id       UUID REFERENCES simulations,
       variable     VARCHAR,       -- recharge, geology, dem, hydrometry
       source_type  VARCHAR,       -- custom, hubeau, sim2, ign_bdalti
       source_ref   VARCHAR,       -- chemin fichier ou URL API
       checksum     VARCHAR,       -- SHA-256 des donnees
       period_start VARCHAR,
       period_end   VARCHAR,
       n_records    INTEGER,
       stats        JSON           -- {mean, min, max, std}
   );

3.9. calibration_sessions
^^^^^^^^^^^^^^^^^^^^^^^^^

Metadata d'une session de calibration.

.. code-block:: sql

   CREATE TABLE calibration_sessions (
       session_id     UUID PRIMARY KEY,
       best_sim_id    UUID REFERENCES simulations,
       method         VARCHAR,       -- scipy_minimize, nlopt, pymoo
       n_iterations   INTEGER,
       best_objective DOUBLE,
       duration_s     DOUBLE,
       config         JSON,          -- section [calibration] du TOML
       created_at     TIMESTAMP DEFAULT now()
   );

3.10. calibration_iterations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Trace complete des iterations. Ecrite en bulk a la fin de la session
(pas d'ecriture DB pendant l'optimisation, zero overhead sur la vitesse).

.. code-block:: sql

   CREATE TABLE calibration_iterations (
       session_id      UUID REFERENCES calibration_sessions,
       iteration       INTEGER,
       parameters      JSON,          -- {K: 1.5, Sy: 0.03}
       objective_value DOUBLE,
       metrics         JSON,          -- {nse: 0.8, rmse: 0.5}
       duration_s      DOUBLE,
       PRIMARY KEY (session_id, iteration)
   );

Workflow :

1. l'optimiseur tourne en memoire (rapide, pas de DB)
2. a la fin, ``INSERT INTO calibration_sessions`` (1 ligne)
3. puis ``INSERT INTO calibration_iterations`` (N lignes, bulk)
4. le best-run est une simulation normale avec ``parent_sim_id`` pointant vers la session

3.11. geographic_features
^^^^^^^^^^^^^^^^^^^^^^^^^

Entites geographiques vectorielles, rattachees a un projet (bassin versant).

.. code-block:: sql

   CREATE TABLE geographic_features (
       project       VARCHAR,
       feature_name  VARCHAR,       -- watershed, river_network, outlet, bbox
       geojson       TEXT,          -- GeoDataFrame serialisee en GeoJSON
       geometry_type VARCHAR,
       crs           VARCHAR,
       properties    JSON,
       PRIMARY KEY (project, feature_name)
   );

Scope : par projet (bassin), pas par simulation. Toutes les simulations d'un meme
bassin partagent les memes features geographiques.

3.12. geographic_metadata
^^^^^^^^^^^^^^^^^^^^^^^^^

Metadonnees scalaires du bassin versant.

.. code-block:: sql

   CREATE TABLE geographic_metadata (
       project VARCHAR,
       key     VARCHAR,               -- catchment_area_km2, crs, outlet_x, dem_resolution...
       value   VARCHAR,
       PRIMARY KEY (project, key)
   );

4. Layout Zarr : standardise, solver-agnostique
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Chaque simulation a son propre dossier Zarr. Le nommage des variables est identique
quel que soit le solver (modflownwt, modflow6, boussinesq).

.. code-block:: text

   simulations/<basename>.zarr/
   ├── zarr.json                        # Zarr v3 root metadata
   │
   ├── mesh/
   │   ├── vertices                     # (n_nodes, 2|3) float64
   │   ├── face_node_connectivity       # (n_cells, max_vpf) int32, -1 = padding
   │   └── z_interfaces                 # (n_layers+1,) float64
   │
   ├── head/                            # variable primaire (tous les solvers)
   │   ├── 0                            # (n_layers, n_cells) float64
   │   ├── 1
   │   └── ...N
   │
   ├── concentration/                   # transport (MF6-GWT, MT3DMS) - optionnel
   │   └── 0 ... N
   │
   ├── derived/                         # variables calculees, solver-agnostique
   │   ├── watertable_elevation/        # (n_cells,) par timestep
   │   ├── watertable_depth/            # (n_cells,) par timestep
   │   ├── seepage_areas/               # (n_cells,) binaire par timestep
   │   ├── outflow_drain/               # (n_cells,) optionnel
   │   └── accumulation_flux/           # (n_cells,) optionnel
   │
   ├── budget/                          # champs spatiaux de budget (optionnel)
   │   ├── recharge/                    # (n_cells,) par timestep
   │   ├── drain/
   │   └── ...
   │
   ├── pathlines/                       # trajectoires de particules (MODPATH)
   │   ├── x, y, z, time               # (n_particles,)
   │   └── ...
   │
   └── geographic/                      # rasters du bassin
       ├── dem                          # (ny, nx) float64 + attrs {transform, crs, nodata}
       └── geology                      # (ny, nx) int32

Compression : BLOSC-ZSTD (clevel=3). Chunking : ``(1, n_layers, n_cells)`` par timestep.

Convention : les noms de variables sont fixes et documentes ici. Les solver adapters
(OutputAdapter) ecrivent dans ces noms standardises. Le display pipeline lit ces noms
sans savoir quel solver a produit les resultats.

5. Cache des donnees d'entree : data/cache.duckdb
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Fichier separe de ``hydromodpy.duckdb``. Concerne uniquement le cache des donnees
d'entree (API et fichiers custom). Aucun lien avec les simulations.

.. code-block:: sql

   CREATE TABLE entries (
       id          INTEGER PRIMARY KEY,
       variable    VARCHAR,           -- dem, geology, hydrometry, recharge...
       source      VARCHAR,           -- hubeau, sim2, ign_bdalti, custom
       station_id  VARCHAR,           -- pour les donnees ponctuelles
       bbox_xmin   DOUBLE,
       bbox_ymin   DOUBLE,
       bbox_xmax   DOUBLE,
       bbox_ymax   DOUBLE,
       crs         VARCHAR,
       date_start  VARCHAR,
       date_end    VARCHAR,
       frequency   VARCHAR,
       unit        VARCHAR,
       source_unit VARCHAR,
       file_path   TEXT,              -- chemin vers le fichier sur disque
       file_mtime  DOUBLE,
       created_at  TIMESTAMP DEFAULT now(),
       is_custom   INTEGER,
       fetch_metadata JSON
   );

Ce fichier peut etre supprime et reconstruit a tout moment en re-fetchant les donnees.
Il ne contient que des metadonnees + des chemins vers des fichiers dans ``data/``.

6. Pipeline d'execution
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   hmp run config.toml
   │
   ├─ Phase 1 : Setup
   │  ├─ Lecture et validation du TOML (HydroModPyConfig)
   │  ├─ Connexion a hydromodpy.duckdb
   │  └─ Resolution du workspace (auto-decouverte)
   │
   ├─ Phase 2 : Geographic preprocessing
   │  ├─ Pipeline WhiteboxTools en memoire (breach → D8 → accumulation → watershed)
   │  ├─ Stockage des features dans hydromodpy.duckdb (geographic_features)
   │  ├─ Stockage des rasters dans <basename>.zarr/geographic/
   │  └─ Rien sur disque (sauf option write_intermediates pour debug)
   │
   ├─ Phase 3 : Chargement des donnees
   │  ├─ DataManagersRuntimeLoader charge depuis data/ et APIs
   │  ├─ Enregistrement dans data/cache.duckdb
   │  └─ Donnees chargees en memoire (LoadResult)
   │
   ├─ Phase 4 : Registration
   │  ├─ generation sim_id (UUID)
   │  ├─ INSERT INTO simulations (status = 'running')
   │  ├─ INSERT INTO parameters (normalise depuis le TOML)
   │  ├─ INSERT INTO provenance (fingerprints des donnees d'entree)
   │  └─ Creation du dossier simulations/<basename>.zarr/
   │
   ├─ Phase 5 : Execution solver
   │  ├─ Creation de .solver_scratch/<uuid>/ (temporaire)
   │  ├─ Adapter FloPy ecrit les inputs MODFLOW
   │  ├─ MODFLOW resout → .hds, .cbc
   │  ├─ Extraction → hydromodpy.duckdb (timeseries, budgets, mass_balance, metrics)
   │  ├─ Extraction → <basename>.zarr/ (head, budget spatial)
   │  ├─ Calcul des derived → <basename>.zarr/derived/
   │  ├─ Suppression de .solver_scratch/<uuid>/
   │  └─ Repetition pour chaque process (flow → transport)
   │
   ├─ Phase 6 : Finalisation
   │  ├─ UPDATE simulations SET status = 'completed', duration_s = ...
   │  └─ Fermeture des connexions
   │
   └─ Phase 7 : Export a la demande (optionnel)
      ├─ Configure dans [simulation.results.export] du TOML
      ├─ Ou via API Python : sim.to_netcdf("head")
      └─ Formats : NetCDF-4/UGRID, CSV, GeoTIFF, VTU, Shapefile

7. API Python
~~~~~~~~~~~~~

Trois niveaux d'abstraction. L'utilisateur ne manipule jamais DuckDB directement
sauf s'il le souhaite.

7.1. SimulationCatalog : point d'entree
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   import hydromodpy as hmp

   catalog = hmp.open("~/workspace")

Explorer les simulations :

.. code-block:: python

   catalog.simulations                                    # DataFrame de toutes les sims
   catalog.find(project="canut", solver="modflow6")       # filtres nommes
   catalog.find(nse_gt=0.7, tags="transient")             # seuils sur metriques

Acceder a une simulation :

.. code-block:: python

   sim = catalog["<uuid>"]                                # par UUID
   sim = catalog.latest("canut")                          # derniere completee du projet
   sim = catalog.best("canut", metric="nse")              # meilleure NSE du projet

Gerer les simulations :

.. code-block:: python

   catalog.delete("<uuid>")                               # supprime DB + Zarr
   catalog.delete(project="canut", status="failed")       # suppression groupee
   catalog.cleanup(older_than="2025-01-01")               # nettoyage par date
   catalog.cleanup(status="failed")                       # nettoyage par statut

Import / export :

.. code-block:: python

   catalog.export_package("<uuid>", "~/partage/canut_best.hmp")
   catalog.import_package("~/partage/colleague_run.hmp")

SQL direct (power users, ML) :

.. code-block:: python

   catalog.sql("SELECT project, solver, AVG(m.value) ...")   # → DataFrame
   catalog.connection                                         # → duckdb.DuckDBPyConnection

7.2. Simulation : une simulation individuelle
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Metadata :

.. code-block:: python

   sim = catalog.best("nancon", metric="nse")

   sim.id                        # UUID
   sim.name                      # nom du run
   sim.project                   # "nancon"
   sim.solver                    # "modflow6"
   sim.solver_category           # "distributed"
   sim.flow_regime               # "transient"
   sim.status                    # "completed"
   sim.created_at                # datetime
   sim.duration_s                # temps d'execution
   sim.config                    # dict (TOML snapshot complet)
   sim.tags                      # ["transient", "sensitivity_K"]
   sim.parameters                # DataFrame {param_name, zone_id, value, unit}
   sim.metrics                   # DataFrame {station_id, metric_name, value}
   sim.provenance                # DataFrame {variable, source, checksum}

Donnees :

.. code-block:: python

   sim.timeseries("head", station="P01")               # → pd.Series
   sim.timeseries("discharge", station="_catchment")    # → pd.Series
   sim.budget(component="recharge")                     # → DataFrame
   sim.mass_balance                                     # → DataFrame

   sim.field("head", timestep=12)                       # → ndarray (n_layers, n_cells)
   sim.field("watertable_depth", timestep=-1)           # → ndarray (dernier pas de temps)
   sim.mesh                                             # → MeshAccessor (vertices, connectivity)

Export cible (chaque methode retourne un Path) :

.. code-block:: python

   sim.to_netcdf("head")                                # → head.nc (UGRID CF-compliant)
   sim.to_netcdf(["head", "watertable_depth"])           # multi-variable
   sim.to_geotiff("watertable_depth", timestep=-1, resolution=50)
   sim.to_shapefile("watertable_depth", timestep=-1)
   sim.to_csv()                                          # toutes les timeseries
   sim.to_vtu("head", timestep=12)                       # ParaView

Export geographic :

.. code-block:: python

   sim.geographic("watershed").to_file("~/export/mask.shp")
   sim.geographic("watershed").to_file("~/export/mask.gpkg")    # GeoPackage aussi
   sim.geographic("river_network").to_file("~/export/rivers.gpkg")
   sim.geographic_raster("dem").to_geotiff("~/export/dem.tif")
   sim.mesh.to_geodataframe()                            # cellules comme polygones GeoDataFrame

Figures a la demande :

.. code-block:: python

   sim.display_capabilities                              # → ['watertable_map', 'cross_section', ...]
   sim.plot("watertable_map")                            # affiche la figure
   sim.plot("watertable_map", save="~/figures/")         # sauvegarde PNG
   sim.plot_all(save="~/figures/")                       # toutes les figures compatibles

Reproduction :

.. code-block:: python

   from hydromodpy import Project

   Project.rerun(sim)                                   # relance avec la meme config
   Project.rerun(sim, K=2.0, Sy=0.1)                    # relance avec overrides

Export complet (package portable) :

.. code-block:: python

   sim.export("~/partage/nancon_best.hmp")
   # cree un dossier contenant simulation.duckdb + results.zarr/
   # le destinataire fait : catalog.import_package("nancon_best.hmp")

7.3. SimulationGroup : operations groupees
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   group = catalog.find(project="canut", status="completed")

   group.count                                           # nombre de simulations
   group.parameters                                      # DataFrame pivot (sim_id x param)
   group.metrics                                         # DataFrame pivot (sim_id x metric)
   group.compare(metric="nse")                           # tableau comparatif trie
   group.best(metric="nse")                              # → Simulation
   group.worst(metric="nse")                             # → Simulation
   group.sort_by("nse", ascending=False)                 # tri

ML-ready :

.. code-block:: python

   df = group.to_dataframe()
   # colonnes : sim_id, K, Sy, Ss, nse, kge, rmse, solver, n_cells, project...
   # directement utilisable par sklearn / pytorch

Comparaison inter-bassins :

.. code-block:: python

   canut  = catalog.find(project="canut",  status="completed")
   nancon = catalog.find(project="nancon", status="completed")

   hmp.compare_groups(canut, nancon, by="param_name", metric="nse")
   # → DataFrame croise : param x bassin x metric

8. Display pipeline solver-agnostique
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Le display ne connait pas le solver. Il connait :

- ``solver_category`` (distributed / integrated) pour les figures incompatibles
- la **presence** des variables dans le Zarr pour les capabilities

.. code-block:: python

   def get_display_capabilities(sim_metadata, zarr_store):
       caps = ["watertable_map", "budget_chart"]

       if sim_metadata.n_layers > 1:           # distributed seulement
           caps.append("cross_section")

       if sim_metadata.flow_regime == "transient":
           caps.extend(["streamflow", "head_timeseries", "drainage_density"])

       if "concentration" in zarr_store:       # transport disponible
           caps.append("concentration_map")

       if "pathlines" in zarr_store:           # MODPATH disponible
           caps.append("pathlines")

       return caps

Figures communes a tous les solvers :

- watertable_map (elevation + profondeur)
- state_triptych (topographie / head / depth)
- budget_chart (bilan par composante)
- recharge_discharge_cumulative

Figures distributed (n_layers > 1) uniquement :

- cross_section (coupe verticale)

Figures transient uniquement :

- streamflow (debit simule vs observe)
- head_timeseries (chronique piezometrique)
- drainage_density (reseau perenne vs intermittent)
- persistency_map (indice de duree d'ecoulement)

Figures conditionnelles :

- concentration_map (si transport actif)
- pathlines (si MODPATH/particules)

9. Calibration
~~~~~~~~~~~~~~

9.1. Execution (rapide, en memoire)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

L'optimiseur tourne sans toucher la DB. Toutes les iterations restent en RAM
(ou en fichiers temporaires locaux si necessaire pour la memoire).

.. code-block:: text

   CalibrationEngine.run()
   ├── iteration 1 : eval(K=1.0, Sy=0.05) → NSE=0.65     # en memoire
   ├── iteration 2 : eval(K=1.5, Sy=0.03) → NSE=0.72     # en memoire
   ├── ...
   ├── iteration N : eval(K=1.8, Sy=0.04) → NSE=0.85     # en memoire
   └── terminaison (convergence ou max_iter)

9.2. Persistance (a la fin, en bulk)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   session.persist(catalog)

Operations :

1. le best-run est execute comme une simulation normale → ligne dans ``simulations``
2. ``INSERT INTO calibration_sessions`` (1 ligne)
3. ``INSERT INTO calibration_iterations`` (N lignes, bulk insert)
4. la simulation du best-run a ``parent_sim_id`` qui reference la session

9.3. Analyse post-hoc
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   session = catalog.calibration_session("<session_id>")
   session.iterations                    # → DataFrame (iteration, parameters, objective, metrics)
   session.best_parameters               # → dict {K: 1.8, Sy: 0.04}
   session.convergence_curve             # → Series (iteration → objective)
   session.best_simulation               # → Simulation (acces complet aux resultats)

.. code-block:: sql

   -- Analyse directe en SQL
   SELECT iteration, objective_value,
          json_extract(parameters, '$.K') AS K,
          json_extract(parameters, '$.Sy') AS Sy
   FROM calibration_iterations
   WHERE session_id = '<session_id>'
   ORDER BY objective_value;

10. Import / export de simulations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

10.1. Format du package .hmp
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Un package ``.hmp`` est un dossier contenant tout le necessaire pour
reconstituer une simulation dans un autre workspace.

.. code-block:: text

   nancon_best.hmp/
   ├── simulation.duckdb              # sous-ensemble de hydromodpy.duckdb
   │   ├── simulations (1 ligne)
   │   ├── parameters
   │   ├── timeseries
   │   ├── budgets
   │   ├── mass_balance
   │   ├── metrics
   │   ├── observation_points
   │   ├── provenance
   │   ├── geographic_features
   │   └── geographic_metadata
   └── results.zarr/                  # copie du <basename>.zarr/
       ├── mesh/
       ├── head/
       ├── derived/
       └── geographic/

10.2. Export
^^^^^^^^^^^^

.. code-block:: python

   sim.export("~/partage/nancon_best.hmp")

Internally :

1. ``CREATE`` un nouveau DuckDB temporaire
2. ``ATTACH hydromodpy.duckdb AS src``
3. pour chaque table : ``CREATE TABLE ... AS SELECT * FROM src.{table} WHERE sim_id = ?``
4. ``geographic_features`` et ``geographic_metadata`` : filtre par ``project``
5. copie du dossier Zarr (``shutil.copytree``) ou de l'archive ``.zarr.zip``

10.3. Import
^^^^^^^^^^^^

.. code-block:: python

   catalog.import_package("~/partage/nancon_best.hmp")

Internally :

1. ``ATTACH simulation.duckdb AS pkg``
2. pour chaque table : ``INSERT INTO {table} SELECT * FROM pkg.{table}``
3. verification : si ``sim_id`` existe deja, erreur (ou option ``force=True``)
4. copie du Zarr dans ``simulations/<basename>.zarr/`` ou ``.zarr.zip``
5. mise a jour de ``zarr_path`` dans la ligne importee

11. Concurrence et robustesse
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

11.1. Ecritures pendant l'execution
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Les ecritures dans ``hydromodpy.duckdb`` se font **apres** le solver, pas pendant :

1. ``register_simulation`` : 1 INSERT (rapide)
2. solver execute (aucune ecriture DB)
3. extraction : N INSERTs timeseries + budgets (sequentiel par simulation)
4. finalize : 1 UPDATE (rapide)

Si deux simulations terminent l'extraction au meme moment, DuckDB serialise
les ecritures via le WAL (Write-Ahead Log). Latence : quelques millisecondes.

11.2. Batch parallele
^^^^^^^^^^^^^^^^^^^^^

Pour les campagnes batch (10+ simulations paralleles), si la serialisation
WAL devient un goulot :

- option 1 : ecriture dans un DuckDB temporaire par simulation, merge a la fin
- option 2 : les ecritures post-solver sont naturellement decalees dans le temps

En pratique, avec des solveurs qui prennent des minutes a des heures,
la fenetre de collision est negligeable.

11.3. Corruption
^^^^^^^^^^^^^^^^

DuckDB utilise le WAL avec checkpoints periodiques. En cas de crash :

- le WAL est rejoue au prochain ``duckdb.connect()``
- les transactions non commitees sont perdues (= le run en cours)
- les simulations deja finalisees sont intactes

Backup : un simple ``cp hydromodpy.duckdb hydromodpy.duckdb.bak`` suffit.

12. Reproductibilite
~~~~~~~~~~~~~~~~~~~~

Chaque simulation stocke :

.. list-table::
   :header-rows: 1

   * - Donnee
     - Table
     - Champ
   * - Config TOML complete
     - simulations
     - config_toml (JSON)
   * - Hash de config (dedup)
     - simulations
     - config_hash (SHA-256)
   * - Parametres normalises
     - parameters
     - param_name, value, unit
   * - Empreinte des donnees d'entree
     - provenance
     - checksum (SHA-256), stats
   * - Hash du mesh
     - simulations
     - mesh_hash (SHA-256)
   * - Filiation
     - simulations
     - parent_sim_id

Pour relancer une simulation :

.. code-block:: python

   from hydromodpy import Project

   sim = catalog["<uuid>"]
   new_sim = Project.rerun(sim)                    # meme config, memes parametres
   new_sim = Project.rerun(sim, K=2.0)             # override d'un parametre

``Project.rerun()`` reconstruit la configuration depuis le snapshot stocke,
applique ``config_overrides`` si fourni, transmet les overrides de parametres au
run, lance une nouvelle simulation, et enregistre ``parent_sim_id`` vers
l'originale. Le ``Run`` reste une vue de lecture sur les resultats ; il ne relance
pas lui-meme le workflow.

Migration API :

- ancienne forme retiree : ``sim.rerun(...)``,
- nouvelle forme : ``Project.rerun(sim, ...)``,
- raison : eviter que la couche ``results`` importe l'orchestrateur ``Project``.

13. Ce qui disparait par rapport a l'architecture precedente
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Supprime
     - Raison
   * - ``project.duckdb`` (par projet)
     - Fusionne dans ``hydromodpy.duckdb``
   * - ``simulation_registry`` dans catalog.duckdb
     - Dead code (jamais lu). Requetes cross-sim natives maintenant
   * - ``catalog.duckdb`` (double role)
     - Remplace par ``data/cache.duckdb`` (scope reduit)
   * - Concept de projet = dossier
     - Projet = label dans ``simulations.project``
   * - ``project_results.zarr.db`` (multi-sim par projet)
     - Un Zarr par simulation (isolation)
   * - JSONL de calibration sur disque
     - Tables ``calibration_*`` dans DuckDB
   * - CSV d'agregation batch
     - Requetes SQL sur les simulations taguees
   * - ``geographic_features.geometry_wkb``
     - Redondant avec ``geojson``
   * - ``results_stable/``
     - Geographic → DB + memoire
   * - ``results_simulations/``
     - ``.solver_scratch/`` (temp) + DB
   * - ``results_calibration/``
     - simulations avec ``parent_sim_id``

14. Evolutivite et versioning du schema
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

14.1. Principe
^^^^^^^^^^^^^^

Le schema est concu pour evoluer par **additions**, jamais par modifications destructives.
Les evolutions possibles :

- ``CREATE TABLE`` : ajouter une table (zero impact sur l'existant)
- ``ALTER TABLE ADD COLUMN`` : ajouter une colonne (les lignes existantes ont NULL)
- nouvelles valeurs dans les colonnes VARCHAR (solver, param_name, metric_name)
- nouveaux dossiers dans le Zarr (schema-less)

Les evolutions interdites (cassent la compatibilite) :

- renommer ou supprimer une colonne existante
- changer le type d'une colonne
- modifier la cle primaire de ``simulations``

14.2. Table de version interne
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: sql

   CREATE TABLE _schema_version (
       version    INTEGER NOT NULL,
       applied_at TIMESTAMP DEFAULT now()
   );
   INSERT INTO _schema_version VALUES (1, now());

A chaque ouverture de ``hydromodpy.duckdb``, le code verifie la version et applique
les migrations necessaires.

14.3. Registre de migrations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   LATEST_VERSION = 1

   MIGRATIONS = {
       # version: liste de statements SQL a executer
       # 1: [],  # schema initial, pas de migration
       # 2: [
       #     "ALTER TABLE simulations ADD COLUMN hmp_version VARCHAR",
       #     "CREATE TABLE sensitivity_indices (...)",
       # ],
       # 3: [
       #     "ALTER TABLE simulations ADD COLUMN mesh_n_nodes INTEGER",
       #     "CREATE TABLE ensemble_runs (...)",
       # ],
   }

   def ensure_schema(conn: duckdb.DuckDBPyConnection):
       current = conn.execute("SELECT MAX(version) FROM _schema_version").fetchone()[0]
       if current >= LATEST_VERSION:
           return
       for v in range(current + 1, LATEST_VERSION + 1):
           for stmt in MIGRATIONS[v]:
               conn.execute(stmt)
           conn.execute(
               "INSERT INTO _schema_version VALUES (?, now())", [v]
           )

L'historique des migrations est conserve dans ``_schema_version`` (une ligne par version
appliquee avec timestamp). Permet de savoir quel schema utilise un fichier partage.

14.4. Compatibilite import/export
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Le package ``.hmp`` embarque la version du schema :

.. code-block:: python

   def export_package(sim_id, output_path):
       # ...
       # copie aussi _schema_version dans le package
       conn.execute("CREATE TABLE _schema_version AS SELECT * FROM src._schema_version")

A l'import, si le package a une version plus recente que le workspace :

.. code-block:: python

   def import_package(package_path):
       pkg_version = ...  # lire depuis package
       local_version = ... # lire depuis hydromodpy.duckdb
       if pkg_version > local_version:
           raise IncompatibleSchemaError(
               f"Le package utilise le schema v{pkg_version}, "
               f"ce workspace est en v{local_version}. "
               f"Mettez a jour HydroModPy."
           )
       # si pkg_version <= local_version : import normal, les colonnes manquantes = NULL

14.5. Colonnes cle-valeur : extensibilite sans migration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Les tables ``parameters`` et ``metrics`` utilisent un schema **vertical** (cle-valeur).
Ajouter un nouveau parametre ou une nouvelle metrique ne necessite aucune migration :

.. code-block:: text

   -- Avant (v1) : K et Sy
   parameters: (sim_id, 'K', 1.728), (sim_id, 'Sy', 0.05)

   -- Apres (v1, aucune migration) : on ajoute porosite et dispersivite
   parameters: (sim_id, 'K', 1.728), (sim_id, 'Sy', 0.05),
               (sim_id, 'porosity', 0.15), (sim_id, 'dispersivity', 2.5)

Idem pour ``metrics`` : ajouter KGE', 'pbias', 'volume_error' ne touche pas au schema.

Si un jour on a besoin de metadata sur les noms (unite par defaut, sens de l'optimum),
une table de reference optionnelle peut etre ajoutee :

.. code-block:: sql

   -- Migration v2
   CREATE TABLE metric_definitions (
       metric_name  VARCHAR PRIMARY KEY,
       display_name VARCHAR,
       direction    VARCHAR,     -- 'higher_is_better' ou 'lower_is_better'
       default_unit VARCHAR
   );

   INSERT INTO metric_definitions VALUES
       ('nse',   'Nash-Sutcliffe',  'higher_is_better', '-'),
       ('kge',   'Kling-Gupta',     'higher_is_better', '-'),
       ('rmse',  'RMSE',            'lower_is_better',  'm'),
       ('pbias', 'Percent Bias',    'lower_is_better',  '%');

``catalog.best()`` utilise ``direction`` pour choisir MAX ou MIN automatiquement.
Les simulations existantes ne sont pas affectees.

14.6. JSON blobs : flexibilite vs queryabilite
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Certaines colonnes utilisent JSON pour absorber les cas imprevisibles :

.. list-table::
   :header-rows: 1

   * - Colonne
     - Pourquoi JSON
     - Risque
   * - ``simulations.config_toml``
     - snapshot TOML complet, structure variable
     - trop gros pour normaliser
   * - ``calibration_iterations.parameters``
     - N parametres variables par session
     - nombre de params inconnu a l'avance
   * - ``calibration_iterations.metrics``
     - metriques variables par iteration
     - idem
   * - ``provenance.stats``
     - {mean, min, max, std}
     - schema fixe mais optionnel
   * - ``geographic_features.properties``
     - attributs GeoDataFrame variables
     - depend du jeu de donnees

Le JSON est queryable en DuckDB via ``json_extract()`` :

.. code-block:: sql

   SELECT json_extract(parameters, '$.K') AS K FROM calibration_iterations;

Si le JSON devient un goulot (volume ou performance), la strategie est de **materialiser**
dans une table normalisee sans supprimer le JSON :

.. code-block:: sql

   -- Migration vN : materialiser les parametres de calibration
   CREATE TABLE calibration_iteration_params (
       session_id UUID,
       iteration  INTEGER,
       param_name VARCHAR,
       value      DOUBLE,
       PRIMARY KEY (session_id, iteration, param_name)
   );
   -- remplir depuis le JSON existant
   INSERT INTO calibration_iteration_params
   SELECT session_id, iteration, key, CAST(value AS DOUBLE)
   FROM calibration_iterations, json_each(parameters);

Le JSON original reste comme archive. La table normalisee sert aux requetes.

14.7. Zarr : evolution libre
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Zarr est schema-less. Ajouter une variable spatiale = creer un dossier :

.. code-block:: text

   <basename>.zarr/
   ├── head/                    # v1
   ├── derived/                 # v1
   ├── velocity/                # v2 : nouveau, aucune migration
   └── thermal/                 # v3 : nouveau, aucune migration

Les anciennes simulations n'ont pas ces dossiers. Le code verifie la presence
avant de lire :

.. code-block:: python

   def field(self, variable, timestep):
       if variable not in self._zarr_root:
           raise VariableNotFound(f"'{variable}' absent de cette simulation")
       return self._zarr_root[variable][timestep][:]

Pas de schema a migrer, pas de version a gerer cote Zarr.

14.8. Scenarios d'evolution concrets
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Besoin futur
     - Type de changement
     - Migration
   * - Nouveau solver (FEFLOW, PFLOTRAN)
     - Nouvelle valeur dans ``simulations.solver``
     - Aucune
   * - Nouveau process (thermique)
     - Nouveau dossier Zarr + entrees dans ``parameters``
     - Aucune
   * - Version HydroModPy
     - ``ALTER TABLE simulations ADD COLUMN hmp_version VARCHAR``
     - v2
   * - Ensemble / Monte Carlo
     - ``CREATE TABLE ensemble_runs (ensemble_id, sim_id, weight)``
     - v2
   * - Scoring multi-objectif
     - ``CREATE TABLE pareto_fronts (front_id, sim_id, rank)``
     - v2
   * - Metadata utilisateur libre
     - ``ALTER TABLE simulations ADD COLUMN user_metadata JSON``
     - v2
   * - Spatial indexing (R-tree)
     - Extension DuckDB ``spatial`` (pas de DDL)
     - Aucune
   * - Series observees dans la DB
     - ``ALTER TABLE timeseries ADD COLUMN source VARCHAR DEFAULT 'simulated'``
     - v2
   * - Multi-workspace (cloud)
     - Le ``.hmp`` package est deja portable
     - Aucune
   * - Versionning du config TOML
     - ``ALTER TABLE simulations ADD COLUMN schema_version INTEGER DEFAULT 1``
     - v2
   * - Normaliser les params calibration
     - ``CREATE TABLE calibration_iteration_params (...)``
     - vN

Regle : **aucun de ces scenarios ne necessite de reecrire une table existante
ou de modifier des donnees deja stockees.**

14.9. Engagement de stabilite
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Les elements suivants sont geles et ne changeront pas :

.. list-table::
   :header-rows: 1

   * - Element
     - Garantie
   * - ``simulations.sim_id`` (UUID, PK)
     - Cle universelle, jamais modifiee
   * - FK ``sim_id`` dans toutes les tables
     - Jointure standard, jamais modifiee
   * - Nom du fichier ``hydromodpy.duckdb``
     - Point d'entree unique
   * - Structure ``simulations/<basename>.zarr/`` ou ``.zarr.zip``
     - Un artefact Zarr par simulation
   * - Noms des tables existantes
     - Jamais renommees, jamais supprimees
   * - Colonnes existantes
     - Jamais renommees, jamais supprimees

Tout le reste peut evoluer via le systeme de migrations.

15. Requetes SQL de reference
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Lister les simulations d'un bassin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: sql

   SELECT sim_id, name, solver, status, duration_s, created_at
   FROM simulations
   WHERE project = 'canut'
   ORDER BY created_at DESC;

Comparer les metriques entre solveurs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: sql

   SELECT s.solver, AVG(m.value) AS mean_nse, MIN(m.value), MAX(m.value)
   FROM simulations s
   JOIN metrics m USING (sim_id)
   WHERE s.project = 'canut'
     AND s.status = 'completed'
     AND m.metric_name = 'nse'
   GROUP BY s.solver;

Plage de parametres produisant de bons resultats
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: sql

   SELECT
       ROUND(p.value, 1) AS K_bin,
       COUNT(*) AS n_runs,
       AVG(m.value) AS avg_nse,
       MIN(m.value) AS min_nse,
       MAX(m.value) AS max_nse
   FROM parameters p
   JOIN metrics m ON p.sim_id = m.sim_id AND m.metric_name = 'nse'
   WHERE p.param_name = 'K' AND p.zone_id IS NULL
   GROUP BY K_bin
   ORDER BY avg_nse DESC;

Comparaison inter-bassins
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: sql

   SELECT
       s.project,
       p.param_name,
       AVG(p.value) AS mean_value,
       STDDEV(p.value) AS std_value,
       MAX(m.value) AS best_nse
   FROM simulations s
   JOIN parameters p USING (sim_id)
   JOIN metrics m USING (sim_id)
   WHERE s.status = 'completed'
     AND m.metric_name = 'nse'
     AND p.zone_id IS NULL
   GROUP BY s.project, p.param_name
   ORDER BY s.project, p.param_name;

DataFrame ML-ready
^^^^^^^^^^^^^^^^^^

.. code-block:: sql

   SELECT
       s.sim_id, s.project, s.solver, s.n_cells, s.flow_regime,
       MAX(CASE WHEN p.param_name = 'K'  THEN p.value END) AS K,
       MAX(CASE WHEN p.param_name = 'Sy' THEN p.value END) AS Sy,
       MAX(CASE WHEN p.param_name = 'Ss' THEN p.value END) AS Ss,
       MAX(CASE WHEN m.metric_name = 'nse'  THEN m.value END) AS nse,
       MAX(CASE WHEN m.metric_name = 'kge'  THEN m.value END) AS kge,
       MAX(CASE WHEN m.metric_name = 'rmse' THEN m.value END) AS rmse
   FROM simulations s
   LEFT JOIN parameters p ON s.sim_id = p.sim_id AND p.zone_id IS NULL
   LEFT JOIN metrics m ON s.sim_id = m.sim_id
   WHERE s.status = 'completed'
   GROUP BY s.sim_id, s.project, s.solver, s.n_cells, s.flow_regime;

Convergence d'une calibration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: sql

   SELECT
       iteration,
       objective_value,
       json_extract(parameters, '$.K') AS K,
       json_extract(parameters, '$.Sy') AS Sy
   FROM calibration_iterations
   WHERE session_id = '<session_id>'
   ORDER BY iteration;

Detecter les runs dupliques
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: sql

   SELECT config_hash, COUNT(*) AS n_duplicates, ARRAY_AGG(sim_id) AS sim_ids
   FROM simulations
   WHERE status = 'completed'
   GROUP BY config_hash
   HAVING COUNT(*) > 1;
