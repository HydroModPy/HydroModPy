# Test a method on many catchments

You have a way of building or solving the model, and you want to know how it behaves on
twenty catchments, not on one. After these steps one file expands a table of catchments
and a list of variants into one child file each, runs the children one after the other,
and writes tables that put the variants side by side. If the child files already exist, the
`regional_lab` profile plans and records a whole campaign over them: {doc}`regional-lab`.

The worked case chains two guides. {doc}`select-catchments` finds five basins of about 20 km2
around the Nançon. This guide tests two aquifer thicknesses, 30 m and 50 m, on each of them.
Take the structure from the example, not the numbers.

```{hmp-task}
Task
: Run one change of the model on a table of catchments, and read the evidence side by side.

Time
: Planning takes seconds. The ten cases of this page took 111 s: 10 to 12 s each. A second run of the same file took 6 s, the children being read and not solved again.

Needs
: A base file that runs and depends on no single catchment, a table of outlets, and the MODFLOW 6 executable (`hmp doctor`).

Gives
: The child files, the tables `testbed_cases.csv` and `testbed_metrics.csv`, a report, and one catalog run per case.
```

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

| | generic testbed (this page) | `regional_lab` profile ({doc}`regional-lab`) |
|---|---|---|
| You write | the base file, the cases, the metrics | one child file per site and recipe, and a catalog of sites |
| The tool writes | the child files, then the tables | nothing but the tables and the plan |
| Variants | an overlay per case | one recipe per variant, each with its own file template |
| Metrics | you name them, read from the stored run | status, duration and wall time per case |
| Interrupted run | children already solved are not solved again | the report says which cases are done, and they are skipped |
| A site that cannot run | a case that fails is recorded, and the command ends with exit code 23 | a line in the plan with the reason |

Start with the generic testbed. It tells you quickly whether an overlay isolates the
variant you mean to test. Use `regional_lab` when the child files exist, differ by more than
an overlay, or when a campaign is long enough to be interrupted.

## What a testbed does

1. It loads the base file and removes its own `[testbed]` table.
2. For each case it merges the overlay of the case on that base file.
3. It writes the result as `<output_root>/_generated_configs/<case id>.toml`. In the file
   name, a character other than a letter, a digit, `.`, `_` or `-` becomes `_`.
4. It runs the children in order, each through the normal workflow of its runner.
5. It rewrites the tables after each child, so a stopped run leaves a readable record.

The testbed owns the matrix of cases and the evidence. It does not solve anything itself.

Relative paths are made absolute before the child is written, and only the ones the child
schema declares as paths. A path of the base file is read from the folder of the base file, and a
path of an overlay from the folder of the testbed file. A value becomes absolute when its field is
typed as a path or as an input file, or when it is a text named `path` or ending in `_path`,
`_file`, `_dir`, `_root` or `_folder`. A choice such as `track_dir = "forward"` or a text such as
`profile = "x"` is copied as written. A bare file name given to an input-file key, such as
`DEM_armorican_massif.tif`, and absent from the folder of the base file, stays bare: the child
looks for it in the data folders of the workspace, as {doc}`use-your-own-files` says.

## 1. Write the catalog

One row per catchment. The columns you name in the file are read, and any other column is
available as a placeholder. Here is the file `regional_lab_sites.csv` that the area route of
{doc}`select-catchments` wrote, saved as `sites.csv`, with the columns the testbed uses:

```text
site_id,site_label,x_outlet,y_outlet,area_km2,tags
dem_area_00001,dem_area_00001,382950.0,6820500.0,20.10375,site_selection;nancon_area
dem_area_00002,dem_area_00002,375600.0,6826725.0,19.895625,site_selection;nancon_area
dem_area_00003,dem_area_00003,396000.0,6825150.0,20.154375,site_selection;nancon_area
dem_area_00004,dem_area_00004,375075.0,6810750.0,19.749375,site_selection;nancon_area
dem_area_00005,dem_area_00005,385875.0,6805800.0,20.311875,site_selection;nancon_area
```

The columns `site_id`, `site_label`, `x_outlet`, `y_outlet`, `tags` and `enabled` are among
those of that file, so the output of a site selection feeds this step with no editing. The
catalog can also take the file through the manifest, see {doc}`regional-lab`. A row whose
`enabled` column is false is dropped.

