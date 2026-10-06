# Track particles

You release particles in the flow field of a MODFLOW 6 model and follow them. Each particle
moves with the water until it leaves the aquifer or reaches the time limit you set. You get
its path (x, y, z against time), so you can read a travel path, a travel time and the
distribution of residence times.

The tracking is advective. A particle follows the pore velocity of the flow and does not
disperse, react or change the flow. For concentrations, use a solute transport process, not
this one.

The worked case is example 04, `examples/projects/04_streamflow_intermittence_in_transient`.
The blocks below are merged onto its `step4_transient.toml`. That file gives the particles
a transient flow field to follow. Its K and Sy are assumed, not calibrated, so the travel
times you read are those of that model, not of the Nançon aquifer.

## What you need first

- **A MODFLOW 6 flow process.** The particle process attaches to the flow model of the same
  run. It cannot follow a MODFLOW-NWT model.
- **MODFLOW 6 version 6.5.0 or newer.** The PRT model shipped with 6.5.0. An older executable
  runs a flow model but rejects a particle model. Step 1 checks the version.
- **The Darcy velocity written by the flow run.** The card of
  {toml}`modflow6.runtime.save_specific_discharge` says particle tracking requires it. It is
  on unless you turned it off to save time in a calibration.

```{hmp-params}
modflow6.runtime.save_specific_discharge
```

## 1. Check the MODFLOW 6 build

`hmp doctor --prt` resolves the `mf6` executable HydroModPy would use and runs three checks:
the executable exists (`prt:mf6`), its version is at least 6.5.0 (`prt:mf6_version`), and
the installed FloPy has a PRT model (`prt:flopy`).

```bash
hmp doctor --prt
```

If the version check reports `KO`, download a recent build:

```bash
hmp install-binaries --mf6-prt --upgrade
```

`--mf6-prt` installs only the MODFLOW 6 executable. To use an executable of your own, give its
name or its absolute path:

```{hmp-params}
modflow6.runtime.mf6_executable_name
```

## 2. Add the particle process

A particle run is a second process in the same simulation, after the flow process. You
declare it as a `transport` process whose solver is `modflow6_prt`, and you give its settings
under {toml}`transport.modflow6prt.parameters`.

```toml
base_config = "step4_transient.toml"

[simulation]
name = "nancon_particles"

[[simulation.process__append]]
id = "prt_main"
type = "transport"
solvers = ["modflow6_prt"]

[transport.modflow6prt.parameters]
release_zone = "upstream"
max_particles = 300
```

The solver name is `modflow6_prt`, with an underscore. The settings table is
`transport.modflow6prt`, without one.

A simulation holds at most one process of each type, so it has one flow process and one
transport process. Order matters: the particle process must come after the flow process.
`step4_transient.toml` already declares `flow_main`. A list of tables of another length
replaces the parent's list, so `[[simulation.process__append]]` adds the new entry to it.
This is the `__append` spelling of {doc}`inheritance`. In a file of your own that does not
inherit, write two `[[simulation.process]]` entries, flow first.

```{hmp-params}
simulation.process
simulation.process.id
simulation.process.type
simulation.process.solvers
```

## 3. Choose where the particles start

HydroModPy releases one particle per selected cell. A cell here is a column of the mesh,
active if any of its layers is active. The particle starts at the centroid of the cell, in the
topmost active layer of its column. {toml}`transport.modflow6prt.parameters.local_z` sets its
height inside that cell, as a fraction of the cell thickness.

{toml}`transport.modflow6prt.parameters.release_zone` selects the cells.

| Zone | Cells it selects |
|---|---|
| `domain` | Every active cell. |
| `domain_nonriver` | Every active cell that is not a river-support cell. |
| `upstream` | Active cells whose top elevation is at or above the quantile set by {toml}`transport.modflow6prt.parameters.upstream_top_quantile`. |
| `upstream_nonriver` | The same cells, without the river-support cells. |
| `river` | The river-support cells. |
| `outlet` | Among the river-support cells, those whose top elevation is at or below the quantile set by {toml}`transport.modflow6prt.parameters.outlet_bottom_quantile`. If the model has no river-support cell, the same rule applies to all active cells. |
| `custom` | The cells you list in {toml}`transport.modflow6prt.parameters.particle_cell_ids`. |

```{hmp-params}
transport.modflow6prt.parameters.release_zone
transport.modflow6prt.parameters.upstream_top_quantile
transport.modflow6prt.parameters.outlet_bottom_quantile
transport.modflow6prt.parameters.particle_cell_ids
transport.modflow6prt.parameters.local_z
```

The river-support cells are the cells of the stream boundary, the one you switch on with
`"stream"` in {toml}`flow.active_bc`. Example 04 does not switch it on: it uses the drainage
boundary only. In example 04 the set is empty, and three things follow.

- `river` selects no cell, and the run stops (see the messages below).
- `domain_nonriver` and `upstream_nonriver` select the same cells as `domain` and `upstream`.
- `outlet` selects the lowest cells among all active cells.

