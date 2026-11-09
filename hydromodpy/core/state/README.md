# core/state

This folder answers: where do things live on disk, and what does a run carry between its steps? It
holds the path rules of a project and the runtime objects the launcher and the workflow pass along.

## Modules, in the order a caller uses them

1. `layout.py` is the layout of a project: the names of `.hmp/`, `runs/`, `sessions/`, `jobs/`, `trash/` and the rest, the `*_dir_for` helpers, and the project and workspace roots.
2. `result_dirs.py` spells and reads the relative directory of a run, a session or a kept trial (`parse_rel_dir`), tells a sealed run, and anchors a project (`resolve_project_root`).
3. `scratch.py` is the scratch folder of a live run (`run_scratch`, `sweep_dead_run_scratch`, `preprocessing_dir`).
4. `portable.py` has the cache and state folders (`cache_dir`, `state_dir`), the workspace-relative path encoding and the root URI.
5. `run_state.py` has the mutable state of a run: `SetupContext` (built once), `LoadedDataContext` (support data), `ExecutionRegistry` and `WorkflowContext`.
6. `rng.py` is `RngManager`, which derives one deterministic seed per consumer from a single master seed.
7. `names.py` is the rule of a project name and of a run name, written once. A name holds `[a-z0-9_-]`, at most 40 characters without the `.vN` of a run version, and is not a device name Windows reserves (`con`, `prn`, `aux`, `nul`, `com1` to `com9`, `lpt1` to `lpt9`). `check_name(name, what=)` returns a name that follows the rule or raises a `ConfigError` (exit code 14) with a sentence that proposes the folded name. It refuses a long name, because a cut would put two names with one prefix in one folder. `fold_name(text)` folds a text the code made (a case of a plan, a file stem) into the letters of a name, and the caller passes the result through `check_name`. A person's name is checked when a project is created, when a run takes its folder, and when a case is renamed.

The data overview state is not here: it is `DataOverviewState` in `core/contracts/overview.py`.

## What other layers import from it

Almost all of them: `cli`, `results`, `workflow`, `project`, `data`, `calibration` and `display`. `hydromodpy.core` exposes the four contexts lazily.

## Where to add what

- A new folder name under a project: `layout.py`, with its `*_dir_for` helper.
- A new thing a step must hand to the next: a field of the matching context in `run_state.py`.
- A new random consumer: ask `RngManager` for its seed, never seed globally.

The layer rules are checked by `tests/unit/architecture/`.
