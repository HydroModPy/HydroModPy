# Validation Cases

Reusable scientific benchmarks. The split of responsibilities:

- `validation_cases/`: case definitions, references, metadata and runners,
- `tests/validation/`: thin pytest files that run a case and assert
  thresholds. See `tests/validation/README.md` for pytest usage, markers,
  results and CI.

## Where to look first

No inventory is kept here. Use the generated sources:

- results, references and thresholds: the docs page Theory > Validation
  (`docs/source/theory/validation.md`, from
  `docs/source/theory/validation_results.json`);
- the analytical cases with regime and solvers:
  `python -m validation_cases.run_cases --solver <solver> --regime both --list`;
- the solver variants of one case: `[config_files]` in its `metadata.toml`;
- thresholds and their rationale: `tests/TOLERANCES.md` and the case
  `tolerances*.toml`;
- assumptions of one case: its `README.md`.

## Tree

- `analytical/steady/`, `analytical/transient/`: closed-form references, run
  through the launcher.
- `numerical/`: published examples and solver-to-solver comparisons where no
  clean analytical reference exists. Not part of the analytical batch.
- `calibration/`: twin experiments for the calibration chain. See its own
  `README.md`.
- `shared/`: runtime and helpers used by every case.
- `run_cases.py`: batch runner.

Some modules are helpers without a case directory, for example
`analytical/transient/linearized_unconfined_1d.py` and
`analytical/transient/brutsaert_reference.py`.

## Case layout

A launcher-backed case directory contains:

- `metadata.toml`: case id, regime, `default_solver`, the `[config_files]`
  table (one launcher config per solver variant), the expected output shape and
  the reference parameters,
- `config_common.toml`: settings shared by the variants, when present,
- `config_<solver>.toml`: one launcher config per variant,
- `reference.py`: the reference solution and its literature,
- `comparison.py`: run and compare logic, returns metrics,
- `tolerances.toml`: default thresholds,
- `tolerances_<variant>.toml`: thresholds of one variant that differ,
- `plotting.py`: optional figure helper,
- `run_case.py`: direct entrypoint,
- `README.md`: assumptions and what the case does and does not validate.

A tolerance file may carry a `[doc]` table with a `reason` and, for a known
gap, a `gap`. Both are shown on the docs page.

A case may declare any of these solver variants: `modflow_nwt`, `modflow6`,
`modflow6_irregular_tri`, `modflow6_voronoi`, `boussinesq`,
`boussinesq_local`. `boussinesq` is the PETSc engine (Linux, `petsc4py`).
`boussinesq_local` is the default engine and needs no PETSc.

## Shared modules

`validation_cases/shared/` holds the runtime (`runtime.py`: execution, output
directory, workspace discovery), loaders, metrics, the `run_case.py` CLI
(`cli.py`), mesh helpers and the strip geometry.

`strip_geometry.py` says where a strip model reports its profile and holds its
side heads. A cell-centred model holds a Dirichlet head at the centre of the
boundary cell, not on the face. A reference must pose its heads there.

## Running

From the repository root, in the `hmp_dev` environment. PETSc variants need
`petsc4py` from conda-forge, on Linux.

One case, with a figure and the printed metrics:

```bash
python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --no-show
python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --solver modflow6
```

`--solver` selects a variant declared in the case `[config_files]`.
`--output-root` sets the output root for the run. `--help` lists the rest.

All compatible cases for one solver:

```bash
python -m validation_cases.run_cases --solver modflow6 --regime both --list
python -m validation_cases.run_cases --solver modflow6 --regime steady --no-show
python -m validation_cases.run_cases --solver modflow6 --regime both --no-show --stop-on-error
```

`--help` lists the accepted solvers. `--report-json` writes a batch report.

## Output

See "Output directories" in `tests/validation/README.md`. Results recorded for
the docs page are described there too (`HMP_VALIDATION_RESULTS`,
`python -m tools.docs.validation_results merge`).

## Adding a case

- Keep the physics explicit and the reference documented.
- Prefer deterministic synthetic configurations.
- Put benchmark constants in `metadata.toml`.
- Derive thresholds: about twice the measured error with a refinement check, or
  about 1.1 times with a written `[doc] gap` for an explained gap. Never loosen
  one to pass. Add the rationale to `tests/TOLERANCES.md`.
- Pose the reference heads where the model holds them
  (`shared/strip_geometry.py`).
- Expose a few scalar metrics to pytest, and make `run_case.py` useful for
  visual debugging.
- Add the pytest file as described in `tests/validation/README.md`.

A case directory should be understandable without opening its pytest file.