## 2. Declare the testbed

```toml
[workflow]
mode = "testbed"

[testbed]
id = "depth_on_five_basins"
subject = "flow"
base_config = "step1_minimal.toml"
output_root = "outputs/depth_on_five_basins"
execute = false

[testbed.runner]
type = "simulation"
no_display = true

[testbed.catalog]
path = "sites.csv"
id_field = "site_id"
label_field = "site_label"
tags = ["site_selection"]
required_fields = ["site_id", "x_outlet", "y_outlet"]

[[testbed.case_from_catalog]]
id_template = "{site_id}_30m"
axis_template = "thickness_30m"

[testbed.case_from_catalog.overlay.simulation]
name = "{site_id}_30m"

[testbed.case_from_catalog.overlay.geographic.catchment]
x_outlet = "{x_outlet}"
y_outlet = "{y_outlet}"

[testbed.case_from_catalog.overlay.domain.depth_model]
thickness = "30 m"
```

`execute = false` plans the cases and writes the child files without running them. Keep it
until step 5 is done. The block is the start of the file, with the rule of step 3 for 30 m; the
whole file is at the end of step 4.

```{hmp-params}
testbed.id
testbed.subject
testbed.base_config
testbed.output_root
testbed.execute
testbed.runner.type
testbed.runner.no_display
testbed.catalog.path
testbed.catalog.id_field
testbed.catalog.label_field
testbed.catalog.tags
testbed.catalog.required_fields
```

- The path of the base file is read from the folder of the testbed file. The flow and
  transport subjects require it.
- {toml}`runner.type|testbed.runner.type` says what runs a case. `simulation` runs one
  simulation file. `comparison` runs one comparison file, see {ref}`testbed-comparison`.
  `calibration` runs one calibration file, see the metrics of step 4.
- A row stays when it carries every tag of {toml}`tags|testbed.catalog.tags`. The five rows
  above carry `site_selection`.
- Without {toml}`output_root|testbed.output_root` the files go to `testbed/<id>` next to the
  testbed file.
- {toml}`no_display|testbed.runner.no_display` skips the figures of the children. Their
  `[display]` figures are the longest part of a small run.

```{note}
The `[testbed]` table refuses a key it does not know: `exceute = false` stops the file with
`[testbed] does not accept 'exceute'. Accepted keys: ...`. Keep `execute = false` until the
plan looks right.
```

## 3. Write one rule per variant

A rule of {toml}`testbed.case_from_catalog` makes one case per catalog row. A string that
holds a column name between braces is replaced by the value of that column. When the whole
string is one placeholder, the value keeps its type, so `"{x_outlet}"` becomes a number.

```toml
[workflow]
mode = "testbed"

[testbed]
id = "depth_on_five_basins"
subject = "flow"
base_config = "step1_minimal.toml"
output_root = "outputs/depth_on_five_basins"
execute = false

[testbed.runner]
type = "simulation"
no_display = true

[testbed.catalog]
path = "sites.csv"
id_field = "site_id"
label_field = "site_label"
tags = ["site_selection"]
required_fields = ["site_id", "x_outlet", "y_outlet"]

[[testbed.case_from_catalog]]
id_template = "{site_id}_30m"
axis_template = "thickness_30m"

[testbed.case_from_catalog.overlay.simulation]
name = "{site_id}_30m"

[testbed.case_from_catalog.overlay.geographic.catchment]
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
  {toml}`y_outlet|geographic.catchment.y_outlet` move the catchment to the row. The DEM is the
  one of the base file: `step1_minimal.toml` names it as a bare file, and the child finds it in the
  data folder of the workspace.
- {toml}`thickness|domain.depth_model.thickness` is the variant. Replace it by any key of the
  base file: a solver option, a mesh setting, a source of data.

Two rules need two id templates. Without `id_template`, both rules take the id from the
catalog column and the testbed refuses the duplicate.

You can also list cases by hand with `[[testbed.case]]`, each with an `id`, an optional
`label`, an `axis` and an `overlay`. Hand-written and catalog cases can be mixed as long as
the ids differ. A case with `enabled = false` is listed with the status `disabled` and gets
no child file.

## 4. Choose the metrics

A metric copies one value of the child summary into a column of `testbed_metrics.csv`.

```toml
# not checked: fragment of the testbed file, the whole file is shown below
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

