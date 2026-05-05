# ML access pattern

This page documents the *machine learning* access pattern of HydroModPy. The
goal is to let a sklearn / PyTorch / xgboost / JAX pipeline plug directly into
HydroModPy results without touching solver internals.

The promise rests on three storage formats wired into every workspace:

| Format  | File                                            | Best for                                |
|---------|-------------------------------------------------|-----------------------------------------|
| DuckDB  | `workspace/hydromodpy.duckdb`                   | SQL queries on metadata + tabular views |
| Parquet | `workspace/simulations/<basename>.parquet/*.parquet` | Batched DataFrame loading per run    |
| Zarr    | `workspace/simulations/<basename>.zarr/`        | Tensor / DataArray access on fields     |

`<basename>` is built from the simulation's `(project, name, sim_id)`. Older
workspaces fall back to the bare `sim_id`. The catalog column
`simulations.storage_basename` is the source of truth.

## 1. SQL queries via DuckDB

The catalog is a single DuckDB file. Open it read-only when training, since
DuckDB allows concurrent readers but only one writer:

```python
import duckdb

con = duckdb.connect("workspace/hydromodpy.duckdb", read_only=True)
con.sql("SHOW TABLES").show()
```

Typical feature/label join across `simulations`, `parameters` and `metrics`:

```python
features = con.sql(
    """
    SELECT
        s.sim_id,
        s.project,
        p.K,
        p.Sy,
        p.recharge,
        m.metric_value AS nse
    FROM simulations s
    JOIN parameters p USING (sim_id)
    JOIN metrics m USING (sim_id)
    WHERE s.status = 'success' AND m.metric_name = 'nse'
    """
).df()
```

The `timeseries`, `budgets` and `mass_balance` views are Parquet-backed: SQL
queries on them transparently scan the per-simulation files.

## 2. Batched Parquet loading

Each successful run materialises three Parquet files under
`workspace/simulations/<basename>.parquet/`:

- `timeseries.parquet` (head, flow, recharge, ET, etc. per timestep)
- `budgets.parquet` (per-cell water-balance components)
- `mass_balance.parquet` (catchment-scale closure)

These files are independent, so a sklearn / PyTorch loader can fan out without
the catalog in the loop:

```python
from pathlib import Path

import pandas as pd

workspace = Path("workspace")
files = sorted(workspace.glob("simulations/*.parquet/timeseries.parquet"))
batch = pd.concat(
    (pd.read_parquet(f).assign(sim_id=f.parent.name.split("__")[-1]) for f in files),
    ignore_index=True,
)
```

For sklearn:

```python
from sklearn.ensemble import RandomForestRegressor

X = features[["K", "Sy", "recharge"]].to_numpy()
y = features["nse"].to_numpy()
model = RandomForestRegressor().fit(X, y)
```

## 3. Zarr fields for tensor pipelines

Spatial fields are persisted as Zarr v3 stores. Open them with `xarray`
(structured grids) or `xugrid` (unstructured DISV / DISU meshes):

```python
import xarray as xr

ds = xr.open_zarr("workspace/simulations/getting_started__synthetic__a1b2c3d4.zarr")
head = ds["head"]            # dims: (time, layer, y, x)
recharge = ds["recharge"]    # dims: (time, y, x)
```

A minimal PyTorch `Dataset` wrapping a list of runs:

```python
from pathlib import Path

import torch
import xarray as xr
from torch.utils.data import DataLoader, Dataset


class HydroModPyDataset(Dataset):
    def __init__(self, zarr_paths: list[Path], variable: str = "head") -> None:
        self.paths = zarr_paths
        self.variable = variable

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, idx: int) -> torch.Tensor:
        ds = xr.open_zarr(self.paths[idx])
        return torch.from_numpy(ds[self.variable].values)


paths = sorted(Path("workspace/simulations").glob("*.zarr"))
loader = DataLoader(HydroModPyDataset(paths), batch_size=4, num_workers=2)
```

## 4. Provenance: the `runs_environment` table

Every run records the host environment so an experiment can be reproduced or
filtered out post-hoc. The workflow populates the table at registration time
via `SimulationCatalog.write_run_environment(sim_id)` (see
`hydromodpy/results/run_environment.py`). Schema:

