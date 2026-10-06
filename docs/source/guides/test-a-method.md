# Test a method on many catchments

You have a way of building or solving the model, and you want to know how it behaves on
twenty catchments, not on one. After these steps one file expands a table of catchments
and a list of variants into one child file each, runs the children one after the other,
and writes tables that put the variants side by side. A second profile, `regional_lab`,
does the same for child files you already have, and records what it planned, skipped,
reused and failed.

The worked case is example 04, `examples/projects/04_streamflow_intermittence_in_transient`.
The variants are two aquifer thicknesses, 30 m and 50 m. The sites are Nançon and
placeholders. Take the structure from them, not the numbers.

## What you need first

- A base file that runs and that does not depend on one catchment. The blocks below use
  `step1_minimal.toml` of example 04, a steady run of about 6 seconds on Nançon. Do not
  use `step4_transient.toml` as the base of a many-catchment test: its recharge and runoff
  files are those of the Nançon gauge.
- A table of catchments, in CSV or JSONL, with the coordinates of each outlet. The regional
  DEM of the base file must cover them.
- The solver executables. `hmp doctor` lists the ones it finds.
- A shell in the folder of the base file. Put the testbed file there too, so that relative
  paths resolve.

A testbed file is not a project file. `hmp config check` reads it with its own schema,
chosen by {toml}`workflow.mode`. The reference lists its tables under `testbed`.

```{hmp-params}
workflow.mode
testbed.profile
```

## Choose a profile

| | generic testbed | `regional_lab` profile |
|---|---|---|
| You write | the base file, the cases, the metrics | one child file per site and recipe, and a catalog of sites |
| The tool writes | the child files, then the tables | nothing but the tables and the plan |
| Variants | an overlay per case | one recipe per variant, each with its own file template |
| Metrics | you name them, read from the stored run | status, duration and wall time per case |
| Interrupted run | children already solved are not solved again | the report says which cases are done, and they are skipped |
| A site that cannot run | a row that lacks a required column stops the plan | a line in the plan with the reason |

Start with the generic testbed. It tells you quickly whether an overlay isolates the
variant you mean to test. Use `regional_lab` when the child files exist, differ by more than
an overlay, or when a campaign is long enough to be interrupted. Steps 1 to 7 are the generic
testbed, {ref}`regional-lab` is the other profile.

## What a testbed does

1. It loads the base file and removes its own `[testbed]` table.
2. For each case it merges the overlay of the case on that base file.
3. It writes the result as `<output_root>/_generated_configs/<case id>.toml`. In the file
   name, a character other than a letter, a digit, `.`, `_` or `-` becomes `_`.
4. It runs the children in order, each through the normal workflow of its runner.
5. It rewrites the tables after each child, so a stopped run leaves a readable record.

The testbed owns the matrix of cases and the evidence. It does not solve anything itself.

Relative paths are made absolute before the child is written. A path of the base file is
read from the folder of the base file, and a path of an overlay from the folder of the
testbed file. A value counts as a path when its key contains `path`, `root`, `dir`,
`folder`, `file` or `mask`. Step 3 shows the consequence.

## 1. Write the catalog

One row per catchment. The columns you name in the file are read, and any other column is
available as a placeholder.

```text
site_id,site_label,x_outlet,y_outlet,tags
nancon,Nancon,389285.910,6816518.749,selected
site_b,Site B,389500.0,6817000.0,selected
site_c,Site C,390000.0,6818000.0,spare
```

The first row is the outlet of example 04. The other two are placeholders: write the
outlets of your catchments. The columns `site_id`, `site_label`, `x_outlet`, `y_outlet`,
`tags` and `enabled` are among those of `regional_lab_sites.csv`, the table that a site
selection writes, so the output of {doc}`select-catchments` can feed this step. A row whose
`enabled` column is false is dropped.

## 2. Declare the testbed

```toml
# not checked: fragment of testbed.toml, the whole file is shown after step 4
[workflow]
mode = "testbed"

[testbed]
id = "depth_model_test"
subject = "flow"
base_config = "step1_minimal.toml"
output_root = "outputs/depth_model_test"
execute = false

[testbed.runner]
type = "simulation"

[testbed.catalog]
path = "sites.csv"
id_field = "site_id"
label_field = "site_label"
tags = ["selected"]
required_fields = ["site_id", "x_outlet", "y_outlet"]
```