[[testbed.metrics]]
name = "drain_out_m3_s"
source = "flow_metrics.budget_drain_total_out"
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
`param_<name>` for each parameter (`param_K`, `param_Sy`, `param_thickness`);
`max_abs_mass_balance_percent_error`, `mean_mass_balance_percent_error`,
`last_mass_balance_percent_error`; `budget_<component>_total_in`, `_total_out` and `_net`;
`<field>_min`, `_max`, `_mean`, `_abs_max` and the counts of cells; and `head_range_m`. The
component names come from the budget of the run. For the steady MODFLOW 6 run of this page they
are `drain`, `recharge`, `storage_ss` and `storage_sy`.

- A metric that is not found is an empty cell. With `required = true` it fails the case.
- With no metric at all, `testbed_metrics.csv` holds every numeric value of the summary, as
  flat columns.
- A field the run did not store gives a warning, and its metrics are left out: `Skipping testbed
  field metrics: field 'outflow_drain' is not in the store. Set [simulation.results.derived]
  outflow_drain = true and run the simulation again: this field is written during the run, not on
  read.` Put the flag in the overlay or in the base file.
- The older spelling `[[testbed.metric]]` is refused: write `[[testbed.metrics]]`.

### Discharge metrics

The metrics above are the flow of the model, not a score against a gauge. Three ways to read
the discharge, from the least to the most demanding:

- **The simulated discharge of a case.** `budget_drain_total_out` is the water that leaves
  through the drains in the zone the budget covers, in m3/s. For a steady run it is the baseflow
  to the streams, to read beside `budget_recharge_total_in`, the recharge that enters. On the
  five basins it ranged from 0.14 to 0.24 m3/s for 0.18 m3/s of recharge. The run warns that this
  discharge is baseflow only when it has no runoff forcing.
- **A score against a gauge, with the `calibration` runner.** The child is a calibration file,
  and the summary is the report of the calibration. `best_objective` is the lowest cost the
  search reached, in the units of the objective of the file (the objective is scored against the
  observed discharge, so a lower cost is a better score). `best_parameters.<name>`,
  `n_iterations` and `duration_s` are in the summary too. A calibration needs observations for
  every site, so the base file cannot carry the gauge of the Nançon for all of them.

  ```toml
  [workflow]
  mode = "testbed"

  [testbed]
  id = "calibration_on_sites"
  subject = "flow"
  base_config = "run_calibration.toml"
  output_root = "outputs/calibration_on_sites"
  execute = false

  [testbed.runner]
  type = "calibration"

  [testbed.catalog]
  path = "sites.csv"
  id_field = "site_id"
  required_fields = ["site_id", "x_outlet", "y_outlet"]

  [[testbed.case_from_catalog]]
  id_template = "{site_id}"

  [testbed.case_from_catalog.overlay.geographic.catchment]
  x_outlet = "{x_outlet}"
  y_outlet = "{y_outlet}"

  [[testbed.metrics]]
  name = "best_cost"
  source = "best_objective"
  ```

  This file is checked against its schema only: no calibration was run on many sites for this
  page.
- **A comparison of simulations on a discharge observable**, with the `comparison` runner, see
  the last section of this page.

## The whole file

The whole file of the five basins, ready to check:

```toml
[workflow]
mode = "testbed"

[testbed]
id = "depth_on_five_basins"
subject = "flow"
base_config = "step1_minimal.toml"
output_root = "outputs/depth_on_five_basins"
execute = false

[testbed.runner]
type = "simulation"
no_display = true

[testbed.catalog]
path = "sites.csv"
id_field = "site_id"
label_field = "site_label"
tags = ["site_selection"]
required_fields = ["site_id", "x_outlet", "y_outlet"]

[[testbed.case_from_catalog]]
id_template = "{site_id}_30m"
axis_template = "thickness_30m"

[testbed.case_from_catalog.overlay.simulation]
name = "{site_id}_30m"

[testbed.case_from_catalog.overlay.geographic.catchment]
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

[[testbed.metrics]]
name = "drain_out_m3_s"
source = "flow_metrics.budget_drain_total_out"
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
summary. `case_count` is 10 here: two rules, five sites. `executed_count` is 0.

Open the plan before you pay for any solve.

1. `testbed_cases.csv` has one row per case, with the status `planned`, the `axis` and the
   path of the child file.
2. In `outputs/depth_on_five_basins/_generated_configs/`, open `dem_area_00004_50m.toml`. Read the
   outlet, the thickness and the path of the DEM. The file is a normal simulation file:
   `hmp config check` accepts it, and `hmp run` runs it by hand.
3. Check that the DEM exists where the child will look for it. `hmp config check` does not look.

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
```

