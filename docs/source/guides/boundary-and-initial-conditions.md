# Set the boundaries and the starting heads

```{hmp-task}
Task
: Say where water leaves or enters the model at its edges and at the ground, and where the heads start.

Time
: Fifteen minutes. The file below runs in about twenty seconds on two cores.

Needs
: A model that runs. For a fixed head, the level of the sea, the river or the lake that holds it.

Gives
: A model whose exits you chose, and a map of the cells each boundary acts on.
```

A boundary says what happens where the model meets the outside: at the ground surface,
along the sides of the domain, at the sea or along a river. The starting heads say where
the water table is when the run begins. Both are written under `[flow]`.

The worked case is example 04. Its files drain every cell at the ground surface and leave
the four sides of the domain closed: no water crosses them. That is the usual choice for a
headwater catchment, whose divides are its edges. The blocks below are merged onto
`step1_minimal.toml`.

{download}`Download the file of this guide <recipes/model/guide_boundaries.toml>`.

## What you need first

- A model that runs.
- For a fixed head along a side, at the sea or on a river: the level, and a model whose
  cells all reach below it (step 3).

## 1. List the boundaries

{toml}`flow.active_bc` lists the boundaries the model carries. A boundary that is not in
the list is not built, whatever its table says, and an empty list builds none.

| Id | What it is | Package | Solvers |
|---|---|---|---|
| `drainage` | Seepage at the ground surface: a cell whose head rises above its top loses the excess. | DRN | all three |
| `north_side`, `south_side`, `east_side`, `west_side` | A fixed head along one side of the domain. | CHD | all three |
| `ocean` | A fixed head, the sea level, on every cell whose ground is at or below it. | CHD | all three |
| `stream` | A fixed head on the river cells of a Gmsh mesh. | CHD | MODFLOW 6, Boussinesq |
| `lake`, `reservoir` | A lake whose stage the solver computes. | LAK | MODFLOW 6 |
| `sfr` | Streams that route water down a network. | SFR | MODFLOW 6 |

A side that no boundary names is closed. The lake and the streams have their own guides:
{doc}`lakes-and-reservoirs` and {doc}`route-streams-with-sfr`.

```{hmp-params}
flow.active_bc
```

## 2. Drain the ground surface

`drainage` puts one drain on the top of every cell, at the elevation of the top. The drain
takes water out when the head rises above it, and never puts any in. This is how the water
table reaches the surface and leaves as seepage. It needs no table:

```toml
base_config = "step1_minimal.toml"

[simulation]
name = "nancon_guide_boundaries"

[flow]
active_bc = ["drainage"]
```

The conductance of each drain is derived from the conductivity of its cell, its area and
the thickness of a drain bed. A {toml}`flow.bc.<name>.value` written under
`[flow.bc.drainage]` replaces it by one conductance per cell, in m2/s. Keep the derived
one unless you know the bed: the drain then scales with K and does not limit the seepage.
The law is in {doc}`../theory/exits`.

```{hmp-params}
flow.bc.<name>.value
```

## 3. Hold a head along a side, at the sea or on a river

A side boundary holds one head on every cell of that side, in every layer. The head is
written once:

```toml
base_config = "step1_minimal.toml"

[flow]
active_bc = ["drainage", "west_side"]

[flow.bc.west_side]
value = "150 m"
```

The head must stand above the bottom of every cell it is applied to, or MODFLOW 6 refuses
the file. One head along a side whose ground climbs is therefore a strong statement. On
example 04, the west side of the domain runs from 133 m to 191 m of ground over 30 m of
aquifer: no single head stays inside all of its cells. A fixed side suits an edge that
follows a canal, a lake shore or the coast, or a model on a flat substratum
({doc}`depth-and-substratum`).

`ocean` takes its head the same way, under `[flow.bc.ocean]`, and applies it to every cell
whose ground is not above it. `stream` applies its head to the river cells of a Gmsh mesh.
A head that changes in time takes a `forcing` table in place of `value`, `constant` or
`csv`.