`execute = false` plans the cases and writes the child files without running them. Keep it
until step 5 is done.

```{hmp-params}
testbed.id
testbed.subject
testbed.base_config_path
testbed.output_root
testbed.execute
testbed.runner.type
testbed.catalog.path
testbed.catalog.id_field
testbed.catalog.label_field
testbed.catalog.tags
testbed.catalog.required_fields
```

- The key you write for the base file is `base_config`. The reference card above is named
  `base_config_path`.
- The path of the base file is read from the folder of the testbed file. The flow and
  transport subjects require it.
- {toml}`runner.type|testbed.runner.type` says what runs a case. `simulation` runs one
  simulation file. `comparison` runs one comparison file, see {ref}`testbed-comparison`.
  `calibration` runs one calibration file.
- A row stays when it carries every tag of {toml}`tags|testbed.catalog.tags`. Here the row
  of `site_c` is left out.
- Without {toml}`output_root|testbed.output_root` the files go to `testbed/<id>` next to the
  testbed file.

```{warning}
The `[testbed]` table does not refuse a key it does not know. `exceute = false` is read as
no key at all, `execute` keeps its default, and `hmp run` solves every case. Compare the
spelling with the cards, and keep `execute = false` until the plan looks right.
```

## 3. Write one rule per variant

A rule of {toml}`testbed.case_from_catalog` makes one case per catalog row. A string that
holds a column name between braces is replaced by the value of that column. When the whole
string is one placeholder, the value keeps its type, so `"{x_outlet}"` becomes a number.

```toml
# not checked: fragment of testbed.toml, the whole file is shown after step 4
[[testbed.case_from_catalog]]
id_template = "{site_id}_30m"
axis_template = "thickness_30m"

[testbed.case_from_catalog.overlay.simulation]
name = "{site_id}_30m"

[testbed.case_from_catalog.overlay.geographic.catchment]
dem_init_path = "../../data/dem/DEM_armorican_massif.tif"
x_outlet = "{x_outlet}"
y_outlet = "{y_outlet}"

[testbed.case_from_catalog.overlay.domain.depth_model]
thickness = "30 m"

[[testbed.case_from_catalog]]
id_template = "{site_id}_50m"
axis_template = "thickness_50m"

[testbed.case_from_catalog.overlay.simulation]
name = "{site_id}_50m"

[testbed.case_from_catalog.overlay.geographic.catchment]
dem_init_path = "../../data/dem/DEM_armorican_massif.tif"
x_outlet = "{x_outlet}"
y_outlet = "{y_outlet}"

[testbed.case_from_catalog.overlay.domain.depth_model]
thickness = "50 m"
```

```{hmp-params}
testbed.case_from_catalog.id_template
testbed.case_from_catalog.axis_template
testbed.case_from_catalog.overlay
```

Example 04 gives the thickness this value:

```{hmp-resolved} domain.depth_model.thickness
:config: step1_minimal.toml
```

What each overlay table does:

- {toml}`simulation.name` names the run of the case. Give every case its own name, or the
  second run takes the next free version of the name.
- {toml}`x_outlet|geographic.catchment.x_outlet` and
  {toml}`y_outlet|geographic.catchment.y_outlet` move the catchment to the row.
- {toml}`thickness|domain.depth_model.thickness` is the variant. Replace it by any key of the
  base file: a solver option, a mesh setting, a source of data.
- {toml}`dem_init_path|geographic.catchment.dem_init_path` is there because of the path
  rule above. Step 1 writes the DEM as a bare file name, and a bare name is looked for in
  the `data/dem` folder of the workspace. The testbed turns it into a path in the folder of
  the base file, where the DEM is not, and every child stops at its first step. Writing the
  path in the overlay avoids that. The path above is right for the example folder, one
  folder below `projects/`, with `data/dem/` next to `projects/`.

Two rules need two id templates. Without `id_template`, both rules take the id from the
catalog column and the testbed refuses the duplicate.

You can also list cases by hand with `[[testbed.case]]`, each with an `id`, an optional
`label`, an `axis` and an `overlay`. Hand-written and catalog cases can be mixed as long as
the ids differ. A case with `enabled = false` is listed with the status `disabled` and gets
no child file.

## 4. Choose the metrics

