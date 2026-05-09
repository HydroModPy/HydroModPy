# Boussinesq Validation And Testbed Proposal

Etat au 2026-05-08.

## Validation Documentation Check

The Boussinesq validation documentation is mostly up to date.

Checks performed from the repository root:

```powershell
python -m validation_cases.run_cases --solver boussinesq --regime both --list
```

Result: 21 analytical cases are discoverable for the `boussinesq` solver:
12 steady cases and 9 transient cases. The list covers the piecewise-K 1D
cases, sloping-substratum cases, circular island, hillslope interception,
Brutsaert recessions, linearized transient forcing cases, and late-time
pumping.

The generated ReadTheDocs validation page reports:

```text
Boussinesq: 21/21 cases passed on 2026-05-06T07:41:24.118686+00:00
report validation_cases/reports/latest/boussinesq_both.json
```

The source-hash audit of
`docs/readthedocs/source/_static/capability_gallery/validation/*_summary.json`
shows no stale Boussinesq case page. The only stale generated validation
artifacts found are outside the Boussinesq case set:

- `linearized_unconfined_drainage_1d_summary.json`
- `linearized_unconfined_hillslope_drainage_1d_summary.json`
- `modflow6_irregular_tri_xt3d_method_choice_summary.json`

So the Boussinesq validation examples can be treated as current. The separate
generated-gallery refresh should still be run later if the non-Boussinesq pages
matter for a documentation release.

One manual README wording was corrected in `tests/validation/README.md`: the
suite is no longer described as centered only on `modflownwt`, because the
analytical runner and generated report now expose broad `boussinesq`,
`modflow6`, and `modflow6_irregular_tri` coverage.

## Boundary Between Validation And Testbeds

Keep a hard separation:

- `validation_cases/`: analytical or tightly controlled scientific references
  with explicit tolerances.
- `tests/validation/`: pytest entrypoints for those references.
- `examples/projects/09_comparison_workflow/`: pairwise solver comparisons,
  especially MF6 reference versus Boussinesq candidate.
- `examples/projects/10_testbed_workflow/`: multi-case campaigns, sweeps,
  natural basin ladders, and operational diagnostics.

Natural multi-basin campaigns should not be placed in `validation_cases/`.
They are testbeds, not proof cases, because geology, topography, recharge and
surface drainage add data and modelling assumptions that do not have a single
analytical truth.

## Synthetic Testbed Proposal

Name:

```text
boussinesq_synthetic_heterogeneous
```

Goal: stress the new Boussinesq method beyond the analytical unit benchmarks
while keeping geometry and forcing deterministic.

Constraint: the testbed should still run through the normal simulation path.
It should not import prebuilt meshes and should not need a custom runner. Use a
standard `workflow = "simulation"` base config, then the existing
`workflow = "testbed"` or `workflow = "comparison"` layer only to materialize
ordinary child simulation TOMLs.

Recommended scope:

| Block | Purpose | Suggested variants |
| --- | --- | --- |
| `strip_piecewise_k` | Bridge from analytical validation to testbed workflow. | 1D thin strip, K contrast 1:10 and 1:100, fixed heads, recharge on/off. |
| `hillslope_drainage` | Controlled surface-interaction stress. | Sloping topography, drainage conductance low/medium/high, transient recharge pulse. |
| `patchy_2d_catchment` | 2D heterogeneous K without external data. | Synthetic triangular or cartesian support, 5 to 8 hydrofacies patches, MF6 reference and Boussinesq candidate. |
| `resolution_ladder` | Numerical robustness. | Same physics at coarse/medium/fine mesh; compare convergence, mass balance, active-surface area and runtime. |

For mesh creation, prefer a base simulation that declares the synthetic support
and a `mesh_catchment` section, rather than using `mesh_input`. The comparison
layer can then use `mesh_mode = "mesh_catchment"` for both MF6 and Boussinesq.

Minimum metrics:

- solver status and nonlinear iteration count,
- residual norms and runtime,
- mass-balance closure,
- head map RMSE against MF6 when a reference run exists,
- cell-wise max absolute head difference,
- surface-excess/drainage flux totals,
- number and area of active seepage/drainage cells.

This testbed should reuse existing analytical case constants where useful, but
should not duplicate the analytical validation cases verbatim. Its value is the
cross-product of heterogeneity, transient forcing, surface interaction and mesh
resolution.

## Natural Testbed Proposal

Name:

```text
boussinesq_natural_geology_k_ladder
```

Goal: evaluate Boussinesq on natural topography, river-constrained meshes,
geology-derived spatial support and heterogeneous hydraulic conductivity across
many basins and basin sizes.

Use the classic simulation path for every basin. Each case starts from outlet
coordinates, loads the natural data, delineates the basin, builds the
geographic support, creates the mesh, then runs the solver. Do not use
`mesh_input`, `bundle_dir`, or committed mesh-gallery bundles as simulation
inputs.

The base natural simulation should look like the existing Nancon seasonal
pattern:

```toml
workflow = "simulation"

[geographic]
source_mode = "standard"
catch_def = "from_outlet_coord"
dem_init_path = "../../data/dem/DEM_armorican_massif.tif"
snap_dist = "150 m"
buff_area = "10%"
crs_project = "EPSG:2154"
dem_correc_type = "breach"
reuse_existing_outputs = false

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.5
compute_strahler_order = true
compute_stream_links = true
all_vertices = true

[domain]
zone_ids = ["geology"]

[domain.supports.field_geology]
provider = "geology"

[data]
types = ["dem", "geology", "hydrography", "recharge"]
inference_mode = "warn"

[data.geology]
id = "field_geology"

[[data.geology.sources]]
source = "brgm_1m"

[[data.hydrography.sources]]
source = "bdtopage"
rasterize_field = "FID"

[mesh_catchment]
constraints_mode = "geology_rivers"
output_layout = "flat"
figures_enabled = true
```

For MF6/Boussinesq comparisons, keep the same base simulation and use the
existing comparison workflow with:

```toml
mesh_mode = "mesh_catchment"
```

for both simulations. This keeps the two child runs independent but makes both
go through the same public simulation pathway.

The site catalogue should contain outlet coordinates and expected scale class,
not mesh paths. A useful first target is about 20 to 30 outlets across the same
three size classes:

| Scale group | Target number of outlets | Approximate basin area before buffer | Role |
| --- | ---: | ---: | --- |
| `small_10km2` | 8-10 | 5-20 km2 | Fast smoke and sensitivity to local geology. |
| `medium_100km2` | 10-15 | 50-200 km2 | Main natural ladder. |
| `large_1000km2` | 5 | 500-1500 km2 | Scaling and robustness. |

The exact area should be measured after delineation and written to the
testbed outputs. Do not preselect cases by existing mesh size.

Hydraulic conductivity:

- Use `flow.param.K.field.kind = "heterogeneous"` with
  `field_spatial_id = "field_geology"`.
- Start with the existing CSV mechanism:

  ```toml
  [flow.param.K.field]
  id = "K"
  kind = "heterogeneous"
  unit = "m/s"

  [flow.param.K.field_heterogeneous]
  values_source = "csv"
  values_csv_file = "inputs/k_tables/geology_K_testbed.csv"
  csv_key_column = "zone_key"
  csv_value_column = "K_value"
  field_spatial_id = "field_geology"
  ```

- Do not use `examples/data/geology/geology_K_dummy_demo.csv` as the final
  scientific table. It is explicitly tagged `dummy_demo_not_for_scientific_use`.
  It is acceptable only for the first mechanical smoke test.
- For a publishable natural testbed, add a curated testbed-specific K table
  under `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/inputs/k_tables/`.
  The source can be documented from BRGM/InfoTerre geology and, where relevant,
  BDLISA hydrogeological classes. Keep the table versioned and cite the
  provenance in `README.md`.

Recommended tiers:

