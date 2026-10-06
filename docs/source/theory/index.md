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
stress period, and how outputs align on the periods.

- {doc}`forcing`

(step-soil)=
### 2. The soil decides what reaches the water table

The share of the rain that recharges the aquifer, the share that runs off, the
share that evaporates.

- {doc}`soil-reservoir`

(step-aquifer)=
### 3. The aquifer moves the water

The groundwater flow equation, its discrete form on the grid, and the solvers
that integrate it.

- {doc}`groundwater-flow`
- {doc}`solvers/modflow-governing-equation-and-cvfd-formulation`
- {doc}`solvers/vertical-representation-and-storage-assumptions`
- {doc}`solvers/field-to-cell-parameter-transfer`
- {doc}`solvers`
- {doc}`boussinesq`
- {doc}`mf6-vs-nwt`

(step-exits)=
### 4. The water leaves the aquifer

Drains at the ground surface, streams, lakes, the sea, and the network of cells
where the water table reaches the surface.

- {doc}`exits`

(step-observations)=
### 5. The model meets the observations

How a run is scored against measured flow or a mapped network.

- {doc}`calibration/inverse-problem-formulation`
- {doc}`downslope-distance`

### Across all steps: the grid and the notation

- {doc}`mesh`
- {doc}`solvers/xt3d-on-irregular-disv-meshes`
- {doc}`notation`
- {doc}`bibliography`

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

forcing
soil-reservoir
groundwater-flow
solvers/modflow-governing-equation-and-cvfd-formulation
solvers/vertical-representation-and-storage-assumptions
solvers/field-to-cell-parameter-transfer
solvers
boussinesq
mf6-vs-nwt
exits
calibration/inverse-problem-formulation
downslope-distance
mesh
solvers/xt3d-on-irregular-disv-meshes
notation
bibliography
validation
```
