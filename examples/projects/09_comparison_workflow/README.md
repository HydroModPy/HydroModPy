# Example 09: compare three recipes of one catchment

The Nançon catchment (Ille-et-Vilaine), in steady state with MODFLOW 6, solved with three
values of the hydraulic conductivity K. The three runs are three recipes of one project;
`hmp report compare` reads them once they are sealed and writes one page: the differences to
the reference run, the maps of the head and of the depth to the water table, the head at the
outlet, the water-budget closure of each run.

## The files

- `project.toml`: the model, the site table and the three recipes. `k_mid` is the file as it
  is; `k_low` and `k_high` set `flow.param.K.field.value` on top of it.
- `sites.csv`: the one site, its label and its outlet. `[sites.bind]` copies each column into
  every case.

## Commands

From this folder, in a HydroModPy workspace that holds `data/dem/DEM_armorican_massif.tif`:

```bash
hmp config check project.toml          # the three cases, every error at its cell
hmp run project.toml --dry-run         # the plan: cases, solves, scratch; nothing written
hmp run project.toml                   # runs/nancon-k_low, runs/nancon-k_mid, runs/nancon-k_high
hmp report compare k_mid k_low k_high  # summary/report/compare/k_mid-vs-k_low-vs-k_high/
```

The first reference of `hmp report compare` is the reference of the differences. A recipe
names the latest run of each of its cases; a run name (`nancon-k_low`) or a run directory
works too. The three runs share the site and the mesh, so they compare as one case; runs on
two meshes need `--allow-different-mesh`, runs of several sites `--by site`.

The comparison opens `summary/report/compare/<refs>/web/index.html`. Nothing is written into
the runs.