A metric copies one value of the child summary into a column of `testbed_metrics.csv`.

```toml
# not checked: fragment of testbed.toml, the whole file is shown below
[[testbed.metrics]]
name = "n_cells"
source = "flow_metrics.n_cells"

[[testbed.metrics]]
name = "max_abs_balance_error"
source = "flow_metrics.max_abs_mass_balance_percent_error"
required = true

[[testbed.metrics]]
name = "head_range_m"
source = "flow_metrics.head_range_m"
```

```{hmp-params}
testbed.metrics.name
testbed.metrics.source
testbed.metrics.required
```

`source` is a dotted path into the summary of the child. After each `simulation` child, the
testbed reopens the run in its catalog and adds these blocks to the summary:

| Block | Holds |
|---|---|
| `catalog` | the run identity, the solver, the status, the duration, the number of cells, layers and time steps |
| `parameters` | the stored scalar parameters |
| `budget` | the inflow, outflow and net flow of each budget component |
| `mass_balance` | the number of rows, and the largest, mean and last percent error of the mass balance |
| `field_summary` | statistics of the last stored state of `head`, `watertable_depth`, `outflow_drain`, `accumulation_flux` and `recharge_flux` |
| `flow_metrics` | the same values as flat keys, the ones to use as a source |

The keys of `flow_metrics` are `duration_s`, `n_cells`, `n_layers`, `n_timesteps`;
`param_<name>` for each parameter; `max_abs_mass_balance_percent_error`,
`mean_mass_balance_percent_error`, `last_mass_balance_percent_error`;
`budget_<component>_total_in`, `_total_out` and `_net`; `<field>_min`, `_max`, `_mean`,
`_abs_max` and the counts of cells; and `head_range_m`. The component names come from the
solver result, for example `chd` or `rcha` for MODFLOW 6.

- A metric that is not found is an empty cell. With `required = true` it fails the case.
- With no metric at all, `testbed_metrics.csv` holds every numeric value of the summary, as
  flat columns.
- `[[testbed.metric]]` is read too, and wins over `[[testbed.metrics]]` when a file has
  both. Use one of them.

The whole file, ready to check:

```toml
# not checked: testbed file, hmp config check reads it with its own schema
[workflow]
mode = "testbed"

[testbed]
id = "depth_model_test"
subject = "flow"
base_config = "step1_minimal.toml"
output_root = "outputs/depth_model_test"
execute = false

[testbed.runner]
type = "simulation"

[testbed.catalog]
path = "sites.csv"
id_field = "site_id"
label_field = "site_label"
tags = ["selected"]
required_fields = ["site_id", "x_outlet", "y_outlet"]

[[testbed.case_from_catalog]]
id_template = "{site_id}_30m"
axis_template = "thickness_30m"

[testbed.case_from_catalog.overlay.simulation]
name = "{site_id}_30m"

[testbed.case_from_catalog.overlay.geographic.catchment]
dem_init_path = "../../data/dem/DEM_armorican_massif.tif"
x_outlet = "{x_outlet}"
y_outlet = "{y_outlet}"

[testbed.case_from_catalog.overlay.domain.depth_model]
thickness = "30 m"

[[testbed.case_from_catalog]]
id_template = "{site_id}_50m"
axis_template = "thickness_50m"

[testbed.case_from_catalog.overlay.simulation]
name = "{site_id}_50m"

[testbed.case_from_catalog.overlay.geographic.catchment]
dem_init_path = "../../data/dem/DEM_armorican_massif.tif"
x_outlet = "{x_outlet}"
y_outlet = "{y_outlet}"

[testbed.case_from_catalog.overlay.domain.depth_model]
thickness = "50 m"

[[testbed.metrics]]
name = "n_cells"
source = "flow_metrics.n_cells"

[[testbed.metrics]]
name = "max_abs_balance_error"
source = "flow_metrics.max_abs_mass_balance_percent_error"
required = true

[[testbed.metrics]]
name = "head_range_m"
source = "flow_metrics.head_range_m"
```

## 5. Check and plan

```bash
hmp config check testbed.toml
hmp run testbed.toml
```

`hmp config check` prints `OK: <path>` when the `[testbed]` table loads. It does not open
the base file, the catalog or the overlays.

