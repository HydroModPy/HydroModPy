# CI Linux pour Boussinesq

Liens : [boussinesq_solver_architecture.md](boussinesq_solver_architecture.md),
[boussinesq_petsc_vs_marcais_2017.md](boussinesq_petsc_vs_marcais_2017.md),
[boussinesq_petsc_headwater_100km2_diagnostic.md](boussinesq_petsc_headwater_100km2_diagnostic.md).

## Objectif

Le solveur Boussinesq dispose de deux niveaux de tests Linux :

- Une suite smoke standard pour les chemins `local`, `scipy` et
  `scipy_sparse`.
- Une suite smoke PETSc pour les chemins `runtime_backend = "petsc"`,
  disponibles uniquement sous Linux.

Le job PETSc est volontairement séparé du job PR par défaut car il
impose un environnement PETSc et petsc4py plus lourd.

## GitHub Actions

Workflow :

```
.github/workflows/linux-boussinesq.yml
```

Deux jobs :

- `boussinesq-linux-smoke` : s'exécute sur les PR et les pushes qui
  modifient Boussinesq, l'adapter flow, la validation ou les fichiers
  CI.
- `boussinesq-petsc-smoke` : s'exécute sur le schedule hebdomadaire ou
  manuellement via `workflow_dispatch`.

Commandes correspondantes :

```bash
bash tools/ci/run_boussinesq_linux_smoke.sh
bash tools/ci/run_boussinesq_petsc_smoke.sh
```

La suite smoke PETSc valide les deux formulations de surface
supportées :

- `petsc_partition` : PETSc avec
  `surface_interaction_model = "regularized_partition"`.
- `petsc` : PETSc avec `surface_interaction_model = "complementarity"`.

Cas couverts :

- Benchmark Dupuit analytique en régime permanent (sanity check).
- Scénario transitoire hillslope recharge pulse overflow (vérifie
  l'activation du seuil de surface).
- Scénario transitoire réel `headwater_100km2_outlet_2` cycling recharge
  (vérifie que la variante complementarity gère des cycles
  activation/désactivation sur un maillage naturel).

## Usage local WSL

Le dépôt peut être testé depuis WSL avec les mêmes scripts, une fois un
env Linux muni des dépendances.

Références de travail actuelles (machine de référence) :

```
WSL distro     : Ubuntu 22.04
Linux repo     : /mnt/c/codes/HydroModPy-GH
Miniforge root : /home/dreuzy/miniforge3
Standard env   : /home/dreuzy/miniforge3/envs/hydromodpy-wsl
PETSc env      : /home/dreuzy/miniforge3/envs/hydromodpy-petsc
```

Checks rapides :

```bash
/home/dreuzy/miniforge3/bin/conda env list
/home/dreuzy/miniforge3/bin/conda run -n hydromodpy-petsc python -c "import petsc4py, whitebox_workflows, hydromodpy; print('ok')"
```

Paquets système nécessaires aux benchmarks basés sur gmsh :

```bash
apt-get install -y libxft2 libglu1-mesa libgl1 libxcursor1 libxinerama1 libxrandr2 libfreetype6 libfontconfig1
```

Bootstrap d'un env PETSc conda-forge depuis PowerShell :

```powershell
wsl.exe bash -lc "source ~/miniforge3/etc/profile.d/conda.sh && mamba create -y -n hydromodpy-petsc -c conda-forge --strict-channel-priority python=3.12 pip petsc petsc4py mpi4py dask plotly numpy scipy pytest pytest-xdist pandas xarray pydantic matplotlib shapely pyproj geopandas rasterio rioxarray flopy h5py netcdf4 pint pyshp scikit-learn meshio imageio requests geopy selenium tqdm sqlalchemy"
wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy-GH && source ~/miniforge3/etc/profile.d/conda.sh && conda activate hydromodpy-petsc && python -m pip install pysheds tomli-w whitebox-workflows && python -m pip install -e . --no-deps"
```

Commande smoke non-PETSc depuis PowerShell :

```powershell
wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy-GH && source ~/miniforge3/etc/profile.d/conda.sh && conda activate hydromodpy-petsc && bash tools/ci/run_boussinesq_linux_smoke.sh"
```

Commande PETSc :

```powershell
wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy-GH && source ~/miniforge3/etc/profile.d/conda.sh && conda activate hydromodpy-petsc && bash tools/ci/run_boussinesq_petsc_smoke.sh"
```

## Benchmarks validés

Comparaison multi-méthodes Boussinesq sur Linux avec env PETSc :

```powershell
wsl.exe /home/dreuzy/miniforge3/bin/conda run -n hydromodpy-petsc python -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_multi_solver_case --solvers boussinesq petsc_partition petsc --forcing-preset strong --output-root /mnt/c/codes/HydroModPy-GH/out/boussinesq_hillslope_overflow_multi_linux_20260413
```

Benchmark transitoire cross-model sous Linux incluant MODFLOW-NWT,
MODFLOW 6, MODFLOW 6 triangles irréguliers et Boussinesq :

```powershell
wsl.exe /home/dreuzy/miniforge3/bin/conda run -n hydromodpy-petsc python -m tools.investigate_surface_interaction_hillslope_transient --output-root /mnt/c/codes/HydroModPy-GH/out/sih_tx_4cmp_linux_20260414
```

Benchmark gallery haute conductivité avec MODFLOW 6 et Boussinesq PETSc
complementarity :

```powershell
wsl.exe /home/dreuzy/miniforge3/bin/conda run -n hydromodpy-petsc python /mnt/c/codes/HydroModPy-GH/tools/investigate_surface_interaction_highk_linux.py
```

Benchmark comparant MODFLOW-NWT avec les trois variantes Boussinesq sur
un même forçage `4 mois montée / 4 mois descente / 6 mois sec` :

```powershell
wsl.exe /home/dreuzy/miniforge3/bin/conda run -n hydromodpy-petsc python -m tools.investigate_linux_nwt_boussinesq_transient --output-root /mnt/c/codes/HydroModPy-GH/out/linux_nwt_bouss_4m4m6m_20260414
```

## Cas réel 100 km²

Le replay permanent `headwater 100 km²` sous PETSc reste un run
diagnostique manuel, pas un test CI par défaut :

```bash
python -m hydromodpy run examples/projects/launcher_simulation/run_headwater_100km2_outlet_2_boussinesq_petsc_partition_mesh_input.toml
```

Cas plus gros et plus nonlinéaire, réservé aux diagnostics ciblés. La
CI smoke préserve la disponibilité PETSc et les deux formulations sans
transformer chaque PR en benchmark nonlinéaire long.
