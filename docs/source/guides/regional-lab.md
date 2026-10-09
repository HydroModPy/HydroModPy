# Run a regional lab

You have one child file for each catchment and each way of building the model, and you want
one plan and one report for the whole campaign. The `regional_lab` profile of the testbed reads
a catalog of sites and a list of recipes, plans one case for each site and recipe, runs them one
after the other, and records what it planned, skipped, reused and failed. It does not write the
child files: you do, or a script does. To make the child files from one base file and a table
of catchments, use the generic testbed of {doc}`test-a-method`.

```{hmp-task}
Task
: Plan and run a campaign of simulation or comparison files over many sites, and read what it did.

Time
: Planning takes seconds. A run costs the sum of its child runs: the five steady children of this page took 11 to 15 s each, 55 s in all with the site that failed once; a second run took 18 s, as it read four of them back.

Needs
: One child file for each site and recipe, and a catalog of sites in CSV or JSONL. The solver executables (`hmp doctor`).

Gives
: A plan, a case matrix, tables by recipe, cluster and region, and a report that lets a second run skip what is done.
```

## What you need first

- The child files, one for each site and recipe. Each one is a normal simulation file, or a
  comparison file. Step 1 shows one.
- A catalog of sites: the output of {doc}`select-catchments` (`regional_lab_sites.csv`) or a table
  of your own. Step 2 gives its columns.
- A shell in the folder that holds the campaign file, so that relative paths resolve.

The campaign file is a testbed file. `hmp config check` reads it with its own schema, chosen by
{toml}`workflow.mode` and {toml}`testbed.profile`.

```{hmp-params}
workflow.mode
testbed.profile
```

## 1. Write the child files

One file for each site. It sits in a subfolder here, so it states its project folder: without that
line the folder of the child becomes the project, and the DEM is not found.

```toml
base_config = "../step1_minimal.toml"

[workspace]
project_root = ".."

[simulation]
name = "dem_area_00004_regional"

[geographic.catchment]
x_outlet = 375075.0
y_outlet = 6810750.0
```

Save it as `children/dem_area_00004.toml`, and write the others the same way. A script can write
them from your catalog. For this page the files of the sites 1 to 4 exist, and the site 5 has none.

## 2. Write the campaign file

The catalog describes sites. It is not a model file. The columns below are the defaults; a
column with another name is declared in {toml}`catalog|analysis.batch.catalog`. The file
`regional_lab_sites.csv` of a site selection has them all but `cluster_id`, which is optional.

```text
site_id,site_label,region_id,cluster_id,enabled,x,y,tags
dem_area_00001,dem_area_00001,,headwater,true,382950.0,6820500.0,site_selection
dem_area_00002,dem_area_00002,,headwater,true,375600.0,6826725.0,site_selection
dem_area_00003,dem_area_00003,,headwater,true,396000.0,6825150.0,site_selection
dem_area_00004,dem_area_00004,,regional,true,375075.0,6810750.0,site_selection
dem_area_00005,dem_area_00005,,regional,true,385875.0,6805800.0,site_selection
```

```toml
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
tags = ["site_selection"]

[[regional_lab.recipe]]
id = "steady_mf6"
label = "Steady MODFLOW 6"
launcher = "simulation"
config_path_template = "children/{site_id}.toml"
```

The reference lists the keys of the table `[regional_lab]` under `analysis.batch`: the two names
are one model, and the links below point there. In a testbed file you write `[regional_lab]`,
because `hmp run` reads that name. A testbed file with the same keys under `[analysis.batch]`
is refused.

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

## 3. Plan, then run

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

With the five sites above and the files of steps 1 and 2 written for the first four only, the
plan took 4.5 s. It selects five sites, plans four cases and skips one:

```text
Workflow 'testbed' complete: regional.toml
  lab_id: headwaters
  selected_site_count: 5
  planned_case_count: 4
  skipped_case_count: 1
  executed_case_count: 0
  ...
```

`regional_lab_summary.md` lists the gap with its reason:

```text
## Coverage Gaps

- `steady_mf6` / `dem_area_00005`: missing_config_path (Resolved child config is missing: <folder>/children/dem_area_00005.toml)
```


When the plan is right, set `execute = true`. The cases run in order, each through the
launcher of its recipe, and every table is rewritten after each case.

- A case is `ok` or `failed`. The report keeps no message for a failed case: run the child
  file by hand, for example `hmp run children/dem_area_00004.toml`, to read the error.
- A second run skips the cases that the previous report marks as completed, and lists them
  with the status `skipped_existing_ok`. Both
  {toml}`resume_from_report|analysis.batch.resume_from_report` and
  {toml}`skip_completed_cases|analysis.batch.skip_completed_cases` must be true. A failed
  case is tried again.
