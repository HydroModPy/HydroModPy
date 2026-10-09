# Theory

The equations HydroModPy solves, in the order the water meets them, with what
each one assumes and where it stops being true. Read this part to review a
result, to cite the model, or to know exactly what a parameter does inside an
equation. Each page names the keys that set its terms; the steps of a run are in
the {doc}`staircase <../get-started/staircase/index>`.

## Same subject, four doors

Take the soil reservoir. Each door says something different about it.

| Door | What it says | Example |
|---|---|---|
| {doc}`Understand <../understand/what-it-computes>` | What it means, in plain words | Part of the rain never reaches the water table: the soil keeps it and plants take it back. |
| {doc}`Get started <../get-started/staircase/step6>` | How to do it | Switch the soil reservoir on, in step 6 of example 04. |
| {toml}`Reference\|flow.sinks_sources.recharge.soil` | Every key, generated | `ru`: capacity of the store, in mm, default and range. |
| {doc}`Theory <soil-reservoir>` | The equations | $S_t = W_t - \mathrm{ETR}_t - X_t$, where $X_t$ is the water above $\mathrm{RU}$. |

## Follow the water

1. {ref}`Rain and evaporation reach the ground <step-forcing>`
2. {ref}`The soil decides what reaches the water table <step-soil>`
3. {ref}`The aquifer moves the water <step-aquifer>`
4. {ref}`The water leaves the aquifer <step-exits>`
5. {ref}`The model meets the observations <step-observations>`

(step-forcing)=
### 1. Rain and evaporation reach the ground

What arrives at the surface each day, and how daily data become the forcing of
a stress period.

```{toctree}
:caption: 1. Rain and evaporation
:maxdepth: 1

forcing
```

(step-soil)=
### 2. The soil decides what reaches the water table

The share of the rain that recharges the aquifer, the share that runs off, the
share that evaporates.

```{toctree}
:caption: 2. Soil
:maxdepth: 1

soil-reservoir
```

(step-aquifer)=
### 3. The aquifer moves the water

The problem, the grid it is solved on, and the solvers that integrate it.

```{toctree}
:caption: 3. Aquifer, the problem
:maxdepth: 1

groundwater-flow
dupuit-limits
solvers/field-to-cell-parameter-transfer
```

```{toctree}
:caption: 3. Aquifer, the grid
:maxdepth: 1

mesh
solvers/xt3d-on-irregular-disv-meshes
```

```{toctree}
:caption: 3. Aquifer, the solvers
:maxdepth: 1

solvers
mf6-vs-nwt
boussinesq
```

(step-exits)=
### 4. The water leaves the aquifer

Fixed heads at the sea and on the rivers, drains and evapotranspiration at the
ground surface, lakes, streams and the water mover, the routing of the released
water on the mesh, and the network of cells where the water table reaches the
surface.

```{toctree}
:caption: 4. Exits
:maxdepth: 1

exits
```

(step-observations)=
### 5. The model meets the observations

How outputs and observations are put on the same periods, and how a run is
scored against measured flow or a mapped network.

```{toctree}
:caption: 5. Observations
:maxdepth: 1

time-alignment
calibration/inverse-problem-formulation
downslope-distance
```

### For every step

```{toctree}
:caption: For every step
:maxdepth: 1

notation
bibliography
validation
```

## How we know the code solves them

{doc}`validation` lists every check of `tests/validation/`: the reference it
is compared with (a closed-form solution, a published MODFLOW 6 example, a
manufactured solution, or a parameter to find again), the solvers it runs,
and the thresholds it must stay under. The page is generated from the source of
the tests: a check appears there only when a test exists for it.

How a theory page is written, and what its build checks, is in
{doc}`../contribute/write-a-theory-page`.
