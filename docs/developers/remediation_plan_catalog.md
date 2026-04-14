# Plan de remediation : Simulation Catalog

Ce document decrit les corrections et ajouts a apporter au Simulation Catalog
(DuckDB + Zarr) pour que l'implementation reelle corresponde au schema prevu
et que la base soit exploitable en production.

Etat actuel : le schema DuckDB est complet (12 tables + `_schema_version`),
mais le pipeline d'execution ne remplit que 4 tables sur 12. Plusieurs
mecanismes critiques (transactions, batch writes, nettoyage complet)
sont absents.

## 1. Enrichir `register_simulation()`

### Probleme

Les deux points d'appel (`store_lifecycle.py:38` et `project.py:415`) ne
passent que `sim_id`, `project`, `solver`, `name`, `run_id`. Toutes les
colonnes dimensionnelles restent NULL.

### Fichiers concernes

- `hydromodpy/workflow/steps/store_lifecycle.py` — `step_open_store()`
- `hydromodpy/project.py` — `Project.run()`

### Ce qu'il faut passer

Au moment de l'appel, le contexte contient tout le necessaire :

| Colonne cible | Source dans le contexte | Type |
|---|---|---|
| `flow_regime` | `ctx.cfg.flow.flow_regime` | str |
| `n_cells` | `ctx.setup.domain.mesh.n_cells` | int |
| `n_layers` | `ctx.setup.domain.n_layers` | int |
| `n_timesteps` | longueur de `ctx.setup.time_grid` | int |
| `cell_types` | `ctx.setup.domain.mesh.cell_types` | list[str] |
| `bbox` | `ctx.setup.geographic.bbox` (ou calcul depuis mesh vertices) | list[float] |
| `crs` | `ctx.setup.geographic.crs` | str |
| `period_start` | `ctx.setup.time_grid[0]` | str |
| `period_end` | `ctx.setup.time_grid[-1]` | str |
| `time_unit` | `ctx.cfg.simulation.time_unit` | str |
| `config_toml` | `ctx.cfg.model_dump(mode="json")` | dict → JSON |
| `config_hash` | SHA-256 du JSON serialise | str |
| `mesh_type` | `ctx.setup.domain.mesh.mesh_type` | str |
| `mesh_hash` | SHA-256 de (vertices + connectivity) | str |

### Implementation

```python
# store_lifecycle.py — step_open_store()

import hashlib, json

config_dict = ctx.cfg.model_dump(mode="json")
config_json = json.dumps(config_dict, sort_keys=True, default=str)
config_hash = hashlib.sha256(config_json.encode()).hexdigest()

# mesh hash : empreinte des arrays de topologie
mesh = ctx.setup.domain.mesh
mesh_bytes = mesh.vertices.tobytes() + mesh.face_node_connectivity.tobytes()
mesh_hash = hashlib.sha256(mesh_bytes).hexdigest()

ctx.store.register_simulation(
    ctx.sim_id,
    project=project_name,
    solver=",".join(r.solver for r in plan.runs),
    name=ctx.setup.run_id,
    run_id=ctx.setup.run_id,
    flow_regime=ctx.cfg.flow.flow_regime,
    n_cells=mesh.n_cells,
    n_layers=ctx.setup.domain.n_layers,
    n_timesteps=len(ctx.setup.time_grid),
    cell_types=mesh.cell_types,
    bbox=list(ctx.setup.geographic.bbox),
    crs=str(ctx.setup.geographic.crs),
    period_start=str(ctx.setup.time_grid[0]),
    period_end=str(ctx.setup.time_grid[-1]),
    time_unit=ctx.cfg.simulation.time_unit,
    config=config_dict,
    mesh_type=mesh.mesh_type,
    mesh_hash=mesh_hash,
)
```

Faire la meme chose dans `project.py` pour `Project.run()`. Les objets sont
accessibles via `self.geographic`, `self.domain`, `self.cfg`.

### Verification

```sql
SELECT sim_id, n_cells, n_layers, flow_regime, crs, config_hash
FROM simulations;
-- Aucune colonne ne doit etre NULL (sauf tags, notes, parent_sim_id)
```


## 2. Ecrire les parametres dans le pipeline normal

### Probleme

`write_parameters()` n'est appele que depuis `calibration_bridge.py`.
En run normal, la table `parameters` reste vide.

### Fichier concerne

