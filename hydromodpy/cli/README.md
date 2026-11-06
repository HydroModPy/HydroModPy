# `hydromodpy/cli`

The command line: the `hmp` and `hydromodpy` entry points. It parses arguments,
calls the code that does the work, formats the output and turns an exception
into a typed exit code. It holds no scientific logic. This file is the map of
the package: its parts, the verbs, the contract of a verb, the boundary with the
rest of the code, and where to add what.

## Parts

| part | answers |
|---|---|
| `main.py` | how is the argparse tree built, and how does a parsed namespace reach its handler? It builds the tree from `ALL_COMMANDS`, sets the console verbosity of `-q`, `-v` or `--debug`, runs the handler `args._handler`, and maps any exception through `exit_code_for`. It also turns SIGTERM into an exception for the whole process |
| `commands/` | one module per leaf verb, one sub-package per verb family. `commands/__init__.py` holds `ALL_COMMANDS`, the registration order |
| `conventions.py` | the shared argparse grammar: `workspace_parser`, `confirm_parser`, `dry_run_parser`, `format_parser`, `verbosity_parser`, `profile_parser`, `add_destination`, `add_sim_ref`, `add_action_subparsers`, and `OLD_CLI_FORMS`, the forms that moved |
| `output.py` | what a program reads: `OUTPUTS` declares what each verb writes under `--format json` and `csv`, and `emit` is the only function that writes it |
| `helpers.py` | the typed exit codes and `exit_code_for(exc)`, `fail(exc)` and `refuse(message, code)`, which print the `HMPY.Exxx` of a failure, plus the helpers that several verbs share (verbosity, `find_workspace` / `resolve_workspace` / `resolve_project` / `project_root_of`, profiling) |
| `effective_toml.py` | what a TOML verb (`run`, `calibrate`, `spinup`) runs: the copy `--set` and `--overlay` write beside the file, the file a verb was given (`toml_target`), and where `--profile` writes its report |
| `_workers/` | the application services of the verbs whose reusable Python surface is not part of `hydromodpy._api`: catalog listings and ranks, the lockfile, the data cache, privacy purge. A worker may assemble diagnostics; it must not become a hidden scientific workflow. Its `README.md` lists them |
| `auth.py` | who acts? `AuthBackend` names the local user for the privacy certificate and the notes of `catalog note`, and allows every read and write |
| `banner.py` | the banner `hmp run` prints |

## Verbs

Twenty-one top-level verbs, in `ALL_COMMANDS` order. `hmp <verb> --help` prints the
options of each one, and the CLI reference of the documentation is generated
from the same parsers.

| verb | role |
|---|---|
| `workspace` | workspace lifecycle: `init`, `list` (the sealed runs found by walking the tree, no index), `clean` (`--results` moves every run and session to the trash of its project) |
| `project` | a project and its plan: `new`, `plan`, `status`, `log`, `delete`, `show`, `list`, `import` |
| `campaign` | a project of many cases, and what a calibration found: `array`, `case`, `collect`, `promote` (a trial of a session to `runs/`), `prune` (the kept trials but the best to the trash) |
| `example` | the shipped examples: `list`, `show`, `add` |
| `catalog` | the run lifecycle: `ls`, `query`, `show`, `point`, `rank`, `gc`, `reindex`, `delete`, `restore`, `trash`, `tag`, `note`, `rename`, `diff`, `watch`, `import`, `rerun` |
| `data` | the input cache: `ls`, `get`, `check`, `add`, `remove`, `prune`, `archive`, `restore` |
| `export` | write data of one run to files under `runs/<run>/exports/` (fields, series, layers, budget, or the whole run), and write again what its ledgers record (`--regen`) |
| `publish` | copy a run, the summary or the project out of the tree (directory or tar), with `PUBLICATION.json`; `--package` writes the project with its data, which `hmp project import` installs |
| `viz` | figures: `list`, `show` |
| `config` | `template`, `check`, `resolve`, `schema`, `targets`, `validate-field`, `wizard` |
| `lock` | the lockfile of a project: `update`, `verify` |
| `completion` | a shell completion script |
| `dev` | developer-only, out of the contract: `run-script`, `examples`, `manage`, `test` |
| `privacy` | `purge` a run for good (its name stays taken) with a certificate, and `verify` that certificate |
| `run` | execute the workflow a TOML names in `[workflow].mode`, or the one its sections imply |
| `calibrate` | run a calibration workflow from a TOML |
| `spinup` | cyclic spin-up until heads and lake stage converge |
| `site` | the sites of a workspace (`data/sites/catalog.csv`): `add`, `import`, `ls`, `show` |
| `report` | `render` a calibration report, `compare` sealed runs of one case, build a `catchment` report |
| `doctor` | diagnose Python, dependencies, solver binaries and the workspace; it reads and reports, it rewrites no file |
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

A verb family is a sub-package (`workspace`, `project`, `campaign`, `example`,
`catalog`, `data`, `viz`, `lock`, `dev`, `site`). Its `__init__.py` carries `NAME`, `HELP` and an
`ACTIONS` tuple, and every action module repeats the same four symbols. The
group is attached with `add_action_subparsers`, so a bare `hmp catalog` is a
usage error and exits 2. `config`, `privacy` and `report` are single modules
that declare their own sub-commands.

