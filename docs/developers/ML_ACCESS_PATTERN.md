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
filtered out post-hoc. Schema:

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
| `git_commit`         | VARCHAR      | Repository commit (when known)         |
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

The recommended split key is `simulations.scientific_objective` (a forthcoming
column tracked under S04-16). Until it ships, group by `simulations.project`
or `simulations.tags` to isolate held-out catchments:

```python
import numpy as np

projects = features["project"].unique()
rng = np.random.default_rng(seed=42)
rng.shuffle(projects)

train_projects = projects[: int(0.7 * len(projects))]
val_projects = projects[int(0.7 * len(projects)) : int(0.85 * len(projects))]
test_projects = projects[int(0.85 * len(projects)) :]

train = features[features["project"].isin(train_projects)]
val = features[features["project"].isin(val_projects)]
test = features[features["project"].isin(test_projects)]
```

Splitting by `project` (or by `scientific_objective` once available) avoids
leakage across catchments that share a regional aquifer or a calibration
period.