- `hydromodpy/simulation/results/post_run.py` — ajouter une phase
- `hydromodpy/workflow/steps/store_lifecycle.py` — alternative : ecrire juste apres registration

### Source des parametres

Les parametres hydrauliques sont dans `ctx.setup.flow.parameters`, un dict
de `FieldParam`. Chaque `FieldParam` expose :

- `.identifier` : nom (`"K"`, `"Sy"`, `"Ss"`)
- `.value` : valeur scalaire (cas homogene)
- `.values_by_key` : dict `{zone_id: value}` (cas heterogene)
- `.unit` : unite SI
- `.kind` : `"homogeneous"` ou `"heterogeneous"`

### Implementation

Ajouter dans `step_open_store()`, juste apres `register_simulation()` :

```python
def _write_flow_parameters(store, sim_id, flow):
    params = []
    for pid, fp in flow.parameters.items():
        if fp.is_homogeneous:
            params.append({
                "param_name": pid,
                "zone_id": None,       # → _homogeneous en base
                "value": fp.value,
                "unit": fp.unit,
                "parameterization": "homogeneous",
            })
        else:
            for zone_key, val in fp.values_by_key.items():
                params.append({
                    "param_name": pid,
                    "zone_id": str(zone_key),
                    "value": val,
                    "unit": fp.unit,
                    "parameterization": "geology_mapped",
                })
    if params:
        store.write_parameters(sim_id, params)
```

Meme logique dans `project.py` apres `register_simulation()`.

### Verification

```sql
SELECT sim_id, param_name, zone_id, value, unit
FROM parameters
WHERE sim_id = '<uuid>';
-- Doit retourner au minimum K et Sy pour un run flow standard
```


## 3. Ecrire la provenance

### Probleme

`write_provenance()` n'est jamais appele. TODO explicite dans la codebase.

### Fichier concerne

- `hydromodpy/workflow/steps/result_ingestion.py` — ou un nouveau step
- `hydromodpy/data/common/base_manager.py` — alternative : chaque manager enregistre sa provenance au chargement

### Point d'integration recommande

Apres le data loading, dans le workflow. A ce stade, `ctx.loaded_data`
contient tous les `LoadResult` avec les arrays charges. Pour chaque
variable chargee :

```python
def step_write_provenance(ctx):
    for variable, load_result in ctx.loaded_data.items():
        ctx.store.write_provenance(
            ctx.sim_id,
            variable=variable,
            source_ref=str(load_result.source_path),
            data=load_result.data,
            source_type=load_result.source_type,
            period_start=load_result.period_start,
            period_end=load_result.period_end,
        )
```

L'implementation existante dans `catalog.py:250-276` calcule deja le
fingerprint (SHA-256 + stats) via `provenance.fingerprint()`.

### Verification

```sql
SELECT sim_id, variable, source_type, checksum, n_records
FROM provenance
WHERE sim_id = '<uuid>';
```


## 4. Fiabiliser `mass_balance`

### Probleme

L'extraction est implementee dans les extracteurs (`modflownwt.py:164`,
`modflow6.py:202`) mais echoue silencieusement si le fichier `.lst`
n'est pas lisible ou absent.

### Correction

Dans `_extract_mass_balance()` des deux extracteurs : logger en WARNING
au lieu de DEBUG quand le parsing echoue, pour que le probleme soit
visible.

Verifier que le solver ecrit bien le `.lst` :
- MODFLOW-NWT : actif par defaut
- MODFLOW 6 : verifier la config FloPy du listing file

Si le `.lst` est bien present mais que le parsing echoue, investiguer
le format de sortie (versions FloPy / MODFLOW).


## 5. Corriger `delete()` — fuite geographic_*

### Probleme

`PER_SIM_TABLE_NAMES` ne contient pas `geographic_features` ni
`geographic_metadata`. Ces lignes deviennent orphelines a chaque
suppression.

### Fichier concerne

- `hydromodpy/results/catalog_schema.py` — `PER_SIM_TABLE_NAMES`

### Correction

```python
PER_SIM_TABLE_NAMES: tuple[str, ...] = (
    "parameters",
    "timeseries",
    "budgets",
    "mass_balance",
    "metrics",
    "observation_points",
    "provenance",
    "geographic_features",      # ajoute
    "geographic_metadata",      # ajoute
)
```

`delete()` dans `catalog.py` boucle deja sur cette tuple, donc la
correction est immediate.


