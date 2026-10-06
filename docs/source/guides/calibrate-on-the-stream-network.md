# Calibrate on the stream network

You have a map of the streams of a catchment and you want the model to produce the same
network. HydroModPy moves the conductivity K until the cells where the aquifer feeds the
surface reach as far as the mapped streams. It can then fit the storage Sy to a gauge.

The first stage identifies the ratio K/R of conductivity to recharge, not K alone. This guide
says how to declare the map, run the search and read the result. What the criterion
measures, and which way its known biases point, is in {doc}`../theory/downslope-distance`.
The picture of how the model makes streams is in {doc}`../understand/stream-network`.

## What you need first

- A project that runs in transient mode. The worked case is example 04,
  `examples/projects/04_streamflow_intermittence_in_transient`. The blocks below are merged
  on its files and checked.
- The mapped network as a vector file (GeoPackage, Shapefile, GeoJSON), in lines.
- Drains at the ground surface: {toml}`flow.active_bc` lists `"drainage"`. Leave the
  conductance {toml}`flow.bc.drainage.value` at zero, so each drain takes
  `C = K * cell_area / drain_bed_thickness_m` from the K the search moves
  ({toml}`solver.drain_bed_thickness_m`). That proportionality is what makes the search
  identify K/R. `hmp config targets project.toml` lists `drainage` with its current value.
- A recharge that does not move during the search. Keep the recharge out of
  {toml}`calibration.parameters` and out of anything the first stage changes.
- A conductivity written as one number, {toml}`flow.param.K.field.value`. The report gives
  K/R only for that case.
- No SFR or LAK package in {toml}`flow.active_bc`. Both build their own conductance, and the
  search is refused with them (see {ref}`network-problems`).
- For the second stage, a gauge in {toml}`data.types` and a station in
  {toml}`data.hydrometry.sources`.

```{hmp-resolved} flow.bc.drainage.value
:config: project.toml
```

## 1. Write the calibration file

A calibration file inherits the project and adds the search. This one declares the two
parameters, the mapped network and the method:

```toml
base_config = "step4_transient.toml"

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "nancon_stream_network.gpkg"

[calibration.protocol]
name = "matching_hydrographic_network"
```

The section name under {toml}`calibration.parameters` is the quantity. `K` and `Sy` are resolved
against the project, so you write the range and no path. `hmp config targets` prints the
names a project carries. A conductivity is searched in log space without a word from you.

```{hmp-params}
calibration.parameters.<name>.bounds
calibration.parameters.<name>.transform
```

The protocol name {toml}`calibration.protocol.name` writes the two stages for you:

1. Stage one moves K alone, in steady state, until the simulated network matches the map.
   It is a root search by bisection on the signed gap between the two networks.
2. Stage two moves Sy alone, in transient, with K frozen, on the discharge of the gauge.
   It scores from one year after the start of the run, because the first year is spin-up.

The gauge needs no declaration. The protocol reads the station of
{toml}`data.hydrometry.sources`. With several stations, name one in
{toml}`calibration.protocol.observed_station_id`.

```{hmp-params}
calibration.protocol.name
calibration.protocol.conductivity
calibration.protocol.storage
calibration.protocol.network_output
calibration.protocol.steady_window
calibration.protocol.scoring_window
```

`hmp calibrate run_calibration.toml --expand` prints the stages a protocol writes, as TOML,
so you see what runs. Every key of `[calibration.protocol]` is a card of the
{doc}`reference <../reference/parameters/calibration/protocol>`. A file that names a protocol
cannot declare phases or objective blocks that differ from the ones the protocol writes. A child file that inherits a protocol and
wants its own stages drops the name with `protocol__delete = true` under `[calibration]`.

## 2. Point at the mapped network

The output {toml}`calibration.outputs.<name>` with `support = "network"` holds the map. Its name is yours.
Exactly one of two keys says where the map comes from.

```{hmp-params}
calibration.outputs.<name>.stream_geometry_path
calibration.outputs.<name>.observed_network
```