With `execute = false`, `hmp run` expands the cases and writes the child files and the
tables, then prints `Workflow 'testbed' complete: testbed.toml` and the keys of the
summary. `case_count` is 4 here: two rules, two sites. `executed_count` is 0.

Open the plan before you pay for any solve.

1. `testbed_cases.csv` has one row per case, with the status `planned`, the `axis` and the
   path of the child file.
2. In `outputs/depth_model_test/_generated_configs/`, open `site_b_50m.toml`. Read the
   outlet, the thickness and the path of the DEM. The file is a normal simulation file:
   `hmp config check` accepts it, and `hmp run` runs it by hand.
3. Check that the path of the DEM exists. `hmp config check` does not look for it.

`testbed_metrics.csv` is empty at this stage: it holds one row per executed case.

## 6. Run the cases

Set `execute = true` in the file, or delete the line, and run again.

```bash
hmp run testbed.toml
```

The children run one after the other. A case that fails is recorded and the next one
starts, unless {toml}`continue_on_error|testbed.continue_on_error` is false. In that case
the testbed writes its tables, then raises the error of the failed case.

```{hmp-params}
testbed.continue_on_error
testbed.runner.no_display
```

- Each case is an ordinary run of the project of the base file, named by
  {toml}`simulation.name`. `hmp catalog ls` lists them, and the guide
  {doc}`find-compare-and-clean-runs` shows how to open, compare and delete them.
- A child whose resolved configuration equals a completed run of the project is not solved
  again, and the testbed still reads its results. After a failure, run the file again: the
  children that completed are read, the others are solved.
- The exit code of `hmp run` is 0 even when cases failed. Read `failed_count` in the
  summary, or the `status` column of `testbed_cases.csv`.

## 7. Read the evidence

Five files, in `output_root`. Read them in this order.

1. `_generated_configs/`: what each child received after the merge. Confirm first that the
   overlays isolate the variant you mean to test.
2. `testbed_report.md`: the counts, then one line per case with its status and duration.
3. `testbed_cases.csv`: one row per case. `status` is `planned`, `disabled`, `ok` or
   `failed`. `error` holds the message of a failed case. The columns that follow come
   from the child summary: `name`, `sim_id`, `catalog`, `mass_balance`, `flow_metrics`.
4. `testbed_metrics.csv`: one row per executed case, with `case_id`, `case_label`, `axis`,
   `status` and one column per metric. A failed case has an `error` column instead.
5. `testbed_manifest.json` and `testbed_plan.json`: the same content for a program, with
   the catalog, the rules and the paths of every file.

The label is the site and the axis is the variant, so a pivot puts the variants side by
side:

```python
import pandas as pd

metrics = pd.read_csv("outputs/depth_model_test/testbed_metrics.csv")
ok = metrics[metrics["status"] == "ok"]
print(ok.pivot(index="case_label", columns="axis", values="head_range_m"))
```

A site that failed under one variant has no value in its column. Look at its `error` first.

(testbed-comparison)=
## Compare several methods on each site

To compare solvers or solver options on every site, give the testbed a comparison file as
base. Each case then runs one comparison, with its audit, its metrics and its figures.
{doc}`compare-runs` explains the comparison file. The base simulation of that file must
work at every site, as in the first section of this page.

```toml
# not checked: comparison file, the base of a comparison testbed
[workflow]
mode = "comparison"

[comparison]
comparison_id = "ims"
base_simulation_config = "step1_minimal.toml"
reference_simulation = "complex"

[[comparison.simulation]]
id = "complex"
label = "IMS COMPLEX"
solver = "modflow6"

[[comparison.simulation]]
id = "moderate"
label = "IMS MODERATE"
solver = "modflow6"

[comparison.simulation.overlay.modflow6.runtime]
mf6_ims_complexity = "MODERATE"

[[comparison.observable]]
name = "head_outlet"
variable = "watertable_elevation"
support = "point"
x = 389285.910
y = 6816518.749
time = "all"
unit = "m"
```

Save it as `compare_ims.toml`. The testbed file sets what changes with the site: the name
and folder of the comparison, the catchment of the base simulation, and the point of the
observable.

