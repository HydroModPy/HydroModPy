# Coming from version 1

Version 1 was a set of Python scripts. You built a `Watershed` object, called `add_*` and
`update_*` methods on it, and ran MODFLOW with `preprocessing_modflow` and `processing_modflow`.
Version 2 puts the same choices in a TOML file. You run it with `hmp run`, and every run is
stored in a folder you can read without HydroModPy.

The v1 scripts stay on the tag `v1.0.0`, and the branch `v1.0` is frozen. Nothing forces you to
move a finished study. For a new one, start from {doc}`index`.

## What changes

- Every setting is a key in a TOML file. There are no setter calls.
- A project is a folder with a `project.toml`. A run file names it with `base_config` and states
  only what it changes. A loop over a parameter becomes several run files, or a calibration.
- Results go to `runs/<name>/` as Zarr, Parquet and JSON. There is no pickle file to reload.
- Units are written with the value, as in `"30 m"` or `unit = "m/s"`. Version 1 expected
  meters and days. Version 2 stores SI units, so a v1 `hk` in m/day must be divided by 86400
  or written with its unit.
- Data come from a `[data]` table, either from a provider or from your own file.

## Keys

| Version 1 | Version 2 |
|---|---|
| `Watershed(from_xyv=[x, y, snap, buffer, crs])` | `[geographic.catchment]` with `kind = "from_outlet_coord"`, `x_outlet`, `y_outlet`, `snap_dist`, `buff_area`, and `crs_project` in `[geographic]` |
| `from_dem`, `from_shp` | `kind = "dem"` and `cell_size`, or `kind = "from_polyg_shp"` and `polyg_shp_path` |
| `dem_path` | `[[data.dem.sources]]` with `source = "file"` |
| `BV.add_hydrography`, `add_hydrometry`, `add_geology` | `types = [...]` and `[[data.<variable>.sources]]` in `[data]` |
| `update_simulation_state('transient')` | `flow_regime` in `[flow]`, and `[simulation.time]` for the dates |
| `update_nlay`, `update_lay_decay` | `nlay` and `lay_decay` in `[domain.layers]` |
| `update_thick(30)` | `[domain.depth_model]` with `kind = "constant_thickness"` and `thickness` |
| `update_hk`, `update_sy` | `[flow.param.K.field]` and `[flow.param.Sy.field]`, with `kind`, `unit` and `value` |
| `update_recharge` | `[flow.sinks_sources.recharge]`, and `recharge` in the `types` of `[data]` |
| `update_sink_fill` | `sink_fill` in `[solver]` |
| `update_input_particles(zone_partic=...)` | `zone_partic` in `[transport.modpath.parameters]` |
| `update_model_name` | `name` in `[simulation]` |
| `postprocessing_modflow(watertable_depth=True, ...)` | `figures` in `[display]` and `[[export]]` tables with `variables` |

A table of a process now carries `kind` where an alpha release of version 2 used `type`. If an
old file does not load, `hmp doctor --fix-config` rewrites the renamed keys and says what it
changed. The generated reference lists every key: {doc}`../reference/parameters/index`.

## Commands

| Version 1 | Version 2 |
|---|---|
| Edit the paths at the top of a script | `hmp workspace init`, then `hmp example add 04` |
| `preprocessing_modflow` and `processing_modflow` | `hmp run project/step.toml` |
| `postprocessing_modflow` and `postprocessing_netcdf` | `hmp export <run> --list`, then `hmp export <run> ...` |
| Plot functions of `visualization_results` | `hmp viz`, and the `figures` list of `[display]` |
| Reload a pickle of models | `hmp catalog ls`, `hmp catalog show <run>` and `hmp.read(...)` in Python |
| Calibration scripts | `hmp calibrate file.toml`, see {doc}`../reference/cli/calibrate` |
| Copy a folder of results to a colleague | `hmp publish <run> --to <folder> --with inputs` |

Every command takes `-w <workspace>`, and prints JSON with `--format json`. The full list is in
{doc}`../reference/cli/index`.

## Moving a study

1. Run `hmp workspace init` and put your input files in `~/hydromodpy/data/`.
2. Write a `project.toml` with the site, the catchment, the depth and the data. The six files of
   {doc}`the staircase <staircase/index>` show each step, from the shortest file that solves.
3. Run it with a steady regime first. Check the figures, then add the dates and the forcings.
4. Compare with your v1 results through `hmp catalog diff` or a notebook.

Results are not bit for bit equal to version 1. The recharge, the drains and the meshing were
rewritten, and each change is in the {doc}`changelog <../about/changelog>`.
