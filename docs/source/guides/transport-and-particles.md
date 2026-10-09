# Model solute transport and particles

```{hmp-task}
Task
: Add a transport process to a flow model: the concentration of a solute, or the paths of particles, forward or backward.

Time
: Thirty minutes to choose and write. The solute file below runs in about three minutes on two cores.

Needs
: A transient flow model that runs on MODFLOW 6 or MODFLOW-NWT.

Gives
: A concentration field over time, or particle paths and travel times.
```

A transport process runs after the flow process of the same simulation, on the heads and
the flows it computed. HydroModPy has four transport solvers. Two compute a concentration,
two follow particles, and each one follows one flow solver. The Boussinesq solver takes
no transport process.

| Solver name | Follows | Computes | Settings | Direction |
|---|---|---|---|---|
| `modflow6` | `modflow6` | the concentration of one solute (MODFLOW 6 GWT) | {toml}`transport.modflow6gwt.parameters` | |
| `mt3dms` | `modflow_nwt` | the concentration of one solute (the `mt3dusgs` executable) | {toml}`transport.mt3dms.parameters` | |
| `modflow6_prt` | `modflow6` | particle paths (MODFLOW 6 PRT) | {toml}`transport.modflow6prt.parameters` | forward only |
| `modpath` | `modflow_nwt` | particle paths (MODPATH 6, the `mp6` executable) | {toml}`transport.modpath.parameters` | forward or backward |

A simulation holds one process of each type, so one flow process and at most one
transport process. The transport process comes after the flow process in
`[[simulation.process]]`, and names its solver in `solvers`. Particle tracking with MODFLOW
6 has its own guide, {doc}`track-particles`; this page covers the other three solvers and
what backward tracking can do today.

The worked case is example 04, on its monthly transient `step4_transient.toml`.

{download}`Download the solute file of this guide <recipes/model/guide_solute.toml>`.

## What you need first

- A transient flow model that runs. The transport reads the flow of every stress period.
- The solver executables: `mf6` for MODFLOW 6, `mfnwt`, `mt3dusgs` and `mp6` for the
  MODFLOW-NWT side. `hmp doctor` lists the ones it finds, and `hmp install-binaries`
  downloads them.

## 1. Add a solute to a MODFLOW 6 model

The solver `modflow6` of a `transport` process runs MODFLOW 6 GWT on the flow of the run.
The block below brings a solute with the recharge, at a concentration of 50, into an
aquifer that holds none at the start. The figures label concentrations in kg/m3.

```toml
base_config = "step4_transient.toml"

[simulation]
name = "nancon_guide_solute"

[[simulation.process__append]]
id = "gwt_main"
type = "transport"
solvers = ["modflow6"]

[transport.modflow6gwt.parameters]
spc_name = "NO3"
sconc_init = 0.0
sconc_input = 50.0
porosity = 0.05

[display]
figures = ["concentration_map"]
```

`[[simulation.process__append]]` adds the transport process to the flow process that
step 4 inherits. The values above only complete the file: the solute, its input and the
porosity belong to your site.

```{hmp-params}
transport.modflow6gwt.parameters.spc_name
transport.modflow6gwt.parameters.sconc_init
transport.modflow6gwt.parameters.sconc_input
transport.modflow6gwt.parameters.porosity
transport.modflow6gwt.parameters.scheme
```

`sconc_init` is the concentration everywhere at the start, `sconc_input` the
concentration of the recharge. Without a porosity, the specific yield of the flow model
stands for it, which makes the solute travel too fast. The advection scheme is `upstream`
by default, robust and diffusive; `TVD` keeps a sharp front.

Dispersion, diffusion and decay are off by default. Their rates run on the clock of the
GWT model, in seconds: a diffusion coefficient is in m2/s, and a first-order decay in 1/s.
A rate per day written as is is 86 400 times too large.

```{hmp-params}
transport.modflow6gwt.parameters.disp_long
transport.modflow6gwt.parameters.diffu_coeff
transport.modflow6gwt.parameters.react_order
transport.modflow6gwt.parameters.rate_decay
```

## 2. Add a solute to a MODFLOW-NWT model

On MODFLOW-NWT, the solver is `mt3dms`, with the same parameters under
{toml}`transport.mt3dms.parameters`. The flow process names `modflow_nwt`, and the
transport process follows it:

```toml
base_config = "step4_transient.toml"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]

[[simulation.process]]
id = "mt3d_main"
type = "transport"
solvers = ["mt3dms"]

[transport.mt3dms.parameters]
sconc_input = 50.0
porosity = 0.05
```

The two processes are written in full, because the flow solver changes: a list written in
a file replaces the inherited one.

## 3. Follow particles on MODFLOW-NWT

