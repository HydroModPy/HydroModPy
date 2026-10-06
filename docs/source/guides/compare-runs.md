# Compare runs and methods

You have one physical case and two or more ways to solve it: another solver, another
solver option, another value of one parameter. A comparison file takes one base simulation
file, builds one child simulation per method, runs each child with `hmp run`, and reads
the stored results. It writes an audit, metrics against a reference child, figures and a
report in one folder.

Use it when the case is fixed and the method changes. It does not check a run against an
analytical solution or a trusted reference. That is validation, and the comparison does
not replace it. To compare two runs that already exist, see
{doc}`find-compare-and-clean-runs`.

## What you need first

- A simulation file that runs, with exactly one `flow` process. The blocks below use
  `step4_transient.toml` of example 04. Its first period is solved steady and gives the
  initial heads.
- The solver executables of the methods you compare. `hmp doctor` lists the ones it finds.
- Time. Each child is a full run. Two children on example 04 cost two runs of
  `step4_transient.toml`, one after the other.

A comparison file is not a project file. It is read by its own schema, and
`hmp config check` picks that schema from {toml}`workflow.mode`. Its tables are written
`[comparison]`, `[[comparison.simulation]]` and `[[comparison.observable]]`. The generated
reference lists the same keys under `analysis.comparison`, and the links below point
there. Put the file next to the base file, in the example 04 folder, so that relative
paths resolve.

The worked case compares two settings of the MODFLOW 6 solver, `COMPLEX` and `MODERATE`,
on the Nançon catchment. The physical case does not change, so a difference in the results
comes from the method.

## 1. Name the base case and the reference

Start the file with the workflow mode and the base simulation.

```toml
# not checked: comparison file
[workflow]
mode = "comparison"

[comparison]
comparison_id = "nancon_ims"
base_simulation_config = "step4_transient.toml"
reference_simulation = "complex"
```

```{hmp-params}
workflow.mode
analysis.comparison.comparison_id
analysis.comparison.base_simulation_config
analysis.comparison.reference_simulation
analysis.comparison.output_root
```

- Relative paths resolve against the folder of the comparison file.
- When {toml}`comparison_id|analysis.comparison.comparison_id` is not set, the name of the
  file without `.toml` is used.
- The results go to `comparison/<comparison_id>` next to the file, unless
  {toml}`output_root|analysis.comparison.output_root` says otherwise.
- Every difference is a difference to the reference child. When
  {toml}`reference_simulation|analysis.comparison.reference_simulation` is not set, the
  first child that completed is the reference. It must name an enabled child.

## 2. Declare the children

One `[[comparison.simulation]]` block per method. The `id` of a child is the key you use in
the rest of the file.

```toml
# not checked: comparison file
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
```

```{hmp-params}
analysis.comparison.simulation.id
analysis.comparison.simulation.label
analysis.comparison.simulation.solver
analysis.comparison.simulation.overlay
analysis.comparison.simulation.enabled
```

A child is built in three layers, each merged on the previous one: the base simulation
file, the table {toml}`base_simulation_overlay|analysis.comparison.base_simulation_overlay`
shared by every child, then the {toml}`overlay|analysis.comparison.simulation.overlay` of
the child. Put in the shared overlay what the whole case needs, such as a path or an
outlet. Put in the child overlay what makes the method differ.

{toml}`solver|analysis.comparison.simulation.solver` replaces the solver name of the single
`flow` process of the base file. The overlay of the example above leaves it as it is and
changes one option of the solver. {toml}`mf6_ims_complexity|modflow6.runtime.mf6_ims_complexity`
is the key it sets.

For a child that must run another solver, name the solver and write the same name in
{toml}`solver.backend`, as {doc}`choose-a-solver` explains for a normal file.

```toml
# not checked: comparison file
[[comparison.simulation]]
id = "nwt"
label = "MODFLOW-NWT"
solver = "modflow_nwt"

[comparison.simulation.overlay.solver]
backend = { backend = "modflow_nwt" }
```

