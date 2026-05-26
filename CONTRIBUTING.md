# Contributing to HydroModPy

Thanks for considering a contribution. This file is the short version: how
to report an issue, set up a dev environment, run tests, and open a pull
request. The deep documentation (CLI, TOML, Pydantic config, data managers,
architecture) lives in the
[contributor guide](https://hydromodpy-docs.readthedocs.io/en/main/contribute.html)
and on the [Read the Docs site](https://hydromodpy-docs.readthedocs.io/en/main/).
Release naming, maintenance branches, tags, and GitHub Releases are covered
in [VERSIONING.md](VERSIONING.md).

## Open an issue

Report bugs and request features at
<https://github.com/HydroModPy/HydroModPy/issues>. A useful bug report
includes:

- the HydroModPy version (`hmp --version` or `pip show hydromodpy`),
- the Python version and OS,
- the TOML config (or a minimal version),
- the full traceback,
- what you expected.

For a new data source or variable, please attach the API endpoint, response
format, units, spatial and temporal resolution, and any rate limit. The more
technical detail, the faster the integration.

## Dev install

```bash
git clone https://github.com/HydroModPy/HydroModPy.git
cd HydroModPy
conda create -n hmp-dev python=3.12 -y
conda activate hmp-dev
pip install -e ".[dev,test,docs]"
pre-commit install
```

The `-e` flag installs in editable mode: source edits take effect on next
import. The `pre-commit install` step registers the Git hook that runs
`ruff` before each commit.

For conda env files, Windows + WSL setup, and the PETSc Boussinesq backend,
see the [installation guide](https://hydromodpy-docs.readthedocs.io/en/main/install.html).

## Lint and format

`ruff` is the single source of truth. Run it before every commit (the
pre-commit hook does it automatically on staged files):

```bash
ruff check --fix .
ruff format .
```

## Run tests

Five tiers under `tests/`: `unit/`, `integration/`, `regression/`, `e2e/`,
`validation/`. The main CI gate runs quality checks, architecture
contracts, fast tests on Python 3.11 to 3.13, unit tests, integration tests,
fast regression, packaging smoke, and an advisory mypy baseline. Heavier
validation, e2e, full regression, and cross-platform checks run on scheduled
workflows. Locally, the fast loop is:

```bash
python -m pytest -m fast -q -n auto      # fast unit tests, parallel
hmp test regression --fast               # fast regression tier
hmp test validation --fast               # fast validation tier
```

Tolerances are centralized in [`tests/TOLERANCES.md`](tests/TOLERANCES.md).
Do not hard-code tolerances elsewhere. New solver behavior needs at least a
unit test, plus a validation case if the math is non-trivial.

For the full ladder (when each family runs, what each protects against),
see the [test families guide](https://hydromodpy-docs.readthedocs.io/en/main/architecture/overview/test-families-and-quality-roles.html).
For GitHub check names and CI triage, see the
[GitHub Actions workflow guide](https://hydromodpy-docs.readthedocs.io/en/main/architecture/ci-workflows.html).

## Code style

- Python 3.11 to 3.13. Type hints on every public signature.
- Pydantic v2 only. Every `BaseModel` sets
  `model_config = ConfigDict(extra="forbid")`.
- Ruff line length 100, target py311.
- Default to no comments. Add one only when the *why* is not obvious from
  the code.
- File names: `snake_case`. Class names: `CamelCase`. Common suffixes:
  `Config`, `Adapter`, `Manager`, `Builder`, `Resolver`, `Optimizer`,
  `Provider`, `Backend`.

The architecture is a strict layered DAG. Cross-layer imports outside the
matrix are CI failures. The contract lives in
[`tests/unit/architecture/layer_matrix.yaml`](tests/unit/architecture/layer_matrix.yaml)
and is enforced by `tests/unit/architecture/test_layer_matrix.py`.

## Commits and pull requests

- Branch from `dev` for normal work. Use a short descriptive name, for
  example `feat/bdtopage-loader`, `fix/calib-cell-resolve`, or
  `docs/versioning-policy`.
- `main` is the current v2 line and future default branch.
- `archive-v1` is the frozen v1.0.0 branch. Do not target normal PRs there.
- Use `maint/1.x` only if active maintenance of the `1.*` line resumes.
- Use `release/X.Y` only for short stabilization windows before a final
  `vX.Y.0` release.
- Commit format: Conventional Commits, one line, no body. Examples:
  `feat(data): add bdtopage loader`, `fix(calibration): resolve cells`,
  `docs(versioning): document maintenance branches`.
- Group related changes in one focused commit.
- Open the PR against `dev`. Reference the issue (`Closes #123`) when
  applicable.
- Mention reviewers if the change affects modeling outputs, the public API,
  or any user-visible workflow.

Releases are identified by tags such as `v1.1.0`, `v2.0.0a1`,
`v2.0.0b1`, or `v2.0.0rc1`, not by branch names. See
[`VERSIONING.md`](VERSIONING.md) and
[`docs/source/about/release_policy.rst`](docs/source/about/release_policy.rst).

## Where to look next

- [Configuration reference](https://hydromodpy-docs.readthedocs.io/en/main/user_guide/config_reference/index.html):
  every TOML section, fields, defaults, validators.
- [Architecture](https://hydromodpy-docs.readthedocs.io/en/main/architecture/index.html):
  layer matrix, package maps, runtime handoff.
- [User guide](https://hydromodpy-docs.readthedocs.io/en/main/user_guide/index.html):
  workflows, cookbook, theory, supported data variables.
- [API reference](https://hydromodpy-docs.readthedocs.io/en/main/api/index.html):
  auto-generated, complete.

## License

By contributing you agree that your contribution will be released under the
[Eclipse Public License 2.0](https://opensource.org/licenses/EPL-2.0).