- {toml}`stream_geometry_path|calibration.outputs.<name>.stream_geometry_path` is a vector
  file. A relative path is looked for from the folder of the calibration file, then from its
  parent and its grandparent. A bare file name is also looked for under `data/hydrography/`
  of each of the three.
- {toml}`observed_network|calibration.outputs.<name>.observed_network` takes
  `"data.hydrography"`, which reuses the network that {toml}`data.hydrography` already
  loaded (a local file, or a BD Topage, OSM or EU-Hydro download), clipped to the
  catchment. It takes `"geographic.river_network"` too, a network derived from the DEM.
  That one fits a seepage density onto a geomorphological one, so the run warns and records it.

The map is the target. It is never an input of the model. Keep it out of anything the
simulation reads.

```{hmp-resolved} calibration.outputs.seepage_network.stream_geometry_path
:config: run_calibration.toml
```

To read the same map from the data section instead:

```toml
base_config = "run_calibration.toml"

[calibration.outputs.seepage_network]
stream_geometry_path__delete = true
observed_network = "data.hydrography"
```

### Check that the map follows the model

The criterion measures lengths along the flow paths of the model top. A map that does not
follow those paths makes it measure a disagreement between two datasets. HydroModPy does not
edit the model top to hide it. Two numbers tell you how large it is.

- The geographic step measures `alpha` when {toml}`data.hydrography.sources` holds a local
  vector file (`source = "custom"`). Alpha is the share of the downstream closure of the map,
  on the D8 pointer of the routing DEM, that the map already covers. The step writes it to
  `stream_dem_agreement.json` in the geographic folder and warns when it is low. An API
  source is not downloaded for this: the step logs that alpha needs a custom vector source.
  With no usable source, alpha does not run and nothing else changes.
- Each trial of the search publishes `alpha_obs_closure_catchment`, measured on the model
  top and on the catchment. The run warns once below
  {toml}`alpha_warning_threshold|calibration.outputs.<name>.alpha_warning_threshold`.
  Judge a trial on this one. A low value is a fact about the top and the map. It is not an
  instruction to edit the model top.

## 3. Choose how the map is drawn on the mesh

The criterion needs the map as cells. {toml}`calibration.outputs.<name>.observed_rasterization`
decides how.

```{hmp-params}
calibration.outputs.<name>.observed_rasterization
calibration.outputs.<name>.heads_snap_radius
calibration.outputs.<name>.heads_min_drained_area_km2
```

- `"heads"` keeps only the free ends of the mapped lines, where a stream
  starts, and draws the rest down the descent of the model. A mapped path below a head follows
  fields, ditches and rectified reaches that a drain model on a DEM cannot reproduce, so
  scoring it cell by cell would count false error. Each head lands on the nearest cell
  within {toml}`heads_snap_radius|calibration.outputs.<name>.heads_snap_radius`
  that drains at least
  {toml}`heads_min_drained_area_km2|calibration.outputs.<name>.heads_min_drained_area_km2`.
  A head with no such cell is lost, and the trial counts it in `n_heads_lost`. The drawn
  map reaches the outlet by construction. When a lake declares a spillway, the foot of its dam
  is a head too (see {doc}`lakes-and-reservoirs`).
- `"crossing"` matches the published method. A cell belongs to the map when a line crosses the
  segment joining two edge-sharing cell centres. Use it for a map that is not a tree: a canal
  or a diversion across a divide, a braided reach, a polder, a karst system that loses flow
  underground. The heads rule assumes that a free end is a head or the outlet.
- `"touch"` keeps every cell the line touches, corners included. It replays a session made
  before 2026-09. Prefer the other two for a new one.

```toml
base_config = "run_calibration.toml"

[calibration.outputs.seepage_network]
observed_rasterization = "crossing"
```

`observed_network_heads_map` redraws the heads, the lost ones and the trace they draw (see
{ref}`network-figures`).

## 4. Set how strictly the agreement is judged

Equation 4 of the published method qualifies the result: the calibration is valid when the
mean mismatch between the two networks stays within a validity length. The bound never changes
the cost. It adds a verdict to the value the search returns.

