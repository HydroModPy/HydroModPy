# Validation Cases

This folder hosts reusable scientific validation cases.

The separation of responsibilities is:

- `validation_cases/`: benchmark definitions, references, metadata, and
  runnable case logic,
- `tests/validation/`: pytest entrypoints that execute those cases and assert
  metric thresholds.

This split keeps the benchmark implementation reusable outside pytest while
keeping the actual test files short and focused.

## How a Validation Case Is Used

For launcher-backed analytical cases, the usual workflow is:

1. a pytest file imports one case-specific `run_*_comparison(...)` function,
2. the comparison function loads `metadata.toml` and the applicable tolerance file,
3. the shared runtime launches `examples/projects/launcher_simulation`,
4. postprocessed arrays are loaded from the generated workspace,
5. the analytical reference is evaluated,
6. metrics are returned to pytest for assertion.

The same case can also be run manually through `run_case.py`, which generates a
figure and prints a short metric summary. Cases with more than one configured
solver variant may also expose `--solver`.

## Running All Cases

Use `validation_cases.run_cases` to execute every compatible `run_case.py`
sequentially for one solver and one regime.

## Runtime Environments

The project may use more than one runtime environment, but the split should be
explicit by task.

Current recommended convention:

- Linux / WSL for PETSc-oriented runs and solver comparisons involving
  `petsc_partition` or `petsc`
- Windows `hydromodpy` for docs, static gallery assets, and non-PETSc tooling

Reference note:

- `reporting/runtime_environment_matrix_2026-04-16.md`

List the selected cases without running them:

```powershell
python -m validation_cases.run_cases --solver modflownwt --regime both --list
python -m validation_cases.run_cases --solver modflow6 --regime both --list
python -m validation_cases.run_cases --solver modflow6_irregular_tri --regime both --list
```

Run all steady or transient cases without interactive figures:

```powershell
python -m validation_cases.run_cases --solver modflownwt --regime steady --no-show
python -m validation_cases.run_cases --solver modflownwt --regime transient --no-show
python -m validation_cases.run_cases --solver modflow6 --regime steady --no-show
python -m validation_cases.run_cases --solver modflow6 --regime transient --no-show
python -m validation_cases.run_cases --solver modflow6_irregular_tri --regime steady --no-show
python -m validation_cases.run_cases --solver modflow6_irregular_tri --regime transient --no-show
```

Run the full analytical inventory for one solver:

```powershell
python -m validation_cases.run_cases --solver modflownwt --regime both --no-show
python -m validation_cases.run_cases --solver modflow6 --regime both --no-show
python -m validation_cases.run_cases --solver modflow6_irregular_tri --regime both --no-show
python -m validation_cases.run_cases --solver boussinesq --regime both --no-show
```

Refresh the committed JSON batch reports consumed by the documentation gallery:

```powershell
python -m validation_cases.update_reports --no-show
```

Run with figures enabled:

```powershell
python -m validation_cases.run_cases --solver modflownwt --regime transient --show
python -m validation_cases.run_cases --solver modflow6 --regime steady --show
```

Stop the batch on the first failing case:

```powershell
python -m validation_cases.run_cases --solver modflownwt --regime both --no-show --stop-on-error
```

## Current Scope

Current cases are mostly:

- analytical,
- deterministic,
- groundwater-flow oriented,
- shared across `modflownwt`, `modflow6`, and the in-house `boussinesq`
  backend where the benchmark physics remains defensible,
- mirrored on `modflow6_irregular_tri` for the 21 analytical cases that also
  expose a `modflow6` variant, using either 1D strip reductions or dedicated
  2D irregular meshes for radial/circular benchmarks.

Numerical exploratory cases that are intentionally not part of the analytical
batch inventory live under `validation_cases/numerical/`. They are used for
controlled solver-to-solver comparisons when no clean analytical reference is
available.

One helper module, `analytical/transient/linearized_unconfined_1d.py`, is
module-only and exists to share analytical formulas across transient cases.

## Directory Contract

Launcher-backed case directories typically contain:

- `config_modflownwt.toml`: deterministic launcher configuration for the
  `modflownwt` variant,
- `config_modflow6.toml`: optional `modflow6` variant for the same benchmark
  when solver parity is under validation,
