# Prompt : implementation du Simulation Catalog

Copier-coller ce prompt dans une nouvelle session Claude Code.

---

## Prompt

Tu es expert en architecture logiciel et bases de donnees. Ta mission est d'implementer la nouvelle architecture "Simulation Catalog" pour HydroModPy.

Le document de reference complet est dans :
`docs/developers/simulation_catalog_architecture.md`

Lis-le en entier avant de commencer. Il contient le schema DuckDB (12 tables), le layout Zarr, l'API Python (3 niveaux), le pipeline d'execution, l'import/export, la calibration, le display solver-agnostique, le versioning du schema, et les requetes SQL de reference.

### Contexte

HydroModPy est un toolbox Python pour la modelisation hydrogéologique. L'architecture actuelle utilise N `project.duckdb` (un par projet) + un `catalog.duckdb` (workspace) avec duplication partielle. On remplace tout ca par une seule base `hydromodpy.duckdb` au workspace + un Zarr isole par simulation.

On ne migre pas l'existant. On repart de zero. Le code existant dans `hydromodpy/results/` (store.py, schema.py, zarr_layout.py, exporters/, etc.) est a remplacer, pas a adapter. Le code existant dans `hydromodpy/data/registry/catalog_duckdb.py` est a renommer/simplifier (il ne gere plus que le cache d'entree, plus le simulation_registry).

### Structure cible sur disque

```
workspace/
├── hydromodpy.duckdb              # source de verite unique
├── data/
│   ├── cache.duckdb               # cache des donnees d'entree uniquement
│   └── <variable>/                # fichiers bruts (CSV, NC, TIF)
├── simulations/                   # un Zarr par simulation
│   └── <uuid>.zarr/
└── configs/                       # TOMLs utilisateur (organisation libre)
```

### Ordre d'implementation

Phase 1 : le socle (schema + store)

1. Creer `hydromodpy/results/schema.py` : toutes les tables du schema (section 3 du .md), incluant `_schema_version` et `ensure_schema()` (section 14). 12 tables + 1 table de version.

2. Creer `hydromodpy/results/catalog.py` : la classe `SimulationCatalog`.
   - `__init__(workspace_path)` : ouvre/cree `hydromodpy.duckdb`, appelle `ensure_schema()`, decouvre le dossier `simulations/`
   - `register_simulation(...)` : INSERT dans simulations + parameters + creation du Zarr
   - `write_timeseries(sim_id, ...)`, `write_budget(...)`, `write_mass_balance(...)`, `write_metric(...)`, `write_provenance(...)` : ecritures standard
   - `finalize(sim_id, status, duration_s)` : UPDATE simulations
   - `delete(sim_id)` : DELETE cascade + suppression du Zarr
   - `close()` : fermeture propre
   - propriete `connection` : acces DuckDB brut

3. Creer `hydromodpy/results/zarr_store.py` : gestion du Zarr par simulation.
   - `create(sim_path)` : cree le Zarr v3 DirectoryStore
   - `write_mesh(vertices, connectivity, z_interfaces)`
   - `write_field(variable, timestep, values, subgroup=None)`
   - `read_field(variable, timestep, subgroup=None)`
   - `write_geographic_raster(name, data, transform, crs, nodata)`
   - `read_geographic_raster(name)`
   - layout standardise (mesh/, head/, derived/, budget/, pathlines/, geographic/)
   - compression BLOSC-ZSTD, chunking (1, n_layers, n_cells)

Phase 2 : l'API Python haut niveau

4. Creer `hydromodpy/results/simulation.py` : la classe `Simulation`.
   - wraps sim_id + reference au catalog
   - proprietes : id, name, project, solver, solver_category, config, parameters, metrics, provenance, tags, created_at, duration_s, status, flow_regime
   - methodes donnees : `timeseries(variable, station)`, `budget(component)`, `mass_balance`, `field(variable, timestep)`, `mesh`
   - methodes export : `to_netcdf(variable)`, `to_geotiff(variable, timestep, resolution)`, `to_shapefile(variable, timestep)`, `to_csv()`, `to_vtu(variable, timestep)`
   - methodes geographic : `geographic(feature_name)` → GeoDataFrame, `geographic_raster(name)` → ndarray + metadata
   - `export(output_path)` : cree le package .hmp
   - `rerun(**overrides)` : relance avec parent_sim_id
   - `plot(figure_name, save=None)`, `plot_all(save=None)`, `display_capabilities`

