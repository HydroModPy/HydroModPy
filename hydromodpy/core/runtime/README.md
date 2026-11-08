# core/runtime

This folder answers: how does the running process behave? It declares the environment variables, and
turns a termination signal into an exception.

## Modules, in the order a caller uses them

1. `env.py` lists every `HMP_*` variable in one table (`ENV_VARS`, `EnvVar`, `env_var`) with its scope. It declares them and reads none.
2. `interrupts.py` makes SIGTERM raise like SIGINT (`terminate_as_interrupt`, `TerminationRequested`), so a long run closes its session in a `finally`.

## What other layers import from it

`calibration`, `results`, `workflow` and `cli`.

## Where to add what

- A new `HMP_*` variable: one entry in `env.py`.
- A new signal rule: `interrupts.py`.

A module of `core` never needs a higher layer: it receives what it needs as an argument.

The layer rules are checked by `tests/unit/architecture/`.