- `config_modflow6_irregular_tri.toml`: optional MODFLOW 6 DISV/triangular
  variant when an irregular mesh is part of the validation target,
- `reference.py`: analytical solution and literature references,
- `comparison.py`: case-specific execution and comparison logic,
- `metadata.toml`: benchmark metadata used to rebuild reference geometry and
  find launcher outputs,
- `tolerances.toml`: default accepted thresholds used by pytest,
- `tolerances_<solver>.toml`: optional solver-specific thresholds when one
  backend needs slightly different validation margins,
- `plotting.py`: optional figure helper for manual inspection,
- `run_case.py`: direct CLI entrypoint,
- `README.md`: short case-level description and assumptions.

The shared runtime used by all cases lives under `validation_cases/shared/`.

## Shared Runtime Files

- `shared/runtime.py`: case execution, output directory resolution, workspace
  discovery.
- `shared/loaders.py`: TOML and numpy loaders used by cases.
- `shared/metrics.py`: reusable numerical metrics such as RMSE and max absolute
  error.
- `shared/cli.py`: common command-line helper used by `run_case.py` scripts.

## Inventory

The inventory is organized first by validation type, then by physical family or
comparison goal.

### Analytical Steady Cases

#### Core 1D Dupuit Baselines

| Path | Type | Regime | Reference | Purpose |
| --- | --- | --- | --- | --- |
| `analytical/steady/dupuit_fixed_head_1d` | launcher-backed | steady | Dupuit, fixed heads | Baseline 1D unconfined profile between two imposed heads. |
| `analytical/steady/dupuit_uniform_recharge_1d` | launcher-backed | steady | Dupuit, uniform recharge | 1D recharge benchmark with fixed heads on both sides. |
| `analytical/steady/dupuit_divide_river_1d` | launcher-backed | steady | Dupuit, divide-river | 1D recharge benchmark with west divide and east river head. |

#### Steady 1D Boussinesq with Heterogeneous Conductivity

| Path | Type | Regime | Reference | Purpose |
| --- | --- | --- | --- | --- |
| `analytical/steady/boussinesq_fixed_head_piecewise_k_1d` | launcher-backed | steady | Boussinesq, fixed heads, piecewise `K` | 1D heterogeneous benchmark with exact `h^2` profile and conductivity jumps. |
| `analytical/steady/boussinesq_uniform_recharge_piecewise_k_1d` | launcher-backed | steady | Boussinesq, recharge, piecewise `K` | 1D recharge benchmark with exact piecewise-constant `K` reference. |
| `analytical/steady/boussinesq_divide_fixed_head_piecewise_k_1d` | launcher-backed | steady | Boussinesq, divide, piecewise `K` | 1D west-divide benchmark without geology dependencies. |

#### Steady 1D Boussinesq with Topography or Sloping Substratum

| Path | Type | Regime | Reference | Purpose |
| --- | --- | --- | --- | --- |
| `analytical/steady/boussinesq_sloping_substratum_constant_thickness_1d` | launcher-backed | steady | Boussinesq, sloping substratum, constant thickness | 1D sloping-bottom benchmark with exact constant-thickness head profile across MODFLOW-NWT, MODFLOW 6, and the local Boussinesq runtime. |
| `analytical/steady/boussinesq_sloping_substratum_fixed_head_1d` | launcher-backed | steady | Boussinesq, sloping substratum, fixed heads | 1D sloping-bottom benchmark with an exact no-recharge fixed-head profile across MODFLOW-NWT, MODFLOW 6, and the local Boussinesq runtime. |
| `analytical/steady/boussinesq_sloping_substratum_uniform_recharge_1d` | launcher-backed | steady | Boussinesq, sloping substratum, uniform recharge | 1D sloping-bottom benchmark with a recharge-driven semi-analytical profile across MODFLOW-NWT, MODFLOW 6, and the local Boussinesq runtime. |
| `analytical/steady/boussinesq_hillslope_interception_1d` | launcher-backed | steady | Boussinesq hillslope interception | 1D sloping-topography benchmark for emergence position and dry-zone profile on the dense in-house runtime. |
| `analytical/steady/linearized_unconfined_drainage_1d` | launcher-backed | steady | linearized unconfined drainage | 1D equilibrium benchmark for the top-drainage boundary condition. |
| `analytical/steady/linearized_unconfined_hillslope_drainage_1d` | launcher-backed | steady | linearized unconfined hillslope drainage | 1D sloping-topography proxy benchmark for distributed drainage above land surface. |