| Column               | Type         | Meaning                                |
|----------------------|--------------|----------------------------------------|
| `sim_id`             | UUID (PK)    | Foreign reference to `simulations`     |
| `python_version`     | VARCHAR      | Runtime Python version                 |
| `hydromodpy_version` | VARCHAR      | Package version at run time            |
| `platform`           | VARCHAR      | `platform.platform()` string           |
| `hostname`           | VARCHAR      | Host that produced the run             |
| `user_name`          | VARCHAR      | OS user                                |
| `cpu_info`           | JSON         | CPU model, core count, frequency       |
| `memory_gb`          | DOUBLE       | Total RAM available at run time        |
| `git_commit`         | VARCHAR      | HydroModPy repository commit           |
| `project_git_commit` | VARCHAR      | User project repository commit         |
| `mf6_binary_sha256`  | VARCHAR      | SHA-256 of the active MODFLOW binary   |
| `env_packages`       | JSON         | `pip freeze`-style package manifest    |
| `recorded_at`        | TIMESTAMPTZ  | Insertion timestamp                    |

Filter a training set to a single hardware / version combination:

```python
clean = con.sql(
    """
    SELECT s.sim_id
    FROM simulations s
    JOIN runs_environment e USING (sim_id)
    WHERE e.hydromodpy_version = '1.0.0'
      AND e.python_version LIKE '3.12%'
    """
).df()
```

## 5. Train / validation / test splits

`SimulationCatalog.training_split` returns three lists of `sim_id`s, split
deterministically with optional stratification:

```python
from hydromodpy.results.catalog import SimulationCatalog

catalog = SimulationCatalog("workspace/")
train, val, test = catalog.training_split(
    test_size=0.2,
    val_size=0.1,
    stratify_by="scientific_objective",
    random_state=42,
)
```

Allowed values for `stratify_by`: `scientific_objective`, `project`, `solver`,
`solver_category`, `flow_regime`, `study_area_name`. Pass `None` to disable
stratification. Stratification falls back to `None` automatically when at
least one class has fewer than 2 members; the function never raises in that
case.

The function requires `scikit-learn` (optional dependency). It raises
`hydromodpy.results.catalog.discovery.MissingMLDependencyError` with an
install hint if the import fails.

To label simulations with a scientific objective, either pass it at
registration time:

```python
catalog.register_simulation(sid, project="bv_morbihan", solver="modflow6",
                            scientific_objective="calibration_recharge")
```

or update an existing row:

```python
catalog.write_scientific_objective(
    sid,
    "calibration_recharge",
    description="Recharge sensitivity sweep over 12 catchments",
    contact_email="hydro@example.org",
    doi="10.5281/zenodo.0",
    study_area_name="Morbihan",
    outlet_x=247_500.0,
    outlet_y=6_770_000.0,
)
```

A run that finalises without a `scientific_objective` is auto-tagged as
`unspecified` (with a warning). Splitting by objective then merges those into
the same stratum, so prefer setting an explicit value before training.

## 6. PyTorch DataLoader pattern

`Run.to_xarray_batch(variables=...)` returns a lazy `xarray.Dataset` ready
to feed a tensor pipeline. Combined with the `training_split` helper:

```python
import torch
from torch.utils.data import Dataset, DataLoader

from hydromodpy.results.catalog import SimulationCatalog


class HydroModPyDataset(Dataset):
    def __init__(self, catalog: SimulationCatalog,
                 sim_ids: list[str], variables: tuple[str, ...]) -> None:
        self.catalog = catalog
        self.sim_ids = sim_ids
        self.variables = variables

    def __len__(self) -> int:
        return len(self.sim_ids)

    def __getitem__(self, i: int) -> torch.Tensor:
        run = self.catalog[self.sim_ids[i]]
        ds = run.to_xarray_batch(self.variables)
        return torch.from_numpy(ds.to_array().values)


catalog = SimulationCatalog("workspace/")
train_ids, val_ids, test_ids = catalog.training_split()
loader = DataLoader(
    HydroModPyDataset(catalog, train_ids, ("head", "concentration")),
    batch_size=4,
)
```