An overlay can reach the solver and numerical sections (`modflow6`, `modflownwt`,
`solver`), the mesh sections, `simulation` (name, tags, description, `if_exists`, process,
results), `workspace`, `display`, and the `bc`, `ic` and `param` tables of `flow` with a
few of its runtime selectors. It cannot reach `domain`, `data`, `geographic`, the time
window or the recharge of `flow.sinks_sources`. A child file that changes those would not
be the same case. A file that lists one of them is refused when the comparison starts.

Each child is named `<comparison_id>__<id>` and lives in its own folder,
`workspaces/<id>` under the comparison folder, with its own project and its own results.
Its {toml}`simulation.if_exists` is `"replace"` unless the overlay says otherwise, so a
second comparison replaces the first run of the same child.

## 3. Declare what to compare

One `[[comparison.observable]]` block per quantity. At least one is required, and the
names must be unique.

```toml
# not checked: comparison file
[[comparison.observable]]
name = "head_last"
variable = "watertable_elevation"
support = "map"
time = "last"
unit = "m"

[[comparison.observable]]
name = "head_outlet"
variable = "watertable_elevation"
support = "point"
x = 389285.910
y = 6816518.749
time = "all"
unit = "m"
```

The point is the outlet of example 04. These are its coordinates:

```{hmp-resolved} geographic.catchment.x_outlet
:config: step4_transient.toml
```

```{hmp-resolved} geographic.catchment.y_outlet
:config: step4_transient.toml
```

```{hmp-params}
analysis.comparison.observable.name
analysis.comparison.observable.variable
analysis.comparison.observable.support
analysis.comparison.observable.x
analysis.comparison.observable.y
analysis.comparison.observable.cell_index
analysis.comparison.observable.time
analysis.comparison.observable.simulations
analysis.comparison.observable.unit
```

- A `point` needs `x` and `y`, an `anchor_id` or a `cell_index`. An `outlet` needs one of
  them too. A `map` keeps the whole field.
- A point series is cheap to read. A map is richer and needs the children to share a
  support. When the children use different meshes, add a common raster:
  {toml}`enabled|analysis.comparison.fine_raster.enabled` with a
  {toml}`resolution|analysis.comparison.fine_raster.resolution`.
- Only one map observable gets a figure: `head_map_last` when you declare it, else the
  first map you declare. The figure is written only when the fine raster is on.
- With {toml}`simulations|analysis.comparison.observable.simulations` an observable applies
  to a subset of the children.

## 4. Choose what the audit does

Before it trusts a difference, the audit asks whether the children still describe one
case. It compares each child with the reference on the mesh and time metadata, on the
persisted parameter tables, on the recharge budget totals, and on the physical sections of
the resolved file: the time window, the geographic and domain sections, the meshes, the
recharge data, and the flow regime, sources, boundaries, parameters and initial
conditions.

```{hmp-params}
analysis.comparison.audit.mode
analysis.comparison.audit.on_mismatch
```

With the default, a difference stops the command after every output is written. To
compare a parameter on purpose, you change `flow.param` in an overlay, the audit sees it,
and you tell it the difference is wanted. Here K of example 04 is the base value in one
child and lower in the other:

```{hmp-resolved} flow.param.K.field.value
:config: step4_transient.toml
```

```toml
# not checked: comparison file
[comparison.audit]
on_mismatch = "warn"

[[comparison.simulation]]
id = "k_ref"
solver = "modflow6"

[[comparison.simulation]]
id = "k_low"
solver = "modflow6"

[comparison.simulation.overlay.flow.param.K.field]
value = 2e-5
```

The audit then reports the section `flow.param` as a warning, and the status of the audit
is `warn` instead of `fail`. Mixing a method change and a parameter change in one
comparison makes the result hard to read. Change one thing per child.

## 5. Check the file

```bash
hmp config check compare_ims.toml
```