#### Steady 2D Radial or Island Cases

| Path | Type | Regime | Reference | Purpose |
| --- | --- | --- | --- | --- |
| `analytical/steady/dupuit_circular_island_ocean_2d` | launcher-backed | steady | radial Dupuit-Boussinesq | 2D circular-island benchmark using the `ocean` boundary condition. |
| `analytical/steady/boussinesq_circular_island_piecewise_k_2d` | launcher-backed | steady | radial Boussinesq, concentric `K` | 2D circular-island benchmark with concentric heterogeneous conductivity. |

### Analytical Transient Cases

#### Shared Analytical Helper

| Path | Type | Regime | Reference | Purpose |
| --- | --- | --- | --- | --- |
| `analytical/transient/linearized_unconfined_1d.py` | module-only | transient | linearized Boussinesq | Standalone analytical helper for transient 1D checks. |

#### Transient 1D Boundary or Recharge Forcing

| Path | Type | Regime | Reference | Purpose |
| --- | --- | --- | --- | --- |
| `analytical/transient/linearized_unconfined_recharge_step_1d` | launcher-backed | transient | linearized recharge step | 1D recharge-step benchmark under equal fixed heads. |
| `analytical/transient/linearized_unconfined_boundary_step_1d` | launcher-backed | transient | linearized boundary step | 1D west-boundary step benchmark with fixed east head. |
| `analytical/transient/linearized_unconfined_recharge_step_deep_1d` | launcher-backed | transient | linearized recharge step, deep aquifer | 1D recharge-step benchmark with a much deeper reference thickness to reduce linearization error. |
| `analytical/transient/linearized_unconfined_recharge_periodic_1d` | launcher-backed | transient | linearized periodic recharge | 1D sinusoidal recharge benchmark. |
| `analytical/transient/linearized_unconfined_boundary_piecewise_1d` | launcher-backed | transient | linearized piecewise boundary forcing | 1D multi-step west-boundary benchmark using CSV forcing. |

#### Transient 1D Recession or Interception Dynamics

| Path | Type | Regime | Reference | Purpose |
| --- | --- | --- | --- | --- |
| `analytical/transient/boussinesq_hillslope_recharge_step_interception_1d` | launcher-backed | transient | linearized hillslope interception onset | 1D sloping-topography benchmark for transient interception onset on the dense in-house Boussinesq runtime. |
| `analytical/transient/brutsaert_recession_linearized_deep_1d` | launcher-backed | transient | Brutsaert linearized recession | 1D outlet-discharge benchmark for deep-aquifer recession across MODFLOW-NWT, MODFLOW 6, MODFLOW 6 irregular triangles, and the local Boussinesq backend. |
| `analytical/transient/brutsaert_recession_boussinesq_thin_1d` | launcher-backed | transient | Brutsaert nonlinear recession | 1D outlet-discharge benchmark for thin-aquifer nonlinear recession across MODFLOW-NWT, MODFLOW 6, MODFLOW 6 irregular triangles, and the local Boussinesq backend. |

#### Transient 2D Radial Response

| Path | Type | Regime | Reference | Purpose |
| --- | --- | --- | --- | --- |
| `analytical/transient/late_time_unconfined_pumping_2d` | launcher-backed | transient | late-time Theis proxy | 2D radial pumping benchmark in the late-time unconfined regime. |

### Numerical Exploratory Cases

| Path | Type | Regime | Purpose |
| --- | --- | --- | --- |
| `numerical/transient/boussinesq_hillslope_recharge_pulse_overflow_1d` | direct Boussinesq runtime | transient | Sloping-hillslope overflow stress case used to compare `petsc_partition`, `petsc`, and regularized-partition non-PETSc paths with a richer diagnostic figure. |

## Detailed Case Sheets

Some recurring conventions apply across several cases:

- most "1D" cases are run on a thin Cartesian strip and compared through a
  profile averaged across rows,
- radial 2D cases are run on Cartesian grids and compared through annular
  averages,
- transient cases usually compare either a full space-time head matrix or a
  final-time/radial profile subset,
