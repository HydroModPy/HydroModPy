# core/state

This folder answers: where do things live on disk, and what does a run carry between its steps? It
holds the path rules of a project and the runtime objects the launcher and the workflow pass along.

## Modules, in the order a caller uses them

1. `paths.py` is the layout of a project: `.hmp/` index, `runs/`, sessions, jobs, trash, the scratch folder of a live run (`run_scratch`, `sweep_dead_run_scratch`), the cache and state folders (`cache_dir`, `state_dir`), and the workspace-relative path encoding.
2. `run_state.py` has the mutable state of a run: `SetupContext` (built once), `LoadedDataContext` (support data), `ExecutionRegistry` and `WorkflowContext`.
3. `rng.py` is `RngManager`, which derives one deterministic seed per consumer from a single master seed.

The data overview state is not here: it is `DataOverviewState` in `core/contracts/overview.py`.

## What other layers import from it

Almost all of them: `cli`, `results`, `workflow`, `project`, `data`, `calibration` and `display`. `hydromodpy.core` exposes the four contexts lazily.

## Where to add what

- A new folder name under a project: `paths.py`, with its `*_dir_for` helper.
- A new thing a step must hand to the next: a field of the matching context in `run_state.py`.
- A new random consumer: ask `RngManager` for its seed, never seed globally.

The layer rules are checked by `tests/unit/architecture/`.