```toml
base_config = "run_calibration.toml"

[calibration.outputs.seepage_network]
weighting = "area"
validity_length = "300 m"
on_roptim_violation = "error"
```

```{hmp-params}
calibration.outputs.<name>.weighting
calibration.outputs.<name>.validity_length
calibration.outputs.<name>.observed_position_accuracy
calibration.outputs.<name>.on_roptim_violation
calibration.outputs.<name>.max_unreachable_fraction
```

- {toml}`weighting|calibration.outputs.<name>.weighting`: use `"area"` as soon as the mesh is
  refined along the streams. An unweighted mean then over-samples the river corridor, where
  distances are smallest. Both weightings are always reported.
- {toml}`validity_length|calibration.outputs.<name>.validity_length`: `"auto"` is two cells of
  the mesh where the map lies. A length such as `"300 m"` replaces it.
- {toml}`on_roptim_violation|calibration.outputs.<name>.on_roptim_violation`: `"warn"` logs a
  violation and returns the value. `"error"` raises after the session is saved, so a staged
  calibration freezes nothing and runs no phase that depends on this one.
- Leave {toml}`tau_specific_ratio|calibration.outputs.<name>.tau_specific_ratio` alone. It
  is frozen for the whole search, because a threshold that moved with the trial would cost
  the criterion its monotonicity.

## 5. Check the file

Nothing solves in these three commands.

```console
$ hmp config check run_calibration.toml
$ hmp calibrate run_calibration.toml --list-phases
$ hmp calibrate run_calibration.toml --check
```

`--list-phases` prints each stage, its method, the output it scores and the map or station it
compares to. `--check` runs every check the search needs and reports all the problems at once,
not the first. It ends with `run_calibration.toml: ready to run.` when none is left. It names
what a protocol does differently from the paper, for instance the rasterization rule.

## 6. Run it

```console
$ hmp calibrate run_calibration.toml
```

`hmp run run_calibration.toml` does the same, since the file sets `mode = "calibration"`. The two
stages run in declaration order. `--phase` selects one stage, and it accepts only a stage that
depends on no other. To run stage two, run both. {toml}`calibration.rerun_best_with_outputs`
replays the best trial of each stage as a full run with its figures and exports.

## 7. Read the result

The command prints, per stage, the calibrated value, the cost and what the search proved
around it. For stage one:

```text
  K = ...
  cost: ...
  k_over_r = ... against R_mean_m_s = ... m/s on output 'seepage_network', k_optim = ... m/s
  roptim (seepage_network) = ..., Doptim = ... m <= ... m (auto), Eq. 4 holds
  bracket on K: [..., ...], width ...% (closed)
  search: converged on its rule (...), ... evaluation(s) of ... declared
```

- The bracket is the interval on K whose two ends change the sign of the residual. It is
  the proof beyond the value returned. A `(open, the budget ran out first)` bracket means the
  search stopped before it closed.
- `roptim` and `Eq. 4` are the verdict of step 4, read on the returned trial only.
  `Doptim` is the mean mismatch in metres. The verdict qualifies the value. It does not say
  the value is wrong, and it measures agreement, not correctness.
- `k_over_r` appears only when the search moved the homogeneous conductivity alone. The same
  line carries `d_sat_m`, `t_over_r_m` and `t_optim_m2_s` when the solver serves a saturated
  thickness. It warns when the aquifer runs more than half full, because T/R then depends on
  the imposed thickness.

Every trial is also written to the project, under `sessions/<name>/`: `session.json` for the
search and `trials.jsonl` for one line per trial. Each diagnostic of a network output carries
the name of the output, for instance `seepage_network.J_signed`. They are written whether or
not a run is promoted. Read these first:

| Key | What it says |
|---|---|
| `J_signed` | The signed residual the search brackets. Its sign says which side of the balance the trial is on. |
| `D_so`, `D_os` | The mean downslope distance from the simulated network to the map, and the reverse. |
| `roptim`, `roptim_valid`, `validity_length_m`, `validity_length_provenance` | The ratio of the mismatch to the cell size, the Equation 4 test, and what set the length. |
| `R_mean_m_s` | The recharge the criterion read back from the built model. It is the denominator of K/R. A move between two builds raises a warning naming both values. |
| `alpha_obs_closure_catchment`, `frac_obs_outside_catchment` | The agreement between the map and the model top on the scored catchment, and the share of the map outside it. |
| `frac_unreachable_so`, `frac_unreachable_os` | The share of each network whose descent never meets its target. Only the first is bounded. |
| `n_valid`, `n_excess`, `n_missing` | Cells where both networks agree, where only the model has a stream, where only the map has one. |
| `n_heads`, `n_heads_lost`, `n_forced_heads` | Under `"heads"`: heads landed, heads lost, dam feet added. |
| `catchment_mismatch` | The area gap between the catchment the criterion scores and the delineated one. A value above 0.05 logs a warning. |

(network-figures)=
### Look at it

The figures are declared, never scripted. List them in {toml}`display.figures`, in the project
or in the calibration file, and the promoted run draws them. The three network maps need a
per-cell `release_flux`, set by {toml}`simulation.results.derived.release_flux`, a mapped
network stored with the run, and a delineated watershed.

```toml
base_config = "run_calibration.toml"

[display]
figures__append = [
    "seepage_network_reference_overlay",
    "seepage_network_confusion_map",
    "downslope_distance_map",
    "downslope_distance_crossing",
    "bisection_bracket_trace",
    "parameter_cost_profile",
    "matching_hydrographic_network_card",
    "observed_network_heads_map",
    "hydrograph_log_nse",
]
```

- `seepage_network_reference_overlay` draws the simulated network over the mapped one. Open
  it before you trust a number: a residual near zero is compatible with a network that
  ignores the talwegs.
- `seepage_network_confusion_map` draws where the two networks agree, where the model has too
  much stream and where it has too little.
- `downslope_distance_map` draws the distance field behind `D_so` or `D_os`, in four classes.
- `downslope_distance_crossing` and `bisection_bracket_trace` show the root: the two
  distances against K, and the bracket closing on the zero of the residual.
- `parameter_cost_profile` shows how lopsided the cost is around the value returned.
- `matching_hydrographic_network_card` puts both stages on one page.
- `hydrograph_log_nse` draws the discharge on the log axis stage two scores it on.

Their options are on the cards of {doc}`../reference/figures`. A figure that cannot be drawn
says which input is missing. For the flux it prints:

```text
run has no per-cell release_flux: set [simulation.results.derived] release_flux = true
```

### What to publish

Publish the ratio, not the conductivity. The recharge series gives K its value: state it beside
the number. State the density of the mapped network too, because the bias of the criterion
grows as the map is thinned. The theory page gives the direction of each bias.

## Variant: calibrate K without a gauge

Stage one is a method of its own. {toml}`calibration.protocol.storage` defaults to `Sy`, and a
TOML file has no null to turn the second stage off. Skip the protocol and write the single
stage by hand. The objective block names the criterion: `distance_gap` is the signed gap
between the two downslope distances, and its zero is the balance the search solves for.

```toml
base_config = "step4_transient.toml"

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "nancon_stream_network.gpkg"

[[calibration.objective_blocks]]
name = "network_extension"
metric = "distance_gap"
uses_outputs = ["seepage_network"]

[[calibration.phases]]
name = "steady_conductivity"
parameters = ["K"]
regime = "steady"
objective_blocks = ["network_extension"]
method = "bisection"
```

```{hmp-params}
calibration.objective_blocks.metric
calibration.phases.regime
calibration.phases.method
calibration.phases.max_iter
```

`bisection` is a root search, not a minimiser. It stops on the width of the bracket, never on
the size of the residual, which is a step function that may never get small. It searches one
parameter, and that parameter must be searched in log space (the
{toml}`transform|calibration.parameters.<name>.transform` card says how a conductivity gets
it). With {toml}`calibration.phases.max_iter` left at `"auto"`, the search counts the
evaluations it needs before the first solve. A smaller number is refused by `--check`.

