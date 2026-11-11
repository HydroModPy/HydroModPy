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
| `conventions.py` | the shared argparse grammar: `workspace_parser`, `confirm_parser`, `dry_run_parser`, `format_parser`, `verbosity_parser`, `profile_parser`, `add_destination`, `add_sim_ref`, `add_action_subparsers`, and `OLD_CLI_FORMS`, the forms that moved, among them the refused forms of the old developer verb, each with the `python -m tools.dev` command that replaces it |
| `output.py` | what a program reads: `OUTPUTS` declares what each verb writes under `--format json` and `csv`, and `emit` is the only function that writes it |
| `helpers.py` | the typed exit codes, `EXIT_CODE_OF` (the code of each `Category`), `exit_code_for(exc)`, `fail(exc)` and `refuse(message, code)`, which print the `HMPY.Exxx` of a failure, plus the helpers that several verbs share (verbosity, `resolve_workspace` / `resolve_project` / `project_root_of`, profiling, `add_override_arguments` for `--set` and `--overlay`, `toml_target` and `profile_output_of`). The lookups they build on, `find_workspace` and its two siblings, live in `core/workspace/resolve.py` because a library may not import `cli` |
| `environment.py` | the three options `--credentials`, `--allow-host` and `--max-download-bytes`: `add_environment_arguments(parser)` registers them on the six commands, `environment_from_args(args)` builds the `Environment`, and `environment_flags_of(args)` serializes them onto the command line of a launched case |
| `auth.py` | who acts? `AuthBackend` names the local user for the privacy certificate and the notes of `catalog note`, and allows every read and write |
| `banner.py` | the banner `hmp run` prints |

## Verbs

Twenty-three top-level commands, in `ALL_COMMANDS` order. `hmp <verb> --help` prints the
options of each one, and the CLI reference of the documentation is generated
from the same parsers.

| verb | role |
|---|---|
| `workspace` | workspace lifecycle: `init`, `list` (the sealed runs found by walking the tree, no index), `clean` (`--results` moves every run and session to the trash of its project) |
| `project` | a project and its plan: `new`, `plan`, `log`, `delete`, `list`, `import` |
| `campaign` | a project of many cases, and what a calibration found: `array`, `case`, `collect`, `promote` (a trial of a session to `runs/`), `prune` (the kept trials but the best to the trash) |
| `example` | the shipped examples: `list`, `show`, `add` |
| `catalog` | the maintenance of the index and of the runs: `query`, `gc`, `reindex`, `delete`, `restore`, `trash`, `tag`, `note`, `rename`, `watch`, `import`, `rerun` |
| `ls` | the runs of a project from the index (`--site`, `--label`, `--best METRIC`, `--by site`), or from the directories (`--disk`), or where its plan stands (`--plan`) |
| `show` | one thing of a run, a session or a project: the summary, `--profile`, `--point`, `--rank METRIC`, `--figure NAME`, `--report`, `--table NAME` |
| `diff` | what differs between two runs, or with `--to DIR` a folder that compares sealed runs of one site |
| `check` | check a TOML file, every fault at once (`--partial`, `--inputs`) |
| `data` | the input cache: `ls`, `get`, `remove`, `prune`, `lock` (write `hydromodpy.lock`, or `--check [--strict]` to compare the files with it), `archive`, `restore` |
| `export` | write data of one run to files under `runs/<run>/exports/` (fields, series, layers, budget, or the whole run), and write again what its ledgers record (`--regen`) |
| `publish` | copy a run, the summary or the project out of the tree (directory or tar), with `PUBLICATION.json`; `--package` writes the project with its data, which `hmp project import` installs |
| `config` | `template`, `figures` (the figure names `[display].figures` accepts), `resolve`, `schema`, `targets`, `wizard` |
| `completion` | a shell completion script |
| `privacy` | `purge` a run for good (its name stays taken) with a certificate, and `verify` that certificate |
| `run` | execute the workflow a TOML file or a JSON run request names in `[workflow].mode`, or the one its sections imply |
| `replay` | play a sealed run or a published copy again, and class the values it computes |
| `calibrate` | run a calibration workflow from a TOML file or a JSON run request; it writes the session report, `--no-report` skips it |
| `spinup` | cyclic spin-up until heads and lake stage converge |
| `stop` | ask a running run or calibration session to stop, by its flag `.hmp/stop.json` |
| `site` | the sites of a workspace (`data/sites/catalog.csv`): `add`, `import`, `ls`, `show` |
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
`catalog`, `data`, `site`). Its `__init__.py` carries `NAME`, `HELP` and an
`ACTIONS` tuple, and every action module repeats the same four symbols. The
group is attached with `add_action_subparsers`, so a bare `hmp catalog` is a
usage error and exits 2. `config` and `privacy` are single modules
that declare their own sub-commands.