## The workspace a verb reads

Every verb takes `-w/--workspace` (`workspace_parser`), which names a workspace
root or a project directory, after the verb or before it: `hmp -w W catalog ls`.
A verb that reads no workspace accepts it and says so in its help, so that a
script can always write it. Without it the verb uses `HMP_WORKSPACE`, then the workspace or project that
holds the current directory, and stops with exit code 10 when it finds none,
naming `-w`. No verb falls back on `~/hydromodpy`; `hmp workspace init` alone
creates it when no path is given.

## The boundary

- `commands/*.py` parse arguments, call `hydromodpy._api`, another package or a
  worker of `_workers/`, format the output and map errors to exit codes.
- Reusable behavior belongs in `hydromodpy._api` or in its domain package, and
  the command module calls it. Business logic never lives in `cli/`.
- The workflow dispatch is not here. `hmp run` calls `dispatch_workflow`
  of `hydromodpy/project/dispatch/workflow.py` (`commands/run.py`), the same
  adapter table `hmp.run` reaches, and the table maps each mode to its launcher.
- `cli` is a leaf consumer. Only `hydromodpy/__main__.py` may import it, and
  `tests/unit/architecture/test_cli_boundary.py` checks it.

## What a program reads

`--format table|json|csv` is on every verb but the ones that print a document
(`config template`, `resolve`, `schema`, `wizard`, `completion`). Under `json`
stdout holds one object, `{"schema": "hmp.catalog.ls.v1", "data": ...}`, and
nothing else: `main.py` points stdout at stderr while the verb works, down to
the file descriptor, and `output.emit` writes the result once it is over. The
page `reference/cli/machine-output` is generated from `OUTPUTS`.

## The words of the grammar

A destination is `--to`, a preview is `--dry-run`, a verb that removes something
takes `-y`, a name is `--name`. The file format of `export` is `--as` and the
container of `publish` is `--container`. `--force` has one meaning: go past a
refusal the verb makes because of what is already there or what protects it (an
existing file, a pinned run, a running case). It never skips a question.

## Exit codes

A failure prints one line on stderr that starts with its `HMPY.Exxx` code.
`helpers.py` defines them and `exit_code_for` maps an exception class to one.
`0` is success, `1` a generic error, `2` a usage error (a refused confirmation
without `-y` included), `10` to `23` the typed categories (not found, schema
mismatch, write conflict, read-only, configuration, solver, validation,
cross-project, backup failed, migration failed, ambiguous reference,
calibration, unreadable catalog, cases failed), `130` an interruption (SIGINT).
The list with the exception behind each code is the exit-codes page of the CLI
reference.

## How a run starts

```
hmp run config.toml
  -> commands/run.py: apply overrides, resolve verbosity, resolve the workflow
     (the declared [workflow].mode, or the one the sections imply)
  -> project/dispatch/workflow.dispatch_workflow(mode, path)
  -> the launcher of that mode (simulation, overview, calibration)
```

An exception that leaves the handler goes to `helpers.fail` in `main.py`, which
prints its code and its message on stderr and exits with the code of its class.

## Where to add what

1. **A leaf verb.** A module in `commands/` with `NAME`, `HELP`, `register` and
   `run`, and its name in the import list and in `ALL_COMMANDS` of
   `commands/__init__.py`.
2. **An action of a family.** A module in the family sub-package with the same
   four symbols, listed in the `ACTIONS` tuple of its `__init__.py`.
3. **A shared option.** A parser in `conventions.py`, passed through `parents=`.
   A new verb declares what it writes in `OUTPUTS` of `output.py`. A form that
   moved gets its line in `OLD_CLI_FORMS`.
4. **Work only the CLI needs.** A function in `_workers/`. Work that a Python
   user needs too goes in `hydromodpy._api` or its domain package first.
5. **An exit code.** A constant and an entry in the mapping of `helpers.py`.

`tests/unit/cli/test_cli_help.py` walks `ALL_COMMANDS` and checks the help of
each verb. `tests/unit/cli/test_cli_surface_matches_the_target.py` holds the
list of verbs and actions the CLI must expose and the ones it must not: a verb
added or removed is a line there. `tests/unit/cli/test_machine_output.py` walks
the tree for the grammar and the envelope.

## Import rules

`cli` sits above the layer matrix (`tests/unit/architecture/layer_matrix.yaml`):
it may import `<root>`, `core`, `schema`, `config`, `data`, `simulation`, `solver`,
`calibration`, `results`, `display`, `analysis`, `workflow`, `project` and `examples`.
Nothing imports it except the entry point `hydromodpy/__main__.py`.

## Reading path

1. `main.py` for the dispatch loop.
2. `commands/__init__.py` for `ALL_COMMANDS`.
3. `commands/run.py` for the canonical workflow verb.
4. `project/dispatch/workflow.py` for the mode to launcher table.
5. A small verb such as `commands/catalog/point.py`: parse, call a worker,
   format, map errors.
