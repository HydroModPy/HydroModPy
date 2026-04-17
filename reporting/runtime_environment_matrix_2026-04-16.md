# Runtime Environment Matrix

Date: `2026-04-16`

## Principle

The project may use more than one runtime environment, but the split must be
explicit and stable.

Recommended convention:

- **Linux / WSL** is the reference platform for **PETSc-oriented work**
- **Windows** is the reference platform for **documentation, lightweight plots,
  and non-PETSc local tooling**
- outputs are always written back to the repository tree under
  `C:\codes\HydroModPy-GH\out\...`

This keeps PETSc and native scientific runtimes on the platform where they are
most reliable, while preserving simple local access to generated figures and
reports.

## Canonical Matrix

| Task family | Preferred OS | Preferred environment | Why |
| --- | --- | --- | --- |
| Boussinesq PETSc runs (`petsc_partition`, `petsc`) | Linux / WSL | `hydromodpy-petsc` | PETSc support is Linux-first and avoids fragile Windows native issues. |
| Cross-code transient investigations including PETSc | Linux / WSL | `hydromodpy-petsc` | Keeps the full solver stack on one platform and simplifies comparison runs. |
| Boussinesq local / MODFLOW exploratory runs without PETSc | Windows or Linux | `hydromodpy` on Windows, `hydromodpy-wsl` or `hydromodpy-petsc` on Linux | These cases are portable, but Linux is still preferred if the campaign may later include PETSc. |
| Static gallery asset generation (`PNG`, `JSON`) | Windows | `hydromodpy` | Easy access to the docs tree and generated files; no PETSc required. |
| Full documentation gallery rebuild | Windows preferred, fallback Linux | `hydromodpy` | Uses the broad docs/data stack (`rasterio`, `whitebox_workflows`, plotting libs). |
| Analytical validation batches without PETSc | Windows | `hydromodpy` | Matches the main project environment and launcher workflow. |

## Canonical Commands

### 1. Windows `hydromodpy`

Use this for docs, gallery assets, and non-PETSc validation/tooling.

```powershell
C:\Users\dreuzy\.conda\envs\hydromodpy\python.exe -m validation_cases.run_cases --solver modflow6 --regime steady --no-show
C:\Users\dreuzy\.conda\envs\hydromodpy\python.exe tools\doc_gallery\generate_code_comparison_assets.py
C:\Users\dreuzy\.conda\envs\hydromodpy\python.exe -m tools.doc_gallery --check
```

### 2. Linux / WSL `hydromodpy-petsc`

Use this for PETSc-oriented numerical campaigns.

```bash
cd /mnt/c/codes/HydroModPy-GH
source ~/miniforge3/etc/profile.d/conda.sh
conda activate /home/dreuzy/miniforge3/envs/hydromodpy-petsc
python tools/investigate_surface_interaction_hillslope_transient.py \
  --output-root /mnt/c/codes/HydroModPy-GH/out/sih_tx_linux_example \
  --solvers modflownwt modflow6 modflow6_irregular_tri boussinesq petsc_partition petsc
```

## Current Practical Rule

For the recent surface-interaction intercomparison work, the operational rule is:

- **all PETSc-capable comparison runs**: launch in **Linux / WSL**
- **all gallery asset refreshes and docs-facing static packaging**: launch in
  **Windows `hydromodpy`**

This is the default convention to follow unless one task explicitly documents a
different requirement.

## Notes

- The repository environment files already declare the broad raster/docs stack,
  including `rasterio` and `whitebox-workflows`:
  - `install/env_hydromodpy.yml`
  - `install/env_hydromodpy_light.yml`
- If a command fails in a generic `base` Python, that does **not** mean the
  project is missing the dependency. It usually means the wrong environment was
  used.
- Mixing environments is acceptable **by task**, not randomly inside one
  partially reproducible workflow.
