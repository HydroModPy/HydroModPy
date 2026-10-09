# Fixed heads: the sea, the rivers and the sides

A fixed head takes the head of a cell out of the solution. The flux across the
cell becomes a result. HydroModPy uses it for the sea, for a river given as a
head, and for the sides of the model.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(heads-law)=
## The law

In every layer of a fixed-head cell $n$ and in every period,

$$
h_n = h^\mathrm{bc} .
$$ (eq-fixed-head)

The head of a period is the value that the boundary, or its forcing, gives for
that period. The flux across the cell is stored in the budget as
`constant_head`, and the share of it that crosses a river cell as
`constant_head_stream` ({doc}`simulated-network` reads that share).

A fixed head is a Dirichlet condition. It is not a conductance-limited exchange
of the GHB or RIV kind, and HydroModPy builds neither of those packages. A river
that must exchange through a streambed is a stream network
({doc}`streams-and-mover`).

(heads-sea)=
## The sea

The sea cells are the cells of the model domain whose DEM is not above the
highest sea level of the run:

$$
\mathcal{C}_\mathrm{sea} = \{\, n \in \text{domain} : z^\mathrm{dem}_n \leq \max_t h_\mathrm{sea}(t) \,\} .
$$ (eq-sea-cells)

A cell below that level far inland is in the set: the code does not test the
connection to the sea. The drains stay on the other cells. A sea level of 0 m:

```toml
base_config = "step4_transient.toml"

[flow]
active_bc = ["drainage", "ocean"]

[flow.bc.ocean]
value = 0.0
```

MODFLOW-NWT selects its cells by the same DEM, with one difference: its
constant-head rows take $z^\mathrm{dem}_n < h_\mathrm{sea}$, and its `ibound`
takes $z^\mathrm{dem}_n \leq h_\mathrm{sea}$.

In the code: `ocean_chd_support_mask`.

(heads-rivers)=
## The rivers and the sides

The river cells are the river cells of the mesh support, or the cells with the
{toml}`support_label|flow.bc.<name>.support_label` given to the boundary. A side
boundary is the cells along one side of the model. A cell that falls in two sets
keeps the last head written, in the order sea, river, side.

One CHD package carries the three. The build therefore writes which cells are sea
and which are river in a file beside the solver files, and the extraction reads
it to tell a river head from a sea head. That is how the river share of the
constant-head flux reaches the stored budget.

In the code: `assemble_constant_head_stress_period_data`.

## Assumptions

- The sea is a fixed head with the level of its period. It does not move inside a
  period.
- A river head is a fixed head. A river that exchanges through a bed is a stream
  network.

## Limits

- **The sea is not a density model.** There is no interface between fresh and
  salt water, and no tide inside a period.
- **The sea cells are selected by their DEM**, with the one difference between
  the two MODFLOW solvers given above.
- **Stream heads need MODFLOW 6 or Boussinesq.** MODFLOW-NWT has the sea and the
  sides.

## Parameters of this page

```{hmp-params}
flow.active_bc
flow.bc.<name>.value
flow.bc.<name>.support_label
```

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.solver.modflow6.builders.boundary_conditions
hydromodpy.solver.modflow_common.boundary_roles
```

## In the code

| What | Where |
|---|---|
| Sea, river and side heads under MODFLOW 6 | `hydromodpy/solver/modflow6/builders/boundary_conditions.py` |
| The roles of the CHD cells | `hydromodpy/solver/modflow_common/boundary_roles.py` |
| Fixed heads under MODFLOW-NWT | `hydromodpy/solver/modflow_nwt/nwt/payloads/chd.py` |