- When a case failed, `hmp run` writes every table, then ends with the exit code 23
  (`FailedCasesError`). With {toml}`continue_on_error|analysis.batch.continue_on_error` false, the
  loop stops after the first failed case and the command ends the same way.

## 4. Read the files it writes

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

With `execute = true` and an outlet of the fifth child outside the DEM, the run took 55 s: four
cases `ok` (11 to 13 s each) and one `failed`. It ended with the exit code 23 after writing every
table, and printed:

```text
regional lab 'headwaters': 1 of 5 case(s) failed: steady_mf6::dem_area_00005. Read outputs/headwaters_run/regional_lab_report.json.
```

`all_passed` is false in the report. The matrix gives the status and the duration of the case and no
message: its `reason` and `detail` columns are empty for a failure. Run
`hmp run children/dem_area_00005.toml` to read the error. After the fix, the second run took 18 s:

```text
  selected_site_count: 5
  planned_case_count: 5
  skipped_case_count: 0
  executed_case_count: 1
  reused_case_count: 4
  failed_case_count: 0
```

The four cases that completed are `skipped_existing_ok`, with `reused_from_report` true, and
`all_passed` is true.

The profile does not read metrics from the runs. To compare the results of the sites, open
the runs from the catalog of each project, as in {doc}`find-and-compare-runs`, or run the
generic testbed of {doc}`test-a-method`, which reads metrics from each child.

## Share the terrain work between sites

When the children of a campaign use one DEM, {toml}`share_regional_flow|analysis.batch.share_regional_flow`
does the terrain analysis once. It applies when `execute` is true. It accepts simulation
recipes with an outlet catchment and a DEM path, and refuses lake enforcement and river
network extraction. The launcher writes the shared job in `regional_flow_jobs/` and one
child file per case in `materialized_configs/`. A refusal names the case, for example
`<case id>: shared flow requires an outlet catchment`.

## What can go wrong

The message that `hmp config check` or `hmp run` prints is quoted. The folder part of a
path is replaced by `<folder>`.

| Symptom | Cause | Fix |
|---|---|---|
| `Config invalid: <folder>/regional.toml` then `exceute: Extra inputs are not permitted (input=False)` (exit 14) | A key is misspelled. The lab refuses what it does not know. | Fix the key. |
| `regional_lab selection did not match any site` | The filters of `[regional_lab.selection]` leave no site. | Loosen a filter, or check the tags of the catalog. |
| `regional_lab.recipe[steady_mf6] references unknown template key 'site'` | The template of a recipe names a column the catalog does not have. | Use a column of the catalog, or `site_id`, or `lab_id`. |
| `Missing file: regional_lab.catalog.path not found: <folder>/nocatalog.csv` (exit 10) | The catalog does not exist. | Check the path. |
| `recipes.0.launcher: Value error, Unsupported regional_lab.recipe launcher 'calibration'. Use 'simulation' or 'comparison'.` | A recipe asks for a launcher the lab does not have. | Use `simulation` or `comparison`. |
| `Section [regional_lab] is not a HydroModPyConfig section. Use [analysis.batch] for regional-lab testbed settings.` | A `[regional_lab]` table sits in a project file. | Keep the table in a testbed file, with `[testbed] profile = "regional_lab"`. In a project file the section is `[analysis.batch]`. |
| `skipped_missing_config_path` in the matrix, and `Resolved child config is missing: <folder>/children/<site>.toml` in the coverage gaps | The child file of the template does not exist. | Write the file, or set `validate_config_paths = false` to plan anyway. |
| `regional lab '<id>': 1 of 5 case(s) failed: steady_mf6::dem_area_00005. Read <folder>/regional_lab_report.json.` (exit 23) | A case failed, and every table was written first. With `continue_on_error = false` the loop stops at the first failure: the cases after it stay `planned`, and the message counts the cases of the loop (`1 of 1`). | Read the `failed` rows of `regional_lab_case_matrix.csv`, then run the child file by hand: the matrix keeps no message. |
| `<case id>: shared flow requires an outlet catchment` | `share_regional_flow` met a recipe it does not accept. | Switch it off for that recipe, or use an outlet catchment and a DEM path. |

## Next

- Make the child files from one base file and a table of catchments: {doc}`test-a-method`.
- Choose the catchments of a campaign: {doc}`select-catchments`.
- Find the runs of a campaign in the catalog and compare them: {doc}`find-and-compare-runs`;
  delete them: {doc}`clean-and-reindex-runs`.
- Every key of the profile: {toml}`analysis.batch`.