```toml
# not checked: testbed file, hmp config check reads it with its own schema
[workflow]
mode = "testbed"

[testbed]
id = "ims_on_sites"
subject = "flow"
base_config = "compare_ims.toml"
output_root = "outputs/ims_on_sites"
execute = false

[testbed.runner]
type = "comparison"

[testbed.catalog]
path = "sites.csv"
id_field = "site_id"
tags = ["selected"]
required_fields = ["site_id", "x_outlet", "y_outlet"]

[[testbed.case_from_catalog]]
id_template = "{site_id}"

[testbed.case_from_catalog.overlay.comparison]
comparison_id = "ims_{site_id}"
output_root = "outputs/ims_on_sites/comparisons/{site_id}"

[testbed.case_from_catalog.overlay.comparison.base_simulation_overlay.geographic.catchment]
dem_init_path = "../../data/dem/DEM_armorican_massif.tif"
x_outlet = "{x_outlet}"
y_outlet = "{y_outlet}"

[[testbed.case_from_catalog.overlay.comparison.observable]]
x = "{x_outlet}"
y = "{y_outlet}"
```

- The path of the DEM is written in the overlay for the reason given in step 3.
- The last table has the same length as the list of observables of the base file, so the
  two lists merge element by element: the observable keeps its name, variable and unit and
  takes the point of the site. With one observable more or less in the overlay, the
  overlay would replace the list. {doc}`inheritance` gives the rule.
- With no `[[testbed.metrics]]`, `testbed_metrics.csv` holds a default summary of each
  comparison: `comparison_id`, `audit_status`, `n_metric_rows`, `n_difference_rows` and the
  numerical closure columns when the comparison produced them.
- Read the audit of a comparison before its metrics, as {doc}`compare-runs` says.

(regional-lab)=
## The regional_lab profile

Use it when a child file already exists for each site, and you want one plan and one report
for the whole campaign. The file keeps `[workflow].mode = "testbed"`, and selects the
profile in {toml}`testbed.profile`. The settings of the campaign are in a table
`[regional_lab]`.

The reference lists the keys of this table under `analysis.batch`: the two names are one
model, and the links below point there. In a testbed file you write `[regional_lab]`,
because `hmp run` reads that name. A testbed file with the same keys under
`[analysis.batch]` is refused.

### The child files

One file per site. It is a normal simulation file. It sits in a subfolder here, so it
states its project folder: without that line the folder of the child becomes the project,
and the DEM is not found.

```toml
base_config = "../step1_minimal.toml"

[workspace]
project_root = ".."

[simulation]
name = "site_b_regional"

[geographic.catchment]
x_outlet = 389500.0
y_outlet = 6817000.0
```

Save it as `children/site_b.toml`, and write the others the same way. A script can write
them from your catalog.

### The campaign file

The catalog describes sites. It is not a model file. The columns below are the defaults; a
column with another name is declared in {toml}`catalog|analysis.batch.catalog`.

```text
site_id,site_label,region_id,cluster_id,enabled,x,y,tags
nancon,Nancon,brittany,headwater,true,389285.910,6816518.749,headwater;gauged
site_b,Site B,brittany,headwater,true,389500.0,6817000.0,headwater
site_c,Site C,brittany,regional,true,390000.0,6818000.0,regional
```

```toml
# not checked: a regional_lab file is read by its own schema, not by HydroModPyConfig
[workflow]
mode = "testbed"

[testbed]
profile = "regional_lab"

[regional_lab]
lab_id = "headwaters"
output_root = "outputs/headwaters"
execute = false

[regional_lab.catalog]
path = "site_catalog.csv"

[regional_lab.selection]
regions = ["brittany"]

[[regional_lab.recipe]]
id = "steady_mf6"
label = "Steady MODFLOW 6"
launcher = "simulation"
config_path_template = "children/{site_id}.toml"
```

```{hmp-params}
analysis.batch.lab_id
analysis.batch.output_root
analysis.batch.execute
analysis.batch.continue_on_error
analysis.batch.validate_config_paths
analysis.batch.resume_from_report
analysis.batch.skip_completed_cases
analysis.batch.catalog.path
analysis.batch.selection.regions
analysis.batch.selection.tags
analysis.batch.recipes.id
analysis.batch.recipes.launcher
analysis.batch.recipes.config_path_template
```

The expansion goes in this order:

```text
catalog of sites
  -> cluster rules (optional)
  -> global selection
  -> selection of each recipe
  -> one case per site and recipe, named <recipe id>::<site id>
  -> plan, then execution
  -> tables and report
```