## 6. Transactions

### Probleme

Chaque `execute()` est auto-committed. Si `delete()` plante apres 3
tables sur 9, la base est incoherente. Meme risque pour le cycle
register → writes → finalize.

### Strategie

Deux niveaux de protection :

**Niveau 1 — Operations atomiques (obligatoire) :**

Wrapper les operations multi-statements dans des transactions explicites.

```python
def delete(self, sim_id: str | UUID) -> None:
    sid = str(sim_id)
    row = self._db.execute(
        "SELECT zarr_path FROM simulations WHERE sim_id = ?", [sid],
    ).fetchone()

    self._db.begin()
    try:
        for table in PER_SIM_TABLE_NAMES:
            self._db.execute(f"DELETE FROM {table} WHERE sim_id = ?", [sid])
        self._db.execute("DELETE FROM simulations WHERE sim_id = ?", [sid])
        self._db.commit()
    except Exception:
        self._db.rollback()
        raise

    # Zarr hors transaction (filesystem, pas de rollback possible)
    if row and row[0]:
        zarr_abs = self._workspace / row[0]
        if zarr_abs.exists():
            shutil.rmtree(zarr_abs, ignore_errors=True)
```

Appliquer le meme pattern a :
- `import_simulation()` — tous les INSERT dans une transaction
- `export_simulation()` — les ecritures dans le package DuckDB

**Niveau 2 — Cycle de simulation (mode robuste) :**

Le cycle complet (register → extract → finalize) est naturellement
decouvert en phases. On ne wrappe pas tout dans une seule transaction
(c'est trop long et ça bloque l'acces concurrent).

A la place, on utilise le champ `status` comme marqueur :
- `register_simulation()` ecrit `status = 'running'`
- si le solver crash, la ligne reste en `status = 'running'`
- `finalize()` passe a `status = 'completed'` ou `'failed'`
- `cleanup(status='running')` nettoie les simulations abandonnees

C'est deja le pattern prevu par le schema. Il faut juste s'assurer que
`finalize(status='failed')` est appele dans le `except` du runner.

**Mode debug / prototypage :**

En prototypage (notebook, `Project.run()` pas a pas), on veut pouvoir
inspecter l'etat intermediaire apres un crash. Le pattern `status='running'`
le permet : la ligne et les donnees partielles restent en base, lisibles
pour investigation. On n'annule rien.

Pour nettoyer apres debug :

```python
catalog.cleanup(status="running")   # supprime les runs abandonnes
catalog.cleanup(status="failed")    # supprime les runs echoues
```


## 7. Batch writes

### Probleme

`write_budget()` fait un INSERT par appel. Les extracteurs l'appellent
dans une boucle `timesteps x components` soit ~600 INSERT par
simulation. Meme pattern pour `write_mass_balance()`,
`write_geographic_metadata()`, `register_observation_points()`.

### Approche

Remplacer les boucles d'appels unitaires par des methodes batch dans
le catalog, sur le meme pattern que `write_timeseries()`.

### Fichier concerne

- `hydromodpy/results/catalog.py` — nouvelles methodes batch
- `hydromodpy/simulation/results/extractors/modflownwt.py` — adapter les appels
- `hydromodpy/simulation/results/extractors/modflow6.py` — adapter les appels

### Implementation

Ajouter dans `SimulationCatalog` :

```python
def write_budgets(
    self,
    sim_id: str | UUID,
    records: list[dict],
) -> None:
    if not records:
        return
    sid = str(sim_id)
    df = pd.DataFrame(records)
    df["sim_id"] = sid
    self._db.execute(
        "INSERT INTO budgets "
        "(sim_id, timestep, zone_id, component, flux_in, flux_out, unit) "
        "SELECT sim_id, timestep, zone_id, component, flux_in, flux_out, unit "
        "FROM df"
    )


def write_mass_balances(
    self,
    sim_id: str | UUID,
    records: list[dict],
) -> None:
    if not records:
        return
    sid = str(sim_id)
    df = pd.DataFrame(records)
    df["sim_id"] = sid
    self._db.execute(
        "INSERT INTO mass_balance "
        "(sim_id, timestep, total_in, total_out, "
        "storage_in, storage_out, percent_error) "
        "SELECT sim_id, timestep, total_in, total_out, "
        "storage_in, storage_out, percent_error FROM df"
    )
```