```{hmp-params}
flow.bc.<name>.application_domain
flow.bc.<name>.forcing
```

## 4. Choose where the heads start

A steady run solves the heads it ends with; where they start only helps the solver. A
transient run starts from {toml}`flow.ic.h.type`, unless its first stress period is
solved steady, which is the default ({toml}`flow.first_period_steady`). Example 04 starts
its transient runs from that steady period.

```toml
base_config = "step4_transient.toml"

[flow]
first_period_steady = false

[flow.ic]
type = "steady_state"
```

`[flow.ic]` is a flat table. The types are `top`, the default, `bottom`, `top_offset`,
`custom`, `steady_state` and `spinup_cyclic`. Which one to take, and how to spin a model
up, is the subject of {doc}`time-and-initial-state`.

```{hmp-params}
flow.ic.h.type
flow.first_period_steady
```

## 5. Run it and look at the boundaries

The file of this guide keeps the drains of example 04 and stores the budget of every cell,
which `boundary_package_map` reads.

```toml
base_config = "step1_minimal.toml"

[simulation.results.budget]
spatial_fields = true

[display]
figures = ["boundary_package_map", "water_budget"]
```

::::{tab-set}

:::{tab-item} Command line
```bash
hmp run guide_boundaries.toml
hmp viz show @last boundary_package_map
```
:::

:::{tab-item} Python
```python
import hydromodpy as hmp

run = hmp.run("guide_boundaries.toml")
print(run.budget(component="drain"))
hmp.figure(run, "boundary_package_map")
```
:::

::::

`boundary_package_map` colours every cell a package exchanges water through. In the
steady state of example 04, 611 of the 21 406 cells drain, 2.9 % of the mesh, along the
valleys:

```{figure} /_static/figures/guides/boundary-and-initial-conditions/boundary_package_map.webp
:alt: Map of the cells where the drains of the model release water, along the valleys of the Nançon catchment.

`boundary_package_map` of the file of this guide.
```

## Check that it worked

1. `boundary_package_map` shows each boundary where you expect it. A boundary listed in
   {toml}`flow.active_bc` that acts on no cell is reported with zero cells.
2. `water_budget`, or `run.budget()` in Python, has one term per boundary. A fixed head
   appears as `constant_head`, a drain as `drain`.
3. A fixed head that takes in or gives out most of the water of the model is the first
   thing to question.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `flow.active_bc: '<name>' is not a valid boundary-condition id for Flow` | A boundary id that does not exist. | Use an id of the table of step 1. |
| `solver.backend='modflow_nwt' does not support the 'sfr' boundary (supported by: modflow6)` | A boundary the solver does not build. | See {doc}`choose-a-solver`. |
| The run stops with `[HMPY.E401] Flow solver 'modflow6' failed`, and the listing reads `CHD BOUNDARY 1 HEAD (100.0000000000000) IS LESS THAN CELL BOTTOM (129.8000030500000) FOR CELL (1,21268)` | A side, sea or river head below the bottom of some of its cells. HydroModPy does not check it before the solver. | Raise the head, or deepen the aquifer under that edge. |
| `Boundary 'stream' is active but its selected runtime mesh support is empty.` | `stream` without river cells on the mesh. | Build a Gmsh mesh that follows the rivers: {doc}`choose-and-build-the-mesh`. |
| `flow.ic.type='steady_state' is only supported when flow.flow_regime='transient'` | A steady start on a steady run. | Remove `[flow.ic]` from a steady file. |
| A steady run stays in its `run_solver` step for minutes | No boundary takes water out: `drainage` is missing from {toml}`flow.active_bc` and no head is fixed, so the recharge has no exit. | Add `drainage`. |

## Where to go next

- What each exit does to the water, with its equations: {doc}`../theory/exits`.
- The starting state of a transient run: {doc}`time-and-initial-state`.
- A lake or a stream network as a boundary: {doc}`lakes-and-reservoirs`,
  {doc}`route-streams-with-sfr`.
- Every boundary key: {toml}`flow.bc`.