- A recipe turns the row of a site into the path of a child file. Any column of the
  catalog can appear in the template, with `site_id` and `lab_id`.
- {toml}`launcher|analysis.batch.recipes.launcher` is `simulation` or `comparison`. Several
  recipes can use different launchers in one campaign.
- Selection filters keep the sites that match every filter you give: regions, clusters,
  families, scales, statuses, maturity levels, site ids and tags. A site must carry every
  tag listed. `limit` keeps the first sites in the order of region, cluster and site id.
- {toml}`cluster_rules|analysis.batch.cluster_rules` give a cluster to sites that have none,
  by their region, tags or any column.
- A site-selection manifest can replace the catalog `path`. Write
  `from_site_selection_manifest = "<manifest.json>"` and, optionally, `output = "<key>"`
  in the catalog table, in a regional lab or in a generic testbed. The default key is
  `regional_lab_sites_csv`. The option
  {toml}`write_regional_lab_csv|site_selection.output.write_regional_lab_csv` of a site
  selection writes that file. A catalog table holding both `path` and the manifest key is
  refused.

### Plan, then run

```bash
hmp config check regional.toml
hmp run regional.toml
```

With `execute = false` the command plans and writes the tables. The summary it prints has
`selected_site_count`, `planned_case_count` and `skipped_case_count`. A pair of site and
recipe that cannot run is skipped with a reason, not with an error:

| Status in the case matrix | Meaning |
|---|---|
| `skipped_missing_config_path` | the child file of the template does not exist and `validate_config_paths` is true |
| `skipped_missing_required_fields` | the site lacks a column that the recipe lists in `required_fields` |
| `skipped_unsupported_platform` | the recipe lists `allowed_platforms` and this one is not in it |

With the three sites above and no file for `site_c`, the plan has two cases and one skipped
case, and the summary lists the gap:

```text
## Coverage Gaps

- `steady_mf6` / `site_c`: missing_config_path (Resolved child config is missing: <folder>/children/site_c.toml)
```

When the plan is right, set `execute = true`. The cases run in order, each through the
launcher of its recipe, and every table is rewritten after each case.

- A case is `ok` or `failed`. The report keeps no message for a failed case: run the child
  file by hand, for example `hmp run children/site_b.toml`, to read the error.
- A second run skips the cases that the previous report marks as completed, and lists them
  with the status `skipped_existing_ok`. Both
  {toml}`resume_from_report|analysis.batch.resume_from_report` and
  {toml}`skip_completed_cases|analysis.batch.skip_completed_cases` must be true. A failed
  case is tried again.
- With {toml}`continue_on_error|analysis.batch.continue_on_error` false, the loop stops
  after the first failed case, and `hmp run` still exits with 0.

### The files it writes

All are in `output_root`. Read them in this order.

1. `regional_lab_summary.md`: the counts, then one table per recipe, cluster and region,
   then the coverage gaps with their reasons.
2. `regional_lab_case_matrix.csv`: one row per planned or skipped case, with `status`,
   `reason`, `detail`, `duration_seconds` and `reused_from_report`.
3. `regional_lab_execution_metrics.csv`: one row per executed case, with the artifacts of
   the child, such as its wall time and its project folder.
4. `regional_lab_recipe_summary.csv`, `regional_lab_cluster_summary.csv`,
   `regional_lab_region_summary.csv`, `regional_lab_family_summary.csv` and
   `regional_lab_scale_summary.csv`: the counts and durations by group, with the share of
   candidate sites that the recipe covers. A table is written only when it has rows.
5. `regional_lab_site_inventory.csv`: the selected sites and what happened to each.
6. `regional_lab_plan.json` and `regional_lab_report.json`: the same content for a
   program. The report has `all_passed`, true when nothing failed and nothing is pending.

The profile does not read metrics from the runs. To compare the results of the sites, open
the runs from the catalog of each project, as in {doc}`find-compare-and-clean-runs`.

### Share the terrain work between sites

When the children of a campaign use one DEM, {toml}`share_regional_flow|analysis.batch.share_regional_flow`
does the terrain analysis once. It applies when `execute` is true. It accepts simulation
recipes with an outlet catchment and a DEM path, and refuses lake enforcement and river
network extraction. The launcher writes the shared job in `regional_flow_jobs/` and one
child file per case in `materialized_configs/`. A refusal names the case, for example
`<case id>: shared flow requires an outlet catchment`.