Conserver les methodes unitaires `write_budget()` et
`write_mass_balance()` pour les cas ponctuels (tests, usage manuel).

### Adaptation dans les extracteurs

Remplacer la boucle dans `modflownwt.py` :

```python
# Avant (actuel) :
for t, time in enumerate(times):
    for component in record_names:
        store.write_budget(sim_id, t, "0", component, flux_in, flux_out)

# Apres :
budget_records = []
for t, time in enumerate(times):
    for component in record_names:
        budget_records.append({
            "timestep": t,
            "zone_id": "0",
            "component": component.lower().strip(),
            "flux_in": float(flux_in),
            "flux_out": float(abs(flux_out)),
            "unit": "m3/d",
        })
store.write_budgets(sim_id, budget_records)
```

Meme refactoring dans `modflow6.py`.


## 8. Unites dans les timeseries

### Probleme

Les 684 lignes de timeseries ont `unit = ""`. L'appelant
(`catchment_aggregation.py`) ne passe pas d'unite.

### Correction

Dans `catchment_aggregation.py`, definir les unites par variable :

```python
VARIABLE_UNITS = {
    "watertable_depth": "m",
    "watertable_elevation": "m",
    "seepage_areas": "%",
    "outflow_drain": "m3/d/cell",
    "recharge_budget": "m/d",
    "recharge_forcing": "m/d",
    "accumulation_flux": "m3/d",
    "well_pumping": "m3/d",
}
```

Passer `unit=VARIABLE_UNITS.get(variable, "")` a `write_timeseries()`.


## 9. Nettoyage Zarr — rasters intermediaires

### Probleme

Le dossier `geographic/` dans chaque Zarr contient 10 rasters
intermediaires du pipeline WhiteboxTools (`watershed_buff_dem`,
`watershed_buff_fill`, `watershed_buff_direc`, etc.). L'architecture
prevoit seulement `dem` et `geology`.

### Correction

Dans le code qui ecrit les rasters geographiques
(`spatial/geographic/store_ingestion.py`), ne persister que les
rasters finaux necessaires au display et a la derivation :

- `dem` — MNT du bassin versant (utilise pour `watertable_depth`)
- `geology` — carte geologique (si presente)
- `fill` — MNT corrige (optionnel, utile pour le debug)

Les rasters intermediaires (direction, accumulation, buffers) sont
des produits de calcul du pipeline spatial. Ils doivent rester en
memoire pendant le traitement et ne pas etre persistes dans le Zarr.


## 10. Mesh dans le Zarr

### Etat actuel

Le dossier `mesh/` contient `surface_top` et `z_interfaces` mais
pas `vertices` ni `face_node_connectivity`. Ces arrays sont ecrits
par `SimulationZarr.write_mesh()` mais cette methode n'est jamais
appelee avec les vertices dans le workflow normal.

### Correction

Appeler `store.write_mesh()` avec tous les arrays dans
`step_open_store()` ou dans le runner, apres la construction du mesh :

```python
mesh = ctx.setup.domain.mesh
store.write_mesh(
    ctx.sim_id,
    vertices=mesh.vertices,
    face_node_connectivity=mesh.face_node_connectivity,
    z_interfaces=ctx.setup.domain.z_interfaces,
)
```

Le mesh dans le Zarr doit etre autonome : n'importe quel
consommateur (export VTU, `register_observation_points()`,
display) doit pouvoir reconstruire la geometrie a partir du
seul Zarr, sans avoir besoin de relancer le pipeline spatial.

### Stockage des champs par cellule

Le mesh definit la topologie (indices de cellules). Les parametres
spatiaux (K, Sy, topographie par cellule) sont des vecteurs plats
indexes par `cell_id`. Ce pattern est standard (VTK, UGRID, MODFLOW
interne) :

```
mesh/
    vertices                  (n_nodes, 2)       float64
    face_node_connectivity    (n_cells, max_vpf) int32
    z_interfaces              (n_layers+1,)      float64

fields/
    K                         (n_cells,)         float64
    Sy                        (n_cells,)         float64
    topo                      (n_cells,)         float64
```

Le mesh est stocke une fois, les fields sont des arrays plats.
On reconstruit la visualisation spatialisee a la volee en
joignant le mesh et le field par indice.

Chaque simulation garde sa propre copie du mesh dans son Zarr
(isolation). La deduplication via `mesh_hash` reste possible a
terme mais n'est pas necessaire tant que les meshes restent
petits (<10 Mo).