| Tier | Purpose | Basins | Solver scope | Expected cost |
| --- | --- | --- | --- | --- |
| N0 `nancon_anchor` | Existing Nancon seasonal-hydrography anchor that regenerates its mesh with `mesh_catchment`. | 1 | Keep in `09_comparison_workflow`. | Medium. |
| N1 `small_smoke` | Fast end-to-end path and geology-K output sanity. | 5 generated small basins. | Boussinesq plus MF6 on 1 or 2 basins. | Low. |
| N2 `medium_ladder` | Main natural campaign. | 10 to 15 generated medium basins. | Boussinesq all; MF6 reference on a stratified subset. | Medium/high. |
| N3 `large_stress` | Scaling and robustness. | 5 generated large basins. | Boussinesq first; MF6 only if runtime budget allows. | High. |
| N4 `mesh_resolution_variant` | Mesh sensitivity from the same natural outlet. | 1 to 3 outlets, each regenerated at coarse/medium/fine mesh settings. | MF6/Boussinesq pairwise. | Medium/high. |

Recommended natural metrics:

- status, wall time, nonlinear iterations, memory if available,
- number of cells and active cells,
- mass-balance closure and flux components,
- head range and watertable-depth distribution,
- drainage/surface-excess total flux and active area,
- overlap with observed/reference hydrography when exposed by the run,
- geology-class area fractions and K distribution summary,
- mesh-generation diagnostics: cell count, geology-interface count, river-trace
  curve count, coverage QA and mesh-size settings,
- MF6/Boussinesq head and flux differences for the paired subset.

## Directory Organization

Add one identifiable sub-tree under the existing testbed workflow directory:

```text
examples/projects/10_testbed_workflow/
  boussinesq/
    README.md
    synthetic_heterogeneous/
      README.md
      synthetic_geology_zones.geojson
      base_synthetic_patchy_mf6_bouss_transient.toml
      boussinesq_synthetic_patchy_testbed.toml
      compare_synthetic_patchy_mf6_bouss.toml
      inputs/
      outputs/
    natural_geology_k/
      README.md
      base_natural_geology_k_generated_mesh.toml
      boussinesq_natural_geology_k_ladder.toml
      compare_natural_geology_k_subset_mf6_bouss.toml
      site_tables/
        armorican_outlet_ladder.csv
      inputs/
        k_tables/
          geology_K_testbed.csv
      outputs/
```

Rationale:

- It stays inside `examples/projects/10_testbed_workflow/`, so it does not add a
  new top-level concept.
- The `boussinesq/` prefix makes the campaign easy to find and keeps it away
  from the existing NWT files.
- `synthetic_heterogeneous/` and `natural_geology_k/` separate deterministic
  stress tests from natural-data campaigns.
- Generated outputs stay under the existing
  `examples/projects/10_testbed_workflow/outputs/` tree, with a campaign prefix
  (`boussinesq_synthetic_heterogeneous`, `boussinesq_natural_geology_k`) so they
  are easy to clean and do not collide with the existing NWT outputs.
- Natural cases store outlet coordinates and mesh settings, not mesh paths.
  Meshes are products of each run.
- Pairwise MF6/Boussinesq comparison TOMLs can live beside the campaign when
  they are subsets of the same testbed. Once one comparison becomes a stable
  benchmark, promote a copy or wrapper into
  `examples/projects/09_comparison_workflow/`.

Recommended site table columns:

```text
case_id,scale_group,outlet_id,x_outlet,y_outlet,snap_dist,buff_area,
target_area_km2,mesh_global_size_m,mesh_min_size_m,mesh_max_size_m,
k_table_id,recharge_scenario_id,time_window_id,ic_scenario_id,run_tier,
enabled,tags
```

Recommended output roots:

```text
examples/projects/10_testbed_workflow/outputs/boussinesq_synthetic_heterogeneous/
examples/projects/10_testbed_workflow/outputs/boussinesq_natural_geology_k/
```

## Result Storage And Display Without New Code

The generic `workflow = "testbed"` already persists enough evidence for a
first campaign without adding code. It does not create a generic HTML report.
The readable entry point is the Markdown/CSV/JSON bundle under
`testbed.output_root`.

For the proposed natural testbed:

```text
examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/outputs/
  testbed_plan.json
  testbed_manifest.json
  testbed_cases.csv
  testbed_metrics.csv
  testbed_report.md
  _generated_configs/
    <variant_id>.toml
  <variant_id>_workspace/
    hydromodpy.duckdb
    hydromodpy_debug.log
    simulations/
      <simulation_basename>.zarr/
      <simulation_basename>.parquet/
    figures/
      <run_name>/
        *.png
    exports/
```

Roles:

- `testbed_plan.json`: planned variants and generated child TOML paths.
- `_generated_configs/<variant_id>.toml`: ordinary simulation TOML produced
  from the base config plus the variant overlay.
- `testbed_cases.csv`: one row per variant with status, duration, generated
  config path, error if any, simulation name and `sim_id` when execution
  succeeds.
- `testbed_metrics.csv`: scalar metrics selected by `[[testbed.metric]]`.
  For a simulation runner, available sources include catalog-derived
  `flow_metrics.*` values such as duration, cell count, time-step count,
  mass-balance error, field statistics and selected budget totals when the
  child run exposes them.
- `testbed_manifest.json`: complete machine-readable index of the campaign,
  including paths, case rows and metric rows.
- `testbed_report.md`: compact human-readable summary table.
- `<variant_id>_workspace/hydromodpy.duckdb`: normal HydroModPy catalog for
  that child simulation.
- `<variant_id>_workspace/simulations/`: normal Zarr and Parquet result
  stores for fields, time series, budgets and mass balance.
- `<variant_id>_workspace/figures/<run_name>/`: standard simulation figures
  if `[display]` is enabled and `testbed.runner.no_display = false`.

Therefore the no-new-code reading order is:

1. Open `testbed_report.md` for pass/fail and durations.
2. Open `testbed_cases.csv` for generated TOML paths, `sim_id` and errors.
3. Open `testbed_metrics.csv` for cross-basin comparison.
4. Inspect one child workspace under `figures/<run_name>/` for maps and
   hydrographic diagnostics.
5. Use `hydromodpy.duckdb`, Zarr and Parquet through the existing results API
   for deeper analysis.

### HTML summary strategy

There are two practical options for an HTML summary.

1. Use comparison mode for the HTML that already exists.

   A `workflow = "comparison"` run already writes a browsable report at:

   ```text
   <comparison_output_root>/web/index.html
   ```

   This is the preferred no-new-code path for Boussinesq versus MF6 subsets. The
   comparison config should keep the end-to-end simulation path: each compared
   simulation starts from a normal simulation config, rebuilds the mesh through
   `mesh_catchment`, runs the solver, then lets the existing comparison workflow
   collect metrics, figures, artifacts, and the HTML report.

   Recommended location for Boussinesq natural comparison outputs:

   ```text
   examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/outputs/
     comparisons/
       <case_id>_mf6_vs_bouss/
         comparison_manifest.json
         comparison_metrics.csv
         comparison_figures/
         web/
           index.html
   ```

   This gives one standard comparison HTML per basin or per selected basin
   variant. It is simple, identifiable, and does not require adding presentation
   code.

2. Add a testbed-level HTML index only if a multi-basin synthesis page is needed.

   The generic `workflow = "testbed"` currently persists JSON, CSV, markdown,
   generated configs, workspaces, and figures, but it does not produce a generic
   HTML dashboard. A synthetic overview like the previous NWT flux page is now
   handled by the generic post-processor:

   ```text
   examples/projects/10_testbed_workflow/reporting/
     generate_testbed_web_report.py
   ```

   This script should only read stable outputs already produced by the standard
   workflows:

   ```text
   outputs/testbed_manifest.json
   outputs/testbed_cases.csv
   outputs/testbed_metrics.csv
   outputs/testbed_report.md
   outputs/<variant_id>_workspace/figures/
   outputs/comparisons/<case_id>_mf6_vs_bouss/web/index.html
   ```

   It should not run simulations, generate meshes, or add new scientific logic.
   Its role is only to provide navigation: basin table, scale classes, geology/K
   metadata, links to figures, links to comparison HTML pages, and links to raw
   CSV/JSON artifacts.

