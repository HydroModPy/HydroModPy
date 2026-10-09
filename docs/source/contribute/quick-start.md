# Quick start

Ten minutes from a clone to a first commit. The {doc}`handbook` has the long
version: conda environments, WSL, PETSc, the pull-request flow.

## 1. Install an editable clone

You need Python 3.11, 3.12 or 3.13.

```bash
git clone https://github.com/HydroModPy/HydroModPy.git
cd HydroModPy
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,test,docs]"
pre-commit install
```

`dev` brings `ruff` and `pre-commit`, `test` brings `pytest` and its plugins,
`docs` brings Sphinx and the extensions of this site. Check the result:

```bash
hmp doctor
```

`hmp` and `hydromodpy` are the same command.

## 2. Run the architecture gate

This is the one test tier worth running before every push. It checks the import
layers and the other structural contracts, and it takes about a minute and a half with two workers.

```bash
python -m pytest tests/unit/architecture -q -n 2
```

If it fails on an import, read {doc}`architecture/how-to/fix-an-architecture-gate`.

## 3. Run the tests of the area you touch

Name the folder, not the suite. For a change in `hydromodpy/physics/`:

```bash
python -m pytest tests/unit/physics -q -n 2
```

Do not run the whole suite locally: CI does. Before you run tests in parallel,
read the rules in {ref}`run-the-tests`.

## 4. Lint what you changed

```bash
ruff check --fix path/to/file.py
ruff format path/to/file.py
```

The `pre-commit` hook runs the same two commands, then `gitleaks` (secrets),
`doc8` (`.rst` pages), and a few hygiene checks. It runs on staged files only.

## 5. Commit

Stage the files you mean by name, then write one line:

```bash
git add hydromodpy/physics/flow/flow_config.py tests/unit/physics/test_flow_regime.py
git commit -m "feat(flow): add an aquifer anisotropy ratio"
```

The subject is a Conventional Commits line in the imperative, 72 characters at
most with the prefix, and no body. The allowed types are `feat`, `fix`,
`refactor`, `cleanup`, `perf`, `chore`, `docs`, `tests`, `validation`,
`examples`, `pipeline`, `config`, `adapters`, `data` and `style`. The scope is
the area you touched, in one lowercase word. The reason for a change goes in
the code, the tests or `CHANGELOG.md`, not in the commit message.

## Where next

- Add something: pick a recipe in {doc}`architecture/how-to/index`.
- Understand the code first: {doc}`architecture/mental-model`.
- Change a page of this site: {doc}`documentation/index`.