- tolerances are always asserted on a few scalar metrics rather than on raw
  arrays.

### Steady Cases

#### Core 1D Dupuit Baselines

| Case | Numerical setup | Analytical target | Primary metrics | What the case validates |
| --- | --- | --- | --- | --- |
| `dupuit_fixed_head_1d` | Homogeneous unconfined strip, fixed west/east heads, no recharge | Steady 1D Dupuit profile between two imposed heads | head-profile RMSE, max abs error, cross-row spread | Baseline launcher chain, side Dirichlet boundaries, free-surface equilibrium on a simple domain |
| `dupuit_uniform_recharge_1d` | Homogeneous strip, fixed west/east heads, uniform recharge | Steady 1D Dupuit recharge solution | head-profile RMSE, max abs error, cross-row spread | Uniform recharge handling together with side Dirichlet boundaries |
| `dupuit_divide_river_1d` | Homogeneous strip, west divide, east fixed head, uniform recharge | Steady 1D Dupuit divide-river profile | head-profile RMSE, max abs error, cross-row spread | One-sided no-flow behavior plus recharge and one imposed downstream head |

#### Steady 1D Boussinesq with Heterogeneous Conductivity

| Case | Numerical setup | Analytical target | Primary metrics | What the case validates |
| --- | --- | --- | --- | --- |
| `boussinesq_fixed_head_piecewise_k_1d` | Strip with piecewise-constant `K`, fixed west/east heads, no recharge | Exact steady Boussinesq profile written on `U = h^2` | head-profile RMSE, max abs error, cross-row spread | Heterogeneous conductivity mapping and flux continuity across conductivity jumps |
| `boussinesq_uniform_recharge_piecewise_k_1d` | Strip with piecewise-constant `K`, fixed west/east heads, uniform recharge | Exact steady piecewise-`K` Boussinesq recharge solution | head-profile RMSE, max abs error, cross-row spread | Coupling between recharge and conductivity jumps on a benchmark that remains analytical |
| `boussinesq_divide_fixed_head_piecewise_k_1d` | Strip with piecewise-constant `K`, west divide, east fixed head, uniform recharge | Exact steady piecewise-`K` Boussinesq divide-fixed-head solution | head-profile RMSE, max abs error, cross-row spread | One no-flow side boundary combined with heterogeneity |

#### Steady 1D Boussinesq with Topography or Sloping Substratum

| Case | Numerical setup | Analytical target | Primary metrics | What the case validates |
| --- | --- | --- | --- | --- |
| `boussinesq_sloping_substratum_constant_thickness_1d` | Homogeneous strip, linear topography, linearly sloping impermeable bottom, fixed west/east heads chosen so thickness stays constant | Exact steady profile `H(x) = z_b(x) + b*` | head-profile RMSE, max abs error, cross-row spread | Direct validation that the sloping-bottom term is carried consistently across the three backends in the simplest exact regime |
| `boussinesq_sloping_substratum_fixed_head_1d` | Homogeneous strip, linear topography, linearly sloping impermeable bottom, general fixed west/east heads, no recharge | Exact steady no-recharge Boussinesq profile on a sloping substratum | head-profile RMSE, max abs error, cross-row spread | Direct validation of sloping-bottom flow beyond the trivial constant-thickness branch |
| `boussinesq_sloping_substratum_uniform_recharge_1d` | Homogeneous strip, linear topography, linearly sloping impermeable bottom, fixed west/east heads, uniform recharge | Semi-analytical steady Boussinesq profile on a sloping substratum with recharge | head-profile RMSE, max abs error, cross-row spread | Direct validation of the sloping-bottom term combined with uniform recharge on the same simple hillslope geometry |
| `boussinesq_hillslope_interception_1d` | Strip with west divide, east fixed head, uniform recharge, and linear topography | Approximate inland interception point from the dry no-drain Boussinesq profile | interception-position error, topography-overshoot check, cross-row spread | Steady seepage/interception onset on a sloping hillslope with the dense in-house Boussinesq runtime |
| `linearized_unconfined_drainage_1d` | Homogeneous strip, fixed west/east heads, distributed top drainage everywhere, flat drainage level | Steady linearized unconfined solution with distributed drainage | head-profile RMSE, max abs error, cross-row spread | `drainage` boundary-condition path in a controlled analytical setting |
| `linearized_unconfined_hillslope_drainage_1d` | Homogeneous strip, fixed west/east heads, linear topography, distributed top drainage everywhere | Steady linearized unconfined solution with linear drainage elevation | head-profile RMSE, max abs error, cross-row spread, minimum clearance above topography | Sloping-topography drainage behavior without introducing a free seepage-face problem |

