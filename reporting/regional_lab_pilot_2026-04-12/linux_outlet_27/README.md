# Linux outlet 27 backend probe

This folder contains Linux/WSL probe configs for the sanitized
`headwater_100km2_outlet_27` bundle.

Environment used on 2026-04-12:

- WSL2 `Ubuntu-22.04`
- conda environment `hydromodpy-petsc`
- editable repo at `/mnt/c/codes/HydroModPy-GH`

Configs:

- `run_headwater_100km2_outlet_27_boussinesq_scipy_sparse_linux.toml`
- `run_headwater_100km2_outlet_27_boussinesq_petsc_partition_linux.toml`
- `run_headwater_100km2_outlet_27_boussinesq_petsc_mixed_linux.toml`

Observed results on the same sanitized bundle:

| Backend | Surface model | Status | Nonlinear iterations | Residual inf | Peak active fraction | Peak head above top |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `scipy_sparse` | `regularized_partition` | failed | 200 | 3.714e-1 | 0.6132 | 36.5647 m |
| `petsc_partition` | `regularized_partition` | solved | 14 | 7.468e-11 | 0.2440 | 9.538e-6 m |
| `petsc_mixed` | `complementarity` | solved | 10 | 4.887e-8 | 0.2440 | 8.491e-13 m |

Additional timing data from `_metrics.json`:

- `petsc_partition`: `8.4 s`
- `petsc_mixed`: `5.16 s`

Interpretation:

- the outlet-27 failure is not a universal Boussinesq failure on this geometry;
- it is reproducibly a `scipy_sparse` failure on the current regularized-partition
  path for this case;
- both PETSc variants converge on the same mesh and sanitized bundle;
- the PETSc runs also land on a much smaller overflow-active fraction than the
  failed SciPy sparse run.

Generated figures:

- backend comparison summary:
  - `linux_backend_comparison.png`
  - `linux_backend_comparison.csv`
- `scipy_sparse` post-hoc figures:
  - `outputs/linux_compare_outlet_27/scipy_sparse/results_simulations/flow_main__boussinesq/_postprocess/_figures/dem_overview.png`
  - `outputs/linux_compare_outlet_27/scipy_sparse/results_simulations/flow_main__boussinesq/_postprocess/_figures/hydrography.png`
- `petsc_partition` figures:
  - `outputs/linux_compare_outlet_27/petsc_partition/results_simulations/flow_main__boussinesq/_postprocess/_figures/boussinesq_state.png`
  - `outputs/linux_compare_outlet_27/petsc_partition/results_simulations/flow_main__boussinesq/_postprocess/_figures/boussinesq_diagnostics.png`
  - `outputs/linux_compare_outlet_27/petsc_partition/results_simulations/flow_main__boussinesq/_postprocess/_figures/boussinesq_edge_flux.png`
  - `outputs/linux_compare_outlet_27/petsc_partition/results_simulations/flow_main__boussinesq/_postprocess/_figures/flow_state_triptych.png`
  - `outputs/linux_compare_outlet_27/petsc_partition/results_simulations/flow_main__boussinesq/_postprocess/_figures/dem_overview.png`
  - `outputs/linux_compare_outlet_27/petsc_partition/results_simulations/flow_main__boussinesq/_postprocess/_figures/hydrography.png`
- `petsc_mixed` figures:
  - `outputs/linux_compare_outlet_27/petsc_mixed/results_simulations/flow_main__boussinesq/_postprocess/_figures/boussinesq_state.png`
  - `outputs/linux_compare_outlet_27/petsc_mixed/results_simulations/flow_main__boussinesq/_postprocess/_figures/boussinesq_diagnostics.png`
  - `outputs/linux_compare_outlet_27/petsc_mixed/results_simulations/flow_main__boussinesq/_postprocess/_figures/boussinesq_edge_flux.png`
  - `outputs/linux_compare_outlet_27/petsc_mixed/results_simulations/flow_main__boussinesq/_postprocess/_figures/flow_state_triptych.png`
  - `outputs/linux_compare_outlet_27/petsc_mixed/results_simulations/flow_main__boussinesq/_postprocess/_figures/dem_overview.png`
  - `outputs/linux_compare_outlet_27/petsc_mixed/results_simulations/flow_main__boussinesq/_postprocess/_figures/hydrography.png`

Reproduction:

```bash
source ~/miniforge3/etc/profile.d/conda.sh
conda activate hydromodpy-petsc
cd /mnt/c/codes/HydroModPy-GH
python reporting/regional_lab_pilot_2026-04-12/linux_outlet_27/make_linux_outlet_27_graphs.py
```