## The workspace a verb reads

Every verb takes `-w/--workspace` (`workspace_parser`), which names a workspace
root or a project directory, after the verb or before it: `hmp -w W ls`.
A verb that reads no workspace accepts it and says so in its help, so that a
script can always write it. Without it the verb uses `HMP_WORKSPACE`, then the workspace or project that
holds the current directory, and stops with exit code 10 when it finds none,
naming `-w`. No verb falls back on `~/hydromodpy`; `hmp workspace init` alone
creates it when no path is given.

`hmp run`, `calibrate` and `spinup` also read their relative paths from a base, and `-w` gives it when
it names a project. `hmp run --base DIR` gives it too and wins over `-w`. No environment variable
carries the base, so a sub-process receives `-w` on its command line.

## A command calls a verb

A command parses its arguments, calls one verb of `hydromodpy.project.api` inside `run(args)`,
formats the result and maps errors to exit codes. It never writes `import hydromodpy as hmp`.
The table is the only correspondence between the two.

| command | verb | what the command adds |
|---|---|---|
| `run`, `calibrate`, `spinup`, `replay`, `stop`, `export`, `publish`, `doctor`, `check` | the same name | the options of the command line, the recap, the exit code |
| `ls` | `status` | `--plan` and `--disk`; the filters of the index read `results.catalog` |
| `show` | `show` | one selector per value of `what`: `--profile`, `--point`, `--rank`, `--figure`, `--report`, `--table` |
| `diff` | `compare` | two runs print their deltas from the index; `--to`, `--by` or `--variables` write the folder |
| `example list`, `show`, `add` | `example` | `add` installs, the other two read the catalog |
| `catalog trash`, `catalog restore` | `trash` | `restore` brings an entry back, a bare `trash` lists |

A command that leaves the first level has a refusal in `OLD_CLI_FORMS` (2.1.0): `catalog ls`,
`show`, `diff`, `point` and `rank`, `viz show` and `list`, `report render`, `catchment` and
`compare`, `config check`, `project status` and `show`. It exits 2 and names the command that replaces it.

## The boundary

- `commands/*.py` parse arguments, call `hydromodpy.project.api` or the package the
  verb serves (`results.catalog`, `data.request`, `display`, `project.data_cache`),
  format the output and map errors to exit codes.
- Reusable behavior belongs in `hydromodpy.project.api` or in its domain package, and
  the command module calls it. Business logic never lives in `cli/`.
- `hmp run` calls the verb `run` for a simulation and an overview, and `dispatch_workflow`
  of `hydromodpy/project/dispatch/workflow.py` for a calibration (`commands/run.py`).
  `fill_trial_pipeline` stays in `main.py`, because `campaign`, `catalog rerun` and the
  `[sites]` launcher read the pipeline without a verb.
- `cli` is a leaf consumer. Only `hydromodpy/__main__.py` may import it, and
  `tests/unit/architecture/test_cli_boundary.py` checks it.

## What a program reads

`--format table|json|csv` is on every verb but the ones that print a document
(`config template`, `resolve`, `schema`, `wizard`, `completion`). Under `json`
stdout holds one object, `{"schema": "hmp.ls.v1", "data": ...}`, and
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
An exception says its `Category` once, on its class (`core/exceptions.py`), and
`EXIT_CODE_OF` in `helpers.py` gives the code of the category. `exit_code_for(exc)`
reads the category of a `HydroModPyError`, the code of the cause of a `StepError`,
and maps a `FileNotFoundError` or a `FileExistsError` raised outside our classes to
10 and 12. A new exception takes the code of its category and touches no table.
`0` is success, `1` a generic error, `2` a usage error (a refused confirmation
without `-y` included), `130` an interruption (SIGINT).

