# Add a flow barrier

A flow barrier is a thin vertical wall inside the aquifer that water crosses with
difficulty: a dam cutoff wall, a grout curtain, a sheet pile, a sealed fault. You
draw its trace on the map, say how deep it goes and how tight it is. HydroModPy writes
it as a MODFLOW 6 Horizontal Flow Barrier (HFB) package. The water that used to cross
the wall in the top layers is forced to go under it.

This guide declares one barrier, checks that the solver received it, and lists the
refusals you can meet. The same payload also exists as the cutoff wall of a lake, in
step 5.

## What you need first

- A flow process solved with MODFLOW 6. The barrier exists for no other backend. See
  {doc}`choose-a-solver <choose-a-solver>`.
- A trace: the vertices of the wall in the project CRS, or a vector file that holds it.
  A wall on a map is a polyline, so it needs two vertices at least.
- A depth, or the elevation of the wall foot. Without one of the two, the barrier
  has no vertical extent.
- A resistance. A near-impermeable wall takes a very small value.

The blocks below are written to be merged onto `step1_minimal.toml` of example 04, the
shortest file that runs. Its trace coordinates are placeholders. Replace them with the
coordinates of your wall.

## How the wall is placed

A barrier does not refine the mesh and does not follow your line exactly. MODFLOW 6
places a barrier on the face shared by two cells. HydroModPy turns the trace into the
chain of faces it separates: a face is blocked when the trace crosses the segment that
joins the centres of its two cells. The wall is therefore a staircase along cell edges,
and its position is exact to about one cell. A trace that runs along cell edges is no
problem.

On each blocked face, every layer that the barrier band touches is blocked over its whole
thickness. The band runs from the barrier crest, the model top unless you set
{toml}`crest_elevation|flow.sinks_sources.flow_barriers.<name>.crest_elevation`, down to
the foot. A layer where either of the two cells is inactive gets no barrier.

The barrier is static. It holds the same resistance for the whole run.

## 1. Give the barrier a name and a trace

The name is yours. It is the last part of the table name. A trace is either inline
vertices or a file. You write one of the two, never both.

```toml
# not checked: incomplete on purpose, steps 2 and 3 add the depth and the resistance
[flow.sinks_sources.flow_barriers.cutoff]
line = [[389200.0, 6816400.0], [389380.0, 6816620.0]]
```

This block is not complete. A trace alone is refused: steps 2 and 3 add the depth and the
resistance.

```{hmp-params}
flow.sinks_sources.flow_barriers
flow.sinks_sources.flow_barriers.<name>.line
flow.sinks_sources.flow_barriers.<name>.line_path
```

With a file, write {toml}`line_path|flow.sinks_sources.flow_barriers.<name>.line_path`
instead of `line`. HydroModPy reads a vector file with one polyline (GeoPackage,
Shapefile, GeoJSON) or a CSV of ordered x and y columns.

- A vector file is reprojected to the project CRS and its parts are merged into one line.
  A file with no CRS is read as if it were in the project CRS, and a warning says so.
- A CSV is read as if it were in the project CRS.
- A file with a branching or a multi-part trace is refused: split it into one barrier
  per line.

For a general barrier, the file is opened as you write it. A relative path is relative to
the folder where you run `hmp`. Give an absolute path when you are not sure. The lookup in
`<workspace>/data/cutoff_wall/` that the card of
{toml}`line_path|flow.sinks_sources.flow_barriers.<name>.line_path` mentions applies to the
cutoff wall of a lake only.

## 2. Set how deep the wall goes

Two ways, and you write exactly one.

- {toml}`depths|flow.sinks_sources.flow_barriers.<name>.depths`: the depth below the crest,
  in metres. One value makes a wall of constant depth. Several values give a depth per
  vertex of the trace, interpolated along the line. The list then needs exactly one value
  per vertex of an inline `line`. With a `line_path`, give one value.
- {toml}`base_elevation|flow.sinks_sources.flow_barriers.<name>.base_elevation`: the
  absolute elevation of the foot. The barrier then blocks every layer between the crest
  and that elevation. Take it for a full-height dam, where the body of the dam and the
  grout curtain stop all flow down to the foot of the curtain.

A depth shallower than the aquifer leaves a path under the wall: that is the point of a
partial wall. A depth of zero or less is refused.

```toml
# not checked: incomplete on purpose, step 3 adds the resistance
[flow.sinks_sources.flow_barriers.cutoff]
line = [[389200.0, 6816400.0], [389380.0, 6816620.0]]
depths = [10.0]
```

Compare the depth with the thickness of your model before you choose it. Example 04 sets
it to:

```{hmp-resolved} domain.depth_model.thickness
:config: step1_minimal.toml
```

```{hmp-params}
flow.sinks_sources.flow_barriers.<name>.depths
flow.sinks_sources.flow_barriers.<name>.base_elevation
flow.sinks_sources.flow_barriers.<name>.crest_elevation
```

## 3. Set the resistance

