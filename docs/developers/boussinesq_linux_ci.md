# Boussinesq Linux CI

## Purpose

The Boussinesq solver has two Linux-facing test levels:

- a standard Linux smoke suite for the `local`, `scipy`, and `scipy_sparse`
  paths;
- a PETSc smoke suite for the Linux-only `runtime_backend = "petsc"` paths.

The PETSc job is intentionally separate from the default pull-request job
because it needs a heavier PETSc/petsc4py environment.

## GitHub Actions

The workflow lives at:

```text
.github/workflows/linux-boussinesq.yml
```

It defines:

- `boussinesq-linux-smoke`: runs on pull requests and pushes touching the
  Boussinesq, flow-adapter, validation, or CI files.
- `boussinesq-petsc-smoke`: runs on the weekly schedule or manually through
  `workflow_dispatch`.

The standard job runs:

```bash
bash tools/ci/run_boussinesq_linux_smoke.sh
```

The PETSc job runs:

```bash
bash tools/ci/run_boussinesq_petsc_smoke.sh
```

The PETSc smoke suite validates the two current PETSc surface formulations on
two focused benchmarks:

- `petsc_partition`: PETSc with `surface_interaction_model = "regularized_partition"`;
- `petsc`: PETSc with `surface_interaction_model = "complementarity"`.

Covered PETSc smoke cases:

- the small steady Dupuit fixed-head benchmark, used as a compact analytical
  acceptance check;
- the transient hillslope recharge-pulse overflow scenario, used to confirm
  that both PETSc variants do activate the surface-threshold/overflow response
  on a more nonlinear synthetic case;
- the transient real `headwater_100km2_outlet_2` cycling-recharge scenario,
  used to confirm that the mixed complementarity runtime resolves repeated
  activation/deactivation windows on a committed natural mesh while the
  regularized-partition path stays on its smoother always-active response.

## Local WSL Usage

This repository can be tested from WSL with the same scripts once a Linux
environment has the needed packages installed.

Current working local references on this machine:

```text
WSL distro           : Ubuntu 22.04
Linux repo path      : /mnt/c/codes/HydroModPy-GH
Miniforge root       : /home/dreuzy/miniforge3
Standard env         : /home/dreuzy/miniforge3/envs/hydromodpy-wsl
PETSc env            : /home/dreuzy/miniforge3/envs/hydromodpy-petsc
```

Quick checks:

```bash
/home/dreuzy/miniforge3/bin/conda env list
/home/dreuzy/miniforge3/bin/conda run -n hydromodpy-petsc python -c "import petsc4py, whitebox_workflows, hydromodpy; print('ok')"
```

Bootstrap a conda-forge PETSc environment from PowerShell:

```powershell
wsl.exe bash -lc "source ~/miniforge3/etc/profile.d/conda.sh && mamba create -y -n hydromodpy-petsc -c conda-forge --strict-channel-priority python=3.12 pip petsc petsc4py mpi4py dask plotly numpy scipy pytest pytest-xdist pandas xarray pydantic matplotlib shapely pyproj geopandas rasterio rioxarray flopy h5py netcdf4 pint pyshp scikit-learn meshio imageio requests geopy selenium tqdm sqlalchemy"
wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy-GH && source ~/miniforge3/etc/profile.d/conda.sh && conda activate hydromodpy-petsc && python -m pip install pysheds tomli-w whitebox-workflows && python -m pip install -e . --no-deps"
```

Minimal non-PETSc command from PowerShell:

```powershell
wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy-GH && source ~/miniforge3/etc/profile.d/conda.sh && conda activate hydromodpy-petsc && bash tools/ci/run_boussinesq_linux_smoke.sh"
```

PETSc command from PowerShell after activating a conda-forge environment that
contains `petsc`, `petsc4py`, and the HydroModPy test dependencies:

```powershell
wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy-GH && source ~/miniforge3/etc/profile.d/conda.sh && conda activate hydromodpy-petsc && bash tools/ci/run_boussinesq_petsc_smoke.sh"
```

Direct multi-method Boussinesq comparison already validated on Linux with the
PETSc environment:

```powershell
wsl.exe /home/dreuzy/miniforge3/bin/conda run -n hydromodpy-petsc python -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_multi_solver_case --solvers boussinesq petsc_partition petsc --forcing-preset strong --output-root /mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_20260413
```

Generated outputs:

```text
/mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_20260413
```

## Real 100 km2 Case

The steady headwater 100 km2 PETSc replay remains a diagnostic/manual run, not
a default CI test:

```bash
python -m hydromodpy run examples/projects/launcher_simulation/run_headwater_100km2_outlet_2_boussinesq_petsc_partition_mesh_input.toml
```

It is larger, more nonlinear, and intended for focused solver diagnostics.
The smoke CI keeps PETSc availability and the two formulations checked without
turning every pull request into a long nonlinear benchmark.