`examples/projects/04_streamflow_intermittence_in_transient/run_calibration_by_hand.toml`
writes the two stages of the protocol as phases. It runs the same trials. The only thing it
loses is the citation and the list of deviations from the paper that a protocol run records.

(network-two-bounds)=
## Score K on two maps and two bounds

One mapped network is one definition of "flowing". A transient run can be scored on two: the
reaches that flow all year, and the reaches that flow at some time of the year. For every
complete calendar year of the run, HydroModPy builds a minimal and a maximal simulated
extent, and compares each to its own map. This is an option of the network output. It works
in any phase, hand-written or expanded from a protocol.

### Declare the two maps

The maximal map is every reach of the map you declared in step 2. A minimal map, the
permanent reaches, is declared beside it. The maximal map scored is the union of the two
files, so wherever they disagree the wider of the two is scored. `frac_minimal_outside_maximal`
publishes how much they disagreed. It is a property of the two files, not of the model.

```toml
base_config = "run_calibration.toml"

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "complete_network.gpkg"
minimal_stream_geometry_path = "permanent_network.gpkg"
```

```{hmp-params}
calibration.outputs.<name>.minimal_stream_geometry_path
calibration.outputs.<name>.minimal_observed_network
```

{toml}`minimal_observed_network|calibration.outputs.<name>.minimal_observed_network` takes
`"data.hydrography"` and reads the permanent reaches that the hydrography data family wrote
beside its own network. It can do so only when the source says which reaches are permanent,
BD Topage among them. Declare one route for the minimal map, never both. The map is read as it
is: no attribute filter runs in a calibration.

With both maps and no `extent` table, the one scored state is compared to the minimal map.
The maximal map is scored at the same state as a validation, published with the suffix
`_maximal_validation`, and never enters the cost.

### Declare the extent table

An `extent` table switches the output from one state to every complete calendar year of a
transient run:

```toml
base_config = "run_calibration_bdtopage.toml"

[calibration.outputs.seepage_network.extent]
maximal_flowing_steps = 1
minimal_dry_steps     = 1
year_quorum           = 0.5
visible_flow          = "1 L/s"

[calibration.outputs.seepage_network.extent.weights]
minimal = 0.5
maximal = 0.5
```

```{hmp-params}
calibration.outputs.<name>.extent.maximal_flowing_steps
calibration.outputs.<name>.extent.minimal_dry_steps
calibration.outputs.<name>.extent.year_quorum
calibration.outputs.<name>.extent.visible_flow
calibration.outputs.<name>.extent.weights.minimal
calibration.outputs.<name>.extent.weights.maximal
```

For each complete year, two masks are built from the number of timesteps each cell flowed.
A timestep belongs to the year its midpoint falls in, and a year the run does not cover
whole is dropped.

- The maximal mask holds the cells that flow at least
  {toml}`maximal_flowing_steps|calibration.outputs.<name>.extent.maximal_flowing_steps`
  timesteps of the year.
- The minimal mask holds the cells that flow at every timestep but at most
  {toml}`minimal_dry_steps|calibration.outputs.<name>.extent.minimal_dry_steps`.

Both count timesteps, never days. With 12 monthly steps and `maximal_flowing_steps = 1`, a
cell flows one month out of twelve. The same value on a daily run asks one day out of 365. A
cell enters the mask that is compared to the map when it meets the rule in
`ceil(year_quorum * n_years)` scored years. Under three scored years the run warns, because
with two years a quorum of one half is their union.

A cell flows at a timestep when it lies downstream of the seepage cells and, unless
{toml}`visible_flow|calibration.outputs.<name>.extent.visible_flow` is `"0 L/s"`, when the
discharge routed to it reaches that threshold. Write it as a discharge with its unit
(`"1 L/s"`, `"0.002 m3/s"`) or as a share of the outlet discharge (`"1%"`). A bare number is
refused. The threshold is never scaled with the cell size. No value is agreed in the
literature.

