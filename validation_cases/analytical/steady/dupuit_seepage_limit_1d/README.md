# Dupuit Seepage Limit 1D

Steady synthetic hillslope used to validate the seepage mask against its Dupuit
closed form, and to prove that the mask and the head depend on `K` and `R` only
through the ratio `K/R`. Six solvers run it, each on the four scenarios below:
MODFLOW-NWT, MODFLOW 6 on a structured grid, on irregular triangles and on their
Voronoi dual (a drain at the land surface), and the in-house Boussinesq solver on
its PETSc VI obstacle and on its default local engine (no drain).

Reference used by the documentation:

- reference: Dupuit seepage limit `x_e = L / (1 + slope**2 K/R)` and the free Dupuit water table above it

## Equations

The equations of the reference solution the comparison uses.

$$
x_e=\frac{L}{1+s^2\,K/R}
$$

$$
h(x)=s\,x \quad (x<x_e),\qquad
h(x)^2=(s\,x_e)^2+\frac{2R}{K}\left(L\,(x-x_e)-\frac{x^2-x_e^2}{2}\right) \quad (x\ge x_e)
$$

$s$ is the slope of the surface, $L$ the length of the hillslope, $x$ the
distance upslope from the toe, $K$ the hydraulic conductivity and $R$ the
recharge.

## Physics

A plane surface `z = slope * x` sits over a flat substratum, `x` measured
upslope from the toe where the two meet. The hillslope is closed at both ends:
at `x = L` by the divide, at `x = 0` because the saturated thickness vanishes
there. Every cell carries a drain at its own surface elevation.

Under Dupuit assumptions the aquifer can carry at most `K * slope**2 * x` past
the position `x`, while the recharge collected upslope of `x` is `R * (L - x)`.
Equating the two gives the seepage limit:

```
K * slope**2 * x_e = R * (L - x_e)      ->      x_e = L / (1 + slope**2 * K/R)
```

Below `x_e` the water table is pinned at the surface and the excess leaves
through the drains; above it the water table leaves the surface tangentially and
follows the free Dupuit profile
`h**2 = (slope * x_e)**2 + (2 R/K) (L (x - x_e) - (x**2 - x_e**2)/2)`.

Both the water table and the seepage limit are functions of `R/K` alone. The
discharge is not: mass balance pins the total drain outflow at `R * area`
whatever `K` does.

## Numerical setup

- geometry: `80 x 5` cells of `5 m`, `L = 400 m`, width `25 m`,
- topography: plane sampled at cell centers, `slope = 0.02`, toe at the
  downslope grid edge (`base_elevation = slope * dx / 2`,
  `right_to_left_amplitude = slope * (L - dx)`),
- substratum: flat at `0.0 m`, so the saturated thickness is `slope * x`,
- boundary conditions: no lateral boundary at all, one Cauchy drain on the top
  face with `value = 0.0 m2/s`, which selects the shared MODFLOW fallback
  conductance `C = K * cell_area / top_thickness`,
- `K = 2.5e-4 m/s`, `R = 8.64 mm/day = 1e-7 m/s`, so `slope**2 * K/R = 1` and
  `x_e = L/2 = 200 m`.

The drain conductance MUST stay proportional to `K`. A constant conductance
breaks the `K/R` invariance because the head excess the drain needs in order to
discharge then stops scaling with the rest of the problem.

## Scenarios

Each solver has the four scenarios of the table; its key is the solver name, and
the name with the suffix of the scenario. The solvers are `modflow_nwt`,
`modflow6`, `modflow6_irregular_tri`, `modflow6_voronoi`, `boussinesq` and
`boussinesq_local`.

| scenario key | K | R | purpose |
|---|---|---|---|
| `modflow6` | `2.5e-4 m/s` | `8.64 mm/day` | reference |
| `modflow6_scaled_down` | `x 0.01` | `x 0.01` | `K/R` invariance |
| `modflow6_scaled_up` | `x 100` | `x 100` | `K/R` invariance |
| `modflow6_k_only` | `x 2` | unchanged | negative control |

## Grids and solvers

- MODFLOW-NWT and MODFLOW 6 (structured): the `80 x 5` grid above. The NWT
  scenarios run with the NWT validation profile of `validation_cases/shared/runtime.py`
  (headtol `1e-9` m, fluxtol `1e-10` m3/s), which the scaled scenarios inherit by
  the name of their solver; without it they differ from the reference by `7e-3 m`.
- MODFLOW 6 on triangles and on their Voronoi dual: the 594 triangles of about 6 m
  built by `mesh_bundle.py` (bundle under `mesh_bundles/`, rebuilt with
  `python -m validation_cases.analytical.steady.dupuit_seepage_limit_1d.mesh_bundle`),
  or their 320 nodes. The cell tops come from the same 5 m raster, flat past the
  center of its end columns, so the toe nodes of the dual read `0.05 m` and none
  is dry. The reference is read at each cell and averaged over the same 5 m
  columns as the model. Both need the ILUT fill of their configs. The cells that
  disagree with the seepage state of their column are counted; a structured
  grid has none.
- Boussinesq: 320 triangles (`80 x 2` columns of 5 m, 10 m wide), no drain. A cell
  seeps when its head is within `1e-6 m` of its surface, and the water that leaves
  is the surface-excess flux. The default engine runs the `K` and `R` scenarios
  with Newton closures scaled with the recharge (`config_boussinesq_local*.toml`)
  and starts the doubled-`K` control from the solution of the reference scenario:
  from a flat start its dense Newton fails.

## What the case asserts

1. the mask seepage limit matches `x_e` in every scenario, and the water-table
   profile matches the analytical Dupuit solution,
2. scaling `K` and `R` by the same factor leaves the seepage mask identical cell
   for cell and the head equal to a tight band,
3. the same factor on `K` alone moves the mask, while the total drain outflow
   does not move at all.

Assertion 3 is why assertion 2 never looks at the discharge: mass balance forces
`sum(Q) = R * area`, so a discharge check passes on a model that ignores `K`
entirely. Measured here: a factor 2 on `K` alone moves 70 cells of the mask
while the drain outflow ratio stays `1.00000005`.

## Solver settings

`[modflow6.runtime] mf6_inner_rclose = 1e-11` is set once, for every scenario.
The IMS flux-residual criterion is absolute (m3/s), so it is the one part of the
setup that is not scale free; tightening it uniformly keeps the water-budget
closure of the `x 0.01` scenario at `3e-5` instead of `1e-4`. It is not tuned
per scenario.

## Direct execution

```bash
python -m validation_cases.analytical.steady.dupuit_seepage_limit_1d.run_case
python -m validation_cases.analytical.steady.dupuit_seepage_limit_1d.run_case --solver modflow6_k_only --show
```