## What can go wrong

The message that `hmp config check` or `hmp run` prints is quoted. The folder part of a
path is replaced by `<folder>`.

A subject that is not known:

```text
Config invalid: Unsupported testbed.subject 'mash'. Supported values: flow, mesh, transport.
```

A runner that the subject does not accept, for example a mesh subject with a comparison:

```text
Config invalid: testbed.subject='mesh' requires runner.type to be one of simulation.
```

A flow test with no base file:

```text
Config invalid: testbed.runner.type='simulation' requires testbed.base_config to point to the delegated child workflow TOML. Keep the testbed declaration outside the child config.
```

A testbed with no case, or catalog rules with no catalog:

```text
Config invalid: testbed.case or testbed.case_from_catalog must contain at least one item
Config invalid: testbed.case_from_catalog requires a [testbed.catalog] section
```

The old spelling of a case:

```text
Config invalid: testbed.variant is no longer supported; use testbed.case.
```

Two cases with the same id, in the same testbed or across two rules. The comparison ignores
case:

```text
Duplicate testbed.case id 'nancon_30m'
```

Give each rule its own `id_template`.

A placeholder that is not a column of the catalog, or a column that a rule requires and the
catalog lacks:

```text
testbed.case_from_catalog[nancon_30m].overlay.geographic.catchment.x_outlet references unknown catalog field 'xx'
testbed catalog row is missing required field(s): zz
```

A catalog or a base file that does not exist. Both are found by `hmp run`, not by
`hmp config check`:

```text
Missing file: testbed catalog path not found: <folder>/nofile.csv
Missing file: [Errno 2] No such file or directory: '<folder>/nope.toml'
```

A catalog whose tags filter leaves no row:

```text
testbed did not expand any case
```

A required metric that the summary does not hold. The case is marked `failed`, and the
text is in the `error` column, after `ValueError: `:

```text
Required testbed metric 'max_abs_balance_error' could not be found at source 'flow_metrics.max_abs_mass_balance_percent_error'.
```

The usual cause is a source with a typo. The `flow_metrics` block exists for the
`simulation` runner only, so a source that starts with it fails for a `comparison` or a
`calibration` runner. When the run of a child cannot be reopened, the summary has a
`catalog_extraction_error` key instead of `flow_metrics`.

A child that stops at its first step. The `error` column holds the error of the child,
here a DEM path that the testbed made absolute:

```text
StepError: step 'build_geographic' failed: RasterioIOError: <folder>/DEM_armorican_massif.tif: No such file or directory
```

Put the DEM path in the overlay, as in step 3. The same applies to any other bare file name
that the base file leaves to the data folder of the workspace, as long as its key looks
like a path. To see the error of a child without the testbed, run one generated file by
hand with `hmp run <child file>`.

The regional lab refuses what it does not know, where the generic testbed does not:

```text
Config invalid: <folder>/regional.toml
  exceute: Extra inputs are not permitted (input=False)
```

Other messages of the profile:

```text
regional_lab selection did not match any site
regional_lab.recipe[steady_mf6] references unknown template key 'site'
Missing file: regional_lab.catalog.path not found: <folder>/nocatalog.csv
Config invalid: <folder>/regional.toml
  recipes.0.launcher: Value error, Unsupported regional_lab.recipe launcher 'calibration'. Use 'simulation' or 'comparison'. (input='calibration')
```

A `[regional_lab]` table in a project file, which is not a testbed file, is refused:

```text
Config invalid: <folder>/project.toml: Section [regional_lab] is not a HydroModPyConfig section. Use [analysis.batch] for regional-lab testbed settings.
```

In a testbed file the table must stay `[regional_lab]`, as above.

## Next

- Run the cases of a comparison and read their audit: {doc}`compare-runs`.
- Find the runs of a testbed in the catalog, compare and delete them:
  {doc}`find-compare-and-clean-runs`.
- Choose the catchments of a campaign: {doc}`select-catchments`.
- How a file inherits another and how lists of tables merge: {doc}`inheritance`.
- Search a parameter on one catchment: {doc}`calibrate`.
- Every key of the testbed: {toml}`testbed`. Every key of the profile: {toml}`analysis.batch`.
