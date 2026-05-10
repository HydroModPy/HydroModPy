# Natural Geology/K Boussinesq Regional Lab

This folder contains the natural Boussinesq/MODFLOW 6 regional-lab campaign
scaffold.

Status: implemented planning scaffold, not yet a completed natural simulation
campaign. The site selection and stratification are regional-lab concerns; the
execution still goes through the generic `workflow = "testbed"` and
`workflow = "comparison"` path.

## Files

- `natural_regional_lab_sites.csv`: unified regional site catalog. It contains
  N1 10 km2 rows, N2 100 km2 rows, N3 anchors, provenance tags, scale classes
  and paths to generated comparison TOMLs.
- `natural_regional_lab.toml`: regional-lab inventory/planning entry point. It
  plans N1, N2 and N3 comparison recipes from the unified catalog.
- `natural_10km2_mf6_bouss_testbed.toml`: N1 testbed. It selects 8 active
  10 km2 rows and generates one comparison TOML per site.
- `natural_100km2_mf6_bouss_testbed.toml`: N2 testbed. It selects 9 active
  100 km2 rows and generates one comparison TOML per site.
- `natural_n3_mesh_sensitivity_mf6_bouss_testbed.toml`: N3 testbed. It selects
  3 anchor sites and generates coarse/reference/refined mesh-comparison TOMLs.
- `compare_natural_10km2_mf6_bouss_base.toml`: common N1 comparison template.
- `compare_natural_100km2_mf6_bouss_base.toml`: N2 comparison template, based
  on the N1 template with larger support, river and mesh settings.
- `compare_natural_n3_mesh_sensitivity_mf6_bouss_base.toml`: N3 comparison
  template, with mesh settings supplied by the N3 testbed rules.
- `base_site_01_mf6_bouss_transient.toml`: shared physical simulation base:
  DEM, hydrography, geology, recharge, domain, flow parameters and simulation
  window.

`natural_10km2_sites.csv` is kept as the older compact N1-only catalog. New
regional-lab work should use `natural_regional_lab_sites.csv`.

## Run Order

Generate N1 comparison TOMLs:

```powershell
python -m hydromodpy run `
  examples\projects\10_testbed_workflow\boussinesq\natural_geology_k\natural_10km2_mf6_bouss_testbed.toml
```

Generate N2 comparison TOMLs:

```powershell
python -m hydromodpy run `
  examples\projects\10_testbed_workflow\boussinesq\natural_geology_k\natural_100km2_mf6_bouss_testbed.toml
```

Generate N3 mesh-sensitivity comparison TOMLs:

```powershell
python -m hydromodpy run `
  examples\projects\10_testbed_workflow\boussinesq\natural_geology_k\natural_n3_mesh_sensitivity_mf6_bouss_testbed.toml
```

Build the regional-lab inventory:

```powershell
python -m hydromodpy run `
  examples\projects\10_testbed_workflow\boussinesq\natural_geology_k\natural_regional_lab.toml
```

The regional-lab file has `execute = false`. It is an inventory/planning layer
over generated comparison TOMLs. Actual Boussinesq PETSc runs should be launched
from WSL in the `hydromodpy-wsl` environment.

## HTML Synthesis

Refresh the three testbed synthesis pages:

```powershell
python examples\projects\10_testbed_workflow\reporting\generate_testbed_web_report.py `
  examples\projects\10_testbed_workflow\outputs\boussinesq_natural_n1_10km2_testbed `
  --title "Boussinesq/MODFLOW6 natural N1 10km2 regional-lab testbed"

python examples\projects\10_testbed_workflow\reporting\generate_testbed_web_report.py `
  examples\projects\10_testbed_workflow\outputs\boussinesq_natural_n2_100km2_testbed `
  --title "Boussinesq/MODFLOW6 natural N2 100km2 regional-lab testbed"

python examples\projects\10_testbed_workflow\reporting\generate_testbed_web_report.py `
  examples\projects\10_testbed_workflow\outputs\boussinesq_natural_n3_mesh_sensitivity_testbed `
  --title "Boussinesq/MODFLOW6 natural N3 mesh sensitivity testbed"
```

Open:

```text
examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed/web_synthesis/index.html
examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n2_100km2_testbed/web_synthesis/index.html
examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n3_mesh_sensitivity_testbed/web_synthesis/index.html
```

## Notes

- No pre-existing mesh input is used by the generated simulations. Each child
  follows the normal simulation path and regenerates its catchment mesh through
  `mesh_catchment`.
- The Boussinesq child follows case 1 only: the comparison overlay keeps top
  Cauchy drainage conductance at `0.0 m2/s`, so PETSc TS/SNESVI enforces
  `h <= z_top` through the upper obstacle.
- N2 coordinates currently come from previous 100 km2 mesh-gallery screening
  by extracting candidate outlet coordinates from the low boundary node of the
  imported gallery bundle. This is site-selection provenance, not a mesh input.
- `geology_K_dummy_demo.csv` is still a demonstration hydraulic-conductivity
  table. It is heterogeneous and useful for workflow validation, but it is not
  a curated scientific K reference table.
- Heads and water-table depths are the primary comparable quantities. Native
  drain, seepage, surface-excess and budget terms are diagnostics unless the
  comparison workflow has explicitly aggregated them into comparable quantities.