The resistance of a barrier is its hydraulic characteristic, the conductivity of the wall
divided by its thickness. It is an inverse time. A small value is a tight wall. You give
it in one of two forms, and exactly one.

- {toml}`hydchr|flow.sinks_sources.flow_barriers.<name>.hydchr`, the value itself, in the
  unit of {toml}`hydchr_unit|flow.sinks_sources.flow_barriers.<name>.hydchr_unit`.
- {toml}`k|flow.sinks_sources.flow_barriers.<name>.k` and
  {toml}`thickness|flow.sinks_sources.flow_barriers.<name>.thickness`, together. HydroModPy
  divides the first by the second after it converts both to metres and seconds. A wall of
  `k = 1e-9` m/s and `thickness = 0.5` m is a `hydchr` of 2e-9 per second.

Use the second form when you know the material of the wall and not its characteristic.

```toml
base_config = "step1_minimal.toml"

[flow.sinks_sources.flow_barriers.cutoff]
line = [[389200.0, 6816400.0], [389380.0, 6816620.0]]
depths = [10.0]
hydchr = 1e-9
hydchr_unit = "1/s"
```

The same wall from the material:

```toml
base_config = "step1_minimal.toml"

[flow.sinks_sources.flow_barriers.cutoff]
line = [[389200.0, 6816400.0], [389380.0, 6816620.0]]
depths = [10.0]
k = 1e-9
k_unit = "m/s"
thickness = 0.5
thickness_unit = "m"
```

```{hmp-params}
flow.sinks_sources.flow_barriers.<name>.hydchr
flow.sinks_sources.flow_barriers.<name>.hydchr_unit
flow.sinks_sources.flow_barriers.<name>.k
flow.sinks_sources.flow_barriers.<name>.k_unit
flow.sinks_sources.flow_barriers.<name>.thickness
flow.sinks_sources.flow_barriers.<name>.thickness_unit
```

## 4. Keep MODFLOW 6

The check reads {toml}`solver.backend.backend`, not the solver named in
{toml}`simulation.process`. Example 04 uses the default, which is MODFLOW 6, so you write
nothing. With another backend, the file is refused as soon as it is read.

```toml
# not checked: shows a refused backend
[solver.backend]
backend = "modflow_nwt"

[flow.sinks_sources.flow_barriers.cutoff]
line = [[389200.0, 6816400.0], [389380.0, 6816620.0]]
depths = [10.0]
hydchr = 1e-9
```

```text
solver.backend='modflow_nwt' does not support flow barriers / dam cutoff walls (HFB); they require the 'modflow6' backend.
```

Declaring a barrier is enough to switch it on. It is not listed in
{toml}`flow.active_bc` nor in {toml}`flow.active_sinks_sources`.

(barrier-lake)=
## 5. Or put the wall on a lake

A reservoir with a dam takes its wall as the `cutoff_wall` of the lake, with the same
keys as above.

```toml
base_config = "step1_minimal.toml"

[flow]
active_bc = ["drainage", "lake"]

[flow.sinks_sources.lakes.reservoir]
bedleak = 1e-7
stageinit = "100 m"

[flow.sinks_sources.lakes.reservoir.cutoff_wall]
line = [[389200.0, 6816400.0], [389380.0, 6816620.0]]
depths = [10.0]
hydchr = 1e-9
```

This block shows the wall only. A lake also needs its footprint from the data of the
project: see {doc}`lakes-and-reservoirs <lakes-and-reservoirs>`. Three things differ from
a general barrier.

- A relative `line_path` is resolved against `<workspace>/data/cutoff_wall/`. A bare file
  name that is not there is then looked up in `<workspace>/data/`.
- {toml}`auto|flow.sinks_sources.lakes.<name>.cutoff_wall.auto` `= true` replaces the
  trace. HydroModPy puts the wall on the downstream edge of the reservoir: it takes the
  point of the footprint nearest to the catchment outlet, and draws the wall across the
  reservoir, perpendicular to the direction of the outlet, a little past both banks. It
  needs the outlet of the catchment and the footprint of the lake. A general barrier
  refuses `auto` when the run starts, as the table at the end shows.
- The lake cells that sit downstream of the wall are removed from the lake. The reservoir
  ends at the dam. When the mesh refinement of the lakes is on, the wall is also refined
  with {toml}`dam_cell_size|mesh_catchment.lake_refinement.dam_cell_size` and
  {toml}`hfb_buffer|mesh_catchment.lake_refinement.hfb_buffer`.

```{hmp-params}
flow.sinks_sources.lakes.<name>.cutoff_wall
flow.sinks_sources.lakes.<name>.cutoff_wall.auto
```

## Check that it worked

1. `hmp config check <file>` validates the shape of the barrier: the trace, the vertical
   extent, the resistance and the units. It does not read the trace file, and it does not
   build the mesh, so it cannot tell if the trace falls on the model.
