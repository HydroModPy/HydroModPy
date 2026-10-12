# Glossary

The terms used in this part of the site, with a short definition. Where a term has a setting in
the configuration file, the second line of its entry says where. A term can be cited from
another page with `` {term}`unconfined aquifer` ``.

On the pages of this part, a term underlined with dots shows its definition when you point at it
or move the keyboard focus to it. On a touch screen, tap it once for the definition and a second
time to open this page.

```{glossary}
:sorted:

actual evapotranspiration
  The part of the {term}`potential evapotranspiration` that is really taken, limited by the
  water available in the soil. Abbreviated AET. The {term}`soil reservoir` computes it.

aquifer
  Rock or sediment saturated with water, which lets the water move and stores it.

aquifer thickness
  Depth of the modeled layer below the ground surface: 30 m in example 04. This is an
  assumption. The {term}`depth to water table` cannot exceed it.

  *In the file:* {toml}`domain.depth_model.thickness`.

available water capacity
  Water that roots can take from the soil, in mm. Abbreviated AWC. It sets how much water the
  soil keeps before it lets water pass to the water table.

  *In the file:* {toml}`flow.sinks_sources.recharge.soil.ru`.

baseflow
  The part of the river flow that comes from the aquifer. In the model: the water that leaves
  the aquifer through the {term}`drains <drain>`, summed over the catchment.

BD Topage
  The reference hydrographic network of France, published by Sandre. HydroModPy can download
  it as a {term}`mapped network`. It is not the same product as the {term}`BD TOPO`.

  *In the file:* {toml}`data.hydrography`.

BD TOPO
  The topographic database of the French national mapping agency (IGN). Example 04 takes its
  {term}`mapped network` from the permanent reaches of this database.

  *In the file:* {toml}`data.hydrography`.

calibration
  Tuning of the model parameters (here K, then Sy) so that its results look like observations.
  A calibrated result is not, for that reason, validated (see {term}`validation`).

  *In the file:* {toml}`calibration.protocol.name`.

catchment
  Surface that gathers water toward a single exit point, the {term}`outlet`. In HydroModPy, it
  is drawn from the relief and the position of the outlet.

  *In the file:* {toml}`geographic.catchment.catch_def`.

cell
  One square of the computation grid: 75 m wide in example 04. The model computes one value per
  cell, and the maps count cells. The set of cells that cuts the model area is the
  {term}`mesh`.

conductance
  How freely a {term}`drain` passes water for a given rise of the water table. Unless you
  declare one, the model derives it from the {term}`hydraulic conductivity` and from the
  thickness of the clogging layer of the drain bed.

  *In the file:* {toml}`solver.drain_bed_thickness_m`.

criterion
  A number that a {term}`calibration` drives toward a target, over many {term}`trials <trial>`.
  It must behave well along that search. The same number, only read, is a {term}`diagnostic`.

depth to water table
  Distance between the ground and the top of the {term}`water table`, in meters, never negative.

  *Figure:* `watertable_depth_map`, in {toml}`display.figures`.

diagnostic
  A number that you read to describe a result, put in a report or use to compare two runs. It
  is not driven to a target. See {term}`criterion`.

digital elevation model
  Map of the ground elevation, on a regular grid. Abbreviated DEM.

  *In the file:* {toml}`data.dem`.

downslope distance
  Distance a cell travels along the slope before it reaches a network. Written $D_{so}$ from
  the simulated network to the mapped one, and $D_{os}$ in the opposite direction. It measures
  how far apart two networks are.

drain
  Condition that lets water leave the aquifer when the water table reaches its elevation, never
  the reverse. In example 04, the drains are placed at the ground surface and their capacity
  (the {term}`conductance`) is deduced from K.

  *In the file:* {toml}`flow.active_bc`.

ensemble
  A set of runs of the same model with different parameters or inputs. The spread between the
  runs shows how much a result depends on those choices. See {doc}`how-sure`.

equifinality
  Several different sets of parameters reproduce the observations about equally well. The
  calibration then cannot say which set is right. See {doc}`how-sure`.

excess
  A cell where the model puts a stream and the map has none. See {term}`valid`.

forcing
  What drives the model through time: the recharge, or the rainfall and the
  {term}`potential evapotranspiration` from which a {term}`soil reservoir` computes it.

GR4J
  A rainfall-runoff model that treats a catchment as a single unit. HydroModPy can calibrate it
  in place of the distributed model.

groundwater
  Water that fills the pores of the ground below the {term}`water table`.

Hub'Eau
  The public interface to French water data. HydroModPy can download the discharge measured at
  a gauging station from its hydrometry service.

  *In the file:* {toml}`data.hydrometry`.

hydraulic conductivity
  How easily the subsurface lets water pass, written K, in m/s. It cannot be measured at the
  scale of a catchment: it is calibrated.

  *In the file:* {toml}`flow.param.K.field.value`.

hydraulic head
  Elevation of the {term}`water table` at a point. It is the unknown that the model computes in
  each cell; the {term}`depth to water table` is deduced from it.

  *In the file (initial state):* {toml}`flow.ic.h.type`.

hydrograph
  Curve of the flow as a function of time.

indicative
  A reliability label. No field measurement was compared with this result. See
  {term}`reliability label`.

initial condition
  State of the water table at the start of the computation. In example 04, a first month in
  {term}`steady state` provides it.

  *In the file:* {toml}`flow.ic.h.type`, {toml}`flow.first_period_steady`.

interfluve
  The higher ground between two valleys. The water table is deep under it.

intermittent flow
  A stream that flows for only part of the year. On the intermittence map: a cell that flows at
  some time steps of the year, not at all of them.

lockfile
  The file `hydromodpy.lock` at the root of a project. It pins the input data by checksum and
  records the version of the code and of the solver binary. See
  {doc}`can-i-check-what-was-run`.

mapped network
  Streams drawn on a map (here, the permanent reaches of the {term}`BD TOPO`). It is a
  reference to compare and calibrate against, not an input to the flow computation.

  *In the file:* {toml}`data.hydrography`.

mesh
  The set of {term}`cells <cell>` that cuts the model area. The word grid means the same
  thing when the cells are squares.

missing
  A cell where the map has a stream and the model puts none. See {term}`valid`.

MODFLOW 6
  The groundwater flow code of the United States Geological Survey (USGS). It is the solver of
  example 04. HydroModPy also runs MODFLOW-NWT, an older code of the same family, and a
  Boussinesq solver written for HydroModPy.

NANCON station
  The gauge at the outlet of the Nançon catchment. Example 04 compares the discharge measured
  there with the simulated one.

  *In the file:* {toml}`data.hydrometry`.

NSE
  Nash-Sutcliffe efficiency: compares simulated and measured flow. 1 is a perfect match, 0 is
  the same as predicting the mean of the measurements, and a negative value is worse. The "log"
  variant computes it on the logarithms to give weight to low flows.

  *In the file:* {toml}`calibration.protocol.transient_metric`.

numerical check
  A reliability label. An internal check of the computation, independent of the
  {term}`calibration`. See {term}`reliability label`.

objective
  What a {term}`calibration` tries to reach: one or several {term}`criteria <criterion>`, each
  computed on an observation such as the stream network or the discharge.

  *In the file:* {toml}`calibration.objective_blocks.metric`.

outlet
  Exit point of the catchment, where the flow is measured.

  *In the file:* {toml}`geographic.catchment.x_outlet`.

percent bias
  Volume gap between the simulated flow and the measured flow, as a percentage of the measured
  volume. Abbreviated PBIAS. It is positive when the model underestimates, that is when it is
  too dry, and negative when it overestimates.

perennial flow
  A stream that flows all year. On the intermittence map: a cell that flows at every time step
  of the year.

persistence
  Share of the time steps during which a cell flows, over the whole simulation.

potential evapotranspiration
  Amount of water that the atmosphere could take back from a soil that is well supplied with
  water. Abbreviated PET.

  *In the file:* {toml}`data.etp`.

provenance
  The record of what produced a result: the version of the code, the solver, the input files and
  their checksums. See {doc}`can-i-check-what-was-run`.

reach
  A stretch of stream between two points.

reanalysis
  A gridded estimate of past weather or hydrology, made by running a model over all the
  observations available. {term}`SIM2` is one.

recharge
  Water that reaches the water table from the soil. It is supplied, or computed by a soil
  reservoir.

  *In the file:* {toml}`flow.sinks_sources.recharge`, {toml}`data.recharge`.

reliability label
  One of three words that tell how far a result can be trusted: {term}`numerical check`,
  {term}`calibrated <calibration>` and {term}`indicative`. They are used under every figure of
  {doc}`reading-results`.

resolution
  The size of one {term}`cell`, 75 m in example 04. A feature smaller than the resolution is
  not drawn.

runoff
  Water that reaches the stream without passing through the water table. In example 04, it is
  given to the model as data and is added to the drainage to form the simulated flow.

  *In the file:* {toml}`data.runoff`.

scoring window
  Period over which the calibration compares simulated and measured flow. In example 04, 2001
  and 2002; the year 2000 is used as {term}`spin-up`.

  *In the file:* {toml}`calibration.protocol.scoring_window`.

seepage
  Cell where the {term}`water table` reaches the ground surface and where water leaves the
  aquifer.

  Rebuilt on read from the head and the ground surface (or from the surface excess of a
  Boussinesq run); nothing to set.

seepage threshold
  Fraction of its own recharge that a cell must give back to count as seepage: 0.01 % by
  default. Another threshold changes the network maps.

  *In the file:* {toml}`calibration.outputs.<name>.tau_specific_ratio`.

SIM2
  Météo-France reanalysis on an 8 km grid, which supplies rainfall and potential
  evapotranspiration to the soil reservoir.

  *In the file:* {toml}`data.etp`.

simulated network
  Extension downstream, following the slope of the terrain, of the cells where the aquifer
  gives water back to the surface. It does not result from a hydraulic river computation.

soil reservoir
  Simple daily balance: the soil fills with rain, empties by evapotranspiration and lets the
  surplus pass to the water table.

  *In the file:* {toml}`flow.sinks_sources.recharge.soil`.

specific yield
  Share of the rock volume that drains when the water table falls, written Sy, without
  dimension. It sets the speed at which the water table empties and refills.

  *In the file:* {toml}`flow.param.Sy.field.value`.

spin-up
  Start of the simulation that is not scored, while the initial state of the model fades out.
  In example 04, the year 2000.

  *In the file:* {toml}`calibration.protocol.scoring_window`.

spring
  A place where groundwater comes out of the ground. A {term}`seepage` cell is a spring of
  the model.

steady state
  Computation where nothing changes with time: the recharge is a constant mean.

  *In the file:* {toml}`flow.flow_regime`.

stream head
  The upstream end of a stream, where it starts to flow. The heads dry up first in summer.

stress period
  Interval over which the {term}`forcing` is held constant. It is one month in example 04. The
  solver may cut it into smaller time steps.

  *In the file:* {toml}`simulation.time.step_value`, {toml}`simulation.time.substeps_per_period`.

time step
  On the maps and curves of this part of the site, the unit of time of the results: one month
  in example 04. Strictly, the month is a {term}`stress period` and the solver may cut it into
  smaller steps.

TOML
  The plain-text format of the configuration file. One TOML file describes a whole run. The
  files of example 04 are walked through in {doc}`../get-started/index`.

transient
  Computation where the recharge and the water table vary from one time step to the next.

  *In the file:* {toml}`flow.flow_regime`.

trial
  One run of the model with one set of parameter values, tried by a {term}`calibration`. A
  calibration runs many trials and keeps the best.

unconfined aquifer
  Aquifer whose top is not trapped under an impermeable layer: it rises and falls freely with
  the recharge. HydroModPy targets this type of aquifer.

uncertainty
  How far a result could be from the truth. See {doc}`how-sure`.

valid
  A cell where the simulated network and the mapped network both pass. With {term}`excess`
  and {term}`missing`, it gives the three classes of the confusion map.

validation
  A comparison of a model with measurements that the {term}`calibration` has not seen. See
  {doc}`what-validated-means`.

visible flow
  Minimum flow that a cell must carry to count as "flowing" on the persistence maps: 1 L/s by
  default. It is a convention.

  *In the file:* {toml}`calibration.outputs.<name>.extent.visible_flow`.

water budget
  What enters the aquifer (recharge), what leaves it (drainage) and the change in storage. Its
  closure is a numerical check of the solver.

water table
  The top of the {term}`groundwater`: the level below which the ground is saturated. The model
  computes its elevation in every cell, as the {term}`hydraulic head`.
```