## 11. `rerun()` — relancer une simulation depuis son snapshot

### Principe

Chaque simulation stocke son `config_toml` (Pydantic serialise en
JSON). `rerun()` reconstruit l'objet config, applique des overrides
optionnels, et lance une nouvelle simulation avec un nouvel UUID.
`parent_sim_id` pointe vers la simulation source.

### Fichiers concernes

- `hydromodpy/results/simulation.py` — methode `rerun()`
- `hydromodpy/core/config/` — methode de classe `from_snapshot()` sur `HydroModPyConfig`

### Implementation

**Etape 1 : reconstruction de config depuis snapshot**

Ajouter a `HydroModPyConfig` :

```python
@classmethod
def from_snapshot(cls, snapshot: dict, **overrides) -> "HydroModPyConfig":
    merged = deep_merge(snapshot, overrides)
    return cls.model_validate(merged)
```

`deep_merge` fusionne les overrides dans le snapshot (remplacement
cle par cle, recursif pour les dicts imbriques).

**Etape 2 : methode `rerun()` sur `Simulation`**

```python
def rerun(self, **overrides) -> "Simulation":
    snapshot = self.config
    if snapshot is None:
        raise ValueError(
            f"Simulation '{self.id}' has no config snapshot — cannot rerun"
        )

    new_config = HydroModPyConfig.from_snapshot(snapshot, **overrides)

    # Lancer la simulation avec le nouveau config
    # Le workflow cree un nouvel UUID et ecrit parent_sim_id = self.id
    new_sim_id = run_from_config(
        new_config,
        parent_sim_id=self.id,
        catalog=self._catalog,
    )
    return self._catalog[new_sim_id]
```

**Etape 3 : tracer la filiation**

`register_simulation()` accepte deja `parent_sim_id`. Il suffit de
le passer depuis le workflow quand `rerun()` est utilise.

La filiation permet :
- comparer deux runs (original vs override)
- retrouver l'historique d'un parametre
- tracer la calibration (best_run → session → iterations)

### API utilisateur

```python
sim = catalog["<uuid>"]
sim.config                        # dict du TOML resolu

sim2 = sim.rerun()                # meme config, nouvel UUID
sim3 = sim.rerun(K=2.0, Sy=0.1)  # overrides sur les parametres

sim3.parent_sim_id                # == sim.id
```


## 12. Preparer les metriques (sans les activer)

### Principe

Pas de metriques automatiques hors calibration pour le moment, mais
le schema et l'API sont prets. Le chemin d'ecriture existe deja
(`write_metric()` dans le catalog, `metrics` dans `Simulation`).

### Ce qui est deja en place

- Table `metrics` avec PK `(sim_id, station_id, metric_name)`
- `catalog.write_metric(sim_id, station_id, metric_name, value)`
- `catalog.best(project, metric="nse")` — requete sur la table
- `catalog.find(nse_gt=0.7)` — filtre par seuil
- `Simulation.metrics` — property DataFrame

### Ce qui manquerait pour des metriques automatiques

Un step `step_compute_metrics(ctx)` qui :
1. Recupere les observations depuis `ctx.loaded_data` (piezometry, hydrometry)
2. Recupere les timeseries simulees depuis le store
3. Aligne temporellement obs / sim
4. Calcule NSE, KGE, RMSE via `objective_function.py`
5. Ecrit via `store.write_metric()`

Aujourd'hui ce step n'existe pas et n'est pas necessaire. Quand il
sera active, il s'inserera apres `step_ingest_run_results()`.


## 13. `finalize()` en cas d'echec

### Probleme

Si le solver crash, `finalize()` n'est jamais appele. La simulation
reste en `status = 'running'` indefiniment.

### Correction

Dans le runner (workflow et `Project.run()`), wraper l'execution
dans un try/except qui appelle `finalize(status='failed')` :

```python
try:
    runner.execute(plan, ctx)
    store.finalize(sim_id, status="completed", duration_s=elapsed)
except Exception:
    store.finalize(sim_id, status="failed", duration_s=elapsed)
    raise
```

En mode debug/prototypage, la simulation en `status='failed'` reste
en base avec ses donnees partielles pour investigation.

Nettoyage a la demande :

```python
catalog.cleanup(status="failed")
catalog.cleanup(status="running")  # simulations abandonnees
```


## 14. Ordre d'implementation