| category | code |
|---|---|
| `generic` | 1 |
| `usage` | 2 |
| `not_found` | 10 |
| `schema_mismatch` | 11 |
| `write_conflict` | 12 |
| `read_only` | 13 |
| `config` | 14 |
| `solver` | 15 |
| `data` | 16 |
| `cross_projects` | 17 |
| `backup_failed` | 18 |
| `migration_failed` | 19 |
| `ambiguous_reference` | 20 |
| `calibration` | 21 |
| `catalog_unreadable` | 22 |
| `cases_failed` | 23 |

The list with the exception behind each code is the exit-codes page of the CLI
reference, and `tests/unit/architecture/surface/exit_codes.tsv` holds it.

## How a run starts

```
hmp run config.toml                      hmp run request.json --base /project
  -> commands/run.py: request_of builds the RunRequest, --set, --overlay and --case join it
     (a .json file is the request itself, and --overlay is refused with it)
  -> project.api.run(request, base=, environment=)
       the workflow is the declared [workflow].mode, or the one the sections imply
  -> run_simulation: load, check_name, claim, request.json and config.toml, inputs,
     request_id, restart or skip, then the pipeline
```

`request_of` is the one place that reads a TOML file, a JSON request, a dict or a built
configuration for a run, and it refuses the combinations of options a workflow cannot honour with
the sentences of `hmp run`. The environment (credentials, allowed hosts, download limit) is built
from the options of the command line and is never written into the request.

A run identical to a completed one is not computed again. `hmp run` and `hmp calibrate` give back the
completed run and name it, and `--force` computes anyway. A resume, a partial window and a replay
never skip.

Docker holds the same program. `docker run <image> run /project/request.json --base /project` plays
a request found in a mounted project folder.

An exception that leaves the handler goes to `helpers.fail` in `main.py`, which
prints its code and its message on stderr and exits with the code of its class.

## Where to add what

1. A leaf verb is a module in `commands/` with `NAME`, `HELP`, `register` and
   `run`, and its name in the import list and in `ALL_COMMANDS` of
   `commands/__init__.py`.
2. An action of a family is a module in the family sub-package with the same
   four symbols, listed in the `ACTIONS` tuple of its `__init__.py`.
3. A shared option is a parser in `conventions.py`, passed through `parents=`.
   A new verb declares what it writes in `OUTPUTS` of `output.py`. A form that
   moved gets its line in `OLD_CLI_FORMS`.
4. Work behind a command is a function in the package it serves, never in
   `cli/`. Work that a Python user needs too is a verb of `hydromodpy.project.api` first,
   and the command calls it.
5. An exit code is a `Category` on the exception class. A new category is a value of
   `Category` and a line of `EXIT_CODE_OF`.

`tests/unit/cli/test_cli_help.py` walks `ALL_COMMANDS` and checks the help of
each verb. `tests/unit/cli/test_cli_surface_matches_the_target.py` holds the
list of verbs and actions the CLI must expose and the ones it must not: a verb
added or removed is a line there. `tests/unit/cli/test_machine_output.py` walks
the tree for the grammar and the envelope.

## Import rules

`cli` sits above the layer matrix (`tests/unit/architecture/layer_matrix.yaml`):
it may import `<root>`, `core`, `schema`, `config`, `data`, `solver`,
`calibration`, `results`, `display`, `workflow` and `project`.
Nothing imports it except the entry point `hydromodpy/__main__.py`.

## Reading path

1. `main.py` for the dispatch loop.
2. `commands/__init__.py` for `ALL_COMMANDS`.
3. `commands/run.py` for the canonical workflow verb.
4. `project/api.py` for the verbs, and `project/dispatch/workflow.py` for the mode to launcher table.
5. A small command such as `commands/stop.py`: parse, call the verb, format.
