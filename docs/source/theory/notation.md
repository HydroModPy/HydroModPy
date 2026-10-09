# Notation

Every symbol of the theory pages, with its unit and the key that sets it. The
tables are generated from one registry, `docs/source/theory/symbols.yaml`, and
each theory page renders its own table from the same file.

The units are the ones the code stores: lengths in metres, hydraulic
conductivity in m/s, rates in m/s. The soil reservoir is the exception, because
it works in mm and days. A name that exists in the code or in an output file is
given in `code font` in the meaning column, so a symbol can be matched with a
column of a result file.

## Conventions

- Lengths are in metres, and elevation is positive up.
- A flux into the aquifer is positive. The residual of the Boussinesq solver is
  the one exception: it counts a loss as positive, and its page says so.
- Cells are $n$ and $m$ on the pages of the two MODFLOW solvers and of the mesh,
  and $i$ on the Boussinesq page, which runs on triangles.
- A symbol with an overbar, such as $\bar B$, is an average over the catchment.
  It is by area, unless the page says otherwise.
- A TOML value can carry its unit, such as `"500 m"` or `"1 month"`. The unit of
  a key is on its card.

## Space, time and heads

```{hmp-notation}
:groups: space
```

## The domain and its layers

```{hmp-notation}
:groups: domain
```

## Properties of the ground

```{hmp-notation}
:groups: ground
```

## Fluxes

```{hmp-notation}
:groups: fluxes
```

A recharge series is read in the unit of {toml}`flow.sinks_sources.recharge.units`
and converted to m/s. When the soil reservoir computes it, $N = (1 - f)\,O_t$
(see {doc}`soil-reservoir`).

## Cells and their balance

```{hmp-notation}
:groups: cells
```

## The nonlinear solve

```{hmp-notation}
:groups: solve
```

## The mesh

```{hmp-notation}
:groups: mesh
```

## From a zone map to the cells

```{hmp-notation}
:groups: transfer
```

## The Boussinesq solver

```{hmp-notation}
:groups: boussinesq
```

## The soil reservoir

Stores are in mm of water per unit of unsealed area, fluxes in mm/day.
{doc}`soil-reservoir` defines each one with its equation.

```{hmp-notation}
:groups: soil
```

## Forcing and time

{doc}`forcing` and {doc}`time-alignment` define each one.

```{hmp-notation}
:groups: forcing
```

## The exits of the aquifer

{doc}`exits` and its six pages define each one.

```{hmp-notation}
:groups: exits
```

## The descent and the distance between networks

The descent $D$ is where water goes on the model top: from each cell, the path to a
lower neighbour, down to the outlet or to a cell where water leaves the model. It is
a computation on a copy of the top and is never given back to the solver. The
distances below are not measured on $D$, but on their own copy
({doc}`downslope-distance`).

```{hmp-notation}
:groups: descent
```

## Scores

The names below are written in roman type. Each is a value of
{toml}`calibration.objective_blocks.metric`.

```{hmp-notation}
:groups: scores
```

$\mathrm{NSE}_{\log}$ is not {toml}`transform|calibration.objective_blocks.transform`
set to `log`. The metric takes the logarithm of the series. The transform takes
the logarithm of a cost that is already computed.
