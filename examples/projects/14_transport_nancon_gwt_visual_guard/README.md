# 14 - Transport visual guard on the Nancon mesh

Visual guard for MODFLOW 6 transport work on the real Nancon triangular DISV
mesh (EPSG:2154), ahead of any refactor to the transport code. Two backends
are exercised side by side: a deterministic synthetic-velocity plume renderer
for fast visual inspection, and a real MODFLOW 6 steady GWF flow model coupled
to the `transport/modflow6prt` PRT backend for actual particle tracking.

## Run

```bash
# synthetic-velocity plume report, all three cases
python examples/projects/14_transport_nancon_gwt_visual_guard/run_nancon_visual_guard.py

# one case only
python examples/projects/14_transport_nancon_gwt_visual_guard/run_nancon_visual_guard.py --case nancon_01_internal_pulse

# real steady MF6 flow + PRT pathline tracking, needs a PRT-capable mf6 binary
hmp install-binaries --mf6-prt
hmp run examples/projects/14_transport_nancon_gwt_visual_guard/run_nancon_steady_mf6_prt_pathlines.toml
```

Runtime unmeasured here: both commands need a Nancon mesh bundle produced by
running `examples/projects/09_comparison_workflow` first
(`outputs/nancon_transient_seasonal_hydrography/workspace_mf6/mesh/mesh_catchment_bundle`),
and the PRT run additionally needs an `mf6` executable recent enough to
support PRT. Neither was available on this machine to time.

Outputs land under `examples/projects/14_transport_nancon_gwt_visual_guard/outputs/`:
one HTML report per case, its figures, and `signatures.json` / `signatures.csv`
with the numeric checks behind the plots.

## Cases

- `nancon_01_internal_pulse`: compact pulse released away from the upstream
  boundary.
- `nancon_02_upstream_pulse`: finite upstream concentration pulse.
- `nancon_03_constant_upstream`: constant upstream concentration source.

All three use a homogeneous transport setup, with the diffusion coefficient
picked from a target mean cell Peclet number near 20.

## What it shows

The synthetic-velocity backend is real Nancon mesh, topography and river
constraints, but a controlled synthetic velocity field, so plume motion stays
readable. It is not a coupled MF6-GWT solve.

The PRT overlay is particle tracking, not a concentration-transport solve. It
solves a steady MODFLOW 6 GWF model, attaches a PRT model through the
`GWF6-PRT6` exchange, and releases 300 particles over active non-river cells.
PRT integrates each particle through the specific-discharge budget and the MIP
porosity. HydroModPy reads the PRT track CSV that MODFLOW 6 writes to disk and
stores `pathlines/x`, `pathlines/y`, `pathlines/z` and `pathlines/time` arrays
in the run's Zarr store. There is no in-memory path yet: `mf6` writes
`*.trk.csv` (and optionally `*.trk`) before HydroModPy ingests it, which is why
the launcher sets `simulation.results.keep_solver_files = true`.