- Each case is an ordinary run of the project of the base file, named by
  {toml}`simulation.name`. `hmp catalog ls` lists them, and the guide
  {doc}`find-and-compare-runs` shows how to open and compare them, and
  {doc}`clean-and-reindex-runs` how to delete them.
- A child whose resolved configuration equals a completed run of the project is not solved
  again, and the testbed still reads its results. The second run of the file above took 6 s,
  with 0.2 s for each case. After a failure, run the file again: the children that completed are
  read, the others are solved.
- When a case failed, `hmp run` writes every file of the evidence, then ends with the exit code
  23 (`FailedCasesError`), so that a script or a CI job sees it. It prints the cases that failed
  and the report to read:

  ```text
  testbed 'one_fails': 1 of 2 case(s) failed: outside_the_dem. Read outputs/one_fails/testbed_report.md.
  ```

  Read `failed_count` in the summary, or the `status` column of `testbed_cases.csv`, to see
  which cases failed. In Python, the summary is the `.summary` of the exception.

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

metrics = pd.read_csv("outputs/depth_on_five_basins/testbed_metrics.csv")
ok = metrics[metrics["status"] == "ok"]
print(ok.pivot(index="case_label", columns="axis", values="head_range_m").round(1))
```

```text
axis            thickness_30m  thickness_50m
case_label
dem_area_00001           54.2           38.1
dem_area_00002           78.9           72.4
dem_area_00003           39.6           33.2
dem_area_00004           60.0           51.1
dem_area_00005           39.2           30.1
```

On the five basins the head range, the difference between the highest and the lowest head, is
smaller with the thicker aquifer on every one, by 6 to 16 m, and the number of cells is the same in
the two columns (6 080 to 7 308), as it should be: the thickness moves the bottom of the model,
not its mesh. The mass balance closes on every case (`max_abs_balance_error` is 0.0). A site that
failed under one variant has no value in its column. Look at its `error` first.

## The subjects: flow, mesh and transport

{toml}`testbed.subject` says what the testbed is about. It sets the runners a case may use and
whether `base_config` is required.

| Subject | Runners | `base_config` | The child is |
|---|---|---|---|
| `flow` | `simulation`, `comparison`, `calibration` | required | a flow model, a comparison of flow models, or a calibration |
| `mesh` | `simulation` | optional | a simulation with a mesh process: the testbed adds `[[simulation.process]] type = "mesh"`, `backend = "catchment"` when the file declares none |
| `transport` | `simulation`, `comparison` | required | a transport model, or a comparison of transport models |

A subject left out is `mesh`. A runner the subject does not accept is refused at the check. The
cases, the catalog, the metrics and the evidence are the same for the three. What changes is
what the child produces, and so which sources a metric can read: the budget and field blocks of
step 4 exist for a child that stored a flow run.

A mesh testbed varies a meshing option over a table of catchments. The base file is a simulation
file with a `[mesh_catchment]` section, which example 04 does not have, so this block is checked
against the schema only:

```toml
[workflow]
mode = "testbed"

[testbed]
id = "mesh_resolution"
subject = "mesh"
base_config = "mesh_base.toml"
output_root = "outputs/mesh_resolution"
execute = false

[testbed.runner]
type = "simulation"

[[testbed.case]]
id = "coarse"
axis = "resolution"

[testbed.case.overlay.mesh_catchment.zone_meshing]
global_size = 3500.0

[[testbed.case]]
id = "fine"
axis = "resolution"

