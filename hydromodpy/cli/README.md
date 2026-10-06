# `hydromodpy/cli`

The command line: the `hmp` and `hydromodpy` entry points. It parses arguments,
calls the code that does the work, formats the output and turns an exception
into a typed exit code. It holds no scientific logic. This file is the map of
the package: its parts, the verbs, the contract of a verb, the boundary with the
rest of the code, and where to add what.

## Parts

| part | answers |
|---|---|
| `main.py` | how is the argparse tree built, and how does a parsed namespace reach its handler? It builds the tree from `ALL_COMMANDS`, runs the handler `args._handler`, and maps any exception through `exit_code_for`. It also turns SIGTERM into an exception for the whole process |
| `commands/` | one module per leaf verb, one sub-package per verb family. `commands/__init__.py` holds `ALL_COMMANDS`, the registration order |
| `_conventions.py` | the shared argparse grammar: `workspace_parser`, `confirm_parser`, `format_parser`, `verbosity_parser`, `profile_parser`, `add_sim_ref`, `add_action_subparsers` |
| `helpers.py` | the typed exit codes and `exit_code_for(exc)`, plus the helpers that several verbs share (verbosity, workspace and project lookup, profiling, the scratch folder of the test tiers) |
| `_workers/` | the application services of the verbs whose reusable Python surface is not part of `hydromodpy._api`: catalog listings, audit display, privacy purge, developer reports. A worker may assemble diagnostics; it must not become a hidden scientific workflow |
| `banner.py` | the banner `hmp run` prints |

## Verbs

Twenty top-level verbs, in `ALL_COMMANDS` order. `hmp <verb> --help` prints the
options of each one, and the CLI reference of the documentation is generated
from the same parsers.

| verb | role |
|---|---|
| `workspace` | workspace lifecycle and registration in the global index: `init`, `list`, `register`, `search`, `forget`, `prune`, `clean` |
| `project` | projects inside a workspace: `new`, `list`, `show`, `delete` |
| `example` | the shipped examples: `list`, `show`, `add` |
| `catalog` | the run lifecycle: `ls`, `query`, `show`, `point`, `gc`, `reindex`, `delete`, `restore`, `trash`, `tag`, `note`, `rename`, `diff`, `watch`, `import`, `rerun` |
| `data` | the input cache and `.hmp` package exchange: `ls`, `get`, `check`, `add`, `remove`, `prune`, `archive`, `restore`, `import` |
| `export` | write data of one run to files (fields, series, layers, budget, or the whole run) |
| `viz` | figures: `list`, `show`, `gallery` |
| `config` | `template`, `check`, `schema`, `targets`, `wizard` |
| `dev` | developer-only: `run-script`, `completion`, `schema`, `examples`, `lock`, `rank`, `manage` |
| `audit` | `list` and `verify` on the hash-chained audit log |
| `privacy` | `purge` a simulation with a certificate, and `verify` that certificate |
| `process` | run a capability as an external process, in one job directory: `list`, `describe`, `run`, `chain`, `verify` |
| `run` | execute the workflow a TOML names in `[workflow].mode` |
| `calibrate` | run a calibration workflow from a TOML |
| `spinup` | cyclic spin-up until heads and lake stage converge |
| `site-selection` | `plan`, `select-catchments`, `build-observed`, `build-generated`, `report` |
| `test` | run the `unit`, `regression` or `validation` tier |
| `report` | `render` a calibration report, `compare` two runs, build a `catchment` report |
| `doctor` | diagnose Python, dependencies, solver binaries and the workspace |
| `install-binaries` | download the MODFLOW, MODPATH and MT3D-USGS binaries |

## Contract of a verb

A leaf module under `commands/` exposes four symbols:

```python
NAME: str = "myverb"
HELP: str = "One-line description."


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    ...
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None: ...
```

`main.py` calls `register` on each module of `ALL_COMMANDS`, parses, then calls
`args._handler(args)`.

A verb family is a sub-package (`workspace`, `project`, `example`, `catalog`,
`data`, `viz`, `dev`, `process`). Its `__init__.py` carries `NAME`, `HELP` and an
`ACTIONS` tuple, and every action module repeats the same four symbols. The
group is attached with `add_action_subparsers`, so a bare `hmp catalog` is a
usage error and exits 2. `config`, `audit`, `privacy`, `report` and
`site-selection` are single modules that declare their own sub-commands.

## The boundary

- `commands/*.py` parse arguments, call `hydromodpy._api`, another package or a
  worker of `_workers/`, format the output and map errors to exit codes.
- Reusable behaviour belongs in `hydromodpy._api` or in its domain package, and
  the command module calls it. Business logic never lives in `cli/`.
- The `[workflow].mode` dispatch is not here. `hmp run` calls `dispatch_workflow`
  of `hydromodpy/project/dispatch/workflow.py` (`commands/run.py`), the same
  adapter table `hmp.run` reaches, and the table maps each mode to its launcher.
- `cli` is a leaf consumer. Only `hydromodpy/__main__.py` may import it, and
  `tests/unit/architecture/test_cli_boundary.py` checks it.

## Exit codes

`helpers.py` defines them and `exit_code_for` maps an exception class to one.
`0` is success, `1` a generic error, `2` a usage error, `10` to `22` the typed
categories (not found, schema mismatch, write conflict, read-only, configuration,
solver, validation, cross-project, backup failed, migration failed, ambiguous
reference, calibration, unreadable catalog), `130` an interruption (SIGINT).
The list with the exception behind each code is the exit-codes page of the CLI
reference.

## How a run starts

```
hmp run config.toml
  -> commands/run.py: apply overrides, resolve verbosity, read [workflow].mode
  -> project/dispatch/workflow.dispatch_workflow(mode, path)
  -> the launcher of that mode (simulation, overview, calibration, comparison,
     testbed, site_selection)
```

An exception that leaves the handler goes to `exit_code_for` in `main.py`, which
prints its message on stderr and exits with the matching code.

## Where to add what

1. **A leaf verb.** A module in `commands/` with `NAME`, `HELP`, `register` and
   `run`, and its name in the import list and in `ALL_COMMANDS` of
   `commands/__init__.py`.
2. **An action of a family.** A module in the family sub-package with the same
   four symbols, listed in the `ACTIONS` tuple of its `__init__.py`.
3. **A shared option.** A parser in `_conventions.py`, passed through `parents=`.
4. **Work only the CLI needs.** A function in `_workers/`. Work that a Python
   user needs too goes in `hydromodpy._api` or its domain package first.
5. **An exit code.** A constant and an entry in the mapping of `helpers.py`.

`tests/unit/cli/test_cli_help.py` walks `ALL_COMMANDS` and checks the help of
each verb.

## Import rules

`cli` sits above the layer matrix (`tests/unit/architecture/layer_matrix.yaml`):
it may import every layer, `catalog`, `project` and `examples`. Nothing imports
it except the entry point `hydromodpy/__main__.py`.

## Reading path

1. `main.py` for the dispatch loop.
2. `commands/__init__.py` for `ALL_COMMANDS`.
3. `commands/run.py` for the canonical workflow verb.
4. `project/dispatch/workflow.py` for the mode to launcher table.
5. A small verb such as `commands/catalog/point.py`: parse, call a worker,
   format, map errors.
