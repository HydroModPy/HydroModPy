# Read a value at a point

You want the value of one variable at one place of the model, for example the head or the
depth of the water table at a piezometer. You get a table with one row per time step. There
are two ways to get it. You can ask a finished run, at any place, after the fact. Or you can
declare the place in the project file, so that every run records it as it finishes.

| | Ask a finished run | Declare the point in the file |
|---|---|---|
| When | Any time after the run | Before the run, in the project file |
| Place | Any place, chosen afterwards | A place you know in advance |
| Entry point | `hmp catalog point`, `run.probe.series` | {toml}`observation.points` |
| Result | A table printed or written to a file | A series stored with the run |

Both read the same mesh and give the same number.

## What you need first

- A completed run in a project catalog. Example 04 gives one:
  `hmp run step4_transient.toml`, from its folder.
- The place, as coordinates in the project CRS or as a cell index. Example 04 works in
  `EPSG:2154`, in metres. The block below uses the outlet of its catchment,
  {toml}`x_outlet|geographic.catchment.x_outlet` and
  {toml}`y_outlet|geographic.catchment.y_outlet`.
- The name of the variable. The run keeps its own list, shown in step 1.

Both ways cover persisted fields, such as `head`, and fields rebuilt when you read them,
such as `watertable_depth`. They give the same table.

## 1. Ask a finished run

### From the command line

```bash
hmp catalog point @last --var head --xy 389285.910 6816518.749
```

`@last` is the newest completed run. A run is also named by its name, by its `sim_id` or
by a unique prefix of it. `hmp catalog ls` lists them. Run the command from the project
folder, or give the folder with `-w`.

The place is one of two options, never both:

- `--xy X Y` gives coordinates in the project CRS. The command finds the cell that holds
  them.
- `--cell N` gives the zero-based index of a cell.

The layer is optional, and one of two options:

- `--layer N` is a zero-based layer index. A negative number counts from the bottom.
- `--depth METRES` is a depth below the local model top. The command picks the layer that
  holds it, from the layer thicknesses at that cell. A depth below the bottom of the model
  gives the bottom layer.

Without either, a field that has layers is read in layer 0, the top one.

`--var` repeats for several fields, and `--timestep N` keeps one step (a negative number
counts from the end). `--label` names the point in the table.

```bash
# the depth of the water table, last step only
hmp catalog point @last --var watertable_depth --cell 5000 --timestep -1

# two variables at once, written to a file
hmp catalog point @last --var head --var watertable_depth \
    --xy 389285.910 6816518.749 -o outlet.csv
```

The table goes to the screen. `--format` picks `table`, `json` or `csv`. `-o FILE` also
writes a `.csv` or a `.parquet` file. Any other extension is refused.

Several runs stack their answers in one table, for comparison. The coordinates are resolved
on each run, because two runs rarely share a mesh:

```bash
hmp catalog point run_a run_b --var head --cell 5000
```

### From Python

`run.probe.series` does the same. `hmp.open` takes the project folder:

```python
import hydromodpy as hmp

cat = hmp.open(".")
run = cat.latest()

run.array.list_fields()    # the fields you can ask for

table = run.probe.series("head", x=389285.910, y=6816518.749)
table = run.probe.series("watertable_depth", cell=5000, timestep=-1)
table = run.probe.series(["head", "watertable_depth"], cell=5000, depth=12.5)
```

The arguments are the options above: `x` and `y` or `cell`, then `layer` or `depth`,
`label`, `timestep`, and `output` for a `.csv` or `.parquet` file.

A set of runs has the same `probe`:

```python
group = cat.find(solver="modflow6")
table = group.probe.series("head", x=389285.910, y=6816518.749, output="head.parquet")
```

### The table

The answer is a `pandas.DataFrame` in long format, with one row per time step, variable
and run.

| Column | Meaning |
|---|---|
| `run`, `sim_id` | The run the row comes from |
| `variable`, `unit` | The field and its registered unit |
| `timestep`, `time` | The step index and its date. `NaT` when the run has no calendar axis |
| `value` | The number |
| `cell`, `layer` | The cell and the layer actually read. `layer` is `<NA>` when the stored field has no layer axis, as `watertable_depth` |
| `x`, `y` | The coordinates you gave, or the centre of the cell when you gave `cell` |

A steady run has one row per variable.

## 2. Declare the point in the file

When you read the same place on every run, declare it. The run samples it when it
finishes, while it holds its own fields. Reading it afterwards is a plain table read.

