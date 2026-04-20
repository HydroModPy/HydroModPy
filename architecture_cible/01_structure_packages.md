# Architecture cible HydroModPy — Structure des packages

**Auteur** : Architecte logiciel senior (références : scikit-learn, xarray, FloPy, dask).
**Branche de référence** : `dev-database` (post-merge `dev-refact`, HEAD `74b62878`).
**Date** : 2026-04-18.
**Portée** : conception IDÉALE de la hiérarchie de packages. Pas un patch.
**Sources** : 11 rapports d'audit (`audit_code/01_..` à `11_synthese_finale.md`).

> **Intention** : proposer une structure où (a) chaque package a UNE responsabilité, (b) le DAG d'import est acyclique et document-généré, (c) un nouveau contributeur comprend le projet en moins de 5 minutes, (d) l'ajout d'un solveur, d'une variable, d'un format d'export ou d'un workflow touche **un seul package**.

---

## Table des matières

1. [Principes directeurs](#1-principes-directeurs)
2. [Arbre complet du package `hydromodpy/`](#2-arbre-complet-du-package-hydromodpy)
3. [Graphe de dépendances autorisé](#3-graphe-de-dépendances-autorisé)
4. [API publique `hmp.*`](#4-api-publique-import-hydromodpy-as-hmp)
5. [Points d'entrée CLI `hmp`](#5-points-dentrée-cli-hmp)
6. [Tableau de migration actuel → cible](#6-tableau-de-migration-actuel--cible)
7. [Conventions de nommage et organisation](#7-conventions-de-nommage-et-organisation)
8. [Schémas de structures techniques critiques](#8-schémas-de-structures-techniques-critiques)
9. [Annexe — exemples de code squelette](#9-annexe--exemples-de-code-squelette)

---

## 1. Principes directeurs

| # | Principe | Conséquence pratique |
|---|---|---|
| 1 | **Une responsabilité par package** | Un package ne cumule pas « configuration + parsing + exécution ». Cf. `sklearn.preprocessing` ≠ `sklearn.pipeline`. |
| 2 | **DAG strict, pas de cycle** | Les dépendances inter-packages se lisent en haut→bas. Vérifié par un test `test_import_graph_is_dag.py`. |
| 3 | **`core/` est une feuille** | `core/` n'importe AUCUN autre package `hydromodpy.*`. C'est l'infrastructure brute (logging, unités, chemins, registres). |
| 4 | **Extension sans modification** | Ajouter un solveur = ajouter UN fichier dans `solver/<nom>/`. Ajouter un exporteur = UN fichier dans `results/io/exporters/`. Ajouter une variable = UN sous-dossier dans `data/variables/`. |
| 5 | **Profondeur maximale 4 niveaux** | Aucun chemin d'import > `hmp.a.b.c.d`. FloPy arrête à 3, HydroModPy actuel va à 6. |
| 6 | **Nommage scientifique explicite** | Pas de `common/`, `utils/`, `helpers/`, `misc/`, `tools/`. Préférer le nom du domaine : `linear_algebra.py`, `raster_io.py`, `crs.py`. |
| 7 | **Modules de convention stable** | `foo_config.py` (Pydantic), `foo_manager.py` (variable loader), `foo_schema.py` (SQL DuckDB), `foo_api.py` (façade publique). |
| 8 | **Pas de `cases/` dans le runtime** | Les scripts de démonstration / benchmarks vivent à la racine du repo (`validation_cases/`, `examples/`), JAMAIS dans les sous-packages. |
| 9 | **API publique minimale et stable** | `import hydromodpy as hmp` n'expose qu'une vingtaine d'objets. Le reste se documente sous-package par sous-package. |
| 10 | **Un seul orchestrateur par workflow** | La collision actuelle `project.py` ↔ `workflow/pipelines/` ↔ `runners/` est supprimée : chaque verbe CLI a une seule façade. |

---

## 2. Arbre complet du package `hydromodpy/`

> Conventions : le symbole en préfixe désigne le statut : **[C]** conservé, **[R]** renommé, **[D]** déplacé, **[F]** refactoré, **[N]** nouveau, **[K]** supprimé (tué — n'apparaît pas, mentionné §6).

```
hydromodpy/
│
├── [F] __init__.py                 Lazy imports PEP 562. API publique ≤ 25 symboles.
├── [R] _cli/                       CLI argparse (ex-__main__.py monolithe).
│   ├── __init__.py                 Parser racine, dispatch, --version, argcomplete.
│   ├── main.py                     Point d'entrée (≤ 80 l.) — installé comme `hmp`/`hydromodpy`.
│   ├── commands/
│   │   ├── __init__.py             Registre des verbes.
│   │   ├── init_cmd.py             `hmp init` — crée workspace.
│   │   ├── new_cmd.py              `hmp new` — crée projet.
│   │   ├── config_cmd.py           `hmp config` — template TOML profilé.
│   │   ├── run_cmd.py              `hmp run` — dispatch workflow via TOML sections.
│   │   ├── display_cmd.py          `hmp display` — post-hoc figures.
│   │   ├── list_cmd.py             `hmp list` — inventaire workspace.
│   │   ├── export_cmd.py           `hmp export` — export portable `.hmp`.
│   │   ├── inspect_cmd.py          `hmp inspect <sim_id>` — dump metadata (NOUVEAU).
│   │   └── version_cmd.py          `hmp --version` (NOUVEAU).
│   └── completion.py               Support `argcomplete` (NOUVEAU).
│
├── [F] core/                       INFRASTRUCTURE FEUILLE. N'importe rien de hydromodpy.*.
│   ├── __init__.py                 Exports publics : Workspace, HydroModPyConfig.
│   │
│   ├── config/                     Pydantic models racine + chargement TOML.
│   │   ├── __init__.py
│   │   ├── aggregate_config.py     HydroModPyConfig (ex-hydromodpy_config.py). Plus d'imports métier.
│   │   ├── loader.py               from_toml(path), to_toml(path, profile).
│   │   ├── param_level.py          ParamLevel (USER/DEV/EXPERT) + Field(json_schema_extra).
│   │   ├── template.py             Génération du template TOML par profil.
│   │   └── introspect.py           Helpers Pydantic (parcours récursif, extraction doc).
│   │
│   ├── workspace/                  Layout workspace + discovery.
│   │   ├── __init__.py             Workspace, WorkspaceConfig, PathRegistry.
│   │   ├── workspace.py            Workspace (lifecycle, lazy DB open).
│   │   ├── workspace_config.py     WorkspaceConfig Pydantic.
│   │   ├── discovery.py            discover_workspace_root(cwd).
│   │   └── path_registry.py        PathRegistry : chemins canoniques.
│   │
│   ├── state/                      Contexte de run partagé (frozen dataclasses).
│   │   ├── __init__.py
│   │   ├── run_context.py          RunContext (unique, plat — remplace triple WorkflowContext).
│   │   ├── setup_context.py        SetupContext : objets structurels immutables.
│   │   └── execution_registry.py   ExecutionRegistry : résultats typés par process.
│   │
│   ├── time/                       Grille et fenêtre temporelle.
│   │   ├── __init__.py
│   │   ├── time_grid.py            TimeGrid (PeriodIndex + substeps).
│   │   ├── window.py               ResolvedSimulationTimeWindow.
│   │   └── resolve.py              apply_time_window_to_tgrids().
│   │
│   ├── units/                      Unités + dimensional analysis (pint-based).
│   │   ├── __init__.py
│   │   ├── registry.py             Unit registry (pint.UnitRegistry singleton).
│   │   ├── quantities.py           Quantity types + validators.
│   │   └── constants.py            Constantes physiques (g, rho_water, etc.).
│   │
│   ├── logging/                    Logger setup.
│   │   ├── __init__.py             LogManager, get_logger().
│   │   └── formatters.py           Format console / fichier.
│   │
│   ├── io/                         Primitives I/O génériques (pas métier).
│   │   ├── __init__.py
│   │   ├── raster_io.py            read_raster / write_raster wrappers rasterio.
│   │   ├── vector_io.py            read_vector / write_vector wrappers pyogrio.
│   │   ├── crs.py                  Parsing CRS robuste (pyproj.CRS.from_user_input).
│   │   └── http_client.py          HTTPClient avec retry/backoff/timeout (Hub'Eau, BRGM, IGN).
│   │
│   ├── whitebox/                   Backend Whitebox (ex core/backends/, renommé au singulier).
│   │   ├── __init__.py
│   │   ├── backend.py              WhiteboxBackend + cache.
│   │   └── adapter.py              whitebox_workflows → API homogène.
│   │
│   ├── exceptions.py               Hiérarchie exceptions (HydroModPyError, ConfigError,
│   │                               SolverError, DataError, MeshError). UTILISÉE partout.
│   └── version.py                  __version__ (récupère metadata, fallback pyproject).
│
├── [F] data/                       COUCHE DONNÉES : entrées + cache + providers.
│   ├── __init__.py                 Exports : DataLoadPlan, DataPlanner, Hydrometry, Piezometry...
│   │
│   ├── contracts.py                Protocols : VariableManager, LoadResult.
│   ├── base_manager.py             BaseVariableManager (ABC). Suppression de data/common/.
│   │
│   ├── cache/                      Cache DuckDB des inputs.
│   │   ├── __init__.py             CacheCatalog.
│   │   ├── catalog.py              CacheCatalog (DuckDB), add/query/fingerprint.
│   │   └── schema.py               Schéma SQL + schema_version.
│   │
│   ├── planner/                    Planification des managers.
│   │   ├── __init__.py
│   │   ├── planner.py              DataPlanner (ex-DataManagersPlanner).
│   │   ├── plan.py                 DataLoadPlan (frozen dataclass).
│   │   ├── inference.py            Rules : "stream" → hydrography, "geology" → geology.
│   │   └── runtime_loader.py       Exécution du plan → LoadedDataContext.
│   │
│   ├── timeseries/                 SOURCES TIMESERIES UNIFIÉES (factorise 6 doublons).
│   │   ├── __init__.py
│   │   ├── source_config.py        TimeseriesSourceConfig (mixin Pydantic).
│   │   └── loader.py               load_timeseries(config) → pd.DataFrame.
│   │
│   ├── providers/                  Clients API externes (NOUVEAU, centralisé).
│   │   ├── __init__.py
│   │   ├── hubeau.py               Hub'Eau (hydrométrie, piézométrie).
│   │   ├── brgm.py                 BRGM (géologie, lithologie).
│   │   ├── ign.py                  IGN (DEM BD ALTI).
│   │   ├── shom.py                 SHOM (marégraphes).
│   │   └── meteofrance.py          Météo-France SIM2, DRIAS.
│   │
│   └── variables/                  UN DOSSIER PAR VARIABLE (convention stricte).
│       ├── __init__.py
│       │
│       ├── dem/                    Modèle numérique de terrain.
│       │   ├── __init__.py         Exports publics.
│       │   ├── config.py           DemConfig (Pydantic).
│       │   ├── manager.py          DemManager(BaseVariableManager).
│       │   ├── result.py           DemLoadResult dataclass.
│       │   └── providers.py        IgnBdAltiProvider, SrtmProvider (adapte `providers/`).
│       │
│       ├── geology/                Géologie / lithologie.
│       │   └── {config,manager,result,providers}.py
│       │
│       ├── hydrography/            Réseau hydrographique (rivières, ocean).
│       │   └── {config,manager,result,providers}.py
│       │
│       ├── hydrometry/             Débits aux stations.
│       │   └── {config,manager,result,providers}.py
│       │
│       ├── piezometry/             Niveaux piézométriques.
│       │   └── {config,manager,result,providers}.py
│       │
│       ├── intermittency/          Intermittence du réseau.
│       ├── oceanic/                Marées, bathymétrie.
│       ├── water_quality/          Qualité (concentrations).
│       ├── recharge/               Recharge mesurée.
│       ├── subbasin/               Découpage sous-bassins.
│       │
│       └── climatic/               Climatiques (mixins TimeseriesSource).
│           ├── __init__.py
│           ├── precipitation.py    PrecipitationManager (héritage mince).
│           ├── temperature.py
│           ├── etp.py
│           ├── radiation.py
│           ├── humidity.py
│           ├── wind.py
│           ├── runoff.py
│           └── soil_moisture.py
│
├── [F] spatial/                    DOMAINE GÉOGRAPHIQUE + MAILLAGE + CHAMPS.
│   ├── __init__.py                 Exports : Geographic, Domain, HydroMesh, FieldParam.
│   │
│   ├── geographic/                 Délinéation catchment (ex-geographic).
│   │   ├── __init__.py
│   │   ├── geographic.py           Geographic (ex-classe). Interface stable.
│   │   ├── geographic_config.py    GeographicConfig Pydantic.
│   │   ├── delineation.py          Algo délinéation (pysheds/whitebox).
│   │   ├── streams.py              Extraction réseau hydrographique.
│   │   └── subbasin.py             Subbasin structure + algorithmes.
│   │
│   ├── domain/                     Assemblage domaine de simulation.
│   │   ├── __init__.py
│   │   ├── domain.py               Domain (zones, boundaries).
│   │   ├── domain_config.py        DomainConfig Pydantic.
│   │   └── zones.py                CatchmentZonesField.
│   │
│   ├── mesh/                       HydroMesh + génération. FINI `solver/utils/mesh/`.
│   │   ├── __init__.py             HydroMesh, CellType, CellBlock, MeshConfig.
│   │   ├── hydro_mesh.py           HydroMesh (pivot structuré/non-structuré).
│   │   ├── mesh_config.py          MeshConfig + sous-modèles (CartesianCfg, GmshCfg).
│   │   ├── cartesian/              Génération cartésienne.
│   │   │   ├── __init__.py
│   │   │   ├── generator.py        build_cartesian_mesh(cfg) → HydroMesh.
│   │   │   └── layering.py         Empilement vertical (lay_proportions).
│   │   ├── gmsh/                   Génération Gmsh (ex-solver/utils/mesh/gmsh_grid/).
│   │   │   ├── __init__.py
│   │   │   ├── generator.py        build_gmsh_mesh(cfg) → HydroMesh.
│   │   │   ├── geometry.py         Primitives Gmsh (surfaces, lignes).
│   │   │   ├── refinement.py       Politique de raffinement (un seul fichier).
│   │   │   └── zones.py            Zone meshing consolidé (ex-zone_meshing/).
│   │   ├── quality.py              Contrôles qualité : CCW, angle min, aspect ratio.
│   │   ├── io.py                   Export / import (UGRID, VTU).
│   │   └── adapters.py             FloPy DIS/DISV adapters (bidirectionnels).
│   │
│   ├── fields/                     Champs spatiaux sur mesh.
│   │   ├── __init__.py             FieldParam, Aggregation.
│   │   ├── field_param.py          FieldParam (propriétés par zone).
│   │   ├── field_config.py         FieldParamConfig Pydantic (avec bornes physiques).
│   │   ├── aggregation.py          Literal["arithmetic","harmonic","geometric"] — choix explicite.
│   │   ├── geology_field.py        GeologyField (lit DataLoadPlan).
│   │   └── discretization.py       WeightedAverageFieldDiscretization corrigée.
│   │
│   └── surface.py                  Surface elevation + PreparedSurfaceSampler.
│
├── [F] physics/                    EX-`process/`. Renommé pour éviter polysémie multiprocessing.
│   ├── __init__.py                 Exports : Flow, Transport, BoundaryCondition, SourceTerm...
│   │
│   ├── base/                       Contrats abstraits physiques.
│   │   ├── __init__.py
│   │   ├── process.py              Process (ABC), ProcessSpatial (generic typed par IC).
│   │   ├── initial_condition.py    InitialCondition.
│   │   ├── boundary_condition.py   BoundaryCondition (Literal["dirichlet","neumann","robin"]).
│   │   ├── source_term.py          SourceTerm (ex-SinkSource, nom PDE standard).
│   │   └── forcing.py              ForcingBase + discriminated union (ConstantForcing | CsvForcing).
│   │
│   ├── flow/                       Écoulement souterrain.
│   │   ├── __init__.py             Flow, FlowConfig, FlowInitialConditions.
│   │   ├── flow.py                 Flow(ProcessSpatial[FlowInitialConditions]).
│   │   ├── flow_config.py          FlowConfig Pydantic.
│   │   ├── boundary_conditions.py  CHD, RIV, GHB, DRN, WEL config classes.
│   │   ├── source_terms.py         Recharge, EVT, Wells.
│   │   └── initial_conditions.py   FlowInitialConditions.
│   │
│   ├── transport/                  Transport solutés.
│   │   ├── __init__.py             Transport, TransportConfig, TransportInitialConditions.
│   │   ├── transport.py            Transport(ProcessSpatial[TransportInitialConditions]).
│   │   ├── transport_config.py     Inclut `effective_porosity` explicite (≠ Sy).
│   │   ├── boundary_conditions.py  SSM, chem BC.
│   │   └── initial_conditions.py   TransportInitialConditions.
│   │
│   └── recharge/                   Modèles recharge (ex-`process/hydrology/`, aplati).
│       ├── __init__.py
│       ├── pyhelp.py               Wrapper PyHELP.
│       └── synthetic.py            Recharge synthétique.
│
├── [F] solver/                     ADAPTATEURS DE SOLVEURS.
│   ├── __init__.py                 Exports : Modflow, Modflow6, Modpath7, Mt3dms, Boussinesq.
│   │
│   ├── base/                       Contrats abstraits solveur.
│   │   ├── __init__.py
│   │   ├── solver.py               Solver (ABC).
│   │   ├── solver_config.py        SolverConfig base.
│   │   ├── solver_engine.py        SolverEngine Protocol (structural).
│   │   └── extractor.py            ResultExtractor Protocol (remplace duck-typing).
│   │
│   ├── modflow_common/             FACTORISATION NWT + MF6.
│   │   ├── __init__.py
│   │   ├── flow_translator.py      Flow → MODFLOW packages (ex-flow_to_modflow_adapter dédupliqué).
│   │   ├── boundary_packages.py    RIV (stream), GHB (ocean), DRN avec conductance=K·A/b.
│   │   ├── forcing_discretization.py  Recharge/EVT discretization.
│   │   ├── binary_reader.py        Lecture `.hds`, `.cbc` (dédup NWT/MF6).
│   │   ├── grid.py                 Mapping HydroMesh → DIS/DISV.
│   │   └── vka_convention.py       Convention VKA unifiée (valeur absolue, pas ratio).
│   │
│   ├── modflow_nwt/                MODFLOW-NWT (FloPy).
│   │   ├── __init__.py             Modflow (alias MODFLOW-NWT), Modpath7, Mt3dms.
│   │   ├── solver.py               ModflowNwtSolver.
│   │   ├── solver_config.py
│   │   ├── translator.py           Extension de flow_translator (config NWT-specific).
│   │   ├── extractor.py            NWT result extractor.
│   │   └── modpath.py              MODPATH 7 (pas 6). Support DISV.
│   │
│   ├── modflow6/                   MODFLOW 6 (FloPy).
│   │   ├── __init__.py             Modflow6.
│   │   ├── solver.py               Modflow6Solver.
│   │   ├── solver_config.py
│   │   ├── translator.py           Extension de flow_translator (config MF6-specific).
│   │   ├── extractor.py            MF6 result extractor.
│   │   └── transport_gwt.py        MF6-GWT (transport natif MF6).
│   │
│   └── boussinesq/                 BOUSSINESQ (natif).
│       ├── __init__.py             Boussinesq.
│       ├── solver.py               BoussinesqSolver.
│       ├── solver_config.py
│       ├── discretization.py       Discrétisation spatiale + temporelle.
│       ├── formulations.py         h/h², MCP Fischer-Burmeister.
│       ├── assembly.py             Assemblage résidu + jacobien.
│       ├── jacobian.py             Jacobien semianalytique + FD (fallback test).
│       ├── runtimes.py             Local / scipy_sparse / scipy_dense / petsc (paramétré).
│       ├── forcing.py              Recharge / seepage.
│       └── extractor.py            Boussinesq result extractor.
│
├── [F] simulation/                 ORCHESTRATION : plan → run → extraction.
│   ├── __init__.py                 Exports : Simulation, SimulationPlan, SolverAdapter.
│   │
│   ├── api.py                      CLASSE PUBLIQUE Simulation (ex-project.py, ~150 l).
│   │                               Wrapper mince sur execute_simulation().
│   │
│   ├── planning/                   Construction immuable du plan.
│   │   ├── __init__.py
│   │   ├── plan.py                 SimulationPlan (frozen), ProcessRun.
│   │   ├── planner.py              SimulationPlanner (config → plan).
│   │   └── validation.py           Validation plan (dépendances, unicité, cycles).
│   │
│   ├── execution/                  Exécution du plan.
│   │   ├── __init__.py             execute_simulation() — API impérative.
│   │   ├── runner.py               SimulationRunner (boucle sur plan.runs).
│   │   ├── callbacks.py            ProcessCallbacks Protocol typé (remplace duck-typing).
│   │   └── overrides.py            Application d'overrides sans bypass du planner.
│   │
│   ├── adapters/                   SolverAdapter Protocol registry.
│   │   ├── __init__.py             SolverAdapter, register_adapter, get_adapter.
│   │   ├── base.py                 SolverAdapter Protocol + enregistrement typé.
│   │   ├── registry.py             Single source of truth (`(process_type, solver_name)`).
│   │   ├── flow_nwt.py             Flow × MODFLOW-NWT.
│   │   ├── flow_mf6.py             Flow × MODFLOW 6.
│   │   ├── flow_boussinesq.py      Flow × Boussinesq.
│   │   ├── transport_mt3dms.py     Transport × MT3DMS.
│   │   ├── transport_gwt.py        Transport × MF6-GWT.
│   │   └── particles_modpath.py    Particles × MODPATH 7.
│   │
│   ├── extraction/                 EX-`simulation/results/`. Renommé (collision `results/`).
│   │   ├── __init__.py
│   │   ├── base.py                 BaseExtractor + ExtractorContext.
│   │   ├── head_field.py           Head fields + derived (watertable, depth, seepage).
│   │   ├── budget_field.py         Budget fields (recharge, drain).
│   │   ├── timeseries.py           Station / outlet extraction.
│   │   ├── particles.py            Pathlines extraction.
│   │   └── aggregation.py          Catchment aggregation (heuristique n_per corrigée).
│   │
│   └── workflows/                  EX-`workflow/pipelines/`. UN SEUL ORCHESTRATEUR.
│       ├── __init__.py
│       ├── simulation_workflow.py  Workflow TOML [simulation] → plan → execute.
│       ├── overview_workflow.py    Workflow [overview] → fiche d'identité bassin.
│       ├── mesh_workflow.py        Workflow [mesh_catchment] → mesh-only.
│       ├── calibration_workflow.py Workflow [calibration] → boucle calibration.
│       ├── batch_workflow.py       Workflow [batch] → batch régional.
│       ├── comparison_workflow.py  Workflow [comparison] → comparaison solveurs.
│       └── dispatcher.py           detect_workflow(config) → workflow callable.
│
├── [F] results/                    CATALOGUE + STOCKAGE (DuckDB + Zarr). UNIQUE.
│   ├── __init__.py                 Exports : SimulationCatalog, Simulation, SimulationGroup.
│   │
│   ├── catalog/                    Catalogue DuckDB (ex-catalog.py 920 l. éclaté).
│   │   ├── __init__.py             SimulationCatalog.
│   │   ├── catalog.py              SimulationCatalog (~150 l. lifecycle only).
│   │   ├── writes.py               Méthodes d'écriture (register, append).
│   │   ├── queries.py              Méthodes de lecture (find, best, worst, filters).
│   │   ├── package.py              Export/import portable .hmp + manifest.json.
│   │   └── migrations.py           Versioning schéma + migrations effectives.
│   │
│   ├── schema/                     Schémas DuckDB.
│   │   ├── __init__.py             SCHEMA_VERSION.
│   │   ├── tables.py               Tables SQL avec PK complètes + FK (16 tables).
│   │   └── views.py                Vues dénormalisées (view_best_per_project, etc.).
│   │
│   ├── storage/                    Zarr par simulation.
│   │   ├── __init__.py             SimulationZarr, open_zarr.
│   │   ├── zarr_store.py           SimulationZarr (ex-zarr_store.py).
│   │   ├── spec.py                 Layout Zarr formel (paths + dtypes + attrs).
│   │   └── codecs.py               BLOSC-ZSTD, chunk strategy.
│   │
│   ├── simulation.py               Simulation (wrapper haut niveau sim_id).
│   ├── simulation_group.py         SimulationGroup (requêtes groupées, pivot ML).
│   ├── virtual_fields.py           Champs dérivés (watertable_depth, outflow_drain).
│   ├── spatial_index.py            Indexation spatiale.
│   ├── provenance.py               PROV-O provenance (inputs + environnement).
│   │
│   └── io/                         Exports / imports externes.
│       ├── __init__.py             Enregistrement auto des exporteurs.
│       ├── exporter_base.py        Exporter Protocol.
│       ├── registry.py             Registre des exporteurs (par format).
│       └── exporters/              UN EXPORTEUR PAR FORMAT.
│           ├── __init__.py
│           ├── netcdf.py           NetCDF CF-1.8 + UGRID-1.0 strict.
│           ├── geotiff.py          Cloud-Optimized GeoTIFF.
│           ├── geopackage.py       GeoPackage (remplace Shapefile en primaire).
│           ├── shapefile.py        Shapefile (conservé legacy).
│           ├── vtu.py              VTU (bug _split_cell_data corrigé).
│           ├── csv.py              CSV + datapackage.json sidecar (Frictionless Data).
│           └── waterml.py          WaterML 2.0 (NOUVEAU — stations).
│
├── [F] analysis/                   POST-TRAITEMENT : calibration, comparaison, display.
│   ├── __init__.py                 Exports calibration, display, metrics.
│   │
│   ├── metrics/                    Métriques de performance (DRY).
│   │   ├── __init__.py             nse, kge, rmse, mae, r2.
│   │   └── hydro_metrics.py        Métriques hydrologiques + IC.
│   │
│   ├── calibration/                Boucle de calibration (code solide — conservé).
│   │   ├── __init__.py
│   │   ├── engine/                 SessionState + Orchestration + IO (3409 l. éclaté).
│   │   │   ├── __init__.py
│   │   │   ├── session.py          CalibrationSession (~400 l.).
│   │   │   ├── state.py            État interne (~300 l.).
│   │   │   ├── orchestration.py    Boucle itérations.
│   │   │   ├── io.py               Persistance DuckDB + Zarr.
│   │   │   └── reporting.py        Rapports synthétiques.
│   │   ├── methods/                Méthodes (grid, latin hypercube, DREAM, PEST, etc.).
│   │   ├── objective/              Fonctions objectif.
│   │   └── templates/              Templates (ex-runners/templates/ déplacé).
│   │
│   ├── comparison/                 Comparaison multi-solveurs / multi-méthodes.
│   │   ├── __init__.py
│   │   ├── comparison.py           ComparisonRuntime (2061 l. éclaté).
│   │   ├── visuals.py              (1997 l. éclaté en modules figures/).
│   │   └── config.py               ComparisonConfig.
│   │
│   ├── batch/                      Batch régional.
│   │   ├── __init__.py
│   │   ├── batch.py                BatchRuntime (1828 l. éclaté).
│   │   └── config.py               BatchConfig.
│   │
│   ├── display/                    Figures / plots.
│   │   ├── __init__.py             DisplayConfig, suites, posthoc.
│   │   ├── config.py               DisplayConfig Pydantic.
│   │   ├── suites.py               Orchestrateur principal figures (UN SEUL).
│   │   ├── posthoc.py              Re-générer figures depuis results.
│   │   ├── theme.py                Palettes perceptuelles (Crameri 2020). PAS de `jet`.
│   │   ├── figures/                UN FICHIER PAR TYPE DE FIGURE.
│   │   │   ├── __init__.py
│   │   │   ├── flow_fields.py      Cartes de hauteur, vitesse.
│   │   │   ├── watertable.py       Cartes watertable depth.
│   │   │   ├── timeseries.py       Chroniques station / outlet.
│   │   │   ├── transport.py        Concentrations / pathlines.
│   │   │   ├── seepage.py          Aires de seepage.
│   │   │   ├── residence_times.py  Temps de résidence.
│   │   │   ├── mesh.py             Maillage + qualité.
│   │   │   └── synthesis.py        Planche synthèse (flow_synthesis).
│   │   └── cartography/            Cartographie conforme (NOUVEAU).
│   │       ├── __init__.py
│   │       ├── basemap.py          Cartopy + scalebar + north arrow.
│   │       └── crs.py              Gestion CRS pour cartes.
│   │
│   └── postprocess/                Post-traitement NetCDF / timeseries.
│       ├── __init__.py
│       ├── netcdf_writer.py        NetCDF CF-1.8 (délègue à results/io/exporters/netcdf.py).
│       └── timeseries.py           Agrégation timeseries.
│
└── tests/                          HORS PACKAGE, à la racine du repo.
    ├── unit/                       Tests unitaires (1 fichier = 1 module testé).
    ├── regression/
    │   ├── fast/                   Tier court (< 60 s total).
    │   └── extensive/              Tier long.
    ├── validation/                 Tests scientifiques (analytical, benchmarks).
    └── conftest.py                 Fixtures globales + markers auto.
```

### 2.1 Statistiques cibles

| Métrique | Actuel | Cible | Gain |
|---|---:|---:|---|
| Nombre de packages racine | 11 | **10** | `watershed/` supprimé, `workflow/` absorbé dans `simulation/workflows/` |
| Profondeur max d'import | 6 | **4** | Plus de `hmp.solver.utils.mesh.gmsh_grid.cases.xxx.planning` |
| Plus gros fichier | 3 409 l. | **≤ 800 l.** | 10 God modules éclatés |
| Ratio imports inversés | 4 | **0** | `data→analysis`, `spatial→solver`, `core→*` éliminés |
| LOC totales Python (hors tests) | ~90 000 | **~75 000** | ~15 000 l. supprimées (code mort + duplication) |
| Fichiers > 1 000 lignes | 14 | **0** | Convention : seuil dur à 800 lignes |

---

## 3. Graphe de dépendances autorisé

### 3.1 DAG complet — ASCII art

```
                                ┌─────────────────────┐
                                │       _cli/         │
                                │  (parsing argparse) │
                                └──────────┬──────────┘
                                           │ importe
                                           ▼
                    ┌──────────────────────────────────────────┐
                    │            simulation/api.py             │
                    │        (classe publique Simulation)      │
                    └──────────┬───────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────────────────────────┐
                    │         simulation/workflows/            │
                    │       (UN orchestrateur par verbe)       │
                    └──┬────────────┬───────────────┬──────────┘
                       │            │               │
                       │            ▼               │
                       │  ┌──────────────────┐      │
                       │  │   analysis/      │      │
                       │  │ (calibration,    │      │
                       │  │  display, batch) │      │
                       │  └────────┬─────────┘      │
                       │           │                │
                       ▼           ▼                ▼
                    ┌──────────────────────────────────────┐
                    │      simulation/execution/           │
                    │      simulation/planning/            │
                    │      simulation/adapters/            │
                    │      simulation/extraction/          │
                    └────────┬─────────┬───────────┬───────┘
                             │         │           │
                             ▼         ▼           ▼
                    ┌────────────┐ ┌─────────┐ ┌────────────┐
                    │  solver/   │ │results/ │ │ physics/   │
                    │(NWT,MF6,   │ │(catalog │ │(Flow,      │
                    │ Boussinesq)│ │+Zarr+   │ │ Transport, │
                    │            │ │io)      │ │ Recharge)  │
                    └─────┬──────┘ └────┬────┘ └─────┬──────┘
                          │             │            │
                          │             │            ▼
                          │             │      ┌──────────┐
                          │             │      │ physics/ │
                          │             │      │   base/  │
                          │             │      └────┬─────┘
                          └─────────┬───┘           │
                                    ▼               │
                          ┌────────────────┐        │
                          │   spatial/     │◄───────┘
                          │ (geographic,   │
                          │  domain, mesh, │
                          │  fields,       │
                          │  surface)      │
                          └────────┬───────┘
                                   │
                                   ▼
                          ┌────────────────┐
                          │     data/      │
                          │  (planner,     │
                          │   variables,   │
                          │   providers,   │
                          │   cache)       │
                          └────────┬───────┘
                                   │
                                   ▼
                          ┌────────────────┐
                          │     core/      │  ← FEUILLE DU DAG
                          │ (config, state,│    n'importe AUCUN
                          │  time, units,  │    package hydromodpy.*
                          │  workspace,    │
                          │  whitebox, io, │
                          │  logging,      │
                          │  exceptions)   │
                          └────────────────┘
```

### 3.2 Règles d'import explicites

Matrice — ligne = importe, colonne = importé. ✅ = autorisé, ⚠ = lazy uniquement (dans fonctions / `TYPE_CHECKING`), ❌ = interdit.

| ↓ importe \ importé → | core | data | spatial | physics | solver | simulation | results | analysis | _cli |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **core**      | ✅  | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **data**      | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **spatial**   | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **physics**   | ✅ | ⚠ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **solver**    | ✅ | ⚠ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **simulation**| ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| **results**   | ✅ | ⚠ | ✅ | ⚠ | ⚠ | ❌ | ✅ | ❌ | ❌ |
| **analysis**  | ✅ | ✅ | ✅ | ✅ | ⚠ | ✅ | ✅ | ✅ | ❌ |
| **_cli**      | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

### 3.3 Vérification automatique

Un test `tests/unit/test_import_dag.py` NOUVEAU charge le AST de chaque fichier, extrait les imports `hydromodpy.*`, et vérifie que la matrice est respectée. Implémentation :

```python
# tests/unit/test_import_dag.py (NOUVEAU)
import ast, pathlib
ALLOWED = {
    "core": set(),
    "data": {"core"},
    "spatial": {"core", "data"},
    "physics": {"core", "spatial"},     # data en lazy seulement
    "solver": {"core", "spatial", "physics"},
    "simulation": {"core", "data", "spatial", "physics", "solver", "results"},
    "results": {"core"},                 # spatial/physics/solver en lazy
    "analysis": {"core", "data", "spatial", "physics", "simulation", "results"},
    "_cli": {...},  # tout autorisé
}
def test_import_dag_is_respected(): ...
```

---

## 4. API publique `import hydromodpy as hmp`

### 4.1 Symboles exposés au top-level (≤ 25)

Principe : **ce qu'on tape au clavier dans une session Jupyter.**

```python
# hydromodpy/__init__.py (cible)
__all__ = [
    # === Entrée workspace & config ===
    "open",                    # hmp.open(workspace) → SimulationCatalog
    "Workspace",
    "HydroModPyConfig",

    # === Domaine & maillage ===
    "Geographic",              # Délinéation bassin
    "Domain",                  # Domaine simulation
    "HydroMesh",               # Maillage pivot

    # === Physique ===
    "Flow",
    "Transport",

    # === Solveurs (symétrie complète) ===
    "Modflow",                 # NWT (alias historique)
    "Modflow6",                # MF6
    "Modpath7",                # Particules
    "Mt3dms",                  # Transport MT3DMS
    "Boussinesq",              # NATIF (exposé ENFIN)

    # === Orchestration haut niveau ===
    "Simulation",              # API publique programmatique
    "SimulationPlan",          # Plan immuable (inspection)

    # === Résultats ===
    "SimulationCatalog",
    "SimulationResult",

    # === Sous-modules (navigation) ===
    "data", "spatial", "physics", "solver", "simulation",
    "results", "analysis", "core",

    # === Divers ===
    "__version__",
    "log_manager",
]
```

**Retiré du top-level** (exposé uniquement en sous-module) :
- `Hydrometry`, `Piezometry`, `Subbasin` → `hmp.data.hydrometry.Hydrometry`, etc.
- `HydrographyConfig/Manager/Result`, `IntermittencyConfig/Manager`, `OceanicConfig/Manager` → pollution d'espace de noms. Accessibles via `hmp.data.variables.hydrography.*`.

### 4.2 Exemple d'utilisation — session interactive

```python
# ==========================================================================
# EXEMPLE 1 : Utilisation haut niveau TOML-driven
# ==========================================================================
import hydromodpy as hmp

# Lancement direct d'un config
sim = hmp.Simulation("configs/canut_baseline.toml")
result = sim.run(Sy=0.05, K=1e-5, name="baseline_Sy005")

# Inspection des résultats via le catalogue
catalog = hmp.open("/workspaces/brittany")
best = catalog.best(project="canut", metric="nse")
print(best.metadata.solver, best.nse, best.kge)

wt_map = best.field("watertable_depth", timestep=12)
outflow = best.timeseries("outflow_drain")

# ==========================================================================
# EXEMPLE 2 : Construction programmatique
# ==========================================================================
config = hmp.HydroModPyConfig.from_toml("configs/canut_baseline.toml")
geo = hmp.Geographic(config.geographic)
geo.delineate()

mesh = hmp.HydroMesh.from_catchment(geo, config.mesh)
domain = hmp.Domain.from_mesh(mesh, config.domain)

flow = hmp.Flow(config.flow)
solver = hmp.Modflow6(config.solver)

plan = hmp.SimulationPlan.from_config(config, domain=domain, mesh=mesh)
with hmp.open(config.workspace.root) as catalog:
    result = hmp.Simulation.run_plan(plan, catalog=catalog)

# ==========================================================================
# EXEMPLE 3 : Navigation du catalogue
# ==========================================================================
group = catalog.find(project="brittany", nse_gt=0.7, solver="modflow6")
df = group.pivot(index="run_id", columns="parameter", values="value")
group.export("/tmp/top_runs.hmp")     # package portable

# ==========================================================================
# EXEMPLE 4 : Comparaison de solveurs
# ==========================================================================
comparison_config = "configs/canut_compare.toml"
hmp.Simulation(comparison_config).run()   # dispatch via [comparison]
```

### 4.3 Pattern lazy imports

Pattern identique à `scipy.linalg`, `sklearn`, `xarray` — PEP 562 (`__getattr__`) avec cache dans `globals()`. Code squelette :

```python
# hydromodpy/__init__.py (NOUVEAU, cible)
from __future__ import annotations
import importlib
from hydromodpy.core.version import __version__

_LAZY = {
    # symboles → module cible
    "Workspace": "hydromodpy.core.workspace",
    "HydroModPyConfig": "hydromodpy.core.config",
    "Geographic": "hydromodpy.spatial.geographic",
    "Domain": "hydromodpy.spatial.domain",
    "HydroMesh": "hydromodpy.spatial.mesh",
    "Flow": "hydromodpy.physics.flow",
    "Transport": "hydromodpy.physics.transport",
    "Modflow": "hydromodpy.solver.modflow_nwt",
    "Modflow6": "hydromodpy.solver.modflow6",
    "Modpath7": "hydromodpy.solver.modflow_nwt",
    "Mt3dms": "hydromodpy.solver.modflow_nwt",
    "Boussinesq": "hydromodpy.solver.boussinesq",
    "Simulation": "hydromodpy.simulation.api",
    "SimulationPlan": "hydromodpy.simulation.planning",
    "SimulationCatalog": "hydromodpy.results.catalog",
    "SimulationResult": "hydromodpy.results.simulation",
}
_SUBMODULES = ("core","data","spatial","physics","solver","simulation","results","analysis")

def __getattr__(name: str):
    if name in _SUBMODULES:
        mod = importlib.import_module(f"hydromodpy.{name}")
        globals()[name] = mod
        return mod
    if name in _LAZY:
        mod = importlib.import_module(_LAZY[name])
        attr = getattr(mod, name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module 'hydromodpy' has no attribute {name!r}")

def open(workspace_path):  # noqa: A001
    from hydromodpy.results.catalog import SimulationCatalog
    return SimulationCatalog(workspace_path)

# Pas de PROJ_DATA bootstrap ici (déplacé dans core.io.crs, appelé lazy).
# Pas de LogManager() ici (appelé lazy dans core.logging au premier get_logger()).
```

**Différences avec l'actuel** :

| Avant (current) | Après (cible) |
|---|---|
| 319 lignes (dont 207 de PROJ_DATA) | **≤ 80 lignes** |
| `LogManager()` instancié à l'import (effet de bord) | Instancié au premier `get_logger()` |
| `PROJ_DATA` muté au chargement | Muté à la création du premier `Geographic` |
| 17 symboles exposés, dont 7 `*Config/*Manager/*Result` | 22 symboles, aucun `*Manager` top-level |
| `Boussinesq` absent, `Modpath7` absent | Exposés symétriquement |

---

## 5. Points d'entrée CLI `hmp`

### 5.1 Vue d'ensemble

Deux binaires installés par `pyproject.toml` (`[project.scripts]`) :
- `hmp` — alias court.
- `hydromodpy` — alias long.

Les deux pointent sur `hydromodpy._cli.main:main`. Style Git-like : `hmp <verbe> [args...]`.

### 5.2 Liste complète des sous-commandes

| Verbe | Synopsis | Description | Statut |
|---|---|---|---|
| `hmp init` | `hmp init [--path PATH] [--template minimal\|full]` | Crée un workspace (DuckDB vide + arbo). | [C] |
| `hmp new` | `hmp new <project> [--workspace PATH] [--from TEMPLATE]` | Crée un projet dans le workspace. | [C] |
| `hmp config` | `hmp config [output.toml] [--profile user\|dev\|expert] [--solver nwt\|mf6\|boussinesq]` | Génère un template TOML profilé. | [C] |
| `hmp run` | `hmp run <config.toml> [--workflow WORKFLOW] [--dry-run] [--override key=val]...` | Exécute (auto-détection workflow). `--workflow` force. | [F] |
| `hmp display` | `hmp display <config.toml\|sim_id> [--figures FIG1,FIG2]` | Régénère figures post-hoc. | [C] |
| `hmp list` | `hmp list [projects\|sims\|runs] [--project NAME] [--format table\|json\|csv]` | Inventaire workspace. | [F] |
| `hmp export` | `hmp export <sim_id\|project> [--format hmp\|netcdf\|geotiff\|vtu\|shp\|gpkg\|csv\|waterml]` | Exporte dans UN format. | [F] |
| `hmp inspect` | `hmp inspect <sim_id> [--json]` | Dump metadata + stats d'une simulation. | [N] |
| `hmp import` | `hmp import <package.hmp> [--workspace PATH]` | Importe un package portable. | [N] |
| `hmp validate` | `hmp validate <config.toml> [--strict]` | Valide Pydantic + inférence sans lancer. | [N] |
| `hmp doctor` | `hmp doctor` | Diagnostic environnement (PROJ, FloPy, gmsh, executables). | [N] |
| `hmp --version` | | Affiche `__version__` + versions des dépendances clés. | [N] |
| `hmp --help` | | Aide + epilog avec 3 exemples. | [F] |

**Supprimé** : `hmp test` (réinvention de pytest — rapport 01 §2.3). Le README documentera `pytest tests/regression/fast/ -v` directement.

### 5.3 Auto-détection `hmp run`

Table de dispatch stable et documentée dans l'aide :

| Section TOML dominante | Workflow activé |
|---|---|
| `[calibration]` | `calibration_workflow` |
| `[batch]` | `batch_workflow` |
| `[comparison]` | `comparison_workflow` |
| `[overview]` (sans `[simulation]`) | `overview_workflow` |
| `[mesh_catchment]` (sans `[simulation]`) | `mesh_workflow` |
| `[simulation]` ou `[flow]` (défaut) | `simulation_workflow` |

Override explicite : `hmp run config.toml --workflow batch`.

### 5.4 Codes de sortie POSIX

Documentés dans l'aide et respectés uniformément :

| Code | Sémantique |
|---|---|
| 0 | Succès |
| 1 | Erreur runtime générique |
| 2 | Erreur d'usage (arguments invalides) |
| 3 | Erreur de configuration (Pydantic validation failed) |
| 4 | Erreur solveur (MODFLOW, Boussinesq échec de convergence) |
| 5 | Erreur données (API externe, cache corrompu) |
| 130 | Interrompu (Ctrl-C, SIGINT) |

### 5.5 Complétion shell

Activation standard `argcomplete` (3 lignes dans `_cli/main.py`) :

```python
# hydromodpy/_cli/main.py
# PYTHON_ARGCOMPLETE_OK
import argcomplete
parser = _build_parser()
argcomplete.autocomplete(parser)
args = parser.parse_args()
```

Installation pour l'utilisateur : `activate-global-python-argcomplete` (commande tierce, une fois).

### 5.6 Exemple d'aide — `hmp run --help` (cible)

```
usage: hmp run [-h] [--workflow {simulation,overview,mesh,calibration,batch,comparison}]
               [--dry-run] [--override KEY=VALUE]
               config

Execute a HydroModPy workflow from a TOML configuration.

positional arguments:
  config                 Path to the .toml configuration file.

options:
  -h, --help             Show this help message and exit.
  --workflow {...}       Override auto-detection from TOML sections.
  --dry-run              Parse and validate only; do not execute.
  --override KEY=VALUE   Override config values (repeatable, dotted path).

Examples:
  hmp run configs/canut_baseline.toml
  hmp run configs/canut_baseline.toml --override flow.k=1e-5
  hmp run configs/canut_baseline.toml --workflow comparison --dry-run

Exit codes: 0 ok, 1 runtime, 2 usage, 3 config, 4 solver, 5 data.
See 'hmp doctor' for environment diagnostics.
```

### 5.7 Squelette d'une commande

Chaque commande est un module ≤ 80 lignes. Pattern :

```python
# hydromodpy/_cli/commands/run_cmd.py (NOUVEAU)
from __future__ import annotations
import argparse, sys
from hydromodpy.simulation.workflows.dispatcher import detect_workflow
from hydromodpy.core.exceptions import ConfigError, SolverError

def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("run", help="Execute a TOML workflow.")
    p.add_argument("config", help="Path to .toml")
    p.add_argument("--workflow", choices=[...])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--override", action="append", default=[])
    p.set_defaults(func=_handle)

def _handle(args: argparse.Namespace) -> int:
    try:
        workflow = detect_workflow(args.config, explicit=args.workflow)
        if args.dry_run:
            return 0
        workflow(args.config, overrides=args.override)
        return 0
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr); return 3
    except SolverError as e:
        print(f"solver error: {e}", file=sys.stderr); return 4
```

---

## 6. Tableau de migration actuel → cible

### 6.1 Fichiers racine du package

| Actuel | Cible | Action | Rationale |
|---|---|---|---|
| `hydromodpy/__init__.py` (319 l.) | `hydromodpy/__init__.py` (~80 l.) | **[F] refactoré** | Retire PROJ_DATA bootstrap (déplacé vers `core.io.crs`, lazy). Retire `LogManager()` eager. Réduit `_LAZY_IMPORTS` à l'API minimale. |
| `hydromodpy/__main__.py` (1 223 l.) | `hydromodpy/_cli/` | **[F] éclaté** | Un fichier par sous-commande (≤ 80 l. chacun). Ajoute `--version`, `argcomplete`. |
| `hydromodpy/project.py` (705 l.) | `hydromodpy/simulation/api.py` (~150 l.) | **[D] déplacé + [F] refactoré** | Dissonance fichier/classe résolue. Classe `Simulation` = wrapper mince sur `execute_simulation()`. |
| `hydromodpy/exceptions.py` (30 l., 0 usage) | `hydromodpy/core/exceptions.py` | **[D] déplacé + [F] utilisé** | Hiérarchie UTILISÉE : ConfigError, SolverError, DataError, MeshError levées dans les bons endroits. |
| `hydromodpy/watershed/` (500 l.) | — | **[K] supprimé** | Façade historique. 3 générations de code → 2. DeprecationWarning puis suppression. |

### 6.2 Package `core/`

| Actuel | Cible | Action |
|---|---|---|
| `core/__init__.py` | `core/__init__.py` | [C] conservé |
| `core/config/hydromodpy_config.py` (aggrégateur important 13 modules) | `core/config/aggregate_config.py` | **[R]+[F]** renommé + imports lazy via fabriques (`make_simulation_config_slot()`). Restaure core feuille. |
| `core/config/generate_toml.py` | `core/config/template.py` | [R] renommé |
| `core/config/param_level.py` | `core/config/param_level.py` | [C] conservé |
| `core/config/streamlit_config.py` | `core/config/streamlit.py` | [R] renommé (sans `_config`) |
| `core/state/{setup,loaded_data,execution,workflow}.py` | `core/state/{setup_context,run_context,execution_registry}.py` | **[F] fusionné** : triple-niveau `Workflow/Setup/LoadedData/Execution` → double plat `SetupContext` + `RunContext`. |
| `core/time/` | `core/time/` | [C] conservé |
| `core/units/` (7 modules, 1085 l., utilise pint dans 1 seul) | `core/units/` (3 modules, pint partout) | **[F]** migration complète vers pint. |
| `core/tools/log_manager.py` | `core/logging/manager.py` | [D] déplacé |
| `core/tools/folder_root.py` (`input()` bloquant) | — | [K] supprimé |
| `core/tools/io_utils.py` (legacy, Watershed wrapper) | — | [K] supprimé |
| `core/tools/visualization.py` (315 l., cmap jet) | `examples/shared/visualization.py` | [D] déplacé hors package |
| `core/tools/raster.py`, `core/tools/statistics.py` | `core/io/raster_io.py`, conservé si tactique | [D] déplacé |
| `core/tools/run_id.py` (NOUVEAU) | `core/tools/run_id.py` | **[N]** factorise `_derive_run_id_from_filename` (duplicata). |
| `core/workspace/` | `core/workspace/` | [C] conservé |
| `core/backends/` (pluriel trompeur) | `core/whitebox/` | [R] renommé (singulier) |
| `core/exceptions.py` (NOUVEAU depuis racine) | `core/exceptions.py` | [D]+[F] déplacé depuis `hydromodpy/exceptions.py` + utilisé réellement |
| `core/version.py` (NOUVEAU) | `core/version.py` | **[N]** extrait le calcul `__version__` du top-level `__init__.py`. |
| `core/io/http_client.py` (NOUVEAU) | `core/io/http_client.py` | **[N]** wrapper HTTP unique avec retry, timeout, 429. Remplace tous les `urllib.request.urlretrieve` dispersés. |
| `core/io/crs.py` (NOUVEAU) | `core/io/crs.py` | **[N]** Centralise `pyproj.CRS.from_user_input` + bootstrap PROJ_DATA (ex-207 lignes de `__init__.py`). |

### 6.3 Package `data/`

| Actuel | Cible | Action |
|---|---|---|
| `data/climatic/{climatic,sim2_API,driasclimat,driaseau,safransurfex}.py` | — | **[K]** 2 745 l. de legacy supprimées |
| `data/climatic/sim2.py` | `data/providers/meteofrance.py` | [D] déplacé + nettoyé |
| `data/common/base_manager.py` | `data/base_manager.py` | [D] aplati (pas de `common/`) |
| `data/common/` (netcdf_conventions, config abstractions) | Partie → `data/contracts.py`, partie → `analysis/postprocess/` | [D] redistribué |
| `data/contracts/` | `data/contracts.py` (fichier simple) | [F] fichier unique |
| `data/data_managers.py`, `data_managers_config.py`, `planner.py`, `plan.py` | `data/planner/{planner,plan,inference}.py` | [D] regroupé |
| `data/runtime_loader.py` (892 l.) | `data/planner/runtime_loader.py` (≤ 500 l. après dédup) | [F] réduit |
| `data/hydrometry/`, `data/geology/`, `data/piezometry/`, `data/oceanic/` (duplique `variables/`) | — | **[K]** duplication post-merge, supprimée |
| `data/variables/dem/` etc. | `data/variables/dem/` | [C] conservé |
| `data/variables/{etp,humidity,runoff,soil_moisture,temperature,wind}/config.py` (95% identiques) | `data/variables/climatic/{etp,...}.py` + `data/timeseries/source_config.py` | **[F]** factorisé via `TimeseriesSourceConfig` + mixins. ~800 l. gagnées |
| `data/variables/*/apis/` (clients HTTP dispersés) | `data/providers/` + adapters dans chaque `variables/*/providers.py` | **[F]** providers centralisés |
| `data/variables/*/cases/` (10+ dossiers cases) | `validation_cases/data/` (hors package) | **[D]** sorti du package runtime |
| `data/variables/*/examples/` | `examples/data/` | [D] sorti |
| `data/registry/catalog_duckdb.py` | `data/cache/catalog.py` | [R] renommé (cache, pas catalog — éviter collision) |
| `data/subbasin/` | `data/variables/subbasin/` | [D] déplacé |

### 6.4 Package `spatial/`

| Actuel | Cible | Action |
|---|---|---|
| `spatial/__init__.py` | `spatial/__init__.py` | [C] conservé |
| `spatial/catchment_zones_field.py` (au top flottant) | `spatial/domain/zones.py` | [D] déplacé |
| `spatial/raster_support.py` | `spatial/fields/raster_support.py` | [D] déplacé |
| `spatial/surface.py`, `surface_sampling.py` | `spatial/surface.py` (fusionné) | [F] fusionné |
| `spatial/geographic/core/`, `geographic/synthetic/` | `spatial/geographic/` (à plat) | [F] déhiérarchisé |
| `spatial/geographic/pipeline.py` (wrapper legacy) | — | [K] supprimé |
| `spatial/geographic/synthetic/` (non testé) | `examples/synthetic/` | [D] sorti |
| `spatial/geographic/cases/` | `validation_cases/spatial/` | [D] sorti |
| `spatial/geographic/subbasin.py` | `spatial/geographic/subbasin.py` | [C] conservé |
| `spatial/domain/` | `spatial/domain/` | [C] conservé |
| `spatial/field/` | `spatial/fields/` (pluriel) | [R] renommé pour cohérence |
| `spatial/field/core/field_param.py:745-749` (moyenne K arithmétique) | `spatial/fields/aggregation.py` | **[F]** paramètre `aggregation: Literal["arithmetic","harmonic","geometric"]` |
| `spatial/field/cases/` | `validation_cases/fields/` | [D] sorti |
| `spatial/mesh/` | `spatial/mesh/` | [C] conservé |
| `spatial/mesh/runtime*.py` | `spatial/mesh/runtime.py` (convention unique) | [R] uniformisé |
| `solver/utils/mesh/gmsh_grid/` | `spatial/mesh/gmsh/` | **[D]** INVERSION de la dépendance interdite. |
| `solver/utils/mesh/cartesian_grid/` | `spatial/mesh/cartesian/` | **[D]** idem |
| `solver/utils/mesh/gmsh_grid/zone_meshing/_{gmsh_driver,geometry_cleaning,refinement_policy}.py` | — | [K] façades stériles |
| `solver/utils/mesh/*/examples/` | `examples/mesh/` | [D] sorti |

### 6.5 Package `physics/` (ex-`process/`)

| Actuel | Cible | Action |
|---|---|---|
| `process/` | `physics/` | **[R]** renommé (polysémie multiprocessing évitée) |
| `process/__init__.py` (eager imports rendant `__getattr__` mort) | `physics/__init__.py` propre | [F] corrigé |
| `process/contracts.py` (29 l., re-export) | — | [K] fusionné dans `physics/base/__init__.py` |
| `process/base/{process,boundary_condition,initial_condition,sink_source}.py` | `physics/base/{process,boundary_condition,initial_condition,source_term}.py` | [R] `SinkSource` → `SourceTerm` |
| `process/flow/` | `physics/flow/` | [D] |
| `process/transport/` | `physics/transport/` | [D] |
| `process/forcing/` | `physics/base/forcing.py` + spécifiques dans `flow/source_terms.py` | [F] fusionné |
| `process/hydrology/` (30 fichiers, PyHELP) | `physics/recharge/` (aplati) | [F] aplati |
| `process/hydrology/synthetic/` | `examples/physics/synthetic_recharge.py` | [D] sorti |

### 6.6 Package `solver/`

| Actuel | Cible | Action |
|---|---|---|
| `solver/__init__.py` | `solver/__init__.py` | [C] conservé |
| `solver/contracts.py` (15 l. re-export) | — | [K] fusionné dans `solver/base/` |
| `solver/compatibility.py` | `solver/base/compatibility.py` | [D] |
| `solver/base/` | `solver/base/` | [C] conservé |
| `solver/modflow_common/` | `solver/modflow_common/` | [C] conservé |
| `solver/modflow6/flow_to_modflow_adapter.py` + `solver/modflow_nwt/modflow/flow_to_modflow_adapter.py` (duplication) | `solver/modflow_common/flow_translator.py` | **[F]** factorisé |
| `solver/modflow_nwt/` (NWT+MODPATH+MT3DMS imbriqués) | `solver/modflow_nwt/` aplati | [F] aplati |
| `solver/modflow_nwt/modpath/` (MODPATH 6) | `solver/modflow_nwt/modpath.py` (MODPATH 7) | **[F]** mise à niveau MODPATH 7 (support DISV) |
| `solver/modflow6/modflow6.py` (2 900 l.) | `solver/modflow6/{solver,translator,extractor,transport_gwt}.py` | [F] éclaté |
| `solver/boussinesq/` (6 sous-couches) | `solver/boussinesq/` (3 niveaux) | [F] aplati |
| `solver/boussinesq/smoothing.py` (non branché) | — | [K] code mort |
| `solver/boussinesq/{methods,engines,formulations,runtimes,drivers,assembly,jacobian}/` | `solver/boussinesq/{formulations,jacobian,runtimes}.py` | [F] aplati |
| `solver/boussinesq/boussinesq.py` (1 667 l. avec duplication `_resolve_*`) | `solver/boussinesq/solver.py` (≤ 500 l.) | [F] réduit |
| `solver/utils/mesh/` | `spatial/mesh/` | **[D]** voir §6.4 |
| `solver/utils/temporal/` | `core/time/` | [D] déplacé |
| `solver/utils/temporal/cases/` | `validation_cases/time/` | [D] sorti |

### 6.7 Package `simulation/`

| Actuel | Cible | Action |
|---|---|---|
| `simulation/__init__.py` (46 l., helpers impératifs `ensure_*`) | `simulation/__init__.py` épuré | [F] helpers retirés du top |
| `simulation/settings.py` | `simulation/planning/settings.py` | [D] |
| `simulation/adapters/` | `simulation/adapters/` | [C] conservé |
| `simulation/adapters/display/stub.py`, `postprocess/stub.py` | — | [K] jamais enregistrés |
| `simulation/adapters/registry.py` | `simulation/adapters/registry.py` | [C] conservé, typé |
| `simulation/planning/` | `simulation/planning/` | [C] conservé |
| `simulation/execution/` | `simulation/execution/` | [C] conservé, étendu |
| `simulation/execution/{ensure_flow,ensure_transport,ensure_process_context}.py` | `simulation/execution/overrides.py` + internes | [F] plus d'helpers impératifs exposés |
| `simulation/results/` | `simulation/extraction/` | **[R]** collision avec `results/` levée |
| `simulation/results/extractors/` | `simulation/extraction/` (éclaté par type de sortie) | [F] réorganisé |
| `simulation/results/extractors/catchment_aggregation.py` (heuristique `n_per` bugguée) | `simulation/extraction/aggregation.py` (algo correct) | [F] corrigé |
| `simulation/forcing/` | `physics/base/forcing.py` + `simulation/execution/forcing.py` | [F] scindé |
| `workflow/` (top-level) | `simulation/workflows/` | **[D]** absorbé. Un seul lieu d'orchestration. |
| `workflow/pipelines/process_simulation.py` (re-exports only) | — | [K] |
| `workflow/context.py` | `core/state/run_context.py` | [D] |
| `workflow/steps/` | `simulation/execution/steps.py` | [D] fichier unique |

### 6.8 Package `results/`

| Actuel | Cible | Action |
|---|---|---|
| `results/catalog.py` (920 l.) | `results/catalog/{catalog,writes,queries,package,migrations}.py` | [F] éclaté |
| `results/catalog_schema.py` | `results/schema/{tables,views}.py` | [F] enrichi (PK+FK manquantes) |
| `results/simulation.py` | `results/simulation.py` | [C] conservé |
| `results/simulation.rerun()` (NotImplementedError) | — | [K] |
| `results/simulation_group.py` | `results/simulation_group.py` | [C] |
| `results/zarr_store.py` | `results/storage/zarr_store.py` | [D] |
| `results/display.py` | `analysis/display/posthoc.py` | [D] (c'est du display, pas du storage) |
| `results/virtual_fields.py` | `results/virtual_fields.py` | [C] |
| `results/spatial_index.py` | `results/spatial_index.py` | [C] |
| `results/provenance.py` (SHA sur payload post-parsing) | `results/provenance.py` (PROV-O, SHA sur source) | [F] |
| `results/resample.py` (NotImplementedError) | — | [K] |
| `results/config.py` | `results/config.py` | [C] |
| `results/exporters/` | `results/io/exporters/` | [D] |
| `results/exporters/vtu.py` (bug `_split_cell_data`) | `results/io/exporters/vtu.py` corrigé | [F] |
| `results/exporters/netcdf.py` | `results/io/exporters/netcdf.py` (CF-1.8 + UGRID-1.0 strict) | [F] |
| `results/io/exporters/geopackage.py` | `results/io/exporters/geopackage.py` | **[N]** remplace shapefile en primaire |
| `results/io/exporters/waterml.py` | `results/io/exporters/waterml.py` | **[N]** export stations WaterML 2.0 |
| `results/io/registry.py` | `results/io/registry.py` | **[N]** enregistrement auto |

### 6.9 Package `analysis/`

| Actuel | Cible | Action |
|---|---|---|
| `analysis/capability_gallery.py` (marketing au top) | `examples/gallery/` | [D] sorti du package |
| `analysis/calibration/engine/session.py` (3 409 l.) | `analysis/calibration/engine/{session,state,orchestration,io,reporting}.py` | [F] éclaté |
| `analysis/calibration/cases/` | `validation_cases/calibration/` | [D] sorti |
| `analysis/calibration/devkit/templates/` | `analysis/calibration/templates/` | [D] déplacé |
| `analysis/comparison/runtime.py` (2 061 l.) | `analysis/comparison/comparison.py` + dossiers figures | [F] éclaté |
| `analysis/comparison/visuals.py` (1 997 l.) | `analysis/comparison/figures/*.py` | [F] éclaté par planche |
| `analysis/batch/runtime.py` (1 828 l.) | `analysis/batch/batch.py` + modules | [F] éclaté |
| `analysis/display/orchestration.py` | — | [K] façade dormante |
| `analysis/display/visualization_results.py` (914 l. legacy) | — | [K] après migration 3 cas |
| `analysis/display/visualization_watershed.py` (469 l., side-effects) | — | [K] |
| `analysis/display/suites.py` | `analysis/display/suites.py` | [C] conservé (UN SEUL orchestrateur) |
| `analysis/display/figures/` | `analysis/display/figures/` | [C] conservé + split |
| `analysis/display/report/` | `analysis/display/overview.py` | [F] fichier unique |
| `analysis/postprocess/flow/`, `netcdf/`, `timeseries/` | `analysis/postprocess/{netcdf_writer,timeseries}.py` | [F] aplati |
| `analysis/postprocess/flow/` | `results/io/exporters/netcdf.py` (fusion) | [F] partiel |
| `analysis/metrics/` | `analysis/metrics/` | **[N]** factorise `rmse_manual/nse_manual/kge_manual` dispersés |

### 6.10 Package `runners/`

| Actuel | Cible | Action |
|---|---|---|
| `runners/__init__.py` (`detect_workflow`) | `simulation/workflows/dispatcher.py` | [D] déplacé |
| `runners/{simulation,overview,mesh,calibration,batch}.py` | `simulation/workflows/{...}_workflow.py` | [F] fusionnés avec workflows |
| `runners/templates/model_calibration.py` | `analysis/calibration/templates/model_calibration.py` | [D] contenu métier, pas shell CLI |

**Verdict** : le package `runners/` top-level disparaît. Son ancien rôle (dispatch thin-shell) est désormais dans `_cli/commands/` + `simulation/workflows/`.

### 6.11 Résumé quantitatif

| Action | Nombre de fichiers |
|---|---:|
| **[C] Conservé** | ~180 |
| **[R] Renommé** | ~35 |
| **[D] Déplacé** | ~120 |
| **[F] Refactoré** | ~45 |
| **[N] Nouveau** | ~25 |
| **[K] Supprimé** | ~95 (≈ 9 600 lignes, 12 % du code Python non-test) |
| **Total cible** | ~410 fichiers (vs ~580 actuellement) |

---

## 7. Conventions de nommage et organisation

### 7.1 Modules Python

| Convention | Exemple | Rôle |
|---|---|---|
| `foo_config.py` | `flow_config.py`, `geographic_config.py` | Modèle Pydantic v2. Nom = `<Foo>Config` (suffixe `Config` obligatoire). |
| `foo_manager.py` | `geology_manager.py`, `hydrometry_manager.py` | Classe `<Foo>Manager` héritant de `BaseVariableManager`. |
| `foo_result.py` | `dem_result.py` | Dataclass (`@dataclass(frozen=True)`) de retour de `manager.load()`. |
| `providers.py` | `data/variables/dem/providers.py` | Clients API externes spécifiques à la variable. Adapte `core/io/http_client.py`. |
| `foo_schema.py` (SQL) | `results/schema/tables.py` (regroupé) | Schémas DuckDB (CREATE TABLE). |
| `foo_workflow.py` | `simulation/workflows/simulation_workflow.py` | Un orchestrateur de haut niveau par verbe. |
| `foo_cmd.py` | `_cli/commands/run_cmd.py` | Sous-commande CLI argparse. |
| `solver.py` / `solver_config.py` / `extractor.py` / `translator.py` | Dans `solver/<engine>/` | Convention fixée pour chaque solveur. |

**Interdits** :
- `common.py`, `utils.py`, `helpers.py`, `misc.py`, `tools.py`, `base.py` seul → nom du domaine (`raster_io.py`, `crs.py`, `statistics.py`, `variable_base.py`).
- Préfixe `Schema` sur les classes Pydantic (reliquat v1) → suffixe `Config`.
- Suffixe `_legacy`, `_v2`, `_new`, `_npy` (introduisent de l'ambiguïté dans le temps) → renommer clairement ou supprimer.
- `cases/` dans les packages runtime → `validation_cases/` à la racine du repo.

### 7.2 Classes

| Rôle | Suffixe / style | Exemple |
|---|---|---|
| Pydantic model | `<Name>Config` | `FlowConfig`, `MeshConfig`, `DemConfig` |
| Frozen dataclass | Nom nu | `SimulationPlan`, `ProcessRun`, `TimeGrid` |
| ABC | Nom nu OU `Base<Name>` | `Process`, `BaseVariableManager`, `Solver` |
| Protocol (PEP 544) | `<Name>Protocol` OU nom nu si unique | `SolverAdapter`, `ResultExtractor` |
| Manager (loader I/O) | `<Name>Manager` | `GeologyManager` |
| Engine (exécutant) | `<Name>Engine` | `SolverEngine`, `WhiteboxBackend` |
| Wrapper public | Nom du domaine | `Simulation`, `Workspace`, `Geographic` |
| Exception | `<Domain>Error` (ou `<Domain>Warning`) | `ConfigError`, `SolverError`, `DataError`, `MeshError` |

### 7.3 Fichiers de configuration TOML

**Racine** `[hydromodpy]`. Sections au singulier si unique, au pluriel si liste :

```toml
# Sections uniques (Pydantic model)
[workspace]
[geographic]
[domain]
[mesh]
[flow]
[transport]
[solver]
[simulation]
[display]
[postprocess]

# Sections listes (array-of-tables)
[[simulation.process]]
type = "flow"
solver = "modflow6"

[[data.variables]]
type = "geology"
provider = "brgm"

# Sections "mode" (mutuellement exclusives avec simulation)
[overview]          # → overview_workflow
[mesh_catchment]    # → mesh_workflow
[calibration]       # → calibration_workflow
[batch]             # → batch_workflow
[comparison]        # → comparison_workflow
```

**Conventions** :
- Clés TOML en `snake_case`.
- Unités dans la clé si ambigu : `length_m`, `conductivity_m_per_s`, `porosity` (sans unité, adimensionnel). Ou bien `{ value = 1e-5, units = "m/s" }` Pydantic dispatch.
- Aucune clé avec accent ou espace (portabilité Windows/Unix).
- `profile` field dans `[hydromodpy]` : `"user"` / `"dev"` / `"expert"` gouverne `ParamLevel` visible.

### 7.4 Tests associés

Correspondance stricte un pour un :

```
hydromodpy/spatial/mesh/cartesian/generator.py
↔ tests/unit/spatial/mesh/test_cartesian_generator.py

hydromodpy/solver/modflow_common/flow_translator.py
↔ tests/unit/solver/test_modflow_common_flow_translator.py
```

**Règles** :
- Tests unit : isoler le module avec `@pytest.fixture` locales. Pas de solveur invoqué.
- Tests regression : `tests/regression/fast/` (≤ 60 s total), `tests/regression/extensive/` (minutes). Markers automatiques par `conftest.py`.
- Tests validation : `tests/validation/analytical/` pour Theis, Hantush, Ogata-Banks, MMS. Tolérances documentées dans `tests/validation/TOLERANCES.md`.
- Goldens : `tests/regression/*/goldens/` à côté du test. Statistiques `{count, mean, p50, p95, sum, shape}` finite-only.

### 7.5 Import style

```python
# ✅ BIEN : import absolu
from hydromodpy.core.config import HydroModPyConfig
from hydromodpy.spatial.mesh import HydroMesh

# ⚠ TOLÉRÉ : import relatif UNIQUEMENT dans un même package
# Dans hydromodpy/spatial/mesh/cartesian/generator.py :
from ..hydro_mesh import HydroMesh
from .layering import build_layers

# ❌ INTERDIT : import étoile
from hydromodpy.spatial import *

# ❌ INTERDIT : import circulaire ou upstream
# Dans hydromodpy/core/config/aggregate_config.py :
from hydromodpy.spatial.domain.domain_config import DomainConfig   # ❌
# → Remplacer par TYPE_CHECKING ou une fabrique lazy :
if TYPE_CHECKING:
    from hydromodpy.spatial.domain.domain_config import DomainConfig
```

### 7.6 Docstrings

Style **NumPyDoc** strict sur tout symbole public (classes, méthodes, fonctions top-level) :

```python
def solve_flow(config: FlowConfig, mesh: HydroMesh) -> FlowResult:
    """Solve the flow problem with the configured solver.

    Parameters
    ----------
    config : FlowConfig
        Pydantic-validated flow configuration.
    mesh : HydroMesh
        Structured or unstructured mesh.

    Returns
    -------
    FlowResult
        Frozen dataclass with head field, budget, convergence info.

    Raises
    ------
    SolverError
        If the linear / non-linear solver fails to converge.
    ConfigError
        If `config` fails Pydantic validation.

    Notes
    -----
    The vertical K aggregation defaults to harmonic (physically correct
    for layered aquifers). Use `config.field.aggregation = "arithmetic"`
    to override, with caution.

    References
    ----------
    Harbaugh, A.W. 2005. MODFLOW-2005, USGS Techniques and Methods 6-A16.
    """
```

**Interdits dans les docstrings** :
- Références au ticket / PR (`"Added for issue #123"`) → dans le commit/PR description, pas ici.
- Formules sans notation mathématique LaTeX (`:math:\`...\``).
- Mélange français/anglais dans un même projet (choisir : le code base cible **l'anglais**, les rapports d'audit restent en français).

### 7.7 Exemples / cases / benchmarks

Distinction claire, trois emplacements distincts :

| Contenu | Emplacement | Rôle |
|---|---|---|
| Code production | `hydromodpy/<package>/` | Packagé et distribué par pip. |
| Benchmarks scientifiques | `validation_cases/` (racine du repo) | Cas analytiques Theis/Brutsaert/Dupuit/Ogata-Banks + MMS. Exécutables en standalone. |
| Exemples didactiques | `examples/` (racine du repo) | Notebooks/scripts pour documentation. Référencés dans RTD. |
| Tests automatisés | `tests/` (racine du repo) | pytest, séparés en unit/regression/validation. |

---

## 8. Schémas de structures techniques critiques

### 8.1 Layout Zarr par simulation

```
workspace/simulations/<sim_uuid>.zarr/
├── .zattrs                            Metadata globales (sim_id, solver, timestamp UTC)
│
├── mesh/                              Mesh UGRID-1.0 conforme
│   ├── .zattrs                        { "cf_role": "mesh_topology",
│   │                                    "topology_dimension": 2,
│   │                                    "node_coordinates": "node_x node_y",
│   │                                    "face_node_connectivity": "face_node_connectivity",
│   │                                    "Conventions": "UGRID-1.0, CF-1.8" }
│   ├── node_x                         float64 (n_nodes,)         chunks=(n_nodes,)  BLOSC-ZSTD
│   ├── node_y                         float64 (n_nodes,)
│   ├── face_node_connectivity         int32   (n_faces, max_nv)  _FillValue=-1
│   ├── face_centroid_x                float64 (n_faces,)
│   ├── face_centroid_y                float64 (n_faces,)
│   └── z_interfaces                   float64 (n_layers+1, n_faces)
│
├── head/                              (n_timesteps, n_layers, n_cells)  chunks=(1,n_layers,n_cells)
│   ├── .zattrs                        { "standard_name": "piezometric_head",
│   │                                    "units": "m",
│   │                                    "grid_mapping": "crs" }
│   └── time                           datetime64[ns] (n_timesteps,)
│
├── derived/
│   ├── watertable_elevation           (n_timesteps, n_cells)
│   ├── watertable_depth               (n_timesteps, n_cells)
│   └── seepage_areas                  (n_timesteps, n_cells)   int8 mask
│
├── budget/
│   ├── recharge                       (n_timesteps, n_layers, n_cells)  units="m/s"
│   ├── drain_flux                     idem
│   └── well_flux                      idem
│
├── pathlines/                         (Modpath7 output)
│   ├── particle_id                    int64 (n_particles,)
│   ├── coordinates                    float64 (n_points, 3)
│   ├── time                           float64 (n_points,)  units="s"
│   └── particle_start                 int64 (n_particles,)    offsets
│
└── geographic/                        Rasters statiques
    ├── dem                            (n_y, n_x)
    ├── geology                        (n_y, n_x)
    └── crs                            scalar (string attr grid_mapping)
```

**Décisions par rapport à l'actuel** :
- Zarr **v2** par défaut (Zarr v3 exclut QGIS et ParaView jusqu'en 2027).
- Attributs UGRID-1.0 obligatoires sur `mesh/.zattrs`.
- Attributs CF-1.8 (`standard_name`, `units`, `grid_mapping`) sur **chaque** array de `head/`, `derived/`, `budget/`.

### 8.2 Schéma DuckDB (16 tables)

```sql
-- workspace/hydromodpy.duckdb (schema_version = 2)

-- === Méta-schema ===
CREATE TABLE _schema_version (
    version INTEGER NOT NULL,
    applied_at TIMESTAMP NOT NULL,
    CONSTRAINT pk_schema_version PRIMARY KEY (version)
);

-- === Simulations (table centrale) ===
CREATE TABLE simulations (
    sim_id VARCHAR NOT NULL,                -- UUID4
    project VARCHAR NOT NULL,
    run_name VARCHAR NOT NULL,
    solver VARCHAR NOT NULL,
    solver_version VARCHAR,
    period_start TIMESTAMP NOT NULL,        -- TIMESTAMP, pas VARCHAR
    period_end TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL,
    duration_s DOUBLE,
    status VARCHAR NOT NULL CHECK (status IN ('running','succeeded','failed','cancelled')),
    mesh_hash VARCHAR,                      -- SHA256 mesh
    config_hash VARCHAR,                    -- SHA256 TOML canonique
    CONSTRAINT pk_simulations PRIMARY KEY (sim_id)
);
CREATE INDEX idx_sim_project ON simulations(project);

-- === Paramètres normalisés ===
CREATE TABLE parameters (
    sim_id VARCHAR NOT NULL,
    param_name VARCHAR NOT NULL,
    zone_id VARCHAR NOT NULL DEFAULT '_global',
    value DOUBLE NOT NULL,
    units VARCHAR,
    CONSTRAINT pk_parameters PRIMARY KEY (sim_id, param_name, zone_id),
    CONSTRAINT fk_parameters_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

-- === Time series aux stations ===
CREATE TABLE timeseries (
    sim_id VARCHAR NOT NULL,
    station_id VARCHAR NOT NULL,
    variable VARCHAR NOT NULL,              -- 'head', 'outflow_drain', ...
    timestamp TIMESTAMP NOT NULL,
    value DOUBLE,                            -- NULL si no-data
    CONSTRAINT pk_timeseries PRIMARY KEY (sim_id, station_id, variable, timestamp),
    CONSTRAINT fk_timeseries_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);
CREATE INDEX idx_ts_sim_var ON timeseries(sim_id, variable);

-- === Budgets ===
CREATE TABLE budgets (
    sim_id VARCHAR NOT NULL,
    component VARCHAR NOT NULL,              -- 'recharge', 'drain', ...
    zone_id VARCHAR NOT NULL DEFAULT '_catchment',
    timestamp TIMESTAMP NOT NULL,
    inflow DOUBLE,
    outflow DOUBLE,
    CONSTRAINT pk_budgets PRIMARY KEY (sim_id, component, zone_id, timestamp),
    CONSTRAINT fk_budgets_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

-- === Mass balance global ===
CREATE TABLE mass_balance (
    sim_id VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    total_in DOUBLE NOT NULL,
    total_out DOUBLE NOT NULL,
    storage_change DOUBLE NOT NULL,
    residual DOUBLE NOT NULL,
    percent_error DOUBLE,
    CONSTRAINT pk_mass_balance PRIMARY KEY (sim_id, timestamp),
    CONSTRAINT fk_mass_balance_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

-- === Métriques de performance ===
CREATE TABLE metrics (
    sim_id VARCHAR NOT NULL,
    station_id VARCHAR NOT NULL,
    metric_name VARCHAR NOT NULL,            -- 'nse', 'kge', 'rmse', 'mae'
    value DOUBLE NOT NULL,
    period_start TIMESTAMP,
    period_end TIMESTAMP,
    CONSTRAINT pk_metrics PRIMARY KEY (sim_id, station_id, metric_name),
    CONSTRAINT fk_metrics_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

-- === Points d'observation (stations → cell) ===
CREATE TABLE observation_points (
    sim_id VARCHAR NOT NULL,
    station_id VARCHAR NOT NULL,
    x DOUBLE NOT NULL,
    y DOUBLE NOT NULL,
    cell_id INTEGER NOT NULL,
    layer INTEGER NOT NULL,
    CONSTRAINT pk_observation_points PRIMARY KEY (sim_id, station_id),
    CONSTRAINT fk_obs_points_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

-- === Provenance (PROV-O light) ===
CREATE TABLE provenance (
    sim_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,              -- ex: 'brgm_geology_1_50000'
    source_uri VARCHAR,
    fingerprint VARCHAR NOT NULL,            -- SHA256 du fichier SOURCE (pas du payload parsé)
    stats_json VARCHAR,                      -- {min,max,mean,count} sérialisé
    acquired_at TIMESTAMP NOT NULL,
    CONSTRAINT pk_provenance PRIMARY KEY (sim_id, source_id),
    CONSTRAINT fk_provenance_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

-- === Environnement d'exécution (NOUVEAU — traçabilité FAIR) ===
CREATE TABLE run_environment (
    sim_id VARCHAR NOT NULL,
    hmp_version VARCHAR NOT NULL,
    git_sha VARCHAR,
    python_version VARCHAR NOT NULL,
    platform VARCHAR NOT NULL,
    hostname VARCHAR,
    user_name VARCHAR,
    pip_freeze_hash VARCHAR,                 -- SHA256 d'un pip-freeze trié
    CONSTRAINT pk_run_environment PRIMARY KEY (sim_id),
    CONSTRAINT fk_run_env_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

-- === Calibration ===
CREATE TABLE calibration_sessions (
    session_id VARCHAR NOT NULL,
    project VARCHAR NOT NULL,
    method VARCHAR NOT NULL,                 -- 'grid', 'lhs', 'dream', 'pest'
    objective VARCHAR NOT NULL,
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    n_iterations INTEGER,
    best_sim_id VARCHAR,
    CONSTRAINT pk_calibration_sessions PRIMARY KEY (session_id),
    CONSTRAINT fk_cal_best_sim FOREIGN KEY (best_sim_id) REFERENCES simulations(sim_id)
);

CREATE TABLE calibration_iterations (
    session_id VARCHAR NOT NULL,
    iteration INTEGER NOT NULL,
    sim_id VARCHAR NOT NULL,
    objective_value DOUBLE NOT NULL,
    CONSTRAINT pk_calibration_iterations PRIMARY KEY (session_id, iteration),
    CONSTRAINT fk_cal_iter_session FOREIGN KEY (session_id) REFERENCES calibration_sessions(session_id),
    CONSTRAINT fk_cal_iter_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

-- === Géographique ===
CREATE TABLE geographic_features (
    sim_id VARCHAR NOT NULL,
    feature_name VARCHAR NOT NULL,
    geometry_wkb BLOB,
    crs VARCHAR NOT NULL,
    CONSTRAINT pk_geographic_features PRIMARY KEY (sim_id, feature_name),
    CONSTRAINT fk_geo_feat_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

CREATE TABLE geographic_metadata (
    sim_id VARCHAR NOT NULL,
    key VARCHAR NOT NULL,                    -- 'catch_area', 'dem_res', 'crs'
    value VARCHAR NOT NULL,
    CONSTRAINT pk_geographic_metadata PRIMARY KEY (sim_id, key),
    CONSTRAINT fk_geo_meta_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

-- === Tags & notes (NOUVEAU — collaboration) ===
CREATE TABLE tags (
    sim_id VARCHAR NOT NULL,
    tag VARCHAR NOT NULL,
    CONSTRAINT pk_tags PRIMARY KEY (sim_id, tag),
    CONSTRAINT fk_tags_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

CREATE TABLE notes (
    sim_id VARCHAR NOT NULL,
    author VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    body VARCHAR NOT NULL,
    CONSTRAINT pk_notes PRIMARY KEY (sim_id, author, created_at),
    CONSTRAINT fk_notes_sim FOREIGN KEY (sim_id) REFERENCES simulations(sim_id)
);

-- === Vues ===
CREATE VIEW view_best_per_project AS
SELECT p.project, p.sim_id, m.metric_name, m.value
FROM simulations p
JOIN metrics m USING (sim_id)
WHERE m.station_id = '_outlet'
  AND (p.project, m.metric_name, m.value) IN (
    SELECT project, metric_name, MAX(value)
    FROM simulations JOIN metrics USING (sim_id)
    WHERE station_id = '_outlet'
    GROUP BY project, metric_name);

CREATE VIEW view_solver_category AS
SELECT sim_id,
       CASE solver
         WHEN 'modflow_nwt' THEN 'modflow_family'
         WHEN 'modflow6'    THEN 'modflow_family'
         WHEN 'boussinesq'  THEN 'boussinesq_family'
       END AS category
FROM simulations;
```

**Différences principales avec l'actuel** :
- Toutes les tables ont **PK et FK**. 5 tables étaient sans PK (rapport 07).
- `period_start/period_end` en `TIMESTAMP` (non `VARCHAR`).
- `run_environment`, `tags`, `notes` : NOUVELLES (FAIR, collaboration).
- Migrations effectives (`results/catalog/migrations.py`), non un dict vide.

### 8.3 Format de package portable `.hmp`

```
project_brittany_run_baseline.hmp              (archive zip)
├── manifest.json                               Métadonnées + schema_version + checksums
├── simulations.parquet                         Rows simulations/ pour cette sélection
├── parameters.parquet
├── timeseries.parquet
├── budgets.parquet
├── metrics.parquet
├── observation_points.parquet
├── provenance.parquet
├── run_environment.parquet
├── geographic_features.gpkg                    GeoPackage (pas Shapefile)
├── geographic_metadata.parquet
└── simulations/
    ├── <sim_id_1>.zarr.zip                     Zarr en ZIP (compatible QGIS)
    └── <sim_id_2>.zarr.zip
```

**`manifest.json`** :

```json
{
  "format_version": "1.0",
  "hmp_version": "0.4.0",
  "created_at": "2026-04-18T12:34:56Z",
  "simulation_count": 12,
  "primary_project": "brittany",
  "sim_ids": ["..."],
  "schema_version": 2,
  "checksums_sha256": { "simulations.parquet": "...", "...": "..." },
  "zarr_format": 2,
  "conventions": ["CF-1.8", "UGRID-1.0"]
}
```

---

## 9. Annexe — exemples de code squelette

### 9.1 Simulation API (cible ~150 lignes, vs actuel 705)

```python
# hydromodpy/simulation/api.py  [D+F]
"""Public programmatic API — thin wrapper around execute_simulation()."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from hydromodpy.core.config import HydroModPyConfig
from hydromodpy.core.state import SetupContext, RunContext
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.simulation.planning import SimulationPlanner, SimulationPlan
from hydromodpy.simulation.execution import execute_simulation

class Simulation:
    """Programmatic equivalent of `hmp run config.toml`.

    Example
    -------
    >>> sim = Simulation("project.toml")
    >>> result = sim.run(K=1e-5, Sy=0.05, name="baseline")
    >>> sim.close()
    """
    def __init__(self, config: str | Path | HydroModPyConfig) -> None:
        self.cfg = (
            config if isinstance(config, HydroModPyConfig)
            else HydroModPyConfig.from_toml(config)
        )
        self._setup = SetupContext.from_config(self.cfg)   # immuable, plat
        self._catalog = SimulationCatalog(self.cfg.workspace.root)

    def run(self, *, name: str | None = None, **overrides: Any) -> "SimulationResult":
        """Execute and register. Overrides apply to config via Pydantic model_copy."""
        cfg = self.cfg.with_overrides(overrides) if overrides else self.cfg
        plan: SimulationPlan = SimulationPlanner(cfg).build()
        run_ctx = RunContext(setup=self._setup, catalog=self._catalog, name=name)
        return execute_simulation(plan, run_ctx)   # retourne SimulationResult

    def close(self) -> None:
        self._catalog.close()

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()
```

### 9.2 Ajout d'un solveur — recette 1 fichier

```python
# hydromodpy/solver/ogs6/solver.py  (hypothétique — OpenGeoSys 6)  [N]
from hydromodpy.solver.base import Solver, SolverConfig
from hydromodpy.physics.flow import Flow
from hydromodpy.spatial.mesh import HydroMesh

class OgsSolver(Solver):
    name = "ogs6"

    def solve_flow(self, flow: Flow, mesh: HydroMesh, time_grid) -> SolveResult:
        # 1. Traduire Flow → XML project file OGS
        xml_path = self._translate(flow, mesh, time_grid)
        # 2. Invoquer exécutable ogs
        self._invoke(xml_path)
        # 3. Lire résultats VTU et renvoyer SolveResult
        return self._extract(output_dir=xml_path.parent)
```

```python
# hydromodpy/simulation/adapters/flow_ogs6.py  [N]
from hydromodpy.simulation.adapters.base import SolverAdapter
from hydromodpy.simulation.adapters.registry import register_adapter
from hydromodpy.solver.ogs6 import OgsSolver

@register_adapter(process_type="flow", solver_name="ogs6")
class FlowOgs6Adapter(SolverAdapter):
    def execute(self, run, ctx): ...
    def extract(self, run, ctx): ...
```

**C'est tout.** Pas besoin de toucher `core/`, `physics/`, `spatial/`, `data/`, `results/`. L'ajout d'un solveur = 2 fichiers, 1 package.

### 9.3 Ajout d'un format d'export — recette 1 fichier

```python
# hydromodpy/results/io/exporters/parquet.py  [N]
from hydromodpy.results.io.registry import register_exporter
from hydromodpy.results.io.exporter_base import Exporter

@register_exporter(format_name="parquet", extension=".parquet")
class ParquetExporter(Exporter):
    def export_field(self, array, path, metadata): ...
    def export_timeseries(self, df, path, metadata): ...
```

CLI reconnaît automatiquement : `hmp export <sim_id> --format parquet`.

### 9.4 Ajout d'une variable de données — recette 1 dossier

```python
# hydromodpy/data/variables/snow/config.py  [N]
from pydantic import BaseModel, ConfigDict, Field
from hydromodpy.data.timeseries import TimeseriesSourceConfig

class SnowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    source: TimeseriesSourceConfig = Field(...)

# hydromodpy/data/variables/snow/manager.py  [N]
from hydromodpy.data.base_manager import BaseVariableManager
from .config import SnowConfig

class SnowManager(BaseVariableManager):
    kind = "snow"
    config_cls = SnowConfig
    def load(self, cfg: SnowConfig, ctx) -> "SnowResult": ...
```

**C'est tout.** `DataPlanner` détecte automatiquement via le registre `BaseVariableManager.__subclasses__` si `snow` apparaît dans le TOML.

### 9.5 Test du DAG d'imports

```python
# tests/unit/test_import_dag.py  [N]
"""Verify the package import DAG respects the declared architecture."""
from __future__ import annotations
import ast, pathlib, pytest

ROOT = pathlib.Path(__file__).parents[2] / "hydromodpy"
ALLOWED: dict[str, set[str]] = {
    "core":       set(),
    "data":       {"core"},
    "spatial":    {"core", "data"},
    "physics":    {"core", "spatial"},                          # data lazy only
    "solver":     {"core", "spatial", "physics"},
    "results":    {"core"},                                      # spatial/physics/solver lazy
    "simulation": {"core", "data", "spatial", "physics", "solver", "results"},
    "analysis":   {"core", "data", "spatial", "physics", "simulation", "results"},
    "_cli":       {"core", "data", "spatial", "physics", "solver",
                   "simulation", "results", "analysis"},
}

def _top_pkg(mod: str) -> str | None:
    parts = mod.split(".")
    return parts[1] if len(parts) >= 2 and parts[0] == "hydromodpy" else None

def _file_pkg(p: pathlib.Path) -> str:
    rel = p.relative_to(ROOT)
    return rel.parts[0]

@pytest.mark.parametrize("py_file", list(ROOT.rglob("*.py")))
def test_no_forbidden_imports(py_file):
    src = py_file.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(py_file))
    src_pkg = _file_pkg(py_file)
    allowed = ALLOWED[src_pkg] | {src_pkg}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            top = _top_pkg(mod)
            if top and top not in allowed:
                # Tolérance : import à l'intérieur d'une fonction = lazy OK
                if _is_inside_function(node, tree):
                    continue
                pytest.fail(f"{py_file}: forbidden import hydromodpy.{top} from package '{src_pkg}'")
```

---

## 10. Synthèse — 5 actions structurelles majeures

| # | Action | Effet |
|---|---|---|
| 1 | **`core/` devient feuille** : imports lazy dans `aggregate_config.py`, déplacer `io/http_client.py`, `io/crs.py`, `exceptions.py`. | Architecture annoncée = architecture réelle. Test DAG passe. |
| 2 | **`solver/utils/mesh/` → `spatial/mesh/`** | Élimine la dépendance inversée `spatial → solver`. Profondeur d'import réduite de 6 → 4. |
| 3 | **`process/` → `physics/` + `project.py` → `simulation/api.py`** | Nommage sans ambiguïté. Classe `Simulation` réduite de 705 → 150 lignes. |
| 4 | **`__main__.py` → `_cli/commands/`** + `runners/` → `simulation/workflows/` | Un fichier par commande ≤ 80 lignes. UN seul orchestrateur par workflow. |
| 5 | **Suppression de `watershed/`, `exceptions.py` mort, climatic legacy, `hmp test`** | ~9 600 lignes gagnées. Trois générations de code → deux. |

Ces cinq actions — `core` feuille, `spatial/mesh` consolidé, `physics/` + `simulation/api.py`, `_cli/` éclaté, code mort éliminé — **suffisent à passer d'un projet en accrétion à un projet industriel**. Le reste (factorisations, standards CF/UGRID, bornes physiques, benchmarks Theis/Hantush) s'appuie dessus sans friction.

---

*Fin du document — Architecture cible, structure des packages.*
*Prochain document attendu : `02_modele_donnees.md` (schémas DuckDB détaillés, layout Zarr complet, formats `.hmp`).*
