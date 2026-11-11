# Example 09: compare three recipes of one catchment

The Nançon catchment (Ille-et-Vilaine), in steady state with MODFLOW 6, solved with three
values of the hydraulic conductivity K. The three runs are three recipes of one project;
`hmp diff` reads them once they are sealed and writes one folder: the parameters that
differ, the differences to the reference run, the map of each difference, and the water budget
of each run.

## The files

- `project.toml`: the model, the site table and the three recipes. `k_mid` is the file as it
  is; `k_low` and `k_high` set `flow.param.K.field.value` on top of it.
- `sites.csv`: the one site, its label and its outlet. `[sites.bind]` copies each column into
  every case.

## Commands

From this folder, in a HydroModPy workspace that holds `data/dem/DEM_armorican_massif.tif`:

```bash
hmp check project.toml          # the three cases, every error at its cell
hmp run project.toml --dry-run         # the plan: cases, solves, scratch; nothing written
hmp run project.toml                   # runs/nancon-k_low, runs/nancon-k_mid, runs/nancon-k_high
hmp diff k_mid k_low k_high  # summary/report/compare/k_mid-vs-k_low-vs-k_high/
```

The first reference of `hmp diff` is the reference of the differences. A recipe
names the latest run of each of its cases; a run name (`nancon-k_low`) or a run directory
works too. Runs of several sites need `--by site`.

The comparison opens with `summary/report/compare/<refs>/README.md`. Nothing is written into
the runs.