The recommended implementation is therefore hybrid: run the large natural
campaign with `workflow = "testbed"` for reproducible multi-basin coverage, run a
stratified subset with `workflow = "comparison"` for Boussinesq/MF6 evidence, and
add a thin testbed HTML index only after the output contract is stable.

Concrete page articulation for the generic synthesis:

```text
outputs/web_synthesis/index.html
  -> global natural testbed entry point
  -> status table for all basins
  -> basin size classes
  -> geology/K metadata
  -> links to CSV, JSON, Markdown artifacts
  -> links to per-basin pages

outputs/web_synthesis/cases/<case_id>.html
  -> one basin page
  -> outlet, area, mesh-size settings
  -> dominant geology and K table reference
  -> main scalar metrics
  -> standard figures from <variant_id>_workspace/figures/
  -> link to the comparison HTML page when that basin is part of the
     Boussinesq/MF6 comparison subset

outputs/comparisons/<case_id>_mf6_vs_bouss/web/index.html
  -> existing standard comparison report
  -> MF6 versus Boussinesq metrics
  -> comparative figures
  -> comparison artifacts and generated configs
```

The default directory is `web_synthesis/` so it does not overwrite older
specialized reports that may already use `web/index.html`, such as the current
NWT flux report. Use `--web-dir web` only for a run that has no specialized
`web/` report.

The only new code for the synthetic multi-basin HTML is a presentation script:

```text
examples/projects/10_testbed_workflow/reporting/
  generate_testbed_web_report.py
```

This script should follow the same broad pattern as the existing NWT testbed
report generator in `examples/projects/10_testbed_workflow/`, but with a narrower
scope. It should:

- read `outputs/testbed_manifest.json`, `outputs/testbed_cases.csv`,
  `outputs/testbed_metrics.csv`, `outputs/testbed_report.md` and selected
  figure paths from child workspaces;
- discover optional comparison reports under
  `outputs/comparisons/<case_id>_mf6_vs_bouss/web/index.html`;
- write `outputs/web_synthesis/index.html` and
  `outputs/web_synthesis/cases/<case_id>.html`;
- avoid running simulations, creating meshes, modifying generated configs, or
  recomputing scientific metrics.

This keeps the added code outside the core workflow and solver layers. The testbed
and comparison runs remain responsible for all simulation, mesh generation and
metric production; the HTML script is only a static navigation and presentation
layer.

### Reusable HTML organization for other test campaigns

The same HTML organization should also work for other method comparisons and for
other hydrological or hydrogeological processes if the page hierarchy uses
generic concepts instead of solver-specific ones.

Recommended reusable hierarchy:

```text
outputs/
  web_synthesis/
    index.html
    cases/
      <case_id>.html
    methods/
      <method_id>.html
    processes/
      <process_id>.html
    assets/
      *.png
      *.css
  comparisons/
    <comparison_id>/
      web/
        index.html
```

Roles:

- `web_synthesis/index.html`: campaign entry point. It summarizes all cases,
  methods, processes, statuses, main metrics, and available detailed reports.
- `web_synthesis/cases/<case_id>.html`: one physical or synthetic case. It should remain
  independent of the method being tested: outlet, basin size, mesh settings,
  forcing, geology, reference data, run variants and links to comparison reports.
- `web_synthesis/methods/<method_id>.html`: optional method-centered page.
  Useful when the same method is exercised on many cases, for instance
  `boussinesq`, `modflow6`, `modflownwt`, or later another process
  implementation.
- `web_synthesis/processes/<process_id>.html`: optional process-centered page.
  Useful when the campaign covers several behaviours, for example drainage, recharge
  response, river exchange, seepage, storage variation, or seasonal transient
  response.
- `comparisons/<comparison_id>/web/index.html`: detailed comparison page produced
  by the existing comparison workflow. The campaign pages should link to it
  instead of duplicating its content.

The neutral identifiers should be carried by the case table and manifest, for
example:

```text
case_id,scale_group,process_id,method_group,comparison_group,enabled,tags
```

For the Boussinesq natural campaign, this can still be instantiated as:

```text
case_id = "armorican_small_001"
process_id = "seasonal_groundwater_response"
method_group = "boussinesq_mf6"
comparison_group = "mf6_vs_bouss"
```

For another campaign, the same columns could describe a different comparison:

```text
case_id = "synthetic_recharge_pulse_002"
process_id = "transient_recharge_pulse"
method_group = "mf6_nwt"
comparison_group = "mf6_vs_nwt"
```

The presentation code should not stay named after Boussinesq. The current
implementation is the generic helper:

```text
examples/projects/10_testbed_workflow/reporting/
  generate_testbed_web_report.py
```

or, once the contract is stable enough to become part of HydroModPy itself:

```text
hydromodpy/analysis/testbed/web/
```

It can later be moved into `hydromodpy/analysis/testbed/web/` if the CSV/JSON
manifest contract becomes stable enough to support public workflows.

### Genericity boundary

The reporting and output layout should be generic; the first scientific
campaign should remain concrete.

Generic now:

- page concepts: campaign, case, method, process, comparison;
- output names: `web_synthesis/index.html`,
  `web_synthesis/cases/<case_id>.html`,
  `web_synthesis/methods/<method_id>.html`,
  `web_synthesis/processes/<process_id>.html`, `comparisons/<comparison_id>/web/index.html`;
- manifest fields: `case_id`, `process_id`, `method_group`,
  `comparison_group`, `scale_group`, `tags`;
- HTML generator inputs: existing CSV, JSON, Markdown, figure and comparison
  report artifacts.

Keep concrete now:

- the first campaign directory can stay under
  `boussinesq/synthetic_heterogeneous/` and
  `boussinesq/natural_geology_k/`;
- campaign-specific captions, filters and interpretation can stay in the
  Boussinesq README or in optional metadata rather than in the generic renderer;
- Boussinesq-specific captions, metrics and interpretation rules should not be
  pushed into a shared package until the common contract is clear.

Promotion rule: keep the generator in
`examples/projects/10_testbed_workflow/reporting/` while the contract is still
example-level. Only move it into `hydromodpy/analysis/testbed/web/` once the
CSV/JSON manifest contract is stable enough to support public workflows.

### Current generic HTML implementation

The reusable post-processor is implemented here:

```text
examples/projects/10_testbed_workflow/reporting/generate_testbed_web_report.py
examples/projects/10_testbed_workflow/reporting/README.md
```

It detects the output contract automatically:

- `testbed_manifest.json` means a `workflow = "testbed"` run;
- `regional_lab_report.json` means a `workflow = "regional_lab"` run.

For a testbed run it reads `testbed_cases.csv`, `testbed_metrics.csv`, the
manifest, the generated child TOML files, and the figure directories declared in
`[display].output_dir`. For a regional lab run it reads the report JSON, site
inventory, case matrix and execution metrics.

The campaign page deliberately keeps metrics compact: it shows counts, statuses,
which scalar metric columns are populated, and a link to the full CSV rather
than rendering every metric column in the first view. The cases table also has a
dedicated `Simulation HTML` link when a per-simulation page already exists under
the run output, for example `<output_root>/web/site_01.html`.

Comparison integration is artifact-driven. The synthesis generator discovers
comparison runs stored under:

```text
<output_root>/comparisons/<comparison_id>/
  comparison_manifest.json
  comparison_metrics.csv
  comparison_figures/
  web/index.html
```

or accepts them explicitly with `--comparison-root <comparison_output_root>`.
The campaign page lists all discovered comparisons. A case page embeds the key
comparison figures when the comparison identifier or folder path contains the
case or site identifier, for example `site_01_mf6_vs_bouss`. The embedded figures
are the figures already produced by `hydromodpy.analysis.comparison`, such as
`map_comparison`, `map_triptych`, `difference_map`, `timeseries` and
`budget_diagnostics`; the synthesis page does not recompute overlays.

Default output:

```text
<output_root>/web_synthesis/index.html
<output_root>/web_synthesis/cases/<case_id>.html
```

Example command:

```powershell
python examples\projects\10_testbed_workflow\reporting\generate_testbed_web_report.py `
  <output_root> `
  --site-catalog <site_catalog.csv> `
  --site-generation-config <catchment_scan_config.toml> `
  --site-generation-summary <catchment_scan_summary.json>
```

The optional site-generation arguments are only provenance links. They do not
change the simulation, the mesh generation, or the metrics. When supplied, the
synthesis page also displays the main scan parameters from the TOML config and
available JSON/CSV counters from the generation summary. The rest of the page
content is derived from artifacts produced by the normal workflows.

### Current comparison scaffold implementation

The first runnable natural MF6/Boussinesq comparison scaffold is implemented
here:

```text
examples/projects/10_testbed_workflow/boussinesq/
  README.md
  natural_geology_k/
    README.md
    base_site_01_mf6_bouss_transient.toml
    compare_site_01_mf6_bouss.toml
```

This is now a refined one-site demonstrator, not the full natural testbed. It
uses `site_01` from the current Armorican site table, natural DEM and river
extraction, geology-constrained `mesh_catchment`, heterogeneous hydraulic
conductivity through the current `geology_K_dummy_demo.csv` table, and a
24-month synthetic recharge sequence. No pre-existing mesh is used.

The initial smoke run produced only 22 cells, which was too coarse for a
demonstrative map comparison. The current configuration therefore targets a
finer regenerated mesh:

```toml
[geographic.river_network]
threshold_area_km2 = 0.2

[mesh_catchment.zone_meshing]
global_size = 130.0
min_size = 45.0
max_size = 300.0
interface_size = 70.0
interface_distance = 220.0
```

Validation already performed:

```powershell
python -m hydromodpy run --dry-run `
  examples\projects\10_testbed_workflow\boussinesq\natural_geology_k\compare_site_01_mf6_bouss.toml
```

The dry-run resolves as `workflow = "comparison"`. The comparison configuration
also materializes child payloads with the expected solvers:

```text
mf6_ref         -> solvers = ["modflow6"]
bouss_candidate -> solvers = ["boussinesq"]
```

To execute the comparison:

```powershell
python -m hydromodpy run `
  examples\projects\10_testbed_workflow\boussinesq\natural_geology_k\compare_site_01_mf6_bouss.toml
```

Expected output:

```text
examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/
  comparisons/
    site_01_refined_mf6_vs_bouss/
      comparison_manifest.json
      comparison_metrics.csv
      comparison_figures/
      web/index.html
```

Then refresh the generic synthesis:

```powershell
python examples\projects\10_testbed_workflow\reporting\generate_testbed_web_report.py `
  examples\projects\10_testbed_workflow\outputs\nwt_small_catchment_flux `
  --site-catalog examples\projects\10_testbed_workflow\site_tables\armorican_demo_sites.csv `
  --comparison-root examples\projects\10_testbed_workflow\outputs\nwt_small_catchment_flux\comparisons\site_01_refined_mf6_vs_bouss `
  --title "Generic NWT flux testbed report"
```

Because the comparison id is `site_01_refined_mf6_vs_bouss`, the synthesis page will
associate it with `web_synthesis/cases/site_01.html` and embed the comparison
figures produced by the comparison workflow.

Run status on 2026-05-08:

- comparison run completed end to end for `mf6_ref` and `bouss_candidate`;
- `audit_status = warn`, with warnings limited to recharge-budget overlap and
  initial-state policy diagnostics;
- detailed comparison HTML:
  `examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/comparisons/site_01_mf6_vs_bouss/web/index.html`;
- generic synthesis HTML:
  `examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/web_synthesis/index.html`.

Implementation update on 2026-05-09: the executable configuration now uses the
refined comparison id `site_01_refined_mf6_vs_bouss`, a 24-month recharge
sequence, finer river/geology meshing and additional map/point observables.
The refined comparison has been run end to end from mesh creation for both
`mf6_ref` and `bouss_candidate`: 560 cells, 5 map observables, 5 point
timeseries observables, 5845 observable rows and 2920 difference rows. The
comparison wall time was 92.81 s on the local workstation, with child runtimes
of 39.62 s for MF6 and 42.72 s for Boussinesq. The 2026-05-08 paths above
remain the completed smoke output; the current TOML writes to:

```text
examples/projects/10_testbed_workflow/outputs/nwt_small_catchment_flux/comparisons/site_01_refined_mf6_vs_bouss/web/index.html
```

Implementation note: the natural scaffold exposes a boundary case where the
domain geology rasterization may produce zero geology fraction on a few active
Gmsh cells while the mesh bundle has already assigned per-cell geology and
hydraulic conductivity. MF6 now carries the bundle conductivity through
`GmshSupportMetadata.cell_hydraulic_conductivity_m_s` and completes invalid
unstructured `hk`/`hk_value` cells from that bundle metadata before writing the
NPF package. This keeps MF6 and Boussinesq aligned on the generated mesh without
introducing mesh inputs or a separate simulation path.

The same refined natural run also exposed missing centroid top/bottom elevations
for a few cells close to raster-support limits. The generic mesh-bundle export
now falls back from centroid sampling to the finite nodal mean for
`z_top_centroid` and `z_bottom_centroid` when the centroid sample is missing.
This is implemented in the normal bundle creation path and is also covered by a
unit test.

### Current synthetic scaffold implementation

The first synthetic Boussinesq scaffold is now implemented here:

```text
examples/projects/10_testbed_workflow/boussinesq/synthetic_heterogeneous/
  README.md
  synthetic_geology_zones.geojson
  base_synthetic_patchy_mf6_bouss_transient.toml
  boussinesq_synthetic_patchy_testbed.toml
  compare_synthetic_patchy_mf6_bouss.toml
```

It uses no pre-existing mesh. The executable case is now a 36-month synthetic
recharge-response demonstrator rather than a four-month smoke test. The forcing
contains one normal wet season, one dry year, and one strong recharge pulse.
The flow setup deliberately avoids a lateral prescribed-head boundary, so it is
closer to the natural cases targeted later. The only active boundary condition
besides recharge is a top Cauchy drainage term with a fixed conductance of
`0.2 m2/s`. The initial head is generated by the generic steady-state
initial-condition workflow: each solver first runs a permanent calculation with
the mean recharge, then uses the resulting head field as the transient initial
condition.

The transient recharge itself starts with the first monthly value of the
chronicle (`first_clim = "first"`). The mean recharge is reserved for the
auxiliary permanent initial condition, so the transient forcing stays aligned
between MF6 and Boussinesq.

For Boussinesq, this demonstrator must use the Linux PETSc implementation, not
the SciPy sparse fallback. The transient candidate is configured with
`runtime_backend = "petsc"` and
`surface_interaction_model = "ts_vi_obstacle"`, i.e. PETSc TS Backward Euler
with SNESVI on the bounded head obstacle formulation. Because PETSc TS is a
transient integrator, the auxiliary permanent initial-condition solve is kept
inside PETSc but uses the stationary SNESVI obstacle closure
`surface_interaction_model = "vi_obstacle"`.

When the explicit positive Cauchy drainage conductance is active, the PETSc
upper VI bound is relaxed. The lower dry-bound constraint remains active, while
the top exchange is handled by the drainage flux term
`C * max(h - z_top, 0)`. This avoids comparing a hard Boussinesq top obstacle
with the softer MODFLOW 6 drain package.

The execution path is:

```text
[geographic.source_mode = "synthetic"]
  -> synthetic DEM support
[data.geology]
  -> local synthetic polygons
[mesh_catchment]
  -> regenerated geology-conformal mesh
workflow = "testbed" or "comparison"
  -> ordinary child simulation TOMLs
  -> same-solver steady-state initial condition from mean recharge
```

The synthetic geographic runtime does not produce a river trace. The synthetic
case therefore uses `mesh_catchment.constraints_mode = "geology_only"`. The
static `examples/data/dem/conceptual_dem.tif` raster is only used as the
reference grid for rasterizing `synthetic_geology_zones.geojson`; the simulation
topography itself is generated by `[geographic.synthetic]`.

Validation already performed:

