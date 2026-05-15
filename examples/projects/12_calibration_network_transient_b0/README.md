# B0 network and transient-discharge calibration prototype

This example is intentionally separate from the existing comparison testbeds.
Its purpose is to develop the joint calibration contract without changing the
general calibration API too early.

The target inverse problem is:

```text
truth solver      = MODFLOW 6
candidate solver  = MODFLOW 6
domain            = site_05 controlled small natural catchment
parameters        = {mK, Sy}
steady observable = per-cell outflow_drain network
transient output  = Q_total_release(t)
objective         = 0.5 * C_network_phys + 0.5 * C_discharge_phys
```

## Scope of this prototype

This directory owns the first executable specification for the B0 calibration.
It should not modify:

- the global calibration schema;
- the optimizer adapters;
- existing comparison workflows;
- existing Boussinesq/MODFLOW comparison examples.

The first implementation should instead use a dedicated Python metric function
that calls pure helpers from `hydromodpy.calibration.network_metrics`.

## Planned layout

```text
examples/projects/12_calibration_network_transient_b0/
  README.md
  candidates_template.csv
  build_truth_package.py
  run_synthetic_smoke.py
  score_candidate.py
  score_candidate_table.py
  configs/
    truth_steady_network.toml
    truth_transient_discharge.toml
    candidate_steady_network.toml
    candidate_transient_discharge.toml
  truth/
    metadata.json
    normalization.json
    steady_network_drain_by_cell.npz
    steady_network_active_mask.npz
    transient_q_total_release.csv
    cell_geometry.npz
```

The `truth/` files are generated artifacts and are not committed by default.

## Synthetic Smoke Test

Before launching MODFLOW 6 grids, the full B0 scoring contract can be exercised
on deterministic arrays:

```bash
python examples/projects/12_calibration_network_transient_b0/run_synthetic_smoke.py
```

The script writes:

- `outputs/synthetic_smoke/truth/`;
- `outputs/synthetic_smoke/candidate_scores.csv`;
- `outputs/synthetic_smoke/candidate_scores.json`;
- `outputs/synthetic_smoke/summary.json`.

This is not a hydrologic benchmark. It is a fast contract test: the synthetic
truth is generated with `mK = 1.0` and `Sy = 0.05`, then a small grid is scored
with the same physical normalizations used by the real B0 workflow.

## Build The Truth Package

After running or regenerating the steady and transient MODFLOW 6 truth runs,
build the pseudo-observation package with:

```bash
python examples/projects/12_calibration_network_transient_b0/build_truth_package.py \
  --steady-catalog path/to/steady/workspace/or/hydromodpy.duckdb \
  --steady-ref mf6_truth_steady \
  --transient-catalog path/to/transient/workspace/or/hydromodpy.duckdb \
  --transient-ref mf6_truth_transient
```

The script expects:

- complete HydroModPy catalogs with their `simulations/` Parquet/Zarr artifacts
  still available;
- the steady run to expose `outflow_drain` at the final timestep;
- the transient run to expose the `outflow_drain` stack;
- both runs to share the same cell support;
- the steady run to expose the persisted mesh geometry.

## Score One Candidate

Once a `truth/` package exists, score a candidate pair of runs with:

```bash
python examples/projects/12_calibration_network_transient_b0/score_candidate.py \
  --truth-dir examples/projects/12_calibration_network_transient_b0/truth \
  --steady-catalog path/to/candidate/steady/workspace/or/hydromodpy.duckdb \
  --steady-ref candidate_steady \
  --transient-catalog path/to/candidate/transient/workspace/or/hydromodpy.duckdb \
  --transient-ref candidate_transient \
  --output-json examples/projects/12_calibration_network_transient_b0/outputs/candidate_score.json
```

This is the intended bridge before a grid search or optimizer: candidate runs
can be produced by existing launchers, then scored without changing the
calibration engine.

## Score A Candidate Grid

For a first `{mK, Sy}` exploration, create a CSV following
`candidates_template.csv`, with one row per pair of completed steady/transient
candidate runs. Then run:

```bash
python examples/projects/12_calibration_network_transient_b0/score_candidate_table.py \
  --truth-dir examples/projects/12_calibration_network_transient_b0/truth \
  --candidates-csv examples/projects/12_calibration_network_transient_b0/candidates.csv \
  --output-csv examples/projects/12_calibration_network_transient_b0/outputs/candidate_scores.csv
```

This produces a ranked table with `J`, `C_reseau_phys`, `C_debit_phys` and the
detailed diagnostic components. Failed candidates are kept in the table with an
error message, which is useful during the first grid exploration.

## Development order

1. Validate the pure network metrics on synthetic arrays.
2. Add a MODFLOW 6 DRAIN-by-cell extractor for steady and transient runs.
3. Generate the `truth/` package for site_05.
4. Run a small grid in `{mK, Sy}` without a complex optimizer.
5. Promote only the stable parts into the general calibration API.

## Normalization contract

The normalization is fixed from the reference before candidate evaluations:

```text
C_network_phys =
  0.4 * E_flux / eta_flux
  + 0.4 * E_dist / eta_dist
  + 0.2 * E_len / eta_len

C_discharge_phys =
  RMSE(Q_total_release_sim, Q_total_release_ref) / (alpha_Q * Qbar_ref)

J = 0.5 * C_network_phys + 0.5 * C_discharge_phys
```

Initial B0 values:

```text
tau_network = 0.0
d_tol       = 1 * dx
eta_flux    = 0.05
eta_dist    = 1.0
eta_len     = 0.10
alpha_Q     = 0.10
```