#### Steady 2D Radial or Island Cases

| Case | Numerical setup | Analytical target | Primary metrics | What the case validates |
| --- | --- | --- | --- | --- |
| `dupuit_circular_island_ocean_2d` | Circular synthetic island on Cartesian grid, uniform recharge, flat substratum, `ocean` top BC | Radial steady Dupuit-Boussinesq island solution | radial RMSE, radial max abs error, azimuthal spread, ocean head error, minimum land freeboard | Ocean BC activation, radial symmetry preservation, 2D synthetic topography with the water table kept below land surface |
| `boussinesq_circular_island_piecewise_k_2d` | Circular island with concentric piecewise-constant `K`, uniform recharge, `ocean` top BC | Radial steady Boussinesq island solution with concentric `K` zones | radial RMSE, radial max abs error, azimuthal spread, ocean head error, minimum land freeboard | 2D heterogeneous `K` mapping, ocean BC, radial symmetry and land/sea partitioning |

### Transient Cases

#### Transient 1D Boundary or Recharge Forcing

| Case | Numerical setup | Analytical target | Primary metrics | What the case validates |
| --- | --- | --- | --- | --- |
| `linearized_unconfined_recharge_step_1d` | Homogeneous strip, fixed west/east heads, recharge step from the first transient period | Linearized transient response to a recharge step | space-time RMSE, space-time max abs error, final-profile RMSE, cross-row spread | Transient recharge handling and propagation of a simple forcing through time |
| `linearized_unconfined_boundary_step_1d` | Homogeneous strip, fixed east head, west-head step applied through CSV forcing | Linearized transient response to a west-boundary step | space-time RMSE, space-time max abs error, final-profile RMSE, cross-row spread | Launcher-managed transient side-Dirichlet forcing using one simple head step |
| `linearized_unconfined_recharge_step_deep_1d` | Homogeneous strip, fixed west/east heads, recharge step from the first transient period, deep reference thickness | Linearized transient response to a recharge step in the near-linear regime | space-time RMSE, space-time max abs error, final-profile RMSE, cross-row spread | Separation between true transient-code issues and expected nonlinear deviation from the linearized theory |
| `linearized_unconfined_boundary_piecewise_1d` | Homogeneous strip, fixed east head, piecewise west-head series from CSV, no recharge | Linearized transient response to a multi-step west-boundary forcing | space-time RMSE, space-time max abs error, final-profile RMSE, cross-row spread | Multi-step boundary forcing and superposition behavior beyond the single-step case |
| `linearized_unconfined_recharge_periodic_1d` | Homogeneous strip, fixed west/east heads, periodic recharge chronicle from CSV | Linearized transient response to sinusoidal recharge | space-time RMSE, space-time max abs error, final-profile RMSE, cross-row spread | Periodic recharge forcing and phase/amplitude propagation in transient flow |

#### Transient 1D Recession or Interception Dynamics

| Case | Numerical setup | Analytical target | Primary metrics | What the case validates |
| --- | --- | --- | --- | --- |
| `boussinesq_hillslope_recharge_step_interception_1d` | Sloping strip, east fixed head, recharge step from the first transient period | Linearized onset approximation for the moving interception front | onset-time error, interception-trajectory RMSE, interception-trajectory max abs error, cross-row spread | Transient appearance of seepage/interception on a hillslope with the dense in-house Boussinesq runtime |
| `brutsaert_recession_linearized_deep_1d` | Homogeneous strip, west divide, east fixed head, steady recharge pre-run followed by recession | Exponential Brutsaert recession law for a deep aquifer | relative discharge RMSE, relative discharge max abs error, cross-row spread, positive-increment check | Integrated-discharge recession behavior across MODFLOW-NWT, MODFLOW 6, MODFLOW 6 irregular triangles, and the local Boussinesq runtime in the near-linear regime |
| `brutsaert_recession_boussinesq_thin_1d` | Homogeneous strip, west divide, east fixed head, steady recharge pre-run followed by recession | Nonlinear Brutsaert recession law for a thin aquifer | relative discharge RMSE, relative discharge max abs error, cross-row spread, positive-increment check | Integrated-discharge recession behavior across MODFLOW-NWT, MODFLOW 6, MODFLOW 6 irregular triangles, and the local Boussinesq runtime in the nonlinear regime |