Each bound is scored once by the same distance criterion as a single state. With one map only,
the maximal bound alone is scored. Each year is also scored as a diagnostic, as
`J_signed_<bound>_y<year>`.

### Write the phase

The two-bound mode reads the timesteps of a transient run, so the phase that moves K is
transient. A `scoring_window` keeps only the complete years it holds, which is how the spin-up
year leaves the score. This is the K stage of `run_calibration_bdtopage.toml`, with the two
maps written as files:

```toml
base_config = "step4_transient.toml"

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "complete_network.gpkg"
minimal_stream_geometry_path = "permanent_network.gpkg"

# 2000 is spin-up, so two years are scored: a cell has to meet the rule in both.
[calibration.outputs.seepage_network.extent]
year_quorum = 1.0

[[calibration.objective_blocks]]
name = "network_extent"
metric = "distance_gap"
uses_outputs = ["seepage_network"]

[[calibration.phases]]
name = "transient_conductivity"
parameters = ["K"]
regime = "transient"
objective_blocks = ["network_extent"]
method = "bisection"

[calibration.phases.scoring_window]
start = "2001-01-01"
```

```{hmp-resolved} calibration.outputs.seepage_network.extent.year_quorum
:config: run_calibration_bdtopage.toml
```

### Read two roots

Each bound has its own root, K*_minimal and K*_maximal. One bisection sweep brackets both
residuals on the same trials. The value the search returns is the weighted geometric mean of
the two roots, with the {toml}`weights|calibration.outputs.<name>.extent.weights`, which must
sum to one. That value is then solved once more as an ordinary trial, so every number
published beside it comes from a real solve. The equations are in
{doc}`../theory/downslope-distance`.

The command prints one line per bound, then the spread and the value:

```text
  K*_minimal = ..., bracket [..., ...], width ...% (closed)
  K*_maximal = ..., bracket [..., ...], width ...% (closed)
  Delta = log10(K*_maximal / K*_minimal) = ... decade(s)
  K = ..., weighted geometric mean of the two roots (0.5 / 0.5)
```

Read `Delta` as the spread. A large one means no homogeneous K holds both maps. The report has
no single bracket in this mode, because an interval around one value has no meaning between
two roots.

- A weight of zero removes that bound from the search. `minimal = 1` and `maximal = 0`
  give one root on the permanent map. Weights other than the defaults without a minimal map
  are refused.
- A minimising method has no root to combine, so it minimises the weighted sum of the two
  absolute residuals. That sum tends to settle at one of the two roots. Keep the bisection
  here.
- With two bounds, only the suffixed keys exist: `J_signed_minimal`, `J_signed_maximal`,
  `roptim_minimal`, `roptim_maximal`, `weight_minimal` and `weight_maximal`. There is no
  unsuffixed `J_signed`, so a root search pointed at one finds nothing rather than closing on
  the wrong bound. The verdict follows: `roptim_verdict` publishes one entry per bound.
- `n_bounds_scored` is 1 or 2. The extent mode adds `n_years_scored`, `first_year_scored`,
  `last_year_scored`, `n_steps_min_per_year` and the rules it applied.

`network_extent_bounds_map` draws the two simulated extents against the two stored maps
without any search. Point {toml}`display.figures` at it on a run that stored the complete and
the permanent network.

State the deviations beside the calibrated value. A run with an `extent` table departs from the
papers on five points: it scores transient masks over calendar years, counts duration in
timesteps, uses a quorum across years, uses a visible-flow threshold on top of the geometric
closure, and combines two bounds with declared weights.

(network-problems)=
## What can go wrong

`--check` and the first trial find most of these before the budget is spent.

A file with no map source does not load:

```text
calibration output declares neither 'observed_network' nor 'stream_geometry_path': the mapped network has no source. Pick one of 'data.hydrography', 'geographic.river_network', or set 'stream_geometry_path' to an explicit file.
```

Both keys together do not load either. Declare exactly one. The minimal map follows the same rule
with `minimal_observed_network` and `minimal_stream_geometry_path`: declare at most one.