Par priorite et dependance :

### Phase 1 — Corrections critiques (sans changement d'API)

| # | Action | Fichiers | Effort |
|---|---|---|---|
| 1.1 | Ajouter geographic_* a `PER_SIM_TABLE_NAMES` | `catalog_schema.py` | 1 ligne |
| 1.2 | Transaction dans `delete()` | `catalog.py` | 10 lignes |
| 1.3 | Transaction dans `import_simulation()` | `catalog.py` | 10 lignes |
| 1.4 | `finalize(status='failed')` dans le except du runner | `store_lifecycle.py`, `project.py` | 5 lignes chacun |

### Phase 2 — Pipeline d'ingestion complet

| # | Action | Fichiers | Effort |
|---|---|---|---|
| 2.1 | Enrichir `register_simulation()` dans les deux call sites | `store_lifecycle.py`, `project.py` | 30 lignes chacun |
| 2.2 | Ecrire les parametres apres registration | `store_lifecycle.py`, `project.py` | 20 lignes + helper |
| 2.3 | Ecrire le mesh complet dans le Zarr | `store_lifecycle.py`, `project.py` | 10 lignes |
| 2.4 | Unites dans catchment_aggregation | `catchment_aggregation.py` | 15 lignes |

### Phase 3 — Optimisation des ecritures

| # | Action | Fichiers | Effort |
|---|---|---|---|
| 3.1 | `write_budgets()` batch dans catalog | `catalog.py` | 20 lignes |
| 3.2 | `write_mass_balances()` batch dans catalog | `catalog.py` | 20 lignes |
| 3.3 | Adapter les extracteurs NWT et MF6 | `modflownwt.py`, `modflow6.py` | 30 lignes chacun |

### Phase 4 — Provenance et nettoyage Zarr

| # | Action | Fichiers | Effort |
|---|---|---|---|
| 4.1 | Step `write_provenance()` dans le workflow | `result_ingestion.py` ou nouveau step | 30 lignes |
| 4.2 | Filtrer les rasters intermediaires dans le Zarr | `store_ingestion.py` | 20 lignes |
| 4.3 | Fiabiliser `_extract_mass_balance()` (logging + robustesse) | `modflownwt.py`, `modflow6.py` | 10 lignes |

### Phase 5 — `rerun()` et reconstruction de config

| # | Action | Fichiers | Effort |
|---|---|---|---|
| 5.1 | `HydroModPyConfig.from_snapshot()` | `core/config/` | 30 lignes |
| 5.2 | `Simulation.rerun()` | `simulation.py` | 40 lignes |
| 5.3 | Passer `parent_sim_id` dans le workflow | `store_lifecycle.py`, `project.py` | 5 lignes |

### Dependances

```
Phase 1 (aucune dependance, faire en premier)
    ↓
Phase 2 (depend de rien, mais 2.1 doit etre fait avant 5.*)
    ↓
Phase 3 (independant de Phase 2, peut etre fait en parallele)
    ↓
Phase 4 (independant)
    ↓
Phase 5 (depend de 2.1 car rerun() a besoin de config_toml non-NULL)
```


## 15. Verification finale

Apres implementation, lancer une simulation et verifier :

```sql
-- 1. Metadata complete
SELECT sim_id, n_cells, n_layers, flow_regime, crs,
       config_hash IS NOT NULL AS has_config,
       mesh_hash IS NOT NULL AS has_mesh_hash
FROM simulations;

-- 2. Parametres ecrits
SELECT * FROM parameters WHERE sim_id = '<uuid>';

-- 3. Budget en batch
SELECT COUNT(*) FROM budgets WHERE sim_id = '<uuid>';

-- 4. Provenance
SELECT variable, checksum FROM provenance WHERE sim_id = '<uuid>';

-- 5. Pas d'orphelins apres delete
DELETE FROM simulations WHERE sim_id = '<uuid>';  -- ne pas faire, utiliser catalog.delete()
SELECT COUNT(*) FROM geographic_features WHERE sim_id = '<uuid>';  -- doit etre 0
```

Et verifier le Zarr :

```python
import zarr
root = zarr.open("simulations/<uuid>.zarr", mode="r")
assert "mesh/vertices" in root
assert "mesh/face_node_connectivity" in root
assert "head" in root
# geographic/ ne doit contenir que dem, geology (pas de buff_direc etc.)
print(list(root["geographic"].keys()))
```