It prints `OK: <path>` when the file loads. It checks the comparison schema, the existence
of the base file and the links between ids. It does not check the overlays: a forbidden
section of an overlay is found only when the comparison starts, and the base file is
loaded only when the children are built.

## 6. Run it

```bash
hmp run compare_ims.toml
```

The command builds the child files in `_generated_configs/` under the comparison folder.
It runs them one after the other, each as a separate `hmp run`. It then extracts the
observables, writes the audit and the outputs, and prints
`Workflow 'comparison' complete: compare_ims.toml` followed by the keys of the manifest.
From Python, `hmp.run("compare_ims.toml")` returns the same manifest as a dictionary, see
{doc}`drive-from-python`.

```{hmp-params}
analysis.comparison.continue_on_error
analysis.comparison.execution.run_simulations
analysis.comparison.execution.keep_generated_configs
analysis.comparison.execution.timeout_seconds
analysis.comparison.execution.max_parallel_runs
```

- {toml}`continue_on_error|analysis.comparison.continue_on_error` decides what a failed
  child does. Stopped, the comparison ends at the first failure and writes no output. Kept
  going, the failed child is left out of the metrics.
- `max_parallel_runs` can only be 1.
- {toml}`run_simulations|analysis.comparison.execution.run_simulations` set to `false`
  solves nothing and reads the results of children that already ran. Use it after a
  comparison to change an observable, the reference or the audit without paying for the
  solves again. Do not change an overlay with it: the children keep the results they had.

## 7. Read the outputs

Everything is under the comparison folder. Read in this order. Figures come late on
purpose: an impressive difference map means little before you know that the children share
one case.

1. `comparison_audit.md`, or `comparison_audit.json` for the same content in full. The
   status is `pass`, `warn` or `fail`. It lists each issue with its kind and the child it
   concerns.
2. `web/index.html`. It is the reading page of the comparison: it links the audit, the
   metrics, the figures and the tables below. The files stay the source, the page only
   shows them. Its text is in French at this version.
3. `comparison_report.md`. It starts with the audit status, then lists the reference,
   the other children and the observables.
4. `comparison_figures/case_configuration.png`. The case itself: support, boundaries,
   observable points and forcing. It is not a result.
5. `comparison_metrics.csv`, one row per child and observable. See the table below.
6. The other figures of `comparison_figures/`: one `<observable>__timeseries.png` for each
   observable that is not a map, `<observable>__fine_raster_map_comparison.png` for the
   map when the fine raster is on, `storage_comparison_dashboard.png` and
   `total_inputs_outputs_dashboard.png`.
7. `comparison_differences.csv`: the same errors one value at a time, to find where a
   difference sits. `observables.csv` holds the values themselves.
8. The budget tables, `budget_timeseries_long.csv` and `budget_timeseries_wide.csv`, and
   `numerical_closure_summary.csv`. Read them before you interpret a head difference.
9. `hydrographic_network_metrics.csv` and the `simulated_active_network_*.csv` files, when
   the runs carry the stream networks they need. When a child lacks one, a file with the
   same name and the ending `_skipped.json` says why.
10. The child folders, only when a metric needs explaining. The comparison folder holds
    the evidence, the child folders hold the diagnosis.
11. `comparison_manifest.json`: the index of every file above, the generated child files
    and the child folders. Keep it for traceability.

### The metrics

The error of a value is the value of the child minus the value of the reference.

| Column | What it tells you | What it does not tell you |
|---|---|---|
| `bias` | The mean signed error: one systematic offset. | A small bias does not mean the fields agree everywhere. |
| `mae` | The typical absolute error. | It can hide a few large local errors. |
| `rmse` | The same, with large errors weighted more. | It does not say where they are. |
| `max_abs_error` | The worst single error. | One peak does not make the whole field poor. |
| `*_normalized_percent` | An error as a percent of the range of the reference. When the range is zero, of its mean absolute value. | A percent of a small range can look large. |
| `mean_relative_error` | The mean of error over the reference value. | It is undefined where the reference is zero. |