A map file that is not found stops the run at the first trial. `--check` says so:

```text
stream_geometry_path 'x.gpkg' is not there, and none of the places the run looks holds it. The criterion resolves no geometry of its own, so the run would stop at the first trial.
```

A fixed drain conductance stops a search that moves K. The message ends with the fix:

```text
Set the value to zero.
```

Set {toml}`flow.bc.drainage.value` to zero, or remove the key. SFR and LAK stop it too. Their
conductance does not follow K, so the K/R of the criterion would mean something else. The
message starts with `Network calibration output(s) 'seepage_network' move a hydraulic conductivity
while`. Remove the package from {toml}`flow.active_bc` for this calibration.

A time selector that reads several states does not load:

```text
a network output reads exactly one state, 'last', 'first' or one date. A transient comparison of the minimal and maximal extents is the 'extent' table of the output, not this field.
```

An `extent` table beside {toml}`calibration.outputs.<name>.time` other than `"last"` does not
load. Drop `time`. An `extent` table on an output that a steady stage scores is refused by
`--check`:

```text
declares an extent table and is scored by a steady search
```

Score that output in one state, without the table, or run the search transient.

Weights that do not sum to one do not load. Weights other than the default without a minimal map
do not either:

```text
the extent table weighs the bounds (minimal = 0.7, maximal = 0.3) and no minimal map is declared, so only the maximal bound is scored. Declare 'minimal_stream_geometry_path' or 'minimal_observed_network', or drop the weights.
```

An extent rule the run cannot read is refused at the first trial, not by `--check`. This happens
when `maximal_flowing_steps` is above the number of timesteps of the shortest complete year, when
`minimal_dry_steps` is so large that fewer than `maximal_flowing_steps` flowing steps are left,
or when the run holds no complete calendar year. The message starts with
`the extent table cannot be read on this run:` and lists each cause. A `scoring_window` that
holds no complete year is refused by name, and says which years it left out.

A residual that keeps one sign over the whole bracket has no root. The search stops and names
both ends:

```text
the residual keeps the same sign over the whole bracket:
```

The search widens the interval by a decade on each side up to `bracket_expand` times before it
gives up. A root found outside your declared bounds is returned with a warning that starts with
`The root closed on`. Several decades out usually means the residual stopped responding to K,
not that K is surprising. Check `n_excess` at the low end of the sweep: it should collapse as K
rises.

A bisection on a parameter with another transform than `"log"` is refused, with the text
`Declare transform = "log" for this parameter.` It also refuses a space of two parameters. A
stage that moves K and Sy together is not a root search.

A simulated network that never reaches the map stops the trial:

```text
frac_unreachable_so = ... of the simulated network never reaches the mapped one, over the ...% bound.
```

The routing surface still holds depressions. Condition the surface, or raise
{toml}`max_unreachable_fraction|calibration.outputs.<name>.max_unreachable_fraction` knowing what
it buys.

A recharge that changes between two builds is not refused, but it logs:

```text
The mean recharge moved between two network criterion builds:
```

Freeze the recharge for the whole session. Otherwise the bound of one per cent on the
conductivity does not hold, and `R_mean_m_s` tells you by how much it moved.

A stage that does not converge leaves the session `partial`. Nothing is frozen, and a stage that
depends on it is refused. Run both again with a larger {toml}`calibration.phases.max_iter`: the
trials already solved come back from the cache. `--phase transient_storage` alone is refused:

```text
Running 'transient_storage' alone would calibrate it against un-frozen parameters.
```

## Where to go next

- What the criterion measures, and which way each bias points:
  {doc}`../theory/downslope-distance`.
- The general calibration guide, with other targets: {doc}`calibrate`.
- Calibrations to start from: {doc}`calibration-recipes`.
- How wide the value is: {doc}`calibration-uncertainty`.
- A run that does not converge: {doc}`non-convergence`.
- Every key of the calibration section: {doc}`../reference/parameters/calibration/index`.
- The command and its options: {doc}`../reference/cli/calibrate`.
