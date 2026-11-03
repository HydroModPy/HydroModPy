# Many catchments

A model tuned on one catchment runs on a hundred with the same project. The project keeps
its configuration, swaps `[site]` for `[sites]` and a table with one row per catchment, and
lists its recipes: the variants run on every site. The plan is every site crossed with
every recipe, and each pair is a case named `<site>-<recipe>`, with its own folder under
`runs/`.

This page walks through that project: declare the sites, check the plan, run it, follow it,
rerun what failed, and read the summary. {doc}`cluster` runs the same plan on a Slurm
cluster.

## Declare the sites

Start from the `project.toml` you tuned on one catchment. Remove `[site]`, then add
`[sites]`: the table of sites, the recipes, and which columns of the table fill which keys.

```toml
# not checked: a [sites] project has no [site], so it does not load on top of example 04
[sites]
table = "sites.csv"
enabled = "enabled"
overrides = "site_overrides/"

[sites.recipes]
base = "project.toml"
k2e_5 = { file = "project.toml", set = { "flow.param.K.field.value" = 2e-5 } }
calibration = "calibration.toml"

[sites.bind]
"site.name" = "site"
"site.label" = "label"
"site.gauge" = "gauge"
"geographic.catchment.x_outlet" = "x_outlet"
"geographic.catchment.y_outlet" = "y_outlet"
```

```text
site,label,gauge,x_outlet,y_outlet,enabled
J0014010,Nancon at Lecousse,J0014010,389285.910,6816518.749,true
J0170000,Couesnon at Romazy,J0170000,377120.000,6831410.000,false
```

- {toml}`sites.table` is a CSV, Parquet or GeoPackage file, read from the project root. Its
  columns are yours. Without a table, the plan reads `data/sites/catalog.csv` of the
  workspace, which `hmp site add` and `hmp site import` fill, and whose fixed columns
  (`site`, `label`, `gauge`, `uri`, `x_outlet`, `y_outlet`, `crs`, `tags`) need no `bind`.
- {toml}`sites.bind` maps a key of the configuration to a column. The key is written
  between quotes, in the grammar of `hmp run --set`; unquoted, TOML would read it as a
  nested table, and the file is refused. The cell is read by the type of the key it fills,
  and an empty cell leaves the key unbound.
- {toml}`sites.recipes` names each recipe: a file, or an inline table that changes a few
  keys of a file. A recipe name is letters, digits and underscores, because `-` separates
  the site from the recipe in the name of a case. {toml}`sites.recipes_table` reads the
  recipes from a CSV instead, one row per recipe.
- {toml}`sites.enabled`, {toml}`sites.include` and {toml}`sites.exclude` choose the sites
  of the plan without editing the table.
- {toml}`sites.overrides` is a folder of ordinary TOML files, one per site that needs a
  change of its own, such as a wider snapping distance for one outlet.

A key whose value depends on the catchment is marked *varies by site* in the
{doc}`reference <../reference/parameters/index>`: the outlet, the gauge, the paths of
custom data. The plan refuses a project where one of these keys keeps a literal value with
no `bind` and no override, and lists the keys: otherwise every catchment would run with the
outlet of the first one.

The value of a key in a case comes from, the last one winning: the defaults,
`project.toml`, the bound cells, `site_overrides/<site>.toml`, the keys the recipe file
writes itself, then `--set` on the command line. A recipe beats the table on the keys it
writes: `k2e_5` sets K on every site, which is what its name says.

A calibration is a recipe like any other. `calibration.toml` writes
`base_config = "project.toml"`, its `[calibration]` and, if the bounds vary by site, its
own `[sites.bind]` lines, which hold for that recipe only.

## Check the plan

```bash
hmp config check project.toml
hmp run project.toml --dry-run
```

`hmp config check` resolves every case and reports every error once, with the row and the
column it comes from: `sites.csv:37 column x_outlet -> geographic.catchment.x_outlet:
<message>`. The same error on many cases is one line, `100 cases: ...`. `--dry-run` writes
nothing. It counts the cases, the solves and the peak of solves running together, and
estimates the scratch space.

`hmp project plan .` writes the plan under `plan/<hash>/`: one resolved TOML file per case,
which replays alone from any folder, and the tables of the sites and the cases. A plan is
never rewritten in place: an edited table or recipe makes a new hash, and `plan/current`
names the plan in force. `hmp run` writes the plan itself when the current one is out of
date.

## Run it

```bash
hmp run project.toml
hmp run calibration.toml
```

The first command runs every case of the plan, the second the recipe file `calibration.toml`
on every site. Each case runs in its own process, as `hmp run plan/<hash>/<case>.toml`. Before the solves, a
`prepare` phase fetches the data of every case. The cases only read the input cache of the
workspace: what each one downloads goes to a private cache that the launcher merges into the
shared one, so the cases never compete for it.

{toml}`sites.run.parallel` is the number of solves that run side by side. A calibration
case that solves five trials at once counts for five, at its widest phase, and a case wider
than {toml}`sites.run.parallel` is refused without `--force`. {toml}`sites.run.on_error` says
whether a failed case stops the launch or lets the others go on.

## Follow it

```bash
hmp project status .
hmp project log . --failed
```

`hmp project status` reads the `outcome.json` and the heartbeat of each case, never the
index, and counts the cases by state: planned, running, completed, failed, and stale when a
heartbeat is old. `hmp project log . --failed` prints the error of each failed case, one
line each. The full log of a case is in `runs/<case>/logs/`.

## Rerun what failed

```bash
hmp run project.toml --only failed
hmp run project.toml --only failed --fresh
hmp run project.toml --only stale --force
```

A failed case keeps its folder. `--only failed` starts a new attempt in place: the earlier
attempt moves under `runs/<case>/attempts/<n>/`, and the new one resumes from what the
first one left. A calibration reopens its session `sessions/<case>/` and keeps its
trials. `--fresh` files the whole earlier attempt away and starts over; for a calibration
it opens a new session, `sessions/<case>.v2/`. A case whose heartbeat is old may still be
running on another machine, so a stale case is only rerun with `--force`, when you know
its process is dead. Without `--fresh`, a rerun never makes a `.v2`: a version is for a
changed configuration, not for a second try.

## Read the results

```bash
hmp campaign collect .
hmp catalog ls --by site --best nse
hmp report compare J0014010-base J0014010-k2e_5
hmp publish . --to /srv/deliverables/my_project
```

`hmp campaign collect` writes `summary/`: `by_case` with one row per case, `by_site` with
the best case of each site, a map of the sites as a GeoPackage, the cohort figures, the
exports of each `[[sites.export]]` block, a report and a dated `README.md`. It is
regenerated from the runs each time. {toml}`sites.summary` chooses the metrics, the
parameters and the figures, and {toml}`sites.summary.best` which case of a site counts as
its best: by default, a calibrated one.

The scores of a summary are those of the metric rule of each run: the gauge of the site and
the window of {toml}`metrics.window`. `collect` refuses to rank cases scored on different
windows unless you pass `--mixed-windows`, because their scores do not compare. Beside
them, the objective of each calibration sits in its own columns, under its own name.

`hmp publish .` copies the project out of the tree, one folder per site and the summary,
each with its `README.md` and its `PUBLICATION.json`.

Example 19 (`examples/projects/19_many_catchments`) is a small project of this shape on catchments of
Brittany, with a simulation recipe and a short calibration.