```powershell
python -m hydromodpy run --dry-run `
  examples\projects\10_testbed_workflow\boussinesq\synthetic_heterogeneous\compare_synthetic_patchy_mf6_bouss.toml
```

The comparison child materialization resolves to:

```text
mf6_ref          -> solvers = ["modflow6"], mesh_catchment = geology_only
bouss_candidate -> solvers = ["boussinesq"], mesh_catchment = geology_only
```

The synthetic geology file was also checked against the reference raster: the
three zones cover all 4489 cells of `conceptual_dem.tif`.

Run the Boussinesq-only synthetic testbed:

```powershell
wsl bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m hydromodpy run examples/projects/10_testbed_workflow/boussinesq/synthetic_heterogeneous/boussinesq_synthetic_patchy_testbed.toml"
```

Run the MF6/Boussinesq synthetic comparison:

```powershell
wsl bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m hydromodpy run examples/projects/10_testbed_workflow/boussinesq/synthetic_heterogeneous/compare_synthetic_patchy_mf6_bouss.toml"
```

Expected HTML after the comparison run:

```text
examples/projects/10_testbed_workflow/outputs/boussinesq_synthetic_heterogeneous/
  comparisons/
    synthetic_patchy_long_mf6_vs_bouss/
      web/index.html
```

After running both the synthetic testbed and the synthetic comparison, build the
generic campaign synthesis with an explicit comparison link:

```powershell
python examples\projects\10_testbed_workflow\reporting\generate_testbed_web_report.py `
  examples\projects\10_testbed_workflow\outputs\boussinesq_synthetic_heterogeneous\testbed_long_recharge `
  --comparison-root examples\projects\10_testbed_workflow\outputs\boussinesq_synthetic_heterogeneous\comparisons\synthetic_patchy_long_mf6_vs_bouss `
  --title "Boussinesq synthetic patchy long-recharge testbed"
```

The synthesis page is written to:

```text
examples/projects/10_testbed_workflow/outputs/boussinesq_synthetic_heterogeneous/testbed_long_recharge/web_synthesis/index.html
```

Run status on 2026-05-09:

- Boussinesq-only synthetic testbed completed in WSL/PETSc for coarse,
  reference and fine regenerated meshes, with 374, 662 and 970 cells;
- MF6/Boussinesq long-recharge comparison completed end to end from mesh
  creation in WSL with the Boussinesq PETSc TS/SNESVI method;
- the Boussinesq candidate used `runtime_engine_id = "petsc_ts_vi_obstacle"`,
  `surface_interaction_model = "ts_vi_obstacle"`, PETSc TS `beuler` and SNESVI
  `vinewtonrsls`; all 36 periods converged, with 144 PETSc TS steps and 687
  SNES iterations;
- the current run uses `first_clim = "first"` for the transient recharge and a
  mean-recharge same-solver steady initial condition; PETSc reports no active
  top-obstacle cells for the synthetic Cauchy-drainage case, because drainage is
  carried by the explicit `budget/drain` flux;
- the comparison currently reports `audit_status = warn` because the 36 monthly
  recharge values start on 2020-09-01 and the last value is dated 2023-08-01
  while the simulation window ends on 2023-08-31, and because MF6 and Boussinesq
  do not expose the initial-state slice in exactly the same way. These are audit
  warnings, not solver failures.

The current outputs are:

```text
examples/projects/10_testbed_workflow/outputs/boussinesq_synthetic_heterogeneous/testbed_long_recharge/web_synthesis/index.html
examples/projects/10_testbed_workflow/outputs/boussinesq_synthetic_heterogeneous/comparisons/synthetic_patchy_long_mf6_vs_bouss/web/index.html
```

## Synthetic Case Generation And Code Location

Synthetic Boussinesq cases should be generated by configuration and by the
existing workflows, not by a new case-factory Python layer.

Proposed campaign location:

```text
examples/projects/10_testbed_workflow/boussinesq/synthetic_heterogeneous/
  README.md
  synthetic_geology_zones.geojson
  base_synthetic_patchy_mf6_bouss_transient.toml
  boussinesq_synthetic_patchy_testbed.toml
  compare_synthetic_patchy_mf6_bouss.toml
```

Responsibilities:

- `base_synthetic_patchy_mf6_bouss_transient.toml`: ordinary
  `workflow = "simulation"` file. It declares the synthetic geographic support,
  controlled recharge, heterogeneous K/Sy mapping, solver settings, display
  settings, and `mesh_catchment` settings.
- `boussinesq_synthetic_patchy_testbed.toml`: ordinary `workflow = "testbed"`
  file. It declares Boussinesq mesh-resolution variants through
  `[[testbed.variant]]` overlays. It is configured with `execute = true`, so the
  command runs the simulations end to end.
- `compare_synthetic_patchy_mf6_bouss.toml`: `workflow = "comparison"` file for
  the MF6 reference versus Boussinesq candidate.
- `synthetic_geology_zones.geojson`: small deterministic synthetic input file.
  It is not a generated mesh and can stay versioned.

Runtime generation sequence:

```text
hmp run boussinesq_synthetic_patchy_testbed.toml
  -> writes outputs/_generated_configs/<variant_id>.toml
  -> each generated child is workflow = "simulation"
  -> each child uses geographic.source_mode = "synthetic"
  -> existing synthetic geographic code builds the synthetic support
  -> existing mesh_catchment code builds the mesh
  -> existing solver workflow runs Boussinesq or MF6
  -> testbed writes testbed_cases.csv, testbed_metrics.csv, testbed_manifest.json
```

Existing code used for generation:

```text
hydromodpy/spatial/geographic/synthetic/
  -> builds analytical synthetic geographic support

hydromodpy/data/variables/recharge/
  -> supports synthetic recharge sources

hydromodpy/spatial/mesh/
  -> runs mesh_catchment

hydromodpy/analysis/testbed/
  -> expands variants and writes generated child TOMLs

hydromodpy/analysis/comparison/
  -> runs method comparisons and writes comparison HTML
```

No new code is required for synthetic case generation if the existing synthetic
geographic and recharge capabilities are sufficient. The only expected new code
is optional reporting code, now placed in the generic reporting directory:

```text
examples/projects/10_testbed_workflow/reporting/
  generate_testbed_web_report.py
```

The reporting script should consume generated outputs only. It should not create
synthetic domains, write meshes, launch solvers, or define scientific scenarios.

## Where Sites, Recharge, Time And Initial Conditions Are Fixed

These choices should be fixed in configuration artifacts, not in Python code.

### Current reference in the existing NWT testbed

The current `examples/projects/10_testbed_workflow/` reference is the NWT flux
testbed. It is useful as a pattern, but it is not yet a dynamic catalogue-driven
campaign.

Current recharge:

```text
examples/projects/10_testbed_workflow/base_armorican_nwt_flux_transient.toml
```

The recharge is a synthetic monthly chronicle declared directly in
`[data.recharge]`:

```toml
[data.recharge]
date_start = "2000-01-01"
date_end = "2002-12-31"

[[data.recharge.sources]]
source = "synthetic"
freq = "MS"
start_date = "2000-01-01"
periods = 36
values = [
  0.05, 0.05, 0.08, 0.15, 0.25, 0.35,
  0.65, 1.20, 2.20, 3.20, 4.00, 3.40,
  2.40, 1.40, 0.70, 0.30, 0.12, 0.05,
  0.02, 0.02, 0.02, 0.05, 0.10, 0.25,
  0.70, 1.80, 4.00, 5.00, 4.20, 2.00,
  0.80, 0.25, 0.08, 0.05, 0.05, 0.05,
]
runoff_ratio = 0.0
```

Current sites:

```text
examples/projects/10_testbed_workflow/site_tables/armorican_demo_sites.csv
examples/projects/10_testbed_workflow/nwt_small_catchment_flux_testbed.toml
```

The CSV contains the visible catalogue for the report. The executable testbed
TOML repeats the same eight outlets as `[[testbed.variant]]` blocks and overlays
`geographic.x_outlet` and `geographic.y_outlet` for each site.

