# core/runtime

This folder answers: how does the running process behave? It declares the environment variables,
turns a termination signal into an exception, and lets a layer start the root bootstrap without importing it.

## Modules, in the order a caller uses them

1. `env.py` lists every `HMP_*` variable in one table (`ENV_VARS`, `EnvVar`, `env_var`) with its scope. It declares them and reads none.
2. `interrupts.py` makes SIGTERM raise like SIGINT (`terminate_as_interrupt`, `TerminationRequested`), so a long run closes its session in a `finally`.
3. `bootstrap_hook.py` holds the lazy trigger: the root `_bootstrap` stores its callable with `set_bootstrap_hook`, and a layer calls `ensure_bootstrapped`.

## What other layers import from it

`calibration`, `results`, `config`, `cli` and the root `_bootstrap.py`.

## Where to add what

- A new `HMP_*` variable: one entry in `env.py`.
- A new signal rule: `interrupts.py`.
- Anything that needs a higher layer: through the hook, not through an import.

The layer rules are checked by `tests/unit/architecture/`.
