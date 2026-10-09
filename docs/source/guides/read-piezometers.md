# Read several piezometers

```{hmp-task}
Task
: Read the simulated water table at a list of piezometers, and keep them for every run.

Time
: Seconds on a finished run. A minute more to declare them.

Needs
: A completed run, and the coordinates of the piezometers in the project CRS.

Gives
: One table with a column per piezometer, a CSV file, and optionally the series stored with each run.
```

{doc}`read-a-value-at-a-point` reads one place. A piezometer network has ten or a hundred. This
page reads them all, in one table, and shows how to make every run record them.

The table holds simulated values. A piezometer here is a place where the model is read. If you
have measured levels, put them beside the table with your own tools. Observed data is a
diagnostic and never a model input, and this page computes no score from it.

## 1. A list of piezometers

A CSV file with one row per piezometer, in the CRS of the project (`EPSG:2154` for example 04):

```text
id,x,y
PZ1,388352.0,6818548.0
PZ2,390752.0,6821548.0
PZ3,393902.0,6820428.0
PZ4,394272.0,6819822.0
```

The four points of example 04 are cells of its catchment, from the bottom of the valley to a
crest: {download}`recipes/piezometers.csv`. They are not real wells.

## 2. Read a finished run

::::{tab-set}

:::{tab-item} Python

Copy {download}`recipes/read_piezometers.py` next to `piezometers.csv`, in the project folder,
and run it:

```bash
python read_piezometers.py nancon_step4_transient
```

```{literalinclude} recipes/read_piezometers.py
:language: python
:lines: 28-35
```

`run.probe.series` reads one place. The loop calls it once per row, and `label=` names the point
in the `point` column. `pivot` turns the long table into one column per piezometer.
:::

:::{tab-item} Command line

`hmp catalog point` reads one place per call, and takes a run, a variable and `--xy`:

```bash
hmp catalog point nancon_step4_transient --var watertable_depth \
    --xy 388352 6818548 --label PZ1 --format csv -o PZ1.csv
```

Write a loop for a list, or stack the answers with the Python script. The command has no option
to read a file of points.
:::

::::

The script prints the first rows and writes `share/piezometers.csv`:

```text
point        PZ1   PZ2   PZ3    PZ4
time
2000-02-01  3.96  9.15  3.54  20.87
2000-03-01  3.97  9.16  3.55  20.88
2000-04-01  4.07  9.29  3.67  21.03
2000-05-01  4.10  9.36  3.72  21.11
2000-06-01  4.08  9.35  3.72  21.12
```

The values are the depth of the water table below the ground, in metres. Each date is the end of
a monthly stress period, and the value is the state at that date.

```{image} ../_static/figures/guides/read_piezometers.webp
:alt: Depth of the water table in metres, month by month from 2000 to 2002, at four piezometers. PZ1 and PZ3 stay within 1 to 6 m, PZ2 sits near 6 to 11 m and PZ4 on the crest near 17 to 24 m. All four are shallowest in spring 2001.
:class: only-light
```

```{image} ../_static/figures/guides/read_piezometers-dark.webp
:alt: Depth of the water table in metres, month by month from 2000 to 2002, at four piezometers. PZ1 and PZ3 stay within 1 to 6 m, PZ2 sits near 6 to 11 m and PZ4 on the crest near 17 to 24 m. All four are shallowest in spring 2001.
:class: only-dark
```

The vertical axis is flipped, so a rising curve is a rising water table. The four series move
together: all are shallowest in spring 2001, after the wet winter. The crest piezometer stays much deeper than the
valley ones.

### Pick the layer

A piezometer with a screen at a known depth reads the layer that holds it. Pass `depth` in the
loop, in metres below the local model top, or `layer`, a zero-based index with negative values
counting from the bottom. A point cannot have both. Example 04 has one layer, so the choice
changes nothing there.

```python
run.probe.series("head", x=388352.0, y=6818548.0, depth=12.5, label="PZ1")
```

## 3. Record them with every run

When the same piezometers matter for every run, declare them in the file. The run samples each
point when it finishes and stores the series with its results. Reading them back later is a plain
table read, and `hmp catalog reindex` does not lose them.

```toml
base_config = "step4_transient.toml"

[simulation]
name = "nancon_piezometers"

[observation]
variables = ["head", "watertable_depth"]

[[observation.points]]
id = "PZ1"
x = 388352.0
y = 6818548.0

[[observation.points]]
id = "PZ2"
x = 390752.0
y = 6821548.0
```

The full file with four points is {download}`recipes/observe_piezometers.toml`.
{toml}`observation.variables` is read at every point. Each entry of
{toml}`observation.points` needs a unique {toml}`id|observation.points.id` and the coordinates
{toml}`x|observation.points.x` and {toml}`y|observation.points.y`. A point may add its own
{toml}`layer|observation.points.layer`, {toml}`depth|observation.points.depth` or
{toml}`variables|observation.points.variables`.

A list of tables cannot read a CSV file. Write the blocks with a loop:

```python
import pandas as pd

blocks = [
    f'[[observation.points]]\nid = "{row.id}"\nx = {row.x}\ny = {row.y}\n'
    for row in pd.read_csv("piezometers.csv").itertuples()
]
open("observe_piezometers.toml", "a").write("\n" + "\n".join(blocks))
```

Check the file, then run it and read the points back:

```bash
hmp config check observe_piezometers.toml
hmp run observe_piezometers.toml
```

```python
cat = hmp.open(".")
run = cat["nancon_piezometers"]

run.probe.declared
run.timeseries("watertable_depth", station="obs:PZ1")
```

```text
                  run station_id         x          y  cell_id  layer
0  nancon_piezometers        PZ1  388352.0  6818548.0    14907      0
1  nancon_piezometers        PZ2  390752.0  6821548.0     9379      0
2  nancon_piezometers        PZ3  393902.0  6820428.0    11506      0
3  nancon_piezometers        PZ4  394272.0  6819822.0    12623      0
```

The declared series and the series of section 2 are the same numbers: reading `PZ1` both ways
gives identical values. The declared route adds the guarantee that every run of the file has them.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `Point (100.0, 100.0) falls outside the mesh of run 'nancon_step4_transient'.`, exit 1 | The coordinates are not in the model domain, or not in the CRS of the project | Read them in the project CRS, not in WGS 84 |
| `Field 'nosuch' is neither persisted nor derivable in simulation '<sim_id>'.` | The run does not hold that variable | List the fields with `run.array.list_fields()` |
| `Duplicate observation point id 'PZ1'.` from `hmp config check` | Two points share an `id` | Give each point its own `id` |
| `Observation point 'PZ1' declares both 'layer' and 'depth'; keep one.` | Both selectors on one point | Keep one |
| `Observation point 'PZ1' could not be sampled:` in the log, and the point missing from `run.probe.declared` | The point is outside the mesh, or the field is not held | The run keeps its results. Fix the point and run again |
| `pivot` raises `Index contains duplicate entries` | Two rows of the CSV share an `id` | Give each piezometer its own `id` |

## Next

- Read one place from the command line: {doc}`read-a-value-at-a-point`.
- The whole `[observation]` section: {toml}`observation`.
- Compare the series of several runs: {doc}`compare-runs`.