The current NWT TOML does not dynamically call the site-generation pipeline, but
the repository does contain a site-selection and catalog bootstrap path that is
closer to the intended scientific workflow.

### Existing site-list generation path

The outlet generation code lives under:

```text
hydromodpy_annex/preprocess/catchment_identification_scan/
```

It is launched with:

```text
python -m hydromodpy_annex.preprocess.catchment_identification_scan.run_catchment_identification_case \
  --config hydromodpy_annex/preprocess/catchment_identification_scan/config_headwater_100km2.toml
```

Relevant configs already present:

```text
config_headwater_100km2.toml
config_s3_100km2.toml
config_s3_10km2.toml
config_1000km2.toml
```

This pipeline starts from a projected DEM, optionally clips a region, applies a
hydrological correction, computes D8 flow direction and accumulation, selects
candidate outlets, delineates watersheds, filters them, and writes a GeoPackage
plus an outlet CSV.

Key site-selection parameters:

```text
dem_path
region_polygon_path
accumulation_area_km2
outlet_selection_mode = "border" | "scan_global"
scan_tile_size_km
scan_max_outlets_per_tile
scan_min_outlet_spacing_km
scan_max_total_outlets
basin_selection_mode = "all_min_area" | "headwater_target"
headwater_max_strahler_order
headwater_min_target_ratio
target_basin_area_km2
target_area_tolerance_ratio
max_basin_overlap_ratio
dem_correction
snap_dist
```

Important outputs:

```text
<output_dir>/<gpkg_name>
<output_dir>/<outlets_csv_name>
<output_dir>/figures/
optional summary JSON from --output-json
```

The next step is the regional-lab bootstrap helper:

```text
hydromodpy/analysis/batch/bootstrap.py::build_site_catalog_from_outlet_table
```

It converts one outlet table into a canonical site catalog, optionally merging
mesh-run manifests or scanning a mesh-run root. It can enrich rows with
`mesh_ready`, Boussinesq steady/transient readiness tags, mesh bundle paths,
mesh summary paths, cluster ids, scale tags and source-selection ids.

This means the intended reusable chain is:

```text
catchment_identification_scan config
  -> exutoires_*.csv and watersheds_*.gpkg
  -> build_site_catalog_from_outlet_table(...)
  -> regional-lab/testbed site catalog
  -> campaign execution
  -> HTML synthesis
```

The Boussinesq natural testbed should reuse this provenance chain instead of
making a hand-written site list the only source of truth. The local campaign
table can still be a selected snapshot, but it should carry the source selection
id and point back to the scan config and outlet CSV used to create it.

### Generic HTML provenance requirements

The HTML synthesis should make this provenance visible because it is useful for
Boussinesq, MF6/NWT comparisons, and any future process testbed.

Campaign-level HTML (`outputs/web_synthesis/index.html`) should show:

- source site catalogue path;
- site-generation method: manual, external catalogue, `catchment_identification_scan`,
  or other;
- source selection id, for example `scan_headwater_100km2`;
- DEM path, optional region polygon, DEM correction mode and CRS;
- outlet-selection parameters and basin-selection parameters;
- generated outlet CSV and GeoPackage paths;
- number of candidate outlets, retained outlets and retained basins;
- site counts by region, scale, cluster, status, maturity and tags;
- recharge scenario, time-window scenario and initial-condition scenario used by
  the campaign;
- links to `testbed_cases.csv`, `testbed_metrics.csv`, `testbed_manifest.json`,
  generated child TOMLs, and comparison reports.

Site-level HTML (`outputs/web_synthesis/cases/<case_id>.html`) should show:

- site id, external/source outlet id and source selection id;
- outlet coordinates, basin area and scale class;
- generation method and link to the outlet CSV/GPKG row source;
- mesh generation status for this run, including generated mesh artifacts;
- geology/K-table references;
- recharge source actually used by the generated child TOML;
- simulation time window and `[flow.ic]` scenario;
- all comparison pages involving this site.

Method/process pages (`outputs/web_synthesis/methods/*.html`,
`outputs/web_synthesis/processes/*.html`) should summarize the same provenance fields in
aggregated form rather than redefining them. They should link back to the
campaign and site pages so that provenance remains single-source.

### Sites

If the natural site catalogue is canonical elsewhere, do not make this testbed
directory the master catalogue. Keep only a reviewed selection or snapshot here,
or a pointer to the external catalogue version that was used:

```text
examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/
  site_tables/
    armorican_outlet_ladder.csv
```

This local table is a campaign selection table. It should contain enough fields
to make the run auditable: external site id, source catalogue id or version,
outlet coordinates used for the run, scale class, mesh-size settings, K-table id,
recharge scenario id, time-window id, initial-condition scenario id, tier,
enabled flag and tags.

Current `workflow = "testbed"` variants are declared directly in TOML. Therefore
the executable values used by `hmp run` must appear in:

```text
examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/
  boussinesq_natural_geology_k_ladder.toml
```

with one block per executed site:

```toml
[[testbed.variant]]
id = "armorican_small_001"
label = "Armorican small 001"
axis = "site"

[testbed.variant.overlay.workspace]
project_root = "outputs/natural_geology_k/armorican_small_001_workspace"

[testbed.variant.overlay.simulation]
name = "bouss_nat_armorican_small_001"
run_id = "bouss_nat_armorican_small_001"

[testbed.variant.overlay.geographic]
x_outlet = 131189.100
y_outlet = 6833784.400
snap_dist = "150 m"
buff_area = "10%"
```

The external catalogue is the site authority; the local CSV is the campaign
selection and reporting input; the TOML variant is the current execution
contract. If duplication becomes too error-prone, add a small preparation helper
later to expand the selected sites into TOML variants, but that would be an
optional convenience tool, not part of the simulation path.

Synthetic sites do not need outlet coordinates. Their geometry should be fixed
through `[geographic.synthetic]` in the base simulation TOML and varied by
`[[testbed.variant]]` overlays:

```toml
[testbed.variant.overlay.geographic.synthetic.grid]
length_x = "5000 m"
length_y = "1000 m"
nx = 100
ny = 20

[testbed.variant.overlay.geographic.synthetic.topography]
kind = "linear"
base_elevation = 100.0
right_to_left_amplitude = 20.0
```

### Recharge chronicles

The executable recharge is fixed in the simulation TOML contract, not in Python
code. The place to verify the recharge actually used by a run is always the base
simulation TOML and the generated child config under
`outputs/_generated_configs/<variant_id>.toml`.

When all sites share the same forcing scenario, recharge should be fixed in the
base simulation config:

```text
base_synthetic_patchy_mf6_bouss_transient.toml
base_natural_geology_k_generated_mesh.toml
```

using the existing `[data.recharge]` contract:

```toml
[data.recharge]
date_start = "2000-01-01"
date_end = "2002-12-31"

[[data.recharge.sources]]
source = "synthetic"
freq = "MS"
start_date = "2000-01-01"
periods = 36
values = [
  0.05, 0.05, 0.08, 0.15, 0.25, 0.35,
  0.65, 1.20, 2.20, 3.20, 4.00, 3.40,
]
runoff_ratio = 0.0
```

If the recharge chronicle is large or is meant to be reused, store the file under
the testbed inputs and reference it from `[data.recharge]` as a normal custom
source:

```text
examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/
  inputs/
    recharge/
      recharge_monthly_reference_2000_2002.csv
      recharge_pulse_2020_01.csv
```

```toml
[data.recharge]
date_start = "2000-01-01"
date_end = "2002-12-31"

[[data.recharge.sources]]
source = "custom"
path = "inputs/recharge/recharge_monthly_reference_2000_2002.csv"
```

If recharge is a test axis, keep named scenario ids in the site or variant
catalogue (`recharge_scenario_id`) and store the reviewed list of scenarios under:

```text
examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/
  inputs/
    recharge_scenarios/
      recharge_scenarios.csv
```

The scenario catalogue is for review and reporting. With the current
`workflow = "testbed"` contract, the executable recharge still has to be present
in each child TOML, either inherited from the base config or applied through a
`[[testbed.variant]]` overlay. The overlay should replace the full
`[data.recharge]` payload for clarity.

