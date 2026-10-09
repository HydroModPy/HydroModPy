# Theory

Theory covers what HydroModPy computes or decides: the rules it applies when it
builds a model, the conversions from TOML to solver input, the methods it
implements itself, and what it refuses. The equations of MODFLOW and of the
literature are read at their source. A page gives external theory a few sentences
and a citation, then says what HydroModPy does with it. Each page names the keys
that set its terms; the steps of a run are in the
{doc}`staircase <../get-started/staircase/index>`.

## Sources we build on

- MODFLOW 6 groundwater flow: {cite:t}`langevin2017`. Framework and IMS solver:
  {cite:t}`hughes2017framework`. Input guide:
  [MODFLOW 6 input reference](https://modflow6.readthedocs.io/en/latest/mf6io.html).
- XT3D on irregular meshes: {cite:t}`provost2017`.
- MODFLOW-NWT: {cite:t}`niswonger2011`, on {cite:t}`harbaugh2005`. Input guide:
  [MODFLOW-NWT guide](https://water.usgs.gov/ogw/modflow-nwt/MODFLOW-NWT-Guide/).
- Mesh generation: [Gmsh manual](https://gmsh.info/doc/texinfo/gmsh.html).

{doc}`solvers` gathers the links package by package. Every citation is listed in
the {doc}`bibliography`.

## Same subject, four doors

Take the soil reservoir. Each door says something different about it.

| Door | What it says | Example |
|---|---|---|
| {doc}`Understand <../understand/what-it-computes>` | What it means, in plain words | Part of the rain never reaches the water table: the soil keeps it and plants take it back. |
| {doc}`Get started <../get-started/staircase/step6>` | How to do it | Switch the soil reservoir on, in step 6 of example 04. |
| {toml}`Reference\|flow.sinks_sources.recharge.soil` | Every key, generated | `ru`: capacity of the store, in mm, default and range. |
| {doc}`Theory <soil-reservoir>` | What HydroModPy computes, with its assumptions | $S_t = W_t - \mathrm{ETR}_t - X_t$, where $X_t$ is the water above $\mathrm{RU}$. |

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

{doc}`validation` is generated from `tests/validation/`: each check, its
reference, the solvers it runs and the thresholds it must stay under. A check
appears there only when a test exists for it.

How a theory page is written, and what its build checks, is in
{doc}`../contribute/write-a-theory-page`.