After the zone, two keys thin the selection, in this order. The cells are first sorted and
made unique.

1. {toml}`transport.modflow6prt.parameters.sel_slice` keeps one cell out of every N.
2. {toml}`transport.modflow6prt.parameters.max_particles` caps the count. When more cells
   remain, HydroModPy keeps a subset spread over the area. The choice is deterministic:
   the same configuration releases the same cells.

Without a cap, `domain` on the mesh of example 04 releases one particle per active cell,
which is thousands of paths. Set a cap while you test.

```{hmp-params}
transport.modflow6prt.parameters.sel_slice
transport.modflow6prt.parameters.max_particles
```

To release from cells you pick yourself, give their ids. They are zero-based cell ids of the
mesh. A cell that is out of range or inactive is dropped without a message, and the run stops
only if no cell is left.

```toml
[transport.modflow6prt.parameters]
release_zone = "custom"
particle_cell_ids = [1200, 1201, 5310]
```

## 4. Set the porosity

A particle moves at the pore velocity, the Darcy flux divided by the porosity. A low porosity
makes the particles faster for the same flux.

```{hmp-params}
transport.modflow6prt.parameters.porosity
```

When you leave {toml}`transport.modflow6prt.parameters.porosity` out, HydroModPy uses the
specific yield of the flow model in each cell, and 0.3 in a cell where it is not positive. It
logs a warning, because the specific yield is smaller than the porosity and the particles go
too fast. Example 04 gives Sy this value:

```{hmp-resolved} flow.param.Sy.field.value
:config: step4_transient.toml
```

Set the porosity yourself. The number below is a placeholder for the example, not a
measure of the Nançon aquifer.

```toml
[transport.modflow6prt.parameters]
porosity = 0.05
```

## 5. Set when particles start and for how long

All times of this step are in days, counted from the start of the simulation. HydroModPy
converts them to the time unit of the MODFLOW 6 model.

- {toml}`transport.modflow6prt.parameters.release_times_days` lists the release times. Without
  it, every particle starts at the beginning of the first stress period.
- {toml}`transport.modflow6prt.parameters.stop_time_days` is an absolute time at which a
  particle stops.
- {toml}`transport.modflow6prt.parameters.stop_travel_time_days` stops a particle after this
  travel time, whatever its release time.
- {toml}`transport.modflow6prt.parameters.extend_tracking` lets particles go on after the last
  time step of the flow model, when MODFLOW 6 allows it. Example 04 covers three years.
  A stop time later than the end of the simulation relies on it.

```{hmp-params}
transport.modflow6prt.parameters.release_times_days
transport.modflow6prt.parameters.stop_time_days
transport.modflow6prt.parameters.stop_travel_time_days
transport.modflow6prt.parameters.extend_tracking
```

The path file always holds a record at the release, at every cell the particle leaves, at the
end of every time step and at the end of the path. To add records at times of your choice,
give a list with {toml}`transport.modflow6prt.parameters.track_times_days`, or a regular step
with {toml}`transport.modflow6prt.parameters.track_time_step_days`. The step builds the list
from 0 to {toml}`transport.modflow6prt.parameters.stop_time_days`, so it needs a stop time, and
a list takes precedence over a step.

More records make smoother lines and a larger file. They do not change the flow solution or
where the particles go.

```{hmp-params}
transport.modflow6prt.parameters.track_times_days
transport.modflow6prt.parameters.track_time_step_days
```

Together, steps 2 to 5 give this file:

```toml
base_config = "step4_transient.toml"

[simulation]
name = "nancon_particles"

[[simulation.process__append]]
id = "prt_main"
type = "transport"
solvers = ["modflow6_prt"]

[transport.modflow6prt.parameters]
release_zone = "upstream"
max_particles = 300
porosity = 0.05
release_times_days = [0.0]
stop_time_days = 3650.0
track_time_step_days = 30.0
```

## 6. Ask for the figures

Two figures read the paths. List them in {toml}`display.figures`. The `__append` spelling
adds them to the figures of step 4 instead of replacing the list.

```toml
base_config = "step4_transient.toml"

[display]
figures__append = ["particle_tracks", "residence_time_distribution"]

[display.overrides.particle_tracks]
max_tracks = 200
```

- `particle_tracks` draws the paths in plan view over the catchment, coloured by travel time
  in years. `max_tracks` caps the number of lines drawn.
- `residence_time_distribution` plots the density of the travel times of the particles. It sets
  the curve against the exponential law of a single well-mixed store. Each particle counts
  once, so the density follows the release you asked for. It is not weighted by recharge.

```{hmp-params}
display.figures
```

## 7. Check and run

Save the blocks above as `step4_particles.toml` in the folder of example 04, then:

```bash
hmp config check step4_particles.toml
hmp run step4_particles.toml
```