```toml
base_config = "step4_transient.toml"

[observation]
variables = ["head", "watertable_depth"]

[[observation.points]]
id = "outlet"
x = 389285.910
y = 6816518.749
```

{toml}`observation.variables` is the list read at every point that names none of its own.
Each entry of {toml}`observation.points` needs an {toml}`id|observation.points.id` that is
unique in the file, and {toml}`x|observation.points.x` and {toml}`y|observation.points.y`
in the project CRS.

```{hmp-params}
observation.variables
observation.points
observation.points.id
observation.points.x
observation.points.y
```

A point can choose its layer, or its own variables:

```toml
base_config = "step4_transient.toml"

[observation]
variables = ["head", "watertable_depth"]

[[observation.points]]
id = "outlet"
x = 389285.910
y = 6816518.749
depth = 12.5

[[observation.points]]
id = "top_layer"
x = 389285.910
y = 6816518.749
layer = 0
variables = ["head"]
```

{toml}`layer|observation.points.layer` and {toml}`depth|observation.points.depth` work as
the options of step 1, and a point cannot have both.

```{hmp-params}
observation.points.layer
observation.points.depth
observation.points.variables
```

```{note}
This is not {toml}`data.piezometry`. That section loads measured series from a data
source. {toml}`observation` says where the model is read. Nothing is compared to a
measurement here: the result is a model series.
```

## 3. Check it worked

Check the file first. The check catches a missing key, a duplicate `id`, and a point that
has both a layer and a depth:

```bash
hmp config check outlet.toml
```

Then run, and read the points back from Python:

```python
cat = hmp.open(".")
run = cat.latest()

run.probe.declared
run.timeseries("head", station="obs:outlet")
```

`run.probe.declared` lists the points the run sampled, with the columns `run`,
`station_id`, `x`, `y`, `cell_id` and `layer`. The series of a declared point is stored
under the station `obs:` followed by its `id`. `run.timeseries` returns it as a
`pandas.Series` indexed by date. A point that is missing from `declared` was not sampled:
see the next section.

The declaration is also written to `runs/<name>/tables.parquet/observation_points.parquet`,
beside the fields. `hmp catalog reindex` rebuilds the index from the run folders, so it
does not lose the declared points.

## What can go wrong

These messages come from the code. The first four stop `hmp catalog point`, which prints
the message on the error stream.

- A reference that matches no run:
  `Reference 'run_x' not found. Run `hmp catalog ls` to list known runs.` A name close
  to a known one is suggested after it. `@last` with no completed run gives
  `No completed run for '@last'`. The exit code is 10.
- A point outside the mesh: `Point (X, Y) falls outside the mesh of run 'NAME'.` The
  coordinates are read in the CRS of the simulation, not in WGS84.
- A cell or a layer out of range: `Cell 99999 is out of range for a mesh of N cells.`,
  `Layer 4 is out of range for 1 layers.` or `Timestep 40 is out of range for 36 steps.`
- A field the run does not hold:
  `Field 'name' is neither persisted nor derivable in simulation 'SIM_ID'.` The fields
  that this run can answer are listed by `run.array.list_fields()`. A virtual field needs
  the stored head and, for the depth of the water table, the surface elevation of the
  mesh.
- Both `--xy` and `--cell`, or both `--layer` and `--depth`, is a usage error of the
  command line, with exit code 2.
- A point that has no value gives `(no value at this point)`.

In the file, a declaration mistake does not lose the run. The check reports a duplicate
`id` as `Duplicate observation point id 'outlet'.`, and a point with both selectors as
`Observation point 'outlet' declares both 'layer' and 'depth'; keep one.` If the check
passes but the point cannot be sampled when the run finishes, for a point outside the mesh
or a field the run does not hold, the run keeps its results and the log shows
`Observation point 'outlet' could not be sampled:` followed by the reason. The point is
then absent from `run.probe.declared`.

```toml
# not checked: shows a mistake on purpose, a point with both selectors
base_config = "step4_transient.toml"

[[observation.points]]
id = "outlet"
x = 389285.910
y = 6816518.749
layer = 0
depth = 12.5
```

## Next

- The whole [observation] section, with every field: {toml}`observation`.
- The options of the command: {doc}`../reference/cli/catalog`.
- Open a catalog and drive runs from a script: {doc}`drive-from-python`.
- The run folder and what each file holds: {doc}`results-and-exports`.
- Find several runs and compare them: {doc}`find-compare-and-clean-runs`.
