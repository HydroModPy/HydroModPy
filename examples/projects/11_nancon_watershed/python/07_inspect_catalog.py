"""Nancon - Python script 07 - Inspect the run catalog from Python.

After any `hmp run` or Python run has populated `hydromodpy.duckdb`,
this script reads it back via the public `Project.runs` accessor and
the per-run `Run` view (Zarr field arrays + Parquet timeseries).

What it does:

* list every simulation registered in the project catalog,
* pick the most recent simulation,
* print run metadata, mesh shape, params, and the first timeseries
  variable available.

No solver work is performed; everything is read-only.

Launch (after at least one run has been executed):
    python examples/projects/11_nancon_watershed/python/07_inspect_catalog.py
"""

from pathlib import Path

import hydromodpy as hmp
from hydromodpy.results.views import saturated_fraction

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent
PROJECT_TOML = PROJECT_DIR / "project.toml"


# ---------------------------------------------------------------------
# 1. Open the project (read-only, no display)
# ---------------------------------------------------------------------

project = hmp.Project(PROJECT_TOML, no_display=True)


# ---------------------------------------------------------------------
# 2. List every simulation registered in the catalog
# ---------------------------------------------------------------------

# `project.runs.list()` returns a pandas DataFrame indexed by sim_id.
df = project.runs.list()

if df is None or df.empty:
    print("no simulations registered yet - run at least one TOML first.")
    project.close()
    raise SystemExit(0)

print(f"{len(df)} simulation(s) in this project:")
for _, row in df.iterrows():
    name = row.get("name") or "(unnamed)"
    sim_id = row.get("sim_id", "") or row.name
    status = row.get("status") or "unknown"
    print(f"  - {name:<35s} sim_id={sim_id} status={status}")


# ---------------------------------------------------------------------
# 3. Pick the most recent simulation as a Run view
# ---------------------------------------------------------------------

# `project.runs.latest()` returns a Run view backed by Zarr/Parquet.
latest = project.runs.latest()


# ---------------------------------------------------------------------
# 4. Print mesh / time / params summary
# ---------------------------------------------------------------------

if latest is not None:
    print()
    print(f"== Latest run: {latest.name} ==")
    print(f"  sim_id      = {latest.sim_id}")
    print(f"  status      = {latest.status}")
    print(f"  grid shape  = {latest.grid.shape}")
    print(f"  cell size   = {latest.grid.cell_size} m")
    print(f"  n_steps     = {len(latest.time_index)}")
    print(f"  params      = {dict(latest.params)}")


# ---------------------------------------------------------------------
# 5. Demonstrate a per-run derived helper
# ---------------------------------------------------------------------

if latest is not None:
    try:
        sat = saturated_fraction(latest)
        print(f"  sat. frac.  : min={sat.min():.3f} max={sat.max():.3f}")
    except Exception as exc:  # noqa: BLE001
        print(f"  sat. frac.  : unavailable ({exc.__class__.__name__})")


project.close()