`hmp config check` validates the schema only. It does not build the plan and it does not
know the release zone names. A wrong solver name, a missing flow process or a misspelt zone
only shows when you run. The messages are in the next section.

The run first solves the flow, then the particles. The console shows "Writing particle
tracking input files" and "Solving particle tracking" for the second part.

When it ends, check three things.

- **The figures.** `hmp viz list` shows `particle_tracks` and `residence_time_distribution`.
  To draw one again for the last run:

  ```bash
  hmp viz show @last particle_tracks
  ```

  The file goes to `runs/<run>/figures/particle_tracks.png` unless you give `--output`.
- **The store.** The paths are in the `particles` group of `runs/<name>/fields.zarr/`. The
  arrays `x`, `y`, `z` and `time` have the shape (particle, track step). `x`, `y` and `z` use the
  coordinates of the mesh, `z` being an elevation. A particle with fewer records than the
  longest one is padded with NaN. `time` is in days: it is the absolute time of the
  simulation, so a travel time is the last time minus the first. The arrays `status` and
  `reason` are there when the solver file carries those columns. The group records its
  `time_units`, the file it was read from and the solver.
- **The solver file.** MODFLOW 6 writes `<model name>_prt.trk.csv` in the solver folder. The
  run deletes that folder when the results are stored, unless you ask to keep it. Keep it to
  read the raw records:

  ```toml
  [simulation.results]
  keep_solver_files = true
  ```

  ```{hmp-params}
  simulation.results.keep_solver_files
  ```

HydroModPy reads the CSV file only. If you turn off
{toml}`transport.modflow6prt.parameters.write_track_csv`, the run still succeeds but stores no
path, and both figures are skipped. The binary file written under
{toml}`transport.modflow6prt.parameters.write_track_binary` is for other tools.

```{hmp-params}
transport.modflow6prt.parameters.write_track_csv
transport.modflow6prt.parameters.write_track_binary
```

## What can go wrong

The messages below are the ones the code prints. Names in angle brackets stand for your values.

| Message | Cause and fix |
|---|---|
| `Simulation process '<id>' (transport/modflow6_prt) requires an earlier process using flow/modflow6.` | The plan has no MODFLOW 6 flow process before the particle process. Declare flow first. In a file that inherits a list of processes, use `[[simulation.process__append]]`, as in step 2. |
| `Unsupported simulation process/solver pair: transport/<name>.` | The solver name is wrong. It is `modflow6_prt`. |
| `At most one process of each type is supported. Duplicate 'transport' process found.` | You declared two transport processes. A simulation takes one. |
| `Unsupported modflow6prt release_zone '<name>'; expected domain, domain_nonriver, upstream, upstream_nonriver, river, outlet, or custom.` | The zone name is misspelt. The file check does not catch it. |
| `release_zone='custom' requires particle_cell_ids.` | Add {toml}`transport.modflow6prt.parameters.particle_cell_ids`. |
| `MODFLOW 6 PRT release zone '<name>' selected no cells.` | The zone is empty. With `river` and no stream boundary, this is expected: see step 3. For `custom`, none of your ids is an active cell. |
| `track_time_step_days requires stop_time_days.` | You gave a step without a stop time, and no list of tracking times. Add {toml}`transport.modflow6prt.parameters.stop_time_days`. |
| `No PRT porosity set; falling back to the flow specific yield` | A warning, not an error. Set {toml}`transport.modflow6prt.parameters.porosity`, as in step 4. |
| `[HMPY.E401] Particle transport solver 'modflow6_prt' failed for run '<run>'.` | MODFLOW 6 stopped during the particle solve. The message names the folder to open. Run `hmp doctor --prt` first: an executable older than 6.5.0 rejects the particle model. |
| `No MODFLOW 6 PRT track CSV found in <folder>` | A warning. The solver wrote no CSV, so nothing was stored. Check {toml}`transport.modflow6prt.parameters.write_track_csv`. |
| `figure 'particle_tracks' does not apply to this run: missing result field(s): particles` | The run stored no path. Either it has no particle process, or no CSV file was read (previous row). |
| `figure 'particle_tracks' does not apply to this run: run holds no particle pathline: no particle moved from its release point` | The group exists, but no particle has two positions. Open the CSV file with `keep_solver_files = true` and read it. |

A wrong direction is refused by the file check. Only forward tracking exists.

```toml
# not checked: shows a mistake on purpose
base_config = "step4_transient.toml"

[transport.modflow6prt.parameters]
track_dir = "backward"
```

```text
transport.modflow6prt.parameters.track_dir: Input should be 'forward' (input='backward')
```

```{hmp-params}
transport.modflow6prt.parameters.track_dir
```

## Where to go next

- The keys of the particle process, with their defaults and units, are in the
  {doc}`transport reference <../reference/parameters/transport>`.
- If the flow run stops before the particles start, see {doc}`non-convergence`.
- To pick a solver family, see {doc}`choose-a-solver`.
- To export or compare what a run stored, see {doc}`results-and-exports`.
