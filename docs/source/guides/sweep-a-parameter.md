# Sweep a parameter

```{hmp-task}
Task
: Run one model for several values of one parameter, and compare the results.

Time
: About a minute per value. Five values of K took 5 minutes.

Needs
: `project.toml` of example 04 and its data. `matplotlib` for the figure.

Gives
: One run per value in the catalog, a table of scores and a figure.
```

A sweep answers one question: how much does the result move when this parameter moves? It is
not a calibration. Nothing is searched and nothing is scored against a target to pick a value.
You choose the values, and you read the runs.

Three routes exist. This page takes the first.

| Route | When | Where |
|---|---|---|
| A loop of `Project.simulate` | You want every run kept, and your own table and figure | This page |
| The command line, one `hmp run` per value | You want a shell loop, or a scheduler | Section 4 |
| A `grid` calibration | You want the regular lattice scored against an observed series | {doc}`calibration-recipes` |

## 1. Choose the values

A run takes overrides of the flow parameters `K`, `Sy` and `Ss`, in the units of the project (for
`K`, m/s), and of `thickness`, `first_clim` and `properties`. The parameter is set for that run
only. The file is not changed.

Example 04 takes `K = 5e-5 m/s`. The sweep covers a factor 20 around it, five values spaced
by a factor of two or two and a half:

```python
K_VALUES = [1e-5, 2e-5, 5e-5, 1e-4, 2e-4]
```

## 2. Run the sweep

Copy {download}`recipes/sweep_k.py` to the project folder of example 04, next to `project.toml`,
and run it from there:

```bash
python sweep_k.py
```

The script has two parts, the runs and the reading. The runs are:

```{literalinclude} recipes/sweep_k.py
:language: python
:lines: 27-39
```

Four points matter:

- **Name every run.** Without `name=`, each run takes the name of the file and the catalog adds
  `.v2`, `.v3`: the names then say nothing about the value. With `name=f"sweep_k_{k:.0e}"` the
  catalog lists `sweep_k_1e-05` to `sweep_k_2e-04`.
- **One `Project`, many runs.** The catchment, the data and the mesh are prepared by the first run
  and reused by the others. The loop sits inside one `with` block.
- **`cfg.export = []`** drops the `[[export]]` blocks of the file, so five runs do not write five
  sets of files. `no_display=True` skips the figures of each run for the same reason.
- **Read the runs after the block.** The `Project` closes its catalog when the block ends.
  `hmp.open(HERE)` opens the catalog of the project again, and `cat[sim_id]` gives each run back.
  Do not open it while the block is still running.

## 3. Read the results

The script prints one row per value:

```text
         mean seepage area (km2)  min seepage area (km2)    NSE  log NSE
K
0.00001                    5.460                   3.026  0.677    0.734
0.00002                    3.461                   1.924  0.673    0.735
0.00005                    1.842                   0.934  0.671    0.739
0.00010                    1.093                   0.540  0.670    0.746
0.00020                    0.628                   0.298  0.656    0.730
```

and writes `share/figures/sweep_k.png`:

```{image} ../_static/figures/guides/sweep_k.webp
:alt: Left, the seepage area of the catchment month by month for five values of K, on a log scale. Right, the NSE and the NSE on log Q at the gauge against K.
:class: only-light
```

```{image} ../_static/figures/guides/sweep_k-dark.webp
:alt: Left, the seepage area of the catchment month by month for five values of K, on a log scale. Right, the NSE and the NSE on log Q at the gauge against K.
:class: only-dark
```

The five curves keep the same shape: the seepage area swells in the wet winter of 2000-2001 and
falls in summer. K sets their level. The mean seepage area falls from 5.5 to 0.6 km², a factor of
nine, when K grows by a factor of twenty. The scores at the gauge hardly move: NSE goes from
0.677 to 0.656. The discharge at the gauge does not tell these five models apart. The seepage
area does. This is why example 04 is calibrated on the mapped network: see
{doc}`calibrate-on-the-stream-network`.

The scores come from `run.metrics`, a table with one row per station and metric. The area is
counted on the cells of the catchment with `hmp.read(run, "seepage_mask")`.

## 4. The same sweep from the command line

`--set` overrides one key for one run, so a shell loop does the same work, with one process per
value:

```bash
for k in 1e-5 2e-5 5e-5 1e-4 2e-4; do
    hmp run project.toml --no-display \
        --set flow.param.K.field.value=$k \
        --set simulation.name=sweep_k_$k
done
```

Each run reads its `K` back as `run.params["K"]`, and `hmp catalog diff sweep_k_1e-5 sweep_k_2e-4`
prints the two values. Each process prepares the catchment and the mesh again. A scheduler that starts one job per
value runs them in parallel.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| The runs are named `…v2`, `…v3` | `simulate` was called without `name=` | Pass `name=` with the value in it |
| `hmp.run('<file>.toml') takes no parameter override (K). Write the value in the TOML file, or load it with hydromodpy.config.HydroModPyConfig.from_toml and pass the configuration object: hmp.run(cfg, K=...).` | `K=` given to `hmp.run` with a path | Use `Project.simulate`, as the script does |
| `The index '<path>' is already open in this process in another mode. …` | A catalog opened inside the `with` block, or two opened one read-only and one for writing | Open the catalog after the block |
| A run of the sweep is missing from the table | Its status is `failed`: the solver did not converge for that value | `hmp catalog ls`, then {doc}`non-convergence` |

## Next

- Search the best value instead of looking at five: {doc}`calibrate`.
- Compare two runs of the sweep side by side: {doc}`compare-runs`.
- Drive runs from Python: {doc}`drive-from-python`.
- The parameters you can override: {doc}`../reference/parameters/calibrable`.