#### Transient 2D Radial Response

| Case | Numerical setup | Analytical target | Primary metrics | What the case validates |
| --- | --- | --- | --- | --- |
| `late_time_unconfined_pumping_2d` | Square unconfined domain, fixed heads on outer boundary, central pumping well, transient run | Late-time radial Theis proxy using `T = K * href` and `S = Sy` | space-time RMSE, space-time max abs error, final-time RMSE, final-time max abs error, azimuthal spread | Transient well forcing, late-time radial drawdown scaling, and numerical radial symmetry around the well |

## Comparison Patterns

The suite currently uses four main comparison patterns:

- `1D strip profile`: mean head along `x`, plus a transverse spread metric to
  ensure the supposed 1D solution remains laterally uniform;
- `2D radial case`: annular mean profile, plus azimuthal spread to quantify
  loss of symmetry on a Cartesian grid;
- `transient matrix`: comparison of the full space-time response, often
  complemented by one final-time or final-profile metric.

Additional case-specific diagnostics are used when needed:

- `ocean_head_max_error` for coastal island cases,
- `min_land_freeboard` to ensure the simulated water table remains below the
  land surface where the benchmark assumes it,
- `final_time_*` metrics for transient pumping where only the late-time regime
  is compared to the analytical reference.

## What Is Currently Covered

Scientifically, the current suite provides direct validation for:

- side Dirichlet boundaries,
- implicit divide / no-flow situations,
- uniform and transient recharge forcing,
- one deep-aquifer transient benchmark used to suppress linearization error when validating the Boussinesq transient path,
- one transient hillslope-interception onset benchmark for the dense in-house `boussinesq` runtime,
- two transient integrated-discharge Brutsaert recession benchmarks available on
  `modflownwt`, `modflow6`, `modflow6_irregular_tri`, and `boussinesq`,
- MODFLOW 6 irregular triangular meshes for the 1D steady strip,
  transient boundary/recharge, Brutsaert recession, circular-island, and
  late-time radial-pumping families,
- top `ocean` boundary condition,
- top distributed `drainage` behavior,
- steady sloping-substratum flow under three 1D references, including constant-thickness, no-recharge fixed-head, and recharge-driven hillslope regimes,
- steady topographic interception / seepage-onset position on a hillslope for the dense in-house `boussinesq` runtime,
- one sloping-topography drainage benchmark that keeps the analytical assumptions explicit,
- homogeneous and piecewise-constant horizontal conductivity fields,
- radial symmetry preservation in 2D cases,
- transient pumping in the late-time unconfined regime.

## What Is Not Yet Covered

The current analytical inventory does not yet provide dedicated scientific
validation for:

- broad `modflow6` parity across the same benchmarks beyond the currently
  enabled dual-solver cases,
- a distinct `stream` top-boundary benchmark,
- a truly differentiated `robin` drainage benchmark,
- multi-layer analytical benchmarks,
- transport / particle-tracking validation (`MT3DMS`, `MODPATH`, `MF6-GWT`).

## Case Design Guidelines

When adding a new validation case:

- keep the physics explicit and the reference documented,
- prefer deterministic synthetic configurations over data-driven cases,
- expose only a few robust metrics to pytest,
- store benchmark-specific constants in `metadata.toml`,
- keep tolerances explicit and justified in `tolerances.toml`,
- make `run_case.py` useful for visual debugging.

A good case directory should be understandable on its own without opening the
corresponding pytest file.

## Relationship With Pytest

The corresponding test files live under `tests/validation/`.
Those tests should generally:

- import one comparison function from the case directory,
- run the case once,
- assert a small set of scalar metrics,
- avoid duplicating analytical logic already stored in the case.

For pytest usage, markers, and debugging guidance, see
`tests/validation/README.md`.
