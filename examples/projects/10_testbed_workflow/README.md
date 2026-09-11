# 10 - Testbed workflow

Demonstrates the generic `[workflow] mode = "testbed"` engine: expand a matrix
of cases from a base config, delegate each case to a `simulation` or
`comparison` child runner, and collect metrics, manifests and an HTML report.
The main case is a MODFLOW-NWT transient flux diagnostic on 8 outlet sites of
the Armorican massif (EPSG:2154, 80x80 grid, one layer, monthly recharge over
2000-2002). Two smaller testbeds reuse base configs from `06_vire_selune` and
`09_comparison_workflow` to check the K-sensitivity and mesh-resolution axes
of the same engine. `boussinesq/` holds MODFLOW 6 versus Boussinesq comparison
campaigns, both synthetic and natural, run through the same `testbed` and
`comparison` machinery.

## Run

```bash
# plan the 8-site NWT flux testbed without executing it
hmp run examples/projects/10_testbed_workflow/nwt_small_catchment_flux_testbed.toml --dry-run

# generate the K-sensitivity child configs (execute = false, no solver run)
hmp run examples/projects/10_testbed_workflow/flow_k_sensitivity_testbed.toml

# generate the mesh-resolution child configs (execute = false, no solver run)
hmp run examples/projects/10_testbed_workflow/mesh_resolution_testbed.toml

# build the HTML synthesis from an already-run testbed output root
python examples/projects/10_testbed_workflow/reporting/generate_testbed_web_report.py \
  examples/projects/10_testbed_workflow/outputs/mesh_resolution_testbed
```

Config generation for the K-sensitivity and mesh-resolution testbeds: about
7 s each. `nwt_small_catchment_flux_testbed.toml` has `execute = true` and
runs 8 full MODFLOW-NWT transient simulations; that duration is unmeasured
here. The Boussinesq campaigns under `boussinesq/` need a PETSc-enabled
environment and are unmeasured as well.

## Data

| Source | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | Regional 75 m DEM, delineates each outlet site |
| `hydrography/regional_stream_network.shp` (`FID`) | hydrography | Regional stream network, rasterized for drainage |
| `conceptual_dem.tif` | dem | Reference grid for the synthetic Boussinesq geology zones |

The NWT flux base uses synthetic monthly recharge inline in
`base_armorican_nwt_flux_transient.toml`; it does not read a shared recharge
source.

## What it shows

`flow_k_sensitivity_testbed.toml` and `mesh_resolution_testbed.toml` set
`testbed.execute = false`: they only expand the case matrix and write child
TOML configs under `outputs/<testbed_id>/_generated_configs/`, they do not
run a solver. This is the fast path to check that a testbed's case/axis
definition is well-formed before spending solver time on it.

`nwt_small_catchment_flux_testbed.toml` is the opposite: `execute = true`,
`continue_on_error = true`, so a failing site does not stop the other seven.

`boussinesq/natural_geology_k/` and `boussinesq/synthetic_heterogeneous/`
each carry their own README with the full MF6-versus-Boussinesq campaign
detail, site catalogs and PETSc runtime requirements.