[testbed.case.overlay.mesh_catchment.zone_meshing]
global_size = 1600.0
```

A transport testbed has the same shape, with `subject = "transport"` and a base file that
declares a `[transport]` section; the comparison runner compares the transport solvers. The
base file must be a transport model that runs: example 04 has none, and this page ran no
transport or mesh case.

(testbed-comparison)=
## Compare several methods on each site

To compare solvers or solver options on every site, give the testbed a comparison file as
base. Each case then runs one comparison, with its audit, its metrics and its figures.
{doc}`compare-runs` explains the comparison file. The base simulation of that file must
work at every site, as in the first section of this page.

```toml
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
name = "head_last"
variable = "watertable_elevation"
support = "map"
time = "last"
unit = "m"
```

Save it as `compare_ims.toml`. The observable is a map, because the two children share the
grid: a `point` given by `x` and `y` needs a mesh bundle to find its cell, which a structured
grid does not have, and the comparison would stop with `Point observable '<name>' needs a mesh
bundle cells.csv for x/y lookup, or a cell_index.` The testbed file sets what changes with the
site: the name and folder of the comparison, and the catchment of the base simulation.

```toml
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
tags = ["site_selection"]
required_fields = ["site_id", "x_outlet", "y_outlet"]

[[testbed.case_from_catalog]]
id_template = "{site_id}"

[testbed.case_from_catalog.overlay.comparison]
comparison_id = "ims_{site_id}"
output_root = "outputs/ims_on_sites/comparisons/{site_id}"