5. Creer `hydromodpy/results/simulation_group.py` : la classe `SimulationGroup`.
   - wraps une liste de sim_ids + reference au catalog
   - proprietes : count, parameters (DataFrame pivot), metrics (DataFrame pivot)
   - methodes : `compare(metric)`, `best(metric)`, `worst(metric)`, `sort_by(metric)`, `to_dataframe()`, `to_csv(path)`

6. Ajouter les methodes de requete sur `SimulationCatalog` :
   - `find(**filters)` → SimulationGroup (project=, solver=, status=, tags=, nse_gt=, etc.)
   - `__getitem__(sim_id)` → Simulation
   - `latest(project)` → Simulation
   - `best(project, metric)` → Simulation
   - `sql(query)` → DataFrame
   - `export_simulation(sim_id, path)` et `import_simulation(path)`
   - `cleanup(status=None, older_than=None)`
   - propriete `simulations` → DataFrame de toutes les sims

7. Creer `hydromodpy/catalog.py` (ou modifier `hydromodpy/__init__.py`) : la fonction `hmp.open(workspace_path)` → SimulationCatalog.

Phase 3 : integration avec le pipeline existant

8. Modifier `hydromodpy/workflow/steps/store_lifecycle.py` : remplacer ResultStore par SimulationCatalog.
   - `step_open_store(ctx)` : ouvre le catalog, genere sim_id, register_simulation
   - `step_finalize_store(ctx)` : finalize, close

9. Modifier les extractors dans `hydromodpy/simulation/results/extractors/` : adapter pour ecrire dans SimulationCatalog au lieu de ResultStore. L'interface d'ecriture (write_field, write_timeseries, etc.) est la meme, seul le backing store change.

10. Modifier `hydromodpy/project.py` : remplacer ResultStore par SimulationCatalog. Le Project ouvre le catalog du workspace, chaque .run() cree une simulation dans le catalog.

11. Modifier `hydromodpy/data/registry/catalog_duckdb.py` : renommer le fichier en `cache.duckdb` au lieu de `catalog.duckdb`. Supprimer la table `simulation_registry` et tout le code associe (create_registry_table, _write_to_registry). Ne garder que la table `entries` pour le cache d'entree.

Phase 4 : import/export et calibration

12. Implementer `export_simulation()` et `import_simulation()` dans SimulationCatalog (section 10 du .md). Format .hmp = dossier avec simulation.duckdb + results.zarr/.

13. Modifier `hydromodpy/analysis/calibration/engine/session.py` : ajouter `persist(catalog)` qui ecrit calibration_sessions + calibration_iterations en bulk a la fin de la session. L'execution de la calibration reste en memoire (pas de changement sur le hot path).

Phase 5 : display solver-agnostique

14. Implementer `display_capabilities` et `plot()` sur Simulation (section 8 du .md). Le display determine les figures possibles a partir de solver_category, n_layers, flow_regime, et la presence des variables dans le Zarr. Pas besoin de connaitre le solver specifique.

### Contraintes

- Pas de migration de l'existant, on repart de zero
- Pas de linting/formatting (ruff, black, mypy ne sont pas configures)
- Tests avec `pytest tests/unit/ -n auto -v`
- Le code existant dans `hydromodpy/results/store.py` est la reference pour comprendre les patterns actuels, mais il sera remplace
- DuckDB : pas de SQLAlchemy, API native uniquement
- Zarr v3 avec DirectoryStore, compression BLOSC-ZSTD
- Toutes les ecritures DB sont post-solver (jamais pendant l'execution du solver)
- La calibration ecrit en bulk a la fin (zero overhead pendant l'optimisation)
- Les figures ne sont pas stockees, elles sont regenerees a la demande
- Repondre en francais

### Ce qu'il ne faut PAS faire

- Ne pas creer de `simulation_registry` (dead code dans l'ancienne archi)
- Ne pas dupliquer les metadonnees entre fichiers
- Ne pas creer de dossier `projects/` avec des sous-dossiers par projet
- Ne pas utiliser de JSON blob pour les parametres (table `parameters` normalisee)
- Ne pas ajouter de docstrings/commentaires inutiles, garder le code concis
- Ne pas creer de fichiers README ou documentation supplementaire
- Ne pas modifier le schema TOML de configuration (hors scope)
- Ne pas toucher aux solvers (modflownwt, modflow6, boussinesq)
- Ne pas toucher aux data managers (sauf le renommage de catalog_duckdb.py)

### Pour commencer

Lis `docs/developers/simulation_catalog_architecture.md` en entier, puis lis le code existant dans `hydromodpy/results/store.py` et `hydromodpy/results/schema.py` pour comprendre les patterns actuels. Propose un plan detaille pour la Phase 1 avant de coder.