MODPATH 6 follows particles on a MODFLOW-NWT model. Its settings live under
{toml}`transport.modpath.parameters`. The particles start from the cells of
`zone_partic`: `domain`, the whole domain by default, `seepage_clip`, the seepage cells
of the catchment, or the path of a raster whose non-zero cells mark the start.

```toml
base_config = "step4_transient.toml"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]

[[simulation.process]]
id = "mp_main"
type = "transport"
solvers = ["modpath"]

[transport.modpath.parameters]
zone_partic = "domain"
sel_slice = 20
```

```{hmp-params}
transport.modpath.parameters.zone_partic
transport.modpath.parameters.track_dir
transport.modpath.parameters.cell_div
transport.modpath.parameters.sel_slice
transport.modpath.parameters.sel_random
```

A raster given as `zone_partic` must sit on the grid of the solver, row for row and column
for column. The paths of MODPATH and of MODFLOW 6 PRT are stored the same way, so the
figures and the reading of {doc}`track-particles` apply to both.

## 4. Track backward

A backward tracking starts particles where the water arrives, a well or a stream, and
follows them up the flow to where they came from: it delineates a capture zone. What the
code does today:

- MODFLOW 6 PRT tracks forward only. {toml}`transport.modflow6prt.parameters.track_dir`
  accepts `forward` and nothing else, and a file that writes `backward` is refused.
- MODPATH accepts `track_dir = "backward"`. The particles start at the centre of the top
  layer of each cell that the `zone_partic` raster marks, and MODPATH tracks them against
  the flow. No test of HydroModPy runs a backward MODPATH case end to end: read its result
  with care.
- No function turns the paths into a capture-zone polygon. The paths are in the store
  ({doc}`track-particles`, step 7).

```toml
base_config = "step4_transient.toml"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]

[[simulation.process]]
id = "mp_main"
type = "transport"
solvers = ["modpath"]

[transport.modpath.parameters]
zone_partic = "capture_start.tif"
track_dir = "backward"
```

Here `capture_start.tif` is a raster you make on the grid of the solver, with 1 on the
cells to start from and 0 elsewhere.

## 5. Run it and look at the concentration

::::{tab-set}

:::{tab-item} Command line
```bash
hmp run guide_solute.toml
hmp viz show @last concentration_map
```
:::

:::{tab-item} Python
```python
import hydromodpy as hmp

run = hmp.run("guide_solute.toml")
hmp.figure(run, "concentration_map")
```
:::

::::

`concentration_map` draws the concentration at the date of {toml}`display.time`, October
2002 for step 4. After almost three years, the aquifer under the plateaus, where the
recharge stays, is close to the input, 50. The valleys, where water from upslope comes
out, read 20 to 30: that water entered before the solute did.

```{figure} /_static/figures/guides/transport-and-particles/concentration_map.webp
:alt: Map of the solute concentration over the Nançon model after three years.

`concentration_map` of the solute file of this guide, October 2002.
```

## Check that it worked

1. `hmp run` prints the transport step after the flow step. A transport process that
   comes first is refused before the run.
2. `hmp viz list` names the transport figures the run can draw:
   `concentration_map` for a solute, `particle_tracks` for particles.
3. A concentration above `sconc_input` anywhere is a numerical artefact: try `TVD`, or
   smaller time steps.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `Simulation process '<id>' (transport/modflow6) requires an earlier process using flow/modflow6.` | The transport process comes first, or follows a flow process of the other solver. `mt3dms` and `modpath` ask for `flow/modflow_nwt` the same way. | List the flow process first, with the solver the table above names. |
| `Unsupported simulation process/solver pair: transport/<name>.` | A solver name that does not exist. | Use a name of the table. |
| `At most one process of each type is supported. Duplicate 'transport' process found.` | Two transport processes. | Keep one per simulation. |
| `solver.backend='boussinesq' does not support the [transport] section` | A transport process on a Boussinesq model. | Use a MODFLOW solver. |
| `transport.modflow6prt.parameters.track_dir: Input should be 'forward' (input='backward')` | Backward tracking on MODFLOW 6 PRT. | Use MODPATH on MODFLOW-NWT, as in step 4. |
| `MODPATH injection raster <path> has shape (<r>, <c>) but the MODFLOW grid is (<nrow>, <ncol>).` | The `zone_partic` raster is not on the solver grid. | Write the raster on the grid of the solver. |
| `Cannot resolve default zone_partic='domain'. Provide transport.modpath.parameters.zone_partic as a raster path.` | The run has no domain raster to start from. | Give a raster path. |
| `MODFLOW 6 GWT produces no calibration observable` | A calibration that scores a concentration. | Calibration reads the flow outputs only. |

## Where to go next

- Particles on MODFLOW 6, with their figures and their travel times:
  {doc}`track-particles`.
- Which flow solver to take: {doc}`choose-a-solver`.
- Every transport key: {doc}`../reference/parameters/transport`.