2. Run with `hmp run <file> -v`. The verbose level prints every INFO line, and the builder
   writes one when it creates the package:

   ```text
   HFB cutoff wall: <n> barrier rows over <m> shared faces.
   ```

   `<m>` is the number of faces the trace was mapped onto, `<n>` the number of layer
   rows on them. The line says "cutoff wall" for every barrier, lake or not. When no line
   appears, no barrier reached the solver. The same line is in
   `<project>/.hmp/logs/hydromodpy_debug.log` at any verbosity.
3. To read the package itself, set
   {toml}`keep_solver_files|simulation.results.keep_solver_files` to `true` and open the
   `.hfb` file in the solver folder. The way to find that folder is in
   {doc}`non-convergence <non-convergence>`.
4. To see what the wall does, run the same model with and without the barrier and compare
   the two runs: {doc}`compare-runs <compare-runs>`. A partial wall blocks the flow across
   the trace in the top layers and sends it below.

Two lines of the same log tell you what the builder skipped.

- `<n> HFB row(s) dropped over inactive cells.` Part of the wall sits where a cell is
  inactive. The barrier is not applied there.
- `<n> face(s) sealed at the nearest layer where the band misses the aquifer (fence
  continuity).` With `base_elevation`, the band did not touch the aquifer at some faces.
  HydroModPy seals the nearest active layer instead, so that the fence stays closed.

## What can go wrong

Each message below is printed as written. The name of your barrier replaces `cutoff`.

| Message | Cause | Fix |
|---|---|---|
| `flow barrier needs exactly one geometry source: set auto, line (inline coordinates), or line_path (a vector file).` | The trace is missing, or `line` and `line_path` are both written. | Keep one. |
| `flow barrier needs exactly one vertical extent: set depths (below the top / crest) or base_elevation (an absolute floor), not both and not neither.` | Neither `depths` nor `base_elevation`, or both. | Keep one. |
| `flow barrier needs a resistance source: set hydchr, or both k and thickness.` | Only one of `k` and `thickness`, or none. | Write `hydchr`, or both. |
| `flow barrier resistance is over-specified: set hydchr alone, or k and thickness (without hydchr), not a mix.` | `hydchr` and one of `k`, `thickness` are both written. | Keep one form. |
| `flow barrier line needs at least two vertices.` | A one-point `line`. | Add a vertex. |
| `flow barrier depths must be positive (metres below the top).` | A depth of zero or less. | Write positive depths. |
| `Unsupported leakance unit 'm'. Allowed units: 1/s, 1/day, 1/h, 1/min` | `hydchr_unit` is not an inverse time. `k_unit` and `thickness_unit` are checked the same way, each with its own message. | Give an inverse time for `hydchr_unit`, a velocity for `k_unit`, a length for `thickness_unit`. |
| `solver.backend='modflow_nwt' does not support flow barriers / dam cutoff walls (HFB); they require the 'modflow6' backend.` | A barrier on a backend other than MODFLOW 6. | Use MODFLOW 6. |
| `flow barrier 'cutoff': the trace crosses no interior mesh face. Check the trace CRS and coordinates and that it lies within the model extent and off the mesh edges.` | The trace is outside the model, in another CRS, or does not separate any two cells. | Fix the coordinates and the CRS, or lengthen the trace past the cells it must separate. |
| `flow barrier 'cutoff': depths must have 1 value or one per line vertex (2).` | A `depths` list that matches neither one value nor the vertices. | Write one value, or one per vertex. |
| `flow.sinks_sources.flow_barriers.cutoff line_path '<file>' resolves to a MultiLineString, not a single LineString; provide one contiguous polyline (a branching or multi-part trace is not supported).` | The file holds a branching or a broken trace. | Split it into one barrier per contiguous line. |
| `flow.sinks_sources.flow_barriers.cutoff has neither auto, line, nor line_path.` | `auto = true` on a general barrier. The file check lets it pass, the run refuses it. | Give a `line` or a `line_path`. `auto` is for lake cutoff walls. |
| `flow barrier 'cutoff': resolves to <n> face(s) but every layer joins an inactive cell; no HFB row was emitted.` | A warning, not an error. The trace lies on inactive cells and the barrier has no effect. | Move the trace onto the active domain. |
| `flow.sinks_sources.lakes.reservoir.cutoff_wall auto needs the catchment outlet; only from_outlet_coord catchments expose x_outlet/y_outlet. Give an explicit line instead.` | `auto` on a lake of a catchment that has no outlet point. | Give a `line`. |
| `cutoff wall for lake 'reservoir' classifies every cell as downstream of the voile; check the trace orientation and position.` | Every cell of the lake falls on the outlet side of the wall, so the lake would have no cell. | Move the trace to the dam, downstream of the lake body. |

## Where to go next

- {doc}`lakes-and-reservoirs <lakes-and-reservoirs>`: the lake the cutoff wall belongs to.
- {doc}`choose-a-solver <choose-a-solver>`: the MODFLOW 6 backend.
- {doc}`compare-runs <compare-runs>`: measure the effect of the wall against a run without it.