Example overlay for a site-specific recharge scenario:

```toml
[testbed.variant.overlay.data.recharge]
date_start = "2000-01-01"
date_end = "2002-12-31"

[[testbed.variant.overlay.data.recharge.sources]]
source = "custom"
path = "inputs/recharge/recharge_monthly_reference_2000_2002.csv"
```

### Time window

The solver time grid belongs in `[simulation.time]` of the base simulation TOML:

```toml
[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = "1 month"
coverage_policy = "warn"
```

The recharge date window must cover the simulation time window. For comparison
runs, all methods in the comparison should inherit the same `[simulation.time]`
unless the tested question is explicitly about temporal discretization.

If time discretization is part of the testbed, use a `time_window_id` in the
catalogue and make the variant overlay change `[simulation.time]` and
`[data.recharge]` together.

### Initial conditions

Initial conditions belong in `[flow.ic]`, not in ad hoc test code:

```toml
[flow.ic]
type = "top"
```

Supported flow choices are `top`, `top_offset`, `bottom`, `custom`, and
`steady_state`. Examples:

```toml
[flow.ic]
type = "top_offset"
value = "10 m"
```

```toml
[flow.ic]
type = "custom"
value = "220 m"
```

For the first natural Boussinesq testbed, use one documented default
`ic_scenario_id`, for example `top_start` for smoke and robustness runs. If the
campaign later needs warm-start or spin-up style initial conditions, define that
as a separate scenario and only promote it if it can be expressed through the
existing workflow contract or a clearly scoped workflow extension.

For Boussinesq/MF6 comparisons, the same initial-condition scenario must be
applied to both methods unless the comparison is explicitly testing sensitivity
to initialization.

#### Audit of the current implementation

The current implementation expresses the synthetic long-recharge demonstrator
with the generic steady-state initial-condition contract:

- parsing is centralized in
  `hydromodpy/physics/flow/initial_conditions_config.py`;
- the accepted flat TOML keys are `type`, `value`, `unit|units`,
  `description`, `source`, `recharge_statistic` and
  `boundary_condition_policy`;
- accepted `flow.ic.type` values are `top`, `top_offset`, `bottom`, `custom`
  and `steady_state`;
- MF6 starting heads are built in
  `hydromodpy/solver/modflow6/builders/initial_conditions.py::build_start_heads`;
- Boussinesq starting heads are built in
  `hydromodpy/solver/boussinesq/forcing/initial_conditions.py::InitialConditionResolutionMixin.resolve_initial_head_field`;
- MODFLOW-NWT uses the same conceptual choices in
  `hydromodpy/solver/modflow_nwt/nwt/_chd_payloads.py`.

The geometric modes are useful for smoke tests, but they remain shortcuts. In
particular, a fixed `top_offset` can start the synthetic aquifer too dry or too
wet relative to the forcing and boundary conditions. It then mixes the method
comparison with an arbitrary initialization transient.

The synthetic comparison therefore uses a shared steady-state initial
condition:

```text
mean recharge over the transient chronicle
  -> steady solve on the generated mesh
  -> resulting head field used as transient initial state
  -> initial-state period excluded from transient error metrics
```

The public configuration is generic rather than Boussinesq-only:

```toml
[flow.ic]
type = "steady_state"
source = "mean_recharge"
recharge_statistic = "time_mean"
boundary_condition_policy = "first_period"
description = "Steady state under the mean recharge of the transient forcing."
```

This is supported as a generic `[flow.ic]` strategy. The implemented contract
keeps the auxiliary permanent solve same-solver: MF6 initializes MF6,
MODFLOW-NWT initializes MODFLOW-NWT, and Boussinesq initializes Boussinesq.
For the Boussinesq PETSc TS VI method, "same solver" means the same PETSc
family: the transient `ts_vi_obstacle` method is initialized with the stationary
PETSc SNESVI `vi_obstacle` method, because PETSc TS is not the permanent
problem solver.
For the current synthetic comparison:

1. `type = "steady_state"` is declared in the base simulation TOML and inherited
   by the comparison children;
2. the recharge statistic is resolved from the already parsed `[data.recharge]`
   chronicle;
3. the steady initialization solve runs through the same generated mesh
   and solver adapters;
4. the resulting head field is persisted as a normal simulation artifact;
5. that field is fed to every transient child simulation in the comparison;
6. the initialization slice is tagged as `is_initial_state` so comparison metrics do
   not interpret it as a transient response.

#### Time discretization audit

The synthetic comparison also exposed a Boussinesq time-axis issue: some
persisted Boussinesq state arrays carried zero period lengths even though the
root Zarr `time` array contained the correct monthly elapsed times. The
transient driver now resolves stress-period lengths from the launcher time grid
and falls back to explicit time boundaries when the raw period-length vector is
degenerate. The comparison readers also ignore degenerate Boussinesq state time
axes and fall back to the root `time` axis when available.

This fix is covered by focused unit tests under:

```text
tests/unit/solver/test_boussinesq_transient_driver.py
tests/unit/analysis/comparison/test_runtime_series_time_axis.py
```

After this correction, the comparison can align monthly MF6 and Boussinesq
slices in elapsed time. It does not, by itself, solve the scientific question of
the initial condition.

#### What is comparable in natural cases

For the natural MF6/Boussinesq comparison, charges and water-table depths are
the primary comparable variables. They represent the same state variable on the
same regenerated mesh.

Fluxes need a stricter rule. Native solver flux components are not necessarily
the same physical or numerical object:

- an MF6 drain flux is a boundary/process package contribution;
- a Boussinesq surface-excess or seepage term is a variational/surface
  activation response;
- storage and mass-balance budget terms are solver diagnostics.

Therefore natural testbed pages should not present every native budget term as
a method-to-method comparison. The comparable flux quantity should be an
explicitly aggregated observable such as:

```text
comparable_outflow_total_m3_s =
  drainage_total_m3_s + surface_excess_total_m3_s
```

or, when one method does not expose the boundary flux as a native component, a
balance-implied observable:

```text
balance_implied_outflow_total_m3_s =
  recharge_total_m3_s
  + well_total_m3_s
  + dry_deficit_total_m3_s
  - drainage_total_m3_s
  - surface_excess_total_m3_s
  - storage_change_total_m3_s
```

The second form is not an independent solver output; it is the missing external
outflow required by the basin water balance. It is acceptable for comparison
only if the HTML labels it as balance-implied. All other native flux and budget
plots should be labelled as diagnostics. This rule is generic enough to reuse
for other method pairs or process families: first define the shared observable,
then keep native process terms as audit evidence rather than direct comparison
metrics.

#### Synthetic flux and storage inventory

For the current synthetic MF6/Boussinesq comparison, the relevant budget
inventory is:

| Method | Native input terms | Native output terms | Storage term | Comparable external outflow |
| --- | --- | --- | --- | --- |
| MODFLOW 6 | `RCHA` -> `recharge_total_m3_s` | `DRN` -> `drainage_total_m3_s`; `CHD` only when a prescribed-head boundary is active | `STO-SS`/`STO-SY` -> `storage_change_total_m3_s` | `drainage_total_m3_s + surface_excess_total_m3_s` for the current top-drainage synthetic case |
| Boussinesq | `budget/recharge` -> `recharge_total_m3_s`; signed `budget/well` if active | `budget/drain` -> `drainage_total_m3_s`; `budget/surface_excess` -> `surface_excess_total_m3_s` | reconstructed from `head`, `z_bottom`, `z_top`, cell area and `storage_coefficient` | `drainage_total_m3_s + surface_excess_total_m3_s`; balance-implied outflow remains a diagnostic when a method lacks a native outflow term |

The previous comparison read Boussinesq recharge and storage from persisted
state-history arrays that were zero in this backend. The comparison export now
uses the canonical Zarr `budget` fields for Boussinesq fluxes and reconstructs
storage from the head state when the persisted saturated-thickness history is
degenerate.

#### Physical interpretation of comparison metrics

