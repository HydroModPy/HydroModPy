# Architecture du module `simulation/results/`

## Objectif

Fournir une **interface unifiee** pour stocker, interroger et exporter les
resultats de simulation, quel que soit le solveur (MODFLOW-NWT, MODFLOW 6,
MT3DMS, MODPATH, GR4J). L'utilisateur interagit avec un seul objet
`ResultStore` qui masque la complexite du stockage sous-jacent.

---

## 1. Probleme actuel

Les sorties sont aujourd'hui gerees de maniere ad-hoc :

- Dossiers de sortie avec organisation propre a chaque run
- Fichiers heterogenes : `.shp`, `.nc`, `.csv`, `.npy`, fichiers bruts solver
  (`.hds`, `.cbc`, `.ucn`)
- Pas d'interface unifiee : chaque post-traitement est bricole
- Pas de requetes inter-simulations possibles
- Pas de metadonnees exploitables apres fermeture
- Les fichiers propriétaires du solveur trainent sur le disque sans qu'on
  sache lesquels sont encore utiles

---

## 2. Decision architecturale : approche hybride

Apres analyse comparative (DuckDB, SQLite/SpatiaLite, HDF5, NetCDF-4, Zarr,
TileDB, GeoPackage, Parquet), l'architecture retenue est **hybride** :

| Couche | Technologie | Contenu |
|--------|-------------|---------|
| Catalogue & series | **DuckDB** | Metadonnees, config, series temporelles ponctuelles, bilans de masse, index vers les arrays |
| Champs volumiques | **Zarr v3** | Champs spatiaux `(timestep, layer, cell_id)`, topologie du maillage (UGRID) |
| Export interoperable | **NetCDF-4/UGRID** | Fichiers de partage pour QGIS (MDAL), THREDDS, outils tiers |
| Export visualisation | **VTU** (via meshio) | Pour ParaView / PyVista |

### DuckDB unifie : un seul moteur de base de donnees

DuckDB remplace SQLite + SQLAlchemy comme moteur de base de donnees pour
**tout** le framework. Deux fichiers DuckDB coexistent a des niveaux differents :

| Fichier | Scope | Contenu |
|---------|-------|---------|
| `workspace/catalog.duckdb` | Workspace (partage entre projets) | Catalogue data (entries, api_coverage) + registre des simulations (simulation_registry) |
| `projects/{name}/project.duckdb` | Projet | Resultats de simulation (simulations, timeseries, budgets, ...) |

