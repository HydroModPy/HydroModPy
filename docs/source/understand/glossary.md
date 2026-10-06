# Glossary

The terms used in this part of the site, with a short definition and, where one exists, the
configuration file parameter linked to it. A term can be cited from another page with
`` {term}`unconfined aquifer` ``.

```{glossary}
:sorted:

actual evapotranspiration
  The part of the potential evapotranspiration that is really taken, limited by the water
  available in the soil. Abbreviated AET. The soil reservoir computes it.

aquifer
  Rock or sediment saturated with water, which lets the water move and stores it.

aquifer thickness
  Depth of the modeled layer below the ground surface: 30 m in example 04. This is an
  assumption. The water table depth cannot exceed it. Parameter:
  {toml}`domain.depth_model.thickness`.

available water capacity
  Water that roots can take from the soil, in mm. Abbreviated AWC. It sets how much water the
  soil keeps before it lets water pass to the water table. Parameter:
  {toml}`flow.sinks_sources.recharge.soil.ru`.

baseflow
  The part of the river flow that comes from the aquifer. In the model: the water that leaves
  the aquifer through the drains, summed over the catchment.

calibration
  Tuning of the model parameters (here K, then Sy) so that its results look like observations.
  A calibrated result is not, for that reason, validated. Parameter:
  {toml}`calibration.protocol.name`.

catchment
  Surface that gathers water toward a single exit point, the outlet. In HydroModPy, it is drawn
  from the relief and the position of the outlet. Parameter:
  {toml}`geographic.catchment.catch_def`.

cell
  One square of the computation grid: 75 m wide in example 04. The model computes one value per
  cell, and the maps count cells.

depth to water table
  Distance between the ground and the top of the water table, in meters, never negative.
  Figure: `watertable_depth_map`, in {toml}`display.figures`.

digital elevation model
  Map of the ground elevation, on a regular grid. Abbreviated DEM. Parameter: {toml}`data.dem`.

downslope distance
  Distance a cell travels along the slope before it reaches a network. Written $D_{so}$ from
  the simulated network to the mapped one, and $D_{os}$ in the opposite direction. It measures
  how far apart two networks are.

drain
  Condition that lets water leave the aquifer when the water table reaches its elevation, never
  the reverse. In example 04, the drains are placed at the ground surface and their capacity is
  deduced from K. Parameter: {toml}`flow.active_bc`.

hydraulic conductivity
  How easily the subsurface lets water pass, written K, in m/s. It cannot be measured at the
  scale of a catchment: it is calibrated. Parameter: {toml}`flow.param.K.field.value`.

hydraulic head
  Elevation of the water table at a point. It is the unknown that the model computes in each
  cell; the water table depth is deduced from it. Initial state parameter:
  {toml}`flow.ic.h.type`.

hydrograph
  Curve of the flow as a function of time.

initial condition
  State of the water table at the start of the computation. In example 04, a first month in
  steady state provides it. Parameters: {toml}`flow.ic.h.type`,
  {toml}`flow.first_period_steady`.

intermittent flow
  A stream that flows for only part of the year. On the intermittence map: a cell that flows at
  some time steps of the year, not at all of them.

mapped network
  Streams drawn on a map (here, the permanent reaches of the BD TOPO). It is a reference to
  compare and calibrate against, not an input to the flow computation. Parameter:
  {toml}`data.hydrography`.

NSE
  Nash-Sutcliffe efficiency: compares simulated and measured flow. 1 is a perfect match, 0 is
  the same as predicting the mean of the measurements, and a negative value is worse. The "log"
  variant computes it on the logarithms to give weight to low flows. Parameter:
  {toml}`calibration.protocol.transient_metric`.

outlet
  Exit point of the catchment, where the flow is measured. Parameter:
  {toml}`geographic.catchment.x_outlet`.

percent bias
  Volume gap between the simulated flow and the measured flow, as a percentage of the measured
  volume. Abbreviated PBIAS. It is positive when the model underestimates.

perennial flow
  A stream that flows all year. On the intermittence map: a cell that flows at every time step
  of the year.

persistence
  Share of the time steps during which a cell flows, over the whole simulation.

potential evapotranspiration
  Amount of water that the atmosphere could take back from a soil that is well supplied with
  water. Abbreviated PET. Parameter: {toml}`data.etp`.

recharge
  Water that reaches the water table from the soil. It is supplied, or computed by a soil
  reservoir. Parameters: {toml}`flow.sinks_sources.recharge`, {toml}`data.recharge`.

runoff
  Water that reaches the stream without passing through the water table. In example 04, it is
  given to the model as data and is added to the drainage to form the simulated flow.
  Parameter: {toml}`data.runoff`.

scoring window
  Period over which the calibration compares simulated and measured flow. In example 04, 2001
  and 2002; the year 2000 is used as spin-up. Parameter:
  {toml}`calibration.protocol.scoring_window`.

seepage
  Cell where the water table reaches the ground surface and where water leaves the aquifer.
  Parameter: {toml}`simulation.results.derived.seepage_areas`.

seepage threshold
  Fraction of its own recharge that a cell must give back to count as seepage: 0.01 % by
  default. Another threshold changes the network maps. Parameter:
  {toml}`calibration.outputs.<name>.tau_specific_ratio`.

SIM2
  Météo-France reanalysis on an 8 km grid, which supplies rainfall and potential
  evapotranspiration to the soil reservoir. Parameter: {toml}`data.etp`.

simulated network
  Extension downstream, following the slope of the terrain, of the cells where the aquifer
  gives water back to the surface. It does not result from a hydraulic river computation.

soil reservoir
  Simple daily balance: the soil fills with rain, empties by evapotranspiration and lets the
  surplus pass to the water table. Parameter: {toml}`flow.sinks_sources.recharge.soil`.

specific yield
  Share of the rock volume that drains when the water table falls, written Sy, without
  dimension. It sets the speed at which the water table empties and refills. Parameter:
  {toml}`flow.param.Sy.field.value`.

spin-up
  Start of the simulation that is not scored, while the initial state of the model fades out.
  In example 04, the year 2000. Parameter: {toml}`calibration.protocol.scoring_window`.

steady state
  Computation where nothing changes with time: the recharge is a constant mean. Parameter:
  {toml}`flow.flow_regime`.

time step
  Interval over which the recharge is constant: one month in example 04. MODFLOW 6 calls it a
  stress period. Parameters: {toml}`simulation.time.step_value`,
  {toml}`simulation.time.substeps_per_period`.

transient
  Computation where the recharge and the water table vary from one time step to the next.
  Parameter: {toml}`flow.flow_regime`.

unconfined aquifer
  Aquifer whose top is not trapped under an impermeable layer: it rises and falls freely with
  the recharge. HydroModPy targets this type of aquifer.

visible flow
  Minimum flow that a cell must carry to count as "flowing" on the persistence maps: 1 L/s by
  default. It is a convention. Parameter: {toml}`calibration.outputs.<name>.extent.visible_flow`.

water budget
  What enters the aquifer (recharge), what leaves it (drainage) and the change in storage. Its
  closure is a numerical check of the solver. Parameter: {toml}`simulation.results.budget`.
```