The comparison metrics should not be read as abstract scores. Each metric needs
the physical scale of the synthetic case:

- head-map and head-chronicle MAE/RMSE are water-level errors in metres;
- for a synthetic recharge-response case, report them against the transient
  response amplitude, for example `head_rmse / (max(head_ref) - min(head_ref))`;
- for map observables, also report the affected area fraction, for example the
  fraction of cells where `abs(delta_head) > 0.25 m` or another reviewed
  tolerance;
- for storage, show the global `storage_change_total_m3_s` rate first; the
  cumulative storage volume can remain a derived CSV calculation rather than a
  default figure;
- for external water balance, compare total inputs and total outputs separately
  before interpreting any individual native process term;
- for flux or storage errors, prefer volume-based metrics normalized by total
  recharge volume over instantaneous pointwise RMSE alone.

For the current synthetic HTML, this means:

```text
case_configuration.png
  -> large context figure: mesh, boundaries, points and recharge forcing

one representative head_map_* triptych
  -> direct hydraulic-head field comparison in metres

storage_comparison_dashboard.png
  -> global storage-rate comparison, with zero line

total_inputs_outputs_dashboard.png
  -> external input/output balance, storage excluded, with zero line

The head and budget figures should keep fixed method-family colors across all
plots. In the current implementation, MODFLOW 6 aliases (`modflow6`, `mf6_ref`)
are blue and Boussinesq aliases (`boussinesq`, `bouss_candidate`) are orange.

The HTML section `Methodes numeriques` should not mix model setup and numerical
solver settings. It is split into:

- `Configuration hydraulique commune`: flow regime, recharge policy, initial
  conditions, boundary conditions and hydraulic properties;
- `Parametrage numerique`: MODFLOW 6 DISV/IMS settings, Boussinesq PETSc
  TS/SNESVI settings, tolerances, substeps and spatial discretization.

comparison_metrics.csv
  -> numerical error table; physically meaningful once normalized by the
     synthetic head-response amplitude, aquifer thickness, area or recharge
     volume
```

The next useful improvement is to add derived normalized columns to the
comparison metrics, rather than multiplying the number of raw metrics:

```text
head_rmse_over_response_amplitude
head_mae_over_saturated_thickness
area_fraction_above_head_tolerance
storage_volume_error_over_recharge_volume
output_volume_error_over_recharge_volume
```

Do not write generated configs or solver outputs into `validation_cases/`,
`tests/`, or `docs/readthedocs/source/_static/`. Documentation gallery assets
should only be refreshed after a testbed result is stable enough to present.

Do not use existing mesh bundles as inputs. It is acceptable to compare the
newly generated mesh summaries against previous mesh-gallery orders of
magnitude during analysis, but the run itself must generate its mesh.

### Implemented synthetic comparison campaign

Implemented on 2026-05-09 under:

```text
examples/projects/10_testbed_workflow/boussinesq/synthetic_heterogeneous/
```

The implemented synthetic campaign keeps the same deterministic geometry,
geology polygons and observation anchors, then varies one modelling axis at a
time:

| Case | Axis | Base config | Comparison id |
| --- | --- | --- | --- |
| Homogeneous control | hydraulic properties | `base_synthetic_homogeneous_control.toml` | `synthetic_homogeneous_control_mf6_vs_bouss` |
| Patchy K moderate contrast | hydraulic properties | `base_synthetic_patchy_mf6_bouss_transient.toml` | `synthetic_patchy_long_mf6_vs_bouss` |
| Patchy K strong contrast | hydraulic properties | `base_synthetic_patchy_strong_k.toml` | `synthetic_patchy_strong_k_mf6_vs_bouss` |
| Low drainage conductance | top drainage | `base_synthetic_drainage_low.toml` | `synthetic_drainage_low_mf6_vs_bouss` |
| High drainage conductance | top drainage | `base_synthetic_drainage_high.toml` | `synthetic_drainage_high_mf6_vs_bouss` |
| 48-month recharge pulse | recharge chronicle | `base_synthetic_recharge_pulse_48m.toml` | `synthetic_recharge_pulse_48m_mf6_vs_bouss` |
| Small domain | domain size | `base_synthetic_small_domain.toml` | `synthetic_small_domain_mf6_vs_bouss` |
| Large domain | domain size | `base_synthetic_large_domain.toml` | `synthetic_large_domain_mf6_vs_bouss` |
| Low topographic gradient | topography | `base_synthetic_low_slope.toml` | `synthetic_low_slope_mf6_vs_bouss` |
| High topographic gradient | topography | `base_synthetic_high_slope.toml` | `synthetic_high_slope_mf6_vs_bouss` |

Each comparison TOML inherits the central comparison setup, materializes two
ordinary simulation TOMLs and runs both methods through the standard CLI path:

```text
geographic.synthetic
  -> data.geology and data.recharge
  -> mesh_catchment regenerated for the child run
  -> MODFLOW 6 or Boussinesq simulation
  -> comparison extraction, metrics and HTML
```

No existing mesh is used. The Boussinesq candidate uses the PETSc TS/SNESVI
path in WSL:

```toml
[comparison.simulation.overlay.flow]
runtime_backend = "petsc"
surface_interaction_model = "ts_vi_obstacle"
ts_vi_steps_per_period = 4
ts_vi_adapt = false
ts_vi_type = "beuler"
ts_vi_snes_type = "vinewtonrsls"
```

The domain-size variants use separate scaled geology polygons and scaled point
observables. This avoids clipping the central geology support or comparing
points that no longer represent the same relative hydraulic context. The
topographic amplitude is also scaled with domain length in these two cases so
the regional slope remains comparable to the central case.

Run all implemented synthetic comparisons:

```powershell
wsl bash /mnt/c/codes/HydroModPy/examples/projects/10_testbed_workflow/boussinesq/synthetic_heterogeneous/run_synthetic_comparison_campaign.sh
```

Build the synthesis HTML after the comparison runs:

```powershell
python examples\projects\10_testbed_workflow\boussinesq\synthetic_heterogeneous\build_synthetic_comparison_synthesis.py
```

Campaign synthesis page:

```text
examples/projects/10_testbed_workflow/outputs/boussinesq_synthetic_heterogeneous/synthetic_comparison_campaign/web_synthesis/index.html
```

Per-case comparison pages:

```text
examples/projects/10_testbed_workflow/outputs/boussinesq_synthetic_heterogeneous/comparisons/<comparison_id>/web/index.html
```

The synthesis page is generic: it reads the comparison manifests and exposes
direct links to each case page, each comparison HTML report, the comparison CSVs
and the base TOML that defines the physical context. It can be reused for other
method pairs or process families as long as their comparison outputs keep the
same manifest/CSV/HTML contract.

## Implementation Sequence

1. Create the `boussinesq/` testbed sub-tree and READMEs.
2. Add the synthetic base case and two or three variants first.
3. Add `armorican_outlet_ladder.csv` with outlet coordinates, target scale
   classes and mesh-size settings.
4. Add a mechanical natural smoke using the existing dummy K table, clearly
   marked as non-scientific.
5. Replace or override the dummy K table with a curated testbed-specific table.
6. Run N1 small smoke end to end and produce `testbed_cases.csv`,
   `testbed_metrics.csv`, generated mesh summaries and a compact report.
7. Promote the best small/medium natural subset into a pairwise MF6/Boussinesq
   comparison case that still uses `mesh_mode = "mesh_catchment"`.
8. Only then consider ReadTheDocs gallery integration.

## External Data Notes

Potential sources to document for the curated natural K table:

- BRGM InfoTerre geological-map downloads:
  https://infoterre.brgm.fr/page/telechargement-cartes-geologiques
- BRGM BDLISA hydrogeological reference:
  https://www.brgm.fr/fr/reference-projet-acheve/referentiel-hydrogeologique-francais-bdlisa
- HydroPortail for observed hydrometric context:
  https://www.hydro.eaufrance.fr/

These sources should be cited in the natural testbed README when their data are
used. The first implementation can remain repository-local by reusing the
already committed DEM and example data, while still regenerating the watershed
and mesh for every testbed case.