Le catalogue data reste au **niveau workspace** car les donnees telechargees
(Hub'Eau, SIM2, etc.) sont partagees entre projets. Un index par projet
dupliquerait les telechargements inutilement.

Les requetes croisees data/resultats utilisent `ATTACH` :

```sql
ATTACH 'workspace/catalog.duckdb' AS catalog;
SELECT s.name, e.station_id, e.date_start, e.date_end
FROM simulations s
JOIN catalog.entries e ON e.station_id = ...;
```

Justification :
- A ~1000 lignes dans le catalogue, la distinction OLTP/OLAP est sans objet
- Un seul langage SQL, un seul moteur, zero dependance SQLAlchemy
- Les requetes croisees data/resultats sont possibles via `ATTACH`
- DuckDB lit nativement les fichiers SQLite existants via `ATTACH` (migration)

### Concurrence et robustesse

`catalog.duckdb` est partage entre projets. Si deux simulations sur des
projets differents tournent en parallele, leurs `finalize()` ecrivent
dans le meme fichier. Strategie :

- **WAL mode** : DuckDB utilise un Write-Ahead Log qui permet des lectures
  concurrentes pendant les ecritures. Active par defaut.
- **Retry on BUSY** : si une ecriture echoue (verrou exclusif deja pris),
  retry avec backoff exponentiel (3 tentatives, 100ms/200ms/400ms).
  L'ecriture dans `simulation_registry` est une seule ligne INSERT -
  la fenetre de conflit est de l'ordre de la milliseconde.
- **Transactions courtes** : chaque ecriture dans `catalog.duckdb` est une
  transaction atomique independante. Pas de transaction longue qui
  bloquerait les autres writers.
- **project.duckdb** : pas de probleme de concurrence - un seul projet
  a la fois ecrit dans son propre fichier.

```python
import duckdb
import time

def _write_to_registry(catalog_path, row, retries=3):
    """Ecriture avec retry pour gerer la concurrence."""
    for attempt in range(retries):
        try:
            conn = duckdb.connect(str(catalog_path))
            conn.execute("INSERT OR REPLACE INTO simulation_registry ...", row)
            conn.close()
            return
        except duckdb.IOException:
            if attempt < retries - 1:
                time.sleep(0.1 * (2 ** attempt))
            else:
                raise
```

### Pourquoi pas une solution unique ?

- **DuckDB seul** : anti-pattern pour les champs volumiques. Une table
  `(sim_id, timestep, layer, cell_id, value)` atteindrait ~1.8 milliard de
  lignes pour une simulation typique (500k cellules x 10 couches x 365 pas de
  temps). L'acces array direct est O(1) vs O(log n) en base relationnelle.
  Benchmarks FoxBench (DLR, 2025) confirment la superiorite de Zarr/NetCDF-4
  pour les lectures denses n-dimensionnelles.

- **Zarr seul** : pas de SQL, requetes inter-simulations penibles, pas de
  filtrage par parametres de configuration.

- **HDF5** : verrou global (GIL niveau C), handles non fork-safe (probleme
  PyTorch DataLoader multi-workers). Zarr v3 avec sharding resout le probleme
  historique "1 fichier par chunk".

- **TileDB** : ecarte. Benchmarks FoxBench defavorables pour donnees denses.
  Pertinent uniquement si forte sparsite (wetting/drying massif).

---

## 3. Contrainte maillage non-structure

HydroModPy utilise un pivot unifie `HydroMesh` pour toutes les grilles. Meme
les grilles structurees sont manipulees comme non-structurees. Les champs
spatiaux ne sont pas des arrays reguliers (i,j,k) mais des **vecteurs indexes
par cell_id** avec connectivite explicite.

### Structures internes existantes

```python
# Maillage 2D - hydromodpy/spatial/mesh/hydro_mesh.py
@dataclass(frozen=True)
class HydroMesh:
    vertices: np.ndarray              # (n_nodes, 2|3) float64
    cell_blocks: tuple[CellBlock, ...]
    cell_data: dict[str, np.ndarray]  # (n_cells,) par champ
    point_data: dict[str, np.ndarray] # (n_nodes,) par champ
    structured_shape: tuple[int, ...] | None

@dataclass(frozen=True)
class CellBlock:
    cell_type: CellType               # TRIANGLE | QUADRILATERAL | WEDGE | HEXAHEDRON
    connectivity: np.ndarray          # (n_cells, nodes_per_cell) int

# Maillage 3D extrude - gmsh_grid/extruded_prism_mesh.py
@dataclass(frozen=True)
class ExtrudedPrismMeshData:
    points_xyz: np.ndarray            # (n_nodes, 3)
    prism_connectivity: np.ndarray    # (n_prisms, 6|8)
    cell_type_2d: str                 # "triangle" | "quadrilateral"
    z_interfaces: np.ndarray          # (nz,) limites verticales
    layer_indices: np.ndarray         # (n_prisms,) couche par prisme
    source_cell_indices: np.ndarray   # (n_prisms,) cellule 2D source

# Champs attaches - gmsh_grid/extruded_mesh_values.py
@dataclass(frozen=True)
class ExtrudedPrismMeshWithValues:
    mesh: ExtrudedPrismMesh3D
    values_3d: np.ndarray             # (nlay, n_cells_2d)
    label: str | None
    prism_center_depths: np.ndarray | None
    metadata: Mapping[str, Any] | None
```

### Consequences pour le stockage

- Les champs sont des numpy arrays `(nlay, n_cells_2d)` - pas de DataFrame
- La connectivite est un array `(n_cells, max_nodes_per_face)` avec fill=-1
  pour les maillages mixtes tri/quad (convention UGRID)
- Taille typique : 50k-500k cellules 2D x 1-10 couches x 365+ pas de temps
- Chaque simulation peut avoir un maillage different (nombre de cellules,
  type de cellules) : pas de schema fixe entre simulations

---

## 4. Separation des responsabilites : Data Managers vs ResultStore

Le framework manipule deux familles de donnees distinctes. Elles vivent dans
des stores separes, sans duplication.

### Qui stocke quoi ?

Les deux domaines vivent dans des **fichiers DuckDB separes** a des niveaux
differents. Le catalogue data est partage entre projets (niveau workspace),
les resultats sont propres a chaque projet.

```
workspace/
├── catalog.duckdb                     # Partage entre projets
│   ┌──────────────────────┐
│   │ entries              │  Catalogue des donnees d'entree
│   │ api_coverage         │  (pluie, ETP, piezo, hydro, ...)
│   │                      │
│   │ simulation_registry  │  Annuaire de TOUTES les simulations
│   │                      │  de tous les projets (decouverte,
│   │                      │  recherche inter-projets)
│   │                      │
│   │ Scope : workspace    │
│   └──────────────────────┘
│
├── data/                              # Fichiers cache partages
│   ├── hydrometry/*.csv
│   ├── precipitation/*.nc
│   └── ...
│
└── projects/{name}/
    ├── project.duckdb                 # Propre au projet
    │   ┌──────────────────────────┐
    │   │ simulations              │  Catalogue complet + config
    │   │ timeseries               │  Series temporelles
    │   │ budgets                  │  Bilans de masse
    │   │ metrics                  │  Metriques de calibration
    │   │ observation_points       │  Mapping station → cellule
    │   │ mass_balance_summary     │  Bilan global (listing)
    │   │ input_provenance         │  Fingerprint des entrees
    │   │                          │
    │   │ Scope : UN projet        │
    │   └──────────────────────────┘
    │
    └── project_results.zarr/          # Champs volumiques
```

Le `simulation_registry` dans `catalog.duckdb` est un **annuaire leger**
qui indexe toutes les simulations de tous les projets. Il ne duplique pas
les donnees - il stocke juste assez de metadonnees pour la decouverte et
la recherche inter-projets. Les details complets restent dans chaque
`project.duckdb`.

Les requetes croisees utilisent DuckDB `ATTACH` :

```python
conn = duckdb.connect("projects/canut/project.duckdb")
conn.execute("ATTACH '../../catalog.duckdb' AS catalog")
# JOIN direct entre tables resultats et catalogue data
```

**Regle** : le ResultStore ne stocke PAS les forcages (recharge, pluie, ETP)
ni les donnees observees. Il stocke uniquement ce que le solveur **produit**.

Les donnees brutes et extraites restent dans les data managers. Pour la
comparaison simule/observe (calibration, figures), le code interroge les
deux stores independamment :

```python
# Comparaison simule / observe
simulated = result_store.query_timeseries(sim_id, station="P1", variable="head")
observed  = data_manager.piezometry.load(station="P1", period=...)
plot_comparison(simulated, observed)
```

### Tracabilite des entrees (provenance)

Le probleme : la config TOML dit "utilise la recharge SIM2 2020-2024", mais
si les donnees source changent dans les data managers apres le run, on perd
la trace de ce qui a reellement ete injecte dans le solveur.

La solution : le ResultStore stocke un **fingerprint** leger (hash SHA-256 +
statistiques) des donnees effectivement utilisees - pas les donnees elles-memes.
Cela permet de detecter toute divergence sans dupliquer les forcages.

```python
import hashlib
import numpy as np

def fingerprint(data: np.ndarray) -> dict:
    """Fingerprint leger d'un array de forcage."""
    return {
        "checksum": hashlib.sha256(data.tobytes()).hexdigest(),
        "shape": list(data.shape),
        "dtype": str(data.dtype),
        "stats": {
            "mean": float(np.mean(data)),
            "min": float(np.min(data)),
            "max": float(np.max(data)),
            "std": float(np.std(data)),
        },
    }
```

Verification 6 mois plus tard :

```python
prov = store.get_provenance(sim_id, "recharge")
current_data = data_manager.recharge.load(period=prov.period)
current_hash = hashlib.sha256(current_data.tobytes()).hexdigest()

if current_hash != prov.checksum:
    print("Les donnees source ont change depuis ce run !")
    print(f"Run : mean={prov.stats['mean']:.4f}")
    print(f"Now : mean={current_data.mean():.4f}")
```

### Typologie des donnees stockees dans le ResultStore

| Type | Exemple | Volume | Stockage |
|------|---------|--------|----------|
| Metadonnees | Config TOML, parametres Pydantic, dates, metriques | ~Ko | DuckDB |
| Provenance entrees | Hash + stats des forcages injectes | ~Ko | DuckDB |
| Series temporelles ponctuelles | H(t) a un piezo, Q(t) a l'exutoire | Ko-Mo | DuckDB |
| Champs spatiaux sur maillage x temps | Head(cell_id, layer, t), Concentration | Mo-Go | Zarr v3 |
| Bilans de masse / budgets | Flux par zone, erreur de bilan | Ko | DuckDB |
| Trajectoires de particules | MODPATH pathlines (particle, t) -> (x,y,z) | Mo | Zarr v3 |
| Geometrie du maillage | HydroMesh complet (vertices + connectivity) | Mo | Zarr v3 (1 fois/sim) |
| Fichiers bruts solver | .hds, .cbc, .ucn (archivage/debug) | Go | Supprimes apres ingestion (sauf config) |

### Solveur integre vs distribue

| | Integre (GR4J, GR2M...) | Distribue (MODFLOW, MT3DMS...) |
|---|---|---|
| Sortie spatiale | 1 point (BV) ou quelques sous-BV | Maillage non-structure, milliers de cellules |
| Serie temporelle | Q(t), S(t) a l'exutoire | H(x,y,z,t) partout |
| Volume | Ko-Mo | Mo-Go |
| Maillage | Aucun | HydroMesh complet |

L'interface `ResultStore` est la meme pour les deux cas. Pour un modele
integre, les champs Zarr sont simplement absents (tout est dans DuckDB).

---

## 5. Layout Zarr (convention UGRID)

Chaque simulation possede son propre groupe Zarr avec topologie independante.
Le maillage est stocke une seule fois, les champs sont des datasets 3D
`(ntimesteps, nlayers, ncells)`.

```
project_results.zarr/
|
+-- {sim_uuid}/
    |
    +-- mesh/                              # Topologie (stockee 1 fois)
    |   +-- vertices                       # (n_nodes, 2|3) float64
    |   +-- face_node_connectivity         # (n_cells, max_vpf) int32, fill=-1
    |   +-- z_interfaces                   # (nz,) float64
    |   +-- layer_indices                  # (n_prisms,) int32
    |   +-- source_cell_indices            # (n_prisms,) int32
    |   +-- .zattrs                        # cell_types, start_index, n_layers...
    |
    +-- head                               # (ntimesteps, nlayers, ncells) float64
    +-- concentration                      # (ntimesteps, nlayers, ncells) float64
    |
    +-- derived/                           # Variables derivees (configurable)
    |   +-- watertable_elevation           # (ntimesteps, ncells) float64 - 2D
    |   +-- watertable_depth               # (ntimesteps, ncells) float64 - 2D
    |   +-- seepage_areas                  # (ntimesteps, ncells) bool - 2D
    |   +-- groundwater_flux               # (ntimesteps, nlayers, ncells) float64
    |   +-- accumulation_flux              # (ntimesteps, ncells) float64 - 2D
    |   +-- concentration_seepage          # (ntimesteps, ncells) float64 - 2D
    |   +-- mass_seepage                   # (ntimesteps, ncells) float64 - 2D
    |   +-- mass_accumulated               # (ntimesteps, ncells) float64 - 2D
    |
    +-- budget/                            # Champs spatiaux par composante (optionnel)
    |   +-- drn                            # (ntimesteps, nlayers, ncells)
    |   +-- rch                            # (ntimesteps, ncells)
    |   +-- wel                            # (ntimesteps, nlayers, ncells)
    |   +-- riv                            # (ntimesteps, nlayers, ncells)
    |   +-- ghb                            # (ntimesteps, nlayers, ncells)
    |   +-- sto                            # (ntimesteps, nlayers, ncells)
    |   +-- flow_ja_face                   # (ntimesteps, n_link_faces)
    |
    +-- pathlines/                         # MODPATH
        +-- x                              # (n_particles, n_steps) float64
        +-- y
        +-- z
        +-- time
```

### Chunking et compression

```python
# Chunking optimal : 1 chunk = 1 pas de temps complet
# Pour 500k cellules x 10 couches x float64 = ~40 Mo/chunk
chunks = (1, nlayers, ncells)

# Compression : Blosc + Zstd, ratio ~2-3x sur donnees hydrologiques
compressor = zarr.codecs.BloscCodec(cname='zstd', clevel=3)
```

Le sharding Zarr v3 elimine le probleme "1 fichier par chunk" : un shard
unique contient tous les chunks avec un index interne.

---

## 6. Schema DuckDB

Deux fichiers DuckDB a des scopes differents :

- **`workspace/catalog.duckdb`** : catalogue data partage (voir `data/structure.md`
  section 6 pour le schema complet des tables `entries` et `api_coverage`)
  + registre des simulations (table `simulation_registry` ci-dessous)
- **`projects/{name}/project.duckdb`** : resultats de simulation (tables ci-dessous)

### Registre des simulations (`catalog.duckdb`)

Annuaire leger de toutes les simulations de tous les projets. Permet la
recherche inter-projets sans ouvrir chaque `project.duckdb`. Alimente
automatiquement par `ResultStore.finalize()`.

```sql
CREATE TABLE simulation_registry (
    sim_id         UUID PRIMARY KEY,
    project        VARCHAR NOT NULL,    -- nom du projet ('canut', 'nancon', ...)
    project_path   TEXT NOT NULL,       -- chemin relatif vers project.duckdb

    -- Identification
    name           VARCHAR,             -- nom libre de la simulation
    description    VARCHAR,             -- description libre
    tags           VARCHAR[],           -- tags utilisateur ['calibration', 'v2', ...]
    created_at     TIMESTAMP DEFAULT now(),

    -- Solver et modele
    solver         VARCHAR NOT NULL,    -- 'modflownwt' | 'modflow6' | 'gr4j' | ...
    process_types  VARCHAR[],          -- ['flow'] | ['flow', 'transport'] | ['flow', 'pathline']
    status         VARCHAR NOT NULL,    -- 'completed' | 'failed' | 'calibrated'

    -- Maillage
    n_cells        INTEGER,             -- nombre de cellules 2D
    n_layers       INTEGER,             -- nombre de couches
    cell_types     VARCHAR[],           -- ['triangle'] | ['triangle', 'quad']
    bbox           DOUBLE[4],           -- [xmin, ymin, xmax, ymax]
    crs            VARCHAR,             -- 'EPSG:2154'

    -- Temporel
    n_timesteps    INTEGER,
    period_start   DATE,                -- debut de la simulation
    period_end     DATE,                -- fin de la simulation
    time_unit      VARCHAR,             -- 'days' | 'seconds'

    -- Execution
    duration_s     DOUBLE,              -- temps de calcul (secondes)

    -- Metriques cles (denormalisees pour la recherche rapide)
    -- Remplies depuis la table metrics du project.duckdb au finalize()
    best_nse       DOUBLE,              -- max NSE toutes stations
    best_kge       DOUBLE,              -- max KGE toutes stations
    best_rmse      DOUBLE,              -- min RMSE toutes stations
    n_observation_points INTEGER,       -- nombre de points d'observation

    -- Provenance (resume)
    forcing_sources VARCHAR[],          -- ['recharge/sim2', 'precipitation/sim2', ...]
    config_hash     VARCHAR             -- SHA-256 du config_toml (detecter les reruns)
);

CREATE INDEX ix_registry_project ON simulation_registry(project);
CREATE INDEX ix_registry_solver ON simulation_registry(solver);
CREATE INDEX ix_registry_status ON simulation_registry(status);
CREATE INDEX ix_registry_created ON simulation_registry(created_at);
```

#### Champs du registre - justification

| Groupe | Champs | Pourquoi |
|--------|--------|----------|
| Identification | project, name, tags, description | Decouverte ("toutes les sims du projet canut tagees calibration") |
| Solver | solver, process_types, status | Filtrage par type de modele et etat |
| Maillage | n_cells, n_layers, cell_types, bbox, crs | Comparaison de complexite, localisation spatiale |
| Temporel | n_timesteps, period_start, period_end | Couverture temporelle |
| Execution | duration_s | Benchmarking, estimation du temps pour de futurs runs |
| Metriques | best_nse, best_kge, best_rmse | Recherche rapide des meilleurs runs sans drill-down |
| Provenance | forcing_sources, config_hash | Detecter les doublons, tracer les sources de donnees |

#### Requetes inter-projets (exemples)

```sql
-- Meilleur NSE tous projets confondus
SELECT project, name, solver, best_nse, period_start, period_end
FROM simulation_registry
WHERE status = 'calibrated'
ORDER BY best_nse DESC
LIMIT 10;

-- Toutes les simulations MODFLOW6 avec gros maillage
SELECT project, name, n_cells, n_layers, duration_s
FROM simulation_registry
WHERE solver = 'modflow6' AND n_cells > 100000
ORDER BY n_cells DESC;

-- Performance moyenne par bassin versant
SELECT project, COUNT(*) AS n_runs,
       AVG(best_nse) AS mean_nse,
       MIN(duration_s) AS fastest,
       MAX(duration_s) AS slowest
FROM simulation_registry
WHERE status IN ('completed', 'calibrated')
GROUP BY project;

-- Simulations utilisant la recharge SIM2
SELECT project, name, best_nse
FROM simulation_registry
WHERE list_contains(forcing_sources, 'recharge/sim2');

-- Detecter les reruns identiques (meme config)
SELECT config_hash, COUNT(*) AS n_runs,
       array_agg(project || '/' || name) AS runs
FROM simulation_registry
GROUP BY config_hash
HAVING COUNT(*) > 1;

-- Drill-down : une fois la simulation trouvee, charger les details
ATTACH 'projects/canut/project.duckdb' AS canut;
SELECT * FROM canut.timeseries WHERE sim_id = 'uuid-trouve-ci-dessus';
```

### Tables resultats de simulation (`project.duckdb`)

```sql
-- Catalogue des simulations
CREATE TABLE simulations (
    sim_id        UUID PRIMARY KEY,
    name          VARCHAR,
    created_at    TIMESTAMP DEFAULT now(),
    config_toml   JSON,          -- config complete serialisee
    solver        VARCHAR,       -- 'modflownwt' | 'modflow6' | 'gr4j' | ...
    n_cells       INTEGER,
    n_layers      INTEGER,
    n_timesteps   INTEGER,
    cell_types    VARCHAR[],     -- ['triangle', 'quad']
    bbox          DOUBLE[4],     -- [xmin, ymin, xmax, ymax]
    zarr_group    VARCHAR,       -- chemin vers le groupe Zarr
    status        VARCHAR,       -- 'running' | 'completed' | 'failed'
    duration_s    DOUBLE,
    tags          VARCHAR[]
);

-- Series temporelles aux stations d'observation
CREATE TABLE timeseries (
    sim_id        UUID REFERENCES simulations(sim_id),
    station_id    VARCHAR,
    variable      VARCHAR,       -- 'head' | 'discharge' | 'concentration'
    timestamps    TIMESTAMP[],
    values        DOUBLE[],
    unit          VARCHAR
);

-- Bilans de masse par zone
CREATE TABLE budgets (
    sim_id        UUID REFERENCES simulations(sim_id),
    timestep      INTEGER,
    zone_id       INTEGER,
    component     VARCHAR,       -- 'recharge' | 'drain' | 'wells' | ...
    flux_in       DOUBLE,
    flux_out      DOUBLE,
    unit          VARCHAR
);

-- Metriques de performance / calibration
CREATE TABLE metrics (
    sim_id        UUID REFERENCES simulations(sim_id),
    station_id    VARCHAR,
    metric_name   VARCHAR,       -- 'rmse' | 'nse' | 'kge' | 'bias'
    value         DOUBLE
);

-- Points d'observation (mapping spatial station → cellule du maillage)
-- Le mapping est calcule une seule fois via point-in-cell sur le maillage.
CREATE TABLE observation_points (
    sim_id        UUID REFERENCES simulations(sim_id),
    station_id    VARCHAR,
    x             DOUBLE,
    y             DOUBLE,
    cell_id       INTEGER,       -- resultat du point-in-cell lookup
    layer         INTEGER DEFAULT 0,  -- couche d'observation
    variable      VARCHAR        -- 'head' | 'concentration' | 'discharge'
);

-- Bilan de masse global (parse du listing file MODFLOW)
CREATE TABLE mass_balance_summary (
    sim_id         UUID REFERENCES simulations(sim_id),
    timestep       INTEGER,
    total_in       DOUBLE,        -- flux entrant total (m3/d)
    total_out      DOUBLE,        -- flux sortant total (m3/d)
    storage_in     DOUBLE,
    storage_out    DOUBLE,
    percent_error  DOUBLE         -- erreur de fermeture (%)
);

-- Provenance des entrees (tracabilite sans duplication)
-- Stocke un fingerprint des donnees effectivement injectees dans le solver.
-- Permet de detecter si les donnees source ont change apres le run.
CREATE TABLE input_provenance (
    sim_id        UUID REFERENCES simulations(sim_id),
    variable      VARCHAR,       -- 'recharge' | 'precipitation' | 'etp' | 'hk' | ...
    source_type   VARCHAR,       -- 'data_manager' | 'synthetic' | 'csv' | 'constant'
    source_ref    VARCHAR,       -- 'precipitation/sim2' (ref data manager)
    period_start  DATE,
    period_end    DATE,
    checksum      VARCHAR,       -- SHA-256 des donnees numpy injectees dans le solver
    n_records     INTEGER,       -- nombre de pas de temps / enregistrements
    stats         JSON           -- {"mean": 0.0023, "min": 0.0, "max": 0.012,
                                 --  "std": 0.001, "shape": [365, 50000],
                                 --  "dtype": "float64", "unit": "m/d"}
);
```

### Requetes inter-simulations (exemples)

```sql
-- Trouver les simulations avec bonne calibration
SELECT s.name, m.value AS nse
FROM simulations s
JOIN metrics m ON s.sim_id = m.sim_id
WHERE m.metric_name = 'nse' AND m.value > 0.7
ORDER BY m.value DESC;

-- Comparer les bilans de deux runs
SELECT a.component,
       a.flux_in - b.flux_in AS delta_in,
       a.flux_out - b.flux_out AS delta_out
FROM budgets a
JOIN budgets b ON a.component = b.component AND a.timestep = b.timestep
WHERE a.sim_id = 'uuid_a' AND b.sim_id = 'uuid_b';

-- Toutes les simulations sur maillages > 100k cellules
SELECT name, n_cells, solver FROM simulations WHERE n_cells > 100000;
```

### Requetes croisees data / resultats (via ATTACH)

Le catalogue data est dans un fichier DuckDB separe (niveau workspace).
Les requetes croisees utilisent `ATTACH` pour joindre les deux bases.

```sql
-- Depuis project.duckdb, attacher le catalogue workspace
ATTACH '../../catalog.duckdb' AS catalog;

-- Verifier si les donnees piezometriques observees couvrent la periode du run
SELECT s.name, s.sim_id, e.station_id, e.date_start, e.date_end
FROM simulations s
JOIN observation_points op ON s.sim_id = op.sim_id
JOIN catalog.entries e ON e.station_id = op.station_id
                       AND e.variable = 'piezometry'
WHERE e.date_end < s.created_at::DATE;

-- Trouver les sources de donnees utilisees dans les simulations bien calibrees
SELECT DISTINCT ip.source_ref, ip.variable, m.value AS nse
FROM input_provenance ip
JOIN metrics m ON ip.sim_id = m.sim_id
WHERE m.metric_name = 'nse' AND m.value > 0.8
ORDER BY m.value DESC;

-- Lister les stations d'observation absentes du catalogue de donnees
SELECT op.station_id, op.variable
FROM observation_points op
LEFT JOIN catalog.entries e ON e.station_id = op.station_id
                            AND e.variable = op.variable
WHERE e.id IS NULL;
```

---

## 7. Interface Python : `ResultStore`

```python
class ResultStore:
    """Interface unifiee pour les resultats de simulation."""

    def __init__(self, project_path: Path, workspace_path: Path | None = None):
        """Ouvre/cree le store pour un projet.

        workspace_path : optionnel. Si fourni :
          - ATTACH catalog.duckdb pour les requetes croisees data/resultats
          - finalize() alimente simulation_registry (decouverte inter-projets)
          - delete_simulation() nettoie simulation_registry

        En mode CLI (hmp simulation), workspace_path est toujours fourni
        par le SimulationRunner. En mode standalone (notebook, script),
        il peut etre omis - on perd le registre inter-projets mais tout
        le reste fonctionne normalement.
        """
        # self._db : connexion DuckDB (project_path / "project.duckdb")
        # self._zarr : zarr.Group (project_path / "project_results.zarr")
        # self._catalog : connexion DuckDB (workspace_path / "catalog.duckdb") | None

    # -- Enregistrement (appele par SimulationRunner) --

    def register_simulation(self, sim_id: UUID, config: HydroModPyConfig) -> None: ...
    def write_mesh(self, sim_id: UUID, mesh: HydroMesh, z_interfaces: np.ndarray) -> None: ...
    def register_observation_points(self, sim_id: UUID, points: dict[str, tuple[float, float]], variable: str = "head", layer: int = 0) -> None:
        """Enregistre des points d'observation et calcule le mapping station → cell_id.
        Effectue un point-in-cell lookup sur le maillage stocke.
        points : {"P1": (x1, y1), "P2": (x2, y2), ...}"""
        ...
    def write_field(self, sim_id: UUID, variable: str, timestep: int, values: np.ndarray) -> None: ...
    def write_timeseries(self, sim_id: UUID, station: str, variable: str, ts: pd.Series) -> None: ...
    def write_budget(self, sim_id: UUID, timestep: int, zone: int, component: str, flux_in: float, flux_out: float) -> None: ...
    def write_mass_balance(self, sim_id: UUID, timestep: int, total_in: float, total_out: float, percent_error: float, **kwargs) -> None:
        """Enregistre le bilan de masse global (depuis le listing file MODFLOW)."""
        ...
    def record_provenance(self, sim_id: UUID, variable: str, source_ref: str, data: np.ndarray, **meta) -> None:
        """Enregistre un fingerprint (hash + stats) des donnees d'entree.
        Ne stocke PAS l'array - uniquement le hash SHA-256 et les statistiques."""
        ...
    def finalize(self, sim_id: UUID, status: str = "completed") -> None:
        """Marque la simulation comme terminee.

        1. Met a jour simulations.status et simulations.duration_s dans project.duckdb
        2. Si workspace_path est configure, enregistre un resume dans
           catalog.duckdb/simulation_registry (metriques cles, solver, maillage,
           provenance) pour la decouverte inter-projets.
        """
        ...

    # -- Requetes --

    def list_simulations(self, **filters) -> pd.DataFrame: ...
    def query_timeseries(self, sim_id: UUID, station: str, variable: str, period: tuple | None = None) -> pd.Series:
        """Extrait une serie temporelle a un point d'observation.
        Utilise le mapping station → cell_id pour lire dans Zarr :
        zarr[sim_id/variable][:, layer, cell_id] → pd.Series."""
        ...
    def query_field(self, sim_id: UUID, variable: str, timestep: int, layer: int | None = None) -> np.ndarray:
        """Charge un champ spatial pour un pas de temps donne.
        Accepte les variables brutes (head, concentration) et derivees
        (watertable_depth, seepage_areas) de maniere transparente."""
        ...
    def query_budget(self, sim_id: UUID, zone: int | None = None, period: tuple | None = None) -> pd.DataFrame: ...
    def query_mass_balance(self, sim_id: UUID) -> pd.DataFrame:
        """Retourne le bilan de masse global par pas de temps + erreur de fermeture."""
        ...
    def get_provenance(self, sim_id: UUID, variable: str | None = None) -> pd.DataFrame:
        """Retourne les fingerprints des entrees utilisees pour un run."""
        ...
    def verify_provenance(self, sim_id: UUID, variable: str, current_data: np.ndarray) -> bool:
        """Compare le hash des donnees actuelles avec celui du run. Retourne False si divergence."""
        ...
    def compare(self, sim_a: UUID, sim_b: UUID, variable: str, timestep: int) -> dict: ...

    # -- Calibration --

    def extract_calibration_vector(self, sim_id: UUID, observation_plan: list) -> np.ndarray:
        """Retourne un vecteur 1D de valeurs simulees alignees sur les observations.

        observation_plan : liste de (station_id, variable, timestamps[])
        Pour chaque station, extrait la serie depuis Zarr via le mapping
        station → cell_id, puis concatene le tout en un vecteur 1D compatible
        avec le callback simulator() du module calibration.
        """
        ...

    # -- Export --

    def export(self, sim_id: UUID, variable: str, format: str, path: Path, **kwargs) -> Path:
        """
        Exporte les resultats dans un format standard.

        Formats supportes :
        - "nc"  : NetCDF-4/UGRID (champs spatiaux + topologie)
        - "csv" : series temporelles
        - "shp" : geometries des cellules + valeur a un timestep
        - "tif" : GeoTIFF (rasterisation du maillage non-structure)
        - "vtu" : VTK Unstructured Grid (pour ParaView)
        """
        ...

    # -- Suppression --

    def delete_simulation(self, sim_id: UUID) -> None:
        """Supprime une simulation et toutes ses donnees associees.

        Nettoyage dans 3 endroits :
        1. project.duckdb : DELETE CASCADE dans les 7 tables
           (simulations, timeseries, budgets, metrics, observation_points,
           mass_balance_summary, input_provenance)
        2. project_results.zarr : suppression du groupe {sim_id}/
        3. catalog.duckdb : DELETE FROM simulation_registry WHERE sim_id = ?
           (si workspace_path configure, avec retry concurrence)
        """
        ...
```

---

## 8. Adaptateurs par solveur (OutputAdapter)

Chaque solveur produit des fichiers dans des formats differents. Un adaptateur
lit les sorties brutes et les injecte dans le `ResultStore`.

```
ResultStore (interface unifiee)
    ^
    |  write_field / write_timeseries / write_budget
    |
OutputAdapter (par solveur)
    |
    +-- ModflowNwtOutputAdapter   : lit .hds, .cbc, .ddn via FloPy
    +-- Modflow6OutputAdapter     : lit .hds, .cbc via FloPy (MF6)
    +-- Mt3dmsOutputAdapter       : lit .ucn via FloPy
    +-- ModpathOutputAdapter      : lit pathline/endpoint files
    +-- GR4JOutputAdapter         : lit resultats en memoire (pd.Series)
```

### Deux phases dans chaque OutputAdapter

**Phase 1 - Extraction brute (toujours executee)**

Lecture des fichiers proprietaires et injection dans le ResultStore :

| Variable | Source | Solveurs concernes |
|----------|--------|--------------------|
| `head` | HeadFile (`.hds`) | MF6, MF-NWT |
| `concentration` | UcnFile (`.ucn`) | MT3DMS, MF6-GWT |
| `budget/*` | CellBudgetFile (`.cbc`) | MF6, MF-NWT |
| `mass_balance` | ListingFile (`.lst`) | MF6, MF-NWT |
| `pathlines` | PathlineFile | MODPATH |
| `Q(t)`, `S(t)` | en memoire | GR4J |

L'OutputAdapter detecte automatiquement les composantes de budget presentes
dans le CellBudgetFile (`cbb.get_unique_record_names()`) et extrait :
- Les **totaux agreses** (in/out par composante par timestep) → DuckDB `budgets`
- Les **champs spatiaux** par composante → Zarr `budget/{component}`
  (optionnel, si `budget.spatial_fields = true`)

Composantes MODFLOW typiques : DRN, RCH/RCHA, WEL, RIV, GHB, CHD, STO-SS,
STO-SY, FLOW-JA-FACE.

**Phase 2 - Variables derivees (configurable via TOML)**

Calculees a partir des sorties brutes, stockees dans Zarr `derived/` :

| Variable derivee | Calcul | Dependances |
|------------------|--------|-------------|
| `watertable_elevation` | `flopy.utils.postprocessing.get_water_table(head)` | head |
| `watertable_depth` | `SolverMesh.top - watertable_elevation` | head, mesh |
| `seepage_areas` | `watertable_elevation >= SolverMesh.top` (booleen) | head, mesh |
| `groundwater_flux` | magnitude des flux inter-cellules (right/front/lower face) | budget |
| `accumulation_flux` | routage des flux de drain sur le reseau hydrographique | budget (DRN) |
| `concentration_seepage` | concentration aux cellules de suintement uniquement | concentration, seepage |
| `mass_seepage` | flux de masse au suintement | concentration, budget |
| `mass_accumulated` | cumul temporel de mass_seepage | mass_seepage |

Note : `watertable_depth` depend de `SolverMesh.top` (elevation de surface),
qui est une donnee du maillage deja disponible dans l'OutputAdapter - pas
besoin d'interroger les data managers.

### Suppression des fichiers solver

Les fichiers bruts solver sont **supprimes par defaut** apres ingestion dans
le ResultStore. L'utilisateur peut demander a les conserver via la config TOML
(`keep_solver_files = true`) pour le debug ou la reproductibilite.

### Pickle legacy

Les adapters actuels persistent un `results_{model_name}.pkl` avant le run.
Avec le ResultStore, ce pickle n'a plus de raison d'etre : la config est dans
DuckDB, le maillage dans Zarr, les resultats dans Zarr. Le pickle sera
supprime lors de la migration (voir section 15).

---

## 9. Cycle de vie des donnees

### Principe general

Le solveur (MODFLOW 6, NWT, GR4J...) produit ses fichiers dans des formats
proprietaires. Le `ResultStore` est la **seule source de verite** apres la
simulation : les fichiers solver sont temporaires, le store est permanent.

```
                     FORMATS PROPRIETAIRES          RESULTSTORE
                     (temporaires)                  (permanent)
                     ─────────────────              ──────────────

MODFLOW 6 tourne ──> .hds, .cbc, .ucn
                           │
                     OutputAdapter lit
                     via FloPy
                           │
                     standardise ──────────────> Zarr (champs)
                                                DuckDB (meta, series, bilans)
                           │
                     supprime les .hds/.cbc/.ucn
                     (sauf keep_solver_files=true)


Plus tard...

  display ──────> ResultStore.query_field() ──> numpy array ──> figure
  export  ──────> ResultStore.export("nc")  ──> fichier NetCDF propre
  compare ──────> ResultStore.compare()     ──> diff entre 2 simulations
  ML/IA   ──────> ResultStore via Zarr      ──> PyTorch DataLoader
```

### Etapes detaillees

**1. Execution et ingestion (automatique, fin de simulation)**
```
SimulationRunner
  -> forcing/ prepare les entrees (recharge, CL, parametres spatiaux)
  -> ResultStore.record_provenance()   # hash + stats des forcages injectes
                                       # (ne stocke PAS les arrays de forcage)
  -> SolverAdapter execute le solver
  -> le solver ecrit ses fichiers proprietaires (.hds, .cbc, .ucn, ...)
  -> OutputAdapter lit ces fichiers via FloPy (ou en memoire pour GR4J)
  -> ResultStore.write_mesh()          # topologie du maillage (1 seule fois)
  -> ResultStore.write_field()         # champs spatiaux, pas de temps par pas de temps
  -> ResultStore.write_timeseries()    # series ponctuelles (piezo, debit)
  -> ResultStore.write_budget()        # bilans de masse
  -> ResultStore.finalize()            # marque la simulation comme terminee
  -> suppression des fichiers solver (si keep_solver_files = false)
```

**2. Consultation (a la demande, meme des semaines plus tard)**
```
Utilisateur / script
  -> ResultStore.list_simulations(solver='modflow6', n_cells__gt=100000)
  -> DuckDB filtre -> retourne sim_ids
  -> ResultStore.query_field(sim_id, 'head', timestep=180, layer=0)
  -> Zarr charge le chunk de 40 Mo (pas les 14 Go) -> retourne np.ndarray
  -> affichage, analyse, comparaison...
```

**3. Export (a la demande ou automatique via TOML)**
```
Utilisateur / config TOML
  -> ResultStore.export(sim_id, 'head', format='nc', path=...)
  -> Zarr -> xugrid -> NetCDF-4/UGRID (pour QGIS, partage)
  -> ou Zarr -> meshio -> VTU (pour ParaView)
  -> ou DuckDB -> pandas -> CSV (series temporelles)
  -> ou Zarr -> rasterisation -> GeoTIFF

L'export produit des fichiers dans un dossier au choix de l'utilisateur.
Le ResultStore n'est pas modifie par l'export.
```

**4. Calibration (chemin chaud - tout en RAM)**
```
Boucle d'optimisation (x 10 000 - 50 000 iterations)
  -> make_hot_simulator(run_fn) produit un callback
  -> callback(params) → np.ndarray en memoire (zero I/O disque)
  -> optimizer calcule objective(sim, obs) → scalar
  -> next params

Apres convergence (UNE seule fois)
  -> persist_calibration_result(store, result, run_fn)
  -> relance le meilleur run → ResultStore (chemin froid standard)
  -> stocke metriques + parametres optimaux dans DuckDB
```

**5. ML/IA (acces programmatique)**
```
Pipeline ML
  -> DuckDB filtre simulations par parametres de config
  -> Zarr -> xarray lazy (Dask) -> charge uniquement les chunks necessaires
  -> Xbatcher -> PyTorch DataLoader (multi-workers, parallele)
  -> ou PyTorch Geometric (graph neural networks sur maillage)
```

---

## 10. Configuration utilisateur (TOML)

L'utilisateur peut configurer les exports automatiques dans le TOML :

```toml
[simulation.results]
store = true                       # activer le ResultStore (defaut: true)
keep_solver_files = false          # garder les fichiers proprietaires du solver
                                   # (.hds, .cbc, .ucn) apres ingestion
                                   # defaut: false → supprimes apres ingestion
                                   # mettre true pour debug / reproductibilite

[simulation.results.derived]
# Variables derivees calculees a partir des sorties brutes.
# Stockees dans Zarr derived/. Desactiver pour economiser du disque.
watertable_elevation = true
watertable_depth = true
seepage_areas = true
groundwater_flux = false           # volumineux (3D x temps)
accumulation_flux = false          # necessite le reseau de drainage
concentration_seepage = false      # necessite transport
mass_seepage = false
mass_accumulated = false

[simulation.results.budget]
spatial_fields = false             # stocker les champs spatiaux par composante
                                   # de budget dans Zarr (DRN, RCH, WEL, ...)
                                   # volumineux - desactive par defaut
                                   # les totaux agreges sont toujours dans DuckDB

[simulation.results.export]
# Exports automatiques en fin de simulation.
# Les fichiers sont ecrits dans le dossier d'export du projet.
# L'utilisateur peut aussi exporter manuellement via ResultStore.export().
netcdf = true                      # export NetCDF-4/UGRID automatique
csv_timeseries = true              # export CSV des series temporelles
vtu = false                        # export VTU (desactive par defaut)
geotiff = false                    # export GeoTIFF (rasterisation)
shapefile = false                  # export Shapefile
output_dir = "exports/"            # dossier de sortie relatif au projet

[simulation.results.export.variables]
head = true
concentration = false
budget = true
pathlines = false
```

---

## 11. Dependances ajoutees

| Package | Usage | Obligatoire |
|---------|-------|-------------|
| `zarr>=3.0` | Stockage arrays chunkes avec sharding | Oui |
| `duckdb` | Base unifiee (catalogue data + resultats) | Oui |
| `blosc2` | Compression Blosc+Zstd pour Zarr | Oui (via zarr) |
| `xugrid` | Export NetCDF-4/UGRID, regridding inter-maillages | Optionnel (export) |
| `meshio` | Export VTU (deja present) | Deja present |
| `rioxarray` | Export GeoTIFF (rasterisation) | Optionnel (export) |

### Dependances supprimees

| Package | Raison |
|---------|--------|
| `sqlalchemy` | Remplace par DuckDB natif (API Python `duckdb.connect()`) |
| `sqlite3` | Plus utilise - DuckDB couvre tous les besoins SQL |

DuckDB fournit une API Python directe (`conn.execute()`, `conn.sql()`)
sans besoin d'ORM. Le catalogue de donnees (ex-`DataCatalog` via SQLAlchemy)
sera reecrit en SQL DuckDB natif.

### Migration SQLite → DuckDB

DuckDB peut lire nativement les fichiers SQLite existants :

```python
import duckdb
conn = duckdb.connect("workspace/catalog.duckdb")
conn.execute("INSTALL sqlite; LOAD sqlite")
conn.execute("ATTACH 'catalog.db' AS legacy (TYPE SQLITE)")
conn.execute("CREATE TABLE entries AS SELECT * FROM legacy.entries")
conn.execute("CREATE TABLE api_coverage AS SELECT * FROM legacy.api_coverage")
conn.execute("DETACH legacy")
```

Cette migration peut etre faite automatiquement au premier lancement si un
fichier `catalog.db` (SQLite) est detecte dans le workspace.

---

## 12. Structure du module

```
simulation/results/
|-- __init__.py
|-- store.py              # ResultStore : interface principale
|-- schema.py             # Schema DuckDB (creation des tables)
|-- zarr_layout.py        # Fonctions de creation/lecture du layout Zarr
|-- provenance.py         # Fingerprint (hash + stats) des entrees
|-- spatial_index.py      # Point-in-cell lookup (station → cell_id)
|-- calibration_bridge.py # make_calibration_simulator() wrapper
|-- adapters/
|   |-- __init__.py
|   |-- base.py           # BaseOutputAdapter (protocole : phase 1 + phase 2)
|   |-- modflownwt.py     # ModflowNwtOutputAdapter
|   |-- modflow6.py       # Modflow6OutputAdapter (+ listing parser)
|   |-- mt3dms.py         # Mt3dmsOutputAdapter
|   |-- modpath.py        # ModpathOutputAdapter
|   |-- gr4j.py           # GR4JOutputAdapter
|   |-- derived.py        # Calcul des variables derivees (phase 2)
|-- exporters/
|   |-- __init__.py
|   |-- netcdf.py         # Export NetCDF-4/UGRID (via xugrid)
|   |-- csv.py            # Export CSV series temporelles
|   |-- geotiff.py        # Export GeoTIFF (rasterisation)
|   |-- shapefile.py      # Export Shapefile
|   |-- vtu.py            # Export VTU (via meshio)
```

---

## 13. Integration avec la calibration

### Le probleme des performances en boucle de calibration

Le module calibration (`analysis/calibration/`) fonctionne avec un callback
`simulator(params) → np.ndarray` qui retourne un vecteur 1D. Pour un modele
integre (GR4J), la calibration peut necessiter **10 000 a 50 000 iterations**.

Si chaque iteration ecrit dans le ResultStore puis relit, l'overhead I/O
domine le temps de calcul :

```
GR4J run        : ~1 ms
Ecriture DuckDB : ~5-10 ms    ← 10x le temps du modele
Lecture DuckDB  : ~5 ms
──────────────────────────────
Total par iter  : ~15 ms      dont 93% d'I/O inutile
x 50 000 iter   : ~12 min     dont ~50 s de calcul reel
```

DuckDB est un moteur **OLAP** (analytique), optimise pour scanner des
millions de lignes d'un coup. Il n'est PAS concu pour 50 000 cycles
rapides insert+read. C'est un anti-pattern.

### Solution : chemin chaud (RAM) vs chemin froid (store)

```
CHEMIN CHAUD (calibration)              CHEMIN FROID (simulation standard)
tout en memoire, zero I/O               ResultStore (DuckDB + Zarr)
──────────────────────────              ──────────────────────────────

  optimizer                               simulation unique
      │                                       │
      ├─ run_model(params)                    ├─ run solver
      │  → np.ndarray (RAM)                   │  → OutputAdapter
      │  aucune ecriture disque               │  → ResultStore.write_*()
      │                                       │
      ├─ objective(sim, obs)                  └─ finalize()
      │  → scalar (RAM)
      │
      ├─ next params
      │
      └─ ... x 50 000 iterations
             │
             │ calibration terminee
             │
             └─ persist best run ──> ResultStore
```

**Regle** : la boucle de calibration ne touche **jamais** au ResultStore.
Tout reste en RAM (numpy arrays). Seul le resultat final (meilleurs
parametres, meilleur run) est persiste.

Les numpy arrays **sont** le format en memoire - pas besoin de format
temporaire intermediaire ni de "mini-store en RAM".

### Modele integre vs distribue en calibration

| | Integre (GR4J) | Distribue (MODFLOW) |
|---|---|---|
| Iterations | 10 000 - 50 000 | 100 - 500 |
| Temps par run | ~1 ms | 2 - 10 min |
| Overhead I/O store | Inacceptable (93% du temps) | Negligeable (<0.1% du temps) |
| Strategie | **Chemin chaud** : tout en RAM | Chemin froid possible (optionnel) |
| Persistence | Seulement le meilleur run | Chaque iteration si souhaite (debug) |

Pour MODFLOW, on **peut** persister chaque iteration dans le ResultStore
(l'overhead de ~100 ms est invisible face a 5 min de solver), mais ce n'est
pas obligatoire. C'est configurable.

### Implementation du bridge

```python
# simulation/results/calibration_bridge.py

def make_hot_simulator(run_fn):
    """Callback pour la boucle de calibration. Tout en RAM, pas de store.

    run_fn : callable(params) → np.ndarray
        Fonction qui lance le modele et retourne directement les resultats
        en memoire (pas de persistence).
    """
    def simulator(params: dict) -> np.ndarray:
        return run_fn(params)  # numpy array direct, zero I/O
    return simulator


def persist_calibration_result(result_store, calibration_result, run_fn):
    """Apres calibration : relance le meilleur run et persiste dans le store.

    Appele UNE SEULE FOIS, apres la boucle d'optimisation.
    """
    sim_id = uuid4()
    best_output = run_fn(calibration_result.best_params)

    result_store.register_simulation(sim_id, calibration_result.config)
    # ... write_mesh, write_field, write_timeseries selon le type de modele

    # Enregistrer les metriques de calibration
    for station, metric_name, value in calibration_result.metrics:
        result_store.write_metric(sim_id, station, metric_name, value)

    # Enregistrer les parametres optimaux
    result_store.write_calibration_params(sim_id, calibration_result.best_params)

    result_store.finalize(sim_id, status="calibrated")
    return sim_id
```

### Encapsulation preservee

| Composant | Connait le ResultStore ? | Connait le modele ? |
|-----------|--------------------------|---------------------|
| Module calibration | Non | Non (callback opaque) |
| `make_hot_simulator()` | Non | Oui (appelle run_fn) |
| `persist_calibration_result()` | Oui | Non (recoit des arrays) |
| ResultStore | - | Non |

Le module calibration reste agnostique du stockage. Il recoit un callback,
retourne des metriques. Le bridge fait le lien sans que les deux se connaissent.

### Validation sur le code existant

L'approche chemin chaud a ete validee contre le module calibration existant
(`analysis/calibration/core/`). Le workflow actuel est **deja tout en RAM** :

- `CalibrationEngine.calibrate()` appelle le callback `simulator(params_dict)`
  qui retourne un `np.ndarray` en memoire
- `CalibrationParameterSet` gere les conversions `dict ↔ vector` en RAM
- Aucune methode (simplex, nelder_mead, grid_search, random_search, gp_mapping,
  da_mh_gp) ne fait d'I/O fichier pendant la boucle d'iteration
- Le cache de `da_mh_gp` est un `dict` Python en memoire (pas sur disque)
- `CalibrationResults` est retourne en memoire, l'utilisateur decide de la
  persistence

L'ajout du `persist_calibration_result()` est la seule piece manquante - un
pont post-convergence vers le ResultStore. La boucle de calibration elle-meme
n'est pas impactee.

### Empreinte memoire en calibration

L'analyse de la consommation RAM montre que le chemin chaud ne pose aucun
probleme de saturation :

**Modele integre (GR4J, 50 000 iterations) :**
```
observed         : ~29 Ko   (fixe, 10 ans journalier)
simulated        : ~29 Ko   (ecrase a chaque iteration, libere par le GC)
optimizer state  : ~quelques Mo (simplex vertices, MCMC chain)
cache da_mh_gp   : ~230 Mo  (pire cas : 8 000 entrees × 29 Ko)
─────────────────────────────
Total pic RAM    : ~300 Mo max
```

**Modele distribue (MODFLOW, 100-500 iterations) :**
```
Callback simulator :
  FloPy HeadFile.get_data(totim=t) lit 1 timestep a la fois (~40 Mo)
  Extraction aux piezos : 10 stations × 365 jours = ~29 Ko
  L'array head complet est libere apres extraction
─────────────────────────────
Total pic RAM    : ~50 Mo par iteration (transitoire)
```

Le vecteur retourne par le simulator est toujours petit (~29 Ko pour 10 piezos
× 365 jours). Seul le transitoire de lecture FloPy consomme de la RAM, et il
est libere immediatement.

### Le ResultStore resout un probleme de RAM existant

Le code actuel de post-processing (`solver/modflow6/modflow6.py`) accumule
**toutes** les variables derivees pour **tous** les pas de temps dans des
dicts Python :

```python
# Code actuel - accumule tout en RAM (probleme)
dict_watertable_depth = {}
dict_seepage_areas = {}
dict_outflow_drain = {}
dict_accumulation_flux = {}

for item, time in enumerate(times):
    head = head_fpu.get_data(totim=time)
    wt = pp.get_water_table(head, -9999)
    dict_watertable_depth[item] = dem - wt       # GARDE en memoire
    dict_seepage_areas[item] = (wt >= dem)        # GARDE en memoire
    dict_outflow_drain[item] = extract_drain(cbb) # GARDE en memoire
    # ...

# Pour 500k cellules × 365 pas de temps × 5 variables × 8 octets :
# = ~7.3 Go en RAM au final
```

Avec le ResultStore, chaque pas de temps est ecrit dans Zarr puis libere :

```python
# Avec ResultStore - RAM constante (solution)
for item, time in enumerate(times):
    head = head_fpu.get_data(totim=time)          # ~40 Mo (1 timestep)
    wt = pp.get_water_table(head, -9999)
    wtd = dem - wt

    store.write_field(sim_id, "watertable_depth", item, wtd)  # flush Zarr
    store.write_field(sim_id, "seepage_areas", item, wt >= dem)
    # head, wt, wtd sont liberes au prochain tour de boucle

# RAM pic : ~80 Mo constant, quel que soit le nombre de pas de temps
# vs ~7.3 Go avec le code actuel
```

Le passage au ResultStore offre donc un **avantage inattendu** : en decouplant
le calcul du stockage, il elimine l'accumulation en RAM du post-processing
actuel. C'est un argument de poids au-dela de la standardisation des sorties.

---

## 14. Migration depuis le code existant

Le code actuel dans `analysis/postprocess/` et `analysis/display/` fonctionne.
La migration se fait en trois phases sans casser l'existant.

### Code existant a migrer

| Code actuel | Devient | Notes |
|-------------|---------|-------|
| `analysis/postprocess/flow/` | `simulation/results/adapters/` | Lecteurs FloPy .hds/.cbc reutilises |
| `analysis/postprocess/netcdf/` | `simulation/results/exporters/netcdf.py` | Reecrit avec xugrid (UGRID) |
| `analysis/postprocess/timeseries/` | `simulation/results/exporters/csv.py` | Source = ResultStore au lieu de .npy |
| `analysis/display/figures/` | Inchange | Recoit pd.Series, source = ResultStore |
| `analysis/display/export_vtuvtk.py` | `simulation/results/exporters/vtu.py` | Via meshio (deja present) |
| `results_{model}.pkl` (pickle legacy) | Supprime | Config dans DuckDB, maillage dans Zarr |
| Dossier `_postprocess/` avec .npy | Supprime | Tout est dans le ResultStore |

### Phases de migration

**Phase 1 - Coexistence (en cours de dev)**

Le ResultStore est implemente et les nouveaux OutputAdapters ecrivent dedans.
L'ancien code `analysis/postprocess/` continue de fonctionner en parallele.
Les deux systemes produisent les memes donnees.

Objectif : valider que le ResultStore produit des resultats identiques.

**Phase 2 - Bascule des consommateurs**

Les fonctions de display et de calibration sont modifiees pour lire depuis
le ResultStore au lieu des fichiers .npy / CSV / NetCDF :

```python
# Avant (analysis/display)
data = np.load("_postprocess/watertable_depth.npy")

# Apres (via ResultStore)
data = store.query_field(sim_id, "watertable_depth", timestep=180)
```

Les fonctions de rendering (`render_discharge`, `render_piezometry`) ne
changent pas - elles recoivent toujours des pd.Series/pd.DataFrame.
Seule la source change.

**Phase 3 - Nettoyage**

Suppression de :
- `analysis/postprocess/flow/` (remplace par les adapters)
- `analysis/postprocess/netcdf/` (remplace par les exporters)
- `analysis/postprocess/timeseries/` (remplace par les exporters)
- Pickle legacy `results_{model_name}.pkl`
- Dossier `_postprocess/` dans le workspace

---

## 15. Points ouverts

### Resolus

- [x] **Unification DuckDB** : DuckDB remplace SQLite + SQLAlchemy pour tout
  le framework. Le catalogue data reste au **niveau workspace**
  (`catalog.duckdb`, partage entre projets), les resultats sont au **niveau
  projet** (`project.duckdb`). Requetes croisees via `ATTACH`.
  Voir sections 2, 4 et 6.

- [x] **Quand ingerer ?** Decision : **post-run** (apres execution complete).
  L'OutputAdapter lit les fichiers proprietaires du solveur en un seul passage,
  standardise dans le ResultStore, puis les fichiers solver sont supprimes
  (sauf `keep_solver_files = true`). Le streaming pendant l'execution est
  differe a une version ulterieure si le besoin se confirme.

- [x] **Concurrence DuckDB** : WAL mode + retry avec backoff exponentiel
  pour les ecritures concurrentes dans `catalog.duckdb`. Voir section 2.

- [x] **Suppression de simulations** : `delete_simulation()` nettoie les
  3 endroits (project.duckdb, Zarr, simulation_registry). Voir section 7.

- [x] **Registre inter-projets** : `simulation_registry` dans `catalog.duckdb`
  pour la decouverte et la recherche inter-projets. Alimente automatiquement
  par `finalize()`. Voir section 6.

- [x] **workspace_path optionnel** : en mode CLI toujours fourni (registre
  actif), en mode standalone optionnel (registre desactive). Voir section 7.

- [x] **xugrid et extrusion 3D** : MODFLOW est fondamentalement un modele par
  couches (DIS, DISV, DISU). Meme DISU reste en volumes polyedriques connectes,
  pas en tetraedres FEM (c'est FEFLOW ou TOUGH2, hors scope). La convention
  `(time, layer, face)` dans Zarr + UGRID couvre tous les cas MODFLOW. xugrid
  gere le 2D + couches extrudees, ce qui est suffisant. Le vrai 3D volumique
  n'est pas dans le scope.

- [x] **Versioning des resultats** : chaque run = nouveau `sim_id` (UUID).
  Pas d'ecrasement. L'utilisateur nettoie via `delete_simulation()`.
  Evolution future : un mode `store_level = "full" | "lite"` pour la
  calibration, ou `"lite"` ne garde que les series aux points d'observation +
  metriques + metadonnees, sans les champs volumiques Zarr. Permet de garder
  des centaines de runs de calibration sans exploser le stockage.

- [x] **Scope Zarr** : un seul `project_results.zarr/` par projet, avec un
  groupe par `sim_id`. La suppression d'un groupe est une operation standard.
  Le volume total est identique dans les deux cas, mais un store par simulation
  creerait des centaines de dossiers en calibration. L'integrite entre les
  3 endroits (project.duckdb, Zarr, simulation_registry) est verifiee par
  `check_integrity()` qui detecte les orphelins et propose le nettoyage.

- [x] **Separation solveur integre / distribue** : meme API `ResultStore`
  pour tous les solveurs. Pour un modele integre (GR4J), les methodes spatiales
  (`query_field`, `export_netcdf`) levent une `ValueError` explicite :
  `"No spatial fields for lumped model (solver=gr4j)"`. Les methodes temporelles
  (`query_timeseries`, `query_budget`) fonctionnent normalement. Un flag
  `is_distributed: bool` dans la table `simulations` (DuckDB) est derive du
  solver.

- [x] **Point-in-cell robustesse** : lookup spatial via `shapely.STRtree` sur
  les polygones des faces (exact, gere les formes irregulieres et les maillages
  mixtes tri/quad). Pour les points hors maillage (station dont les coordonnees
  tombent en dehors du domaine simule) : retourne `None` + warning, pas
  d'exception. `scipy.KDTree` sur centroides ecarte (approximatif).

- [x] **Listing file parser** : utilise les parsers FloPy existants -
  `flopy.utils.MfListBudget` (NWT) et `flopy.utils.Mf6ListBudget` (MF6).
  Pas de parser custom. Les resultats (`total_in`, `total_out`,
  `percent_error` par stress period) vont dans la table `mass_balance_summary`.

### Differes

- [ ] **Regridding inter-simulations** : pour comparer deux simulations sur
  des maillages differents, reprojeter sur une grille commune via xugrid
  (`OverlapRegridder`, `CentroidLocatorRegridder`). Fonctionnalite avancee,
  pas dans le scope initial. En attendant, l'utilisateur exporte en NetCDF
  et utilise xugrid en notebook.

- [ ] **Mode lite calibration** : parametre `store_level = "full" | "lite"`
  pour ne garder que l'essentiel (series ponctuelles + metriques) sans les
  champs volumiques Zarr. Pertinent pour les campagnes de calibration avec
  des centaines de runs. Depend du type de calibration demande.

- [ ] **check_integrity()** : verification de coherence entre les 3 endroits
  de stockage (project.duckdb, project_results.zarr, simulation_registry).
  Detecte les orphelins (simulation supprimee partiellement, crash pendant
  l'ecriture) et propose le nettoyage automatique.

---

## 16. References

- Zarr v3 spec : https://zarr-specs.readthedocs.io/en/latest/v3/core/v3.0.html
- Convention UGRID : https://ugrid-conventions.github.io/ugrid-conventions/
- DuckDB : https://duckdb.org/docs/
- xugrid (Deltares) : https://deltares.github.io/xugrid/
- FoxBench (DLR, 2025) : benchmark Zarr vs NetCDF-4 vs TileDB pour geosciences
- Xbatcher (Pangeo) : https://xbatcher.readthedocs.io/
- MeshGraphNets (DeepMind, ICLR 2021) : modeles surrogate sur maillages
