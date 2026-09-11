# 09 - Comparison workflow

Solver and mesh intercomparison, using `workflow.mode = "comparison"` to run
two or more simulation legs from one shared base case and diff their outputs.
Cases range from a synthetic 1D Dupuit sanity check to the Nancon and Vire
catchments (EPSG:2154), steady and transient, comparing MODFLOW 6 against
MODFLOW-NWT and against Boussinesq, and structured grids against DISV and
generated mesh-catchment discretizations at several target cell sizes.

## Run

```bash
hmp run examples/projects/09_comparison_workflow/compare_dupuit_mf6_bouss.toml
hmp run examples/projects/09_comparison_workflow/compare_vire_natural_mf6_nwt.toml
hmp run examples/projects/09_comparison_workflow/compare_nancon_steady_mf6_disv_vs_nwt.toml

# named cases through the Python launcher, writes a report and figures
python examples/projects/09_comparison_workflow/run_comparison_example.py --case synthetic --show
python examples/projects/09_comparison_workflow/run_comparison_example.py --case all --show

# check materialized outputs against locked thresholds, no solver involved
python examples/projects/09_comparison_workflow/check_comparison_stability.py
```

`--case` accepts `synthetic`, `natural`, `natural-bouss`,
`natural-bouss-recharge`, `natural-bouss-transient-pulse`, `nancon-seasonal`,
`nancon-seasonal-hydrography`, `nancon-monthly-bouss-comparable`,
`nancon-seasonal-high-k-hydrography`, `nancon-seasonal-high-k-hydrography-mf6`,
or `all`. Every other `compare_*.toml` in this folder runs only through
`hmp run <file>` directly.

Each comparison runs one MODFLOW 6/NWT/Boussinesq solve per leg, so runtime is
unmeasured here; it was not timed in this pass.

## Data

| Source | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | shared Armorican massif DEM, both catchments |
| BD Topage, provider `bdtopage` | hydrography | observed network, compared against each leg's generated network |
| synthetic recharge | recharge | generated in-config, no shared file |

## What it shows

Every comparison keeps geometry, boundary conditions and forcing fixed across
its legs and varies exactly one thing: the solver backend or the mesh
discretization. `comparison_figures/case_configuration.png` documents the
shared support first, then the `*triptych*.png` figures line up the reference
head field, the candidate head field, and their difference. The PETSc
variants of the Nancon monthly Boussinesq-comparable case (`_petsc_*` files)
isolate one variational-inequality solver option at a time against the same
MODFLOW 6 reference.
