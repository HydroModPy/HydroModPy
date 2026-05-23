# Nancon Transport Visual Guard

This example is a dedicated visual guard for future Nancon MODFLOW 6 GWT
transport work.

It is intentionally separate from the synthetic `13_transport_mf6_gwt_disv_visual_guard`
example. The goal here is to inspect transport behavior on a real Nancon
triangular DISV mesh before refactoring the production transport code.

## Input Mesh

By default, the runner reuses the existing Nancon mesh bundle:

```text
examples/projects/09_comparison_workflow/outputs/nancon_transient_seasonal_hydrography/workspace_mf6/mesh/mesh_catchment_bundle
```

The bundle must contain:

- `nodes.csv`
- `cells.csv`
- `edges.csv`

The default local bundle has about 6200 triangular cells and river-only
constraints.

## What It Produces

For each case:

- `index.html`
- `figures/domain_context.png`
- `figures/mesh_overview.png`
- `figures/topography.png`
- `figures/flow_head_direction.png`
- `figures/cell_peclet.png`
- `figures/concentration_snapshots.png`
- `figures/concentration_profiles.png`
- `figures/probe_breakthrough.png`
- `figures/plume_evolution.png`
- `figures/network_exposure.png`
- `signatures.json`
- `signatures.csv`

The current backend is deterministic and visual. It uses the real Nancon mesh,
topography and river constraints, but a controlled synthetic velocity field so
that plume motion is readable in a compact report. It is not yet a coupled
MF6-GWT validation run.

A real MODFLOW 6 PRT pathline overlay is also provided as an explicit launcher
entry point:

```text
run_nancon_steady_mf6_prt_pathlines.toml
```

This overlay runs a steady MODFLOW 6 DISV flow model on the same Nancon mesh,
then runs the new `transport/modflow6prt` backend with 300 release points spread
over active non-river cells. It requires a MODFLOW 6 executable recent
enough to support PRT.

The PRT overlay is particle tracking, not a concentration-transport solve. The
workflow first solves the steady GWF flow model, then attaches a MODFLOW 6 PRT
model through the `GWF6-PRT6` exchange. PRT integrates each released particle
through the flow field using the MODFLOW 6 specific-discharge budget and the MIP
porosity. HydroModPy currently reads the PRT track CSV written by MODFLOW 6 and
stores vectorized `pathlines/x`, `pathlines/y`, `pathlines/z` and
`pathlines/time` arrays in the simulation Zarr store for plotting.

This means the current HydroModPy path is file-mediated. Because MODFLOW 6 is
run as an external executable through FloPy, PRT writes its track output to disk
(`*.trk.csv` and optionally `*.trk`) before HydroModPy can ingest it. The HTML
builder can read the CSV directly from the solver scratch directory with
`--track-csv` or `--prefer-track-csv`, which bypasses the Zarr read for
pathlines but still consumes the file written by `mf6`. There is no current
in-memory callback that returns particle paths directly from the running `mf6`
process.

The PRT launcher keeps solver files via `simulation.results.keep_solver_files =
true` so the raw `*.trk.csv` remains available for inspection and direct report
generation.

For smoother plotted pathlines, `transport.modflow6prt.parameters` supports
`track_time_step_days`. When `track_times_days` is omitted, this option generates
regular tracking output times from zero to `stop_time_days` without listing every
time explicitly in the TOML. The demonstrative launcher uses a 2-day tracking
interval to keep the plotted lines visibly discretized.

## Cases

- `nancon_01_internal_pulse`: compact internal pulse away from the upstream
  boundary.
- `nancon_02_upstream_pulse`: finite upstream concentration pulse.
- `nancon_03_constant_upstream`: constant upstream concentration source.

All cases use a homogeneous transport setup and choose the diffusion coefficient
from a target mean cell Peclet number near 20.

## Usage

Generate all reports:

```powershell
python examples/projects/14_transport_nancon_gwt_visual_guard/run_nancon_visual_guard.py
```

Write and run the real steady MF6 + PRT pathline case:

```powershell
hmp install-binaries --mf6-prt
hmp run examples/projects/14_transport_nancon_gwt_visual_guard/run_nancon_steady_mf6_prt_pathlines.toml
```

Generate one case:

```powershell
python examples/projects/14_transport_nancon_gwt_visual_guard/run_nancon_visual_guard.py --case nancon_01_internal_pulse
```

Use another mesh bundle:

```powershell
python examples/projects/14_transport_nancon_gwt_visual_guard/run_nancon_visual_guard.py --mesh-bundle path\to\mesh_catchment_bundle
```

Outputs are written under:

```text
examples/projects/14_transport_nancon_gwt_visual_guard/outputs/
```