[testbed.case_from_catalog.overlay.comparison.base_simulation_overlay.geographic.catchment]
x_outlet = "{x_outlet}"
y_outlet = "{y_outlet}"
```

- `base_simulation_overlay` is the part of the comparison file that every child inherits: it
  moves the catchment of the base simulation to the row. The DEM stays the bare name of
  `step1_minimal.toml`. Each child runs in a workspace of its own, so the testbed looks the name
  up in the data folder of the workspace of the base file, and writes the path it finds into the
  child. A name found nowhere stays bare, and the child stops at its first step.
- To change a list of the comparison for each site, such as the list of observables, write
  `observable__merge` instead of `observable` in the overlay: the table then merges, element by
  element, into the one of the base file, and the directive is refused when the lengths differ.
  {doc}`inheritance` gives the rule.
- With no `[[testbed.metrics]]`, `testbed_metrics.csv` holds a default summary of each
  comparison: `comparison_id`, `audit_status`, `n_metric_rows`, `n_difference_rows` and the
  numerical closure columns when the comparison produced them.
- Read the audit of a comparison before its metrics, as {doc}`compare-runs` says.

The files above ran on the five basins of step 1, with `execute = true`. It took 180 s, 34 to 38 s
for each site, and ended with the exit code 23 because two cases failed. This is the evidence, in
`testbed_metrics.csv` (the column `closure_max_abs_mm_d` is empty and left out):

| `case_id` | `status` | `audit_status` | `n_difference_rows` | `closure_max_abs_m3_s` | `closure_relative_error_p95` |
|---|---|---|---:|---:|---:|
| `dem_area_00001` | `failed` | | | | |
| `dem_area_00002` | `ok` | `pass` | 7308 | 0.0125 | 0.0114 |
| `dem_area_00003` | `failed` | | | | |
| `dem_area_00004` | `ok` | `pass` | 6256 | 0.0090 | 0.0090 |
| `dem_area_00005` | `ok` | `pass` | 6080 | 0.0295 | 0.0290 |

On three basins the two settings agree: the audit passes, and the 95th percentile of the relative
closure error is 0.9 to 2.9 %. On the two others the `error` column says
`Comparison child 'moderate' failed: hmp run exited with code 15` and the end of the log of the
child, `SolverDivergedError: [HMPY.E401] Flow solver 'modflow6' failed`: IMS MODERATE did not
converge where IMS COMPLEX did. One site would not have shown it. Run the child of such a case by
hand, from its folder `comparisons/<site>/workspaces/moderate`, to read its `mfsim.lst`.

## What can go wrong

The message that `hmp config check` or `hmp run` prints is quoted. The folder part of a path is
replaced by `<folder>`.

| Symptom | Cause | Fix |
|---|---|---|
| `Config invalid: Unsupported testbed.subject 'mash'. Supported values: flow, mesh, transport.` | A subject that is not known. | Use one of the three. |
| `Config invalid: testbed.subject='mesh' requires runner.type to be one of simulation.` | A runner that the subject does not accept. | Use a runner of the table of subjects. |
| `Config invalid: testbed.runner.type='simulation' requires testbed.base_config to point to the delegated child workflow TOML. Keep the testbed declaration outside the child config.` | A flow or transport test with no base file. | Write {toml}`testbed.base_config`. |
| `Config invalid: testbed.case or testbed.case_from_catalog must contain at least one item`, or `testbed.case_from_catalog requires a [testbed.catalog] section` | A testbed with no case, or rules with no catalog. | Add a case, or the catalog table. |
| `Config invalid: testbed.variant is no longer supported; use testbed.case.` | The old spelling of a case. | Write `testbed.case`. |
| `Config invalid: [testbed] does not accept 'exceute'. Accepted keys: ...` | A key is misspelled. Every `[testbed]` table refuses what it does not know. | Fix the key. |
| `testbed.id is no longer supported` style messages for `testbed_id` and `testbed.metric` | The retired spellings are refused. | Write `id` and `[[testbed.metrics]]`. |
| `Duplicate testbed.case id 'dem_area_00001_30m'` | Two cases with the same id, in the same testbed or across two rules. The comparison ignores case. | Give each rule its own `id_template`. |
| `testbed.case_from_catalog[...].overlay.geographic.catchment.x_outlet references unknown catalog field 'xx'` or `testbed catalog row is missing required field(s): zz` | A placeholder is not a column of the catalog, or a required column is missing. | Fix the placeholder, or the catalog. |
| `Missing file: testbed catalog path not found: <folder>/nofile.csv` or `Missing file: [Errno 2] No such file or directory: '<folder>/nope.toml'` | The catalog or the base file does not exist. `hmp run` finds it, `hmp config check` does not. | Check the paths. |
| `testbed did not expand any case` | The tags filter of the catalog leaves no row. | Check the tags of the rows. |
| `Required testbed metric 'max_abs_balance_error' could not be found at source 'flow_metrics.max_abs_mass_balance_percent_error'.` in the `error` column of a failed case, after `ValueError: ` | A required metric the summary does not hold, usually a typo in the source. `flow_metrics` exists for the `simulation` runner only. When the run of a child cannot be reopened, the summary has a `catalog_extraction_error` key instead. | Fix the source, or use a source of the runner. |
| `Comparison child 'moderate' failed: hmp run exited with code 15` then `SolverDivergedError: [HMPY.E401] Flow solver 'modflow6' failed ...` in the `error` column | A child of a comparison did not converge at that site. The case fails, and the other sites go on. | Read `mfsim.lst` in the workspace of the child under `comparisons/<site>/workspaces/<id>`. |
| `Point observable '<name>' needs a mesh bundle cells.csv for x/y lookup, or a cell_index.` | A `point` observable given by `x` and `y` on a structured grid. | Declare a `map` observable, or a `cell_index`. |
| `StepError: step 'build_geographic' failed: EmptyCatchmentError: Outlet 'outlet' delineated an empty catchment. Check geographic.catchment.x_outlet / y_outlet, ...` in the `error` column | The outlet of a row is outside the DEM or on no stream. | Check the coordinates and the CRS of the catalog. |
| The run ends with exit code 23, and `testbed '<id>': <n> of <m> case(s) failed: <ids>. Read <folder>/testbed_report.md.` | A case failed. Every table was written first. | Read the `error` column of `testbed_cases.csv`. To see the error of a child without the testbed, run its generated file by hand with `hmp run <child file>`. |
| `[WARNING] Skipping testbed field metrics: field 'outflow_drain' is not in the store. ...` | A field metric needs a derived field the run did not write. | Set `[simulation.results.derived] outflow_drain = true` in the overlay. |

## Next

- Plan and record a whole campaign over child files you already have: {doc}`regional-lab`.
- Run the cases of a comparison and read their audit: {doc}`compare-runs`.
- Find the runs of a testbed in the catalog, compare and delete them:
  {doc}`find-and-compare-runs`.
- Choose the catchments of a campaign: {doc}`select-catchments`.
- How a file inherits another and how lists of tables merge: {doc}`inheritance`.
- Search a parameter on one catchment: {doc}`calibrate`.
- Every key of the testbed: {toml}`testbed`.
