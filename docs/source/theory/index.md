# Theory

The equations HydroModPy solves, in the order the water meets them, with what
each one assumes and where it stops being true. Read this part to review a
result, to cite the model, or to know exactly what a parameter does inside an
equation. It says nothing about setting up a run.

## Same subject, four doors

Take the soil reservoir. Each door says something different about it.

| Door | What it says | Example |
|---|---|---|
| {doc}`Understand <../understand/what-it-computes>` | What it means, in plain words | Part of the rain never reaches the water table: the soil keeps it and plants take it back. |
| {doc}`Guides <../guides/recharge>` | How to do it | Switch the soil reservoir on and check its water balance. |
| {toml}`Reference\|flow.sinks_sources.recharge.soil` | Every key, generated | `ru`: capacity of the store, in mm, default and range. |
| {doc}`Theory <soil-reservoir>` | The equations | $S_t = W_t - \mathrm{ETR}_t - X_t$, where $X_t$ is the water above $\mathrm{RU}$. |

## Follow the water

```{raw} html
<div class="hmp-chain">
<a href="#step-forcing">1 Rain and ETP</a><span>&rarr;</span>
<a href="#step-soil">2 Soil</a><span>&rarr;</span>
<a href="#step-aquifer">3 Aquifer</a><span>&rarr;</span>
<a href="#step-exits">4 Exits</a><span>&rarr;</span>
<a href="#step-observations">5 Observations</a>
</div>
```

(step-forcing)=
### 1. Rain and evaporation reach the ground

What arrives at the surface each day, how daily data become the forcing of a
stress period, and how outputs align on the periods. One page, from three of today:

- {doc}`Hydrological forcing chain <hydrology/hydrological-forcing-chain>`
- {doc}`Forcing time aggregation and First_Clim <hydrology/forcing-time-aggregation-and-first-clim>`
- {doc}`Recharge and surface-exchange semantics <hydrology/recharge-and-surface-exchange-semantics>`

(step-soil)=
### 2. The soil decides what reaches the water table

The share of the rain that recharges the aquifer, the share that runs off,
the share that evaporates.

- {doc}`The daily soil reservoir <soil-reservoir>`

(step-aquifer)=
### 3. The aquifer moves the water

The groundwater flow equation, its discrete form, and the solvers that integrate it.

- {doc}`Groundwater flow problem definition <foundations/groundwater-flow-problem-definition>`, to rewrite with the equations of `[flow]`
- {doc}`MODFLOW governing equation and CVFD formulation <solvers/modflow-governing-equation-and-cvfd-formulation>`
- {doc}`Vertical representation and storage assumptions <solvers/vertical-representation-and-storage-assumptions>`
- {doc}`Field-to-cell parameter transfer <solvers/field-to-cell-parameter-transfer>`
- {doc}`Boussinesq theory <boussinesq>`, its core of about 1 200 lines
- One page for the solvers, from today's navigation pages:
  {doc}`MODFLOW 6 flow <solvers/flow/modflow/modflow6>`,
  {doc}`MODFLOW-NWT flow <solvers/flow/modflow/modflownwt>`,
  {doc}`MODFLOW flow family <solvers/flow/modflow-family>`,
  {doc}`comparison and method choice <solvers/flow/modflow/comparison-and-method-choice>`,
  {doc}`transport coupling <solvers/flow/modflow/transport-coupling>`
- {doc}`MODFLOW 6 versus MODFLOW-NWT <solvers/modflow6-vs-modflownwt-scientific-comparison>`, short, linked to the {doc}`validation` matrix

(step-exits)=
### 4. The water leaves the aquifer

Drains at the ground surface, streams, lakes, the sea, and the descent of the water toward the outlet.

- {doc}`MODFLOW package semantics <solvers/modflow-package-semantics-and-boundary-conditions>`, to rewrite for the soil recharge, DRN, SFR, LAK, MVR and the descent D
- The equations of {doc}`stream, ocean and drainage semantics <hydrology/stream-ocean-and-drainage-semantics>`
  and {doc}`simulated active network <hydrology/simulated-active-network>`; their prose goes to Understand

(step-observations)=
### 5. The model meets the observations

How a run is scored against measured flow or a mapped network.

- {doc}`Calibration inverse problem formulation <calibration/inverse-problem-formulation>`
- {doc}`Downslope-distance calibration of the stream network <streams_and_seepage/downslope-distance-calibration>`, equations 1 to 4 only

### Across all steps: the grid, the notation

- One mesh page from four of today, with meshes drawn at build:
  {doc}`mesh and spatial support <mesh/index>`,
  {doc}`regular and irregular cell budgets <mesh/regular-vs-irregular-meshes>`,
  {doc}`discretization strategies <solvers/mesh-and-discretization-strategies>`,
  {doc}`acceptance criteria <solvers/mesh-quality-and-acceptance-criteria>`
- {doc}`XT3D on irregular DISV meshes <solvers/xt3d-on-irregular-disv-meshes>`
- {doc}`System scope and assumptions <foundations/system-scope-and-assumptions>`
- {doc}`Unified notation <notation>`, to rewrite
- {doc}`Bibliography <bibliography>`, cited entries only

## How we know the code solves them

{doc}`validation` lists every check of `tests/validation/`: the reference it
is compared with (a closed-form solution, a published MODFLOW 6 example, a
manufactured solution, or a parameter to find again), the solvers it runs,
and the thresholds it must stay under. The page is generated from the tests,
so it cannot announce a check that does not run.

How a theory page is written, and what its build checks, is in
{doc}`../contribute/write-a-theory-page`.

```{toctree}
:maxdepth: 1
:hidden:

soil-reservoir
validation
Foundations <foundations/index>
Hydrology <hydrology/index>
Mesh <mesh/index>
Solvers <solvers/index>
Boussinesq <boussinesq>
Streams and seepage <streams_and_seepage/index>
Calibration <calibration/index>
notation
bibliography
```