### The time columns

The tables carry a `time_role` column. Read it before you compare two rows.

- `initial_state` is the state before the first period.
- `state_snapshot` is an instantaneous state such as a head.
- `period_value` is a value over an interval, such as a flux or a budget component. Its
  `elapsed_seconds` is the end of the period. The budget tables also carry `period_index`,
  `period_start_seconds` and `period_end_seconds`.
- `reduced` is a statistic of several rows.

### The outflow

Drainage and surface excess are not interchangeable between solvers: the same water can
leave through either, depending on how a solver counts it. The budget tables add the
component `comparable_outflow_total_m3_s`, which is `drainage_total_m3_s` plus
`surface_excess_total_m3_s`, a missing term counted as zero. Use it to ask how much water
leaves the aquifer. Keep the native components to ask which mechanism carried it.

## What can go wrong

Messages of `hmp config check`:

- `comparison.reference_simulation must match an enabled simulation id`: the reference is
  not the `id` of an enabled child.
- `comparison.simulation.solver is required unless simulation_config or run_folder is
  provided`: a child names no solver.
- `point observables require x/y coordinates, anchor_id, or cell_index`: a point has no
  location. An outlet gives a similar message.
- `comparison.base_simulation_config not found: <path>`: the path did not resolve against
  the folder of the comparison file.
- `comparison.execution.max_parallel_runs must be 1 in V1`.
- `comparison.simulation ids must be unique` and `comparison.observable names must be
  unique`.

Messages when the comparison runs:

- `comparison.simulation.overlay contains forbidden sections: domain`: the overlay of a
  child reaches a section it may not change. A key of `flow` that is not allowed gives
  `comparison.simulation.overlay.flow contains forbidden keys: <keys>`.
- `Cannot generate child process overlay: base_simulation_config must declare exactly one
  flow process.`: the base file has no `flow` process, or has several. Declare one, or give
  each child its own `simulation_config`.
- `Comparison child '<id>' failed: hmp run exited with code <n>`, followed by the end of
  the error output of the child. The child ran as a normal `hmp run`, so its message is
  the one to read, for instance in {doc}`non-convergence`. The failed child solved
  nothing that the comparison can use.
- `Comparison audit failed. See <path> for equivalence diagnostics.` The outputs are
  already written. Open `comparison_audit.md`. Either the case differs between children,
  and you fix the overlay, or the difference is wanted, and you set
  {toml}`on_mismatch|analysis.comparison.audit.on_mismatch` to `"warn"`. The value
  `"ignore"` does not hide the issue: the code records it as a warning like `"warn"`.
- `Could not find variable '<name>' in Catalog sim_id=<id>. Tried variables: ...`: the
  children ran, but a run did not store the variable of an observable. The comparison ends
  before any output. Fix the `variable`, then run again with `run_simulations = false` to
  skip the solves.
- `Time selector <value> not found for variable '<name>'`: the {toml}`time|analysis.comparison.observable.time`
  of an observable does not exist in the series of a child. The same remedy applies.
- `No completed reference simulation is available for audit.` is an issue in the audit.
  The reference child failed or was not run.

Two cases do not stop anything and are easy to miss:

- When one child exposes the initial state and another starts at its first computed step,
  and the observable asks for `first` or `initial`, the audit warns with the kind
  `initial_state_policy_mismatch`. The two rows are not the same instant.
- The web page can fail to render. The comparison then goes on, and
  `comparison_manifest.json` holds the reason under `comparison_web_report_error`.

## Where to go next

- {doc}`choose-a-solver` for what each solver supports, before you build a solver child.
- {doc}`../theory/mf6-vs-nwt` for what separates MODFLOW 6 and MODFLOW-NWT.
- {doc}`non-convergence` when a child fails to converge.
- {doc}`test-a-method` to run a method on many catchments.
- {doc}`find-compare-and-clean-runs` to compare runs that already exist.
- {doc}`../reference/parameters/analysis/comparison` for every key of the comparison file.
